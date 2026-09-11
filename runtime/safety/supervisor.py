# SPDX-License-Identifier: Apache-2.0
"""Out-of-Band Safety Supervisor for ComputeMesh Nodes & Appliances.

Runs outside the unprivileged AI agent payload:
- Periodically signs & issues Positive Authorization Leases (TTL ≤ 15s) while healthy.
- Executes tree termination (SIGKILL / TerminateProcess) on worker processes.
- Tripline integration: Trips immediately on anomaly or operator emergency signal.
- Hardware Relay integration: Drops power / network on physical appliances.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from typing import Any

from .dead_mans_switch import (
    DeadMansLeaseGuard,
    ExecutionLease,
    utc_now,
    utc_now_iso,
)
from .hardware_relay import HardwareKillRelay, NullHardwareRelay
from .tripline_monitor import TriplineMonitor

logger = logging.getLogger("cm_safety.supervisor")


class SafetySupervisor:
    """Out-of-band safety supervisor daemon controlling unprivileged AI workers."""

    def __init__(
        self,
        *,
        node_id: str,
        guard: DeadMansLeaseGuard,
        master_private_key_bytes: bytes | None = None,
        master_public_key_hex: str | None = None,
        lease_ttl_seconds: float = 15.0,
        renewal_interval_seconds: float = 5.0,
        hardware_relay: HardwareKillRelay | None = None,
        monitored_paths: list[Path | str] | None = None,
    ) -> None:
        self.node_id = str(node_id or "node-unknown")
        self.guard = guard
        self.master_private_key_bytes = master_private_key_bytes
        self.master_public_key_hex = master_public_key_hex or guard.supervisor_public_key_hex
        self.lease_ttl_seconds = max(2.0, float(lease_ttl_seconds))
        self.renewal_interval_seconds = max(0.5, min(float(renewal_interval_seconds), self.lease_ttl_seconds / 2.0))
        self.hardware_relay = hardware_relay or NullHardwareRelay()

        self._lock = threading.RLock()
        self._is_running = False
        self._heartbeat_thread: threading.Thread | None = None
        self._child_processes: list[subprocess.Popen[Any]] = []
        self._tripped = False
        self._trip_reason: str | None = None

        # Initialize Tripline Monitor
        self.tripline_monitor = TriplineMonitor(
            on_breach_callback=self._on_tripline_breach,
            monitored_paths=monitored_paths or [Path(__file__).resolve().parent],
            check_interval_seconds=1.5,
        )

    def _sign_bytes(self, data: bytes) -> str:
        """Sign canonical bytes using master private key if available."""
        if not self.master_private_key_bytes:
            return ""
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            priv = ed25519.Ed25519PrivateKey.from_private_bytes(self.master_private_key_bytes)
            sig = priv.sign(data)
            return sig.hex()
        except Exception as exc:
            logger.error("Failed to sign lease with Ed25519 private key: %s", exc)
            return ""

    def generate_lease(self, scope: str = "cluster:all") -> ExecutionLease:
        """Creates and cryptographically signs a fresh Positive Authorization Lease."""
        now = utc_now()
        exp = now + timedelta(seconds=self.lease_ttl_seconds)
        issued_iso = now.isoformat().replace("+00:00", "Z")
        exp_iso = exp.isoformat().replace("+00:00", "Z")
        lease_id = f"lease-{secrets.token_hex(8)}"

        unsigned_lease = ExecutionLease(
            lease_id=lease_id,
            node_id=self.node_id,
            issued_at_iso=issued_iso,
            expires_at_iso=exp_iso,
            ttl_seconds=self.lease_ttl_seconds,
            scope=scope,
            tripline_status="armed" if not self._tripped else "tripped",
        )

        sig_hex = self._sign_bytes(unsigned_lease.canonical_bytes())
        signed_lease = ExecutionLease(
            lease_id=unsigned_lease.lease_id,
            node_id=unsigned_lease.node_id,
            issued_at_iso=unsigned_lease.issued_at_iso,
            expires_at_iso=unsigned_lease.expires_at_iso,
            ttl_seconds=unsigned_lease.ttl_seconds,
            scope=unsigned_lease.scope,
            tripline_status=unsigned_lease.tripline_status,
            signature_hex=sig_hex,
            metadata={"supervisor": "SafetySupervisor/1.2", "pid": os.getpid()},
        )
        return signed_lease

    def renew_positive_authorization(self) -> bool:
        """Issues and pushes a new authorization lease to the local guard."""
        with self._lock:
            if self._tripped:
                return False
            lease = self.generate_lease()
            try:
                self.guard.update_lease(lease, verify_signature=bool(self.master_public_key_hex))
                return True
            except Exception as exc:
                logger.error("Failed to renew positive authorization: %s", exc)
                return False

    def start(self) -> None:
        """Starts the supervisor heartbeat and tripline monitors."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._tripped = False
            self._trip_reason = None

        # Issue immediate first lease
        self.renew_positive_authorization()
        self.tripline_monitor.start()

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="SupervisorHeartbeat",
        )
        self._heartbeat_thread.start()
        logger.info("SafetySupervisor started for node %s (TTL: %.1fs)", self.node_id, self.lease_ttl_seconds)

    def stop(self) -> None:
        """Stops supervisor and gracefully ceases lease renewals."""
        with self._lock:
            self._is_running = False
        self.tripline_monitor.stop()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)
        logger.info("SafetySupervisor stopped.")

    def _heartbeat_loop(self) -> None:
        while True:
            with self._lock:
                if not self._is_running or self._tripped:
                    break
            self.renew_positive_authorization()
            time.sleep(self.renewal_interval_seconds)

    def register_child_process(self, proc: subprocess.Popen[Any]) -> None:
        """Registers an unprivileged child worker process for supervision."""
        with self._lock:
            self._child_processes.append(proc)

    def _on_tripline_breach(self, tripline_name: str, details: str) -> None:
        """Internal callback invoked when tripline monitor fires."""
        self.emergency_kill(reason=f"Tripline breach: [{tripline_name}] {details}")

    def emergency_kill(self, reason: str = "Operator manual emergency stop") -> None:
        """Executes full multi-tier emergency kill across processes, guard, and hardware."""
        with self._lock:
            self._tripped = True
            self._trip_reason = reason
            self._is_running = False

        logger.critical(">>> EXECUTING EMERGENCY KILL: %s <<<", reason)

        # 1. Trip local dead man's switch guard immediately
        self.guard.trip(reason)

        # 2. Hard process tree termination (SIGKILL / TerminateProcess)
        self.terminate_all_child_processes(reason)

        # 3. Trip hardware power / network relay if equipped
        try:
            self.hardware_relay.trip_hardware(reason)
        except Exception as exc:
            logger.error("Hardware relay trip failed: %s", exc)

        # 4. Stop background tripline loop
        self.tripline_monitor.stop()

    def terminate_all_child_processes(self, reason: str = "KillSwitch") -> int:
        """Kills all registered child worker processes and their descendants."""
        killed_count = 0
        with self._lock:
            procs = list(self._child_processes)
            self._child_processes.clear()

        for proc in procs:
            if proc.poll() is None:
                pid = proc.pid
                logger.warning("Terminating worker process PID %d (%s)...", pid, reason)
                try:
                    if sys.platform == "win32":
                        # Windows hard process tree termination
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=3.0,
                            check=False,
                        )
                    else:
                        # Linux / POSIX process tree termination
                        import signal
                        try:
                            os.killpg(os.getpgid(pid), signal.SIGKILL)
                        except Exception:
                            proc.kill()
                    killed_count += 1
                except Exception as exc:
                    logger.error("Failed to terminate PID %d: %s", pid, exc)
                    try:
                        proc.kill()
                    except Exception:
                        pass
        return killed_count

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "supervisor": "SafetySupervisor/1.2",
                "node_id": self.node_id,
                "is_running": self._is_running,
                "is_tripped": self._tripped,
                "trip_reason": self._trip_reason,
                "lease_ttl_seconds": self.lease_ttl_seconds,
                "renewal_interval_seconds": self.renewal_interval_seconds,
                "supervised_processes_count": len(self._child_processes),
                "guard_status": self.guard.get_status(),
                "tripline_status": self.tripline_monitor.get_status(),
                "hardware_relay": self.hardware_relay.get_status(),
            }
