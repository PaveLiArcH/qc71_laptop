#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""System D-Bus bridge. Authorize each write using the actual bus sender."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import signal
import sys

from gi.repository import Gio, GLib

# -I excludes both cwd and the script directory; only trust our installed files.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend import Keyboard

NAME = 'io.github.PaveLiArcH.Qc71Keyboard1'
PATH = '/io/github/PaveLiArcH/Qc71Keyboard1'
ACTION = 'io.github.PaveLiArcH.qc71-keyboard.set-color'
XML = f'''<node><interface name="{NAME}">
<method name="GetState">
 <arg name="red" type="u" direction="out"/>
 <arg name="green" type="u" direction="out"/>
 <arg name="blue" type="u" direction="out"/>
 <arg name="brightness" type="u" direction="out"/>
 <arg name="source" type="s" direction="out"/>
</method>
<method name="SetColor">
 <arg name="red" type="u" direction="in"/>
 <arg name="green" type="u" direction="in"/>
 <arg name="blue" type="u" direction="in"/>
 <arg name="expected_source" type="s" direction="in"/>
 <arg name="red" type="u" direction="out"/>
 <arg name="green" type="u" direction="out"/>
 <arg name="blue" type="u" direction="out"/>
 <arg name="brightness" type="u" direction="out"/>
 <arg name="source" type="s" direction="out"/>
</method>
</interface></node>'''


def authorize(connection, sender):
    result = connection.call_sync(
        'org.freedesktop.PolicyKit1', '/org/freedesktop/PolicyKit1/Authority',
        'org.freedesktop.PolicyKit1.Authority', 'CheckAuthorization',
        GLib.Variant('((sa{sv})sa{ss}us)', (
            ('system-bus-name', {'name': GLib.Variant('s', sender)}),
            ACTION, {}, 0, '')),
        GLib.VariantType.new('((bba{ss}))'), Gio.DBusCallFlags.NONE, 5000, None)
    if not result.unpack()[0][0]:
        raise PermissionError('Only an active local session may change the keyboard color')


class Service:
    def __init__(self, connection):
        self.connection = connection
        self.keyboard = Keyboard()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.busy = False
        self.registration = connection.register_object(
            PATH, Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], self.call, None, None)

    def call(self, connection, sender, path, interface, method, parameters, invocation):
        if method not in ('GetState', 'SetColor'):
            invocation.return_dbus_error(NAME + '.UnknownMethod', 'Unknown method')
            return
        if self.busy:
            invocation.return_dbus_error(NAME + '.Busy', 'Keyboard is busy; try again')
            return
        self.busy = True

        def work():
            try:
                if method == 'SetColor':
                    authorize(connection, sender)
                    state = self.keyboard.set_color(*parameters.unpack())
                else:
                    state = self.keyboard.state()
                GLib.idle_add(finish, state, None)
            except Exception as error:
                GLib.idle_add(finish, None, error)

        def finish(state, error):
            self.busy = False
            if error:
                code = '.NotAuthorized' if isinstance(error, PermissionError) else '.Failed'
                invocation.return_dbus_error(NAME + code, str(error))
            else:
                invocation.return_value(GLib.Variant('(uuuus)', state))
            return GLib.SOURCE_REMOVE

        self.pool.submit(work)


def main():
    loop = GLib.MainLoop()
    connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    service = Service(connection)

    def lost(*args):
        print('Cannot own ' + NAME, file=sys.stderr)
        loop.quit()

    owner = Gio.bus_own_name_on_connection(
        connection, NAME, Gio.BusNameOwnerFlags.NONE, None, lost)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, loop.quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, loop.quit)
    try:
        loop.run()
    finally:
        service.pool.shutdown(wait=True)
        connection.unregister_object(service.registration)
        Gio.bus_unown_name(owner)


if __name__ == '__main__':
    main()
