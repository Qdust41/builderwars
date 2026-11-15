"""``DEVICE_TRANSPORT=cloud``: send the board's messages to the Builderwars API as the signed-in
user (``builderwars run --cloud``), instead of AWS IoT Core.

Each publish is ``POST /devices/{device_id}/messages`` with the same ``{topic, payload}`` the
board would publish over MQTT; the API validates it like the MQTT path and pushes it live to
everyone viewing the device. A network or server failure raises :class:`TransportError`, so
the runtime buffers the message offline and retries; a rejected message is logged and dropped,
because sending it again would never succeed.

Commands from the dashboard (ping, uptime) have no MQTT subscription to arrive on, so once
the runtime subscribes, a background thread polls ``POST /devices/{id}/commands/claim`` every
``COMMAND_POLL_INTERVAL_S`` and hands each new command to the runtime, which answers with a
``command_result`` through ``publish`` like any other message.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from typing import Any
from urllib.parse import quote

from board_runtime.cloud.account import AccountError, ApiError, CloudSession
from board_runtime.connectivity.transport import MessageHandler, TransportError

log = logging.getLogger(__name__)

COMMAND_POLL_INTERVAL_S = 2.0
_SEEN_COMMANDS = 256  # command ids remembered, so a re-sent pending command runs once


class CloudApiTransport:
    def __init__(
        self,
        session: CloudSession,
        device_id: str,
        *,
        poll_interval_s: float | None = COMMAND_POLL_INTERVAL_S,
    ) -> None:
        self._session = session
        device_path = f"/devices/{quote(device_id, safe='')}"
        self._path = f"{device_path}/messages"
        self._claim_path = f"{device_path}/commands/claim"
        self._handlers: dict[str, MessageHandler] = {}
        self._connected = False
        self._last_error: str | None = None
        # The poller thread and the runtime share the session (token refresh writes a file).
        self._lock = threading.Lock()
        self._poll_interval_s = poll_interval_s
        self._poller: threading.Thread | None = None
        self._stop = threading.Event()
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._claim_supported = True

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        try:
            self._session.auth_headers()  # fail early if the sign-in has expired
        except AccountError as exc:
            raise TransportError(f"{exc} ({exc.hint})" if exc.hint else str(exc)) from exc
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        self._stop.set()
        if self._poller is not None and self._poller is not threading.current_thread():
            self._poller.join(timeout=5)
        self._poller = None

    def publish(self, topic: str, payload: bytes) -> None:
        if not self._connected:
            raise TransportError("not connected")
        try:
            result = self.upload([{"topic": topic, "payload": json.loads(payload)}])
        except ApiError as exc:
            if exc.status in (400, 413, 422):
                # The API will never accept this message; drop it rather than block the queue.
                log.warning("the API refused a %s message: %s", topic, exc)
                return
            # Expired sign-in, lost membership, server trouble: keep the message buffered
            # and retry; the runtime keeps sampling meanwhile.
            self._warn(exc)
            raise TransportError(str(exc)) from exc
        except AccountError as exc:
            self._warn(exc)
            raise TransportError(str(exc)) from exc
        self._last_error = None
        for item in result.get("results", []):
            if item.get("outcome") == "rejected":
                log.warning("the API rejected a %s message: %s", topic, item.get("detail"))

    def upload(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """POST messages as they are; raises :class:`AccountError` / :class:`ApiError`."""
        with self._lock:
            result = self._session.request("POST", self._path, {"messages": messages})
        return result if isinstance(result, dict) else {}

    def _warn(self, exc: AccountError) -> None:
        text = str(exc) + (f" ({exc.hint})" if exc.hint else "")
        if text != self._last_error:  # once per distinct problem, not once per sample
            log.error("cannot upload to Builderwars, buffering: %s", text)
            self._last_error = text

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        self._handlers[topic] = handler
        if self._poll_interval_s and self._poller is None:
            self._stop.clear()
            self._poller = threading.Thread(
                target=self._poll_loop, name="builderwars-commands", daemon=True
            )
            self._poller.start()

    # -- dashboard commands -----------------------------------------------------------------
    def _poll_loop(self) -> None:
        assert self._poll_interval_s
        while not self._stop.wait(self._poll_interval_s):
            if not self._claim_supported:
                return
            try:
                self.poll_commands()
            except Exception:  # never let the poller die on a surprise
                log.debug("command poll failed", exc_info=True)

    def poll_commands(self) -> int:
        """Fetch pending commands and run the new ones; returns how many were handed over."""
        if not self._connected:
            return 0
        try:
            with self._lock:
                result = self._session.request("POST", self._claim_path, {})
        except ApiError as exc:
            if exc.status in (404, 405) and "device" not in str(exc).lower():
                # An API from before command claiming: stop asking.
                self._claim_supported = False
                log.info("this Builderwars API can't send commands to CLI boards")
            return 0
        except AccountError:
            return 0  # an expired sign-in is reported by the upload path
        handed = 0
        for message in (result or {}).get("messages", []):
            topic = message.get("topic")
            payload = message.get("payload") or {}
            command_id = str((payload.get("payload") or {}).get("command_id", ""))
            handler = self._handlers.get(topic)
            if handler is None or not command_id or command_id in self._seen:
                continue
            self._seen[command_id] = None
            while len(self._seen) > _SEEN_COMMANDS:
                self._seen.popitem(last=False)
            handler(topic, json.dumps(payload).encode())
            handed += 1
        return handed
