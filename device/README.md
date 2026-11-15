# Host runtime (`board_runtime`)

Runs on the **host PC wired to a FREE-WILi 1-OG** over USB (decision #1, ADR 0004). The host is
the platform's "device": it samples the board, batches telemetry, and talks to AWS IoT Core.
Requires **CPython 3.10+** (CI runs these tests on 3.10).

## Testing a board: `builderwars`

```bash
uv run builderwars                    # what's plugged in, and what to type next
uv run builderwars /dev/ttyACM0       # step-by-step check of the board on that port
uv run builderwars test --watch       # first board found; print GPIO/button changes live
uv run builderwars run /dev/ttyACM0   # full host runtime on that board (JSON lines to stdout)
uv run builderwars ports              # boards + serial ports, with permission status
```

Either of the board's two ttys (main or display CPU) works; `ttyACM0` is accepted for
`/dev/ttyACM0`. Every failed step prints the cause and a fix — e.g. if you can't open the port
it names the group that owns it (`uucp` on Arch, `dialout` on Debian/Ubuntu) and the
`usermod` command. Exit codes: 0 pass, 1 board check failed, 2 usage/setup error.
`--debug` (anywhere on the line) shows full tracebacks. `builderwars-logs` is the same program.

## Sending to Builderwars: sign in, then stream or upload

Boards have no AWS IoT certificates for now. Instead you sign in to the CLI with your own
Builderwars account (the web app's email + password), and the CLI sends the board's telemetry
and logs to the API as you. Anyone viewing the device in the web app sees them live (ADR 0009).

```bash
builderwars login                     # email + password; prod API by default
builderwars devices                   # your registered devices and their ids
builderwars run --cloud --device-id dev_... /dev/ttyACM0   # stream the board live (Ctrl+C)
builderwars run --cloud --device-id dev_...                # same with simulated sensors
builderwars upload dev-local --device-id dev_...           # upload a saved log CSV
builderwars run -n 60 > run.jsonl; builderwars upload run.jsonl --device-id dev_...
builderwars whoami / builderwars logout
```

- You need the **member** role (or higher) on the device's project; viewers can't upload.
- The password goes to Cognito only and is never saved. `<state-dir>/account.json` (mode 0600)
  keeps a refresh token, good for 30 days; then `builderwars login` again.
- `--api https://...` (or `BUILDERWARS_API_URL`) points at another deployment;
  `--api http://localhost:8000` uses a local API, where login only asks for a dev user name.
- Uploads are idempotent: messages already stored (e.g. logs that went up live and are also in
  the CSV) are counted as "already uploaded", not stored twice. Files recorded under another id
  (`dev-local`, `sim-001`) are re-addressed to the device you upload to.
- If the network or the API is down, `run --cloud` keeps sampling and buffers messages in memory
  (the last 1000), then sends them when it can.
- Not yet: commands from the dashboard (ping, uptime) don't reach a board in this mode.

## Local development (no board, no AWS)

```bash
# Simulator: emits valid messages as JSON lines (not an authenticated IoT device)
uv run python -m board_runtime.simulator --device-id sim-001 --count 40

# Runtime loop with simulated sensors and the stdout transport
DEVICE_ID=dev-local-001 BUILDERWARS_STATE_DIR=/tmp/bw-state \
  uv run python -m board_runtime.main --samples 12

# Same loop, sending to a local API (uvicorn on :8000) so the web dashboard updates live and
# commands such as ping come back. DEVICE_ID must be a device registered through the API.
DEVICE_ID=<dev_...> DEVICE_TRANSPORT=local-api LOCAL_API_URL=http://localhost:8000 \
  BUILDERWARS_STATE_DIR=/tmp/bw-state uv run python -m board_runtime.main
```

`local-api` is a development transport only: it is not an authenticated IoT device, and the
API serves its routes only when `APP_ENV` is `local` or `test` (ADR 0008).

## On a real host (not yet exercised end to end)

```bash
python3 -m venv ~/.builderwars/venv && . ~/.builderwars/venv/bin/activate
pip install "./packages/device_protocol" "./device[mqtt]" freewili==0.0.51
export DEVICE_ID=<thing-name> DEVICE_SENSORS=freewili DEVICE_TRANSPORT=mqtt \
       IOT_ENDPOINT=<ats-endpoint> IOT_CERT_PATH=~/.builderwars/credentials/device.pem.crt \
       IOT_KEY_PATH=~/.builderwars/credentials/private.pem.key \
       IOT_CA_PATH=~/.builderwars/credentials/AmazonRootCA1.pem
builderwars-host            # or: builderwars-host --port /dev/ttyACM0
```

`DEVICE_PORT=/dev/ttyACM0` (or `--port`) pins the board; setting it implies
`DEVICE_SENSORS=freewili`. Without it the first FREE-WILi found is used.

In a clone of this repo, `freewili` is a root workspace dependency, so `uv sync` installs it.
The cost: it pins `typing-extensions` exactly, which holds the whole workspace on an older
pydantic (2.11 rather than 2.14). It is still not a dependency of `bw-board-runtime` itself, so
a bare host installs it next to the runtime as shown above. (The decisions doc mentions
`onewili`; that isn't on PyPI, and `freewili` is the vendor's published library.)

`builderwars run` with `DEVICE_TRANSPORT=mqtt` needs the registered device id (`--device-id` or
`DEVICE_ID`): AWS IoT only lets a certificate connect as its own thing, so it refuses to fall
back to `dev-local`. Local log CSVs follow `BUILDERWARS_LOG_CSV` for both `run` and `sim`
(`off` disables them). `builderwars to-sql` dumps into a `host_device_logs` table, never the
cloud's `device_logs`, and re-loading a dump skips rows already present.

## Modules

| Module | Purpose | State |
| --- | --- | --- |
| `config.py` | Env-based config; cert/key **paths** only | done |
| `messages.py` | Builds validated, sequenced envelopes | done |
| `sequence.py` | Sequence numbers persisted in `~/.builderwars/seq/<device_id>` (decision #14) | done |
| `batching.py` | Telemetry batches: flush every 5 s or at 32 samples (decision #6) | done |
| `connectivity/transport.py` | `Transport` protocol, stdout + recording transports | done |
| `connectivity/mqtt_client.py` | AWS IoT Core MQTT/TLS via `awsiotsdk` (`mqtt` extra) | done, untested against real IoT |
| `connectivity/backoff.py` | Exponential backoff with jitter | available; the SDK reconnects itself |
| `connectivity/buffer.py` | Offline buffer (bounded, RAM, drop-oldest) | done; persistence TODO |
| `hardware/freewili.py` | FREE-WILi over USB via `freewili`; unplug -> `BoardUnavailableError` | done, untested on hardware; readings are placeholders |
| `hardware/sensors.py` | `SensorReader` protocol, simulated sensors | done |
| `logging/` | `logging.Handler` -> protocol `log` messages | done |
| `commands/` | Allowlisted command dispatcher (`ping`, `get_uptime`) | done; no shell command, ever |
| `firmware.py` | sha256 verification before flashing; UF2 flasher | verify done; flashing stub (spec 09) |
| `main.py` | Runtime loop; `status: degraded` + events while the board is unplugged | done |
