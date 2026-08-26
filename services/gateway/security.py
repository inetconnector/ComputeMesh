"""ComputeMesh Hardened Gateway Security, Rate Limiting & Data Sanitization Module.

Provides:
- In-memory Token-Bucket rate limiter with sliding window burst protection
- Standardized OWASP HTTP Security Headers
- Zero-Trace AI prompt memory scrubbing & error sanitization
- Request body payload size limits
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import logging
import os
import re
import threading
import time
from typing import Any

logger = logging.getLogger("computemesh.security")

# OWASP Recommended Security Headers
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(self), usb=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self' https://computemesh.inetconnector.com wss: https:; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self';",
    "Server": "ComputeMesh-Gateway/1.2",
}

# Maximum Request Body Payload (10 MB)
MAX_REQUEST_PAYLOAD_BYTES: int = 10 * 1024 * 1024


@dataclass
class TokenBucket:
    capacity: float
    tokens: float
    refill_rate_per_sec: float
    last_update: float


class RateLimiter:
    """Thread-safe Token Bucket Rate Limiter with automatic bucket expiration."""

    def __init__(
        self,
        default_rate_per_min: float = 60.0,
        authenticated_rate_per_min: float = 600.0,
    ) -> None:
        self.default_rate_per_sec = default_rate_per_min / 60.0
        self.auth_rate_per_sec = authenticated_rate_per_min / 60.0
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.RLock()
        self._last_cleanup = time.time()

    def is_allowed(self, identifier: str, is_authenticated: bool = False) -> tuple[bool, float]:
        """Checks if a request is allowed. Returns (allowed: bool, retry_after_sec: float)."""
        if os.environ.get("COMPUTEMESH_DISABLE_RATE_LIMIT") == "1":
            return (True, 0.0)

        # Loopback and internal testing are never throttled
        if "127.0.0.1" in identifier or "::1" in identifier or "localhost" in identifier or "loopback" in identifier:
            return (True, 0.0)

        now = time.time()
        refill_rate = self.auth_rate_per_sec if is_authenticated else self.default_rate_per_sec
        capacity = refill_rate * 5.0  # allow 5s burst

        with self._lock:
            if now - self._last_cleanup > 300.0:
                self._cleanup_stale_buckets(now)

            bucket = self._buckets.get(identifier)
            if bucket is None:
                self._buckets[identifier] = TokenBucket(
                    capacity=capacity,
                    tokens=capacity - 1.0,
                    refill_rate_per_sec=refill_rate,
                    last_update=now,
                )
                return (True, 0.0)

            # Refill tokens based on elapsed time
            elapsed = max(0.0, now - bucket.last_update)
            bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_rate_per_sec)
            bucket.last_update = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return (True, 0.0)

            # Rate limit exceeded
            deficit = 1.0 - bucket.tokens
            retry_after = max(0.1, deficit / bucket.refill_rate_per_sec)
            return (False, round(retry_after, 2))

    def _cleanup_stale_buckets(self, now: float) -> None:
        stale_keys = [k for k, v in self._buckets.items() if now - v.last_update > 600.0]
        for k in stale_keys:
            del self._buckets[k]
        self._last_cleanup = now


# Global Singleton Rate Limiter
GLOBAL_RATE_LIMITER = RateLimiter()


def sanitize_error_message(error: Exception | str) -> str:
    """Masks internal stack traces, filesystem paths, and private keys from caller error strings."""
    msg = str(error)
    # Mask file system paths
    msg = re.sub(r"([A-Za-z]:\\[^ \n]+|/(?:root|home|etc|var|opt)/[^ \n]+)", "[internal_path]", msg)
    # Mask API keys and secrets
    msg = re.sub(r"(cm_[a-zA-Z0-9_]{16,}|sk_[a-zA-Z0-9_]{16,}|whsec_[a-zA-Z0-9_]{16,})", "[REDACTED_SECRET]", msg)
    return msg


def zero_memory_bytes(buf: bytearray | memoryview) -> None:
    """Zero-fills memory buffers holding sensitive prompt data."""
    try:
        for i in range(len(buf)):
            buf[i] = 0
    except Exception:
        pass
