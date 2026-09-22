#!/usr/bin/env python3
"""Close Wine's tray helper after Spark's renderer is ready."""
import os
from pathlib import Path
import signal
import sys
import time


PROC = Path(os.environ.get('SPARK_PROC_ROOT', '/proc'))


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
                    os.kill(explorer, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            return
        time.sleep(0.1)


if __name__ == '__main__':
    main()
