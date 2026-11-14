# Architecture

## Components

```text
 ┌──────────┐  MQTT/TLS (X.509)  ┌──────────────┐  topic rule  ┌──────────────┐   ┌──────────────────┐
 │  Board   │ ─────────────────▶ │ AWS IoT Core │ ───────────▶ │ SQS ingest   │──▶│ ingest worker    │
 │ runtime  │ ◀───────────────── │              │              │ (+DLQ)       │   │ (Lambda)         │
 └──────────┘   commands topic   └──────▲───────┘              └──────────────┘   └────────┬─────────┘
                                        │ publish (authorised)                             │
 ┌──────────┐  HTTPS + Cognito JWT ┌────┴─────────┐  enqueue  ┌──────────────┐   ┌─────────▼────────┐
 │  Web app │ ───────────────────▶ │ FastAPI      │ ────────▶ │ SQS jobs     │──▶│ job worker       │
 │ (React)  │                      │ (API GW +    │           │ (+DLQ)       │   │ (Lambda/Fargate) │
 └────▲─────┘                      │  Lambda)     │           └──────────────┘   └─────────┬────────┘
      │ subscribe (Cognito)        └────┬─────────┘                                        │
 ┌────┴──────────────┐  publish (IAM)   │            ┌────────────────┐  ┌──────────────┐  │
 │ AppSync Events    │ ◀────────────────┴────────────│ PostgreSQL     │  │ S3 artifacts │◀─┘
 └───────────────────┘                               │ (RDS)          │  │ + raw data   │
                                                     └────────────────┘  └──────────────┘
```

## Boundaries (and where they live in code)

| Boundary | Rule | Code |
| --- | --- | --- |
| Device → cloud | Only via IoT Core; identity = authorised topic, never the payload | `device_protocol`, `application.services.device_ingest`, `infrastructure/stacks/iot.py` |
| User → application | FastAPI owns authentication and authorisation | `apps/api`, `application.services.authorization` |
| User ↔ user realtime | AppSync Events; notifications only, not the source of truth | `application.realtime`, `apps/web/src/realtime` |
| Application → device | Only application services publish commands, after `SEND_DEVICE_COMMAND` check | `application.ports.DeviceCommandPublisher` (adapter TODO) |
| Long-running work | Queued jobs, never inside request handlers | `application.services.jobs`, `workers.handlers.background_job` |
| Business logic | No AWS SDK imports in `domain`/`application`; adapters implement ports | `application.ports`, `application.adapters` |
| Device protocol | One versioned source of truth; JSON contracts generated from it | `packages/device_protocol`, `contracts/` |

## Layers

- **domain** — dataclasses + rules (role matrix, job state machine, out-of-order device
  observations, firmware artifact invariants). No dependencies.
- **application** — services that enforce authorisation and orchestrate ports; realtime event
  contract; in-memory adapters for local/test only.
- **apps** — delivery mechanisms (HTTP API, queue workers) that build services from adapters.
- **device** — runtime that only depends on the protocol package.
- **ai** — tool catalogue + gate; depends on domain only.

## Key flows

**Device telemetry.** Board builds an envelope (`MessageFactory`) → publishes to
`devices/{id}/telemetry` → IoT rule wraps `{topic, received_at_ms, body_b64}` into SQS → ingest
worker: parse topic → decode/validate → topic/device-id match → claim idempotency key →
store raw → write normalised record → update device last-seen. Invalid messages are
acknowledged and logged (never retried); transient failures go back to the queue and to the DLQ
after 5 attempts.

**Job.** `POST /projects/{id}/jobs` → authorise → persist `queued` → enqueue job id → worker
loads job → skips unless still `queued` (idempotent) → runs executor → `succeeded`/`failed`.

**Session.** `POST /projects/{id}/sessions` → authorise → persist → publish
`project.activity` on `projects/{project_id}/sessions/{session_id}`. Clients fetch the channel
from `GET /sessions/{id}/channel` (membership checked) and refetch state after reconnects.

## Deliberate deferrals

- Simultaneous code editing (CRDT/Yjs) — only if "multiplayer" requires it (open decision #4).
- Fargate workers — once a job type actually exceeds Lambda limits.
- Device shadow, IoT Jobs-based OTA — with the firmware update design (open decision #9).
