# Open product decisions

These are unresolved. The scaffold avoids guessing; where code needed *some* default, the
provisional choice and where it lives are noted. Please record answers here (or as ADRs in
`docs/decisions/`).

| # | Question | Provisional assumption in the scaffold | Affects |
| --- | --- | --- | --- |
| 1 | Exact board hardware, OS, Python version, hardware interfaces? | CPython ≥ 3.12 on the board; `SensorReader` interface with simulated sensors; MQTT library not chosen. If MicroPython, pydantic must be replaced on-device by a validator generated from `contracts/device`. | `device/`, `device_protocol` |
| 2 | Board connects directly to AWS, or via a local gateway? | Direct to IoT Core over MQTT/TLS. | IoT policy, provisioning |
| 3 | Do users also connect to the board over USB / local network? | Not supported. | Device runtime, security |
| 4 | "Multiplayer" = shared viewing/control, simultaneous code editing, or both? | Shared viewing + notifications via AppSync Events. No concurrent editing. | Realtime, possible CRDT layer |
| 5 | Can several users control one board at once? Locking? | Only owners/admins hold `device:command`; no lock/lease model yet. | Commands, sessions |
| 6 | Number of boards, message rates, payload sizes, retention? | ≤32 KiB messages, ≤16 KiB payloads; raw data expires 30/90/365 days (dev/staging/prod). | Protocol limits, storage, cost |
| 7 | Logs: continuous streams, periodic telemetry, events, or file uploads? | Discrete `log` messages over MQTT; no file uploads. | Protocol, S3 layout |
| 8 | AI provider/model, privacy requirements, may project data go to external providers? | No provider chosen; `ModelProvider` interface only; redaction helper. | `packages/ai` |
| 9 | Firmware toolchain, signing, update mechanism, rollback? | Model only (`FirmwareArtifact`); nothing builds or deploys. | Jobs, workers, device |
| 10 | User roles, project sharing, org/team boundaries? | Per-project roles owner/admin/member/viewer; no orgs; no invite flow; Cognito self sign-up off. | Authz, Cognito |
| 11 | Region, environment strategy, budget, data residency? | dev/staging/prod configs; region from `CDK_DEFAULT_REGION`; RDS only in staging/prod. | Infrastructure |

Additional questions found while scaffolding:

| # | Question | Notes |
| --- | --- | --- |
| 12 | Is RDS acceptable cost-wise for the first shared environment, or should dev use something else? | ADR 0003 forbids silently swapping in a different production data model. |
| 13 | Who receives operational alarms? | DLQ/API alarms exist without actions. |
| 14 | Should the device sequence number persist across reboots (gap detection)? | Currently per process. |
