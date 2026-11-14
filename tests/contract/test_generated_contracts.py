"""The JSON files in contracts/ are generated; fail if they drift from the Python models."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]


def test_committed_contracts_match_source_models() -> None:
    spec = importlib.util.spec_from_file_location(
        "export_contracts", ROOT / "scripts" / "export_contracts.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stale = module.stale_files()
    assert stale == [], "regenerate with: uv run python scripts/export_contracts.py"


def test_openapi_exposes_planned_routes() -> None:
    import json

    paths = json.loads((ROOT / "contracts/api/openapi.json").read_text())["paths"]
    expected = {
        ("/health", "get"),
        ("/projects", "get"),
        ("/projects", "post"),
        ("/projects/{project_id}", "get"),
        ("/projects/{project_id}/devices", "get"),
        ("/projects/{project_id}/devices", "post"),
        ("/devices/{device_id}", "get"),
        ("/devices/{device_id}/status", "get"),
        ("/projects/{project_id}/sessions", "get"),
        ("/projects/{project_id}/sessions", "post"),
        ("/sessions/{session_id}", "get"),
        ("/projects/{project_id}/jobs", "post"),
        ("/jobs/{job_id}", "get"),
        ("/projects/{project_id}/devices/{device_id}/commands", "post"),
        ("/commands/{command_id}", "get"),
    }
    actual = {(path, method) for path, methods in paths.items() for method in methods}
    assert expected <= actual
