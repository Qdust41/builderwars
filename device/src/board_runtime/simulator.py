"""Board simulator: emits a burst of valid sample messages as JSON lines.

    uv run python -m board_runtime.simulator --device-id sim-001 --count 40 > /tmp/messages.jsonl
    uv run python -m workers.main /tmp/messages.jsonl

This is a LOCAL simulation. It does not connect to AWS IoT Core and is not an authenticated
device. See docs/aws-deployment.md for testing against a real IoT development environment.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import TextIO

from board_runtime.config import DeviceConfig, TransportKind, log_csv_path_from_env
from board_runtime.connectivity import StdoutTransport
from board_runtime.hardware import SimulatedSensors
from board_runtime.logging import CsvLogSink, DeviceLogForwarder
from board_runtime.main import BoardRuntime


def simulate(
    *,
    device_id: str,
    count: int,
    seed: int | None = None,
    out: TextIO | None = None,
    csv_path: Path | None = None,
    write_csv: bool = True,
) -> None:
    """Emit ``count`` samples as JSON lines.

    Log messages also go to a CSV: ``csv_path`` if given, otherwise wherever
    ``BUILDERWARS_LOG_CSV`` / ``BUILDERWARS_STATE_DIR`` point (``BUILDERWARS_LOG_CSV=off``
    disables it, as for the runtime). ``write_csv=False`` disables it outright.
    """
    config = DeviceConfig(
        device_id=device_id,
        hardware_model="simulated-board",
        firmware_version="0.0.0-sim",
        transport=TransportKind.STDOUT,
    )
    path: Path | None = None
    if write_csv:
        path = csv_path or log_csv_path_from_env({**os.environ, "DEVICE_ID": device_id})
    csv_sink = CsvLogSink(path) if path is not None else None
    runtime = BoardRuntime(
        config, StdoutTransport(out or sys.stdout), SimulatedSensors(seed), csv_sink=csv_sink
    )
    app_log = logging.getLogger("board_runtime.simulator.app")
    app_log.propagate = False
    app_log.setLevel(logging.INFO)
    handler = DeviceLogForwarder(runtime.send_log)
    app_log.addHandler(handler)
    try:
        runtime.start()
        app_log.info("simulator started")
        for _ in range(count):
            runtime.sample()
        runtime.heartbeat()
        runtime.stop()
    finally:
        app_log.removeHandler(handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device-id", default="sim-001")
    parser.add_argument("--count", type=int, default=5, help="number of sensor samples")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="CSV log file (default: $BUILDERWARS_LOG_CSV or ~/.builderwars/logs/<device-id>.csv)",
    )
    args = parser.parse_args(argv)
    simulate(device_id=args.device_id, count=args.count, seed=args.seed, csv_path=args.csv)


if __name__ == "__main__":
    main()
