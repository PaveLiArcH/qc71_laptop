#!/usr/bin/env python3
"""Read-only AC -> DC -> AC observation of the keyboard notifier cache."""
import json
import time

import hardware_test as hw


def source_is_ac():
    value = hw.read(hw.AC0 / 'online')
    if value not in ('0', '1'):
        raise RuntimeError(f'Invalid AC0/online: {value!r}')
    return value == '1'


def require_source(ac):
    if source_is_ac() != ac:
        raise RuntimeError(f'Expected stable {"AC" if ac else "DC"} power')
    if not ac:
        # The driver uses is_system_supplied(), which also considers USB power.
        hw.require_dc_power_source()


def profiles():
    result = {}
    for source, control, colors in (
            ('ac', hw.KEYBOARD_ENABLE_REGS[0], hw.KEYBOARD_RGB_REGS),
            ('dc', hw.KEYBOARD_ENABLE_REGS[1], hw.KEYBOARD_DC_RGB_REGS)):
        ctrl = hw.read_register(control) & ~0x08  # APPLY is self-clearing.
        rgb = [hw.read_register(name) for name in colors]
        if ctrl & 7 > 4 or any(value > 50 for value in rgb):
            raise RuntimeError(f'Unsupported {source.upper()} profile: {ctrl:#x}, {rgb}')
        result[source] = {'control': ctrl, 'rgb': rgb}
    return result


def cache_color():
    values = list(map(int, hw.read(hw.LED / 'multi_intensity').split()))
    if len(values) != 3 or any(not 0 <= value <= 255 for value in values):
        raise RuntimeError(f'Invalid LED color cache: {values}')
    return values


def check_profiles(saved):
    if profiles() != saved:
        raise RuntimeError('AC/DC raw profiles changed during read-only observation')


def wait_cache(ac, saved):
    """Never read brightness here: its getter can schedule a missing refresh."""
    target = saved['ac' if ac else 'dc']['rgb']
    previous, stable = None, 0
    deadline = time.monotonic() + 2
    for attempt in range(11):
        require_source(ac)
        check_profiles(saved)
        color = cache_color()
        require_source(ac)
        raw = [(value * 50 + 127) // 255 for value in color]
        if raw == target:
            stable = stable + 1 if color == previous else 1
            if stable == 2:
                return color
        else:
            stable = 0
        previous = color
        remaining = deadline - time.monotonic()
        if attempt == 10 or remaining <= 0:
            break
        time.sleep(min(0.2, remaining))
    raise RuntimeError('Notifier cache did not settle within 2s; brightness getter was not used')


def color_name(rgb):
    names = {(50, 50, 50): 'БЕЛЫЙ', (50, 0, 0): 'КРАСНЫЙ',
             (0, 50, 0): 'ЗЕЛЁНЫЙ', (0, 0, 50): 'СИНИЙ'}
    if not any(rgb):
        return 'цвет firmware default (не выводится из RGB 0,0,0)'
    if len(set(rgb)) == 1:
        return 'БЕЛЫЙ'
    return names.get(tuple(rgb), f'RGB raw {rgb}')


def observe_stage(ac, saved):
    source = 'ac' if ac else 'dc'
    color = wait_cache(ac, saved)
    # Only after cache-only settlement may the getter validate configured level.
    brightness = int(hw.read(hw.LED / 'brightness'))
    require_source(ac)
    check_profiles(saved)
    profile = saved[source]
    expected = 0 if profile['control'] & 0x10 else ((profile['control'] & 7) * 255 + 2) // 4
    if brightness != expected:
        raise RuntimeError(f'{source.upper()} configured brightness: expected {expected}, read {brightness}')
    expected_color = ('переливающиеся цвета (rainbow)' if profile['control'] & 0x20
                      else color_name(profile['rgb']))
    expected_light = 'ВЫКЛЮЧЕНА' if not expected else f'{expected_color}, если подсветка активна'
    print(json.dumps({'source': source, 'cache': color, 'raw_profile': profile,
                      'configured_brightness': brightness}, ensure_ascii=False), flush=True)
    observed = input(f'{source.upper()}: ожидается {expected_light}. '
                     'Каковы фактические цвет и яркость? ')
    require_source(ac)
    check_profiles(saved)
    print(json.dumps({'source': source, 'expected': expected_light,
                      'observed': observed}, ensure_ascii=False), flush=True)


def observe_power():
    try:
        if hw.read(hw.DMI_BOARD) != 'LAPAC71G':
            raise RuntimeError('Observation is restricted to LAPAC71G')
        if hw.read(hw.PARAMS / 'keyboard_backlight_protocol') != 'intel-ac-dc-v1':
            raise RuntimeError('Observation requires intel-ac-dc-v1')
        if hw.read(hw.LED / 'multi_index').split() != ['red', 'green', 'blue']:
            raise RuntimeError('Observation requires RGB order red green blue')
        require_source(True)
        saved = profiles()
        cache = cache_color()
        require_source(True)
        print('Initial raw profiles and cache:',
              json.dumps({'profiles': saved, 'cache': cache}, ensure_ascii=False), flush=True)
        if saved['ac']['rgb'] == saved['dc']['rgb']:
            print('INCONCLUSIVE: AC/DC RGB одинаковы; по кэшу нельзя доказать работу notifier.', flush=True)
            return
        print('Только чтение: программа не меняет EC и LED. Fn не нажимайте.', flush=True)
        input('Разбудите встроенную клавиатуру обычной клавишей и нажмите Enter: ')
        observe_stage(True, saved)
        input('Физически отключите адаптер питания (AC -> DC), затем Enter: ')
        observe_stage(False, saved)
        input('Физически подключите адаптер питания (DC -> AC), затем Enter: ')
        observe_stage(True, saved)
        print('PASS: cache AC -> DC -> AC settled before each brightness_get by this script; '
              'оба raw профиля сохранились.', flush=True)
    finally:
        print('Верните и оставьте адаптер подключённым (AC). '
              'Программа не выполняет software-записей для восстановления.', flush=True)


if __name__ == '__main__':
    try:
        observe_power()
    except (OSError, RuntimeError, ValueError, KeyboardInterrupt) as error:
        raise SystemExit(f'Observation stopped: {error}') from error
