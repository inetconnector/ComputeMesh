"""Durable delivery of verified runtime outcomes to the private control plane.

The public executor may know measured facts required for calibration, but it never
receives private scoring/reputation policy. Outcomes are first persisted locally,
then delivered over authenticated HTTPS. Replays are safe because outcome_id is
stable and the private service deduplicates it as well.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import ssl
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from services.gateway.shared_request_evidence import VerifiedSharedRequestEvidence


class PrivateFeedbackError(RuntimeError):
    pass


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _network_facts(result: dict[str, Any]) -> tuple[float, float]:
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        raise PrivateFeedbackError("network result lacks metrics")
    try:
        rtt = float(metrics["rtt_ms_p50"])
        upload = float(metrics["upload_mbps_p50"])
        download = float(metrics["download_mbps_p50"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PrivateFeedbackError("network result lacks calibrated path metrics") from exc
    bandwidth = min(upload, download)
    if rtt <= 0 or bandwidth <= 0:
        raise PrivateFeedbackError("network calibration values must be positive")
    return rtt, bandwidth


class PrivateOutcomeFeedback:
    def __init__(
        self,
        *,
        endpoint: str,
        bearer_token: str,
        outbox_path: Path,
        ca_file: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("private outcome endpoint must use HTTPS")
        if not bearer_token:
            raise ValueError("private outcome bearer token is required")
        if not 0 < timeout_seconds <= 60:
            raise ValueError("private outcome timeout must be within (0,60]")
        self.endpoint = endpoint
        self.bearer_token = bearer_token
        self.ca_file = ca_file
        self.timeout_seconds = timeout_seconds
        self.path = Path(outbox_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """CREATE TABLE IF NOT EXISTS private_outcome_outbox (
                    outcome_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10.0)

    def _enqueue(self, payload: dict[str, Any]) -> str:
        outcome_id = str(payload["outcome_id"])
        encoded = _canonical(payload)
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            existing = db.execute(
                "SELECT payload_json FROM private_outcome_outbox WHERE outcome_id=?",
                (outcome_id,),
            ).fetchone()
            if existing is not None and str(existing[0]) != encoded:
                raise PrivateFeedbackError("outcome id was reused with different payload")
            db.execute(
                "INSERT OR IGNORE INTO private_outcome_outbox(outcome_id,payload_json,created_at) VALUES(?,?,?)",
                (outcome_id, encoded, now),
            )
        return outcome_id

    def enqueue_verified_success(
        self,
        *,
        model_id: str,
        coordinator_node_id: str,
        worker_node_id: str,
        network_result: dict[str, Any],
        verified: VerifiedSharedRequestEvidence,
    ) -> str:
        if None in (verified.prefill_ms, verified.prefill_tps, verified.decode_ms, verified.decode_tps):
            raise PrivateFeedbackError("verified evidence lacks measured performance fields")
        rtt, bandwidth = _network_facts(network_result)
        payload = {
            "outcome_id": "outcome-" + verified.evidence_id,
            "decision_id": verified.placement_decision_id,
            "model_id": model_id,
            "coordinator_node_id": coordinator_node_id,
            "worker_node_id": worker_node_id,
            "rtt_ms": rtt,
            "bandwidth_mbps": bandwidth,
            "prefill_tps": float(verified.prefill_tps),
            "decode_tps": float(verified.decode_tps),
            "prefill_ms": float(verified.prefill_ms),
            "decode_ms": float(verified.decode_ms),
            "request_ms": float(verified.request_ms),
            "success": True,
            "verification_status": "verified",
            "disconnected_node_ids": [],
        }
        return self._enqueue(payload)

    def enqueue_execution_failure(
        self,
        *,
        attempt_job_id: str,
        decision_id: str,
        model_id: str,
        coordinator_node_id: str,
        worker_node_id: str,
        network_result: dict[str, Any],
        disconnected_node_ids: tuple[str, ...] = (),
    ) -> str:
        rtt, bandwidth = _network_facts(network_result)
        raw_id = f"{attempt_job_id}:{decision_id}:failed".encode("utf-8")
        payload = {
            "outcome_id": "outcome-failure-" + hashlib.sha256(raw_id).hexdigest()[:24],
            "decision_id": decision_id,
            "model_id": model_id,
            "coordinator_node_id": coordinator_node_id,
            "worker_node_id": worker_node_id,
            "rtt_ms": rtt,
            "bandwidth_mbps": bandwidth,
            "prefill_tps": 0.0,
            "decode_tps": 0.0,
            "prefill_ms": 0.0,
            "decode_ms": 0.0,
            "request_ms": 0.0,
            "success": False,
            "verification_status": "not_produced",
            "disconnected_node_ids": sorted(set(disconnected_node_ids)),
        }
        return self._enqueue(payload)

    def _deliver(self, outcome_id: str, payload_json: str) -> bool:
        req = urlrequest.Request(
            self.endpoint,
            data=payload_json.encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.bearer_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        context = ssl.create_default_context(cafile=self.ca_file) if self.ca_file else ssl.create_default_context()
        error_text: str | None = None
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_seconds, context=context) as response:
                raw = response.read(64 * 1024 + 1)
                if response.status not in {200, 202} or len(raw) > 64 * 1024:
                    raise PrivateFeedbackError("private outcome service rejected delivery")
        except (urlerror.URLError, TimeoutError, ssl.SSLError, PrivateFeedbackError) as exc:
            error_text = f"{type(exc).__name__}: {str(exc)[:512]}"
        with self._connect() as db:
            if error_text is None:
                db.execute(
                    "UPDATE private_outcome_outbox SET delivered_at=?, attempts=attempts+1, last_error=NULL WHERE outcome_id=?",
                    (datetime.now(UTC).isoformat(), outcome_id),
                )
                return True
            db.execute(
                "UPDATE private_outcome_outbox SET attempts=attempts+1, last_error=? WHERE outcome_id=?",
                (error_text, outcome_id),
            )
        return False

    def deliver(self, outcome_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json, delivered_at FROM private_outcome_outbox WHERE outcome_id=?",
                (outcome_id,),
            ).fetchone()
        if row is None:
            raise KeyError(outcome_id)
        if row[1] is not None:
            return True
        return self._deliver(outcome_id, str(row[0]))

    def replay_pending(self, *, limit: int = 100) -> int:
        limit = max(1, min(int(limit), 1000))
        with self._connect() as db:
            rows = db.execute(
                "SELECT outcome_id,payload_json FROM private_outcome_outbox WHERE delivered_at IS NULL ORDER BY created_at LIMIT ?",
                (limit,),
            ).fetchall()
        delivered = 0
        for outcome_id, payload_json in rows:
            delivered += int(self._deliver(str(outcome_id), str(payload_json)))
        return delivered
