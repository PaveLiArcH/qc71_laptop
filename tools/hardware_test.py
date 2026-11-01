#!/usr/bin/env python3
"""Bounded LAPAC71G/H checks; snapshot and keyboard-observe only read hardware.

keyboard-observe asks for one physical Fn+F7 press; no command reloads modules.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import time

PLATFORM = Path('/sys/devices/platform/qc71_laptop')
DMI_BOARD = Path('/sys/class/dmi/id/board_name')
PARAMS = Path('/sys/module/qc71_laptop/parameters')
MODULES = Path('/proc/modules')
BATTERY = Path('/sys/class/power_supply/BAT0')
AC0 = Path('/sys/class/power_supply/AC0')
POWER_SUPPLIES = Path('/sys/class/power_supply')
LED = Path('/sys/class/leds/qc71_laptop:rgb:kbd_backlight')
REGS = Path('/sys/kernel/debug/qc71_laptop/regs')
KEYBOARD_RGB_REGS = ('ADDR_RGBKB_LEVEL_R', 'ADDR_RGBKB_LEVEL_G', 'ADDR_RGBKB_LEVEL_B')
KEYBOARD_DC_RGB_REGS = ('ADDR_RGBKBDC_LEVEL_R', 'ADDR_RGBKBDC_LEVEL_G', 'ADDR_RGBKBDC_LEVEL_B')
KEYBOARD_ENABLE_REGS = ('ADDR_INTELAC_AC_SINGLEBL_ENABLE', 'ADDR_INTELAC_DC_SINGLEBL_ENABLE')
KEYBOARD_CTRL_MASK = 0xf2
KEYBOARD_CTRL_STABLE_MASK = KEYBOARD_CTRL_MASK & ~0x10
KEYBOARD_IMMEDIATE_ADDRS = (0x1801, 0x1802, 0x1803, 0x1805, 0x1808)
INTEL_AC_CONTROL = 'ADDR_INTELAC_AC_SINGLEBL_ENABLE'
LAPAC71_BOARDS = ('LAPAC71G', 'LAPAC71H')


def read(path):
    return Path(path).read_text().strip()


def write(path, value):
    Path(path).write_text(str(value) + '\n')


def hwmon(name):
    matches = [p for p in (PLATFORM / 'hwmon').glob('hwmon*')
               if read(p / 'name') == name]
    if len(matches) != 1:
        raise RuntimeError(f'Expected one {name} hwmon, found {len(matches)}')
    return matches[0]


def snapshot():
    paths = [Path('/sys/class/dmi/id') / p for p in
             ('sys_vendor', 'product_name', 'board_vendor', 'board_name', 'bios_version')]
    paths += list(PARAMS.glob('*'))
    paths += [Path('/sys/module/qc71_laptop/srcversion')]
    paths += [PLATFORM / p for p in ('manual_control', 'fan_always_on', 'fan_reduced_duty_cycle')]
    paths += [BATTERY / p for p in ('capacity', 'status', 'charge_control_end_threshold')]
    paths += list((PLATFORM / 'hwmon').glob('hwmon*/*_input'))
    paths += list((PLATFORM / 'hwmon').glob('hwmon*/pwm*'))
    paths += [LED / p for p in ('brightness', 'max_brightness', 'multi_index', 'multi_intensity')]
    paths += [REGS / p for p in
              ('project_id', 'support_1', 'support_2', 'ctrl_1', 'ctrl_2',
               'fan_ctrl', 'lightbar_ctrl', 'trigger_1') +
              KEYBOARD_RGB_REGS + KEYBOARD_DC_RGB_REGS + KEYBOARD_ENABLE_REGS]
    result = {}
    for p in paths:
        try:
            result[str(p)] = read(p)
        except OSError as error:
            result[str(p)] = str(error)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def require_device():
    if read(DMI_BOARD) not in LAPAC71_BOARDS:
        raise RuntimeError('Write tests are restricted to LAPAC71G/H')
    if os.geteuid() != 0:
        raise RuntimeError('Run write tests with sudo in your own terminal')
    if not (PARAMS / 'fan_control').exists():
        raise RuntimeError('Load the newly built module first (see memory-bank/testing.md)')
    conflicts = {'uniwill_wmi', 'tuxedo_keyboard', 'tuxedo_io', 'uniwill_laptop'}
    loaded = {line.split()[0] for line in read(MODULES).splitlines()}
    if conflicts & loaded:
        raise RuntimeError(f'Other EC drivers loaded: {sorted(conflicts & loaded)}')


def battery_test(threshold):
    path = BATTERY / 'charge_control_end_threshold'
    old = read(path)
    if int(old) == threshold:
        raise RuntimeError('Choose a threshold different from the current one')
    try:
        write(path, threshold)
        time.sleep(3)
        print(f'Threshold: expected {threshold}, read {read(path)}; '
              f'capacity={read(BATTERY / "capacity")}, status={read(BATTERY / "status")}')
        if int(read(path)) != threshold:
            raise RuntimeError('EC did not retain the requested threshold')
    finally:
        write(path, old)
        print(f'Restored battery threshold: {read(path)}')


def read_register(name):
    try:
        value = int(read(REGS / name), 0)
    except ValueError as error:
        raise RuntimeError(f'Invalid EC byte in {name}') from error
    if not 0 <= value <= 255:
        raise RuntimeError(f'EC byte outside 0..255 in {name}: {value}')
    return value


def keyboard_readings():
    result = {name: f'0x{read_register(name):02x}' for name in
              KEYBOARD_RGB_REGS + ('ctrl_2', 'trigger_1') + KEYBOARD_ENABLE_REGS}
    result['manual_control'] = read(PLATFORM / 'manual_control')
    return result


def keyboard_immediate_readings():
    result = {}
    try:
        # Unbuffered single-byte reads avoid probing any adjacent EC address.
        with (REGS.parent / 'ec').open('rb', buffering=0) as stream:
            for address in KEYBOARD_IMMEDIATE_ADDRS:
                key = f'immediate_0x{address:04x}'
                try:
                    stream.seek(address)
                    value = stream.read(1)
                    if len(value) != 1:
                        raise RuntimeError('expected one EC byte')
                    result[key] = f'0x{value[0]:02x}'
                except (OSError, RuntimeError) as error:
                    result[key] = f'unavailable: {error}'
    except FileNotFoundError:
        pass
    except OSError as error:
        result['immediate_read_error'] = str(error)
    return result


def keyboard_observe_readings():
    result = keyboard_readings()
    for name in KEYBOARD_DC_RGB_REGS + ('support_2', 'ADDR_INTELAC_TIMTER_ENABLE',
                                      'power_source', 'power_status'):
        try:
            result[name] = f'0x{read_register(name):02x}'
        except FileNotFoundError:
            continue
        except (OSError, RuntimeError) as error:
            result[name] = f'unavailable: {error}'
    result.update(keyboard_immediate_readings())
    return result


def keyboard_observe(prompt=True):
    """Observe one native hotkey transition without any software writes."""
    if read(DMI_BOARD) not in LAPAC71_BOARDS:
        raise RuntimeError('Native keyboard observation is restricted to LAPAC71G/H')
    before = keyboard_observe_readings()
    print('Keyboard before Fn+F7:', json.dumps(before, ensure_ascii=False), flush=True)
    rgb = [int(before[name], 0) for name in KEYBOARD_RGB_REGS]
    white = rgb[0] > 0 and len(set(rgb)) == 1
    expected = 'white if lit' if white else 'not inferred from initial RGB'
    if white:
        print('Исходные RGB одинаковы: при включении ожидается БЕЛЫЙ свет.', flush=True)
    print('Сохраняйте текущее подключение питания во время наблюдения.', flush=True)
    input('Нажмите Fn+F7 ровно один раз, затем Enter: ')
    print('Keyboard immediately after Fn+F7:',
          json.dumps(keyboard_observe_readings(), ensure_ascii=False), flush=True)
    time.sleep(2)
    print('Keyboard 2s after Fn+F7:',
          json.dumps(keyboard_observe_readings(), ensure_ascii=False), flush=True)
    question = ('Подсветка включилась, погасла или изменила яркость? '
                'Опишите фактический свет и цвет')
    if white:
        question += ' (при включении ожидался БЕЛЫЙ)'
    answer = input(question + ': ') if prompt else 'pending user confirmation'
    print(json.dumps({'test': 'keyboard-observe', 'expected': expected,
                      'observed': answer}, ensure_ascii=False))


def require_intel_ac_baseline():
    require_device()
    if read(PLATFORM / 'manual_control') != '0':
        raise RuntimeError('Intel AC brightness test requires manual_control=0')
    if read(AC0 / 'online') != '1':
        raise RuntimeError('Intel AC brightness test requires AC0 online=1')
    if read_register(INTEL_AC_CONTROL) != 0x02:
        raise RuntimeError('Intel AC brightness test requires exact initial AC control 0x02')
    rgb = [read_register(name) for name in KEYBOARD_RGB_REGS]
    if rgb[0] == 0 or len(set(rgb)) != 1:
        raise RuntimeError('Intel AC brightness test requires equal nonzero RGB (white)')


def keyboard_intel_readings():
    result = keyboard_observe_readings()
    result['AC0/online'] = read(AC0 / 'online')
    return result


def keyboard_intel_brightness(prompt=True):
    """Probe Intel AC level 4, then apply the saved configured level 2."""
    require_intel_ac_baseline()
    print('Intel AC before wake:',
          json.dumps(keyboard_intel_readings(), ensure_ascii=False), flush=True)
    print('Сохраняйте текущее подключение питания во время опыта.', flush=True)
    wake_instruction = ('Нажмите обычную клавишу на встроенной клавиатуре для пробуждения, '
                        'затем опишите исходную яркость и нажмите Enter: ')
    if not prompt:
        print(wake_instruction, flush=True)
    baseline = input(wake_instruction) if prompt else 'pending user confirmation'
    # A keypress/input pause can change firmware or the power source.
    require_intel_ac_baseline()
    print('Intel AC before probe:',
          json.dumps(keyboard_intel_readings(), ensure_ascii=False), flush=True)
    print('8 секунд: проверяется Intel level 4; ожидаются увеличение яркости '
          'или максимум и сохранение БЕЛОГО цвета.', flush=True)
    test_error = None
    restoration_errors = []
    try:
        # This is the only probe write; it affects the AC control byte only.
        write(REGS / INTEL_AC_CONTROL, 0x0c)
        for elapsed in (0, 4):
            readings = keyboard_intel_readings()
            print(f'Intel AC readback at {elapsed}s:',
                  json.dumps(readings, ensure_ascii=False), flush=True)
            if readings['AC0/online'] != '1':
                raise RuntimeError('AC0 changed during the Intel brightness test')
            time.sleep(4)
    except (OSError, RuntimeError, KeyboardInterrupt) as error:
        test_error = error
    finally:
        # APPLY is essential: writing 0x02 alone leaves the physical level stale.
        try:
            write(REGS / INTEL_AC_CONTROL, 0x02 | 0x08)
        except OSError as error:
            restoration_errors.append(f'apply configured AC level 2 (0x0a): {error}')
        try:
            restored = read_register(INTEL_AC_CONTROL)
            if restored & ~0x08 != 0x02:
                raise RuntimeError(f'expected stable 0x02, read 0x{restored:02x}')
        except (OSError, RuntimeError) as error:
            restoration_errors.append(f'verify raw AC control: {error}')
        try:
            print('Intel AC after raw restore:',
                  json.dumps(keyboard_intel_readings(), ensure_ascii=False), flush=True)
        except (OSError, RuntimeError) as error:
            restoration_errors.append(f'post-restore readback: {error}')
    if restoration_errors:
        details = ([f'test: {test_error}'] if test_error else []) + restoration_errors
        raise RuntimeError('Intel AC raw restoration failed: ' + '; '.join(details)) from test_error
    if test_error:
        raise test_error
    print('Применён сохранённый configured level 2 (0x02 | APPLY 0x08). '
          'Исходный скрытый Fn-уровень нужно оценить отдельно; '
          'при необходимости верните физическую яркость Fn+F7.', flush=True)
    answer = (input('Стало ли ярче или достигнут максимум за 8 секунд? '
                    'Сохранился ли БЕЛЫЙ цвет? Что произошло с физической яркостью '
                    'после применения сохранённого level 2: ')
              if prompt else 'pending user confirmation')
    print(json.dumps({'test': 'keyboard-intel-brightness', 'expected': 'brighter/max; white',
                      'baseline_observed': baseline, 'observed': answer,
                      'configured_restored': 'level 2; stable 0x02'}, ensure_ascii=False))


def keyboard_led_bank(power_source='ac'):
    if power_source == 'ac':
        return KEYBOARD_ENABLE_REGS[0], KEYBOARD_RGB_REGS, '1'
    if power_source == 'dc':
        return KEYBOARD_ENABLE_REGS[1], KEYBOARD_DC_RGB_REGS, '0'
    raise RuntimeError(f'Unknown keyboard power source: {power_source}')


def require_dc_power_source():
    """Read-only proof of DC, including supplies other than the AC0 adapter."""
    try:
        if read(AC0 / 'online') != '0':
            raise RuntimeError('DC requires AC0 online=0')
        supplies = list(POWER_SUPPLIES.iterdir())
        if not supplies:
            raise RuntimeError('Power-supply inventory is empty; DC is unknown')
        for supply in supplies:
            try:
                scope = read(supply / 'scope')
            except FileNotFoundError:
                scope = None
            # Match the kernel's is_system_supplied(): device-local supplies
            # do not power this laptop. Missing/other scopes are not excluded.
            if scope == 'Device':
                continue
            supply_type = read(supply / 'type')
            if not supply_type:
                raise RuntimeError(f'{supply.name} has no power-supply type; DC is unknown')
            if supply_type == 'Battery':
                continue
            online = read(supply / 'online')
            if online != '0':
                raise RuntimeError(f'DC requires every non-battery supply offline: '
                                   f'{supply.name} online={online!r}')
    except OSError as error:
        raise RuntimeError(f'Cannot verify all power supplies for DC: {error}') from error


def require_keyboard_led_source(power_source='ac'):
    _control, _rgb, online = keyboard_led_bank(power_source)
    require_device()
    try:
        protocol = read(PARAMS / 'keyboard_backlight_protocol')
    except FileNotFoundError as error:
        raise RuntimeError('Reload the module with the Intel keyboard protocol marker') from error
    if protocol != 'intel-ac-dc-v1' or read(LED / 'max_brightness') != '255':
        raise RuntimeError('keyboard-led requires intel-ac-dc-v1 and max_brightness=255')
    if read(AC0 / 'online') != online:
        raise RuntimeError(f'keyboard-led requires AC0 online={online}; '
                           f'{power_source.upper()} restoration is pending')
    if power_source == 'dc':
        try:
            require_dc_power_source()
        except RuntimeError as error:
            raise RuntimeError(f'{error}; DC restoration is pending') from error
    if read(PLATFORM / 'manual_control') != '0':
        raise RuntimeError('keyboard-led requires manual_control=0')


def quantized_keyboard_brightness(value):
    if not 0 <= value <= 255:
        raise RuntimeError(f'LED brightness outside 0..255: {value}')
    level = max(1, (value * 4 + 127) // 255) if value else 0
    return (level * 255 + 2) // 4


def keyboard_led_readings(power_source='ac'):
    result = keyboard_intel_readings()
    result['selected_profile'] = power_source
    result['LED/brightness'] = read(LED / 'brightness')
    result['LED/multi_intensity'] = read(LED / 'multi_intensity')
    return result


def keyboard_unrelated_settings(power_source='ac'):
    # These settings belong to the inactive bank or to other device functions.
    control, rgb, _online = keyboard_led_bank('dc' if power_source == 'ac' else 'ac')
    masks = {name: 0xff for name in rgb}
    masks.update({control: 0xf7,
                  'ctrl_1': 0x01, 'fan_ctrl': 0xff, 'ctrl_2': 0xef})
    return {name: read_register(name) & mask for name, mask in masks.items()}


def wait_keyboard_led_target(color, brightness, power_source='ac'):
    _control, rgb_registers, _online = keyboard_led_bank(power_source)
    expected_color = list(map(int, color.split()))
    expected_brightness = quantized_keyboard_brightness(brightness)
    expected_raw = [(value * 50 + 127) // 255 for value in expected_color]
    stable = 0
    actual = {}
    deadline = time.monotonic() + 2
    # The LED core can queue the blocking setter after the sysfs write returns.
    for attempt in range(11):
        require_keyboard_led_source(power_source)
        actual = {'brightness': int(read(LED / 'brightness')),
                  'color': list(map(int, read(LED / 'multi_intensity').split())),
                  'raw_rgb': [read_register(name) for name in rgb_registers]}
        actual_color_raw = [(value * 50 + 127) // 255 for value in actual['color']]
        if (actual['brightness'] == expected_brightness and
                actual_color_raw == expected_raw and actual['raw_rgb'] == expected_raw):
            stable += 1
            if stable == 2:
                require_keyboard_led_source(power_source)
                return
        else:
            stable = 0
        remaining = deadline - time.monotonic()
        if attempt == 10 or remaining <= 0:
            break
        time.sleep(min(0.2, remaining))
    raise RuntimeError(f'LED target did not settle within 2s: {actual}')


def keyboard_led_test(prompt=True, power_source='ac'):
    """Exercise only the standard LED API, using the verified Intel backend."""
    require_keyboard_led_source(power_source)
    control, rgb_registers, _online = keyboard_led_bank(power_source)
    test_color = '255 0 0' if power_source == 'ac' else '0 0 255'
    english_color = 'RED' if power_source == 'ac' else 'BLUE'
    russian_color = 'КРАСНЫЙ' if power_source == 'ac' else 'СИНИЙ'
    if read(LED / 'multi_index').split() != ['red', 'green', 'blue']:
        raise RuntimeError('keyboard-led requires RGB order red green blue')
    old_color = read(LED / 'multi_intensity')
    color_values = list(map(int, old_color.split()))
    if len(color_values) != 3 or any(not 0 <= value <= 255 for value in color_values):
        raise RuntimeError('Invalid baseline RGB intensities')
    if not any((value * 50 + 127) // 255 for value in color_values):
        raise RuntimeError('Black/default baseline color cannot be restored by this test')
    if not any(read_register(name) for name in rgb_registers):
        raise RuntimeError('Default raw RGB 0,0,0 cannot be restored by this test')
    if read_register(control) & 0x20:
        raise RuntimeError('A rainbow baseline cannot be restored through the static LED API')
    old_brightness = int(read(LED / 'brightness'))
    quantized_keyboard_brightness(old_brightness)
    if not old_brightness:
        raise RuntimeError('An OFF baseline cannot be restored completely by this bounded LED test')
    wait_keyboard_led_target(old_color, old_brightness, power_source)
    print('LED API baseline:', json.dumps(keyboard_led_readings(power_source), ensure_ascii=False), flush=True)
    power_instruction = ('Сохраняйте подключение адаптера' if power_source == 'ac' else
                         'Сохраняйте питание от батареи и оставьте адаптер отключённым')
    print(power_instruction + '; во время этапов Fn не нажимайте.', flush=True)
    wake_instruction = ('Разбудите встроенную клавиатуру обычной клавишей; '
                        'опишите исходные цвет и физическую яркость, затем Enter: ')
    if not prompt:
        print(wake_instruction, flush=True)
    baseline = input(wake_instruction) if prompt else 'pending user confirmation'
    require_keyboard_led_source(power_source)
    wait_keyboard_led_target(old_color, old_brightness, power_source)
    unrelated = keyboard_unrelated_settings(power_source)
    print('LED API before:', json.dumps(keyboard_led_readings(power_source), ensure_ascii=False), flush=True)
    test_error = None
    restoration_errors = []
    try:
        require_keyboard_led_source(power_source)
        write(LED / 'multi_intensity', test_color)
        for label, brightness, duration in ((f'bright {english_color}', 255, 6),
                                           (f'DIMMER {english_color}', 64, 6), ('OFF', 0, 4)):
            require_keyboard_led_source(power_source)
            expected = {f'bright {english_color}': f'яркий {russian_color}',
                        f'DIMMER {english_color}': f'тусклее {russian_color}',
                        'OFF': 'подсветка ВЫКЛЮЧЕНА'}[label]
            print(f'{duration} секунд: ожидается {expected}.', flush=True)
            write(LED / 'brightness', brightness)
            wait_keyboard_led_target(test_color, brightness, power_source)
            for elapsed in (0, duration // 2, duration):
                require_keyboard_led_source(power_source)
                if keyboard_unrelated_settings(power_source) != unrelated:
                    raise RuntimeError('Inactive profile/manual/fan/CTRL2 settings changed during LED test')
                print(f'LED API {label} at {elapsed}s:',
                      json.dumps(keyboard_led_readings(power_source), ensure_ascii=False), flush=True)
                if elapsed != duration:
                    time.sleep(duration // 2)
    except (OSError, RuntimeError, KeyboardInterrupt) as error:
        test_error = error
    finally:
        # Never apply saved settings through an API that has switched profiles.
        for label, path, value in (('LED off', LED / 'brightness', 0),
                                   ('color', LED / 'multi_intensity', old_color),
                                   ('configured brightness', LED / 'brightness', old_brightness)):
            try:
                require_keyboard_led_source(power_source)
                write(path, value)
                restore_color = old_color if label != 'LED off' else read(LED / 'multi_intensity')
                restore_brightness = old_brightness if label == 'configured brightness' else 0
                wait_keyboard_led_target(restore_color, restore_brightness, power_source)
            except (OSError, RuntimeError) as error:
                restoration_errors.append(f'restore {label}: {error}')
        try:
            wait_keyboard_led_target(old_color, old_brightness, power_source)
            if keyboard_unrelated_settings(power_source) != unrelated:
                raise RuntimeError('Inactive profile/manual/fan/CTRL2 settings changed')
        except (OSError, RuntimeError) as error:
            restoration_errors.append(f'verify configured restoration: {error}')
        try:
            print('LED API after configured restore:',
                  json.dumps(keyboard_led_readings(power_source), ensure_ascii=False), flush=True)
        except (OSError, RuntimeError) as error:
            restoration_errors.append(f'post-restore readback: {error}')
    if restoration_errors:
        details = ([f'test: {test_error}'] if test_error else []) + restoration_errors
        raise RuntimeError('LED configured restoration failed: ' + '; '.join(details)) from test_error
    if test_error:
        raise test_error
    print('Проверены исходные configured color/brightness. Скрытый native Fn-уровень '
          'оцените визуально; при необходимости верните его Fn+F7.', flush=True)
    answer = (input(f'Подтвердите яркий {russian_color} → тусклее {russian_color} → ВЫКЛЮЧЕН. '
                    'Какие цвет и физическая яркость остались после configured restore: ')
              if prompt else 'pending user confirmation')
    print(json.dumps({'test': 'keyboard-led', 'baseline_observed': baseline,
                      'power_source': power_source,
                      'expected': f'bright {english_color} -> DIMMER {english_color} -> OFF',
                      'observed': answer},
                     ensure_ascii=False))


def restore_keyboard(old_color, old_brightness, old_raw):
    """Restore both the LED cache and raw EC bytes; collect every failure."""
    errors = []

    def attempt(label, operation):
        try:
            operation()
        except (OSError, RuntimeError) as error:
            errors.append(f'{label}: {error}')

    # Restore the API cache first. At brightness zero, the driver deliberately
    # skips raw RGB writes, so that alone cannot restore the EC color bytes.
    attempt('LED off', lambda: write(LED / 'brightness', 0))
    attempt('LED color cache', lambda: write(LED / 'multi_intensity', old_color))
    attempt('LED brightness cache', lambda: write(LED / 'brightness', old_brightness))
    for name in KEYBOARD_RGB_REGS:
        attempt(f'restore {name}', lambda name=name: write(REGS / name, old_raw[name]))
    # This is a command byte: do not replay unrelated trigger bits.
    attempt('apply restored RGB', lambda: write(REGS / 'trigger_1', 0x20))

    def restore_ctrl():
        current = read_register('ctrl_2')
        value = ((current & ~KEYBOARD_CTRL_MASK) |
                 (old_raw['ctrl_2'] & KEYBOARD_CTRL_MASK))
        write(REGS / 'ctrl_2', value)

    attempt('restore ctrl_2 keyboard bits', restore_ctrl)

    def verify_register(name, mask=0xff):
        current = read_register(name)
        if current & mask != old_raw[name] & mask:
            raise RuntimeError(f'expected 0x{old_raw[name] & mask:02x}, '
                               f'read 0x{current & mask:02x} (mask 0x{mask:02x})')

    for name in KEYBOARD_RGB_REGS:
        attempt(f'verify {name}', lambda name=name: verify_register(name))
    # Firmware can clear the apply-level command bit at any time.
    attempt('verify ctrl_2 keyboard bits',
            lambda: verify_register('ctrl_2', KEYBOARD_CTRL_STABLE_MASK))

    def verify_api(name, expected):
        current = read(LED / name)
        if current.split() != expected.split():
            raise RuntimeError(f'expected {expected!r}, read {current!r}')

    attempt('verify LED color cache', lambda: verify_api('multi_intensity', old_color))
    attempt('verify LED brightness', lambda: verify_api('brightness', old_brightness))
    return errors


def keyboard_test(color, prompt=True):
    protocol_path = PARAMS / 'keyboard_backlight_protocol'
    if protocol_path.exists() and read(protocol_path) == 'intel-ac-dc-v1':
        raise RuntimeError('Legacy keyboard test is disabled for Intel; use keyboard-led')
    if not LED.exists():
        raise RuntimeError('Keyboard LED not registered; send snapshot and module log')
    old_color, old_brightness = read(LED / 'multi_intensity'), read(LED / 'brightness')
    if not any(map(int, old_color.split())) and int(old_brightness):
        raise RuntimeError('Firmware default color is active (RGB=0,0,0); '
                           'cannot restore it through the LED API. Choose an explicit color first.')
    # debugregs=1 is mandatory: raw backup/restore has no LED-API fallback.
    old_raw = {name: read_register(name) for name in KEYBOARD_RGB_REGS + ('ctrl_2',)}
    if not any(old_raw[name] for name in KEYBOARD_RGB_REGS):
        raise RuntimeError('Firmware default raw RGB=0,0,0 cannot be restored '
                           'exactly after color application; choose an explicit color first.')
    before = keyboard_readings()
    if read_register('trigger_1') & 0x80:
        raise RuntimeError('Rainbow mode is active; a fixed-color test would be ambiguous')
    colors = {'red': ('255 0 0', 'КРАСНЫЙ'), 'green': ('0 255 0', 'ЗЕЛЁНЫЙ'),
              'blue': ('0 0 255', 'СИНИЙ')}
    values, expected = colors[color]
    test_error = None
    try:
        print('Keyboard before:', json.dumps(before, ensure_ascii=False), flush=True)
        print(f'Ожидается {expected} цвет клавиатуры в течение 8 секунд; '
              'яркость зависит от текущего состояния BIOS и проверяется отдельно.', flush=True)
        write(LED / 'multi_intensity', values)
        write(LED / 'brightness', 255)
        for elapsed in (0, 4):
            print(f'Keyboard readback at {elapsed}s:',
                  json.dumps(keyboard_readings(), ensure_ascii=False), flush=True)
            time.sleep(4)
    except (OSError, RuntimeError, KeyboardInterrupt) as error:
        test_error = error
    finally:
        restoration_errors = restore_keyboard(old_color, old_brightness, old_raw)
    try:
        print('Keyboard after restore:',
              json.dumps(keyboard_readings(), ensure_ascii=False), flush=True)
    except (OSError, RuntimeError) as error:
        restoration_errors.append(f'post-restore readback: {error}')
    if restoration_errors:
        details = ([f'test: {test_error}'] if test_error else []) + restoration_errors
        raise RuntimeError('Keyboard restoration failed: ' + '; '.join(details)) from test_error
    if test_error:
        raise test_error
    print('Исходные RGB, keyboard-биты ctrl_2 и состояние LED API восстановлены.')
    answer = (input(f'Клавиатура была {expected}? Опишите цвет/эффект, если результат отличался: ')
              if prompt else 'pending user confirmation')
    print(json.dumps({'test': 'keyboard', 'expected': color, 'observed': answer}, ensure_ascii=False))


def fan_readings():
    p = hwmon('qc71_laptop.hwmon.fan')
    result = {f: read(p / f) for f in ('fan1_input', 'fan2_input', 'temp1_input', 'temp2_input')}
    pwm = hwmon('qc71_laptop.hwmon.pwm')
    result.update({f: read(pwm / f) for f in ('pwm1_enable', 'pwm1', 'pwm2')})
    result['manual_control'] = read(PLATFORM / 'manual_control')
    for name in ('ctrl_1', 'fan_ctrl'):
        try:
            result[name] = f'0x{read_register(name):02x}'
        except FileNotFoundError:
            continue
    return result


def bios_control():
    # manual_control=0 uses the driver fan lock and clears boost before handoff.
    write(PLATFORM / 'manual_control', 0)
    value = read(PLATFORM / 'manual_control')
    print(f'manual_control={value} (expected 0)')
    if value != '0':
        raise RuntimeError('BIOS handoff readback failed')
    mode = read(hwmon('qc71_laptop.hwmon.pwm') / 'pwm1_enable')
    if mode != '2':
        raise RuntimeError(f'BIOS handoff requires PWM mode 2, read {mode}')
    for name, mask in (('ctrl_1', 0x01), ('fan_ctrl', 0x40)):
        try:
            if read_register(name) & mask:
                raise RuntimeError(f'BIOS handoff left {name} bits 0x{mask:02x} set')
        except FileNotFoundError:
            continue


def fan_test(prompt=True):
    pwm = hwmon('qc71_laptop.hwmon.pwm')
    mode = pwm / 'pwm1_enable'
    if read(PLATFORM / 'manual_control') != '0' or read(mode) != '2':
        raise RuntimeError('Start from BIOS control: run the bios subcommand first')
    before = fan_readings()
    if max(int(before['temp1_input']), int(before['temp2_input'])) >= 75000:
        raise RuntimeError('Let CPU/GPU cool below 75 C before this idle test')
    print('Before:', before, flush=True)
    try:
        write(PLATFORM / 'manual_control', 1)
        print('8 секунд: ожидается ускорение ОБОИХ вентиляторов до полной скорости.', flush=True)
        write(mode, 0)
        for elapsed in (0, 4, 8):
            print(f'Full at {elapsed}s:', fan_readings(), flush=True)
            if elapsed != 8:
                time.sleep(4)
        write(mode, 1)
        write(pwm / 'pwm1', 230)
        write(pwm / 'pwm2', 230)
        print('8 секунд: ожидается небольшое замедление ОБОИХ вентиляторов до ~90%.', flush=True)
        for elapsed in (0, 4, 8):
            print(f'90% at {elapsed}s:', fan_readings(), flush=True)
            if elapsed != 8:
                time.sleep(4)
    finally:
        bios_control()
        print('Управление возвращено BIOS; при небольшой нагрузке ожидается замедление.', flush=True)
    for elapsed in (0, 4, 8):
        print(f'BIOS after {elapsed}s:', fan_readings(), flush=True)
        if elapsed != 8:
            time.sleep(4)
    answer = (input('Подтвердите: оба ускорились на full, слегка замедлились на 90%, затем вернулись к обычной работе? ')
              if prompt else 'pending user confirmation')
    print(json.dumps({'test': 'fans', 'observed': answer}, ensure_ascii=False))


def fan_suspend_test(prompt=True):
    """Observe release of owned fan boost across a user-performed suspend."""
    if not prompt:
        raise RuntimeError('fans-suspend requires interactive sleep and physical confirmation; '
                           '--no-prompt is not supported')
    require_device()
    pwm = hwmon('qc71_laptop.hwmon.pwm')
    before = fan_readings()
    if before['manual_control'] != '0' or before['pwm1_enable'] != '2':
        raise RuntimeError('Start from BIOS control: run the bios subcommand first')
    if not {'ctrl_1', 'fan_ctrl'} <= before.keys():
        raise RuntimeError('fans-suspend requires debugregs=1 and readable ctrl_1/fan_ctrl')
    if int(before['ctrl_1'], 0) & 1 or int(before['fan_ctrl'], 0) & 0x40:
        raise RuntimeError('BIOS baseline must have raw manual/boost bits cleared')

    def require_idle_ac(readings, check_temperature=True):
        if read(AC0 / 'online') != '1':
            raise RuntimeError('fans-suspend requires stable AC0 online=1')
        if (check_temperature and
                max(int(readings['temp1_input']), int(readings['temp2_input'])) >= 75000):
            raise RuntimeError('Let CPU/GPU cool below 75 C before this idle test')

    require_idle_ac(before)
    print('Before owned fan suspend:', before, flush=True)
    print('Сохраняйте адаптер подключённым. 8 секунд: ожидается ускорение '
          'ОБОИХ вентиляторов до ~90%.', flush=True)
    test_error = None
    restoration_errors = []
    observed = None
    try:
        write(PLATFORM / 'manual_control', 1)
        write(pwm / 'pwm1_enable', 1)
        write(pwm / 'pwm1', 230)
        write(pwm / 'pwm2', 230)
        for elapsed in (0, 4, 8):
            current = fan_readings()
            require_idle_ac(current)
            if not {'ctrl_1', 'fan_ctrl'} <= current.keys():
                raise RuntimeError('Required fan ownership registers disappeared')
            if (current['manual_control'] != '1' or current['pwm1_enable'] != '1' or
                    not int(current['ctrl_1'], 0) & 1 or
                    not int(current['fan_ctrl'], 0) & 0x40):
                raise RuntimeError('Owned ~90% fan control did not take effect')
            if any(abs(int(current[name]) - 230) > 1 for name in ('pwm1', 'pwm2')):
                raise RuntimeError('Owned ~90% PWM readback mismatch: expected 230 +/-1 '
                                   f'for both fans, read {current["pwm1"]}/{current["pwm2"]}')
            print(f'Owned 90% before sleep at {elapsed}s:', current, flush=True)
            if elapsed != 8:
                time.sleep(4)
        input('Усыпите ноутбук через меню рабочего стола или systemctl suspend '
              'в ДРУГОМ терминале. Пробудите его, затем нажмите Enter здесь: ')
        resumed = fan_readings()
        print('Fan state after user-reported wake:', resumed, flush=True)
        require_idle_ac(resumed, check_temperature=False)
        if not {'ctrl_1', 'fan_ctrl'} <= resumed.keys():
            raise RuntimeError('Required fan ownership registers disappeared after wake')
        manual = resumed['manual_control']
        if (resumed['pwm1_enable'] != '2' or int(resumed['fan_ctrl'], 0) & 0x40 or
                manual not in ('0', '1') or int(resumed['ctrl_1'], 0) & 1 != int(manual)):
            raise RuntimeError('Expected PWM mode 2 and raw boost=0 after wake, with '
                               'consistent manual control; unchanged mode 1/boost means '
                               'the suspend-release transition was not observed')
        if manual == '1':
            print('Ожидаемое состояние: manual_control=1, mode=2, boost=0; '
                  'ручной PWM после пробуждения не активирован.', flush=True)
        else:
            print('manual_control=0, mode=2, boost=0: безопасный полный BIOS. '
                  'Драйвер сохраняет global bit при suspend; firmware мог также снять его.',
                  flush=True)
        print('Этот readback не доказывает факт сна; подтвердите вход/выход по journal отдельно.',
              flush=True)
        observed = input('До сна ОБА вентилятора ускорились на ~90%? После пробуждения '
                         'ОБА замедлились относительно ~90% при небольшой нагрузке? '
                         'Опишите фактическое поведение обоих: ')
    except (OSError, RuntimeError, KeyboardInterrupt, EOFError) as error:
        test_error = error
    finally:
        try:
            bios_control()
        except (OSError, RuntimeError) as error:
            restoration_errors.append(f'BIOS handoff: {error}')
        try:
            print('Fans after final BIOS handoff:', fan_readings(), flush=True)
        except (OSError, RuntimeError) as error:
            restoration_errors.append(f'final fan readback: {error}')
    if restoration_errors:
        details = ([f'test: {test_error}'] if test_error else []) + restoration_errors
        raise RuntimeError('Fan suspend BIOS restoration failed: ' + '; '.join(details)) from test_error
    if test_error:
        if isinstance(test_error, EOFError):
            raise RuntimeError('Interactive fan suspend step was not completed') from test_error
        raise test_error
    print(json.dumps({'test': 'fans-suspend', 'observed': observed,
                      'sleep_evidence': 'journal required separately'}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-prompt', action='store_true',
                        help='skip input in write tests except fans-suspend; '
                             'keyboard-observe still waits for Fn+F7')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('snapshot')
    sub.add_parser('keyboard-observe',
                   help='read state around one physical Fn+F7 press; no software writes')
    sub.add_parser('keyboard-intel-brightness',
                   help='probe Intel AC level 4 for 8s, then apply configured AC level 2')
    keyboard_led = sub.add_parser('keyboard-led',
                                  help='test standard LED API: AC red or DC blue, dim, OFF')
    keyboard_led.add_argument('--power-source', choices=('ac', 'dc'), default='ac',
                              help='profile to test; keep adapter state unchanged (default: ac)')
    battery = sub.add_parser('battery')
    battery.add_argument('--threshold', type=int, choices=range(50, 101), default=90)
    keyboard = sub.add_parser('keyboard')
    keyboard.add_argument('--color', choices=('red', 'green', 'blue'), default='red')
    sub.add_parser('fans')
    sub.add_parser('fans-suspend',
                   help='interactive owned ~90%% fan control, user suspend, then BIOS handoff')
    sub.add_parser('bios')
    args = parser.parse_args()
    if args.command == 'snapshot':
        snapshot()
        return
    if args.command == 'keyboard-observe':
        keyboard_observe(not args.no_prompt)
        return
    if args.command == 'keyboard-intel-brightness':
        keyboard_intel_brightness(not args.no_prompt)
        return
    if args.command == 'keyboard-led':
        keyboard_led_test(not args.no_prompt, args.power_source)
        return
    if args.command == 'fans-suspend':
        fan_suspend_test(not args.no_prompt)
        return
    require_device()
    if args.command == 'battery':
        battery_test(args.threshold)
    elif args.command == 'keyboard':
        keyboard_test(args.color, not args.no_prompt)
    elif args.command == 'fans':
        fan_test(not args.no_prompt)
    else:
        bios_control()


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'signal {signum}')

    # Restore state on terminal closure and ordinary process termination too.
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        main()
    except (OSError, RuntimeError, KeyboardInterrupt) as error:
        raise SystemExit(f'Test stopped: {error}') from error
