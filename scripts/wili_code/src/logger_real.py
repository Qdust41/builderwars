
import onewili
import csv
import time
from datetime import datetime
from pathlib import Path

# Configuration
I2C_ADDRESS = 0x68
IMU_REGISTER = 0x3B
IMU_LENGTH = 14

SAMPLE_INTERVAL = 0.1  # 10 Hz target
OUTPUT = Path("combined_gpio_imu.csv")

# Connect
dev = onewili.connect()
gpio = dev.io.gpio
i2c = dev.io.i2c

# Ensure FREE-WILi is operating as I2C master
slave_result = i2c.i2c_slave_enable(0)
print("Disable I2C slave mode:", slave_result)

# Wake MPU6050
wake_result = i2c.i2c_write(
    I2C_ADDRESS,
    0x6B,
    bytes([0x00])
)
print("Wake MPU6050:", wake_result)


def get_value(result):
    """Extract successful Result values; return None on errors."""
    try:
        return result.ok_value
    except Exception:
        return None


def read_imu():
    """Read 14 consecutive bytes from the MPU6050."""
    result = i2c._call(
        "r",
        [
            f"{I2C_ADDRESS:02X}",
            f"{IMU_REGISTER:02X}",
            str(IMU_LENGTH)
        ],
        ["bytes"],
        timeout=3.0
    )

    return get_value(result), str(result)


def read_gpio():
    """Read the complete GPIO bitfield."""
    result = gpio.read_all()
    return get_value(result), str(result)


# CSV columns
headers = [
    "timestamp",
    "elapsed_s",
    "gpio_raw",
    "gpio_error",
]

headers += [f"GPIO{i}" for i in range(32)]

headers += [
    "imu_raw_hex",
    "imu_error",
]

headers += [
    "imu_byte_" + str(i) for i in range(IMU_LENGTH)
]

headers += [
    "accel_x_raw",
    "accel_y_raw",
    "accel_z_raw",
    "temperature_raw",
    "gyro_x_raw",
    "gyro_y_raw",
    "gyro_z_raw",
]

start = time.monotonic()
sample_count = 0

print(f"\nLogging to: {OUTPUT.resolve()}")
print("Sampling started. Press Ctrl+C to stop.\n")

with OUTPUT.open("w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(headers)

    try:
        while True:
            loop_start = time.monotonic()

            timestamp = datetime.now().isoformat()
            elapsed = time.monotonic() - start

            # Read all GPIOs
            gpio_raw, gpio_result = read_gpio()

            if gpio_raw is not None:
                gpio_raw = int(gpio_raw)
                gpio_bits = [
                    (gpio_raw >> bit) & 1
                    for bit in range(32)
                ]
                gpio_error = ""
            else:
                gpio_bits = [""] * 32
                gpio_error = gpio_result

            # Read IMU
            imu_data, imu_result = read_imu()

            if imu_data is not None:
                imu_data = bytes(imu_data)

                imu_hex = imu_data.hex()
                imu_bytes = list(imu_data)

                # Decode raw signed 16-bit values when available
                if len(imu_data) == IMU_LENGTH:
                    imu_values = [
                        int.from_bytes(
                            imu_data[i:i+2],
                            byteorder="big",
                            signed=True
                        )
                        for i in range(0, IMU_LENGTH, 2)
                    ]
                else:
                    imu_values = [""] * 7

                imu_error = (
                    "" if len(imu_data) == IMU_LENGTH
                    else f"Unexpected length: {len(imu_data)}"
                )

                # Pad short responses for consistent CSV columns
                imu_bytes += [""] * (IMU_LENGTH - len(imu_bytes))
                imu_bytes = imu_bytes[:IMU_LENGTH]

            else:
                imu_hex = ""
                imu_bytes = [""] * IMU_LENGTH
                imu_values = [""] * 7
                imu_error = imu_result

            # Write one combined sample
            writer.writerow([
                timestamp,
                round(elapsed, 6),
                gpio_raw if gpio_raw is not None else "",
                gpio_error,
                *gpio_bits,
                imu_hex,
                imu_error,
                *imu_bytes,
                *imu_values,
            ])

            file.flush()
            sample_count += 1

            if sample_count % 10 == 0:
                print(
                    f"Samples: {sample_count} | "
                    f"Elapsed: {elapsed:.2f}s | "
                    f"GPIO: {'OK' if gpio_raw is not None else 'ERROR'} | "
                    f"I2C: {'OK' if imu_data is not None else 'ERROR'}"
                )

            # Maintain approximate sampling interval
            remaining = SAMPLE_INTERVAL - (
                time.monotonic() - loop_start
            )

            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        print("\nStopping logger...")

print(f"Finished. Recorded {sample_count} samples.")
print(f"CSV saved to: {OUTPUT.resolve()}")
