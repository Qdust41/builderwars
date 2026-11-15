# CS-Dropouts

### Builderwars

A cloud-connected hardware collaboration platform: Python-powered development boards stream
telemetry, logs and status to the cloud; users create projects, register boards, collaborate in
shared sessions, and (later) work with an AI assistant that can propose — never silently apply —
code and firmware changes.

> **Status: scaffold.** The structure, contracts, local development loop and safety boundaries
> are in place. Most AWS adapters, auth, persistence, firmware builds and AI execution are
> stubs. Nothing is deployed. See [What is not implemented](#what-is-not-implemented).

## Repository layout

```text
apps/
  api/          FastAPI app (Lambda + Mangum later)          -> package bw-api, import `api`
  workers/      device-message ingest + job workers          -> bw-workers, `workers`
  web/          React + TypeScript (Vite) frontend
packages/
  device_protocol/  versioned device<->cloud message contract -> bw-device-protocol
  domain/           framework-free domain models and rules    -> bw-domain
  application/      services + ports (+ in-memory adapters)   -> bw-application
  ai/               controlled AI tool boundary (stubs)       -> bw-ai-platform, `ai_platform`
device/         host-PC runtime for the FREE-WILi + simulator -> bw-board-runtime, `board_runtime`
infrastructure/ AWS CDK (Python) — synth only
contracts/      GENERATED JSON Schemas / OpenAPI + device message fixtures
tests/          unit / contract / integration / end_to_end
docs/           architecture, protocol, security, deployment, open decisions, ADRs
scripts/        export_contracts.py
docker/         api / worker images (local use)
```

Dependency direction: `api`, `workers` → `application` → `domain`, `device_protocol`.
`board_runtime` → `device_protocol` only. Domain/application code never imports AWS SDKs.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (0.11+) for development. The host runtime
  that drives a real board only needs Python 3.10+ (see [device/README.md](device/README.md)).
- Node.js 22+ and npm (frontend, and the CDK CLI if you use it)
- Docker is optional

No AWS credentials are needed for anything below.

## Quick start

```bash
uv sync                                   # create .venv with every workspace package + dev tools
cp .env.example .env                      # optional; defaults are already local-safe

# API on http://localhost:8000 (in-memory data, dev-header auth)
uv run uvicorn api.main:app --reload
curl localhost:8000/health
curl -X POST localhost:8000/projects -H 'X-Dev-User: alice' -H 'Content-Type: application/json' -d '{"name":"Rover"}'

# Board simulator -> local worker harness (validates, deduplicates, records)
uv run python -m board_runtime.simulator --count 40 > /tmp/messages.jsonl
uv run python -m workers.main /tmp/messages.jsonl

# Host runtime loop with simulated sensors (prints JSON lines; Ctrl-C to stop)
DEVICE_ID=dev-local-001 BUILDERWARS_STATE_DIR=/tmp/bw-state uv run python -m board_runtime.main --samples 12

# Frontend on http://localhost:5173 (proxies /api -> :8000)
cd apps/web && npm install && npm run dev
```

Interactive API docs: http://localhost:8000/docs. Local auth is the `X-Dev-User` header; the
frontend sends `VITE_DEV_USER` (see `apps/web/.env.example`).

## Quality checks

```bash
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy                                            # strict type checking of all packages
uv run pytest                                          # unit, contract, integration, e2e
uv run python scripts/export_contracts.py --check      # generated contracts are current

cd apps/web && npm run typecheck && npm test && npm run build

cd infrastructure
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py                               # synth dev -> cdk.out/ (no AWS calls)
CDK_CONTEXT_JSON='{"env":"prod"}' .venv/bin/python app.py
.venv/bin/python -m pytest tests                      # synth assertions
# or: npx aws-cdk@2 synth -c env=dev
```

CI (`.github/workflows/ci.yml`) runs all of the above on every pull request.

After changing a protocol model, realtime event or API schema, regenerate the contracts:
`uv run python scripts/export_contracts.py`.

## Architecture in one paragraph

A **device** is a host PC wired over USB to a FREE-WILi 1-OG board (with a Bottlenose WiFi
Orca); the host runs `device/` and holds the internet connection. Hosts talk MQTT/TLS to **AWS IoT Core** with per-device certificates; an IoT rule forwards
device-to-cloud topics to **SQS**, where idempotent **workers** validate messages against the
shared `device_protocol` contract and record them. Users talk to a **FastAPI** app (API Gateway +
Lambda) authenticated by **Cognito**; it owns authorisation and is the only path for commands to
devices. Session notifications flow through **AppSync Events** (backend publishes, users
subscribe). Long jobs (AI runs, builds, tests) are queued and will run on **ECS Fargate**.
Metadata in **PostgreSQL (RDS)**, artifacts and raw data in **S3**. Details:
[docs/architecture.md](docs/architecture.md).

## Documentation

- [Architecture](docs/architecture.md) — components, boundaries, data flows
- [Device protocol](docs/device-protocol.md) — envelope, topics, versioning, limits
- [Security](docs/security.md) — identities, authorisation, AI and firmware controls
- [AWS deployment (future)](docs/aws-deployment.md) — steps, costs, testing against real IoT
- [Deployment guide](docs/deployment-guide.md) — end to end: AWS account, deploy, sign-up, device provisioning, connecting a board
- [Product decisions](docs/open-decisions.md) — answered decisions and what the scaffold does with each
- [Spec outline](docs/spec-outline.md) — the specs still to write, in order
- [Architecture decision records](docs/decisions/)

## What is not implemented

| Area | State |
| --- | --- |
| Persistence | In-memory only (local/test). PostgreSQL repositories: TODO. |
| User auth | `X-Dev-User` header locally; `AUTH_MODE=cognito` verifies Cognito JWTs (ADR 0005). Project members are added by email. |
| Device connectivity | MQTT/TLS via `awsiotsdk` implemented but not yet run against a real IoT endpoint (SDK handles reconnects). Offline buffer: RAM only. |
| Board I/O | `FreeWiliSensors` (vendor `freewili` package) reads GPIO + buttons as placeholder readings; not yet run on a real board. Sensor set: spec 02. |
| Device provisioning | Not implemented (no certificates created anywhere; spec 03). |
| Device commands | API route, per-device queue (32 pending, 30 s expiry), dispatcher handler and result handling exist with in-memory adapters. AWS adapters, timeout sweeper and session broadcast: TODO. |
| Workers in AWS | Lambda handlers raise `NotImplementedError` until AWS adapters exist. |
| Job execution | No executors; queued jobs fail with "not implemented". Fargate: TODO. |
| Realtime | Recording publisher locally; AppSync client/publisher: TODO; membership check on subscribe: TODO. |
| AI | Tool definitions, approval gate, redaction, run records, provider config (OpenAI-compatible / Bedrock). No client, no executors, no default model (spec 08). |
| Firmware | Model, job types and host-side sha256 check only. No build, flashing or deployment (spec 09). |
| Ingest rate limiting | Not implemented (burst 10 msg/s, sustained 60 msg/min per device planned). |
| Lambda packaging | CDK assets are source-only; dependency bundling TODO. |
| Collaborative editing | Deliberately deferred (CRDT/Yjs later if needed). |
