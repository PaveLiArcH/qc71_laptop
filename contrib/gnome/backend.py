#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fixed-path qc71 RGB backend. No raw EC, brightness or fan writes."""
from pathlib import Path
import time

LED = Path('/sys/class/leds/qc71_laptop:rgb:kbd_backlight')
PROTOCOL = Path('/sys/module/qc71_laptop/parameters/keyboard_backlight_protocol')
SUPPLIES = Path('/sys/class/power_supply')


class KeyboardError(RuntimeError):
    pass


class Keyboard:
    def __init__(self, led=LED, protocol=PROTOCOL, supplies=SUPPLIES):
        self.led, self.protocol, self.supplies = led, protocol, supplies

    def validate(self):
        if self.protocol.read_text().strip() != 'intel-ac-dc-v1':
            raise KeyboardError('Unsupported qc71 keyboard protocol')
        order = self.led.joinpath('multi_index').read_text().split()
        if sorted(order) != ['blue', 'green', 'red']:
            raise KeyboardError('Expected a three-channel RGB keyboard')
        if self.led.joinpath('max_brightness').read_text().strip() != '255':
            raise KeyboardError('Unsupported LED range')
        return order

    def source(self):
        # Match the driver's system-supplied test, including USB-C supplies.
        ac0 = self.supplies / 'AC0' / 'online'
        if ac0.read_text().strip() not in ('0', '1'):
            raise KeyboardError('Cannot determine AC0 state')
        online = False
        for supply in self.supplies.iterdir():
            if supply.joinpath('type').read_text().strip() == 'Battery':
                continue
            scope = supply / 'scope'
            if scope.exists() and scope.read_text().strip() == 'Device':
                continue
            path = supply / 'online'
            if not path.exists():
                continue
            value = path.read_text().strip()
            if value not in ('0', '1'):
                raise KeyboardError('Cannot determine system power source')
            online |= value == '1'
        return 'ac' if online else 'dc'

    def read(self):
        order = self.validate()
        source = self.source()
        # Reading brightness can trigger the driver's read-only profile refresh.
        brightness = int(self.led.joinpath('brightness').read_text())
        values = list(map(int, self.led.joinpath('multi_intensity').read_text().split()))
        if len(values) != 3 or any(not 0 <= value <= 255 for value in values):
            raise KeyboardError('Invalid keyboard RGB state')
        if not 0 <= brightness <= 255:
            raise KeyboardError('Invalid keyboard brightness')
        if self.source() != source:
            raise KeyboardError('Power source changed; choose the color again')
        colors = dict(zip(order, values))
        return (*(colors[channel] for channel in ('red', 'green', 'blue')),
                brightness, source)

    def state(self):
        # Allow the asynchronous profile refresh to settle, without any writes.
        previous = self.read()
        for _ in range(5):
            time.sleep(0.1)
            current = self.read()
            if current == previous:
                return current
            previous = current
        raise KeyboardError('Keyboard state is changing; try again')

    def set_color(self, red, green, blue, expected_source):
        rgb = (red, green, blue)
        if any(type(value) is not int or not 0 <= value <= 255 for value in rgb):
            raise KeyboardError('RGB components must be integers from 0 to 255')
        # Near-black is OFF in this firmware, not an independently stored color.
        if not any((value * 50 + 127) // 255 for value in rgb):
            raise KeyboardError('Use GNOME brightness to turn the keyboard off')
        if expected_source not in ('ac', 'dc'):
            raise KeyboardError('Invalid power source')
        before = self.state()
        if before[4] != expected_source:
            raise KeyboardError('Power source changed; choose the color again')
        order = self.validate()
        colors = dict(zip(('red', 'green', 'blue'), rgb))
        if self.source() != expected_source:
            raise KeyboardError('Power source changed; choose the color again')
        # One complete sysfs write. Do not replay or restore into a different bank.
        self.led.joinpath('multi_intensity').write_text(
            ' '.join(str(colors[channel]) for channel in order) + '\n')
        expected = tuple((value * 50 + 127) // 255 for value in rgb)
        stable = 0
        for _ in range(15):
            time.sleep(0.1)
            current = self.read()
            if current[4] != expected_source:
                raise KeyboardError('Power source changed during apply; check the active profile')
            actual = tuple((value * 50 + 127) // 255 for value in current[:3])
            stable = stable + 1 if actual == expected else 0
            if stable == 3:
                return current
        raise KeyboardError('Color readback did not settle; check the keyboard and kernel log')
