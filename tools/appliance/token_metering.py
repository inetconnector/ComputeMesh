"""ComputeMesh Provider Node Token Accounting & Metering Module.

Thread-safe and crash-resilient persistence for tokens computed by this provider node.
Maintains prompt_tokens, completion_tokens, total_tokens_served, and net earnings in USD.
Provides synchronization with local SQLite accounting and coordinator telemetry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any

# Default provider rate: $0.75 Netto per 1,000,000 tokens (75% share pool)
PROVIDER_USD_PER_MILLION_TOKENS = 0.75

def _get_token_storage_path() -> Path:
    base = Path.home() / ".computemesh"
    base.mkdir(parents=True, exist_ok=True)
    return base / "token_accounting.json"

_LOCK = threading.Lock()
_CACHED_STATS: TokenStats | None = None
_DIRTY = False
_LAST_FLUSH_TS = 0.0


@dataclass
class TokenStats:
    total_tokens_served: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_earnings_usd: float = 0.0
    earnings_cm: int = 0
    last_updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_token_stats() -> TokenStats:
    global _CACHED_STATS
    with _LOCK:
        if _CACHED_STATS is not None:
            return _CACHED_STATS
        p = _get_token_storage_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                toks = int(data.get("total_tokens_served", 0) or 0)
                p_toks = int(data.get("prompt_tokens", 0) or 0)
                c_toks = int(data.get("completion_tokens", 0) or 0)
                earn = float(data.get("total_earnings_usd", 0.0) or 0.0)
                if earn == 0.0 and toks > 0:
                    earn = round(toks * (PROVIDER_USD_PER_MILLION_TOKENS / 1_000_000.0), 6)
                st = TokenStats(
                    total_tokens_served=toks,
                    prompt_tokens=p_toks,
                    completion_tokens=c_toks,
                    total_earnings_usd=earn,
                    earnings_cm=toks,
                    last_updated_at=str(data.get("last_updated_at", "")),
                )
                _CACHED_STATS = st
                return st
            except Exception:
                pass
        st = TokenStats()
        _CACHED_STATS = st
        return st


def flush_token_stats_to_disk(force: bool = False) -> None:
    global _DIRTY, _LAST_FLUSH_TS
    now = time.time()
    if not force and (not _DIRTY or (now - _LAST_FLUSH_TS < 2.0)):
        return
    with _LOCK:
        if _CACHED_STATS is None:
            return
        stats = _CACHED_STATS
        p = _get_token_storage_path()
        stats.last_updated_at = datetime.now(timezone.utc).isoformat()
        stats.earnings_cm = stats.total_tokens_served
        if stats.total_earnings_usd == 0.0 and stats.total_tokens_served > 0:
            stats.total_earnings_usd = round(stats.total_tokens_served * (PROVIDER_USD_PER_MILLION_TOKENS / 1_000_000.0), 6)
        try:
            data = stats.to_dict()
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(p)
            _DIRTY = False
            _LAST_FLUSH_TS = now
        except Exception:
            pass


def save_token_stats(stats: TokenStats) -> None:
    global _CACHED_STATS, _DIRTY
    with _LOCK:
        _CACHED_STATS = stats
        _DIRTY = True
    flush_token_stats_to_disk(force=True)


def record_tokens(prompt_tokens: int = 0, completion_tokens: int = 0) -> TokenStats:
    """Increment metered prompt and completion tokens efficiently."""
    global _DIRTY
    st = load_token_stats()
    p_tok = max(0, int(prompt_tokens))
    c_tok = max(0, int(completion_tokens))
    added = p_tok + c_tok
    with _LOCK:
        st.prompt_tokens += p_tok
        st.completion_tokens += c_tok
        st.total_tokens_served += added
        st.total_earnings_usd = round(st.total_tokens_served * (PROVIDER_USD_PER_MILLION_TOKENS / 1_000_000.0), 6)
        st.earnings_cm = st.total_tokens_served
        _DIRTY = True
    flush_token_stats_to_disk(force=False)
    return st


def sync_with_coordinator(coordinator_tokens: int, coordinator_earnings_usd: float = 0.0) -> TokenStats:
    """Sync token stats with coordinator stats, keeping the maximum."""
    st = load_token_stats()
    c_toks = max(0, int(coordinator_tokens or 0))
    c_earn = max(0.0, float(coordinator_earnings_usd or 0.0))
    changed = False
    with _LOCK:
        if c_toks > st.total_tokens_served:
            diff = c_toks - st.total_tokens_served
            st.total_tokens_served = c_toks
            st.completion_tokens += diff
            changed = True
        if c_earn > st.total_earnings_usd:
            st.total_earnings_usd = c_earn
            changed = True
        st.earnings_cm = st.total_tokens_served
    if changed:
        save_token_stats(st)
    return st


def get_token_stats() -> dict[str, Any]:
    st = load_token_stats()
    return {
        "tokens_processed": st.total_tokens_served,
        "prompt_tokens": st.prompt_tokens,
        "completion_tokens": st.completion_tokens,
        "earnings_usd": st.total_earnings_usd,
        "earnings_cm": st.earnings_cm,
    }
