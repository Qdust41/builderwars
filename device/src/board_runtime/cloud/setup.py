"""The device's test setup in the cloud, from the host's side.

* ``fetch_sensors``: the sensor definitions people made on the device page, which
  ``builderwars run`` reads through the FREE-WILi.
* ``report_connection``: tell the device page which laptop and FREE-WILi are running it.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from board_runtime.cloud.account import ApiError, CloudSession
from board_runtime.hardware.freewili import BoardInfo
from device_protocol.sensors import SensorSpec
from device_protocol.setup import BridgeReport, HostReport, SetupReport

log = logging.getLogger(__name__)


@dataclass
class SensorList:
    sensors: list[SensorSpec] = field(default_factory=list)
    # (key or index, why) for definitions this CLI can't use, e.g. from a newer API.
    skipped: list[tuple[str, str]] = field(default_factory=list)
    # Board name per sensor key, for printing.
    boards: dict[str, str] = field(default_factory=dict)


def fetch_sensors(session: CloudSession, device_id: str) -> SensorList:
    """Every sensor defined for the device (enabled or not). A 404 from an API that predates
    sensors reads as "no sensors"; other errors raise ``AccountError``."""
    path = f"/devices/{quote(device_id, safe='')}"
    try:
        rows = session.request("GET", f"{path}/sensors") or []
    except ApiError as exc:
        if exc.status == 404 and "sensor" not in str(exc).lower():
            session.request("GET", path)  # re-raises if the device itself is missing
            return SensorList()
        raise
    boards: dict[str, str] = {}
    try:
        setup = session.request("GET", f"{path}/setup") or {}
        boards = {b["id"]: b["name"] for b in setup.get("boards", [])}
    except Exception:  # board names are only for display
        log.debug("could not read board names", exc_info=True)
    result = SensorList()
    for index, row in enumerate(rows):
        try:
            spec = SensorSpec.model_validate(row)
        except ValidationError as exc:
            name = str(row.get("key") or f"#{index + 1}") if isinstance(row, dict) else f"#{index}"
            first = exc.errors()[0]
            result.skipped.append((name, f"{'.'.join(map(str, first['loc']))}: {first['msg']}"))
            continue
        result.sensors.append(spec)
        if isinstance(row, dict) and row.get("board_id") in boards:
            result.boards[spec.key] = boards[row["board_id"]]
    return result


def host_report(*, cli_version: str, sensor_source: str) -> HostReport:
    return HostReport(
        hostname=platform.node() or "unknown",
        os=f"{platform.system()} {platform.release()} ({platform.machine()})".strip(),
        python_version=platform.python_version(),
        cli_version=cli_version,
        sensor_source=sensor_source,
    )


def bridge_report(info: BoardInfo | None, *, library_version: str | None) -> BridgeReport | None:
    if info is None:
        return None
    return BridgeReport(
        model=info.name or "FREE-WILi",
        serial=None if info.serial in ("", "?") else info.serial,
        main_port=info.main_port,
        display_port=info.display_port,
        library_version=library_version,
    )


def report_connection(
    session: CloudSession, device_id: str, host: HostReport, bridge: BridgeReport | None
) -> dict[str, Any] | None:
    """Best effort: a failure is logged, never fatal (the data upload matters more)."""
    body = SetupReport(host=host, bridge=bridge).model_dump(mode="json")
    try:
        result = session.request(
            "PUT", f"/devices/{quote(device_id, safe='')}/setup/connection", body
        )
    except Exception as exc:
        log.warning("could not report this laptop/FREE-WILi to the device page: %s", exc)
        return None
    return result if isinstance(result, dict) else None
