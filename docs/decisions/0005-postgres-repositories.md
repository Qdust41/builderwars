# 0005 — PostgreSQL repositories: psycopg 3, raw SQL, forward-only SQL migrations

Status: accepted (2026-11-14, workstream A)

## Context
Every repository port in `application.ports.repositories` had only an in-memory adapter, so the
API and workers could not run outside `APP_ENV=local|test` (ADR 0003). Prod uses RDS
PostgreSQL 16 on `db.t4g.micro` (decision #12), reached from Lambda. Scale is under 10 boards
(decision #6), so one database holds everything for the MVP.

## Decision
- **Driver:** psycopg 3 with binary wheels (`psycopg[binary]`, no system libpq) and
  `psycopg_pool`. No ORM: the domain models are frozen dataclasses, and each adapter is a few
  explicit SQL statements in `application/adapters/postgres/repositories.py`.
- **Transactions:** one short transaction per repository call. Cross-repository atomicity
  (a transactional outbox for jobs and commands) is workstream G.
- **Migrations:** numbered SQL files in `application/adapters/postgres/migrations/`, applied in
  order by `python -m application.adapters.postgres`, each in its own transaction under an
  advisory lock, recorded in `schema_migrations`. Forward-only: a fix is a new migration. The API
  and workers check at startup that no migration is pending and refuse to start otherwise; they
  never migrate on their own.
- **Ids** stay domain-minted text (`prj_…`, protocol UUIDs). Enum columns carry CHECK
  constraints that mirror the domain enums.
- **Integrity:** project-side tables have foreign keys to `projects` (and commands to
  `devices`). Ingest tables (`processed_messages`, `device_sequences`, `raw_device_messages`,
  `quarantined_device_messages`, `device_telemetry`, `device_logs`, `device_events`) have none,
  because ingest must record or quarantine messages from devices the registry does not know.
- **Raw messages:** `raw_device_messages` keeps the body (bytea, at most 32 KiB) plus size and
  sha256. When the S3 raw store exists (workstream C), the body can move to S3 `raw/` and the row
  keeps the metadata, in a new migration.
- **Telemetry** (open decision #6) goes in PostgreSQL tables with a jsonb `metrics` column,
  which is ample for 10 boards x 12 msg/min. Retention is still for spec 04.
- **Configuration:** `REPOSITORY_BACKEND=postgres` plus `DATABASE_URL`. Sessions run in UTC.
- **Tests:** the shared `world` and `ingest` fixtures, the API tests and a port contract suite
  run once per backend. The PostgreSQL run needs `TEST_DATABASE_URL` (a disposable database whose
  tables are truncated between tests) and is skipped without it; CI provides one.

## Consequences
- Deployed environments still cannot start: the SQS queues and the AppSync publisher are
  missing, so `build_container` refuses non-local environments until workstream C adds them.
- Running migrations against RDS needs a step inside the VPC (a one-off Lambda or task);
  workstream C owns it, along with turning the RDS secret into `DATABASE_URL` or IAM auth.
- Each new table or column is a new numbered SQL file and a matching adapter change.
