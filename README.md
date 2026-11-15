# CS-Dropouts

### Builderwars

A cloud-connected hardware collaboration platform: Python-powered development boards stream
telemetry, logs and status to the cloud; users create projects, register boards, collaborate in
shared sessions, and (later) work with an AI assistant that can propose — never silently apply —
code and firmware changes.

> **Status: MVP in prod.** The web dashboard runs at <https://builderwars.jimweaver.com>, with
> sign-in, projects, devices and a live device page. Boards reach it through the `builderwars`
> CLI, which uploads as the signed-in user. AI, firmware builds and job execution are still
> stubs. See [What is not implemented](#what-is-not-implemented).

## Where to look

Each area has its own README with setup, commands and internals:

| Area | Folder | README |
| --- | --- | --- |
| HTTP API (FastAPI on Lambda) | `apps/api/` | [apps/api/README.md](apps/api/README.md) |
| Workers (ingest, commands, jobs) | `apps/workers/` | [apps/workers/README.md](apps/workers/README.md) |
| Web dashboard (React + Vite) | `apps/web/` | [apps/web/README.md](apps/web/README.md) |
| Host runtime + `builderwars` CLI internals | `device/` | [device/README.md](device/README.md) |
| Shared Python packages | `packages/` | [packages/README.md](packages/README.md) |
| AWS infrastructure (CDK) | `infrastructure/` | [infrastructure/README.md](infrastructure/README.md) |
| Deploying prod end to end | `docs/` | [docs/deployment-guide.md](docs/deployment-guide.md) |

## Repository layout

```text
apps/
  api/          FastAPI app (API Gateway + Lambda)           -> package bw-api, import `api`
  workers/      device-message ingest + job workers          -> bw-workers, `workers`
  web/          React + TypeScript (Vite) frontend
packages/
  device_protocol/  versioned device<->cloud message contract -> bw-device-protocol
  domain/           framework-free domain models and rules    -> bw-domain
  application/      services + ports (+ in-memory and PostgreSQL adapters) -> bw-application
  ai/               controlled AI tool boundary (stubs)       -> bw-ai-platform, `ai_platform`
  aws/              AWS adapters for the ports (S3, SQS, IoT, AppSync) -> bw-aws-adapters, `aws_adapters`
device/         host-PC runtime for the FREE-WILi + `builderwars` CLI -> bw-board-runtime, `board_runtime`
infrastructure/ AWS CDK (Python)
contracts/      GENERATED JSON Schemas / OpenAPI + device message fixtures
tests/          unit / contract / integration / end_to_end
docs/           architecture, protocol, security, deployment, open decisions, ADRs
scripts/        export_contracts.py, build_web_prod.sh
docker/         api / worker images (local use)
```

Dependency direction: `api`, `workers` → `aws_adapters`, `application` → `domain`, `device_protocol`.
`board_runtime` → `device_protocol` only. Domain/application code never imports AWS SDKs.

## The `builderwars` CLI

`builderwars` runs on the computer your FREE-WILi board is plugged into. It checks the board,
runs the host runtime, and sends the board's telemetry and logs to Builderwars.

**Boards have no AWS IoT certificates.** You sign in to the CLI with your own Builderwars
account (the same email and password as the web app), and the CLI uploads as you. Anyone
viewing the device in the web app sees the data live ([ADR 0009](docs/decisions/0009-cli-uploads-instead-of-device-certificates.md)).

### Install

Needs CPython 3.10+. In a clone of this repo (Python 3.12 + uv), `uv sync` installs it and you
run it as `uv run builderwars ...`. On a separate host PC (a Raspberry Pi, an older laptop):

```bash
git clone https://github.com/Qdust41/builderwars && cd builderwars
python3 -m venv ~/.builderwars/venv && . ~/.builderwars/venv/bin/activate
pip install ./packages/device_protocol ./device freewili==0.0.51
builderwars --help
```

`freewili` is the board vendor's library; it is only needed for a real board. To read the
board's serial port on Linux your user must be in `dialout` (Debian/Ubuntu) or `uucp` (Arch);
`builderwars ports` prints the exact command. To update, `git pull` and rerun the `pip install`
line.

### Quick tour

```bash
builderwars login                                        # 1. sign in (once every 30 days)
builderwars devices                                      # 2. find your device's id
builderwars run --cloud --device-id dev_... /dev/ttyACM0 # 3. stream the board live; Ctrl+C stops
builderwars logs dev_...                                 # 4. its cloud logs -> ./dev_...-logs.csv
```

Register the device first in the web app (open a project, add a device), and make sure you have
the **member** role or higher on that project.

### Commands

| Command | What it does |
| --- | --- |
| `builderwars` | What's plugged in, and what to type next |
| `builderwars /dev/ttyACM0` | Step-by-step check of the board on that port (same as `test`) |
| `builderwars test [--watch]` | Check the first board found; `--watch` prints GPIO/button changes live |
| `builderwars ports` | Boards and serial ports, and whether you can open them |
| `builderwars login [--email E] [--api URL]` | Sign in to your Builderwars account |
| `builderwars whoami` / `logout` | Show or forget the saved sign-in |
| `builderwars devices` | The devices in your projects, with their ids |
| `builderwars run [port] [--cloud] [--device-id ID] [-n N] [-i SECONDS]` | Run the host runtime |
| `builderwars upload FILE --device-id ID` | Upload saved telemetry/logs to a device |
| `builderwars logs [DEVICE] [--since T] [--until T] [-o PATH] [--force]` | Download a device's cloud logs as CSV |
| `builderwars sim` | Emit messages from a simulated board as JSON lines |
| `builderwars show` | List the log CSVs stored on this computer |
| `builderwars to-sql CSV` | Turn one local log CSV (or a device id's CSV) into a `.sql` dump; never load it into prod |

Global options go before the command: `--state-dir DIR` (default `~/.builderwars`) and `--debug`
(full tracebacks). Exit codes: 0 success, 1 board check failed, 2 usage or setup error.

### Sign in: `builderwars login`

```bash
builderwars login                    # asks for email + password; prod API by default
builderwars login --email me@example.com
builderwars whoami
```

- The password goes to Cognito only and is never saved. `~/.builderwars/account.json` (mode
  0600) keeps a refresh token for 30 days; after that, `login` again.
- The API defaults to prod (`https://builderwars.jimweaver.com/api`). `--api URL` or
  `BUILDERWARS_API_URL` picks another deployment, and the CLI remembers the last one used.
  `--api http://localhost:8000` uses a local API, where login only asks for a dev user name.

### Find a device: `builderwars devices`

Lists every device in the projects you belong to, with its id (`dev_` + 32 hex characters) and
name. Commands that take `--device-id` need that id; `logs` also accepts the device's name.

### Stream live: `builderwars run --cloud`

```bash
builderwars run --cloud --device-id dev_... /dev/ttyACM0   # the real board
builderwars run --cloud --device-id dev_...                # no port: simulated sensors
builderwars run --cloud --device-id dev_... -n 60 -i 0.5   # stop after 60 samples, 2 per second
```

- **With a port** it reads that FREE-WILi (either of its two ttys works, and `ttyACM0` is
  short for `/dev/ttyACM0`). **Without a port** it uses simulated sensors, unless
  `DEVICE_SENSORS=freewili` or `DEVICE_PORT` says otherwise. That is handy while the board is
  out of action: the dashboard still fills up.
- `--cloud` needs the registered device id (`--device-id` or `DEVICE_ID`).
- Telemetry is batched (every 5 s or 32 samples) and logs, status and heartbeats are sent as
  they happen. If the network or the API is down, it keeps sampling and buffers the last 1000
  messages in memory, then sends them when it can.
- Every log line is also appended to `~/.builderwars/logs/<device id>.csv`
  (`BUILDERWARS_LOG_CSV=off` disables it).
- Without `--cloud`, `run` prints JSON lines to stdout, which you can save and `upload` later.
- Not yet: commands from the dashboard (ping, uptime) don't reach a board in this mode.

### Upload saved data: `builderwars upload`

```bash
builderwars upload dev-local --device-id dev_...       # a log CSV from ~/.builderwars/logs
builderwars run -n 60 > run.jsonl
builderwars upload run.jsonl --device-id dev_...       # JSON lines from run or sim
```

`FILE` is a path, or a device id whose local log CSV to upload. Uploads are idempotent:
messages already stored (for example logs that went up live and are also in the CSV) are
counted as "already uploaded", not stored twice. Files recorded under another id (`dev-local`,
`sim-001`) are re-addressed to the device you upload to. Viewers can't upload; you need the
member role or higher.

### Download logs: `builderwars logs <device>`

```bash
builderwars logs dev_...                                       # -> ./dev_...-logs.csv
builderwars logs "Bench board" --since 2026-11-14 -o bench.csv # by name, from a date
builderwars logs dev_... --since 2026-11-15T09:00 --until 2026-11-15T12:00Z
builderwars logs dev_... -o - | grep error                     # CSV to stdout
builderwars logs dev_... --force                               # replace an existing CSV
builderwars logs                                               # no device: list local CSVs
```

- Writes everything the cloud stored for the device (log lines and device events, oldest
  first) to a CSV with the columns `timestamp, device_id, kind, level, message, message_id`.
- `DEVICE` is a device id or a device name (from `builderwars devices`).
- `--since` (inclusive) and `--until` (exclusive) take a date or a date-time, in local time
  unless it ends in `Z` or has an offset.
- `-o PATH` sets the output file (default `./<device-id>-logs.csv`); `-o -` writes to stdout.
- An existing file is only replaced with `--force`.
- Any project member can run it, viewers included. It pages through
  `GET /devices/{id}/logs/history`, 1000 entries at a time.

More on the host runtime, its environment variables and its modules:
[device/README.md](device/README.md).

## Local development

Prerequisites: Python 3.12+ and [uv](https://docs.astral.sh/uv/) 0.11+, Node.js 22+ and npm.
Docker is optional (for PostgreSQL). No AWS credentials are needed.

```bash
uv sync                                   # .venv with every workspace package + dev tools
cp .env.example .env                      # optional; defaults are already local-safe

uv run uvicorn api.main:app --reload      # API on http://localhost:8000 (in-memory, dev auth)
cd apps/web && npm install && npm run dev # web app on http://localhost:5173

# A simulated board feeding the local dashboard (device id from the web app's device page):
uv run builderwars login --api http://localhost:8000
uv run builderwars run --cloud --device-id dev_...
```

Area details: [API](apps/api/README.md) (PostgreSQL, auth modes),
[workers](apps/workers/README.md), [web](apps/web/README.md),
[host runtime](device/README.md).

## Quality checks

```bash
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy                                            # strict type checking of all packages
uv run pytest                                          # unit, contract, integration, e2e
uv run python scripts/export_contracts.py --check      # generated contracts are current
cd apps/web && npm run typecheck && npm test && npm run build
```

Infrastructure synth and its tests: [infrastructure/README.md](infrastructure/README.md).
CI (`.github/workflows/ci.yml`) runs all of these on every pull request and on `main`.

After changing a protocol model, realtime event or API schema, regenerate the contracts with
`uv run python scripts/export_contracts.py` (and `npm run gen:api` in `apps/web`).

## Deployment

There is one deployed environment, **prod** (us-east-1); there is no staging. **Every merge to
`main` deploys prod** through `.github/workflows/deploy.yml`, after CI passes: all stacks, the
database migrations, the web app, then a health check. Pull requests and other branches never
deploy. The full walkthrough, from an empty AWS account to a board on the dashboard, is
[docs/deployment-guide.md](docs/deployment-guide.md).

## Architecture in one paragraph

A **device** is a host PC wired over USB to a FREE-WILi 1-OG board (with a Bottlenose WiFi
Orca); the host runs `device/` and holds the internet connection. For now the host's user signs
in to the `builderwars` CLI, which posts the board's messages to the API
(`POST /devices/{id}/messages`) as that user; the API feeds them into the same idempotent ingest
pipeline, validated against the shared `device_protocol` contract. A direct MQTT/TLS path to
**AWS IoT Core** with per-device certificates (IoT rule → **SQS** → **workers**) is built but
parked. Users talk to a **FastAPI** app (API Gateway + Lambda) authenticated by **Cognito**; it
owns authorisation. Live updates flow through **AppSync Events** (backend publishes, users
subscribe). Long jobs (AI runs, builds, tests) are queued and will run on **ECS Fargate**.
Metadata lives in **PostgreSQL (RDS)**, artifacts and raw data in **S3**, and the web app on
**CloudFront**. Details: [docs/architecture.md](docs/architecture.md).

## Documentation

- [Deployment guide](docs/deployment-guide.md) — end to end: AWS account, deploy, sign-up, registering a device, connecting a board
- [Architecture](docs/architecture.md) — components, boundaries, data flows
- [Device protocol](docs/device-protocol.md) — envelope, topics, versioning, limits
- [Security](docs/security.md) — identities, authorisation, AI and firmware controls
- [AWS deployment notes](docs/aws-deployment.md) — short command list and cost table
- [Log ingestion spec](docs/log-ingestion-spec.md) — target shape of the cloud log store
- [Product decisions](docs/open-decisions.md) — answered decisions and what the code does with each
- [Spec outline](docs/spec-outline.md) — the specs still to write, in order
- [Architecture decision records](docs/decisions/)

## What is not implemented

| Area | State |
| --- | --- |
| Persistence | PostgreSQL repositories for every port (ADR 0006); in-memory for local/test. In prod a `Migrate` Lambda applies migrations on every deploy. |
| User auth | Cognito email + password with self sign-up (ADR 0005); `X-Dev-User` header locally. Project members are added by email through the API; no members screen yet. Password reset and MFA: TODO. |
| Device connectivity | The signed-in CLI uploads through the API (ADR 0009). MQTT/TLS via `awsiotsdk` is built but parked and has not run against real IoT. Offline buffer: RAM only. |
| Device provisioning | No certificates are created anywhere (parked with the MQTT path). |
| Board I/O | `FreeWiliSensors` reads GPIO + buttons as placeholder readings; not yet run on a real board. Sensor set: spec 02. |
| Device commands | API route, per-device queue, dispatcher and result handling exist, but commands don't reach CLI-connected boards yet. Timeout sweeper and session broadcast: TODO. |
| Realtime | AppSync Events in prod, an in-process hub locally. The membership check on subscribe: TODO. |
| Job execution | No executors; queued jobs fail with "not implemented". Fargate: TODO. |
| AI | Tool definitions, approval gate, redaction, run records, provider config. No client, no executors, no default model (spec 08). |
| Firmware | Model, job types and host-side sha256 check only. No build, flashing or deployment (spec 09). |
| Ingest rate limiting | Not implemented (burst 10 msg/s, sustained 60 msg/min per device planned). |
| Collaborative editing | Deliberately deferred (CRDT/Yjs later if needed). |
