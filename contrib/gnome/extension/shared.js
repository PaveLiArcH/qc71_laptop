// SPDX-License-Identifier: GPL-2.0-only
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export const NAME = 'io.github.PaveLiArcH.Qc71Keyboard1';
export const PATH = '/io/github/PaveLiArcH/Qc71Keyboard1';
const russian = GLib.get_language_names().some(name => name.startsWith('ru'));
export const tr = (en, ru) => russian ? ru : en;
export const title = tr('Keyboard color', 'Цвет клавиатуры');
export const presets = [
    [tr('White', 'Белый'), 'FFFFFF'],
    [tr('Red', 'Красный'), 'FF0000'],
    [tr('Orange', 'Оранжевый'), 'FF8000'],
    [tr('Yellow', 'Жёлтый'), 'FFFF00'],
    [tr('Green', 'Зелёный'), '00FF00'],
    [tr('Cyan', 'Голубой'), '00FFFF'],
    [tr('Blue', 'Синий'), '0000FF'],
    [tr('Purple', 'Фиолетовый'), 'A040FF'],
    [tr('Pink', 'Розовый'), 'FF40A0'],
];

export function parseHex(value) {
    const text = value.trim().replace(/^#/, '');
    if (!/^[0-9a-fA-F]{6}$/.test(text))
        throw new Error(tr('Enter a color as #RRGGBB', 'Введите цвет в формате #RRGGBB'));
    return [0, 2, 4].map(offset => parseInt(text.slice(offset, offset + 2), 16));
}

export function hex(rgb) {
    return '#' + rgb.slice(0, 3).map(value => value.toString(16).padStart(2, '0')).join('').toUpperCase();
}

export function sourceLabel(source) {
    return source === 'ac' ? tr('AC profile', 'Профиль от сети') : tr('Battery profile', 'Профиль от батареи');
}

export function call(method, values = [], cancellable = null) {
    const parameters = method === 'SetColor' ? new GLib.Variant('(uuus)', values) : null;
    return new Promise((resolve, reject) => {
        Gio.DBus.system.call(NAME, PATH, NAME, method, parameters,
            new GLib.VariantType('(uuuus)'), Gio.DBusCallFlags.NONE, 10000,
            cancellable, (connection, result) => {
                try {
                    resolve(connection.call_finish(result).deepUnpack());
                } catch (error) {
                    Gio.DBusError.strip_remote_error(error);
                    reject(error);
                }
            });
    });
}
