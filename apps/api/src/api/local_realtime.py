"""LOCAL ONLY: an in-process realtime hub that stands in for AppSync Events.

The API publishes events here (``RealtimePublisher`` port) and ``GET /local/realtime`` streams
them to the browser as server-sent events. Only wired with the in-memory backend, which
``validate_settings`` already forbids outside local/test.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress

from application.realtime import RealtimeEvent

log = logging.getLogger(__name__)

MAX_QUEUED_PER_SUBSCRIBER = 500


class _Subscriber:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[str] = asyncio.Queue(MAX_QUEUED_PER_SUBSCRIBER)

    def offer(self, data: str) -> None:
        # Runs on the subscriber's event loop. A slow client loses events rather than memory;
        # clients refetch state after gaps anyway.
        try:
            self.queue.put_nowait(data)
        except asyncio.QueueFull:
            log.warning("local realtime subscriber is behind; dropping an event")


class LocalRealtimeHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[str, set[_Subscriber]] = {}
        self.published: list[RealtimeEvent] = []  # for tests and debugging

    def publish(self, event: RealtimeEvent) -> None:
        data = event.model_dump_json()
        with self._lock:
            self.published.append(event)
            del self.published[:-1000]
            subscribers = list(self._subscribers.get(event.channel, ()))
        for sub in subscribers:
            with suppress(RuntimeError):  # the subscriber's loop has closed
                sub.loop.call_soon_threadsafe(sub.offer, data)

    @contextmanager
    def subscribe(self, channel: str) -> Iterator[asyncio.Queue[str]]:
        sub = _Subscriber(asyncio.get_running_loop())
        with self._lock:
            self._subscribers.setdefault(channel, set()).add(sub)
        try:
            yield sub.queue
        finally:
            with self._lock:
                subs = self._subscribers.get(channel)
                if subs is not None:
                    subs.discard(sub)
                    if not subs:
                        del self._subscribers[channel]
