# Host runtime (`board_runtime`)

Runs on the **host PC wired to a FREE-WILi 1-OG** over USB (decision #1, ADR 0004). The host is
the platform's "device": it samples the board, batches telemetry, and talks to AWS IoT Core.
Requires **CPython 3.10+** (CI runs these tests on 3.10).

## Local development (no board, no AWS)

```bash
# Simulator: emits valid messages as JSON lines (not an authenticated IoT device)
uv run python -m board_runtime.simulator --device-id sim-001 --count 40

# Runtime loop with simulated sensors and the stdout transport
DEVICE_ID=dev-local-001 BUILDERWARS_STATE_DIR=/tmp/bw-state \
  uv run python -m board_runtime.main --samples 12
```

## On a real host (not yet exercised end to end)

```bash
python3 -m venv ~/.builderwars/venv && . ~/.builderwars/venv/bin/activate
pip install "./packages/device_protocol" "./device[mqtt]" freewili==0.0.51
export DEVICE_ID=<thing-name> DEVICE_SENSORS=freewili DEVICE_TRANSPORT=mqtt \
       IOT_ENDPOINT=<ats-endpoint> IOT_CERT_PATH=~/.builderwars/credentials/device.pem.crt \
       IOT_KEY_PATH=~/.builderwars/credentials/private.pem.key \
       IOT_CA_PATH=~/.builderwars/credentials/AmazonRootCA1.pem
builderwars-host
```

On the host, `freewili` is installed by name rather than as a `device` extra, because it pins
`typing-extensions` exactly. In the dev workspace it is a root dependency (`pyproject.toml`), so
`uv sync` already installs it; that pin is why the lockfile holds pydantic at 2.11.x. (The
decisions doc mentions `onewili`; that isn't on PyPI, and `freewili` is the vendor's published
library.)

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
