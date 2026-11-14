# Board runtime (`board_runtime`)

Python runtime intended to run on the development board, plus a local simulator.

```bash
# Simulator: emits a burst of valid messages as JSON lines (not an authenticated IoT device)
uv run python -m board_runtime.simulator --device-id sim-001 --count 5

# Runtime loop with the stdout transport
DEVICE_ID=dev-local-001 DEVICE_TELEMETRY_INTERVAL_S=1 uv run python -m board_runtime.main --iterations 3
```

| Module | Purpose | State |
| --- | --- | --- |
| `config.py` | Env-based config; cert/key **paths** only | done |
| `messages.py` | Builds validated, sequenced envelopes | done |
| `connectivity/transport.py` | `Transport` protocol, stdout + recording transports | done |
| `connectivity/mqtt_client.py` | AWS IoT Core MQTT/TLS transport | **stub** |
| `connectivity/backoff.py` | Exponential backoff with jitter | done, not yet wired to a reconnect loop |
| `connectivity/buffer.py` | Offline buffer (bounded, RAM, drop-oldest) | done; persistence TODO |
| `hardware/` | `SensorReader` interface, simulated sensors | real drivers TODO (board TBD) |
| `logging/` | `logging.Handler` → protocol `log` messages | done |
| `commands/` | Allowlisted command dispatcher (`ping`, `get_uptime`) | done; no shell command, ever |
| `main.py` | Runtime loop | done (single-threaded placeholder) |

Assumes CPython ≥ 3.12 on the board (open decision #1). Credentials are configured via
environment variables pointing at files kept outside the repository.
