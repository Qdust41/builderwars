# Device protocol (schema_version 1)

Source of truth: `packages/device_protocol`. Generated JSON Schemas:
`contracts/device/envelope.v1.schema.json`, `contracts/device/payloads.v1.schema.json`.
Example messages: `contracts/device/fixtures/valid/`, rejected examples in `.../invalid/`
(file names start with the expected rejection reason).

**Payload schemas are provisional** until the board and its sensors are chosen.

## Envelope

```jsonc
{
  "message_id": "uuid",               // required, unique per message (idempotency)
  "schema_version": 1,                // required, must be supported
  "device_id": "device-001",          // required, informational only — NOT identity
  "timestamp": "2026-11-14T18:30:00Z",// required, ISO 8601 with timezone
  "message_type": "telemetry",        // telemetry|log|status|command|command_result|heartbeat
  "sequence_number": 1042,            // optional, >= 0, per-boot counter
  "firmware_version": "0.1.0",        // optional
  "hardware_model": "devboard-x",     // optional
  "payload": { "temperature_c": 42.5 }
}
```

Unknown envelope fields are rejected. `device_id` must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`
(no `/`, `+`, `#`).

## Payloads

| message_type | payload |
| --- | --- |
| `telemetry` | flat object, ≥1 metric, values are number/bool/string (no nesting) |
| `log` | `level` (debug…critical), `message` (≤4096), `logger?` |
| `status` | `state` (booting/online/busy/error/shutting_down), `uptime_s?`, `detail?` |
| `heartbeat` | `uptime_s` |
| `command` | `command_id`, `name` (`^[a-z][a-z0-9_]{0,63}$`), `args` (scalars), `expires_at?` |
| `command_result` | `command_id`, `status` (succeeded/failed/rejected), `detail?`, `output` |

## Topics

`devices/{device_id}/{channel}`

| channel | direction | message types |
| --- | --- | --- |
| `telemetry` | device → cloud | telemetry |
| `logs` | device → cloud | log |
| `status` | device → cloud | status, heartbeat |
| `responses` | device → cloud | command_result |
| `commands` | cloud → device | command |

## Rules

- **Identity.** The IoT policy only lets a connection use topics under its own thing name, so the
  device id is taken from the topic. A payload `device_id` that differs is rejected
  (`identity_mismatch`).
- **Delivery is at-least-once.** Consumers deduplicate on `(device_id, message_id)`. The key is
  claimed only after validation succeeds.
- **Ordering is not guaranteed.** Older observations never move `last_seen_at` backwards.
- **Limits.** Raw message ≤ 32 KiB, payload ≤ 16 KiB (IoT Core's hard limit is 128 KiB).
- **Rejections are permanent** and typed: `too_large`, `malformed_json`, `unsupported_version`,
  `invalid_envelope`, `invalid_payload`, `identity_mismatch`, `wrong_channel`. Rejected messages are
  acknowledged and logged, not retried. (TODO: quarantine store + metric.)
- **Raw vs normalised.** Raw bodies are retained separately (S3 `raw/`) from normalised records.
- **Commands** are named and allowlisted on the board. There is no shell/exec command.

## Versioning

- Adding an optional field: same version.
- Removing/renaming/retyping a field or changing meaning: bump `CURRENT_SCHEMA_VERSION`, add it
  to `SUPPORTED_SCHEMA_VERSIONS`, keep accepting the previous version until boards are upgraded.
- Messages with an unsupported version are rejected with `unsupported_version` before any other
  parsing.
- After any change run `uv run python scripts/export_contracts.py` (CI checks for drift).
