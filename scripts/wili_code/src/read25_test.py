

import onewili
import csv
import time
from datetime import datetime
from pathlib import Path

# Configuration
PIN = 25
DURATION = 30
TOGGLE_INTERVAL = 0.5
SAMPLE_INTERVAL = 0.05

OUTPUT = Path(f"gpio25_{datetime.now():%Y%m%d_%H%M%S}.csv")


def unwrap(result):
    if isinstance(result, onewili.Ok):
        return result.ok_value
    if isinstance(result, onewili.Err):
        raise RuntimeError(result.err_value)
    raise RuntimeError(f"Unexpected result: {result}")


def read_pin(dev, pin):
    # Read complete GPIO bitfield
    bitfield = unwrap(dev.io.gpio.read_all())

    # Extract requested GPIO
    return (bitfield >> pin) & 1


def set_pin(dev, pin, state):
    if state:
        return unwrap(dev.io.gpio.set_io_high(pin))
    else:
        return unwrap(dev.io.gpio.set_io_low(pin))


def main():

    dev = None

    try:
        print("Connecting...")
        dev = onewili.connect()
        print("Connected.")

        # Establish known initial state
        set_pin(dev, PIN, 0)

        start = time.monotonic()
        next_toggle = start
        next_sample = start

        commanded_state = 0
        toggle_count = 0
        sample_count = 0

        with OUTPUT.open("w", newline="") as f:

            writer = csv.writer(f)

            writer.writerow([
                "timestamp",
                "elapsed_s",
                "commanded_state",
                "read_state",
                "toggle_count",
                "match"
            ])

            print("Recording...\n")

            while time.monotonic() - start < DURATION:

                now = time.monotonic()

                # Toggle at configured interval
                if now >= next_toggle:

                    commanded_state = 1 - commanded_state

                    set_pin(dev, PIN, commanded_state)

                    toggle_count += 1
                    next_toggle += TOGGLE_INTERVAL

                # Poll GPIO
                if now >= next_sample:

                    read_state = read_pin(dev, PIN)

                    elapsed = time.monotonic() - start
                    timestamp = datetime.now().isoformat(
                        timespec="milliseconds"
                    )

                    match = commanded_state == read_state

                    writer.writerow([
                        timestamp,
                        f"{elapsed:.6f}",
                        commanded_state,
                        read_state,
                        toggle_count,
                        match
                    ])

                    f.flush()

                    print(
                        f"{elapsed:7.3f}s | "
                        f"Command: {commanded_state} | "
                        f"Read: {read_state} | "
                        f"Match: {match}"
                    )

                    sample_count += 1
                    next_sample += SAMPLE_INTERVAL

                time.sleep(0.001)

        print("\nExperiment complete.")
        print(f"Samples: {sample_count}")
        print(f"Toggles: {toggle_count}")
        print(f"CSV: {OUTPUT.resolve()}")

    finally:
        if dev is not None:
            dev.close()
            print("Disconnected.")


if __name__ == "__main__":
    main()
