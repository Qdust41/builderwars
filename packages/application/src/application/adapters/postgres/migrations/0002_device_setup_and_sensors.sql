-- 0002: the test setup behind a device (laptop -> FREE-WILi -> up to 4 target boards) and the
-- target boards' sensor definitions. Kept out of `devices` because ingest rewrites that row on
-- every message; see domain.devices.setup.

-- What the CLI last reported about the laptop and the FREE-WILi.
CREATE TABLE device_setups (
    device_id   text PRIMARY KEY REFERENCES devices (id) ON DELETE CASCADE,
    host        jsonb,          -- device_protocol.setup.HostReport
    bridge      jsonb,          -- device_protocol.setup.BridgeReport (the FREE-WILi), or NULL
    reported_at timestamptz,
    reported_by text,
    updated_at  timestamptz NOT NULL
);

-- Boards under test wired to the device's FREE-WILi (at most 4, enforced by the service).
CREATE TABLE device_target_boards (
    id         text PRIMARY KEY,
    device_id  text        NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    name       text        NOT NULL CHECK (btrim(name) <> ''),
    notes      text        NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX device_target_boards_device_idx ON device_target_boards (device_id, created_at);

CREATE TABLE device_sensors (
    id              text PRIMARY KEY,
    device_id       text        NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    board_id        text        NOT NULL REFERENCES device_target_boards (id) ON DELETE CASCADE,
    key             text        NOT NULL CHECK (key ~ '^[a-z][a-z0-9_]{0,63}$'),
    name            text        NOT NULL CHECK (btrim(name) <> ''),
    protocol        text        NOT NULL CHECK (protocol IN ('i2c', 'spi', 'uart', 'gpio')),
    bus             jsonb       NOT NULL,  -- device_protocol.sensors.SensorBus
    decode          jsonb       NOT NULL,  -- device_protocol.sensors.SensorDecode
    unit            text,
    poll_interval_s double precision NOT NULL CHECK (poll_interval_s > 0),
    enabled         boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL,
    updated_at      timestamptz NOT NULL,
    UNIQUE (device_id, key)   -- one telemetry stream per device
);
CREATE INDEX device_sensors_device_idx ON device_sensors (device_id, created_at);
CREATE INDEX device_sensors_board_idx ON device_sensors (board_id);
