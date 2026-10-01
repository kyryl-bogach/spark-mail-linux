#!/usr/bin/env python3
"""Hide Wine's tray window and preserve its clipboard manager."""
import ctypes
import ctypes.util
import os
from pathlib import Path
import re
import subprocess
import sys
import time


PROC = Path(os.environ.get('SPARK_PROC_ROOT', '/proc'))


class ClientMessage(ctypes.Structure):
    _fields_ = [
        ('type', ctypes.c_int), ('serial', ctypes.c_ulong),
        ('send_event', ctypes.c_int), ('display', ctypes.c_void_p),
        ('window', ctypes.c_ulong), ('message_type', ctypes.c_ulong),
        ('format', ctypes.c_int), ('data', ctypes.c_long * 5),
    ]


class XEvent(ctypes.Union):
    _fields_ = [('client', ClientMessage), ('pad', ctypes.c_long * 24)]


def tray_windows(pid):
    def property_text(*arguments):
        return subprocess.check_output(
            ['xprop', *arguments], text=True, stderr=subprocess.DEVNULL, timeout=2)

    windows = property_text('-root', '_NET_CLIENT_LIST')
    for window in re.findall(r'0x[0-9a-fA-F]+', windows):
        properties = property_text('-id', window, '_NET_WM_PID', 'WM_CLASS')
        owner = re.search(r'_NET_WM_PID\(CARDINAL\) = (\d+)', properties)
        if owner and int(owner[1]) == pid and '"explorer.exe"' in properties.lower():
            yield int(window, 16)


def hide_tray(pid):
    x11 = ctypes.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                               ctypes.c_long, ctypes.POINTER(XEvent)]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = x11.XOpenDisplay(None)
    if not display:
        return False
    try:
        hidden = False
        for window in tray_windows(pid):
            event = XEvent()
            event.client.type = 33  # ClientMessage
            event.client.display = display
            event.client.window = window
            event.client.message_type = x11.XInternAtom(display, b'WM_PROTOCOLS', False)
            event.client.format = 32
            event.client.data[0] = x11.XInternAtom(display, b'WM_DELETE_WINDOW', False)
            # Wine handles WM_CLOSE by hiding this window. It keeps explorer alive.
            hidden = bool(x11.XSendEvent(display, window, False, 0, ctypes.byref(event))) or hidden
        x11.XFlush(display)
        return hidden
    finally:
        x11.XCloseDisplay(display)


def process_data(path):
    try:
        command = (path / 'cmdline').read_bytes().split(b'\0')
        environment = (path / 'environ').read_bytes().split(b'\0')
    except (OSError, PermissionError):
        return [], []
    return command, environment


def find_processes(prefix):
    expected_prefix = os.fsencode('WINEPREFIX=' + str(prefix))
    explorer = None
    renderer = False
    for path in PROC.glob('[0-9]*'):
        command, environment = process_data(path)
        if expected_prefix not in environment or not command:
            continue
        executable = command[0].lower()
        arguments = [value.lower() for value in command[1:] if value]
        if executable.endswith(b'explorer.exe') and b'/desktop' in arguments:
            explorer = int(path.name)
        elif executable.endswith(b'spark desktop.exe') and any(
                value.startswith(b'--type=renderer') for value in arguments):
            renderer = True
    return explorer, renderer


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: close-tray.py WINEPREFIX')
    prefix = Path(sys.argv[1]).resolve()
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        explorer, renderer = find_processes(prefix)
        if explorer is not None and renderer:
            time.sleep(2)
            current_explorer, _ = find_processes(prefix)
            if current_explorer == explorer:
                try:
                    if hide_tray(explorer):
                        return
                except (OSError, subprocess.SubprocessError):
                    print('warning: cannot hide the Wine tray window; the clipboard helper remains active.', file=sys.stderr)
                    return
        time.sleep(0.1)


if __name__ == '__main__':
    main()
