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
            if os.fsencode('SPARK_ROOT=' + str(ROOT)) in environment:
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
        if re.fullmatch(r'Page \d+ of \d+\+? \(\d+\+? total emails\)', line.strip()):
            continue
        fields = [line[start:end].strip() for start, end in zip(positions, positions[1:] + [len(line)])]
        if not fields[0].isdigit():
            raise ValueError('Unsupported CLI row')
        rows.append(dict(zip(['id', 'account', 'sender', 'date', 'subject', 'flags'], fields)))
    return rows


def no_accounts(output):
    return 'No accounts found.' in [line.strip() for line in output.splitlines()]


def run_cli(*arguments):
    process = subprocess.Popen([str(ROOT / 'bin/spark'), *arguments], stdout=subprocess.PIPE,
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
        return 'timeout', ''
    if process.returncode:
        return 'error', ''
    return 'ok', output


def inbox():
    if not spark_running():
        return {'status': 'Spark is closed', 'emails': []}
    status, output = run_cli('emails')
    if status == 'timeout':
        return {'status': 'Spark did not respond', 'emails': []}
    if status == 'error':
        return {'status': 'CLI unavailable. Check Spark CLI access in Settings.', 'emails': []}
    rows = parse_emails(output)
    if not rows:
        account_status, account_output = run_cli('accounts')
        if account_status == 'ok' and no_accounts(account_output):
            return {'status': 'No accounts shared. Enable one in Spark AI Agents.', 'emails': []}
    return {'status': 'Inbox' if rows else 'Inbox is empty', 'emails': rows}


def focus_window(address):
    """Focus an address on current Hyprland, with pre-0.55 compatibility."""
    if not re.fullmatch(r'0x[0-9a-fA-F]+', address):
        raise ValueError('Unsupported Hyprland window address')
    options = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL, 'timeout': 5}
    lua = f'hl.dsp.focus({{ window = "address:{address}" }})'
    process = subprocess.run(['hyprctl', 'dispatch', lua], **options)
    if process.returncode:
        subprocess.run(['hyprctl', 'dispatch', 'focuswindow', 'address:' + address],
                       check=True, **options)


def open_spark():
    clients = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j'], timeout=5))
    for client in clients:
        if client.get('class', '').lower() != 'spark desktop.exe':
            continue
        try:
            environment = Path('/proc', str(client['pid']), 'environ').read_bytes().split(b'\0')
        except OSError:
            continue
        if os.fsencode('SPARK_ROOT=' + str(ROOT)) not in environment:
            continue
        focus_window(client['address'])
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
