# API (`bw-api`, import `api`)

FastAPI app for projects, members, devices, sessions, jobs and realtime events. In prod it runs
on API Gateway + Lambda (`api.lambda_handler.handler`, via Mangum) and the browser reaches it
same-origin at `https://builderwars.jimweaver.com/api/*` through CloudFront. It owns
authorisation, and it is the only path for commands to devices.

## Run it locally

From the repo root, after `uv sync`:

```bash
uv run uvicorn api.main:app --reload       # http://localhost:8000, in-memory data, dev auth
curl localhost:8000/health
curl -X POST localhost:8000/projects -H 'X-Dev-User: alice' \
  -H 'Content-Type: application/json' -d '{"name":"Rover"}'
```

Interactive docs: <http://localhost:8000/docs>. Settings come from the environment or `.env`
(see `.env.example`).

### On PostgreSQL

```bash
docker compose --profile postgres up -d db   # or point DATABASE_URL at any Postgres 16
export DATABASE_URL=postgresql://builderwars:builderwars-local@localhost:5432/builderwars
uv run python -m application.adapters.postgres            # apply migrations
REPOSITORY_BACKEND=postgres uv run uvicorn api.main:app --reload
```

The API refuses to start if the schema is behind. In prod the `Migrate` Lambda applies
migrations on every deploy (ADR 0006, ADR 0007).

## Settings that matter

| Variable | Values | Notes |
| --- | --- | --- |
| `APP_ENV` | `local`, `test`, `dev`, `prod` | `local`/`test` allow the shortcuts below and the `/local/*` routes |
| `AUTH_MODE` | `dev-header`, `cognito` | `dev-header` trusts `X-Dev-User` and is refused outside `local`/`test` |
| `REPOSITORY_BACKEND` | `memory`, `postgres` | `memory` is refused outside `local`/`test` |
| `COGNITO_REGION`, `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID` | ids | needed for `AUTH_MODE=cognito`; the CDK stack sets them in AWS |
| `DATABASE_URL` | Postgres URL | locally; in AWS the Lambda reads the RDS secret and connects over TLS |
| `CORS_ALLOW_ORIGINS` | JSON list | only for local cross-origin use; prod is same-origin |

With `AUTH_MODE=cognito` the API verifies Cognito access tokens (ADR 0005).

## Routes worth knowing

- `GET /health`, `GET /client-config` (public: the Cognito ids the CLI needs to sign in).
- `POST /devices/{id}/messages`: board messages uploaded by a signed-in member, the path the
  `builderwars` CLI uses (ADR 0009). Same idempotent ingest as the worker pipeline; device
  events are published to AppSync.
- `GET /devices/{id}/logs/history`: all log lines and device events for a device, oldest first,
  with `since`/`until` and a `next_cursor` (up to 1000 per page). Behind `builderwars logs`.
- `/local/*` (local/test only): the in-process realtime stream and the `local-api` device
  transport (ADR 0008).

## Code layout

- `main.py` builds the app; `routes/` one module per resource; `schemas.py` request/response
  models; `auth.py` dev-header and Cognito auth; `dependencies.py` wires services and
  repositories from `settings.py`.
- Business rules live in `packages/application` and `packages/domain`, not here.

After changing a request or response model, regenerate the contracts:
`uv run python scripts/export_contracts.py`, then `npm run gen:api` in `apps/web`.
