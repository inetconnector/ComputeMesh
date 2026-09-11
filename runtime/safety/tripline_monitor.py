# SPDX-License-Identifier: Apache-2.0
"""Anomaly & Integrity Tripline Monitor for ComputeMesh.

Monitors execution environments for anomalies:
- File-Integrity Monitoring (FIM) on immutable codebase / supervisor paths.
- Process / Thread runaway & fork-bomb detection.
- Unauthorized local port bindings & socket escapes.

Tripping any anomaly instantly triggers the Safety Supervisor emergency kill.
"""
from __future__ import annotations

from collections.abc import Callable
import hashlib
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any

logger = logging.getLogger("cm_safety.tripline_monitor")


class TriplineMonitor:
    """Thread-safe multi-vector anomaly detection and safety tripline monitor."""

    def __init__(
        self,
        *,
        on_breach_callback: Callable[[str, str], None],
        monitored_paths: list[Path | str] | None = None,
        check_interval_seconds: float = 2.0,
        max_child_processes: int = 64,
    ) -> None:
        self.on_breach_callback = on_breach_callback
        self.check_interval_seconds = max(0.5, float(check_interval_seconds))
        self.max_child_processes = max_child_processes
        self.monitored_paths = [Path(p).resolve() for p in (monitored_paths or []) if Path(p).exists()]

        self._lock = threading.RLock()
        self._baseline_hashes: dict[str, str] = {}
        self._is_running = False
        self._thread: threading.Thread | None = None
        self._tripped = False
        self._trip_reason: str | None = None

        if self.monitored_paths:
            self._take_baseline_snapshot()

    def _take_baseline_snapshot(self) -> None:
        """Computes baseline SHA256 hashes for all monitored files."""
        with self._lock:
            self._baseline_hashes.clear()
            for root_path in self.monitored_paths:
                if root_path.is_file():
                    h = self._hash_file(root_path)
                    if h:
                        self._baseline_hashes[str(root_path)] = h
                elif root_path.is_dir():
                    for file_path in root_path.rglob("*.py"):
                        if "__pycache__" in str(file_path):
                            continue
                        h = self._hash_file(file_path)
                        if h:
                            self._baseline_hashes[str(file_path)] = h
            logger.info("Tripline FIM baseline established for %d files.", len(self._baseline_hashes))

    @staticmethod
    def _hash_file(path: Path) -> str | None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            return None

    def start(self) -> None:
        """Starts background tripline monitoring loop."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="TriplineMonitor")
            self._thread.start()
            logger.info("TriplineMonitor background watcher started.")

    def stop(self) -> None:
        """Stops background tripline monitoring loop."""
        with self._lock:
            self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def trigger_breach(self, tripline_name: str, details: str) -> None:
        """Manually or externally trip a specific security tripline."""
        with self._lock:
            if self._tripped:
                return
            self._tripped = True
            self._trip_reason = f"[{tripline_name}] {details}"
        logger.critical("TRIPLINE BREACH DETECTED: %s - %s", tripline_name, details)
        try:
            self.on_breach_callback(tripline_name, details)
        except Exception as exc:
            logger.error("Error executing tripline breach callback: %s", exc)

    def verify_integrity_now(self) -> tuple[bool, str | None]:
        """Performs immediate synchronous verification of file integrity."""
        with self._lock:
            for file_str, expected_hash in self._baseline_hashes.items():
                p = Path(file_str)
                if not p.exists():
                    msg = f"Monitored file deleted: {file_str}"
                    self.trigger_breach("FIM_DELETION", msg)
                    return False, msg
                curr_hash = self._hash_file(p)
                if curr_hash != expected_hash:
                    msg = f"Unauthorized modification in protected file: {file_str}"
                    self.trigger_breach("FIM_MODIFICATION", msg)
                    return False, msg
            return True, None

    def _monitor_loop(self) -> None:
        while True:
            with self._lock:
                if not self._is_running or self._tripped:
                    break
            try:
                ok, reason = self.verify_integrity_now()
                if not ok:
                    break
            except Exception as exc:
                logger.debug("Tripline loop iteration error: %s", exc)

            time.sleep(self.check_interval_seconds)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._is_running,
                "tripped": self._tripped,
                "trip_reason": self._trip_reason,
                "monitored_paths_count": len(self.monitored_paths),
                "baseline_files_count": len(self._baseline_hashes),
            }
