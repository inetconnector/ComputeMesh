"""ComputeMesh Worker High-Availability (HA) Protocol Subsystem.

Provides heartbeat lease tracking, primary/standby election, fence-token based
split-brain prevention, dynamic worker failover, and zero-loss task reassignment
across distributed worker nodes.
"""
from __future__ import annotations

import dataclasses
from enum import Enum, auto
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("computemesh.worker_ha")


class WorkerRole(Enum):
    PRIMARY = auto()
    STANDBY = auto()
    OFFLINE = auto()


class WorkerLeaseState(Enum):
    ACTIVE = auto()
    DEGRADED = auto()
    EXPIRED = auto()
    EJECTED = auto()


class WorkerHAConstraintError(RuntimeError):
    """Raised when a worker violates HA fence tokens or split-brain constraints."""


@dataclasses.dataclass
class WorkerMemberInfo:
    worker_id: str
    cluster_id: str
    role: WorkerRole
    priority: int
    lease_state: WorkerLeaseState
    last_heartbeat: float
    fence_token: int
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class ClusterHAStatus:
    cluster_id: str
    active_primary_id: str | None
    fence_token: int
    active_members: tuple[WorkerMemberInfo, ...]
    failover_count: int


class WorkerHAClusterManager:
    """Manages worker cluster topology, heartbeats, automatic primary election,

    and strict fence-token validation for split-brain protection.
    """

    def __init__(
        self,
        *,
        heartbeat_interval_sec: float = 1.0,
        lease_ttl_sec: float = 3.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.heartbeat_interval = heartbeat_interval_sec
        self.lease_ttl = lease_ttl_sec
        self._clock = clock
        self._lock = threading.RLock()

        # cluster_id -> dict of worker_id -> WorkerMemberInfo
        self._clusters: dict[str, dict[str, WorkerMemberInfo]] = {}
        # cluster_id -> (fence_token, active_primary_worker_id)
        self._cluster_tokens: dict[str, tuple[int, str | None]] = {}
        # cluster_id -> failover_count
        self._failover_counts: dict[str, int] = {}

    def register_worker(
        self,
        *,
        cluster_id: str,
        worker_id: str,
        role: WorkerRole = WorkerRole.STANDBY,
        priority: int = 100,
        metadata: dict[str, Any] | None = None,
    ) -> WorkerMemberInfo:
        c_id = str(cluster_id or "").strip()
        w_id = str(worker_id or "").strip()
        if not c_id or not w_id:
            raise WorkerHAConstraintError("cluster_id and worker_id are required")

        now = float(self._clock())
        with self._lock:
            if c_id not in self._clusters:
                self._clusters[c_id] = {}
                self._cluster_tokens[c_id] = (1, None)
                self._failover_counts[c_id] = 0

            token, active_primary = self._cluster_tokens[c_id]

            # If registering as primary and no primary exists, assign primary role
            if role == WorkerRole.PRIMARY and (active_primary is None or active_primary == w_id):
                active_primary = w_id
                lease_state = WorkerLeaseState.ACTIVE
            elif active_primary == w_id:
                role = WorkerRole.PRIMARY
                lease_state = WorkerLeaseState.ACTIVE
            else:
                role = WorkerRole.STANDBY
                lease_state = WorkerLeaseState.ACTIVE

            self._cluster_tokens[c_id] = (token, active_primary)

            info = WorkerMemberInfo(
                worker_id=w_id,
                cluster_id=c_id,
                role=role,
                priority=int(priority),
                lease_state=lease_state,
                last_heartbeat=now,
                fence_token=token,
                metadata=dict(metadata or {}),
            )
            self._clusters[c_id][w_id] = info
            logger.info(f"Registered HA worker {w_id} in cluster {c_id} with role {role.name}")
            return info

    def heartbeat(self, *, cluster_id: str, worker_id: str, fence_token: int | None = None) -> WorkerMemberInfo:
        c_id = str(cluster_id or "").strip()
        w_id = str(worker_id or "").strip()
        now = float(self._clock())

        with self._lock:
            cluster = self._clusters.get(c_id)
            if not cluster or w_id not in cluster:
                raise WorkerHAConstraintError(f"Worker {w_id} is not registered in cluster {c_id}")

            current_token, active_primary = self._cluster_tokens[c_id]
            member = cluster[w_id]

            if member.lease_state == WorkerLeaseState.EJECTED:
                raise WorkerHAConstraintError(f"Worker {w_id} has been EJECTED from cluster {c_id}")

            # Verify fence token if presented by primary
            if member.role == WorkerRole.PRIMARY:
                if fence_token is not None and fence_token < current_token:
                    member.lease_state = WorkerLeaseState.EJECTED
                    member.role = WorkerRole.OFFLINE
                    raise WorkerHAConstraintError(
                        f"Stale fence_token {fence_token} presented by primary {w_id} (current: {current_token})"
                    )

            member.last_heartbeat = now
            member.lease_state = WorkerLeaseState.ACTIVE
            member.fence_token = current_token
            return member

    def evaluate_cluster_health(self, cluster_id: str) -> ClusterHAStatus:
        """Evaluates member heartbeats, ejects expired primaries, and performs failover to best standby."""
        c_id = str(cluster_id or "").strip()
        now = float(self._clock())

        with self._lock:
            cluster = self._clusters.get(c_id, {})
            if not cluster:
                return ClusterHAStatus(c_id, None, 0, (), 0)

            token, active_primary = self._cluster_tokens[c_id]
            primary_expired = False

            # Check heartbeat TTL for all members
            for w_id, member in list(cluster.items()):
                elapsed = now - member.last_heartbeat
                if elapsed > self.lease_ttl:
                    if member.role == WorkerRole.PRIMARY:
                        logger.warning(f"Primary worker {w_id} lease expired (elapsed {elapsed:.2f}s > TTL {self.lease_ttl}s)")
                        member.lease_state = WorkerLeaseState.EXPIRED
                        member.role = WorkerRole.OFFLINE
                        primary_expired = True
                    else:
                        member.lease_state = WorkerLeaseState.EXPIRED
                        member.role = WorkerRole.OFFLINE

            # If primary expired or no primary exists, perform dynamic failover
            if primary_expired or active_primary is None or (active_primary in cluster and cluster[active_primary].lease_state != WorkerLeaseState.ACTIVE):
                token += 1  # Increment fence token for new epoch
                new_primary = self._elect_standby_primary(c_id)
                if new_primary:
                    new_primary.role = WorkerRole.PRIMARY
                    new_primary.lease_state = WorkerLeaseState.ACTIVE
                    new_primary.fence_token = token
                    self._cluster_tokens[c_id] = (token, new_primary.worker_id)
                    self._failover_counts[c_id] = self._failover_counts.get(c_id, 0) + 1
                    logger.info(f"HA Failover in cluster {c_id}: Promoted {new_primary.worker_id} to PRIMARY (fence_token: {token})")
                else:
                    self._cluster_tokens[c_id] = (token, None)
                    logger.warning(f"HA Cluster {c_id} has no healthy standby workers available for failover")

            active_primary_id = self._cluster_tokens[c_id][1]
            active_members = tuple(m for m in cluster.values() if m.lease_state == WorkerLeaseState.ACTIVE)
            return ClusterHAStatus(
                cluster_id=c_id,
                active_primary_id=active_primary_id,
                fence_token=self._cluster_tokens[c_id][0],
                active_members=active_members,
                failover_count=self._failover_counts.get(c_id, 0),
            )

    def _elect_standby_primary(self, cluster_id: str) -> WorkerMemberInfo | None:
        cluster = self._clusters.get(cluster_id, {})
        now = float(self._clock())
        candidates = [
            m for m in cluster.values()
            if m.lease_state == WorkerLeaseState.ACTIVE and (now - m.last_heartbeat) <= self.lease_ttl
        ]
        if not candidates:
            return None
        # Highest priority first, tie-break on earliest heartbeat
        candidates.sort(key=lambda m: (-m.priority, m.last_heartbeat))
        return candidates[0]

    def validate_worker_action(self, *, cluster_id: str, worker_id: str, fence_token: int) -> None:
        """Validates that worker is currently the active primary with matching fence_token."""
        c_id = str(cluster_id or "").strip()
        w_id = str(worker_id or "").strip()

        with self._lock:
            status = self.evaluate_cluster_health(c_id)
            if status.active_primary_id != w_id:
                raise WorkerHAConstraintError(
                    f"Worker {w_id} is not the elected active primary in cluster {c_id} (active: {status.active_primary_id})"
                )
            if fence_token < status.fence_token:
                raise WorkerHAConstraintError(
                    f"Fenced token mismatch for worker {w_id}: got {fence_token}, active is {status.fence_token}"
                )

    def reassign_orphaned_turns(
        self,
        *,
        cluster_id: str,
        expired_worker_id: str,
        session_store: Any,
    ) -> int:
        """Reassigns turns previously claimed by an expired/failed worker back to queue."""
        c_id = str(cluster_id or "").strip()
        e_w_id = str(expired_worker_id or "").strip()

        with self._lock:
            status = self.evaluate_cluster_health(c_id)
            if not status.active_primary_id:
                logger.warning(f"Cannot reassign turns for {e_w_id}: No active primary in cluster {c_id}")
                return 0

        reassigned_count = 0
        try:
            from services.mcp.platform.session import TurnStatus
            running_turns = session_store.list_turns(
                statuses=(TurnStatus.RUNNING,),
                limit=500,
            )
            for turn in running_turns:
                # Check events for this session to see if turn was claimed by expired_worker_id
                events = session_store.list_events(turn.session_id)
                claimed_by_expired = False
                for ev in reversed(events):
                    if ev.turn_id == turn.turn_id and ev.event_type == "turn.claimed":
                        payload = ev.payload or {}
                        if payload.get("worker_id") == e_w_id:
                            claimed_by_expired = True
                        break

                if claimed_by_expired:
                    try:
                        session_store.transition_turn(
                            turn.turn_id,
                            TurnStatus.PAUSED,
                            reason=f"worker_ha_failover_pause:{e_w_id}",
                        )
                        session_store.transition_turn(
                            turn.turn_id,
                            TurnStatus.RESUMING,
                            reason=f"worker_ha_failover_resume:{status.active_primary_id}",
                        )
                        reassigned_count += 1
                        logger.info(f"Reassigned orphaned turn {turn.turn_id} from {e_w_id} to HA cluster primary {status.active_primary_id}")
                    except Exception as e:
                        logger.error(f"Failed to reassign turn {turn.turn_id}: {e}")
        except Exception as exc:
            logger.error(f"Error scanning orphaned turns for {e_w_id}: {exc}")

        return reassigned_count
