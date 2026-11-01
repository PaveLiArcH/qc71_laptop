// SPDX-License-Identifier: GPL-2.0-only
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as QuickSettings from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {call, hex, parseHex, presets, sourceLabel, title, tr} from './shared.js';

const ColorToggle = GObject.registerClass(
class ColorToggle extends QuickSettings.QuickMenuToggle {
    constructor(extension) {
        super({title, iconName: 'keyboard-brightness-symbolic', toggleMode: false});
        this._cancellable = new Gio.Cancellable();
        this._alive = true;
        this._state = null;
        this._busy = false;
        this.menu.setHeader('keyboard-brightness-symbolic', title);
        this._status = new PopupMenu.PopupMenuItem(tr('Loading…', 'Загрузка…'), {reactive: false});
        this.menu.addMenuItem(this._status);
        this._colors = [];
        for (const [name, color] of presets) {
            const item = new PopupMenu.PopupMenuItem(name);
            const swatch = new St.Widget({
                style_class: 'qc71-color-swatch',
                style: `background-color: #${color};`,
            });
            item.insert_child_at_index(swatch, 0);
            item.connect('activate', () => this._apply(parseHex(color)));
            this.menu.addMenuItem(item);
            this._colors.push([item, color]);
        }
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const settings = this.menu.addAction(tr('Custom color…', 'Другой цвет…'), () => {
            Main.panel.statusArea.quickSettings.menu.close();
            extension.openPreferences();
        });
        this.menu._settingsActions[extension.uuid] = settings;
        settings.visible = Main.sessionMode.allowSettings;
        this.connect('clicked', () => this.menu.open());
        this.menu.connect('open-state-changed', (_menu, open) => {
            if (open)
                this._refresh();
        });
        this._refresh();
    }

    _render(state) {
        this._state = state;
        this.subtitle = hex(state);
        this.checked = state[3] > 0;
        this._status.label.text = sourceLabel(state[4]) + (state[3] === 0 ?
            tr(' · light is off', ' · подсветка выключена') : '');
        for (const [item, color] of this._colors)
            item.setOrnament(color === hex(state).slice(1) ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE);
    }

    _sensitive(value) {
        for (const [item] of this._colors)
            item.setSensitive(value);
    }

    async _refresh() {
        if (this._busy)
            return;
        this._busy = true;
        this._sensitive(false);
        try {
            const state = await call('GetState', [], this._cancellable);
            if (this._alive)
                this._render(state);
        } catch (error) {
            if (this._alive) {
                this._state = null;
                this.subtitle = tr('Unavailable', 'Недоступно');
                this._status.label.text = tr('Open settings for details', 'Подробности в настройках');
            }
        } finally {
            this._busy = false;
            if (this._alive)
                this._sensitive(this._state !== null);
        }
    }

    async _apply(rgb) {
        if (this._busy || !this._state)
            return;
        this._busy = true;
        this._sensitive(false);
        try {
            const state = await call('SetColor', [...rgb, this._state[4]], this._cancellable);
            if (this._alive)
                this._render(state);
        } catch (error) {
            if (this._alive)
                Main.notifyError(title, error.message);
        } finally {
            this._busy = false;
            if (this._alive)
                this._refresh();
        }
    }

    destroy() {
        this._alive = false;
        this._cancellable.cancel();
        super.destroy();
    }
});

const ColorIndicator = GObject.registerClass(
class ColorIndicator extends QuickSettings.SystemIndicator {
    constructor(extension) {
        super();
        this.quickSettingsItems.push(new ColorToggle(extension));
    }

    destroy() {
        this.quickSettingsItems.forEach(item => item.destroy());
        super.destroy();
    }
});

export default class KeyboardColorExtension extends Extension {
    enable() {
        this._indicator = new ColorIndicator(this);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
