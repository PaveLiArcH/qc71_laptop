#!/usr/bin/env python3
"""Test the hardware helper using temporary files only; no device access."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


HELPER_PATH = Path(__file__).resolve().parents[1] / "tools" / "hardware_test.py"
SPEC = importlib.util.spec_from_file_location("qc71_hardware_helper", HELPER_PATH)
helper = importlib.util.module_from_spec(SPEC)
with patch("sys.dont_write_bytecode", True):
    SPEC.loader.exec_module(helper)


class HardwareHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="qc71-helper-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.paths = {name: self.root / name for name in
                      ("led", "battery", "platform", "fan", "pwm", "regs", "params", "ac")}
        fixtures = {
            "led": {"multi_intensity": "20 40 60", "brightness": "128",
                    "max_brightness": "255", "multi_index": "red green blue"},
            "battery": {"charge_control_end_threshold": "80", "type": "Battery",
                        "capacity": "72", "status": "Discharging"},
            "platform": {"manual_control": "0"},
            "fan": {"fan1_input": "3000", "fan2_input": "3000",
                    "temp1_input": "56000", "temp2_input": "47000"},
            "pwm": {"pwm1_enable": "2", "pwm1": "100", "pwm2": "100"},
            "params": {"fan_control": "Y", "keyboard_backlight_protocol": "legacy"},
            "ac": {"online": "1", "type": "Mains"},
            "regs": {"ADDR_RGBKB_LEVEL_R": "0x04", "ADDR_RGBKB_LEVEL_G": "0x08",
                     "ADDR_RGBKB_LEVEL_B": "0x0c", "ctrl_2": "0x40", "trigger_1": "0x00",
                     "ADDR_INTELAC_AC_SINGLEBL_ENABLE": "0x02",
                     "ADDR_INTELAC_DC_SINGLEBL_ENABLE": "0x02",
                     "ADDR_RGBKBDC_LEVEL_R": "0x32", "ADDR_RGBKBDC_LEVEL_G": "0x32",
                     "ADDR_RGBKBDC_LEVEL_B": "0x32", "ctrl_1": "0x00", "fan_ctrl": "0x00"},
        }
        for kind, files in fixtures.items():
            self.paths[kind].mkdir()
            for name, value in files.items():
                (self.paths[kind] / name).write_text(value)
        self.power_supplies = self.root / 'power_supplies'
        self.power_supplies.mkdir()
        (self.power_supplies / 'AC0').symlink_to(self.paths['ac'], target_is_directory=True)
        (self.power_supplies / 'BAT0').symlink_to(self.paths['battery'], target_is_directory=True)

        self.original_read, self.original_write = helper.read, helper.write
        self.api_brightness = 128
        self.intel_backend = False
        self.applied_ac_level = 1
        self.applied_dc_level = 1
        self.ac_commands = []
        self.dc_commands = []
        self.board_name = self.root / 'board_name'
        self.board_name.write_text('LAPAC71G')
        self.modules = self.root / 'modules'
        self.modules.write_text('')
        self.raw_ec = self.root / 'ec'

        patches = [
            patch.object(helper, "DMI_BOARD", self.board_name),
            patch.object(helper, "LED", self.paths["led"]),
            patch.object(helper, "BATTERY", self.paths["battery"]),
            patch.object(helper, "PLATFORM", self.paths["platform"]),
            patch.object(helper, "REGS", self.paths["regs"]),
            patch.object(helper, "PARAMS", self.paths["params"]),
            patch.object(helper, "AC0", self.paths["ac"]),
            patch.object(helper, "POWER_SUPPLIES", self.power_supplies),
            patch.object(helper, "MODULES", self.modules),
            patch.object(helper.os, "geteuid", return_value=0),
            patch.object(helper, "read", side_effect=self.read),
            patch.object(helper, "write", side_effect=self.write),
            patch.object(helper, "hwmon", side_effect=self.hwmon),
            patch.object(helper.time, "sleep"),
            patch.object(helper, "input", create=True,
                         return_value="mocked observation"),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def read(self, path):
        path = Path(path)
        self.assertTrue(path.is_relative_to(self.root), f"Read outside fixture: {path}")
        if path == helper.LED / "brightness":
            if self.intel_backend:
                control, _rgb, _online = helper.keyboard_led_bank(self.active_power_source())
                ctrl = int(self.original_read(helper.REGS / control), 0)
                self.api_brightness = 0 if ctrl & 0x10 else (min(ctrl & 7, 4) * 255 + 2) // 4
            else:
                ctrl = int(self.original_read(helper.REGS / "ctrl_2"), 0)
                self.api_brightness = (0 if ctrl & 2 else
                                       (min(ctrl >> 5, 4) * 255 + 2) // 4)
            return str(self.api_brightness)
        return self.original_read(path)

    def write(self, path, value):
        """Model the LED driver's zero-brightness RGB skip, not just files."""
        path = Path(path)
        self.assertTrue(path.is_relative_to(self.root), f"Write outside fixture: {path}")
        self.original_write(path, value)
        if path == helper.LED / "brightness":
            self.api_brightness = int(value)
        if path in (helper.LED / "brightness", helper.LED / "multi_intensity") and self.intel_backend:
            intensities = list(map(int, self.original_read(helper.LED / "multi_intensity").split()))
            rgb = [(intensity * 50 + 127) // 255 for intensity in intensities]
            source = self.active_power_source()
            control, rgb_registers, _online = helper.keyboard_led_bank(source)
            ctrl = int(self.original_read(helper.REGS / control), 0)
            level = max(1, (self.api_brightness * 4 + 127) // 255) if self.api_brightness else 0
            if path == helper.LED / "multi_intensity" and any(rgb):
                for name, raw in zip(rgb_registers, rgb):
                    self.original_write(helper.REGS / name, raw)
            target = ((ctrl & ~0x1f) | level | 0x08) if level and any(rgb) else (ctrl | 0x18)
            self.apply_profile_command(source, target)
        elif path in (helper.LED / "brightness", helper.LED / "multi_intensity"):
            intensities = list(map(int, self.original_read(helper.LED / "multi_intensity").split()))
            rgb = [(intensity * 50 + 127) // 255 for intensity in intensities]
            level = (self.api_brightness * 4 + 127) // 255 if any(rgb) else 0
            if level:
                for name, raw in zip(helper.KEYBOARD_RGB_REGS, rgb):
                    self.original_write(helper.REGS / name, raw)
            ctrl = int(self.original_read(helper.REGS / "ctrl_2"), 0)
            ctrl = (ctrl & ~0xf2) | level << 5 | (0 if level else 2)
            self.original_write(helper.REGS / "ctrl_2", ctrl)
        elif path == helper.REGS / helper.INTEL_AC_CONTROL:
            self.apply_ac_command(int(value))
        elif path == helper.PLATFORM / "manual_control":
            ctrl = int(self.original_read(helper.REGS / "ctrl_1"), 0)
            self.original_write(helper.REGS / "ctrl_1", (ctrl | 1) if int(value) else (ctrl & ~1))
            if not int(value):
                self.original_write(self.paths["pwm"] / "pwm1_enable", 2)
                ctrl = int(self.original_read(helper.REGS / "fan_ctrl"), 0)
                self.original_write(helper.REGS / "fan_ctrl", ctrl & ~0x40)
        elif path == self.paths["pwm"] / "pwm1_enable":
            ctrl = int(self.original_read(helper.REGS / "fan_ctrl"), 0)
            self.original_write(helper.REGS / "fan_ctrl", (ctrl & ~0x40) if int(value) == 2 else (ctrl | 0x40))
            if not int(value):
                self.original_write(self.paths["pwm"] / "pwm1", 255)
                self.original_write(self.paths["pwm"] / "pwm2", 255)
        elif path in (self.paths['pwm'] / 'pwm1', self.paths['pwm'] / 'pwm2'):
            self.original_write(path, (int(value) * 200 // 255) * 255 // 200)
        elif path == helper.REGS / "ctrl_2":
            # Model firmware consuming the transient apply-level command.
            self.original_write(path, int(value) & ~0x10)
        elif path == helper.REGS / "trigger_1":
            self.original_write(path, int(value) & ~0x20)

    def active_power_source(self):
        # The production backend follows generic system-supplied status, so an
        # online USB/UCSI supply can select AC even when AC0 itself is offline.
        for supply in helper.POWER_SUPPLIES.iterdir():
            scope = supply / 'scope'
            if scope.exists() and self.original_read(scope) == 'Device':
                continue
            if self.original_read(supply / 'type') == 'Battery':
                continue
            if self.original_read(supply / 'online') != '0':
                return 'ac'
        return 'dc'

    def apply_ac_command(self, command):
        self.apply_profile_command('ac', command)

    def apply_profile_command(self, source, command):
        commands = self.ac_commands if source == 'ac' else self.dc_commands
        commands.append(command)
        control, rgb_registers, _online = helper.keyboard_led_bank(source)
        self.original_write(helper.REGS / control, command & ~0x08)
        if command & 0x08:
            applied_level = 0 if command & 0x10 else command & 7
            if source == 'ac':
                self.applied_ac_level = applied_level
            else:
                self.applied_dc_level = applied_level
            # OFF may gate the light without clearing the latched RGB outputs.
            if (self.raw_ec.exists() and not command & 0x10 and
                    source == self.active_power_source()):
                contents = bytearray(self.raw_ec.read_bytes())
                for address, name in zip((0x1803, 0x1805, 0x1808), rgb_registers):
                    raw = int(self.original_read(helper.REGS / name), 0)
                    contents[address] = min(255, raw * applied_level)
                self.raw_ec.write_bytes(contents)

    def enable_intel_backend(self, power_source='ac'):
        self.zero_brightness_baseline()
        self.intel_backend = True
        (helper.AC0 / 'online').write_text('1' if power_source == 'ac' else '0')
        (helper.PARAMS / 'keyboard_backlight_protocol').write_text('intel-ac-dc-v1')
        self.create_raw_ec()

    def dc_green_baseline(self):
        self.enable_intel_backend('dc')
        (helper.LED / 'multi_intensity').write_text('0 255 0')
        for name, value in zip(helper.KEYBOARD_DC_RGB_REGS, (0, 50, 0)):
            (helper.REGS / name).write_text(str(value))
        (helper.REGS / helper.KEYBOARD_ENABLE_REGS[1]).write_text('0x03')
        # The inactive AC profile deliberately differs from the DC cache.
        for name, value in zip(helper.KEYBOARD_RGB_REGS, (50, 0, 0)):
            (helper.REGS / name).write_text(str(value))

    def add_power_supply(self, name, supply_type='USB', online='0', scope=None):
        supply = helper.POWER_SUPPLIES / name
        supply.mkdir()
        (supply / 'type').write_text(supply_type)
        if online is not None:
            (supply / 'online').write_text(online)
        if scope is not None:
            (supply / 'scope').write_text(scope)
        return supply


    def hwmon(self, name):
        return {"qc71_laptop.hwmon.fan": self.paths["fan"],
                "qc71_laptop.hwmon.pwm": self.paths["pwm"]}[name]

    def assert_keyboard_restored(self):
        self.assertEqual(helper.read(helper.LED / "multi_intensity"), "20 40 60")
        self.assertEqual(helper.read(helper.LED / "brightness"), "128")
        self.assertEqual([helper.read_register(name) for name in helper.KEYBOARD_RGB_REGS],
                         [4, 8, 12])
        self.assertEqual(helper.read_register("ctrl_2") & 0xe2, 0x40)

    def zero_brightness_baseline(self):
        (helper.LED / "multi_intensity").write_text("255 255 255")
        (helper.LED / "brightness").write_text("0")
        for name in helper.KEYBOARD_RGB_REGS:
            (helper.REGS / name).write_text("0x32")
        (helper.REGS / "ctrl_2").write_text("0x00")
        self.api_brightness = 0

    def assert_zero_brightness_baseline_restored(self):
        self.assertEqual(helper.read(helper.LED / "multi_intensity"), "255 255 255")
        self.assertEqual(helper.read(helper.LED / "brightness"), "0")
        self.assertEqual([helper.read_register(name) for name in helper.KEYBOARD_RGB_REGS],
                         [50, 50, 50])
        self.assertEqual(helper.read_register("ctrl_2"), 0)

    def fail_write_once(self, number):
        original_write = helper.write
        count = 0

        def write(path, value):
            nonlocal count
            count += 1
            if count == number:
                raise OSError("injected write failure")
            original_write(path, value)

        return patch.object(helper, "write", side_effect=write)

    def test_keyboard_color_and_brightness_are_restored(self):
        with patch.object(helper, "write", wraps=helper.write) as write:
            helper.keyboard_test("red")
        self.assert_keyboard_restored()
        self.assertEqual(write.call_args_list[0].args,
                         (helper.LED / "multi_intensity", "255 0 0"))
        self.assertIn("КРАСНЫЙ", helper.input.call_args.args[0])

    def test_keyboard_is_restored_after_a_test_write_fails(self):
        for number in (1, 2):
            with self.subTest(write=number), self.fail_write_once(number):
                with self.assertRaisesRegex(OSError, "injected write failure"):
                    helper.keyboard_test("blue")
                self.assert_keyboard_restored()
        helper.input.assert_not_called()

    def test_firmware_default_color_is_rejected_before_writing(self):
        (helper.LED / "multi_intensity").write_text("0 0 0")
        with patch.object(helper, "write") as write:
            with self.assertRaisesRegex(RuntimeError, "cannot restore"):
                helper.keyboard_test("red")
            write.assert_not_called()

    def test_keyboard_no_prompt_keeps_confirmation_pending(self):
        helper.keyboard_test("green", prompt=False)
        helper.input.assert_not_called()
        self.assertIn("pending user confirmation", self.output.getvalue())
        self.assert_keyboard_restored()

    def test_keyboard_observe_cli_only_reads_and_captures_native_hotkey_changes(self):
        self.zero_brightness_baseline()
        optional = dict.fromkeys(helper.KEYBOARD_DC_RGB_REGS, '0x32')
        optional.update({'support_2': '0x04', 'ADDR_INTELAC_TIMTER_ENABLE': '0x02',
                         'power_source': '0x01', 'power_status': '0x02'})
        for name, value in optional.items():
            (helper.REGS / name).write_text(value)
        inputs = 0

        def native_hotkey(question):
            nonlocal inputs
            inputs += 1
            if inputs == 1:
                self.assertIn('Fn+F7 ровно один раз', question)
                (helper.REGS / 'ADDR_INTELAC_AC_SINGLEBL_ENABLE').write_text('0x12')
                (helper.REGS / 'ADDR_INTELAC_TIMTER_ENABLE').write_text('0x04')
                return ''
            self.assertIn('БЕЛЫЙ', question)
            return 'Подсветка загорелась белым'

        def firmware_delay(seconds):
            self.assertEqual(seconds, 2)
            (helper.REGS / 'ADDR_INTELAC_TIMTER_ENABLE').write_text('0x06')

        with patch.object(helper, 'write') as write, \
                patch.object(helper, 'require_device') as require_device, \
                patch.object(helper, 'input', side_effect=native_hotkey), \
                patch.object(helper.time, 'sleep', side_effect=firmware_delay), \
                patch('sys.argv', ['hardware_test.py', 'keyboard-observe']):
            helper.main()
        write.assert_not_called()
        require_device.assert_not_called()
        self.assertEqual(inputs, 2)
        lines = self.output.getvalue().splitlines()
        snapshots = [json.loads(line.split(':', 1)[1]) for line in lines
                     if line.startswith(('Keyboard before Fn+F7:',
                                         'Keyboard immediately after Fn+F7:',
                                         'Keyboard 2s after Fn+F7:'))]
        self.assertEqual(len(snapshots), 3)
        self.assertEqual([state['ADDR_INTELAC_AC_SINGLEBL_ENABLE'] for state in snapshots],
                         ['0x02', '0x12', '0x12'])
        self.assertEqual([state['ADDR_INTELAC_TIMTER_ENABLE'] for state in snapshots],
                         ['0x02', '0x04', '0x06'])
        self.assertEqual(snapshots[0]['support_2'], '0x04')
        self.assertEqual([state['power_source'] for state in snapshots],
                         ['0x01', '0x01', '0x01'])
        self.assertIn('Сохраняйте текущее подключение питания', self.output.getvalue())
        self.assertEqual([snapshots[0][name] for name in helper.KEYBOARD_DC_RGB_REGS],
                         ['0x32', '0x32', '0x32'])
        self.assertIn('Подсветка загорелась белым', self.output.getvalue())

    def test_keyboard_observe_tolerates_missing_optional_registers_without_writes(self):
        with patch.object(helper, 'write') as write:
            helper.keyboard_observe(prompt=False)
        write.assert_not_called()
        helper.input.assert_called_once()
        self.assertNotIn('ADDR_INTELAC_TIMTER_ENABLE', self.output.getvalue())
        self.assertIn('pending user confirmation', self.output.getvalue())

    def test_keyboard_observe_rejects_other_boards_before_writes_or_hotkey_prompt(self):
        self.board_name.write_text('LAPAC71G-other')
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'restricted to LAPAC71G'):
                helper.keyboard_observe()
        write.assert_not_called()
        helper.input.assert_not_called()

    def create_raw_ec(self):
        contents = bytearray(max(helper.KEYBOARD_IMMEDIATE_ADDRS) + 1)
        for address, value in zip(helper.KEYBOARD_IMMEDIATE_ADDRS, (200, 64, 50, 50, 50)):
            contents[address] = value
        self.raw_ec.write_bytes(contents)
        return contents

    def test_immediate_ec_reads_are_unbuffered_allowlisted_single_bytes(self):
        contents = self.create_raw_ec()
        stream = io.BytesIO(contents)
        with patch.object(stream, 'seek', wraps=stream.seek) as seek, \
                patch.object(stream, 'read', wraps=stream.read) as read_byte, \
                patch.object(Path, 'open', return_value=stream) as open_ec:
            readings = helper.keyboard_immediate_readings()
        open_ec.assert_called_once_with('rb', buffering=0)
        self.assertEqual([call.args for call in seek.call_args_list],
                         [(address,) for address in helper.KEYBOARD_IMMEDIATE_ADDRS])
        self.assertEqual([call.args for call in read_byte.call_args_list], [(1,)] * 5)
        self.assertEqual(readings, {f'immediate_0x{address:04x}': f'0x{contents[address]:02x}'
                                    for address in helper.KEYBOARD_IMMEDIATE_ADDRS})

    def test_keyboard_observe_includes_available_immediate_ec_bytes(self):
        self.create_raw_ec()
        with patch.object(helper, 'write') as write:
            helper.keyboard_observe(prompt=False)
        write.assert_not_called()
        for address in helper.KEYBOARD_IMMEDIATE_ADDRS:
            self.assertIn(f'immediate_0x{address:04x}', self.output.getvalue())

    def test_intel_ac_brightness_writes_only_level4_then_exact_raw_baseline(self):
        self.zero_brightness_baseline()
        self.create_raw_ec()
        helper.input.side_effect = ['исходная яркость средняя', 'ярче, белый, после возврата ярко']
        with patch.object(helper, 'write', wraps=helper.write) as write, \
                patch('sys.argv', ['hardware_test.py', 'keyboard-intel-brightness']):
            helper.main()
        ac_control = helper.REGS / helper.INTEL_AC_CONTROL
        self.assertEqual([call.args for call in write.call_args_list],
                         [(ac_control, 0x0c), (ac_control, 0x0a)])
        self.assertEqual(helper.read_register(helper.INTEL_AC_CONTROL), 0x02)
        self.assert_zero_brightness_baseline_restored()
        self.assertEqual(helper.read_register('ADDR_INTELAC_DC_SINGLEBL_ENABLE'), 0x02)
        self.assertEqual(helper.read(helper.PLATFORM / 'manual_control'), '0')
        self.assertIn('обычную клавишу на встроенной клавиатуре',
                      helper.input.call_args_list[0].args[0])
        self.assertIn('исходную яркость', helper.input.call_args_list[0].args[0])
        self.assertIn('БЕЛЫЙ', helper.input.call_args_list[1].args[0])
        self.assertIn('после применения сохранённого level 2', helper.input.call_args_list[1].args[0])
        output = self.output.getvalue()
        self.assertIn('Intel AC readback at 0s:', output)
        self.assertIn('Intel AC readback at 4s:', output)
        self.assertIn('Intel AC after raw restore:', output)
        self.assertIn('immediate_0x1801', output)
        self.assertIn('Исходный скрытый Fn-уровень нужно оценить отдельно', output)
        self.assertIn('Fn+F7', output)
        self.assertNotIn('Исходная подсветка восстановлена', output)

    def test_intel_ac_no_prompt_uses_no_input_and_leaves_observation_pending(self):
        self.zero_brightness_baseline()
        helper.input.side_effect = AssertionError("input forbidden with --no-prompt")
        with patch.object(helper, 'write', wraps=helper.write) as write, \
                patch('sys.argv', ['hardware_test.py', '--no-prompt',
                                   'keyboard-intel-brightness']):
            helper.main()
        helper.input.assert_not_called()
        self.assertEqual(len(write.call_args_list), 2)
        self.assertIn('pending user confirmation', self.output.getvalue())

    def test_intel_restore_requires_apply_to_change_outputs_not_just_stored_level(self):
        self.zero_brightness_baseline()
        self.create_raw_ec()
        helper.write(helper.REGS / helper.INTEL_AC_CONTROL, 0x0c)
        helper.write(helper.REGS / helper.INTEL_AC_CONTROL, 0x02)
        self.assertEqual(helper.read_register(helper.INTEL_AC_CONTROL), 2)
        self.assertEqual(self.applied_ac_level, 4)
        self.assertEqual(self.raw_ec.read_bytes()[0x1803], 200)
        helper.keyboard_intel_brightness(prompt=False)
        self.assertEqual(self.ac_commands[-1], 0x0a)
        self.assertEqual(helper.read_register(helper.INTEL_AC_CONTROL), 2)
        self.assertEqual(self.applied_ac_level, 2)
        self.assertEqual(self.raw_ec.read_bytes()[0x1803], 100)
        self.assertIn('Исходный скрытый Fn-уровень', self.output.getvalue())

    def test_keyboard_led_uses_only_standard_api_and_restores_configured_target(self):
        self.enable_intel_backend()
        unrelated = helper.keyboard_unrelated_settings()
        helper.input.side_effect = ['до опыта тусклый белый', 'яркий красный, тусклее, выкл; затем белый']
        with patch.object(helper, 'write', wraps=helper.write) as write, \
                patch('sys.argv', ['hardware_test.py', 'keyboard-led']):
            helper.main()
        self.assertEqual([call.args for call in write.call_args_list], [
            (helper.LED / 'multi_intensity', '255 0 0'),
            (helper.LED / 'brightness', 255), (helper.LED / 'brightness', 64),
            (helper.LED / 'brightness', 0), (helper.LED / 'brightness', 0),
            (helper.LED / 'multi_intensity', '255 255 255'),
            (helper.LED / 'brightness', 128)])
        self.assertEqual(helper.keyboard_unrelated_settings(), unrelated)
        self.assertEqual(helper.read(helper.LED / 'brightness'), '128')
        self.assertEqual(helper.read(helper.LED / 'multi_intensity'), '255 255 255')
        self.assertEqual(self.ac_commands[-1], 0x0a)
        self.assertEqual(self.applied_ac_level, 2)
        self.assertEqual(self.raw_ec.read_bytes()[0x1803], 100)
        self.assertIn('Скрытый native Fn-уровень', self.output.getvalue())
        self.assertIn('яркий КРАСНЫЙ', helper.input.call_args_list[-1].args[0])
        self.assertIn('ВЫКЛЮЧЕН', helper.input.call_args_list[-1].args[0])
        states = [json.loads(line.split(':', 1)[1]) for line in self.output.getvalue().splitlines()
                  if line.startswith('LED API OFF at 4s:')]
        self.assertEqual(states[0]['LED/brightness'], '0')
        self.assertEqual(states[0]['immediate_0x1803'], '0x32')

    def test_keyboard_led_rejects_off_baseline_before_writes(self):
        self.enable_intel_backend()
        (helper.REGS / helper.INTEL_AC_CONTROL).write_text('0x12')
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'OFF baseline'):
                helper.keyboard_led_test(prompt=False)
        write.assert_not_called()
        self.assertEqual(helper.read_register(helper.INTEL_AC_CONTROL), 0x12)
        helper.input.assert_not_called()

    def test_keyboard_led_no_prompt_uses_no_input_and_keeps_confirmation_pending(self):
        self.enable_intel_backend()
        helper.input.side_effect = AssertionError('input forbidden with --no-prompt')
        with patch('sys.argv', ['hardware_test.py', '--no-prompt', 'keyboard-led']):
            helper.main()
        helper.input.assert_not_called()
        self.assertIn('Разбудите встроенную клавиатуру', self.output.getvalue())
        self.assertIn('pending user confirmation', self.output.getvalue())

    def test_keyboard_led_rejects_inconsistent_cache_and_raw_rgb_before_writes(self):
        self.enable_intel_backend()
        (helper.LED / 'multi_intensity').write_text('0 255 0')
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'did not settle within 2s'):
                helper.keyboard_led_test()
        write.assert_not_called()
        helper.input.assert_not_called()

    def test_legacy_keyboard_test_rejects_new_intel_marker(self):
        self.enable_intel_backend()
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'use keyboard-led'):
                helper.keyboard_test('red')
        write.assert_not_called()
        helper.input.assert_not_called()

    def test_keyboard_led_waits_for_asynchronous_setter_before_physical_stage(self):
        self.enable_intel_backend()
        original_write = helper.write
        pending = []
        queued = False

        def queue_first_brightness(path, value):
            nonlocal queued
            if path == helper.LED / 'brightness' and value == 255 and not queued:
                queued = True
                pending.append((path, value))
                return
            original_write(path, value)

        def settle(_seconds):
            if pending:
                original_write(*pending.pop())

        with patch.object(helper, 'write', side_effect=queue_first_brightness), \
                patch.object(helper.time, 'sleep', side_effect=settle):
            helper.keyboard_led_test(prompt=False)
        self.assertTrue(queued)
        self.assertEqual(pending, [])
        self.assertEqual(helper.read(helper.LED / 'brightness'), '128')

    def test_keyboard_led_never_committed_target_times_out_but_restores(self):
        self.enable_intel_backend()
        original_write = helper.write

        def silently_drop_target(path, value):
            if path != helper.LED / 'brightness' or value != 255:
                original_write(path, value)

        with patch.object(helper, 'write', side_effect=silently_drop_target):
            with self.assertRaisesRegex(RuntimeError, 'did not settle within 2s'):
                helper.keyboard_led_test()
        self.assertEqual(helper.read(helper.LED / 'brightness'), '128')
        self.assertEqual(helper.read(helper.LED / 'multi_intensity'), '255 255 255')
        helper.input.assert_called_once()

    def test_keyboard_led_guards_reject_old_backend_black_source_and_manual(self):
        self.enable_intel_backend()
        cases = [
            (helper.PARAMS / 'keyboard_backlight_protocol', 'legacy', 'intel-ac-dc-v1'),
            (helper.LED / 'max_brightness', '4', 'max_brightness=255'),
            (helper.LED / 'multi_intensity', '0 0 0', 'Black/default'),
            (helper.REGS / helper.INTEL_AC_CONTROL, '0x22', 'rainbow baseline'),
            (helper.AC0 / 'online', '0', 'AC0 online=1'),
            (helper.PLATFORM / 'manual_control', '1', 'manual_control=0')]
        for path, value, message in cases:
            with self.subTest(guard=path.name):
                old = path.read_text()
                path.write_text(value)
                try:
                    with patch.object(helper, 'write') as write:
                        with self.assertRaisesRegex(RuntimeError, message):
                            helper.keyboard_led_test()
                    write.assert_not_called()
                    helper.input.assert_not_called()
                finally:
                    path.write_text(old)

    def test_keyboard_led_quantization_accepts_normalized_color_cache(self):
        self.enable_intel_backend()
        (helper.LED / 'multi_intensity').write_text('20 41 61')
        for name, raw in zip(helper.KEYBOARD_RGB_REGS, (4, 8, 12)):
            (helper.REGS / name).write_text(str(raw))
        helper.wait_keyboard_led_target('20 40 60', 128)
        self.assertEqual([helper.quantized_keyboard_brightness(value) for value in
                          (0, 1, 64, 127, 128, 191, 255)], [0, 64, 64, 128, 128, 191, 255])

    def test_keyboard_led_every_probe_write_failure_restores_through_api(self):
        for number in range(1, 5):
            self.enable_intel_backend()
            with self.subTest(write=number), self.fail_write_once(number):
                with self.assertRaisesRegex(OSError, 'injected write failure'):
                    helper.keyboard_led_test()
            self.assertEqual(helper.read(helper.LED / 'brightness'), '128')
            self.assertEqual(helper.read(helper.LED / 'multi_intensity'), '255 255 255')

    def test_keyboard_led_cleanup_failures_are_aggregated_and_other_steps_run(self):
        self.enable_intel_backend()
        with self.fail_write_once(5):
            with self.assertRaisesRegex(RuntimeError, 'restore LED off: injected write failure'):
                helper.keyboard_led_test()
        self.assertEqual(helper.read(helper.LED / 'brightness'), '128')
        self.assertEqual(helper.read(helper.LED / 'multi_intensity'), '255 255 255')
        helper.input.assert_called_once()

    def test_keyboard_led_ac_loss_stops_api_writes_and_does_not_touch_dc(self):
        self.enable_intel_backend()
        dc = {name: helper.read_register(name) for name in
              helper.KEYBOARD_DC_RGB_REGS + (helper.KEYBOARD_ENABLE_REGS[1],)}

        def unplug_during_stage(seconds):
            if seconds == 3:
                (helper.AC0 / 'online').write_text('0')

        with patch.object(helper, 'write', wraps=helper.write) as write, \
                patch.object(helper.time, 'sleep', side_effect=unplug_during_stage):
            with self.assertRaisesRegex(RuntimeError, 'AC restoration is pending'):
                helper.keyboard_led_test()
        self.assertEqual([call.args for call in write.call_args_list],
                         [(helper.LED / 'multi_intensity', '255 0 0'),
                          (helper.LED / 'brightness', 255)])
        self.assertEqual({name: helper.read_register(name) for name in dc}, dc)
        helper.input.assert_called_once()

    def test_keyboard_led_dc_cli_blue_stages_restore_dc_and_preserve_inactive_ac(self):
        self.dc_green_baseline()
        unrelated = helper.keyboard_unrelated_settings('dc')
        helper.input.side_effect = ['тусклый зелёный на батарее', 'яркий синий, тусклее синий, выкл, зелёный']
        with patch.object(helper, 'write', wraps=helper.write) as write, \
                patch('sys.argv', ['hardware_test.py', 'keyboard-led', '--power-source', 'dc']):
            helper.main()
        self.assertEqual([call.args for call in write.call_args_list], [
            (helper.LED / 'multi_intensity', '0 0 255'),
            (helper.LED / 'brightness', 255), (helper.LED / 'brightness', 64),
            (helper.LED / 'brightness', 0), (helper.LED / 'brightness', 0),
            (helper.LED / 'multi_intensity', '0 255 0'),
            (helper.LED / 'brightness', 191)])
        self.assertEqual(helper.keyboard_unrelated_settings('dc'), unrelated)
        self.assertEqual(helper.read(helper.LED / 'brightness'), '191')
        self.assertEqual(helper.read(helper.LED / 'multi_intensity'), '0 255 0')
        self.assertEqual(self.ac_commands, [])
        self.assertEqual(self.dc_commands[-1], 0x0b)
        self.assertEqual(self.applied_dc_level, 3)
        self.assertIn('яркий СИНИЙ', helper.input.call_args_list[-1].args[0])
        self.assertIn('тусклее СИНИЙ', helper.input.call_args_list[-1].args[0])
        self.assertIn('батареи', self.output.getvalue())
        readings = next(line for line in self.output.getvalue().splitlines()
                        if line.startswith('LED API bright BLUE at 0s:'))
        state = json.loads(readings.split(':', 1)[1])
        self.assertEqual(state['selected_profile'], 'dc')
        self.assertEqual(state['AC0/online'], '0')
        self.assertEqual([state[name] for name in helper.KEYBOARD_DC_RGB_REGS],
                         ['0x00', '0x00', '0x32'])
        self.assertEqual([state[name] for name in helper.KEYBOARD_RGB_REGS],
                         ['0x32', '0x00', '0x00'])

    def test_keyboard_led_dc_no_prompt_never_calls_input(self):
        self.dc_green_baseline()
        helper.input.side_effect = AssertionError('input forbidden with --no-prompt')
        with patch('sys.argv', ['hardware_test.py', '--no-prompt', 'keyboard-led',
                               '--power-source', 'dc']):
            helper.main()
        helper.input.assert_not_called()
        self.assertIn('pending user confirmation', self.output.getvalue())
        self.assertIn('bright BLUE -> DIMMER BLUE -> OFF', self.output.getvalue())

    def test_dc_power_source_allows_offline_usb_and_ignores_battery_online(self):
        self.dc_green_baseline()
        self.add_power_supply('ucsi-source-psy-USBC000:001', scope='System')
        self.add_power_supply('ucsi-source-psy-USBC000:002', scope='System')
        (helper.BATTERY / 'online').write_text('1')
        with patch.object(helper, 'write') as write:
            helper.require_dc_power_source()
        write.assert_not_called()

    def test_keyboard_led_dc_rejects_online_or_unknown_usb_before_writing(self):
        self.dc_green_baseline()
        usb = self.add_power_supply('ucsi-source-psy-USBC000:001', scope='System')
        for online in ('1', '2', 'unknown', '', None):
            with self.subTest(online=online):
                if online is None:
                    (usb / 'online').unlink()
                else:
                    (usb / 'online').write_text(online)
                with patch.object(helper, 'write') as write:
                    with self.assertRaisesRegex(RuntimeError, 'DC restoration is pending'):
                        helper.keyboard_led_test(power_source='dc')
                write.assert_not_called()
        helper.input.assert_not_called()
        self.assertEqual(self.ac_commands, [])
        self.assertEqual(self.dc_commands, [])

    def test_dc_power_source_rejects_unknown_type_or_unreadable_online(self):
        self.dc_green_baseline()
        usb = self.add_power_supply('USB')
        for supply_type in ('', None):
            with self.subTest(supply_type=supply_type):
                if supply_type is None:
                    (usb / 'type').unlink()
                else:
                    (usb / 'type').write_text(supply_type)
                with patch.object(helper, 'write') as write:
                    with self.assertRaises(RuntimeError):
                        helper.require_dc_power_source()
                write.assert_not_called()
        (usb / 'type').write_text('USB')
        original_read = helper.read

        def unreadable_online(path):
            if Path(path) == usb / 'online':
                raise PermissionError('injected online read failure')
            return original_read(path)

        with patch.object(helper, 'read', side_effect=unreadable_online), \
                patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'Cannot verify all power supplies'):
                helper.require_dc_power_source()
        write.assert_not_called()

    def test_dc_power_source_rejects_empty_inventory(self):
        self.dc_green_baseline()
        empty = self.root / 'empty_power_supplies'
        empty.mkdir()
        with patch.object(helper, 'POWER_SUPPLIES', empty), \
                patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'inventory is empty'):
                helper.require_dc_power_source()
        write.assert_not_called()

    def test_dc_power_source_excludes_only_exact_device_scope(self):
        self.dc_green_baseline()
        usb = self.add_power_supply('device-usb', online='1', scope='Device')
        # Scope is checked first, as in the kernel; device-local supplies need
        # neither a system type nor an ONLINE property for DC classification.
        (usb / 'type').unlink()
        (usb / 'online').unlink()
        with patch.object(helper, 'write') as write:
            helper.require_dc_power_source()
        write.assert_not_called()
        (usb / 'type').write_text('USB')
        (usb / 'online').write_text('1')
        with patch.object(helper, 'write') as write:
            helper.require_dc_power_source()
        write.assert_not_called()
        for scope in ('System', 'Unknown', '', 'device'):
            (usb / 'scope').write_text(scope)
            with self.subTest(scope=scope), patch.object(helper, 'write') as write:
                with self.assertRaisesRegex(RuntimeError, 'non-battery supply offline'):
                    helper.require_dc_power_source()
            write.assert_not_called()
        (usb / 'scope').unlink()
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'non-battery supply offline'):
                helper.require_dc_power_source()
        write.assert_not_called()

    def test_keyboard_led_dc_usb_online_during_probe_skips_restore_into_ac(self):
        self.dc_green_baseline()
        usb = self.add_power_supply('ucsi-source-psy-USBC000:001', scope='System')
        ac = helper.keyboard_unrelated_settings('dc')

        def connect_usb_during_stage(seconds):
            if seconds == 3:
                (usb / 'online').write_text('1')

        with patch.object(helper, 'write', wraps=helper.write) as write, \
                patch.object(helper.time, 'sleep', side_effect=connect_usb_during_stage):
            with self.assertRaisesRegex(RuntimeError, 'DC restoration is pending'):
                helper.keyboard_led_test(power_source='dc')
        self.assertEqual(helper.read(helper.AC0 / 'online'), '0')
        self.assertEqual(self.active_power_source(), 'ac')
        self.assertEqual([call.args for call in write.call_args_list],
                         [(helper.LED / 'multi_intensity', '0 0 255'),
                          (helper.LED / 'brightness', 255)])
        self.assertEqual(helper.keyboard_unrelated_settings('dc'), ac)
        self.assertEqual(self.ac_commands, [])

    def test_keyboard_led_dc_rejects_source_off_rainbow_default_or_stale_cache(self):
        cases = [('source', 'AC0 online=0'), ('off', 'OFF baseline'),
                 ('rainbow', 'rainbow baseline'), ('default', 'Default raw RGB'),
                 ('cache', 'did not settle within 2s')]
        for case, message in cases:
            self.dc_green_baseline()
            with self.subTest(guard=case):
                if case == 'source':
                    (helper.AC0 / 'online').write_text('1')
                elif case == 'off':
                    (helper.REGS / helper.KEYBOARD_ENABLE_REGS[1]).write_text('0x13')
                elif case == 'rainbow':
                    (helper.REGS / helper.KEYBOARD_ENABLE_REGS[1]).write_text('0x23')
                elif case == 'default':
                    for name in helper.KEYBOARD_DC_RGB_REGS:
                        (helper.REGS / name).write_text('0')
                else:
                    (helper.LED / 'multi_intensity').write_text('255 0 0')
                with patch.object(helper, 'write') as write:
                    with self.assertRaisesRegex(RuntimeError, message):
                        helper.keyboard_led_test(power_source='dc')
                write.assert_not_called()
                helper.input.assert_not_called()

    def test_keyboard_led_dc_adapter_connection_after_wake_blocks_all_writes(self):
        self.dc_green_baseline()
        ac = helper.keyboard_unrelated_settings('dc')
        helper.input.side_effect = lambda _question: (helper.AC0 / 'online').write_text('1')
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'DC restoration is pending'):
                helper.keyboard_led_test(power_source='dc')
        write.assert_not_called()
        self.assertEqual(helper.keyboard_unrelated_settings('dc'), ac)

    def test_keyboard_led_dc_connection_during_probe_skips_restore_into_ac(self):
        self.dc_green_baseline()
        ac = helper.keyboard_unrelated_settings('dc')

        def connect_during_stage(seconds):
            if seconds == 3:
                (helper.AC0 / 'online').write_text('1')

        with patch.object(helper, 'write', wraps=helper.write) as write, \
                patch.object(helper.time, 'sleep', side_effect=connect_during_stage):
            with self.assertRaisesRegex(RuntimeError, 'DC restoration is pending'):
                helper.keyboard_led_test(power_source='dc')
        self.assertEqual([call.args for call in write.call_args_list],
                         [(helper.LED / 'multi_intensity', '0 0 255'),
                          (helper.LED / 'brightness', 255)])
        self.assertEqual(helper.keyboard_unrelated_settings('dc'), ac)
        self.assertEqual(self.ac_commands, [])

    def test_keyboard_led_dc_each_probe_failure_restores_dc_not_ac(self):
        for number in range(1, 5):
            self.dc_green_baseline()
            ac = helper.keyboard_unrelated_settings('dc')
            with self.subTest(write=number), self.fail_write_once(number):
                with self.assertRaisesRegex(OSError, 'injected write failure'):
                    helper.keyboard_led_test(power_source='dc')
            self.assertEqual(helper.read(helper.LED / 'brightness'), '191')
            self.assertEqual(helper.read(helper.LED / 'multi_intensity'), '0 255 0')
            self.assertEqual(helper.keyboard_unrelated_settings('dc'), ac)
            self.assertEqual(self.ac_commands, [])

    def test_keyboard_led_dc_cleanup_failure_continues_in_dc_and_reports_error(self):
        self.dc_green_baseline()
        ac = helper.keyboard_unrelated_settings('dc')
        with self.fail_write_once(5):
            with self.assertRaisesRegex(RuntimeError, 'restore LED off: injected write failure'):
                helper.keyboard_led_test(power_source='dc')
        self.assertEqual(helper.read(helper.LED / 'brightness'), '191')
        self.assertEqual(helper.read(helper.LED / 'multi_intensity'), '0 255 0')
        self.assertEqual(helper.keyboard_unrelated_settings('dc'), ac)
        self.assertEqual(self.ac_commands, [])

    def test_intel_ac_initial_guards_reject_without_writes_or_wake_prompt(self):
        self.zero_brightness_baseline()
        guards = [
            (self.board_name, 'LAPAC71G-other', 'restricted to LAPAC71G'),
            (helper.PLATFORM / 'manual_control', '1', 'manual_control=0'),
            (helper.AC0 / 'online', '0', 'AC0 online=1'),
            (helper.REGS / helper.INTEL_AC_CONTROL, '0x04', 'exact initial AC control 0x02'),
            (helper.REGS / 'ADDR_RGBKB_LEVEL_G', '0', 'equal nonzero RGB'),
        ]
        for path, value, expected in guards:
            with self.subTest(guard=path.name):
                old = path.read_text()
                path.write_text(value)
                try:
                    with patch.object(helper, 'write') as write:
                        with self.assertRaisesRegex(RuntimeError, expected):
                            helper.keyboard_intel_brightness()
                    write.assert_not_called()
                    helper.input.assert_not_called()
                finally:
                    path.write_text(old)

    def test_intel_ac_requires_new_module_root_and_no_conflicting_driver(self):
        self.zero_brightness_baseline()
        (helper.PARAMS / 'fan_control').unlink()
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'newly built module'):
                helper.keyboard_intel_brightness()
        write.assert_not_called()
        (helper.PARAMS / 'fan_control').write_text('Y')
        with patch.object(helper.os, 'geteuid', return_value=1000), \
                patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'sudo'):
                helper.keyboard_intel_brightness()
        write.assert_not_called()
        self.modules.write_text('tuxedo_io 1000 0 - Live 0x0')
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'Other EC drivers'):
                helper.keyboard_intel_brightness()
        write.assert_not_called()
        helper.input.assert_not_called()

    def test_intel_ac_rejects_all_zero_rgb_without_writes(self):
        self.zero_brightness_baseline()
        for name in helper.KEYBOARD_RGB_REGS:
            (helper.REGS / name).write_text('0')
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'equal nonzero RGB'):
                helper.keyboard_intel_brightness()
        write.assert_not_called()
        helper.input.assert_not_called()

    def test_intel_ac_accepts_other_equal_nonzero_white_rgb_without_changing_it(self):
        self.zero_brightness_baseline()
        for name in helper.KEYBOARD_RGB_REGS:
            (helper.REGS / name).write_text('16')
        with patch.object(helper, 'write', wraps=helper.write) as write:
            helper.keyboard_intel_brightness(prompt=False)
        self.assertEqual([call.args for call in write.call_args_list],
                         [(helper.REGS / helper.INTEL_AC_CONTROL, 0x0c),
                          (helper.REGS / helper.INTEL_AC_CONTROL, 0x0a)])
        self.assertEqual([helper.read_register(name) for name in helper.KEYBOARD_RGB_REGS],
                         [16, 16, 16])

    def test_intel_ac_rechecks_guards_after_wake_before_any_write(self):
        self.zero_brightness_baseline()
        helper.input.side_effect = lambda _question: (helper.AC0 / 'online').write_text('0')
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'AC0 online=1'):
                helper.keyboard_intel_brightness()
        write.assert_not_called()
        helper.input.assert_called_once()

    def test_intel_ac_restores_after_probe_write_fails(self):
        self.zero_brightness_baseline()
        with self.fail_write_once(1):
            with self.assertRaisesRegex(OSError, 'injected write failure'):
                helper.keyboard_intel_brightness()
        self.assertEqual(helper.read_register(helper.INTEL_AC_CONTROL), 0x02)
        helper.input.assert_called_once()

    def test_intel_ac_restores_after_error_reported_after_probe_write(self):
        self.zero_brightness_baseline()
        original_write = helper.write

        def write_then_fail(path, value):
            original_write(path, value)
            if value == 0x0c:
                raise OSError('ambiguous write completion')

        with patch.object(helper, 'write', side_effect=write_then_fail) as write:
            with self.assertRaisesRegex(OSError, 'ambiguous write completion'):
                helper.keyboard_intel_brightness()
        self.assertEqual([call.args[1] for call in write.call_args_list], [0x0c, 0x0a])
        self.assertEqual(helper.read_register(helper.INTEL_AC_CONTROL), 0x02)

    def test_intel_ac_restores_after_a_during_readback_error(self):
        self.zero_brightness_baseline()
        original_readings = helper.keyboard_intel_readings
        calls = 0

        def fail_during_readback():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError('injected during readback failure')
            return original_readings()

        with patch.object(helper, 'keyboard_intel_readings', side_effect=fail_during_readback), \
                patch.object(helper, 'write', wraps=helper.write) as write:
            with self.assertRaisesRegex(OSError, 'injected during readback failure'):
                helper.keyboard_intel_brightness()
        self.assertEqual([call.args[1] for call in write.call_args_list], [0x0c, 0x0a])
        self.assertEqual(helper.read_register(helper.INTEL_AC_CONTROL), 0x02)
        self.assertEqual(calls, 5)

    def test_intel_ac_restores_on_interrupt_or_adapter_change(self):
        for interrupt in (True, False):
            self.zero_brightness_baseline()
            (helper.AC0 / 'online').write_text('1')

            def interrupt_or_unplug(_seconds):
                if interrupt:
                    raise KeyboardInterrupt('injected interrupt')
                (helper.AC0 / 'online').write_text('0')

            with self.subTest(interrupt=interrupt), \
                    patch.object(helper.time, 'sleep', side_effect=interrupt_or_unplug):
                with self.assertRaises(KeyboardInterrupt if interrupt else RuntimeError):
                    helper.keyboard_intel_brightness()
            self.assertEqual(helper.read_register(helper.INTEL_AC_CONTROL), 0x02)

    def test_intel_ac_restore_failure_is_reported_without_physical_success_claim(self):
        self.zero_brightness_baseline()
        with self.fail_write_once(2):
            with self.assertRaisesRegex(RuntimeError, 'Intel AC raw restoration failed'):
                helper.keyboard_intel_brightness()
        self.assertEqual(helper.read_register(helper.INTEL_AC_CONTROL), 0x04)
        self.assertIn('Intel AC after raw restore:', self.output.getvalue())
        self.assertNotIn('Применён сохранённый configured level 2', self.output.getvalue())
        helper.input.assert_called_once()

    def test_zero_brightness_baseline_restores_actual_rgb_and_ctrl(self):
        self.zero_brightness_baseline()
        with patch.object(helper, "write", wraps=helper.write) as write:
            helper.keyboard_test("red", prompt=False)
        self.assert_zero_brightness_baseline_restored()
        self.assertTrue(any(call.args == (helper.REGS / "trigger_1", 0x20)
                            for call in write.call_args_list))
        during = next(line for line in self.output.getvalue().splitlines()
                      if line.startswith("Keyboard readback at 0s:"))
        raw = json.loads(during.split(":", 1)[1])
        self.assertEqual([raw[name] for name in helper.KEYBOARD_RGB_REGS],
                         ["0x32", "0x00", "0x00"])
        self.assertEqual(int(raw["ctrl_2"], 0) & 0xe2, 0x80)
        self.assertEqual(raw["ADDR_INTELAC_AC_SINGLEBL_ENABLE"], "0x02")
        self.assertEqual(raw["ADDR_INTELAC_DC_SINGLEBL_ENABLE"], "0x02")
        self.assertEqual(raw["manual_control"], "0")

    def test_restore_preserves_current_foreign_ctrl_flags(self):
        self.zero_brightness_baseline()

        def change_foreign_flags(_seconds):
            ctrl = helper.read_register("ctrl_2")
            (helper.REGS / "ctrl_2").write_text(str(ctrl | 0x0d))

        with patch.object(helper.time, "sleep", side_effect=change_foreign_flags):
            helper.keyboard_test("red", prompt=False)
        self.assertEqual(helper.read_register("ctrl_2"), 0x0d)
        self.assertEqual([helper.read_register(name) for name in helper.KEYBOARD_RGB_REGS],
                         [50, 50, 50])

    def test_restore_does_not_compare_transient_apply_level_bit(self):
        self.zero_brightness_baseline()
        (helper.REGS / "ctrl_2").write_text("0x10")
        helper.keyboard_test("red", prompt=False)
        self.assert_zero_brightness_baseline_restored()

    def test_missing_debug_register_blocks_test_before_writing(self):
        (helper.REGS / "ADDR_RGBKB_LEVEL_R").unlink()
        with patch.object(helper, "write") as write:
            with self.assertRaises(FileNotFoundError):
                helper.keyboard_test("red")
            write.assert_not_called()

    def test_zero_raw_default_color_is_rejected_even_when_off(self):
        self.zero_brightness_baseline()
        for name in helper.KEYBOARD_RGB_REGS:
            (helper.REGS / name).write_text("0x00")
        with patch.object(helper, "write") as write:
            with self.assertRaisesRegex(RuntimeError, "cannot be restored exactly"):
                helper.keyboard_test("red")
            write.assert_not_called()

    def test_rainbow_mode_blocks_fixed_color_test_before_writing(self):
        (helper.REGS / "trigger_1").write_text("0x80")
        with patch.object(helper, "write") as write:
            with self.assertRaisesRegex(RuntimeError, "Rainbow mode"):
                helper.keyboard_test("red")
            write.assert_not_called()

    def test_restore_continues_after_api_cleanup_failure(self):
        self.zero_brightness_baseline()
        with self.fail_write_once(3):
            with self.assertRaisesRegex(RuntimeError, "LED off: injected write failure"):
                helper.keyboard_test("red")
        self.assert_zero_brightness_baseline_restored()
        helper.input.assert_not_called()

    def test_multiple_restore_failures_are_aggregated_and_remaining_steps_run(self):
        self.zero_brightness_baseline()
        original_write = helper.write
        failed = {helper.REGS / "ADDR_RGBKB_LEVEL_G", helper.REGS / "trigger_1"}

        def fail_cleanup(path, value):
            if path in failed:
                raise OSError("injected raw restore failure")
            original_write(path, value)

        with patch.object(helper, "write", side_effect=fail_cleanup):
            with self.assertRaises(RuntimeError) as raised:
                helper.keyboard_test("red")
        message = str(raised.exception)
        self.assertIn("restore ADDR_RGBKB_LEVEL_G: injected raw restore failure", message)
        self.assertIn("apply restored RGB: injected raw restore failure", message)
        self.assertIn("verify ADDR_RGBKB_LEVEL_G", message)
        self.assertEqual(helper.read_register("ADDR_RGBKB_LEVEL_B"), 50)
        self.assertEqual(helper.read_register("ctrl_2"), 0)
        self.assertEqual(helper.read(helper.LED / "multi_intensity"), "255 255 255")
        helper.input.assert_not_called()

    def test_battery_threshold_is_restored(self):
        helper.battery_test(90)
        self.assertEqual(helper.read(helper.BATTERY / "charge_control_end_threshold"), "80")

    def test_battery_threshold_is_restored_after_a_test_write_fails(self):
        with self.fail_write_once(1):
            with self.assertRaisesRegex(OSError, "injected write failure"):
                helper.battery_test(90)
        self.assertEqual(helper.read(helper.BATTERY / "charge_control_end_threshold"), "80")

    def test_unchanged_battery_threshold_is_rejected_without_writing(self):
        with patch.object(helper, "write") as write:
            with self.assertRaisesRegex(RuntimeError, "different"):
                helper.battery_test(80)
            write.assert_not_called()

    def test_fans_return_to_bios_and_request_physical_confirmation(self):
        with patch.object(helper, "write", wraps=helper.write) as write:
            helper.fan_test()
        self.assertEqual(helper.read(helper.PLATFORM / "manual_control"), "0")
        self.assertEqual(write.call_args_list[-1].args,
                         (helper.PLATFORM / "manual_control", 0))
        self.assertIn("ускорились", helper.input.call_args.args[0])
        self.assertIn("90%", helper.input.call_args.args[0])
        for stage in ('Full', '90%'):
            for elapsed in (0, 4, 8):
                self.assertIn(f'{stage} at {elapsed}s:', self.output.getvalue())
        for elapsed in (0, 4, 8):
            self.assertIn(f'BIOS after {elapsed}s:', self.output.getvalue())
        self.assertEqual([call.args for call in helper.time.sleep.call_args_list], [(4,)] * 6)
        self.assertEqual(helper.read(self.paths['pwm'] / 'pwm1'), '229')
        self.assertEqual(helper.read(self.paths['pwm'] / 'pwm2'), '229')

    def test_fans_return_to_bios_after_each_test_write_failure(self):
        for number in range(1, 6):
            (self.paths["pwm"] / "pwm1_enable").write_text("2")
            with self.subTest(write=number), self.fail_write_once(number):
                with self.assertRaisesRegex(OSError, "injected write failure"):
                    helper.fan_test()
                self.assertEqual(helper.read(helper.PLATFORM / "manual_control"), "0")
        helper.input.assert_not_called()

    def simulate_owned_fan_suspend(self, question, firmware_handoff=False):
        """Model the driver's PM release, without invoking any system sleep."""
        (self.paths['pwm'] / 'pwm1_enable').write_text('2')
        (helper.REGS / 'fan_ctrl').write_text('0x00')
        if firmware_handoff:
            (helper.PLATFORM / 'manual_control').write_text('0')
            (helper.REGS / 'ctrl_1').write_text('0x00')
        return 'both accelerated, then slowed after wake'

    def assert_fans_bios(self):
        self.assertEqual(helper.read(helper.PLATFORM / 'manual_control'), '0')
        self.assertEqual(helper.read(self.paths['pwm'] / 'pwm1_enable'), '2')
        self.assertEqual(helper.read_register('ctrl_1') & 1, 0)
        self.assertEqual(helper.read_register('fan_ctrl') & 0x40, 0)

    def test_fans_suspend_cli_observes_pm_release_then_always_hands_back_to_bios(self):
        helper.input.side_effect = self.simulate_owned_fan_suspend
        with patch.object(helper, 'write', wraps=helper.write) as write, \
                patch('sys.argv', ['hardware_test.py', 'fans-suspend']):
            helper.main()
        self.assertEqual([call.args for call in write.call_args_list], [
            (helper.PLATFORM / 'manual_control', 1),
            (self.paths['pwm'] / 'pwm1_enable', 1),
            (self.paths['pwm'] / 'pwm1', 230),
            (self.paths['pwm'] / 'pwm2', 230),
            (helper.PLATFORM / 'manual_control', 0)])
        self.assert_fans_bios()
        self.assertEqual([call.args for call in helper.time.sleep.call_args_list], [(4,), (4,)])
        for elapsed in (0, 4, 8):
            self.assertIn(f'Owned 90% before sleep at {elapsed}s:', self.output.getvalue())
        self.assertIn('ДРУГОМ терминале', helper.input.call_args_list[0].args[0])
        self.assertIn('ОБА вентилятора ускорились', helper.input.call_args_list[1].args[0])
        self.assertIn('ОБА замедлились', helper.input.call_args_list[1].args[0])
        self.assertIn("'manual_control': '1'", self.output.getvalue())
        self.assertIn('journal required separately', self.output.getvalue())
        self.assertIn('Fans after final BIOS handoff:', self.output.getvalue())

    def test_fans_suspend_accepts_firmware_full_bios_and_records_hot_resume_without_abort(self):
        def firmware_resume(question):
            self.simulate_owned_fan_suspend(question, firmware_handoff=True)
            (self.paths['fan'] / 'temp1_input').write_text('81000')
            return 'both slowed'

        helper.input.side_effect = firmware_resume
        helper.fan_suspend_test()
        self.assert_fans_bios()
        self.assertIn('безопасный полный BIOS', self.output.getvalue())
        self.assertIn("'temp1_input': '81000'", self.output.getvalue())

    def test_fans_suspend_no_prompt_is_rejected_before_reads_writes_or_input(self):
        with patch.object(helper, 'read') as read, patch.object(helper, 'write') as write, \
                patch('sys.argv', ['hardware_test.py', '--no-prompt', 'fans-suspend']):
            with self.assertRaisesRegex(RuntimeError, 'requires interactive'):
                helper.main()
        read.assert_not_called()
        write.assert_not_called()
        helper.input.assert_not_called()

    def test_fans_suspend_initial_guards_reject_without_writing(self):
        guards = [
            (self.board_name, 'other-board', 'restricted to LAPAC71G'),
            (helper.PLATFORM / 'manual_control', '1', 'Start from BIOS control'),
            (self.paths['pwm'] / 'pwm1_enable', '1', 'Start from BIOS control'),
            (helper.AC0 / 'online', '0', 'stable AC0 online=1'),
            (self.paths['fan'] / 'temp1_input', '75000', 'cool below'),
            (self.paths['fan'] / 'temp2_input', '75000', 'cool below'),
            (helper.REGS / 'ctrl_1', '0x01', 'raw manual/boost bits cleared'),
            (helper.REGS / 'fan_ctrl', '0x40', 'raw manual/boost bits cleared'),
        ]
        for path, value, expected in guards:
            old = path.read_text()
            with self.subTest(guard=path):
                try:
                    path.write_text(value)
                    with patch.object(helper, 'write') as write:
                        with self.assertRaisesRegex(RuntimeError, expected):
                            helper.fan_suspend_test()
                    write.assert_not_called()
                finally:
                    path.write_text(old)
        (helper.REGS / 'fan_ctrl').unlink()
        with patch.object(helper, 'write') as write:
            with self.assertRaisesRegex(RuntimeError, 'debugregs=1'):
                helper.fan_suspend_test()
        write.assert_not_called()
        helper.input.assert_not_called()

    def test_fans_suspend_unchanged_boost_or_mode_without_sleep_fails_then_releases_bios(self):
        for mode, boost in (('1', '0x40'), ('1', '0x00'), ('2', '0x40')):
            def no_release(question):
                (self.paths['pwm'] / 'pwm1_enable').write_text(mode)
                (helper.REGS / 'fan_ctrl').write_text(boost)
                return 'Enter without PM release'

            with self.subTest(mode=mode, boost=boost):
                helper.input.reset_mock(side_effect=True)
                helper.input.side_effect = no_release
                with self.assertRaisesRegex(RuntimeError, 'suspend-release transition was not observed'):
                    helper.fan_suspend_test()
                self.assert_fans_bios()
                helper.input.assert_called_once()

    def test_fans_suspend_each_setup_write_failure_still_releases_bios(self):
        for number in range(1, 5):
            with self.subTest(write=number), self.fail_write_once(number):
                with self.assertRaisesRegex(OSError, 'injected write failure'):
                    helper.fan_suspend_test()
            self.assert_fans_bios()
        helper.input.assert_not_called()

    def test_fans_suspend_ignored_first_pwm_write_fails_before_prompt_and_releases_bios(self):
        original_write = helper.write

        def ignore_first_pwm(path, value):
            if Path(path) != self.paths['pwm'] / 'pwm1':
                original_write(path, value)

        with patch.object(helper, 'write', side_effect=ignore_first_pwm):
            with self.assertRaisesRegex(RuntimeError, 'PWM readback mismatch.*100/229'):
                helper.fan_suspend_test()
        self.assert_fans_bios()
        helper.input.assert_not_called()

    def test_fans_suspend_ignored_second_pwm_write_fails_before_prompt_and_releases_bios(self):
        original_write = helper.write

        def ignore_second_pwm(path, value):
            if Path(path) != self.paths['pwm'] / 'pwm2':
                original_write(path, value)

        with patch.object(helper, 'write', side_effect=ignore_second_pwm):
            with self.assertRaisesRegex(RuntimeError, 'PWM readback mismatch.*229/100'):
                helper.fan_suspend_test()
        self.assert_fans_bios()
        helper.input.assert_not_called()

    def test_fans_suspend_interrupts_at_either_prompt_still_release_bios(self):
        for interrupt_at in (1, 2):
            count = 0

            def interrupted(question):
                nonlocal count
                count += 1
                if count == interrupt_at:
                    raise KeyboardInterrupt('injected prompt interrupt')
                return self.simulate_owned_fan_suspend(question)

            with self.subTest(prompt=interrupt_at):
                helper.input.side_effect = interrupted
                with self.assertRaisesRegex(KeyboardInterrupt, 'injected prompt interrupt'):
                    helper.fan_suspend_test()
                self.assert_fans_bios()

    def test_fans_suspend_closed_stdin_still_releases_bios(self):
        helper.input.side_effect = EOFError('closed stdin')
        with self.assertRaisesRegex(RuntimeError, 'Interactive fan suspend step was not completed'):
            helper.fan_suspend_test()
        self.assert_fans_bios()

    def test_fans_suspend_ac_loss_or_heat_during_boost_aborts_then_releases_bios(self):
        for path, value, expected in ((helper.AC0 / 'online', '0', 'stable AC0 online=1'),
                                      (self.paths['fan'] / 'temp1_input', '75000', 'cool below')):
            old = path.read_text()

            def change_during_boost(seconds):
                path.write_text(value)

            with self.subTest(changed=path), \
                    patch.object(helper.time, 'sleep', side_effect=change_during_boost):
                try:
                    with self.assertRaisesRegex(RuntimeError, expected):
                        helper.fan_suspend_test()
                    self.assert_fans_bios()
                finally:
                    path.write_text(old)
        helper.input.assert_not_called()

    def test_fans_suspend_ac_loss_after_wake_still_releases_bios(self):
        def disconnect_after_wake(question):
            self.simulate_owned_fan_suspend(question)
            (helper.AC0 / 'online').write_text('0')
            return 'resumed without AC'

        helper.input.side_effect = disconnect_after_wake
        with self.assertRaisesRegex(RuntimeError, 'stable AC0 online=1'):
            helper.fan_suspend_test()
        self.assert_fans_bios()

    def test_fans_suspend_inconsistent_raw_manual_after_wake_fails_then_releases_bios(self):
        def inconsistent_manual(question):
            self.simulate_owned_fan_suspend(question)
            (helper.REGS / 'ctrl_1').write_text('0x00')
            return 'raw mismatch'

        helper.input.side_effect = inconsistent_manual
        with self.assertRaisesRegex(RuntimeError, 'consistent manual control'):
            helper.fan_suspend_test()
        self.assert_fans_bios()

    def test_fans_suspend_cleanup_failure_reports_error_and_still_prints_final_snapshot(self):
        helper.input.side_effect = self.simulate_owned_fan_suspend
        with self.fail_write_once(5):
            with self.assertRaisesRegex(RuntimeError, 'BIOS handoff: injected write failure'):
                helper.fan_suspend_test()
        self.assertIn('Fans after final BIOS handoff:', self.output.getvalue())

    def test_hot_fans_are_rejected_before_writing(self):
        (self.paths["fan"] / "temp1_input").write_text("75000")
        with patch.object(helper, "write") as write:
            with self.assertRaisesRegex(RuntimeError, "cool below"):
                helper.fan_test()
            write.assert_not_called()

    def test_existing_manual_mode_is_rejected_before_writing(self):
        (helper.PLATFORM / "manual_control").write_text("1")
        with patch.object(helper, "write") as write:
            with self.assertRaisesRegex(RuntimeError, "Start from BIOS control"):
                helper.fan_test()
            write.assert_not_called()

    def test_bios_handoff_requires_successful_readback(self):
        (helper.PLATFORM / "manual_control").write_text("1")
        with patch.object(helper, "write"):
            with self.assertRaisesRegex(RuntimeError, "handoff readback failed"):
                helper.bios_control()

    def test_bios_handoff_checks_mode_and_optional_raw_ownership_bits(self):
        cases = [(self.paths['pwm'] / 'pwm1_enable', '1', 'requires PWM mode 2'),
                 (helper.REGS / 'ctrl_1', '0x01', 'left ctrl_1 bits'),
                 (helper.REGS / 'fan_ctrl', '0x40', 'left fan_ctrl bits')]
        for path, value, expected in cases:
            with self.subTest(readback=path.name):
                old = path.read_text()
                path.write_text(value)
                try:
                    with patch.object(helper, 'write'):
                        with self.assertRaisesRegex(RuntimeError, expected):
                            helper.bios_control()
                finally:
                    path.write_text(old)

    def test_bios_handoff_allows_missing_optional_debug_registers(self):
        (helper.REGS / 'ctrl_1').unlink()
        (helper.REGS / 'fan_ctrl').unlink()
        with patch.object(helper, 'write', side_effect=self.original_write):
            helper.bios_control()

    def test_fan_no_prompt_keeps_confirmation_pending(self):
        helper.fan_test(prompt=False)
        helper.input.assert_not_called()
        self.assertIn("pending user confirmation", self.output.getvalue())
        self.assertEqual(helper.read(helper.PLATFORM / "manual_control"), "0")


class Lapac71HHardwareHelperTests(HardwareHelperTests):
    def setUp(self):
        super().setUp()
        self.board_name.write_text('LAPAC71H')


if __name__ == "__main__":
    unittest.main()
