"""Restart-safe at-least-once delivery for the durable agent event outbox."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .session import AgentSessionStore, SessionEvent


class EventOutboxDispatchError(RuntimeError):
    """Raised when an outbox dispatcher cannot be configured safely."""


@dataclass(frozen=True)
class OutboxDispatchStats:
    """Outcome of one bounded dispatch pass."""

    claimed: int = 0
    delivered: int = 0
    released: int = 0
    failed: int = 0


EventSink = Callable[[SessionEvent], None]


class AgentEventOutboxDispatcher:
    """Deliver durable events with lease recovery and bounded polling.

    Delivery is intentionally at-least-once: a process can crash after the
    sink accepts an event and before the acknowledgement is committed. Sinks
    must therefore deduplicate by ``event_id`` before applying side effects.
    """

    def __init__(
        self,
        store: AgentSessionStore,
        consumer_id: str,
        sink: EventSink,
        *,
        batch_size: int = 100,
        lease_seconds: float = 60.0,
        poll_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(store, AgentSessionStore):
            raise TypeError("store must be an AgentSessionStore")
        if not callable(sink):
            raise TypeError("sink must be callable")
        consumer = str(consumer_id or "").strip()
        # Reuse the store's canonical validation so dispatcher and database
        # agree on the same consumer identity contract.
        AgentSessionStore._validate_outbox_consumer(consumer)
        try:
            batch = int(batch_size)
            lease = float(lease_seconds)
            poll = float(poll_seconds)
        except (TypeError, ValueError) as exc:
            raise EventOutboxDispatchError("invalid outbox dispatcher limits") from exc
        if not 1 <= batch <= 1000:
            raise EventOutboxDispatchError("batch_size must be between 1 and 1000")
        if not 0.01 <= lease <= 86_400.0:
            raise EventOutboxDispatchError("lease_seconds is outside the supported range")
        if not 0.01 <= poll <= 86_400.0:
            raise EventOutboxDispatchError("poll_seconds is outside the supported range")
        if not callable(sleep):
            raise TypeError("sleep must be callable")
        self.store = store
        self.consumer_id = consumer
        self.sink = sink
        self.batch_size = batch
        self.lease_seconds = lease
        self.poll_seconds = poll
        self._sleep = sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def dispatch_once(self) -> OutboxDispatchStats:
        """Claim and deliver one bounded batch; individual failures are released."""
        events = self.store.claim_pending_events(
            self.consumer_id,
            limit=self.batch_size,
            lease_seconds=self.lease_seconds,
        )
        delivered = 0
        released = 0
        failed = 0
        for event in events:
            try:
                self.sink(event)
                if self.store.ack_pending_events(self.consumer_id, [event.event_id]) != 1:
                    raise EventOutboxDispatchError("event acknowledgement lost its claim")
                delivered += 1
            except Exception as exc:
                failed += 1
                with self._lock:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                try:
                    released += self.store.release_pending_events(self.consumer_id, [event.event_id])
                except Exception as release_exc:
                    with self._lock:
                        self._last_error = f"{type(release_exc).__name__}: {release_exc}"
        return OutboxDispatchStats(
            claimed=len(events),
            delivered=delivered,
            released=released,
            failed=failed,
        )

    def run_once(self) -> OutboxDispatchStats:
        """Run one pass and return its bounded outcome."""
        return self.dispatch_once()

    def run_forever(self) -> None:
        """Poll until stop is requested; safe to use as a supervised thread target."""
        while not self._stop.is_set():
            try:
                stats = self.dispatch_once()
            except Exception as exc:
                # A transient database/connection failure must not silently
                # terminate the supervised delivery thread.
                with self._lock:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                self._stop.wait(self.poll_seconds)
                continue
            if stats.claimed == 0:
                self._stop.wait(self.poll_seconds)

    def start(self, *, daemon: bool = True) -> threading.Thread:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._thread
            self._stop.clear()
            self._thread = threading.Thread(
                target=self.run_forever,
                name=f"computemesh-event-outbox-{self.consumer_id}",
                daemon=bool(daemon),
            )
            self._thread.start()
            return self._thread

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def close(self, *, timeout: float | None = None) -> None:
        self.stop()
        self.join(timeout)

    def __enter__(self) -> "AgentEventOutboxDispatcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close(timeout=2.0)
