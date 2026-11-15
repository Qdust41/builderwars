# ##!/usr/bin/env python3
# """Make a short CSV capture with the FREE-WILi OG onboard Logger.

# The CSV is written to the OG SD card under /logs. This does not read I2C
# or create synthetic measurements.

# Usage:
#     python logger_wili.py
#     python logger_wili.py --duration 20
# """

# import argparse
# import sys
# import time


# def check_result(onewili, result, operation):
#     if isinstance(result, onewili.Err):
#         raise RuntimeError(f"{operation} failed: {result.message}")
#     if isinstance(result, onewili.Ok):
#         return result.value
#     if result is None:
#         return None
#     raise RuntimeError(
#         f"{operation} returned unexpected result "
#         f"{type(result).__name__}: {result!r}"
#     )


# def main():
#     parser = argparse.ArgumentParser(
#         description="Capture device events to CSV using the onboard logger."
#     )
#     parser.add_argument("--duration", type=float, default=10.0,
#                         help="capture duration in seconds (default: 10)")
#     parser.add_argument("--instance", type=int, default=0, choices=range(4),
#                         help="logger instance 0-3 (default: 0)")
#     args = parser.parse_args()

#     if args.duration <= 0:
#         parser.error("--duration must be greater than zero")

#     dev = None
#     started = False

#     try:
#         print("[1/7] Importing OneWili...", flush=True)
#         import onewili

#         print("[2/7] Connecting to FREE-WILi over USB...", flush=True)
#         dev = onewili.connect()
#         print("      Connected.", flush=True)

#         logger = dev.logger

#         print(f"[3/7] Selecting logger instance {args.instance}...", flush=True)
#         check_result(onewili, logger.active_instance(args.instance),
#                      "Select logger instance")

#         print("[4/7] Configuring CSV, immediate trigger, and all capturable events...",
#               flush=True)
#         # Current logger setting values: CSV=0; Immediate trigger=0.
#         check_result(onewili, logger.file_format(0), "Set CSV file format")
#         check_result(onewili, logger.trigger_mode(0), "Set immediate trigger")
#         check_result(onewili, logger.pre_trigger_ms(0), "Set pre-trigger window")
#         check_result(onewili, logger.post_trigger_ms(0), "Set post-trigger window")
#         check_result(onewili, logger.events("all"), "Select all capturable events")

#         print("[5/7] Starting onboard logger...", flush=True)
#         check_result(onewili, logger.start(), "Start logger")
#         started = True

#         print(f"      Capturing for {args.duration:g} seconds. "
#               "CSV is being written to the OG SD card.", flush=True)
#         time.sleep(args.duration)

#         print("[6/7] Stopping logger and finalizing CSV...", flush=True)
#         check_result(onewili, logger.stop(), "Stop logger")
#         started = False

#         print("[7/7] Requesting logger status...", flush=True)
#         check_result(onewili, logger.status(), "Read logger status")

#         print("\nCapture command sequence completed.", flush=True)
#         print(f"Look on the OG SD card under /logs. The first unnamed capture "
#               f"for instance {args.instance} is normally "
#               f"log{args.instance}_0000.csv; subsequent captures increment "
#               "the number.", flush=True)
#         print("Note: selecting 'all' does not enable periodic event sources. "
#               "If no device events are being emitted, the CSV may contain "
#               "only its header.", flush=True)
#         return 0

#     except Exception as exc:
#         print(f"\nERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
#         print("Copy the exact error output if the script fails.",
#               file=sys.stderr, flush=True)
#         return 1

#     finally:
#         if dev is not None:
#             if started:
#                 try:
#                     print("Attempting to stop logger after error...", flush=True)
#                     dev.logger.stop()
#                 except Exception as stop_exc:
#                     print(f"Stop also failed: {stop_exc}", file=sys.stderr, flush=True)
#             try:
#                 dev.close()
#             except Exception:
#                 pass


# if __name__ == "__main__":
#     raise SystemExit(main())
