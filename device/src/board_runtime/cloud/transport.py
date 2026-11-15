"""``DEVICE_TRANSPORT=cloud``: send the board's messages to the Builderwars API as the signed-in
user (``builderwars run --cloud``), instead of AWS IoT Core.

Each publish is ``POST /devices/{device_id}/messages`` with the same ``{topic, payload}`` the
board would publish over MQTT; the API validates it like the MQTT path and pushes it live to
everyone viewing the device. A network or server failure raises :class:`TransportError`, so
the runtime buffers the message offline and retries; a rejected message is logged and dropped,
because sending it again would never succeed.

Commands from the dashboard are not delivered on this path yet (they still go out through
AWS IoT), so ``subscribe`` only records the handler.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

from board_runtime.cloud.account import AccountError, ApiError, CloudSession
from board_runtime.connectivity.transport import MessageHandler, TransportError

log = logging.getLogger(__name__)


class CloudApiTransport:
    def __init__(self, session: CloudSession, device_id: str) -> None:
        self._session = session
        self._path = f"/devices/{quote(device_id, safe='')}/messages"
        self._handlers: dict[str, MessageHandler] = {}
        self._connected = False
        self._warned_commands = False
        self._last_error: str | None = None

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
        result = self._session.request("POST", self._path, {"messages": messages})
        return result if isinstance(result, dict) else {}

    def _warn(self, exc: AccountError) -> None:
        text = str(exc) + (f" ({exc.hint})" if exc.hint else "")
        if text != self._last_error:  # once per distinct problem, not once per sample
            log.error("cannot upload to Builderwars, buffering: %s", text)
            self._last_error = text

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        self._handlers[topic] = handler
        if not self._warned_commands:
            self._warned_commands = True
            log.info("cloud mode: dashboard commands are not delivered to this board yet")
