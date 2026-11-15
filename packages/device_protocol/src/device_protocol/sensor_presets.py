"""A table of common sensor parts, ready to drop onto a target board.

Each preset is a complete ``SensorSpec`` (minus the board) taken from the part's datasheet,
so picking one in the web app fills in the protocol, address, registers and decoding. People
can still edit everything afterwards (address straps, gain, poll rate). ``notes`` says what
the preset assumes. Served by ``GET /sensor-presets``; a test checks every one validates.

Python 3.10-safe.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from device_protocol.sensors import SensorSpec


class SensorPreset(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    part: str
    manufacturer: str
    measures: str
    notes: str = ""
    datasheet: str | None = None
    sensor: SensorSpec


def _i2c(address: int, reg: int, length: int, **extra: Any) -> dict[str, Any]:
    return {"protocol": "i2c", "address": address, "reg": reg, "length": length, **extra}


_RAW: Final[list[dict[str, Any]]] = [
    # -- temperature ------------------------------------------------------------------------
    {
        "id": "tmp102-temp",
        "part": "TMP102",
        "manufacturer": "Texas Instruments",
        "measures": "Temperature",
        "notes": "ADD0 to GND = 0x48 (0x49 VCC, 0x4A SDA, 0x4B SCL). 12-bit, 0.0625 °C/LSB.",
        "datasheet": "https://www.ti.com/product/TMP102",
        "sensor": {
            "key": "tmp102_temp_c",
            "name": "TMP102 temperature",
            "unit": "°C",
            "bus": _i2c(0x48, 0x00, 2),
            "decode": {"data_type": "i16_be", "bit_shift": 4, "scale": 0.0625},
        },
    },
    {
        "id": "lm75-temp",
        "part": "LM75A",
        "manufacturer": "NXP / TI",
        "measures": "Temperature",
        "notes": "A2..A0 to GND = 0x48. 11-bit, 0.125 °C/LSB.",
        "sensor": {
            "key": "lm75_temp_c",
            "name": "LM75 temperature",
            "unit": "°C",
            "bus": _i2c(0x48, 0x00, 2),
            "decode": {"data_type": "i16_be", "bit_shift": 5, "scale": 0.125},
        },
    },
    {
        "id": "mcp9808-temp",
        "part": "MCP9808",
        "manufacturer": "Microchip",
        "measures": "Temperature",
        "notes": "Default address 0x18. Reads 0 °C and above only (the sign bit is masked off).",
        "datasheet": "https://www.microchip.com/en-us/product/MCP9808",
        "sensor": {
            "key": "mcp9808_temp_c",
            "name": "MCP9808 temperature",
            "unit": "°C",
            "bus": _i2c(0x18, 0x05, 2),
            "decode": {"data_type": "u16_be", "bit_mask": 0x0FFF, "scale": 0.0625},
        },
    },
    {
        "id": "si7021-temp",
        "part": "Si7021 / HTU21D",
        "manufacturer": "Silicon Labs / TE",
        "measures": "Temperature",
        "notes": "Address 0x40. 'Hold master' command 0xE3; the sensor stretches the clock.",
        "sensor": {
            "key": "si7021_temp_c",
            "name": "Si7021 temperature",
            "unit": "°C",
            "bus": _i2c(0x40, 0xE3, 2),
            "decode": {
                "data_type": "u16_be",
                "bit_mask": 0xFFFC,
                "scale": 175.72 / 65536,
                "offset": -46.85,
                "decimals": 2,
            },
        },
    },
    {
        "id": "si7021-humidity",
        "part": "Si7021 / HTU21D",
        "manufacturer": "Silicon Labs / TE",
        "measures": "Relative humidity",
        "notes": "Address 0x40. 'Hold master' command 0xE5.",
        "sensor": {
            "key": "si7021_humidity_pct",
            "name": "Si7021 humidity",
            "unit": "%RH",
            "bus": _i2c(0x40, 0xE5, 2),
            "decode": {
                "data_type": "u16_be",
                "bit_mask": 0xFFFC,
                "scale": 125 / 65536,
                "offset": -6,
                "decimals": 1,
            },
        },
    },
    {
        "id": "max31855-thermocouple",
        "part": "MAX31855",
        "manufacturer": "Analog Devices (Maxim)",
        "measures": "Thermocouple temperature",
        "notes": "Read-only SPI: clock out 4 dummy bytes. 14-bit, 0.25 °C/LSB.",
        "datasheet": "https://www.analog.com/en/products/max31855.html",
        "sensor": {
            "key": "max31855_temp_c",
            "name": "Thermocouple (MAX31855)",
            "unit": "°C",
            "bus": {"protocol": "spi", "write": [0, 0, 0, 0], "read_offset": 0, "length": 4},
            "decode": {"data_type": "i32_be", "bit_shift": 18, "scale": 0.25},
        },
    },
    {
        "id": "max6675-thermocouple",
        "part": "MAX6675",
        "manufacturer": "Analog Devices (Maxim)",
        "measures": "Thermocouple temperature",
        "notes": "Read-only SPI: clock out 2 dummy bytes. 12-bit, 0.25 °C/LSB, 0 °C and up.",
        "datasheet": "https://www.analog.com/en/products/max6675.html",
        "sensor": {
            "key": "max6675_temp_c",
            "name": "Thermocouple (MAX6675)",
            "unit": "°C",
            "bus": {"protocol": "spi", "write": [0, 0], "read_offset": 0, "length": 2},
            "decode": {"data_type": "u16_be", "bit_mask": 0x7FF8, "bit_shift": 3, "scale": 0.25},
        },
    },
    # -- power ------------------------------------------------------------------------------
    {
        "id": "ina219-bus-voltage",
        "part": "INA219",
        "manufacturer": "Texas Instruments",
        "measures": "Bus voltage",
        "notes": "A1/A0 to GND = 0x40. 4 mV/LSB.",
        "datasheet": "https://www.ti.com/product/INA219",
        "sensor": {
            "key": "ina219_bus_v",
            "name": "INA219 bus voltage",
            "unit": "V",
            "bus": _i2c(0x40, 0x02, 2),
            "decode": {"data_type": "u16_be", "bit_shift": 3, "scale": 0.004, "decimals": 3},
        },
    },
    {
        "id": "ina219-shunt-voltage",
        "part": "INA219",
        "manufacturer": "Texas Instruments",
        "measures": "Shunt voltage (current = this / shunt ohms)",
        "notes": "A1/A0 to GND = 0x40. 10 µV/LSB; with a 0.1 Ω shunt, set scale 0.1 for mA.",
        "datasheet": "https://www.ti.com/product/INA219",
        "sensor": {
            "key": "ina219_shunt_mv",
            "name": "INA219 shunt voltage",
            "unit": "mV",
            "bus": _i2c(0x40, 0x01, 2),
            "decode": {"data_type": "i16_be", "scale": 0.01, "decimals": 2},
        },
    },
    # -- analog to digital ------------------------------------------------------------------
    {
        "id": "ads1115-ain0",
        "part": "ADS1115",
        "manufacturer": "Texas Instruments",
        "measures": "Voltage on AIN0",
        "notes": "ADDR to GND = 0x48. Setup write puts it in continuous mode, AIN0 vs GND, "
        "±4.096 V range, 128 samples/s.",
        "datasheet": "https://www.ti.com/product/ADS1115",
        "sensor": {
            "key": "ads1115_ain0_v",
            "name": "ADS1115 AIN0",
            "unit": "V",
            "bus": _i2c(0x48, 0x00, 2, setup_writes=[{"reg": 0x01, "data": [0xC2, 0x83]}]),
            "decode": {"data_type": "i16_be", "scale": 4.096 / 32768, "decimals": 4},
        },
    },
    {
        "id": "mcp3008-ch0",
        "part": "MCP3008",
        "manufacturer": "Microchip",
        "measures": "Voltage on CH0",
        "notes": "10-bit SPI ADC; assumes Vref = 3.3 V (scale = Vref / 1024).",
        "datasheet": "https://www.microchip.com/en-us/product/MCP3008",
        "sensor": {
            "key": "mcp3008_ch0_v",
            "name": "MCP3008 CH0",
            "unit": "V",
            "bus": {"protocol": "spi", "write": [0x01, 0x80, 0x00], "read_offset": 1, "length": 2},
            "decode": {
                "data_type": "u16_be",
                "bit_mask": 0x03FF,
                "scale": 3.3 / 1024,
                "decimals": 3,
            },
        },
    },
    # -- motion -----------------------------------------------------------------------------
    {
        "id": "mpu6050-accel-x",
        "part": "MPU-6050",
        "manufacturer": "TDK InvenSense",
        "measures": "Acceleration, X axis",
        "notes": "AD0 to GND = 0x68. Setup write wakes it from sleep; ±2 g range.",
        "sensor": {
            "key": "mpu6050_accel_x_g",
            "name": "MPU-6050 accel X",
            "unit": "g",
            "bus": _i2c(0x68, 0x3B, 2, setup_writes=[{"reg": 0x6B, "data": [0x00]}]),
            "decode": {"data_type": "i16_be", "scale": 1 / 16384, "decimals": 3},
        },
    },
    {
        "id": "mpu6050-temp",
        "part": "MPU-6050",
        "manufacturer": "TDK InvenSense",
        "measures": "Die temperature",
        "notes": "AD0 to GND = 0x68. Setup write wakes it from sleep.",
        "sensor": {
            "key": "mpu6050_temp_c",
            "name": "MPU-6050 temperature",
            "unit": "°C",
            "bus": _i2c(0x68, 0x41, 2, setup_writes=[{"reg": 0x6B, "data": [0x00]}]),
            "decode": {"data_type": "i16_be", "scale": 1 / 340, "offset": 36.53, "decimals": 2},
        },
    },
    {
        "id": "adxl345-x",
        "part": "ADXL345",
        "manufacturer": "Analog Devices",
        "measures": "Acceleration, X axis",
        "notes": "ALT ADDRESS to GND = 0x53. Setup write starts measuring; 3.9 mg/LSB.",
        "datasheet": "https://www.analog.com/en/products/adxl345.html",
        "sensor": {
            "key": "adxl345_x_g",
            "name": "ADXL345 X",
            "unit": "g",
            "bus": _i2c(0x53, 0x32, 2, setup_writes=[{"reg": 0x2D, "data": [0x08]}]),
            "decode": {"data_type": "i16_le", "scale": 0.0039, "decimals": 3},
        },
    },
    # -- light ------------------------------------------------------------------------------
    {
        "id": "veml7700-lux",
        "part": "VEML7700",
        "manufacturer": "Vishay",
        "measures": "Ambient light",
        "notes": "Address 0x10. Setup write powers it on at gain 1, 100 ms (0.0576 lux/LSB).",
        "sensor": {
            "key": "veml7700_lux",
            "name": "VEML7700 light",
            "unit": "lx",
            "bus": _i2c(0x10, 0x04, 2, setup_writes=[{"reg": 0x00, "data": [0x00, 0x00]}]),
            "decode": {"data_type": "u16_le", "scale": 0.0576, "decimals": 1},
        },
    },
    # -- checks and generic ------------------------------------------------------------------
    {
        "id": "bme280-chip-id",
        "part": "BME280 / BMP280",
        "manufacturer": "Bosch",
        "measures": "Chip ID (wiring check)",
        "notes": "SDO to GND = 0x76. Reads 96 for a BME280, 88 for a BMP280. Real temperature "
        "and pressure need Bosch's calibration maths, which presets don't do yet.",
        "sensor": {
            "key": "bme280_chip_id",
            "name": "BME280 chip ID",
            "bus": _i2c(0x76, 0xD0, 1),
            "decode": {"data_type": "u8"},
            "poll_interval_s": 10,
        },
    },
    {
        "id": "gpio-digital-in",
        "part": "Digital input",
        "manufacturer": "Generic",
        "measures": "High/low level of a pin",
        "notes": "GPIO26 is the FREE-WILi's input pin on the header; change the pin as needed.",
        "sensor": {
            "key": "digital_in",
            "name": "Digital input",
            "bus": {"protocol": "gpio", "pin": 26},
        },
    },
    {
        "id": "uart-query",
        "part": "UART query",
        "manufacturer": "Generic",
        "measures": "A number the board prints when asked",
        "notes": "Sends READ? on UART1 and takes the first number in the reply. Set the baud "
        "rate on the FREE-WILi.",
        "sensor": {
            "key": "uart_value",
            "name": "UART value",
            "bus": {"protocol": "uart", "command": "READ?", "baud": 115200},
        },
    },
]

SENSOR_PRESETS: Final[tuple[SensorPreset, ...]] = tuple(
    SensorPreset.model_validate(raw) for raw in _RAW
)

__all__ = ["SENSOR_PRESETS", "SensorPreset"]
