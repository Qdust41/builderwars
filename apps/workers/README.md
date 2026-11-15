# Workers (`bw-workers`, import `workers`)

Idempotent workers that validate device messages against the `device_protocol` contract and
record them, dispatch device commands, and run background jobs.

## Run locally

```bash
uv run python -m board_runtime.simulator --count 40 > /tmp/messages.jsonl
uv run python -m workers.main /tmp/messages.jsonl        # or pipe JSON lines on stdin
```

The local harness validates, deduplicates and records into memory. With
`REPOSITORY_BACKEND=postgres DATABASE_URL=...` it stores into PostgreSQL instead.

## In AWS

`workers.aws_runtime` wires these Lambda handlers (deployed by the Workers stack):

| Handler (`workers.main.…`) | Trigger | Does |
| --- | --- | --- |
| `device_message_lambda_handler` | ingest SQS queue | records telemetry/logs/status, stores raw and rejected bodies in S3, publishes device events to AppSync |
| `command_dispatch_lambda_handler` | commands SQS queue | publishes commands to `devices/<id>/commands` on IoT |
| `job_lambda_handler` | jobs SQS queue | runs background jobs (no executors yet; jobs fail with "not implemented") |
| `autofix_lambda_handler` | auto-fix SQS queue | one run per message: device logs + GitHub repo -> LLM -> pull request (ADR 0012) |
| `migrate_lambda_handler` | invoked by the deploy | applies database migrations |

Today boards reach ingest through the API (`POST /devices/{id}/messages`, ADR 0009), which uses
the same ingest service. The IoT rule → SQS path is deployed but has no certificate-holding
devices yet.

## Code layout

- `handlers/` one handler per message type (`device_message`, `device_command`,
  `background_job`).
- `consumers/` the local JSON-lines harness and the SQS batch consumer (partial batch failures).
- `settings.py` refuses in-memory storage outside local/test, like the API.
