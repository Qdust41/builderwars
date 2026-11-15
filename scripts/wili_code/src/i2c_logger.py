#!/usr/bin/env python3
"""Log I2C traffic on a FreeWili to a CSV file, using the OneWili I2C API.

Two modes (the FreeWili is connected to this computer over USB):

  read   The FreeWili is the I2C master. Every --interval seconds it reads
         --length bytes from register --register of the device at --address
         (dev.io.i2c) and one CSV row is written per read.

  slave  The FreeWili is an I2C slave at --address. Every master write it
         receives arrives as an `i2cslv` event (register, then data bytes) and
         is logged as a row. Any `i2cmon` monitor events are logged too.

Setup:
    git clone https://github.com/freewili/onewili
    pip install -e ./onewili/python

Examples:
    python i2c_to_csv.py --scan                                  # find devices
    python i2c_to_csv.py read --address 0x48 --register 0 --length 2 -d 30 -o temp.csv
    python i2c_to_csv.py slave --address 0x17 -d 60 -o slave.csv

CSV columns:
    host_time     ISO time on this computer
    device_ts_ns  FreeWili timestamp in ns (slave/monitor events; blank for reads)
    source        read | i2cslv | i2cmon
    address       7-bit I2C address (hex)
    register      register (hex)
    data_hex      data bytes, space separated hex
    error         error text if the read failed, else blank
"""
import argparse
import csv
import queue
import time
from datetime import datetime

import onewili
from onewili import encoding

FPGA_ZONE = 6   # the I2C functions require power zone 6 (FPGA)
FIELDS = ["host_time", "device_ts_ns", "source", "address", "register", "data_hex", "error"]


def now():
    return datetime.now().isoformat(timespec="milliseconds")


def hexs(data):
    return " ".join(f"{b:02X}" for b in data)


def int_auto(text):
    """Accept 0x48, 48h-style is not supported; plain ints are decimal."""
    return int(text, 0)


def unwrap(res, what):
    if isinstance(res, onewili.Ok):
        return res.value if hasattr(res, "value") else res.ok_value
    msg = getattr(res, "message", None) or getattr(res, "err_value", res)
    raise RuntimeError(f"{what} failed: {msg}")


def i2c_read(i2c, address, register, length):
    """Master read. The generated i2c_read() takes no arguments although the
    wire command needs <addr hex> <register hex> <length dec>, so call the
    underlying command directly."""
    return i2c._call(
        "r",
        [encoding.enc_hex(address, 2), encoding.enc_hex(register, 2), encoding.enc_int(length)],
        ["bytes"],
    )


def setup_bus(dev, freq=None, pullups=None, skip_power=False):
    if not skip_power:
        res = dev.hardware.power_management.set_zone(FPGA_ZONE, 1)
        if not isinstance(res, onewili.Ok):
            # The board-manager PIC didn't confirm the zone. Don't abort: the
            # I2C commands may still run (the firmware only refuses them once
            # it has a zone report saying the zone is off).
            print("warning: could not switch on power zone 6 (FPGA):",
                  getattr(res, "err_value", res))
            print("  -> unplug the FreeWili USB cable, plug it back in (full power cycle), "
                  "then rerun. Continuing anyway ...")
    i2c = dev.io.i2c
    if freq is not None:
        unwrap(i2c.settings.frequency(freq), "i2c frequency")
    if pullups is not None:
        unwrap(i2c.settings.pull_ups(int(pullups)), "i2c pull-ups")
    return i2c


def log_reads(i2c, writer, address, register, length, interval, duration):
    """Poll a device and write one row per read. Returns (ok_count, error_count)."""
    ok = errors = 0
    end = time.monotonic() + duration
    while time.monotonic() < end:
        t0 = time.monotonic()
        res = i2c_read(i2c, address, register, length)
        row = {"host_time": now(), "device_ts_ns": "", "source": "read",
               "address": f"{address:02X}", "register": f"{register:02X}",
               "data_hex": "", "error": ""}
        if isinstance(res, onewili.Ok):
            value = res.value if hasattr(res, "value") else res.ok_value
            row["data_hex"] = hexs(value)
            ok += 1
        else:
            row["error"] = str(getattr(res, "message", None) or getattr(res, "err_value", res))
            errors += 1
        writer.writerow(row)
        time.sleep(max(0.0, interval - (time.monotonic() - t0)))
    return ok, errors


def event_to_row(frame, slave_address):
    """Turn an i2cslv / i2cmon event frame into a CSV row."""
    name = frame.path.lstrip("*")
    data = bytes(int(t, 16) for t in frame.response.split())
    row = {"host_time": now(), "device_ts_ns": frame.timestamp_ns, "source": name,
           "address": "", "register": "", "data_hex": "", "error": ""}
    if name == "i2cslv" and data:
        row["address"] = f"{slave_address:02X}"
        row["register"] = f"{data[0]:02X}"      # first byte is the register
        row["data_hex"] = hexs(data[1:])
    else:
        row["data_hex"] = hexs(data)
    return row


def log_slave(events, writer, slave_address, duration, poll=0.1):
    """Drain i2cslv / i2cmon events for `duration` seconds. Returns row count."""
    n = 0
    end = time.monotonic() + duration
    while time.monotonic() < end:
        try:
            frame = events.get(timeout=poll)
        except queue.Empty:
            continue
        if frame.path.lstrip("*") in ("i2cslv", "i2cmon"):
            writer.writerow(event_to_row(frame, slave_address))
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", nargs="?", choices=["read", "slave"], help="what to log")
    ap.add_argument("--scan", action="store_true", help="probe all addresses (i2c_poll) and exit")
    ap.add_argument("-a", "--address", type=int_auto, help="7-bit I2C address, e.g. 0x48")
    ap.add_argument("-r", "--register", type=int_auto, default=0, help="register to read (read mode)")
    ap.add_argument("-n", "--length", type=int, default=1, help="bytes per read (read mode)")
    ap.add_argument("-i", "--interval", type=float, default=0.5, help="seconds between reads (read mode)")
    ap.add_argument("-d", "--duration", type=float, default=10.0, help="seconds to log")
    ap.add_argument("-o", "--output", default="i2c_log.csv", help="CSV file to write")
    ap.add_argument("--freq", type=int, help="I2C clock in Hz (leave unset to keep the device setting)")
    ap.add_argument("--pullups", type=int, choices=[0, 1], help="enable (1) / disable (0) bus pull-ups")
    ap.add_argument("--skip-power", action="store_true", help="don't try to switch on power zone 6")
    args = ap.parse_args()

    if not args.scan and (args.mode is None or args.address is None):
        ap.error("give a mode (read|slave) and --address, or use --scan")

    dev = onewili.connect()   # finds the FreeWili over USB with pyfwfinder
    try:
        i2c = setup_bus(dev, args.freq, args.pullups, args.skip_power)

        if args.scan:
            print("poll:", i2c.i2c_poll())
            time.sleep(1.0)
            transport = dev._transport
            while not transport.lines.empty():   # scan results come back as console lines
                print(transport.lines.get_nowait())
            return

        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()

            if args.mode == "read":
                print(f"Reading {args.length} byte(s) from 0x{args.address:02X} reg 0x{args.register:02X} "
                      f"every {args.interval:g}s for {args.duration:g}s ...")
                ok, errors = log_reads(i2c, writer, args.address, args.register,
                                       args.length, args.interval, args.duration)
                print(f"Saved {ok + errors} rows ({ok} ok, {errors} failed) to {args.output}")
            else:
                unwrap(i2c.i2c_slave_enable(args.address), "slave enable")
                try:
                    dev._transport.events.queue.clear()   # drop stale events
                    print(f"Slave at 0x{args.address:02X} on SDA16/SCL17, listening for {args.duration:g}s ...")
                    n = log_slave(dev._transport.events, writer, args.address, args.duration)
                finally:
                    i2c.i2c_slave_enable(0)   # 0 disables slave mode
                print(f"Saved {n} events to {args.output}")
    finally:
        dev.close()


if __name__ == "__main__":
    main()