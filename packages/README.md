# Shared packages

Workspace libraries used by the API, the workers and the host runtime. Dependency direction:
`api`, `workers` → `aws_adapters`, `application` → `domain`, `device_protocol`.
`board_runtime` depends on `device_protocol` only. Domain and application code never import AWS
SDKs (ADR 0001, ADR 0003).

| Folder | Package / import | What it is |
| --- | --- | --- |
| `device_protocol/` | `bw-device-protocol` / `device_protocol` | Versioned device↔cloud message contract (envelope, message types, limits). Source of truth for `contracts/` (ADR 0002). Must stay CPython 3.10-compatible: use `device_protocol.compat` for `StrEnum`/`UTC`. |
| `domain/` | `bw-domain` / `domain` | Framework-free models and rules: projects, roles, devices, sessions, jobs. |
| `application/` | `bw-application` / `application` | Services and ports, plus in-memory and PostgreSQL adapters (`application.adapters.postgres`, migrations included; ADR 0006). |
| `aws/` | `bw-aws-adapters` / `aws_adapters` | AWS implementations of the ports: S3, SQS, IoT data plane, AppSync Events publisher. |
| `ai/` | `bw-ai-platform` / `ai_platform` | Controlled AI tool boundary: tool definitions, approval gate, redaction, provider config. No client yet (spec 08). |

Protocol details: [docs/device-protocol.md](../docs/device-protocol.md). After changing a
protocol model or realtime event, run `uv run python scripts/export_contracts.py`.

Apply PostgreSQL migrations by hand with `uv run python -m application.adapters.postgres`
(needs `DATABASE_URL`).
