// SPDX-License-Identifier: GPL-2.0-only
import Adw from 'gi://Adw';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import {call, hex, parseHex, sourceLabel, title, tr} from './shared.js';

export default class KeyboardColorPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        window.set_default_size(540, 400);
        const cancellable = new Gio.Cancellable();
        let alive = true;
        let state = null;
        let busy = false;
        const page = new Adw.PreferencesPage({title, icon_name: 'keyboard-brightness-symbolic'});
        const group = new Adw.PreferencesGroup({
            title,
            description: tr('The active AC or battery profile is changed. Brightness is controlled in GNOME Quick Settings.',
                'Изменяется активный профиль питания. Яркость регулируется в быстрых настройках GNOME.'),
        });
        page.add(group);
        window.add(page);

        const status = new Adw.ActionRow({title: tr('Current profile', 'Текущий профиль'), subtitle: '…'});
        const refresh = new Gtk.Button({icon_name: 'view-refresh-symbolic', valign: Gtk.Align.CENTER,
            tooltip_text: tr('Refresh profile', 'Обновить профиль')});
        status.add_suffix(refresh);
        group.add(status);
        const entry = new Adw.EntryRow({title: tr('Color · #RRGGBB', 'Цвет · #RRGGBB')});
        group.add(entry);
        const chooser = new Gtk.ColorDialogButton({
            dialog: new Gtk.ColorDialog({title, with_alpha: false}), valign: Gtk.Align.CENTER,
        });
        const chooseRow = new Adw.ActionRow({title: tr('Choose from palette', 'Выбрать на палитре')});
        chooseRow.add_suffix(chooser);
        group.add(chooseRow);
        const apply = new Gtk.Button({label: tr('Apply color', 'Применить цвет'),
            css_classes: ['suggested-action'], halign: Gtk.Align.END, margin_top: 18});
        group.add(apply);
        const info = new Adw.PreferencesGroup({description: tr(
            'Changes apply only when you press Apply. Black is reserved for off: use the brightness control. If you change the power source, refresh the profile first. Fn keys and the idle timer may hide the configured light.',
            'Цвет применяется по кнопке. Для выключения используйте яркость. После подключения или отключения адаптера обновите профиль. Fn и таймер простоя могут временно скрывать подсветку.')});
        page.add(info);

        function sensitive() {
            apply.sensitive = !busy && state !== null;
            entry.sensitive = chooser.sensitive = !busy;
            refresh.sensitive = !busy;
        }

        function showError(error) {
            const dialog = new Adw.AlertDialog({heading: tr('Could not change color', 'Не удалось изменить цвет'),
                body: error.message});
            dialog.add_response('close', tr('Close', 'Закрыть'));
            dialog.present(window);
        }

        function render(current) {
            state = current;
            status.subtitle = sourceLabel(state[4]) + ' · ' + hex(state);
            entry.text = hex(state);
            const rgba = new Gdk.RGBA();
            rgba.parse(hex(state));
            chooser.rgba = rgba;
        }

        async function load() {
            if (busy)
                return;
            busy = true;
            sensitive();
            try {
                const current = await call('GetState', [], cancellable);
                if (alive)
                    render(current);
            } catch (error) {
                if (alive) {
                    state = null;
                    status.subtitle = error.message;
                }
            } finally {
                busy = false;
                if (alive)
                    sensitive();
            }
        }

        chooser.connect('notify::rgba', () => {
            const color = chooser.rgba;
            entry.text = hex([color.red, color.green, color.blue].map(value => Math.round(value * 255)));
        });
        refresh.connect('clicked', load);
        apply.connect('clicked', async () => {
            if (busy || !state)
                return;
            busy = true;
            sensitive();
            try {
                const current = await call('SetColor', [...parseHex(entry.text), state[4]], cancellable);
                if (alive)
                    render(current);
            } catch (error) {
                if (alive)
                    showError(error);
            } finally {
                busy = false;
                if (alive)
                    load();
            }
        });
        window.connect('close-request', () => {
            alive = false;
            cancellable.cancel();
            return false;
        });
        load();
    }
}
