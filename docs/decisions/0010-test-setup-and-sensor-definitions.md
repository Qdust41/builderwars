# 0010 — The test setup is laptop → FREE-WILi → target boards, and sensors are defined in the cloud

Status: accepted (2026-11-15, owner answers: up to 4 target boards per FREE-WILi, a hard max;
boards and sensors are owner-only for now, later every member; I2C setup writes wanted; a table
of common parts to start from)

## Context
A device used to be a name. The CLI read only the FREE-WILi's own GPIO levels and buttons with a
port, and made up `temperature_c` / `cpu_load_pct` / `free_mem_kb` without one, so nothing read
the board actually under test. The real bench is a chain: the user's laptop runs `builderwars`,
a FREE-WILi is plugged into it over USB, and the boards being tested are wired to the
FREE-WILi's I2C, SPI, UART and GPIO pins.

## Decision
1. **Model the chain.** A device's setup has the laptop (`host`) and the FREE-WILi (`bridge`),
   both reported by the CLI when `run` starts (`PUT /devices/{id}/setup/connection`,
   `device:upload`), and 0–4 **target boards** that people add on the device page
   (`/devices/{id}/boards`). These live in their own tables (`device_setups`,
   `device_target_boards`), not on `devices`, because ingest rewrites the device row on every
   message.
2. **Sensors are data, not code.** A sensor belongs to one target board and says how to read
   one value: protocol and bus settings (I2C address + register + length + optional setup
   writes; SPI bytes to send and which reply bytes to keep; UART command + reply regex; GPIO
   pin), how to decode (`u8`…`f32_le`, mask, shift, scale, offset, rounding), unit and poll
   interval. The shared pydantic model `device_protocol.sensors.SensorSpec` is the single
   definition used by the API (validation), the CLI (parsing) and the decoder. Keys are unique
   per device (all boards share one telemetry stream). At most 32 sensors per device.
3. **The CLI reads them.** `builderwars run --cloud` downloads the sensors, opens the FREE-WILi
   (the given port or the first one found) and reads each enabled sensor at its own rate
   through the `freewili` library (`read_i2c`/`write_i2c`, `read_write_spi_data`, `get_io`,
   `write_uart` + UART events). One failing sensor is logged once and skipped; losing the
   FREE-WILi marks the device degraded as before. Definitions are refetched every 30 s.
4. **Simulation is explicit.** With `--cloud`, no port no longer means simulated: it means "the
   first FREE-WILi found". `--simulate` sends made-up values for the defined sensors (or the
   old simulated readings when none are defined), and the laptop card says so. With no sensors
   defined, a real run still sends the FREE-WILi's own pins.
5. **Presets.** `GET /sensor-presets` serves a table of common parts (TMP102, LM75, MCP9808,
   Si7021, MAX31855, MAX6675, INA219, ADS1115, MCP3008, MPU-6050, ADXL345, VEML7700, BME280
   chip id, generic GPIO/UART) with datasheet settings; a test decodes datasheet examples.
6. **Who edits.** New permission `device:configure`, granted to owners only for now.

## Consequences
- The `freewili` library cannot set UART baud or SPI mode/clock from the host; they are stored
  for reference and set on the FREE-WILi itself.
- Parts needing calibration maths (BME280 temperature/pressure) or multi-byte commands with CRC
  (SHT3x) are not expressible yet; a "formula" or per-part driver step would be the next step.
- Nothing here has run against real hardware yet: the I2C/SPI/GPIO/UART calls follow the
  library's API and are covered by fakes.
- Dashboard commands reach CLI-connected boards by polling: the CLI calls
  `POST /devices/{id}/commands/claim` every 2 s, which marks queued commands sent. A device that
  has sent nothing for 75 s reads as offline, so "Live" only shows while a run is going.
