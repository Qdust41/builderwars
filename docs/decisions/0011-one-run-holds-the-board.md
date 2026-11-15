# 0011 — One `builderwars run` holds a device's board at a time

Status: accepted (2026-11-15, owner chose "the run claims the board": the page shows who holds
it and on which laptop, and a second run is refused until the first stops)

## Context
Nothing stopped two `builderwars run --cloud` processes (two laptops, or a forgotten terminal)
from streaming the same device. Their telemetry interleaved, the FREE-WILi's serial ports can
only be opened by one process, and nobody could see on the device page who was using the board.

## Decision
- `run --cloud` makes a run id and sends it with `PUT /devices/{id}/setup/connection`. The API
  locks the board for that run (`device_setups.run_*`, migration 0003). While another run holds
  it, the answer is 409 with `code: board_in_use` and who holds it; the CLI exits with that
  message and suggests `--take-over`.
- Every upload from the run carries its `run_id`, which keeps the lock alive (written at most
  every 15 s). If another run took the board over, the upload gets 409 `run_superseded` and the
  old run stops instead of mixing its data in.
- The lock lapses 75 s after the run last sent anything (same as a device reading as offline),
  so a crashed laptop can't hold the board. A clean stop (Ctrl+C, SIGTERM, SIGHUP) releases it
  with `DELETE /devices/{id}/setup/run/{run_id}`.
- `GET /devices/{id}/setup` returns `run` (who, which laptop, since when) while it is held; the
  device page shows "In use by ... on ...".
- Uploads without `run_id` (`builderwars upload` of saved data) are not affected.

## Consequences
- Two people can't stream one board at once; taking over is explicit.
- Two runs that start in the same instant can both be told "locked"; the next upload of the
  one that lost gets `run_superseded`, so it stops within one batch.
