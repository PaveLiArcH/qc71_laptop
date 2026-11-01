# SPDX-License-Identifier: GPL-2.0-only
PREFIX ?= /usr
UUID = qc71-keyboard@paveliarch.github.io
EXTENSION_DIR = $(PREFIX)/share/gnome-shell/extensions/$(UUID)

.PHONY: install uninstall pack check

install:
	install -d $(DESTDIR)$(PREFIX)/lib/qc71-keyboard
	install -m644 backend.py service.py $(DESTDIR)$(PREFIX)/lib/qc71-keyboard/
	install -Dm644 qc71-keyboard.service $(DESTDIR)$(PREFIX)/lib/systemd/system/qc71-keyboard.service
	install -Dm644 io.github.PaveLiArcH.Qc71Keyboard1.service $(DESTDIR)$(PREFIX)/share/dbus-1/system-services/io.github.PaveLiArcH.Qc71Keyboard1.service
	install -Dm644 io.github.PaveLiArcH.Qc71Keyboard1.conf $(DESTDIR)$(PREFIX)/share/dbus-1/system.d/io.github.PaveLiArcH.Qc71Keyboard1.conf
	install -Dm644 io.github.PaveLiArcH.qc71-keyboard.policy $(DESTDIR)$(PREFIX)/share/polkit-1/actions/io.github.PaveLiArcH.qc71-keyboard.policy
	install -d $(DESTDIR)$(EXTENSION_DIR)
	install -m644 extension/*.js extension/*.json extension/*.css $(DESTDIR)$(EXTENSION_DIR)/

uninstall:
	rm -f $(DESTDIR)$(PREFIX)/lib/qc71-keyboard/backend.py $(DESTDIR)$(PREFIX)/lib/qc71-keyboard/service.py
	rm -f $(DESTDIR)$(PREFIX)/lib/systemd/system/qc71-keyboard.service
	rm -f $(DESTDIR)$(PREFIX)/share/dbus-1/system-services/io.github.PaveLiArcH.Qc71Keyboard1.service
	rm -f $(DESTDIR)$(PREFIX)/share/dbus-1/system.d/io.github.PaveLiArcH.Qc71Keyboard1.conf
	rm -f $(DESTDIR)$(PREFIX)/share/polkit-1/actions/io.github.PaveLiArcH.qc71-keyboard.policy
	rm -f $(DESTDIR)$(EXTENSION_DIR)/extension.js $(DESTDIR)$(EXTENSION_DIR)/prefs.js $(DESTDIR)$(EXTENSION_DIR)/shared.js $(DESTDIR)$(EXTENSION_DIR)/metadata.json $(DESTDIR)$(EXTENSION_DIR)/stylesheet.css

pack:
	gnome-extensions pack --force --extra-source=shared.js --out-dir=/tmp extension

check:
	python3 ../../tests/test_gnome_keyboard.py
