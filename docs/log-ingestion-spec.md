# Log ingestion system — target shape (spec only)

> **Status: specification, not implemented.** This document describes what a cloud system
> would have to look like in order to store the device logs that the host runtime writes to
> local CSV files (`builderwars-logs`) and converts to `.sql` dumps for upload. Nothing in
> the repository implements it; when it is built, this document is the contract it must
> satisfy. It aligns with `docs/architecture.md`, `docs/aws-deployment.md`, and the decided
> values in `docs/open-decisions.md` (#6, #10, #11, #12, #14).

## 1. What the data is

Every `log` message the runtime sends to the cloud (MQTT topic `devices/{device_id}/logs`,
payload type `LogPayload`) is also appended locally to `<state-dir>/logs/<device_id>.csv`
(one row per message, columns in `board_runtime/logging/csv_sink.py:CSV_COLUMNS`):

| CSV column | Meaning | Notes |
| --- | --- | --- |
| `timestamp` | Envelope timestamp, ISO-8601 UTC | authoritative time of the log |
| `message_id` | Envelope `message_id` (UUID) | **natural key / dedup key** |
| `schema_version` | Protocol schema version (int) | versioned contract |
| `device_id` | Envelope device id | must match the auth-derived id (see §5) |
| `sequence_number` | Persisted monotonic sequence | may be empty (fresh host); gaps recorded, never rejected (decision #14) |
| `firmware_version` | Firmware of the sending host runtime | may be empty |
| `hardware_model` | Board model label | may be empty |
| `level` | `debug` \| `info` \| `warning` \| `error` \| `critical` | enum |
| `logger` | Python logger name | may be empty |
| `message` | Log text | ≤ 4096 chars, may contain quotes/newlines/unicode |

`builderwars-logs to-sql` turns a CSV into a self-contained `.sql` dump
(`BEGIN; CREATE TABLE IF NOT EXISTS device_logs (...all TEXT...); INSERTs; COMMIT;`)
that executes in PostgreSQL or SQLite. The dump is a **transport format**: all columns are
`TEXT` and `timestamp` is an ISO-8601 string; the ingestion system is responsible for
coercing to the canonical types below.

## 2. Target storage

Per `docs/aws-deployment.md` (prod only, us-east-1, free-tier sized):

| Store | Role |
| --- | --- |
| **RDS PostgreSQL** `db.t4g.micro`, 20 GB | canonical store: the `device_logs` table below. Same instance that hosts the other application tables (decision #12). |
| **S3** (existing raw-data bucket) | (a) raw uploaded files, (b) raw message bodies on the live path, (c) quarantine objects for bad rows/files. Lifecycle rules bound raw growth (decision #6: raw retention 30 d dev / 365 d prod). |

### 2.1 Canonical table (RDS PostgreSQL)

```sql
CREATE TABLE device_logs (
    message_id        UUID PRIMARY KEY,
    schema_version    SMALLINT NOT NULL,
    device_id         TEXT NOT NULL,
    logged_at         TIMESTAMPTZ NOT NULL,
    sequence_number   BIGINT,              -- NULL when the host had no persisted sequence
    firmware_version  TEXT,                -- NULL when unknown
    hardware_model    TEXT,                -- NULL when unknown
    level             TEXT NOT NULL CHECK (level IN
                      ('debug','info','warning','error','critical')),
    logger            TEXT,                -- NULL when absent
    message           TEXT NOT NULL CHECK (char_length(message) <= 4096),
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    source            TEXT NOT NULL CHECK (source IN ('mqtt','upload'))
);
CREATE INDEX device_logs_device_time_idx ON device_logs (device_id, logged_at DESC);
```

Mapping from the CSV/.sql shape: `timestamp` → `logged_at` (parse ISO-8601, reject if not
valid UTC), `message_id` parsed as UUID, `schema_version`/`sequence_number` parsed as
integers, empty string → `NULL` for the nullable columns. `source` records which ingest
path wrote the row; `ingested_at` is server time (distinct from the log time).

Expected volume is tiny at MVP scale (logs are a fraction of the ~518k messages/month
already budgeted in decision #6); no partitioning or separate store is required.

## 3. Ingest paths

Two paths feed the same table; both must be idempotent on `message_id`.

### 3.1 Live path — MQTT → worker (primary)

Extends the existing documented device-message flow (`docs/architecture.md` "Device
telemetry"): the IoT rule for `devices/+/logs` wraps `{topic, received_at_ms, body_b64}`
into the existing ingest SQS queue (or a dedicated one if log volume ever warrants it).

Worker steps (same shape as the other message types):

1. Parse topic → `device_id`, `channel`; decode + schema-validate the envelope.
2. **Identity check:** the envelope `device_id` must equal the device id derived from the
   *authorised* MQTT topic/certificate; mismatch → quarantine + `sequence_gap`-style
   event, never stored.
3. Claim idempotency key (existing mechanism) → store raw body in S3.
4. Insert the normalised row with `ON CONFLICT (message_id) DO NOTHING`,
   `source='mqtt'`.
5. Update device last-seen (existing behaviour).

Invalid messages are acknowledged and logged (never retried); transient failures requeue
and hit the DLQ after 5 attempts — exactly as the other message types.

### 3.2 File path — upload endpoint for `.sql`/`.csv` (offline debug data)

For logs captured while the cloud link was down, the user uploads the local CSV or the
`.sql` dump produced by `builderwars-logs to-sql`.

**API:** `POST /projects/{project_id}/devices/{device_id}/log-uploads`

- **AuthN:** Cognito JWT (verified per `AUTH_MODE=cognito`, decision #10/TODO list).
- **AuthZ:** caller must be a member (or better) of the project that owns the device
  (existing role matrix); device must belong to the project.
- **Body:** multipart file upload (or raw body), content type `text/csv` or
  `application/sql`; `filename` carried in metadata.
- **Limits (hard, enforced before processing):** file ≤ 100 MB, ≤ 50 000 rows, one upload
  per device per 60 s (abuse ceiling; normal use is far below).
- **Response:** `202` + upload/job id; `GET .../log-uploads/{upload_id}` → status
  (`received` → `processing` → `completed` | `quarantined`), with per-batch counters
  (inserted, duplicate, invalid) and a link to the quarantine report when applicable.

**Processing worker** (new worker type, same Lambda pattern):

1. Fetch from S3. Validate the container:
   - CSV: header must be exactly `CSV_COLUMNS` in order; per-row checks below.
   - SQL: must be a single transaction; every statement must be
     `CREATE TABLE IF NOT EXISTS device_logs`, `INSERT INTO device_logs (...)`,
     `BEGIN`/`COMMIT`, or a comment. Any other statement type → whole file quarantined
     (SQL is executable, so it is treated as untrusted input — see §5).
2. Per-row validation (CSV rows, or rows extracted from SQL literals):

| Rule | On failure |
| --- | --- |
| `message_id` is a valid UUID | row quarantined |
| `timestamp` parses as ISO-8601 with UTC offset | row quarantined |
| `level` in the 5-value enum | row quarantined |
| `message` non-empty, ≤ 4096 chars | row quarantined |
| `logger` ≤ 128 chars, `device_id` matches the URL device id | row quarantined |
| `schema_version` is a supported integer | row quarantined |
| envelope invariants (e.g. no control chars in `device_id`) | row quarantined |

3. Load valid rows in batches (≤ 500) with
   `INSERT ... ON CONFLICT (message_id) DO NOTHING` and `source='upload'`; duplicates are
   counted, not errors (the same log may have arrived live *and* via upload).
4. Quarantined rows + the report are written to S3 (see §6); the upload status is updated.
   A file with > 25 % invalid rows is quarantined wholesale (likely wrong file/columns).
5. Ack/delete the SQS message; the raw upload file is kept per retention (§7).

## 4. Idempotency & dedup

- **Natural key:** `message_id` (UUID, PRIMARY KEY). Every row — live or uploaded — is
  inserted with `ON CONFLICT DO NOTHING`; at-least-once delivery on both paths is therefore
  safe, and re-uploading the same file is a no-op beyond the duplicate counter.
- **Cross-path dedup:** a log delivered live and later uploaded (or vice versa) collapses
  to one row; the first writer wins, `source` reflects the first path. This is acceptable:
  the row content is identical by construction (same envelope).
- **Sequence gaps:** as on the live path (decision #14), gaps in `sequence_number` are
  recorded as `sequence_gap` events and never rejected — uploads may legitimately contain
  rows whose sequence numbers the cloud never saw live.
- Upload processing is idempotent in the same sense: reprocessing a file (retry) only
  increases counters.

## 5. Security

- **AuthN:** Cognito only (email + password, self sign-up, MFA off for MVP — decision
  #10). No device credentials on the upload path; uploads are *user* actions.
- **AuthZ:** project membership, as above. There is no cross-project upload: the device
  must belong to the named project and the envelope's `device_id` must equal it.
- **Untrusted input:** uploaded files (CSV *and* SQL) are attacker-influenceable. The SQL
  path is therefore **never executed as code** — it is parsed into literals and re-emitted
  as parameterised inserts (the §3.2 whitelist makes anything else a quarantine). CSV
  values are likewise bound as parameters, never concatenated.
- **Secrets:** log text may contain whatever the app logged. The AI redaction rules
  (`packages/ai/src/ai_platform/context/redaction.py`) define what counts as secret in
  this codebase;
  the ingestion system must not *add* secret handling but must not echo raw rows back
  through API responses beyond the upload status (rows are only visible through the
  existing log-query surfaces, which inherit their own authorisation).
- **Storage:** S3 objects private, bucket policy denies public access; uploads live under
  `raw/uploads/{project_id}/{device_id}/…`. RDS in the VPC, no public endpoint, credentials
  in Secrets Manager (per `docs/aws-deployment.md`).
- **TLS everywhere** (HTTPS API, MQTT/TLS, S3).

## 6. Error handling & observability

- **Live path:** unchanged from the other message types — ack-and-log for invalid,
  requeue for transient, DLQ after 5 attempts; alarms on DLQ depth (decision #13 owner for
  recipients).
- **Upload path:**
  - Per-row quarantine: invalid rows are never mixed into the table; they land in an S3
    quarantine object (`quarantine/{upload_id}.csv` + a JSON report with rule and reason
    per row), referenced from the upload status.
  - Wholesale quarantine for structurally wrong files (bad header, non-whitelisted SQL,
    > 25 % invalid rows).
  - Transient S3/DB failures: the upload job requeues with the same 5-attempt/DLQ policy;
    the status endpoint reports `processing` until then.
- **Metrics/logs:** per-upload counters (received/inserted/duplicate/invalid), per-path
  insert rate, quarantine rate, DLQ depth — CloudWatch, retention per environment.

## 7. Retention

| Data | Retention |
| --- | --- |
| RDS `device_logs` rows | 90 days hot by default (configurable per project later); MVP volume makes this trivially cheap. Delete by `logged_at` in a scheduled job; `ingested_at` is never used for expiry. |
| S3 raw uploaded files | raw-data lifecycle (30 d dev / 365 d prod, decision #6) |
| S3 quarantine objects | same lifecycle as raw |
| Upload status/job records | 30 days (small table or S3-backed) |

## 8. Open questions (deliberately not decided here)

1. Dedicated SQS queue for logs vs. sharing the existing ingest queue (start shared; split
   only if log volume justifies it).
2. Query surface for logs (API `GET .../logs?since=…` with pagination) — the store is
   ready; the read API is a separate spec.
3. Whether `debug`-level logs should be accepted at all on the live path (the runtime
   currently forwards them; the ingestion side could drop them by policy to save space).
4. Per-project retention override (default 90 d above).
