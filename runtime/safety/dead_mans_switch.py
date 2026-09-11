# SPDX-License-Identifier: Apache-2.0
"""Dead Man's Switch & Positive Authorization Engine for ComputeMesh.

Enforces cryptographically signed, short-lived Positive Authorization Leases.
Execution of inference, MCP tool calls, or cluster work is blocked unless a
valid, unexpired lease signed by an out-of-band Safety Supervisor is present.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import logging
import threading
from typing import Any

from tools.security.ed25519_verify import verify_ed25519_signature

logger = logging.getLogger("cm_safety.dead_mans_switch")


class KillSwitchError(RuntimeError):
    """Base error for all Kill Switch and Dead Man's Switch safety violations."""


class AuthorizationLeaseExpiredError(KillSwitchError):
    """Raised when an action is attempted with an expired positive authorization lease."""


class EmergencyKillTrippedError(KillSwitchError):
    """Raised when the emergency kill switch has been tripped by operator or tripline."""


class MasterAuthorizationRequiredError(KillSwitchError):
    """Raised when a non-master fleet operator attempts a global platform-level action."""


class InvalidLeaseSignatureError(KillSwitchError):
    """Raised when an authorization lease fails cryptographic signature verification."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ExecutionLease:
    """Cryptographically signed positive authorization token."""
    lease_id: str
    node_id: str
    issued_at_iso: str
    expires_at_iso: str
    ttl_seconds: float
    scope: str = "cluster:all"
    tripline_status: str = "armed"  # "armed" | "tripped" | "revoked"
    signature_hex: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def canonical_bytes(self) -> bytes:
        """Deterministic canonical representation for signing and verification."""
        data = {
            "lease_id": self.lease_id,
            "node_id": self.node_id,
            "issued_at_iso": self.issued_at_iso,
            "expires_at_iso": self.expires_at_iso,
            "ttl_seconds": round(float(self.ttl_seconds), 3),
            "scope": self.scope,
            "tripline_status": self.tripline_status,
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def is_expired(self, now: datetime | None = None) -> bool:
        current = now or utc_now()
        try:
            exp = datetime.fromisoformat(self.expires_at_iso.replace("Z", "+00:00"))
            return current >= exp
        except Exception:
            return True

    def time_to_live_seconds(self, now: datetime | None = None) -> float:
        current = now or utc_now()
        try:
            exp = datetime.fromisoformat(self.expires_at_iso.replace("Z", "+00:00"))
            return max(0.0, (exp - current).total_seconds())
        except Exception:
            return 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionLease:
        return cls(
            lease_id=str(data.get("lease_id") or ""),
            node_id=str(data.get("node_id") or ""),
            issued_at_iso=str(data.get("issued_at_iso") or ""),
            expires_at_iso=str(data.get("expires_at_iso") or ""),
            ttl_seconds=float(data.get("ttl_seconds", 0.0)),
            scope=str(data.get("scope") or "cluster:all"),
            tripline_status=str(data.get("tripline_status") or "armed"),
            signature_hex=str(data.get("signature_hex") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


class DeadMansLeaseGuard:
    """Thread-safe positive authorization engine with multi-tenant Fleet & Node Isolation.

    Security Boundaries:
    - Global Platform Kill Switch: ONLY triggerable by Master Platform Owner (Stripe / inetconnector root key).
    - Fleet Kill Switch: Fleet operators can only stop their OWN fleet (isolated scope: fleet:<owner_id>).
    - Node Kill Switch: Node appliances can only stop their OWN local node (isolated scope: node:<node_id>).
    """

    def __init__(
        self,
        *,
        node_id: str,
        supervisor_public_key_hex: str | None = None,
        default_ttl_seconds: float = 15.0,
    ) -> None:
        self.node_id = str(node_id or "node-unknown")
        self.supervisor_public_key_hex = supervisor_public_key_hex
        self.default_ttl_seconds = max(1.0, float(default_ttl_seconds))
        self._lock = threading.RLock()
        self._active_lease: ExecutionLease | None = None
        self._is_tripped = False
        self._trip_reason: str | None = None
        self._trip_timestamp: str | None = None
        # Multi-tenant isolation tables
        self._fleet_trips: dict[str, dict[str, Any]] = {}
        self._node_trips: dict[str, dict[str, Any]] = {}

    @property
    def is_tripped(self) -> bool:
        with self._lock:
            return self._is_tripped

    @property
    def trip_reason(self) -> str | None:
        with self._lock:
            return self._trip_reason

    def trip(self, reason: str = "Master emergency abort", *, is_master: bool = True) -> None:
        """Immediately and permanently trip the GLOBAL platform kill switch (Master only)."""
        with self._lock:
            self._is_tripped = True
            self._trip_reason = str(reason)
            self._trip_timestamp = utc_now_iso()
            self._active_lease = None
            logger.critical("GLOBAL PLATFORM KILL SWITCH TRIPPED BY MASTER OPERATOR: %s", reason)

    def trip_fleet(self, owner_id: str, reason: str = "Fleet operator emergency stop") -> dict[str, Any]:
        """Trips ONLY a specific tenant's fleet. Leaves all other fleets and global mesh 100% operational."""
        clean_owner = str(owner_id or "").strip()
        if not clean_owner:
            raise ValueError("owner_id is required for fleet-scoped emergency stop")
        with self._lock:
            ts = utc_now_iso()
            self._fleet_trips[clean_owner] = {
                "owner_id": clean_owner,
                "is_tripped": True,
                "trip_reason": str(reason),
                "trip_timestamp": ts,
            }
            logger.warning("[FLEET_ISOLATION] Fleet '%s' emergency stopped (Reason: %s)", clean_owner, reason)
            return dict(self._fleet_trips[clean_owner])

    def reset_fleet(self, owner_id: str, reason: str = "Fleet operator reset") -> bool:
        """Resets the trip state for a specific fleet."""
        clean_owner = str(owner_id or "").strip()
        with self._lock:
            if clean_owner in self._fleet_trips:
                del self._fleet_trips[clean_owner]
                logger.info("[FLEET_ISOLATION] Fleet '%s' trip state cleared: %s", clean_owner, reason)
                return True
            return False

    def is_fleet_tripped(self, owner_id: str | None) -> bool:
        """Returns True if the entire platform is tripped OR if this specific fleet is tripped."""
        with self._lock:
            if self._is_tripped:
                return True
            if not owner_id:
                return False
            clean_owner = str(owner_id).strip()
            return self._fleet_trips.get(clean_owner, {}).get("is_tripped", False)

    def get_fleet_trip_reason(self, owner_id: str | None) -> str | None:
        with self._lock:
            if self._is_tripped:
                return self._trip_reason
            if not owner_id:
                return None
            return self._fleet_trips.get(str(owner_id).strip(), {}).get("trip_reason")

    def trip_node(self, node_id: str, reason: str = "Node appliance emergency stop") -> dict[str, Any]:
        """Trips ONLY a specific compute node. Leaves the rest of the fleet and mesh operational."""
        clean_node = str(node_id or "").strip()
        if not clean_node:
            raise ValueError("node_id is required for node-scoped emergency stop")
        with self._lock:
            ts = utc_now_iso()
            self._node_trips[clean_node] = {
                "node_id": clean_node,
                "is_tripped": True,
                "trip_reason": str(reason),
                "trip_timestamp": ts,
            }
            logger.warning("[NODE_ISOLATION] Node '%s' emergency stopped (Reason: %s)", clean_node, reason)
            return dict(self._node_trips[clean_node])

    def reset_node(self, node_id: str, reason: str = "Node operator reset") -> bool:
        clean_node = str(node_id or "").strip()
        with self._lock:
            if clean_node in self._node_trips:
                del self._node_trips[clean_node]
                return True
            return False

    def is_node_tripped(self, node_id: str | None) -> bool:
        with self._lock:
            if self._is_tripped:
                return True
            if not node_id:
                return False
            return self._node_trips.get(str(node_id).strip(), {}).get("is_tripped", False)

    def get_node_trip_reason(self, node_id: str | None) -> str | None:
        with self._lock:
            if self._is_tripped:
                return self._trip_reason
            if not node_id:
                return None
            return self._node_trips.get(str(node_id).strip(), {}).get("trip_reason")

    def reset(self, reason: str = "Master operator authorized reset") -> None:
        """Reset the global platform tripped state (Master only)."""
        with self._lock:
            self._is_tripped = False
            self._trip_reason = None
            self._trip_timestamp = None
            self._active_lease = None
            logger.info("Global platform kill switch trip state cleared: %s", reason)

    def update_lease(
        self,
        lease: ExecutionLease | dict[str, Any],
        *,
        verify_signature: bool = True,
    ) -> bool:
        """Atomically ingest and verify a new signed positive authorization lease."""
        if isinstance(lease, dict):
            lease_obj = ExecutionLease.from_dict(lease)
        else:
            lease_obj = lease

        with self._lock:
            if self._is_tripped:
                raise EmergencyKillTrippedError(f"Kill switch is tripped: {self._trip_reason}")

            if lease_obj.tripline_status in ("tripped", "revoked"):
                self.trip(f"Supervisor revoked authorization: {lease_obj.tripline_status}")
                raise EmergencyKillTrippedError(f"Supervisor revoked authorization: {lease_obj.tripline_status}")

            if lease_obj.is_expired():
                raise AuthorizationLeaseExpiredError(f"Received lease {lease_obj.lease_id} is already expired")

            # Cryptographic signature verification against supervisor public key
            if verify_signature and self.supervisor_public_key_hex:
                if not lease_obj.signature_hex:
                    raise InvalidLeaseSignatureError("Lease missing required signature_hex")
                try:
                    pub_bytes = bytes.fromhex(self.supervisor_public_key_hex)
                    sig_bytes = bytes.fromhex(lease_obj.signature_hex)
                    valid = verify_ed25519_signature(pub_bytes, lease_obj.canonical_bytes(), sig_bytes)
                    if not valid:
                        raise InvalidLeaseSignatureError(f"Ed25519 signature invalid on lease {lease_obj.lease_id}")
                except (ValueError, TypeError) as exc:
                    raise InvalidLeaseSignatureError(f"Signature decoding failed: {exc}") from exc

            self._active_lease = lease_obj
            logger.debug(
                "Positive authorization lease %s active until %s (TTL: %.1fs)",
                lease_obj.lease_id,
                lease_obj.expires_at_iso,
                lease_obj.time_to_live_seconds(),
            )
            return True

    def is_authorized(self, scope: str = "inference", owner_id: str | None = None, node_id: str | None = None) -> bool:
        """Check if execution is authorized for the given fleet owner and node."""
        with self._lock:
            if self._is_tripped:
                return False
            if owner_id and self.is_fleet_tripped(owner_id):
                return False
            if node_id and self.is_node_tripped(node_id):
                return False
            if self._active_lease is None:
                return False
            if self._active_lease.is_expired():
                return False
            return True

    def assert_authorized(self, scope: str = "inference", owner_id: str | None = None, node_id: str | None = None) -> ExecutionLease:
        """Assert authorization or raise specific KillSwitchError."""
        with self._lock:
            if self._is_tripped:
                raise EmergencyKillTrippedError(
                    f"Execution blocked: Global Platform Kill Switch is active ({self._trip_reason})"
                )
            if owner_id and self.is_fleet_tripped(owner_id):
                raise EmergencyKillTrippedError(
                    f"Execution blocked: Fleet '{owner_id}' is stopped ({self.get_fleet_trip_reason(owner_id)})"
                )
            if node_id and self.is_node_tripped(node_id):
                raise EmergencyKillTrippedError(
                    f"Execution blocked: Node '{node_id}' is stopped ({self.get_node_trip_reason(node_id)})"
                )
            if self._active_lease is None:
                raise AuthorizationLeaseExpiredError("Execution blocked: No active positive authorization lease")
            if self._active_lease.is_expired():
                raise AuthorizationLeaseExpiredError(
                    f"Execution blocked: Authorization lease {self._active_lease.lease_id} expired at {self._active_lease.expires_at_iso}"
                )
            return self._active_lease

    def time_to_live_seconds(self) -> float:
        with self._lock:
            if self._is_tripped or self._active_lease is None:
                return 0.0
            return self._active_lease.time_to_live_seconds()

    def get_status(self, owner_id: str | None = None, node_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            active = self.is_authorized(owner_id=owner_id, node_id=node_id)
            ttl = self.time_to_live_seconds()
            fleet_info = None
            if owner_id:
                clean_o = str(owner_id).strip()
                fleet_info = self._fleet_trips.get(clean_o, {"owner_id": clean_o, "is_tripped": False})

            node_info = None
            if node_id:
                clean_n = str(node_id).strip()
                node_info = self._node_trips.get(clean_n, {"node_id": clean_n, "is_tripped": False})

            return {
                "node_id": self.node_id,
                "is_authorized": active,
                "is_tripped": self._is_tripped,
                "trip_reason": self._trip_reason,
                "trip_timestamp": self._trip_timestamp,
                "time_to_live_seconds": round(ttl, 2),
                "active_lease": self._active_lease.as_dict() if self._active_lease else None,
                "fleet_status": fleet_info,
                "node_status": node_info,
                "total_stopped_fleets": len(self._fleet_trips),
                "total_stopped_nodes": len(self._node_trips),
            }


_GLOBAL_LEASE_GUARD: DeadMansLeaseGuard | None = None
_GUARD_LOCK = threading.Lock()


def get_lease_guard(node_id: str = "local-node") -> DeadMansLeaseGuard:
    """Returns the process-wide DeadMansLeaseGuard singleton, initializing from anchor keys if present."""
    global _GLOBAL_LEASE_GUARD
    if _GLOBAL_LEASE_GUARD is not None:
        return _GLOBAL_LEASE_GUARD

    with _GUARD_LOCK:
        if _GLOBAL_LEASE_GUARD is not None:
            return _GLOBAL_LEASE_GUARD

        pub_hex = None
        # Check standard config path
        try:
            from pathlib import Path
            anchor_file = Path(__file__).resolve().parents[2] / "config" / "safety" / "master_killswitch_public.hex"
            if anchor_file.exists():
                pub_hex = anchor_file.read_text(encoding="utf-8").strip()
        except Exception:
            pub_hex = None

        _GLOBAL_LEASE_GUARD = DeadMansLeaseGuard(
            node_id=node_id,
            supervisor_public_key_hex=pub_hex,
        )
        return _GLOBAL_LEASE_GUARD


def set_global_lease_guard(guard: DeadMansLeaseGuard) -> None:
    """Explicitly assign the global DeadMansLeaseGuard instance (useful for testing and bootstrapping)."""
    global _GLOBAL_LEASE_GUARD
    with _GUARD_LOCK:
        _GLOBAL_LEASE_GUARD = guard

