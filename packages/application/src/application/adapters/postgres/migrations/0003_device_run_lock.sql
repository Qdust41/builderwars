-- 0003: the `builderwars run` holding a device's board (one run at a time; see ADR 0011).
-- The lock is live while run_seen_at is recent (75 s) and cleared when the run stops.
ALTER TABLE device_setups
    ADD COLUMN run_id         text,
    ADD COLUMN run_by         text,
    ADD COLUMN run_started_at timestamptz,
    ADD COLUMN run_seen_at    timestamptz;
