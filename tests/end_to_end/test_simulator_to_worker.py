"""Local end-to-end: simulator -> JSON lines -> worker harness -> ingest pipeline. No AWS."""

from __future__ import annotations

import io
import subprocess
import sys

import pytest

from application.services import IngestOutcome
from board_runtime.simulator import simulate
from workers.consumers import LocalHarness, read_jsonl
from workers.main import build_local_device_handler

pytestmark = pytest.mark.end_to_end


def test_simulated_messages_are_ingested_and_replays_are_deduplicated() -> None:
    out = io.StringIO()
    simulate(device_id="sim-e2e", count=4, seed=7, out=out)
    lines = out.getvalue()

    handler, telemetry = build_local_device_handler()
    harness = LocalHarness(handler)
    first = harness.run(read_jsonl(io.StringIO(lines)))
    replay = harness.run(read_jsonl(io.StringIO(lines)))

    total = len(lines.strip().splitlines())
    assert first == {IngestOutcome.PROCESSED: total}
    assert replay == {IngestOutcome.DUPLICATE: total}
    assert len(telemetry.telemetry) == 4


def test_cli_pipeline() -> None:
    sim = subprocess.run(
        [sys.executable, "-m", "board_runtime.simulator", "--count", "2", "--seed", "1"],
        check=True,
        capture_output=True,
        text=True,
    )
    worker = subprocess.run(
        [sys.executable, "-m", "workers.main"],
        input=sim.stdout,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "summary: processed=6; telemetry records=2" in worker.stdout
