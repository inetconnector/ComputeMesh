"""Append-only, secret-minimizing audit events for Agents Platform decisions/actions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, Mapping
import uuid

_SECRET_KEY_RE = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie|private[_-]?key)", re.I)


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    timestamp: float
    event_type: str
    request_id: str | None
    decision: str
    action: str
    evidence: Mapping[str, Any]
    metadata: Mapping[str, Any]


class AuditLogger:
    """JSONL audit log. Records observable decisions, never hidden reasoning."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): ("[REDACTED]" if _SECRET_KEY_RE.search(str(k)) else cls._redact(v)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._redact(v) for v in value]
        if isinstance(value, str) and len(value) > 4096:
            return value[:4096] + "…[truncated]"
        return value

    def log(self, event_type: str, *, request_id: str | None = None, decision: str = "", action: str = "", evidence: Mapping[str, Any] | None = None, metadata: Mapping[str, Any] | None = None) -> AuditEvent:
        event = AuditEvent(
            event_id=f"evt_{uuid.uuid4().hex}", timestamp=time.time(), event_type=str(event_type),
            request_id=request_id, decision=str(decision), action=str(action),
            evidence=self._redact(dict(evidence or {})), metadata=self._redact(dict(metadata or {})),
        )
        line = json.dumps(asdict(event), ensure_ascii=False, sort_keys=True, default=str) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
        return event

    def read(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        result: list[dict[str, Any]] = []
        for line in lines[-max(1, int(limit)):]:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                result.append(parsed)
        return result
