#!/usr/bin/env python3
"""Tests for Worker High-Availability (HA) Protocol Subsystem."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.session import AgentSessionStore, TurnStatus
from services.orchestrator.worker_ha_protocol import (
    WorkerHAClusterManager,
    WorkerHAConstraintError,
    WorkerLeaseState,
    WorkerRole,
)


class TestWorkerHAProtocol(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "agent_sessions.db"
        self.store = AgentSessionStore(self.db_path)
        self.clock_val = 1000.0
        self.mgr = WorkerHAClusterManager(
            heartbeat_interval_sec=1.0,
            lease_ttl_sec=3.0,
            clock=lambda: self.clock_val,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tmp_dir.cleanup()

    def test_worker_registration_and_heartbeat(self) -> None:
        p_info = self.mgr.register_worker(
            cluster_id="cluster-1",
            worker_id="worker-primary-1",
            role=WorkerRole.PRIMARY,
            priority=100,
        )
        self.assertEqual(p_info.role, WorkerRole.PRIMARY)
        self.assertEqual(p_info.lease_state, WorkerLeaseState.ACTIVE)
        self.assertEqual(p_info.fence_token, 1)

        s_info = self.mgr.register_worker(
            cluster_id="cluster-1",
            worker_id="worker-standby-1",
            role=WorkerRole.STANDBY,
            priority=80,
        )
        self.assertEqual(s_info.role, WorkerRole.STANDBY)
        self.assertEqual(s_info.lease_state, WorkerLeaseState.ACTIVE)

        # Heartbeat from primary should succeed
        hb = self.mgr.heartbeat(cluster_id="cluster-1", worker_id="worker-primary-1", fence_token=1)
        self.assertEqual(hb.lease_state, WorkerLeaseState.ACTIVE)

    def test_primary_failover_and_fence_token_increment(self) -> None:
        self.mgr.register_worker(
            cluster_id="cluster-1",
            worker_id="worker-primary-1",
            role=WorkerRole.PRIMARY,
            priority=100,
        )
        self.mgr.register_worker(
            cluster_id="cluster-1",
            worker_id="worker-standby-1",
            role=WorkerRole.STANDBY,
            priority=200,
        )

        status_init = self.mgr.evaluate_cluster_health("cluster-1")
        self.assertEqual(status_init.active_primary_id, "worker-primary-1")
        self.assertEqual(status_init.fence_token, 1)

        # Advance clock past lease TTL (3.0s)
        self.clock_val += 4.0

        # Standby worker heartbeats
        self.mgr.heartbeat(cluster_id="cluster-1", worker_id="worker-standby-1")

        # Primary lease expires, standby should be promoted to primary with fence token 2
        status_after = self.mgr.evaluate_cluster_health("cluster-1")
        self.assertEqual(status_after.active_primary_id, "worker-standby-1")
        self.assertEqual(status_after.fence_token, 2)
        self.assertEqual(status_after.failover_count, 1)

        # Action validation for newly elected primary succeeds
        self.mgr.validate_worker_action(
            cluster_id="cluster-1",
            worker_id="worker-standby-1",
            fence_token=2,
        )

        # Action validation for old primary fails with constraint error
        with self.assertRaises(WorkerHAConstraintError):
            self.mgr.validate_worker_action(
                cluster_id="cluster-1",
                worker_id="worker-primary-1",
                fence_token=1,
            )

    def test_orphaned_turn_reassignment(self) -> None:
        # Register workers
        self.mgr.register_worker(
            cluster_id="cluster-1",
            worker_id="worker-primary-1",
            role=WorkerRole.PRIMARY,
            priority=100,
        )
        self.mgr.register_worker(
            cluster_id="cluster-1",
            worker_id="worker-standby-1",
            role=WorkerRole.STANDBY,
            priority=200,
        )

        # Create session and running turn claimed by worker-primary-1
        sess = self.store.create_session("qwen/qwen2.5-7b-instruct", principal_id="user1")
        turn = self.store.start_turn(sess.session_id, "Orphaned test turn")
        claimed = self.store.claim_turn(turn.turn_id, worker_id="worker-primary-1")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, TurnStatus.RUNNING)

        # Failover primary worker
        self.clock_val += 4.0
        self.mgr.heartbeat(cluster_id="cluster-1", worker_id="worker-standby-1")
        self.mgr.evaluate_cluster_health("cluster-1")

        # Reassign orphaned turns from worker-primary-1
        count = self.mgr.reassign_orphaned_turns(
            cluster_id="cluster-1",
            expired_worker_id="worker-primary-1",
            session_store=self.store,
        )
        self.assertEqual(count, 1)

        reassigned_turn = self.store.get_turn(turn.turn_id)
        self.assertEqual(reassigned_turn.status, TurnStatus.RESUMING)


if __name__ == "__main__":
    unittest.main()
