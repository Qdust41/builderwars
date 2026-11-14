"""Board simulator: emits a burst of valid sample messages as JSON lines.

    uv run python -m board_runtime.simulator --device-id sim-001 --count 40 > /tmp/messages.jsonl
    uv run python -m workers.main /tmp/messages.jsonl

This is a LOCAL simulation. It does not connect to AWS IoT Core and is not an authenticated
device. See docs/aws-deployment.md for testing against a real IoT development environment.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import TextIO

from board_runtime.config import DeviceConfig, TransportKind
from board_runtime.connectivity import StdoutTransport
from board_runtime.hardware import SimulatedSensors
from board_runtime.logging import DeviceLogForwarder
from board_runtime.main import BoardRuntime


def simulate(
    *, device_id: str, count: int, seed: int | None = None, out: TextIO | None = None
) -> None:
    config = DeviceConfig(
        device_id=device_id,
        hardware_model="simulated-board",
        firmware_version="0.0.0-sim",
        transport=TransportKind.STDOUT,
    )
    runtime = BoardRuntime(config, StdoutTransport(out or sys.stdout), SimulatedSensors(seed))
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
    args = parser.parse_args(argv)
    simulate(device_id=args.device_id, count=args.count, seed=args.seed)


if __name__ == "__main__":
    main()
