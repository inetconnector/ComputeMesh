"""ComputeMesh Free Teaser Playground & Conversion Paywall System.

Provides zero-friction model testing for Ollama CLI and OpenAI SDKs without registration,
and delivers a high-conversion onboarding guide when the free quota is exhausted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import sys
import threading
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.common.config import CONFIG


@dataclass
class TeaserSession:
    """Tracks free playground inference consumption for an unauthenticated client IP."""
    client_ip: str
    requests_used: int = 0
    tokens_used: int = 0
    max_free_requests: int = 20
    max_free_tokens: int = 8192
    window_seconds: int = 14400
    created_at: float = field(default_factory=time.time)
    window_started_at: float = field(default_factory=time.time)

    def refresh_if_expired(self, now: float | None = None) -> None:
        current = now if now is not None else time.time()
        if current >= self.reset_at:
            self.requests_used = 0
            self.tokens_used = 0
            self.window_started_at = current

    @property
    def is_quota_exceeded(self) -> bool:
        if time.time() >= self.reset_at:
            return False
        return self.requests_used >= self.max_free_requests or self.tokens_used >= self.max_free_tokens

    @property
    def remaining_requests(self) -> int:
        if time.time() >= self.reset_at:
            return self.max_free_requests
        return max(0, self.max_free_requests - self.requests_used)

    @property
    def reset_at(self) -> float:
        return self.window_started_at + max(1, self.window_seconds)

    @property
    def retry_after_seconds(self) -> int:
        return max(0, int(self.reset_at - time.time()) + 1)

    @property
    def reset_at_iso(self) -> str:
        return datetime.fromtimestamp(self.reset_at, tz=timezone.utc).isoformat()


def get_teaser_paywall_message(max_requests: int | None = None) -> str:
    """Returns onboarding guide and instruction set when free teaser quota is exhausted."""
    limit = max_requests if max_requests is not None else CONFIG.teaser.max_free_requests
    domain = CONFIG.endpoints.domain
    base_url = CONFIG.endpoints.base_url
    return (
        f"🚀 **ComputeMesh Free Teaser-Limit erreicht ({limit} kostenlose Test-Anfragen)!**\n\n"
        "Du hast den dezentralen ComputeMesh-Cluster erfolgreich im Free-Playground getestet.\n"
        "Um das globale Mesh unbegrenzt und mit voller GPU-Beschleunigung zu nutzen, wähle eine der folgenden Optionen:\n\n"
        "1. **🔑 Eigenen API-Key erstellen (Consumer):**\n"
        f"   * Registriere dich unter {base_url} und hole dir deinen persönlichen API-Key.\n"
        "   * Binde den Key in Ollama oder OpenAI SDK ein:\n"
        f"     `export OLLAMA_HOST=\"{domain}:443\"`\n"
        "     `export OPENAI_API_KEY=\"cm_live_dein_api_key\"`\n"
        f"     `export OPENAI_BASE_URL=\"{base_url}/v1\"`\n\n"
        "2. **💰 Eigene GPU/Server als Provider connecten (Geld verdienen):**\n"
        "   * Verbinde dein Linux-/Windows-Rig mit einem einzigen Befehl:\n"
        f"     `curl -sSL {base_url}/install.sh | bash`\n"
        "   * Verdiene bis zu 75% aller Inferenz-Umsätze auf deiner Hardware!\n"
        "   * Auszahlungen erfolgen automatisiert via Stripe Connect aufs Bankkonto oder in Krypto.\n\n"
        "3. **⚡ Eigener Server = 0% Plattform-Aufschlag (Provider-Rabatt):**\n"
        "   Wenn du deinen eigenen Server im Mesh betreibst, rechnest du eigene Anfragen ohne Plattformgebühr zum reinen Selbstkostenpreis direkt über deine eigene Hardware ab!\n\n"
        "---\n"
        f"🌐 Web: {base_url} | Tokenbasierte Registrierung und Stripe-Abrechnung"
    )


class TeaserQuotaManager:
    """Manages IP-based free teaser sessions without requiring user registration."""
    def __init__(
        self,
        max_requests: int | None = None,
        max_tokens: int | None = None,
        window_seconds: int | None = None,
    ) -> None:
        self.max_requests = max_requests if max_requests is not None else CONFIG.teaser.max_free_requests
        self.max_tokens = max_tokens if max_tokens is not None else CONFIG.teaser.max_free_tokens
        self.window_seconds = window_seconds if window_seconds is not None else CONFIG.teaser.window_seconds
        self._sessions: dict[str, TeaserSession] = {}
        self._lock = threading.RLock()

    def get_or_create_session(self, client_ip: str) -> TeaserSession:
        with self._lock:
            if client_ip not in self._sessions:
                self._sessions[client_ip] = TeaserSession(
                    client_ip=client_ip,
                    max_free_requests=self.max_requests,
                    max_free_tokens=self.max_tokens,
                    window_seconds=self.window_seconds,
                )
            sess = self._sessions[client_ip]
            sess.max_free_requests = self.max_requests
            sess.max_free_tokens = self.max_tokens
            sess.window_seconds = self.window_seconds
            sess.refresh_if_expired()
            return sess

    def record_usage(self, client_ip: str, tokens: int = 10) -> TeaserSession:
        with self._lock:
            sess = self.get_or_create_session(client_ip)
            sess.requests_used += 1
            sess.tokens_used += tokens
            return sess

    def response_headers(self, client_ip: str) -> dict[str, str]:
        sess = self.get_or_create_session(client_ip)
        return {
            "X-ComputeMesh-Teaser-Remaining": str(sess.remaining_requests),
            "X-ComputeMesh-Teaser-Limit": str(self.max_requests),
            "X-ComputeMesh-Teaser-Reset-Seconds": str(sess.retry_after_seconds if sess.is_quota_exceeded else 0),
            "X-ComputeMesh-Teaser-Reset-At": sess.reset_at_iso,
        }

    def reset_for_test(self) -> None:
        with self._lock:
            self._sessions.clear()
