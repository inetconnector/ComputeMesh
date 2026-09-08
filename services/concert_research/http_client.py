from __future__ import annotations

import gzip
import threading
from urllib import error, request, robotparser
from urllib.parse import urlsplit

from .config import ConcertResearchConfig
from .security import validate_public_http_url


class ValidatingRedirectHandler(request.HTTPRedirectHandler):
    """Reject unsafe redirect targets before urllib sends the redirected request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HardenedSafeFetcher:
    """Robots-aware public-web fetcher with bounded reads and redirect SSRF checks."""

    def __init__(self, config: ConcertResearchConfig):
        self.config = config
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._robots_lock = threading.Lock()
        self._host_locks: dict[str, threading.Semaphore] = {}
        self._host_locks_lock = threading.Lock()
        self._opener = request.build_opener(ValidatingRedirectHandler())

    def _host_sem(self, host: str) -> threading.Semaphore:
        with self._host_locks_lock:
            return self._host_locks.setdefault(host, threading.Semaphore(self.config.per_host_concurrency))

    def _open(self, req: request.Request, timeout: float):
        return self._opener.open(req, timeout=timeout)

    def _robot(self, url: str) -> robotparser.RobotFileParser:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        with self._robots_lock:
            cached = self._robots.get(base)
            if cached is not None:
                return cached

        rp = robotparser.RobotFileParser()
        robots_url = validate_public_http_url(base + "/robots.txt")
        rp.set_url(robots_url)
        try:
            req = request.Request(robots_url, headers={"User-Agent": self.config.user_agent})
            with self._open(req, timeout=min(8.0, self.config.request_timeout_seconds)) as resp:
                # The redirect handler already validated each hop; retain a final fail-closed check.
                validate_public_http_url(resp.geturl())
                raw = resp.read(512 * 1024 + 1)
                if len(raw) > 512 * 1024:
                    raise ValueError("robots.txt exceeds size limit")
                text = raw.decode("utf-8", "replace")
            rp.parse(text.splitlines())
        except Exception:
            # Keep existing ComputeMesh crawler behavior: an unavailable robots endpoint
            # is not treated as an implicit site-wide deny. Explicit Disallow rules are obeyed.
            rp.parse([])

        with self._robots_lock:
            self._robots[base] = rp
        return rp

    def allowed(self, url: str) -> bool:
        safe = validate_public_http_url(url)
        return self._robot(safe).can_fetch(self.config.user_agent, safe)

    def fetch(self, url: str, *, etag: str | None = None, last_modified: str | None = None):
        # Import lazily to avoid a module cycle: crawler.FetchResult is the shared return contract.
        from .crawler import FetchResult

        safe = validate_public_http_url(url)
        if not self.allowed(safe):
            raise PermissionError("robots.txt disallows crawl")

        parts = urlsplit(safe)
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/ld+json,application/xml,text/xml,"
                "text/calendar,application/rss+xml,application/atom+xml,text/plain;q=0.8,*/*;q=0.1"
            ),
            "Accept-Encoding": "gzip",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        req = request.Request(safe, headers=headers)
        with self._host_sem(parts.hostname or ""):
            try:
                with self._open(req, timeout=self.config.request_timeout_seconds) as resp:
                    final_url = validate_public_http_url(resp.geturl())
                    body = resp.read(self.config.max_response_bytes + 1)
                    if len(body) > self.config.max_response_bytes:
                        raise ValueError("response exceeds configured size limit")
                    if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                        body = gzip.decompress(body)
                        if len(body) > self.config.max_response_bytes:
                            raise ValueError("decompressed response exceeds configured size limit")
                    return FetchResult(
                        final_url,
                        int(resp.status),
                        resp.headers.get("Content-Type", ""),
                        body,
                        resp.headers.get("ETag"),
                        resp.headers.get("Last-Modified"),
                    )
            except error.HTTPError as exc:
                if exc.code == 304:
                    return FetchResult(safe, 304, "", b"", etag, last_modified)
                raise
