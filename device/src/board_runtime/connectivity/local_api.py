"""LOCAL ONLY: talk to a local API process instead of AWS IoT Core.

``DEVICE_TRANSPORT=local-api`` posts each message to ``POST /local/device-messages`` (what the
IoT rule would forward) and polls ``POST /local/devices/{id}/commands/next`` for commands.
The API only mounts those routes with its in-memory backend (``APP_ENV=local``/``test``), and
this transport is not an authenticated IoT device. Standard library only (Python 3.10+).
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

from board_runtime.connectivity.transport import MessageHandler, TransportError

log = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 0.5
REQUEST_TIMEOUT_S = 5.0


class LocalApiTransport:
    def __init__(
        self,
        api_url: str,
        device_id: str,
        *,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._base = api_url.rstrip("/")
        self._device_id = device_id
        self._poll_interval_s = poll_interval_s
        self._handlers: dict[str, MessageHandler] = {}
        self._connected = False
        self._stop = threading.Event()
        self._poller: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True
        self._stop.clear()
        self._poller = threading.Thread(target=self._poll_loop, name="local-api-poll", daemon=True)
        self._poller.start()

    def disconnect(self) -> None:
        self._connected = False
        self._stop.set()
        if self._poller is not None and self._poller is not threading.current_thread():
            self._poller.join(timeout=REQUEST_TIMEOUT_S)
        self._poller = None

    def publish(self, topic: str, payload: bytes) -> None:
        if not self._connected:
            raise TransportError("not connected")
        body = {"topic": topic, "payload": json.loads(payload)}
        result = self._post("/local/device-messages", body)
        if isinstance(result, dict) and result.get("outcome") == "rejected":
            # Rejections are permanent; retrying would never succeed, so do not raise.
            log.warning("local API rejected %s: %s", topic, result.get("detail"))

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        self._handlers[topic] = handler

    def poll_commands(self) -> int:
        """Fetch queued commands once and hand them to the subscribed handlers."""
        path = f"/local/devices/{quote(self._device_id, safe='')}/commands/next"
        messages = self._post(path, None)
        count = 0
        for message in messages if isinstance(messages, list) else []:
            handler = self._handlers.get(message["topic"])
            if handler is None:
                log.warning("no handler for %s", message["topic"])
                continue
            handler(message["topic"], json.dumps(message["payload"]).encode())
            count += 1
        return count

    def _poll_loop(self) -> None:
        while not self._stop.wait(self._poll_interval_s):
            try:
                self.poll_commands()
            except TransportError as exc:
                log.debug("command poll failed: %s", exc)
            except Exception:
                log.exception("command handler failed")

    def _post(self, path: str, body: Any) -> Any:
        data = json.dumps(body).encode() if body is not None else b""
        request = urllib.request.Request(  # noqa: S310 - URL comes from local config
            self._base + path,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:  # noqa: S310
                return json.loads(response.read() or b"null")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TransportError(f"local API unreachable: {exc}") from exc
