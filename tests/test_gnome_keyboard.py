#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""RGB bridge checks using only temporary fixtures; no real hardware writes."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1] / 'contrib' / 'gnome'
sys.path.insert(0, str(ROOT))
from backend import Keyboard, KeyboardError
import service


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.led = self.root / 'led'
        self.led.mkdir()
        self.protocol = self.root / 'protocol'
        self.protocol.write_text('intel-ac-dc-v1\n')
        for name, value in {'multi_index': 'red green blue', 'multi_intensity': '255 255 255',
                            'brightness': '128', 'max_brightness': '255'}.items():
            (self.led / name).write_text(value + '\n')
        self.supplies = self.root / 'supplies'
        self.supplies.mkdir()
        self.supply('AC0', 'Mains', '1')
        self.supply('BAT0', 'Battery', '1')
        self.keyboard = Keyboard(self.led, self.protocol, self.supplies)
        self.sleep = patch('backend.time.sleep')
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def supply(self, name, kind, online, scope=None):
        path = self.supplies / name
        path.mkdir(exist_ok=True)
        (path / 'type').write_text(kind)
        (path / 'online').write_text(online)
        if scope:
            (path / 'scope').write_text(scope)

    def test_reads_do_not_write(self):
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(self.keyboard.state(), (255, 255, 255, 128, 'ac'))
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_only_color_written_once(self):
        original = Path.write_text
        writes = []

        def write(path, content, *args, **kwargs):
            writes.append((path, content))
            return original(path, content, *args, **kwargs)

        with patch.object(Path, 'write_text', write):
            self.assertEqual(self.keyboard.set_color(255, 0, 0, 'ac'), (255, 0, 0, 128, 'ac'))
        self.assertEqual(writes, [(self.led / 'multi_intensity', '255 0 0\n')])

    def test_respects_channel_order(self):
        (self.led / 'multi_index').write_text('blue red green')
        self.keyboard.set_color(255, 128, 0, 'ac')
        self.assertEqual((self.led / 'multi_intensity').read_text(), '0 255 128\n')
        self.assertEqual(self.keyboard.read()[:3], (255, 128, 0))

    def test_color_while_off_keeps_off(self):
        (self.led / 'brightness').write_text('0')
        self.assertEqual(self.keyboard.set_color(255, 0, 0, 'ac')[3], 0)

    def test_input_rejected_before_write(self):
        for rgb, source in [((0, 0, 0), 'ac'), ((2, 2, 2), 'ac'),
                            ((256, 0, 0), 'ac'), ((-1, 0, 0), 'ac'),
                            ((True, 0, 0), 'ac'), ((1.0, 0, 0), 'ac'),
                            ((255, 0, 0), '../ac')]:
            with self.subTest(rgb=rgb, source=source):
                with self.assertRaises(KeyboardError):
                    self.keyboard.set_color(*rgb, source)
                self.assertEqual((self.led / 'multi_intensity').read_text(), '255 255 255\n')

    def test_switch_before_apply_never_writes(self):
        (self.supplies / 'AC0' / 'online').write_text('0')
        with self.assertRaisesRegex(KeyboardError, 'Power source changed'):
            self.keyboard.set_color(255, 0, 0, 'ac')
        self.assertEqual((self.led / 'multi_intensity').read_text(), '255 255 255\n')

    def test_switch_after_apply_never_replays_or_restores(self):
        with patch.object(self.keyboard, 'read', side_effect=[
                (255, 255, 255, 128, 'ac'), (255, 255, 255, 128, 'ac'),
                (255, 0, 0, 128, 'dc')]):
            with self.assertRaisesRegex(KeyboardError, 'during apply'):
                self.keyboard.set_color(255, 0, 0, 'ac')
        self.assertEqual((self.led / 'multi_intensity').read_text(), '255 0 0\n')

    def test_failed_async_apply_is_reported(self):
        with patch.object(self.keyboard, 'read', return_value=(255, 255, 255, 128, 'ac')):
            with self.assertRaisesRegex(KeyboardError, 'did not settle'):
                self.keyboard.set_color(255, 0, 0, 'ac')

    def test_quantized_readback_accepted(self):
        with patch.object(self.keyboard, 'read', side_effect=[
                (255, 255, 255, 128, 'ac'), (255, 255, 255, 128, 'ac'),
                *[(255, 128, 0, 128, 'ac')] * 3]):
            self.keyboard.set_color(255, 127, 0, 'ac')

    def test_power_supply_matches_system_scope(self):
        self.supply('AC0', 'Mains', '0')
        self.supply('mouse', 'USB', '1', 'Device')
        self.assertEqual(self.keyboard.source(), 'dc')
        self.supply('usb_c', 'USB', '1', 'System')
        self.assertEqual(self.keyboard.source(), 'ac')

    def test_invalid_source_fails_closed(self):
        (self.supplies / 'AC0' / 'online').unlink()
        with self.assertRaises(OSError):
            self.keyboard.set_color(255, 0, 0, 'ac')

    def test_invalid_protocol_or_channels_fails_closed(self):
        for file, value in [(self.protocol, 'legacy'),
                            (self.led / 'multi_index', 'red red blue'),
                            (self.led / 'max_brightness', '4')]:
            with self.subTest(file=file):
                old = file.read_text()
                file.write_text(value)
                with self.assertRaises(KeyboardError):
                    self.keyboard.set_color(255, 0, 0, 'ac')
                file.write_text(old)


class AuthorizationTests(unittest.TestCase):
    def test_uses_bus_sender_without_interactive_auth(self):
        from unittest.mock import Mock
        connection = Mock()
        connection.call_sync.return_value = service.GLib.Variant('((bba{ss}))', ((True, False, {}),))
        service.authorize(connection, ':1.123')
        args = connection.call_sync.call_args.args
        self.assertEqual(args[4].unpack(), (
            ('system-bus-name', {'name': ':1.123'}), service.ACTION, {}, 0, ''))

    def test_denial(self):
        from unittest.mock import Mock
        connection = Mock()
        connection.call_sync.return_value = service.GLib.Variant('((bba{ss}))', ((False, False, {}),))
        with self.assertRaises(PermissionError):
            service.authorize(connection, ':1.123')

    def test_policy_active_local_only(self):
        defaults = ET.parse(ROOT / 'io.github.PaveLiArcH.qc71-keyboard.policy').find('action/defaults')
        self.assertEqual({node.tag: node.text for node in defaults},
                         {'allow_any': 'no', 'allow_inactive': 'no', 'allow_active': 'yes'})


class DispatchTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        self.connection = Mock()
        self.bridge = service.Service(self.connection)
        self.addCleanup(self.bridge.pool.shutdown)
        self.bridge.keyboard = Mock()
        self.bridge.keyboard.state.return_value = (255, 255, 255, 128, 'ac')
        self.bridge.keyboard.set_color.return_value = (255, 0, 0, 128, 'ac')
        self.invocation = Mock()
        self.auth = patch.object(service, 'authorize')
        self.authorize = self.auth.start()
        self.addCleanup(self.auth.stop)

    def call(self, method, values=None):
        # Execute the worker and completion synchronously to inspect dispatch.
        with patch.object(self.bridge.pool, 'submit', side_effect=lambda function: function()), \
                patch.object(service.GLib, 'idle_add', side_effect=lambda callback, *args: callback(*args)):
            self.bridge.call(self.connection, ':1.234', service.PATH, service.NAME,
                             method, values, self.invocation)

    def test_read_never_authorizes_or_writes(self):
        self.call('GetState')
        self.authorize.assert_not_called()
        self.bridge.keyboard.set_color.assert_not_called()
        self.assertEqual(self.invocation.return_value.call_args.args[0].unpack(),
                         (255, 255, 255, 128, 'ac'))

    def test_denied_write_never_reaches_backend(self):
        self.authorize.side_effect = PermissionError('denied')
        self.call('SetColor', service.GLib.Variant('(uuus)', (255, 0, 0, 'ac')))
        self.authorize.assert_called_once_with(self.connection, ':1.234')
        self.bridge.keyboard.set_color.assert_not_called()
        self.assertEqual(self.invocation.return_dbus_error.call_args.args[0],
                         service.NAME + '.NotAuthorized')

    def test_authorized_write(self):
        self.call('SetColor', service.GLib.Variant('(uuus)', (255, 0, 0, 'ac')))
        self.authorize.assert_called_once_with(self.connection, ':1.234')
        self.bridge.keyboard.set_color.assert_called_once_with(255, 0, 0, 'ac')

    def test_busy_refuses_before_queueing(self):
        self.bridge.busy = True
        self.call('GetState')
        self.bridge.keyboard.state.assert_not_called()
        self.assertEqual(self.invocation.return_dbus_error.call_args.args[0], service.NAME + '.Busy')


if __name__ == '__main__':
    unittest.main()
