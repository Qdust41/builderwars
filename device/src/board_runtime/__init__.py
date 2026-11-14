"""Python runtime for the development board.

Assumes CPython >= 3.12 on the board for now. If the board turns out to run MicroPython or an
older CPython (open decision #1), the protocol package's pydantic dependency must be replaced
with a lightweight validator generated from the same JSON Schemas.
"""
