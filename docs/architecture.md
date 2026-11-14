# Architecture

## Components

A **device** is a host PC + FREE-WILi 1-OG pair (decisions #1–#3, ADR 0004). The host runs
the CPython 3.10+ runtime in `device/`, talks to the board over USB serial, and is the only
thing that connects to AWS. Scale: < 10 devices, telemetry batched to one message per 5 s,
us-east-1, free tier.


```text
 ┌──────────┐  MQTT/TLS (X.509)  ┌──────────────┐  topic rule  ┌──────────────┐   ┌──────────────────┐
 │ Host PC  │ ─────────────────▶ │ AWS IoT Core │ ───────────▶ │ SQS ingest   │──▶│ ingest worker    │
 │ runtime  │ ◀───────────────── │              │              │ (+DLQ)       │   │ (Lambda)         │
 └────┬─────┘   commands topic   └──────▲───────┘              └──────────────┘   └────────┬─────────┘
      │ USB serial (freewili)           │ publish (dispatcher worker, via SQS commands queue)
 ┌────┴─────┐                           │
 │FREE-WILi │  + Bottlenose WiFi Orca (network adapter for the host link, not a cloud client)
 └──────────┘
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
| Application → device | API checks `device:command`, records the command and queues it; the dispatcher worker publishes it to IoT Core | `application.services.commands`, `workers.handlers.device_command` (AWS adapters TODO) |
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

**Device telemetry.** Host samples the board ~1/s and batches samples (5 s or 32) → builds an
envelope (`MessageFactory`, persisted sequence number) → publishes to
`devices/{id}/telemetry` → IoT rule wraps `{topic, received_at_ms, body_b64}` into SQS → ingest
worker: parse topic → decode/validate → topic/device-id match → claim idempotency key →
store raw → write normalised record → update device last-seen. Invalid messages are
acknowledged and logged (never retried); transient failures go back to the queue and to the DLQ
after 5 attempts.

**Job.** `POST /projects/{id}/jobs` → authorise → persist `queued` → enqueue job id → worker
loads job → skips unless still `queued` (idempotent) → runs executor → `succeeded`/`failed`.

**Device command.** `POST /projects/{id}/devices/{device_id}/commands` → authorise
`device:command` (role-based, no lock) → reject if 32 already pending → persist `queued` →
SQS commands queue → dispatcher publishes to `devices/{id}/commands` (or times it out after
30 s) → host runs the allowlisted handler → `command_result` on `devices/{id}/responses` →
ingest completes the record. Session broadcast of results: TODO.

**Session.** `POST /projects/{id}/sessions` → authorise → persist → publish
`project.activity` on `projects/{project_id}/sessions/{session_id}`. Clients fetch the channel
from `GET /sessions/{id}/channel` (membership checked) and refetch state after reconnects.

## Deliberate deferrals

- Simultaneous code editing (CRDT/Yjs) — only if "multiplayer" requires it (open decision #4).
- Fargate workers — once a job type actually exceeds Lambda limits.
- Device shadow, IoT Jobs-based OTA — with the firmware update design (open decision #9).
