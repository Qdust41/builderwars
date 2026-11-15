#!/usr/bin/env python3
"""Record OneWili logger/device events over USB straight into a CSV file.

No SD card files are touched. The script starts the device logger (so its
armed/triggered/complete/error events fire), then listens to every event
frame the FreeWili sends over the USB serial connection and writes one CSV
row per event on this computer.

Setup:
    git clone https://github.com/freewili/onewili
    pip install -e ./onewili/python

Usage:
    python logger_to_csv.py                       # 5 s -> ./capture.csv
    python logger_to_csv.py -d 30 -o run.csv      # 30 s
    python logger_to_csv.py --no-logger           # just record events, don't arm the logger

CSV columns:
    host_time    ISO timestamp from this computer when the frame arrived
    device_ts_ns timestamp from the FreeWili (nanoseconds)
    seq          frame sequence number
    event        event name (logger, button, can0, uart1, i2cmon, ...)
    payload      the event's text payload
    ok           1/0 success flag from the frame
"""

import argparse
import csv
import queue
import time
from datetime import datetime

import onewili

TRIGGER_IMMEDIATE = 0  # logger.trigger_mode: start as soon as start() runs (assumed value)
FIELDS = ["host_time", "device_ts_ns", "seq", "event", "payload", "ok"]


def frame_to_row(frame):
    """Turn a ResponseFrame for an event ('[*name ...]') into a CSV row dict."""
    return {
        "host_time": datetime.now().isoformat(timespec="milliseconds"),
        "device_ts_ns": frame.timestamp_ns,
        "seq": frame.sequence,
        "event": frame.path.lstrip("*"),
        "payload": frame.response,
        "ok": int(bool(frame.success)),
    }


def record_events(events, writer, seconds, poll=0.1):
    """Drain the event queue into the CSV writer for `seconds`. Returns row count."""
    n = 0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            frame = events.get(timeout=poll)
        except queue.Empty:
            continue
        writer.writerow(frame_to_row(frame))
        n += 1
    # pick up anything still queued
    while True:
        try:
            writer.writerow(frame_to_row(events.get_nowait()))
            n += 1
        except queue.Empty:
            return n


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("-d", "--duration", type=float, default=5.0, help="seconds to record")
    ap.add_argument("-o", "--output", default="capture.csv", help="CSV file to write")
    ap.add_argument(
        "--no-logger", action="store_true", help="don't arm dev.logger, only record events"
    )
    args = ap.parse_args()

    dev = onewili.connect()  # finds the FreeWili over USB with pyfwfinder
    events = dev._transport.events  # queue of every [*event ...] frame from the device
    try:
        lg = dev.logger
        if not args.no_logger:
            lg.stop()  # clear any capture left over from an earlier run
            lg.active_instance(0)
            lg.events("all")
            lg.trigger_mode(TRIGGER_IMMEDIATE)
            lg.pre_trigger_ms(0)
            lg.post_trigger_ms(0)  # 0 = run until stop()

        # Drop stale frames so the CSV only has this run.
        while not events.empty():
            events.get_nowait()

        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()

            if not args.no_logger:
                res = lg.start()
                if not isinstance(res, onewili.Ok):
                    # Usually means the logger can't open its SD files. Events
                    # still stream over USB, so keep recording instead of quitting.
                    print(f"warning: logger.start() failed ({res}); recording USB events only")

            print(f"Recording for {args.duration:g} s ...")
            count = record_events(events, writer, args.duration)

            if not args.no_logger:
                lg.stop()
                count += record_events(events, writer, 1.0)  # catch the 'complete' event

        print(f"Saved {count} events to {args.output}")
        if count == 0:
            print(
                "No events arrived. Trigger something on the device (button press, "
                "CAN/UART/I2C traffic) while recording, or check the USB connection."
            )
    finally:
        dev.close()


if __name__ == "__main__":
    main()
