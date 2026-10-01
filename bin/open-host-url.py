#!/usr/bin/env python3
"""Open web links through the host desktop portal, outside Wine's home overlay."""
import sys
from urllib.parse import urlsplit
import uuid


def valid_url(url):
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        return parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
    except ValueError:
        return False


def open_url(url):
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()
    token = 'spark_' + uuid.uuid4().hex
    sender = bus.get_unique_name().lstrip(':').replace('.', '_')
    path = f'/org/freedesktop/portal/desktop/request/{sender}/{token}'
    result = 2
    timer = None

    def response(_bus, _sender, _path, _interface, _signal, parameters):
        nonlocal result
        result, _ = parameters.unpack()
        loop.quit()

    def timeout():
        nonlocal timer
        timer = None
        loop.quit()
        return False

    subscription = bus.signal_subscribe(
        'org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request',
        'Response', path, None, Gio.DBusSignalFlags.NONE, response)
    timer = GLib.timeout_add_seconds(60, timeout)
    try:
        reply = bus.call_sync(
            'org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
            'org.freedesktop.portal.OpenURI', 'OpenURI',
            GLib.Variant('(ssa{sv})', ('', url, {
                'handle_token': GLib.Variant('s', token),
                'ask': GLib.Variant('b', False),
            })), GLib.VariantType.new('(o)'), Gio.DBusCallFlags.NONE, 10000, None)
        actual_path, = reply.unpack()
        if actual_path != path:
            bus.signal_unsubscribe(subscription)
            subscription = bus.signal_subscribe(
                'org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request',
                'Response', actual_path, None, Gio.DBusSignalFlags.NONE, response)
        loop.run()
    finally:
        if timer is not None:
            GLib.source_remove(timer)
        bus.signal_unsubscribe(subscription)
    return result


def main():
    if len(sys.argv) != 2 or not valid_url(sys.argv[1]):
        sys.exit('error: expected one HTTP or HTTPS link.')
    try:
        result = open_url(sys.argv[1])
    except Exception:
        # Portal errors can include OAuth URLs. Report no request details.
        sys.exit('error: cannot contact the host desktop portal. Check the session bus and python-gobject.')
    if result == 1:
        return
    if result != 0:
        sys.exit('error: the host desktop portal did not open the link.')


if __name__ == '__main__':
    main()
