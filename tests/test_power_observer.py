#!/usr/bin/env python3
"""Read-only power observer checks using temporary files, never hardware."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
SPEC = importlib.util.spec_from_file_location('qc71_power_observer', TOOLS / 'observe_power.py')
observer = importlib.util.module_from_spec(SPEC)
with patch.object(sys, 'path', [str(TOOLS), *sys.path]), patch.object(sys, 'dont_write_bytecode', True):
    SPEC.loader.exec_module(observer)
hw = observer.hw


class PowerObserverTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='qc71-power-observer-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = Path.write_text
        for directory in ('led', 'regs', 'power_supply/AC0', 'power_supply/BAT0', 'params'):
            (self.root / directory).mkdir(parents=True)
        fixtures = {
            'board': 'LAPAC71G', 'power_supply/AC0/online': '1',
            'power_supply/AC0/type': 'Mains', 'power_supply/BAT0/type': 'Battery',
            'params/keyboard_backlight_protocol': 'intel-ac-dc-v1',
            'led/multi_index': 'red green blue',
            'led/multi_intensity': '255 255 255', 'led/brightness': '128',
            'regs/ADDR_INTELAC_AC_SINGLEBL_ENABLE': '0x02',
            'regs/ADDR_INTELAC_DC_SINGLEBL_ENABLE': '0x01',
        }
        for names, values in ((hw.KEYBOARD_RGB_REGS, (50, 50, 50)),
                              (hw.KEYBOARD_DC_RGB_REGS, (50, 0, 0))):
            fixtures.update({f'regs/{name}': str(value) for name, value in zip(names, values)})
        for name, value in fixtures.items():
            self.store(self.root / name, value)
        for name, value in (('DMI_BOARD', self.root / 'board'),
                            ('AC0', self.root / 'power_supply/AC0'),
                            ('POWER_SUPPLIES', self.root / 'power_supply'),
                            ('LED', self.root / 'led'), ('REGS', self.root / 'regs'),
                            ('PARAMS', self.root / 'params')):
            item = patch.object(hw, name, value)
            item.start()
            self.addCleanup(item.stop)
        self.real_read = hw.read
        self.events, self.answers, self.time = [], [], 0
        self.pending = None
        self.publish = True
        self.after_sleep = None
        self.brightness_reads = []
        self.output = io.StringIO()
        patches = [patch.object(hw, 'read', side_effect=self.read),
                   patch.object(hw, 'write', side_effect=AssertionError('software write')),
                   patch.object(Path, 'write_text', side_effect=AssertionError('direct write')),
                   patch.object(observer, 'input', side_effect=self.answer, create=True),
                   patch.object(observer.time, 'monotonic', side_effect=lambda: self.time),
                   patch.object(observer.time, 'sleep', side_effect=self.sleep),
                   contextlib.redirect_stdout(self.output)]
        for item in patches:
            item.__enter__()
            self.addCleanup(item.__exit__, None, None, None)

    def read(self, path):
        path = Path(path)
        self.assertTrue(path.is_relative_to(self.root), f'Host access: {path}')
        value = self.real_read(path)
        self.events.append((path.name, value))
        if path == hw.LED / 'brightness':
            expected = '255 255 255' if self.real_read(hw.AC0 / 'online') == '1' else '255 0 0'
            colors = [value for name, value in self.events if name == 'multi_intensity']
            self.assertEqual(colors[-2:], [expected, expected])
            self.brightness_reads.append(value)
        return value

    def answer(self, prompt):
        self.answers.append(prompt)
        if '(AC -> DC)' in prompt:
            self.store(hw.AC0 / 'online', '0')
            self.store(hw.LED / 'brightness', '64')
            self.pending = '255 0 0'
        elif '(DC -> AC)' in prompt:
            self.store(hw.AC0 / 'online', '1')
            self.store(hw.LED / 'brightness', '128')
            self.pending = '255 255 255'
        return 'фактический цвет подтверждён'

    def sleep(self, duration):
        self.time += duration
        if self.pending and self.publish:
            self.store(hw.LED / 'multi_intensity', self.pending)
            self.pending = None
        if self.after_sleep:
            self.after_sleep()

    def test_ac_dc_ac_read_only_and_cache_precedes_brightness(self):
        observer.observe_power()
        self.assertEqual(self.brightness_reads, ['128', '64', '128'])
        self.assertIn('PASS: cache AC -> DC -> AC settled before each brightness_get',
                      self.output.getvalue())
        self.assertTrue(any('БЕЛЫЙ' in answer for answer in self.answers))
        self.assertTrue(any('КРАСНЫЙ' in answer for answer in self.answers))
        self.assertEqual(self.real_read(hw.AC0 / 'online'), '1')

    def test_timeout_does_not_fall_back_to_brightness_getter(self):
        self.publish = False
        with self.assertRaisesRegex(RuntimeError, 'did not settle'):
            observer.observe_power()
        self.assertEqual(self.brightness_reads, ['128'])
        self.assertIn('Верните и оставьте адаптер', self.output.getvalue())

    def test_source_change_during_settlement_is_rejected_before_getter(self):
        def change_source():
            if self.pending == '255 0 0':
                self.store(hw.AC0 / 'online', '1')
        self.publish = False
        self.after_sleep = change_source
        with self.assertRaisesRegex(RuntimeError, 'stable DC'):
            observer.observe_power()
        self.assertEqual(self.brightness_reads, ['128'])

    def test_raw_profile_change_is_rejected_before_getter(self):
        def change_profile():
            if self.real_read(hw.AC0 / 'online') == '0':
                self.store(hw.REGS / hw.KEYBOARD_DC_RGB_REGS[1], '1')
        self.after_sleep = change_profile
        with self.assertRaisesRegex(RuntimeError, 'raw profiles changed'):
            observer.observe_power()
        self.assertEqual(self.brightness_reads, ['128'])

    def test_identical_rgb_is_inconclusive_without_brightness_or_hotkeys(self):
        for name in hw.KEYBOARD_DC_RGB_REGS:
            self.store(hw.REGS / name, '50')
        observer.observe_power()
        self.assertEqual(self.brightness_reads, [])
        self.assertEqual(self.answers, [])
        self.assertIn('INCONCLUSIVE', self.output.getvalue())

    def test_apply_bit_does_not_change_saved_profile(self):
        def transient_apply():
            self.store(hw.REGS / hw.KEYBOARD_ENABLE_REGS[0], '0x0a')
        self.after_sleep = transient_apply
        observer.observe_power()
        self.assertEqual(self.brightness_reads, ['128', '64', '128'])

    def test_rainbow_profile_expects_effect_instead_of_static_stored_color(self):
        self.store(hw.REGS / hw.KEYBOARD_ENABLE_REGS[1], '0x21')
        observer.observe_power()
        dc_question = next(answer for answer in self.answers if answer.startswith('DC:'))
        self.assertIn('переливающиеся цвета (rainbow)', dc_question)
        self.assertNotIn('КРАСНЫЙ', dc_question)

    def test_other_online_nonbattery_source_blocks_dc_before_getter(self):
        usb = hw.POWER_SUPPLIES / 'usb'
        usb.mkdir()
        self.store(usb / 'type', 'USB')
        self.store(usb / 'online', '1')
        with self.assertRaises(RuntimeError):
            observer.observe_power()
        self.assertEqual(self.brightness_reads, ['128'])

    def test_offline_usb_and_online_battery_do_not_block_dc(self):
        usb = hw.POWER_SUPPLIES / 'usb'
        usb.mkdir()
        self.store(usb / 'type', 'USB')
        self.store(usb / 'online', '0')
        self.store(hw.POWER_SUPPLIES / 'BAT0/online', '1')
        observer.observe_power()
        self.assertEqual(self.brightness_reads, ['128', '64', '128'])

    def test_device_scope_online_supply_does_not_supply_the_system(self):
        usb = hw.POWER_SUPPLIES / 'usb'
        usb.mkdir()
        self.store(usb / 'scope', 'Device')
        self.store(usb / 'type', 'USB')
        self.store(usb / 'online', '1')
        observer.observe_power()
        self.assertEqual(self.brightness_reads, ['128', '64', '128'])

    def test_unknown_nonbattery_online_blocks_dc_before_getter(self):
        usb = hw.POWER_SUPPLIES / 'usb'
        usb.mkdir()
        self.store(usb / 'type', 'USB')
        with self.assertRaises((OSError, RuntimeError)):
            observer.observe_power()
        self.assertEqual(self.brightness_reads, ['128'])

    def test_invalid_initial_source_and_board_are_rejected_without_getter(self):
        for path, value, message in ((hw.AC0 / 'online', '0', 'stable AC'),
                                     (hw.DMI_BOARD, 'other', 'LAPAC71G')):
            with self.subTest(path=path):
                old = self.real_read(path)
                self.store(path, value)
                with self.assertRaisesRegex(RuntimeError, message):
                    observer.observe_power()
                self.store(path, old)
        self.assertEqual(self.brightness_reads, [])


class Lapac71HPowerObserverTests(PowerObserverTests):
    def setUp(self):
        super().setUp()
        self.store(hw.DMI_BOARD, 'LAPAC71H')


if __name__ == '__main__':
    unittest.main()
