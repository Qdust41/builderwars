
# # """Toggle GPIO 25 on a FreeWili."""
# import onewili

# dev = onewili.connect()
# try:
#     res = dev.io.gpio.set_io_toggle(25)
#     print(res)
# finally:
#     dev.close()




import onewili
import csv
import time
from datetime import datetime
from pathlib import Path

ADDRESS = 0x68
DATA_REGISTER = 0x3B
SAMPLE_INTERVAL = 0.1  # Target: 10 Hz
OUTPUT = Path("imu_i2c_test.csv")

dev = onewili.connect()
i2c = dev.io.i2c

# IMPORTANT: Return FREE-WILi to I2C master mode
result = i2c.i2c_slave_enable(0)
print("Disable slave mode:", result)

# Wake MPU6050: write 0x00 to PWR_MGMT_1
result = i2c.i2c_write(ADDRESS, 0x6B, bytes([0x00]))
print("Wake MPU6050:", result)

# Read WHO_AM_I using the firmware command directly.
# Address and register are hexadecimal strings.
def read_register(register, length):
    return i2c._call(
        "r",
        [f"{ADDRESS:02X}", f"{register:02X}", str(length)],
        ["bytes"],
        timeout=3.0
    )

identity = read_register(0x75, 1)
print("WHO_AM_I result:", identity)

if not identity:
    raise RuntimeError(
        "I2C read failed. Check the error above before starting CSV logging."
    )

print("WHO_AM_I bytes:", identity.ok_value.hex())

print("\nStarting IMU CSV logging. Press Ctrl+C to stop.")

start = time.monotonic()
count = 0

with OUTPUT.open("w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        "timestamp", "elapsed_s", "raw_hex",
        "accel_x", "accel_y", "accel_z",
        "temperature", "gyro_x", "gyro_y", "gyro_z"
    ])

    try:
        while True:
            loop_start = time.monotonic()

            result = read_register(DATA_REGISTER, 14)

            if result:
                raw = result.ok_value

                if len(raw) == 14:
                    values = [
                        int.from_bytes(
                            raw[i:i+2],
                            byteorder="big",
                            signed=True
                        )
                        for i in range(0, 14, 2)
                    ]

                    writer.writerow([
                        datetime.now().isoformat(),
                        round(time.monotonic() - start, 4),
                        raw.hex(),
                        *values
                    ])

                    f.flush()
                    count += 1

                    if count % 10 == 0:
                        print(
                            f"Samples: {count} | "
                            f"Raw: {raw.hex()}"
                        )
                else:
                    print("Unexpected response length:", len(raw))
            else:
                print("Read error:", result)

            remaining = SAMPLE_INTERVAL - (
                time.monotonic() - loop_start
            )
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        print("\nLogging stopped.")

print(f"Saved {count} samples to {OUTPUT.resolve()}")


