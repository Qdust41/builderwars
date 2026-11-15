-- 0001: initial schema for the repository ports in application.ports.repositories.
--
-- Ids are minted by the domain (prefixed text such as "prj_..." and protocol UUIDs), so they are
-- stored as text. Every timestamp is timestamptz in UTC. Enum-like columns carry CHECK
-- constraints that mirror the domain StrEnums; adding a value needs a new migration.

CREATE TABLE projects (
    id            text PRIMARY KEY,
    name          text        NOT NULL CHECK (btrim(name) <> ''),
    owner_user_id text        NOT NULL,
    created_at    timestamptz NOT NULL,
    updated_at    timestamptz NOT NULL
);

CREATE TABLE project_memberships (
    project_id text        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    user_id    text        NOT NULL,
    role       text        NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, user_id)
);
CREATE INDEX project_memberships_user_idx ON project_memberships (user_id);

CREATE TABLE devices (
    id                text PRIMARY KEY,
    project_id        text        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    display_name      text        NOT NULL,
    hardware_model    text        NOT NULL,
    extensions        text[]      NOT NULL DEFAULT '{}',
    firmware_version  text,
    connection_status text        NOT NULL
        CHECK (connection_status IN ('unknown', 'online', 'offline')),
    last_seen_at      timestamptz,
    created_at        timestamptz NOT NULL
);
CREATE INDEX devices_project_idx ON devices (project_id, created_at);

CREATE TABLE sessions (
    id         text PRIMARY KEY,
    project_id text        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    created_by text        NOT NULL,
    device_id  text REFERENCES devices (id) ON DELETE SET NULL,
    status     text        NOT NULL CHECK (status IN ('active', 'ended')),
    created_at timestamptz NOT NULL
);
CREATE INDEX sessions_project_idx ON sessions (project_id, created_at);

CREATE TABLE jobs (
    id               text PRIMARY KEY,
    project_id       text        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    job_type         text        NOT NULL CHECK (job_type IN (
        'ai_run', 'firmware_build', 'firmware_deploy', 'firmware_rollback', 'test_run',
        'data_analysis'
    )),
    created_by       text        NOT NULL,
    device_id        text REFERENCES devices (id) ON DELETE SET NULL,
    status           text        NOT NULL
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    input_reference  text,
    output_reference text,
    created_at       timestamptz NOT NULL,
    started_at       timestamptz,
    completed_at     timestamptz,
    error_summary    text
);
CREATE INDEX jobs_project_idx ON jobs (project_id, created_at);

CREATE TABLE device_commands (
    id           text PRIMARY KEY,  -- == protocol command_id (UUID)
    project_id   text        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    device_id    text        NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    name         text        NOT NULL,
    requested_by text        NOT NULL,
    args         jsonb       NOT NULL DEFAULT '{}',
    status       text        NOT NULL CHECK (status IN (
        'queued', 'sent', 'succeeded', 'failed', 'rejected', 'timed_out'
    )),
    created_at   timestamptz NOT NULL,
    expires_at   timestamptz,
    sent_at      timestamptz,
    completed_at timestamptz,
    detail       text,
    output       jsonb       NOT NULL DEFAULT '{}'
);
-- count_pending() and the future timeout sweeper only look at queued/sent commands.
CREATE INDEX device_commands_pending_idx ON device_commands (device_id)
    WHERE status IN ('queued', 'sent');

-- ---------------------------------------------------------------------------------------------
-- Ingest-side tables. No foreign keys to devices: ingest must record (or quarantine) messages
-- from devices the registry does not know yet, and must never fail on them.
-- ---------------------------------------------------------------------------------------------

-- Idempotency keys for at-least-once delivery (ProcessedMessageStore).
CREATE TABLE processed_messages (
    key          text PRIMARY KEY,
    processed_at timestamptz NOT NULL DEFAULT now()
);

-- Highest sequence_number seen per device (SequenceTracker).
CREATE TABLE device_sequences (
    device_id     text PRIMARY KEY,
    last_sequence bigint      NOT NULL CHECK (last_sequence >= 0),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Accepted raw envelopes (RawDeviceMessageStore.put). The body is kept here for now (messages
-- are <= 32 KiB); in AWS the body can move to S3 raw/ and this row keeps the metadata.
CREATE TABLE raw_device_messages (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id   text        NOT NULL,
    message_id  text        NOT NULL,
    received_at timestamptz NOT NULL,
    size_bytes  integer     NOT NULL,
    sha256      text        NOT NULL,
    body        bytea,
    UNIQUE (device_id, message_id)
);
CREATE INDEX raw_device_messages_received_idx ON raw_device_messages (device_id, received_at);

-- Rejected messages (RawDeviceMessageStore.quarantine): kept, never silently dropped.
CREATE TABLE quarantined_device_messages (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id   text,
    received_at timestamptz NOT NULL,
    reason      text        NOT NULL,
    size_bytes  integer     NOT NULL,
    sha256      text        NOT NULL,
    body        bytea
);
CREATE INDEX quarantined_device_messages_received_idx
    ON quarantined_device_messages (received_at);

-- Normalised records (TelemetryRepository). Retention is set in spec 04.
CREATE TABLE device_telemetry (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id  text        NOT NULL,
    message_id text        NOT NULL,
    at         timestamptz NOT NULL,
    metrics    jsonb       NOT NULL
);
CREATE INDEX device_telemetry_device_at_idx ON device_telemetry (device_id, at);

CREATE TABLE device_logs (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id  text        NOT NULL,
    message_id text        NOT NULL,
    at         timestamptz NOT NULL,
    level      text        NOT NULL,
    message    text        NOT NULL
);
CREATE INDEX device_logs_device_at_idx ON device_logs (device_id, at);

CREATE TABLE device_events (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id  text        NOT NULL,
    message_id text,  -- NULL for ingest-derived events such as sequence_gap
    at         timestamptz NOT NULL,
    name       text        NOT NULL,
    severity   text        NOT NULL,
    detail     text
);
CREATE INDEX device_events_device_at_idx ON device_events (device_id, at);
