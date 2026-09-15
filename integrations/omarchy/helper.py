#!/usr/bin/env python3
"""Read the Spark inbox without persistent email data."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def spark_running():
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            command = path.read_bytes().split(b'\0')
            if not any(arg.lower().endswith(b'spark desktop.exe') for arg in command):
                continue
            environment = (path.parent / 'environ').read_bytes().split(b'\0')
            if os.fsencode('WINEPREFIX=' + str(ROOT / 'prefix')) in environment:
                return True
        except (OSError, PermissionError):
            continue
    return False


def parse_emails(output):
    """Parse fixed columns from the installed CLI's header."""
    lines = output.splitlines()
    headings = ['ID', 'Account', 'From', 'Date', 'Subject', 'Flags']
    for index, line in enumerate(lines):
        if re.split(r'\s{2,}', line.strip()) == headings:
            positions = [line.index(name) for name in headings]
            break
    else:
        if re.search(r'\b0 total emails\b', output) or 'No emails found.' in [text.strip() for text in lines]:
            return []
        raise ValueError('Unsupported CLI output')
    rows = []
    for line in lines[index + 1:]:
        if not line.strip():
            continue
        if re.fullmatch(r'Page \d+ of \d+ \(\d+ total emails\)', line.strip()):
            continue
        fields = [line[start:end].strip() for start, end in zip(positions, positions[1:] + [len(line)])]
        if not fields[0].isdigit():
            raise ValueError('Unsupported CLI row')
        rows.append(dict(zip(['id', 'account', 'sender', 'date', 'subject', 'flags'], fields)))
    return rows


def inbox():
    if not spark_running():
        return {'status': 'Spark is closed', 'emails': []}
    process = subprocess.Popen([str(ROOT / 'bin/spark'), 'emails'], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        return {'status': 'Spark did not respond', 'emails': []}
    if process.returncode:
        return {'status': 'CLI unavailable. Check Spark CLI access in Settings.', 'emails': []}
    rows = parse_emails(output)
    return {'status': 'Inbox' if rows else 'Inbox is empty', 'emails': rows}


def open_spark():
    clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j'], timeout=5))
    for client in clients:
        if client.get('class', '').lower() != 'spark desktop.exe':
            continue
        try:
            environment = Path('/proc', str(client['pid']), 'environ').read_bytes().split(b'\0')
        except OSError:
            continue
        if os.fsencode('WINEPREFIX=' + str(ROOT / 'prefix')) not in environment:
            continue
        subprocess.run(['hyprctl', 'dispatch', 'focuswindow', 'address:' + client['address']],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        return
    subprocess.Popen([str(ROOT / 'run-spark.sh')], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['open']:
            open_spark()
        elif sys.argv[1:] == ['list']:
            print(json.dumps(inbox()))
        else:
            sys.exit('usage: helper.py list|open')
    except (OSError, ValueError, subprocess.SubprocessError):
        if sys.argv[1:] == ['list']:
            print(json.dumps({'status': 'Cannot read the Spark inbox', 'emails': []}))
        else:
            sys.exit(1)
