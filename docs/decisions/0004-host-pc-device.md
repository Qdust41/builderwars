# 0004 — A "device" is a host PC + FREE-WILi pair

Status: accepted (2026-11-14, decisions #1–#3)

## Context
The board is a FREE-WILi 1-OG (dual RP2040, iCE40, CC1101) with a Bottlenose WiFi Orca. Its
CPUs run `_main.uf2` apps and WASM guests, not CPython, and the vendor positions it as a
terminal driven from a PC.

## Decision
- The platform's device is the **host PC + board pair**: one IoT thing, one X.509
  certificate, one `device_id`.
- The host runs `device/` (CPython **3.10+**), reads the board over USB serial through the
  vendor `freewili` package (`FreeWiliSensors`), and connects to AWS IoT Core directly over
  MQTT/TLS (`awsiotsdk`). No Greengrass, no local gateway.
- USB is the local wiring and flashing path only, not a user-facing feature.
- `packages/device_protocol` and `device/` stay Python 3.10-compatible; CI checks it.

## Consequences
- No on-board Python or pydantic port is needed (ADR 0002's MicroPython contingency stays
  documented but unused). A FREE-WILi 2 with a CM0 would need specs 02/03 rechecked.
- Board unavailability is a first-class state: the host reports `status: degraded` and a
  `board_disconnected` event while staying connected to the cloud.
- Firmware updates require the host online and the board on USB (decision #9).
