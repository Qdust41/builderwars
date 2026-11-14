from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from device_protocol.schemas import LogLevel

_LEVELS = {
    logging.DEBUG: LogLevel.DEBUG,
    logging.INFO: LogLevel.INFO,
    logging.WARNING: LogLevel.WARNING,
    logging.ERROR: LogLevel.ERROR,
    logging.CRITICAL: LogLevel.CRITICAL,
}


class DeviceLogForwarder(logging.Handler):
    """``logging`` handler that turns records into protocol ``log`` payloads.

    ``emit_payload`` is typically ``runtime.send_log``. Records from the transport layer itself
    should not be forwarded (would loop while offline); attach this handler to the
    application loggers only. TODO: rate limiting / sampling for chatty loggers.
    """

    def __init__(
        self, emit_payload: Callable[[dict[str, Any]], None], level: int = logging.INFO
    ) -> None:
        super().__init__(level)
        self._emit_payload = emit_payload

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = _LEVELS.get(record.levelno, LogLevel.INFO)
            self._emit_payload(
                {
                    "level": level.value,
                    "message": self.format(record)[:4096],
                    "logger": record.name[:128],
                }
            )
        except Exception:  # never let logging crash the runtime
            self.handleError(record)
