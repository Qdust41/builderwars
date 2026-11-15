"""Device-scoped realtime notifications (telemetry, logs, command results).

Published on ``projects/{project_id}/devices/{device_id}`` for everyone viewing the device.
Events are hints: the API stays the source of truth, and clients refetch after a reconnect.
A failed publish is logged and never fails the ingest or command path that triggered it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from application.ports import RealtimePublisher
from application.realtime import RealtimeEvent, RealtimeEventType
from domain.devices import DeviceCommand

log = logging.getLogger(__name__)


class DeviceEventPublisher:
    def __init__(self, publisher: RealtimePublisher) -> None:
        self._publisher = publisher

    def telemetry(
        self, *, project_id: str, device_id: str, samples: list[tuple[datetime, dict[str, Any]]]
    ) -> None:
        self._publish(
            RealtimeEventType.DEVICE_TELEMETRY,
            project_id,
            device_id,
            {"samples": [{"ts": ts.isoformat(), "readings": r} for ts, r in samples]},
        )

    def log_entry(
        self,
        *,
        project_id: str,
        device_id: str,
        at: datetime,
        kind: str,
        level: str,
        message: str,
    ) -> None:
        self._publish(
            RealtimeEventType.DEVICE_LOG,
            project_id,
            device_id,
            {"at": at.isoformat(), "kind": kind, "level": level, "message": message},
        )

    def command_updated(self, command: DeviceCommand) -> None:
        self._publish(
            RealtimeEventType.DEVICE_COMMAND_UPDATED,
            command.project_id,
            command.device_id,
            # Only the id and outcome: the full record is fetched from GET /commands/{id}.
            {
                "command_id": command.id,
                "name": command.name,
                "status": command.status.value,
                "detail": command.detail,
                "output": dict(command.output),
            },
        )

    def status_changed(
        self, *, project_id: str, device_id: str, status: str, at: datetime | None
    ) -> None:
        """The device went online or offline (e.g. the CLI stopped)."""
        self._publish(
            RealtimeEventType.DEVICE_STATUS_CHANGED,
            project_id,
            device_id,
            {"connection_status": status, "last_seen_at": at.isoformat() if at else None},
        )

    def _publish(
        self, type_: RealtimeEventType, project_id: str, device_id: str, data: dict[str, Any]
    ) -> None:
        try:
            event = RealtimeEvent(
                type=type_,
                project_id=project_id,
                device_id=device_id,
                actor_id=device_id,
                data=data,
            )
            self._publisher.publish(event)
        except (ValidationError, ValueError) as exc:
            log.warning("dropping %s event for %s: %s", type_.value, device_id, exc)
        except Exception:
            log.exception("failed to publish %s event for %s", type_.value, device_id)
