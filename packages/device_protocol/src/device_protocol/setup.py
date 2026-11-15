"""What the CLI reports about the test setup when it starts: the laptop (host) it runs on and
the FREE-WILi plugged into it. The target board is described by people in the web app.

    laptop (builderwars CLI)  --USB-->  FREE-WILi  --I2C/SPI/UART/GPIO-->  target board

Python 3.10-safe: the host runtime imports this module.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Report(BaseModel):
    # Ignore unknown fields so a newer CLI can report more than an older API stores.
    model_config = ConfigDict(extra="ignore", frozen=True)


class HostReport(_Report):
    """The laptop running ``builderwars run``."""

    hostname: str = Field(max_length=255)
    os: str = Field(max_length=120, description="e.g. 'Linux 6.8 (x86_64)'")
    python_version: str = Field(max_length=40)
    cli_version: str = Field(max_length=40)
    sensor_source: str = Field(
        default="freewili",
        max_length=20,
        description="'freewili' (real board), 'simulated' (--simulate) or 'freewili-gpio' "
        "(no sensors defined: raw FREE-WILi pins)",
    )


class BridgeReport(_Report):
    """The FREE-WILi between the laptop and the target board."""

    model: str = Field(default="FREE-WILi", max_length=80)
    serial: str | None = Field(default=None, max_length=80)
    main_port: str | None = Field(default=None, max_length=120)
    display_port: str | None = Field(default=None, max_length=120)
    library_version: str | None = Field(default=None, max_length=40)


class SetupReport(_Report):
    """``PUT /devices/{id}/setup/connection``: sent by the CLI when ``run`` starts.
    ``bridge`` is ``None`` when no FREE-WILi is attached (``--simulate``)."""

    host: HostReport
    bridge: BridgeReport | None = None


__all__ = ["BridgeReport", "HostReport", "SetupReport"]
