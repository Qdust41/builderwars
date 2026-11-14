# Device protocol (schema_version 1)

Source of truth: `packages/device_protocol`. Generated JSON Schemas:
`contracts/device/envelope.v1.schema.json`, `contracts/device/payloads.v1.schema.json`.
Example messages: `contracts/device/fixtures/valid/`, rejected examples in `.../invalid/`
(file names start with the expected rejection reason).

The device is a **host PC + FREE-WILi pair** (docs/decisions/0004-host-pc-device.md): the
host runtime speaks this protocol; the board itself never talks to the cloud. Reading names
inside telemetry stay free-form until spec 02 fixes the sensor set.

## Envelope

```jsonc
{
  "message_id": "uuid",               // required, unique per message (idempotency)
  "schema_version": 1,                // required, must be supported
  "device_id": "device-001",          // required, informational only — NOT identity
  "timestamp": "2026-11-14T18:30:05Z",// required, ISO 8601 with timezone (send/flush time)
  "message_type": "telemetry",        // telemetry|log|status|heartbeat|event|command|command_result
  "sequence_number": 1042,            // optional, >= 0, persisted across host reboots
  "firmware_version": "0.1.0",        // optional
  "hardware_model": "freewili-1-og",  // optional
  "payload": {"samples": [{"ts": "2026-11-14T18:30:01Z", "readings": {"temperature_c": 42.5}}]}
}
```

Unknown envelope fields are rejected. `device_id` must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`
(no `/`, `+`, `#`).

## Payloads

| message_type | payload |
| --- | --- |
| `telemetry` | `samples`: 1–32 items ordered by `ts`; each `{ts, readings}`, readings ≥1, names `^[a-z][a-z0-9_]{0,63}$`, values number/bool/string (no nesting). Host batches per 5 s window or at 32 samples (decision #6). |
| `log` | `level` (debug…critical), `message` (≤4096), `logger?` |
| `status` | `state` (booting/online/busy/degraded/error/shutting_down), `uptime_s?`, `detail?`. `degraded` = host online, board unreachable over USB. |
| `heartbeat` | `uptime_s` |
| `event` | `name` (`^[a-z][a-z0-9_]{0,63}$`), `severity` (info/warning/error), `detail?`, `data` (scalars) |
| `command` | `command_id`, `name` (`^[a-z][a-z0-9_]{0,63}$`), `args` (scalars), `expires_at?` |
| `command_result` | `command_id`, `status` (succeeded/failed/rejected), `detail?`, `output` |

## Topics

`devices/{device_id}/{channel}`

| channel | direction | message types |
| --- | --- | --- |
| `telemetry` | device → cloud | telemetry |
| `logs` | device → cloud | log |
| `status` | device → cloud | status, heartbeat |
| `events` | device → cloud | event |
| `responses` | device → cloud | command_result |
| `commands` | cloud → device | command |

## Rules

- **Identity.** The IoT policy only lets a connection use topics under its own thing name, so the
  device id is taken from the topic. A payload `device_id` that differs is rejected
  (`identity_mismatch`).
- **Delivery is at-least-once.** Consumers deduplicate on `(device_id, message_id)`. The key is
  claimed only after validation succeeds.
- **Ordering is not guaranteed.** Older observations never move `last_seen_at` backwards.
- **Gap detection.** `sequence_number` is one per published message (a telemetry batch is one
  message) and persists across host reboots (decision #14), so a jump means lost messages.
  Ingest records a `sequence_gap` event and keeps processing; it never rejects on gaps.
- **Limits.** Raw message ≤ 32 KiB, payload ≤ 16 KiB (IoT Core's hard limit is 128 KiB).
- **Rejections are permanent** and typed: `too_large`, `malformed_json`, `unsupported_version`,
  `invalid_envelope`, `invalid_payload`, `identity_mismatch`, `wrong_channel`. Rejected messages are
  acknowledged (not retried) and quarantined with their reason (S3 `rejected/`), never silently
  dropped. (TODO: CloudWatch metric.)
- **Raw vs normalised.** Raw bodies are retained separately (S3 `raw/`) from normalised records.
- **Commands** are named and allowlisted on the host. There is no shell/exec command. They expire
  30 s after creation; a device can only complete its own commands.
- **Python 3.10.** This package runs on the host (CPython 3.10+), so no 3.11+ features; use
  `device_protocol.compat` for `StrEnum`/`UTC`. CI runs its tests on 3.10.

## Versioning

- Adding an optional field: same version.
- Removing/renaming/retyping a field or changing meaning: bump `CURRENT_SCHEMA_VERSION`, add it
  to `SUPPORTED_SCHEMA_VERSIONS`, keep accepting the previous version until boards are upgraded.
- Messages with an unsupported version are rejected with `unsupported_version` before any other
  parsing.
- After any change run `uv run python scripts/export_contracts.py` (CI checks for drift).
