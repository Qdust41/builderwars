"""Generate the JSON contract files under ``contracts/`` from the Python source of truth.

    uv run python scripts/export_contracts.py          # write files
    uv run python scripts/export_contracts.py --check  # fail if committed files are stale (CI)

The frontend and any non-Python board firmware should consume these generated files rather
than keeping hand-written copies of the protocol.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def build_contracts() -> dict[Path, Any]:
    from api.main import create_app
    from api.settings import AppEnv, Settings
    from application.realtime import RealtimeEvent
    from device_protocol.envelopes import DeviceEnvelope
    from device_protocol.schemas import PAYLOAD_MODELS, TelemetryPayload
    from device_protocol.topics import CHANNEL_FOR_MESSAGE_TYPE, DEVICE_ID_PATTERN

    payloads: dict[str, Any] = {}
    for message_type, model in PAYLOAD_MODELS.items():
        schema = model.model_json_schema()
        if model is TelemetryPayload:
            schema = {
                "title": "TelemetryPayload",
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"type": ["number", "integer", "boolean", "string"]},
            }
        payloads[message_type.value] = schema

    return {
        ROOT / "contracts/device/envelope.v1.schema.json": DeviceEnvelope.model_json_schema(),
        ROOT / "contracts/device/payloads.v1.schema.json": {
            "title": "Device message payloads (schema_version 1)",
            "description": "Payload schema per message_type. Provisional until hardware is chosen.",
            "payloads": payloads,
            "topics": {
                "pattern": "devices/{device_id}/{channel}",
                "device_id_pattern": DEVICE_ID_PATTERN,
                "channel_for_message_type": {
                    k.value: v.value for k, v in CHANNEL_FOR_MESSAGE_TYPE.items()
                },
            },
        },
        ROOT / "contracts/realtime/event.v1.schema.json": RealtimeEvent.model_json_schema(),
        ROOT / "contracts/api/openapi.json": create_app(Settings(app_env=AppEnv.TEST)).openapi(),
    }


def render(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def stale_files() -> list[Path]:
    return [
        path
        for path, data in build_contracts().items()
        if not path.exists() or path.read_text(encoding="utf-8") != render(data)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        stale = stale_files()
        for path in stale:
            print(f"stale contract: {path.relative_to(ROOT)}", file=sys.stderr)
        if stale:
            print("run: uv run python scripts/export_contracts.py", file=sys.stderr)
        return 1 if stale else 0
    for path, data in build_contracts().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(data), encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
