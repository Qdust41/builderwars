# # import onewili

# # dev = onewili.connect()   # discovers the device with pyfwfinder

# # # dev.gui.set_led_color(ledindex: int, red: int, green: int, blue: int, duration: int,
# # #                       mode: enums.owLEDManagerLEDMode | int) -> Result
# # # res = dev.gui.set_led_color(0, 0, 255, 0, 0, 0)
# # match res:
# #     case onewili.Ok(value):
# #         print(value)
# #     case onewili.Err(message):
# #         print("failed:", message)

# # dev.close()


# """Toggle GPIO 25 on a FreeWili."""
import onewili

dev = onewili.connect()
try:
    res = dev.io.gpio.set_io_toggle(25)
    print(res)
finally:
    dev.close()


# import onewili

# dev = onewili.connect()   # discovers the device with pyfwfinder

# # dev.gui.set_led_color(ledindex: int, red: int, green: int, blue: int, duration: int,
# #                       mode: enums.owLEDManagerLEDMode | int) -> Result
# # res = dev.gui.set_led_color(...)
# res = dev.io.gpio.set_io_toggle(25)

# match res:
#     case onewili.Ok(value):
#         print(value)
#     case onewili.Err(message):
#         print("failed:", message)

# dev.close()
