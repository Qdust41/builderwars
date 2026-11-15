import csv
import time
from datetime import datetime
from pathlib import Path

import onewili

# ---------------- CONFIGURATION ----------------

DURATION = 30.0
SAMPLE_INTERVAL = 0.05  # 20 Hz

GPIO_COUNT = 32

OUTPUT = Path(f"gpio_all_{datetime.now():%Y%m%d_%H%M%S}.csv")


# ---------------- API HELPERS ----------------


def unwrap(result):
    if isinstance(result, onewili.Ok):
        return result.ok_value

    if isinstance(result, onewili.Err):
        raise RuntimeError(result.err_value)

    raise RuntimeError(f"Unexpected result: {result}")


def read_all_gpio(dev):
    """Read all GPIO levels as a 32-bit bitfield."""
    return unwrap(dev.io.gpio.read_all())


def decode_gpio(raw):
    """Decode bitfield into individual GPIO values."""
    return {f"GPIO{i}": (raw >> i) & 1 for i in range(GPIO_COUNT)}


# ---------------- MAIN ----------------


def main():

    dev = None

    try:
        print("Connecting to FREE-WILi...")

        dev = onewili.connect()

        print("Connected.")
        print(f"Logging all {GPIO_COUNT} GPIO bits.")
        print(f"Output: {OUTPUT}")

        start = time.monotonic()
        next_sample = start

        sample_count = 0

        with OUTPUT.open("w", newline="") as f:
            writer = csv.writer(f)

            # CSV header
            writer.writerow(
                [
                    "timestamp",
                    "elapsed_seconds",
                    "raw_hex",
                    "raw_decimal",
                    *[f"GPIO{i}" for i in range(GPIO_COUNT)],
                ]
            )

            print("\nStarting acquisition...\n")

            while time.monotonic() - start < DURATION:
                now = time.monotonic()

                if now >= next_sample:
                    # Read entire GPIO bitfield
                    raw = read_all_gpio(dev)

                    # Normalize to unsigned 32-bit integer
                    raw = int(raw) & 0xFFFFFFFF

                    # Decode individual GPIOs
                    pins = decode_gpio(raw)

                    elapsed = time.monotonic() - start

                    timestamp = datetime.now().isoformat(timespec="milliseconds")

                    # Write CSV row
                    writer.writerow(
                        [timestamp, f"{elapsed:.6f}", f"0x{raw:08X}", raw, *pins.values()]
                    )

                    f.flush()

                    # Console output
                    print(f"[{elapsed:8.3f}s] RAW: 0x{raw:08X} | GPIO25: {pins['GPIO25']}")

                    sample_count += 1
                    next_sample += SAMPLE_INTERVAL

                time.sleep(0.001)

        print("\nAcquisition complete.")
        print(f"Samples: {sample_count}")
        print(f"CSV: {OUTPUT.resolve()}")

    finally:
        if dev is not None:
            dev.close()
            print("Disconnected.")


if __name__ == "__main__":
    main()
