#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run under dbus-run-session. Uses a private bus, fake polkit and temp sysfs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'contrib' / 'gnome'
sys.path.insert(0, str(ROOT))
from backend import Keyboard
import service


def server(root, allowed):
    root = Path(root)
    service.Keyboard = lambda: Keyboard(root / 'led', root / 'protocol', root / 'supplies')
    connection = service.Gio.bus_get_sync(service.Gio.BusType.SYSTEM, None)
    xml = '''<node><interface name="org.freedesktop.PolicyKit1.Authority">
    <method name="CheckAuthorization">
      <arg type="(sa{sv})" direction="in"/><arg type="s" direction="in"/>
      <arg type="a{ss}" direction="in"/><arg type="u" direction="in"/>
      <arg type="s" direction="in"/><arg type="(bba{ss})" direction="out"/>
    </method></interface></node>'''

    def check(conn, sender, path, interface, method, parameters, invocation):
        (root / 'auth.json').write_text(json.dumps(parameters.unpack()))
        invocation.return_value(service.GLib.Variant('((bba{ss}))', ((allowed, False, {}),)))

    connection.register_object('/org/freedesktop/PolicyKit1/Authority',
                               service.Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0], check, None, None)
    owner = service.Gio.bus_own_name_on_connection(
        connection, 'org.freedesktop.PolicyKit1', service.Gio.BusNameOwnerFlags.NONE, None, None)
    service.main()
    service.Gio.bus_unown_name(owner)


class DBusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'led').mkdir()
        for name, value in {'multi_index': 'red green blue', 'multi_intensity': '255 255 255',
                            'brightness': '128', 'max_brightness': '255'}.items():
            (self.root / 'led' / name).write_text(value)
        (self.root / 'protocol').write_text('intel-ac-dc-v1')
        ac = self.root / 'supplies' / 'AC0'
        ac.mkdir(parents=True)
        (ac / 'type').write_text('Mains')
        (ac / 'online').write_text('1')
        self.env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=os.environ['DBUS_SESSION_BUS_ADDRESS'])

    def launch(self, allowed):
        self.process = subprocess.Popen([sys.executable, __file__, '--server', str(self.root), str(int(allowed))],
                                        env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop)
        for _ in range(30):
            result = self.call('GetState')
            if result.returncode == 0:
                return result.stdout
            time.sleep(0.05)
        self.fail('Service did not become available: ' + result.stderr)

    def stop(self):
        self.process.terminate()
        stdout, stderr = self.process.communicate(timeout=5)
        if stderr:
            print(stderr, file=sys.stderr)

    def call(self, method, *args):
        return subprocess.run(['gdbus', 'call', '--system', '--dest', service.NAME,
                               '--object-path', service.PATH, '--method', service.NAME + '.' + method,
                               *args], env=self.env, capture_output=True, text=True, timeout=5)

    def test_read_and_authorized_color_round_trip(self):
        self.assertIn("uint32 255, uint32 255, uint32 255, uint32 128, 'ac'", self.launch(True))
        self.assertFalse((self.root / 'auth.json').exists())
        result = self.call('SetColor', '255', '0', '0', 'ac')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'led' / 'multi_intensity').read_text(), '255 0 0\n')
        auth = json.loads((self.root / 'auth.json').read_text())
        self.assertEqual(auth[0][0], 'system-bus-name')
        self.assertTrue(auth[0][1]['name'].startswith(':'))
        self.assertEqual(auth[1:], [service.ACTION, {}, 0, ''])

    def test_denied_color_leaves_fixture_unchanged(self):
        self.launch(False)
        result = self.call('SetColor', '255', '0', '0', 'ac')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('NotAuthorized', result.stderr)
        self.assertEqual((self.root / 'led' / 'multi_intensity').read_text(), '255 255 255')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--server':
        server(sys.argv[2], bool(int(sys.argv[3])))
    else:
        if 'DBUS_SESSION_BUS_ADDRESS' not in os.environ:
            raise SystemExit('Run: dbus-run-session -- python3 tests/test_gnome_dbus.py')
        unittest.main()
