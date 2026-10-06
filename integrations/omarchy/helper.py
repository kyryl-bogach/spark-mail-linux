#!/usr/bin/env python3
"""Read the Spark inbox without persistent email data."""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit
from reminders import Reminders

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


def json_rows(output, key):
    try:
        rows = json.loads(output)[key]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Unsupported rows')
        return rows
    except (KeyError, TypeError, ValueError):
        raise ValueError('Unsupported CLI output') from None


def parse_emails(output):
    """Read full email metadata without fixed-column truncation."""
    try:
        emails = []
        for row in json_rows(output, 'emails'):
            if not isinstance(row['id'], int) or isinstance(row['id'], bool) or row['id'] < 1:
                raise ValueError('Unsupported message ID')
            sender = ', '.join(person.get('name') or person['email'] for person in row['from'])
            emails.append({'id': str(row['id']), 'sender': sender or '(Unknown sender)',
                           'subject': row.get('subject') or '(No subject)',
                           'date': datetime.fromisoformat(row['date']).astimezone().strftime('%Y-%m-%d %H:%M')})
        return emails
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ValueError('Unsupported email output') from None


def event_location(row):
    """Show the stated location or the conference provider."""
    location = row.get('location')
    location = location.strip() if isinstance(location, str) else ''
    conference = row.get('conference_url')
    candidate = location or (conference.strip() if isinstance(conference, str) else '')
    try:
        url = urlsplit(candidate)
        host = url.hostname if url.scheme in {'http', 'https'} else None
    except ValueError:
        host = None
    if host:
        for domain, label in (('meet.google.com', 'Google Meet'), ('zoom.us', 'Zoom'),
                              ('teams.microsoft.com', 'Microsoft Teams'), ('teams.live.com', 'Microsoft Teams')):
            if host == domain or host.endswith('.' + domain):
                return label
        return location or 'Online meeting'
    return location


def parse_events(output):
    """Use one calendar model for the popup, indicator, and reminders."""
    try:
        events = []
        for row in json_rows(output, 'events'):
            if not isinstance(row['all_day'], bool) or not isinstance(row['id'], str) or not row['id']:
                raise ValueError('Unsupported event')
            if not isinstance(row['title'], str):
                raise ValueError('Unsupported title')
            if row.get('attending_status') in {'declined', 'no'}:
                continue
            start = datetime.fromisoformat(row['start'])
            if row['all_day']:
                day = start.astimezone().date() if start.tzinfo is not None else start.date()
                start_ms, time_label = None, 'All day'
            else:
                end = datetime.fromisoformat(row['end'])
                if start.tzinfo is None or end.tzinfo is None:
                    raise ValueError('Calendar times need an offset')
                start, end = start.astimezone(), end.astimezone()
                day = start.date()
                start_ms = int(start.timestamp() * 1000)
                time_label = f'{start:%H:%M} – {end:%H:%M}'
            events.append({'id': row['id'], 'title': row['title'] or 'Untitled event',
                           'day': day.isoformat(), 'time': time_label, 'start_ms': start_ms,
                           'location': event_location(row)})
        return sorted(events, key=lambda event: (event['day'], event['start_ms'] or 0))
    except (KeyError, TypeError, ValueError):
        raise ValueError('Unsupported calendar output') from None


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
    status, output = run_cli('emails', '--json')
    if status == 'timeout':
        return {'status': 'Spark did not respond', 'emails': []}
    if status == 'error':
        return {'status': 'CLI unavailable. Check Spark CLI access in Settings.', 'emails': []}
    try:
        rows = parse_emails(output)
    except ValueError:
        return {'status': 'Cannot read the Spark inbox', 'emails': []}
    if not rows:
        status, output = run_cli('accounts', '--json')
        if status == 'ok':
            try:
                if not json_rows(output, 'accounts'):
                    return {'status': 'No accounts shared. Enable one in Spark AI Agents.', 'emails': []}
            except ValueError:
                return {'status': 'Cannot read Spark account access', 'emails': []}
    return {'status': 'Inbox' if rows else 'Inbox is empty', 'emails': rows}


def read_calendar(now):
    # Include the next day across the week boundary for overnight reminders.
    today = now.date()
    end = today + timedelta(days=max(7 - today.weekday(), 2))
    status, output = run_cli('events', '--start', now.strftime('%Y-%m-%dT%H:%M'), '--end', end.isoformat(), '--json')
    if status != 'ok':
        return status, []
    try:
        return 'ok', parse_events(output)
    except ValueError:
        return 'invalid', []


def calendar_view(status, rows, today):
    result = {'label': 'Today', 'status': '', 'events': [], 'start_times': []}
    if status != 'ok':
        result['status'] = 'Spark did not respond' if status == 'timeout' else 'Cannot read the Spark calendar'
        return result
    if not rows:
        result['status'] = 'No upcoming events'
        return result
    first = date.fromisoformat(max(rows[0]['day'], today.isoformat()))
    result['label'] = ('Today' if first == today else 'Tomorrow' if first == today + timedelta(days=1)
                       else f'{first:%A, %b} {first.day}')
    result['events'] = [{'title': row['title'], 'time': row['time'], 'location': row['location']} for row in rows
                        if max(row['day'], today.isoformat()) == first.isoformat()]
    result['start_times'] = [row['start_ms'] for row in rows if row['start_ms'] is not None]
    return result


def update_reminders(enabled, status, rows):
    if enabled is None:
        return {'ok': True, 'status': ''}
    try:
        if not enabled:
            return {'ok': True, 'status': 'Calendar reminders disabled', 'cancelled': Reminders().clear()}
        if status == 'closed':
            return {'ok': True, 'status': 'Calendar reminders await Spark'}
        if status != 'ok':
            return {'ok': False, 'status': 'Cannot update calendar reminders. Check Spark CLI access.'}
        return dict(Reminders().sync([row for row in rows if row['start_ms'] is not None]), ok=True, status='')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {'ok': False, 'status': 'Calendar reminders are unavailable'}


def overview(reminders_enabled=None, now=None):
    now = (now or datetime.now()).astimezone()
    status, rows = read_calendar(now) if spark_running() else ('closed', [])
    # Update timers before an inbox read that could time out.
    reminders = update_reminders(reminders_enabled, status, rows)
    calendar = calendar_view(status, rows, now.date())
    mail = inbox()
    if status == 'closed':
        calendar['status'] = 'Spark is closed'
    return {'status': mail['status'], 'emails': mail['emails'],
            'events_label': calendar['label'], 'events_status': calendar['status'],
            'events': calendar['events'], 'event_starts_ms': calendar['start_times'],
            'reminders_ok': reminders['ok'], 'reminder_status': reminders['status']}


def sync_reminders(now=None):
    status, rows = read_calendar((now or datetime.now()).astimezone()) if spark_running() else ('closed', [])
    return update_reminders(True, status, rows)


def forward_desktop(*arguments):
    """Forward a desktop action without additional background helpers."""
    env = dict(os.environ, SPARK_ROOT=str(ROOT), SPARK_DEBUG='-all',
               SPARK_NOTIFY='0', SPARK_CLOSE_TRAY='0')
    subprocess.run([str(ROOT / 'run-spark.sh'), *arguments], env=env,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=True, timeout=30)


def open_email(message_id):
    """Open a thread in the running app through its Spark deep link."""
    if not message_id.isdigit():
        raise ValueError('Unsupported message ID')
    status, output = run_cli('thread', message_id)
    if status != 'ok':
        raise subprocess.SubprocessError('Spark did not return the thread')
    match = re.search(r'^Link: (\S+)$', output, re.MULTILINE)
    if not match:
        raise ValueError('Unsupported CLI output')
    url = urlsplit(match.group(1))
    if (url.scheme, url.hostname, url.path) != ('https', 'sparkmailapp.com', '/dpl/bl'):
        raise ValueError('Unsupported Spark link')
    forward_desktop('--win-open-url', match.group(1))
    client = spark_window()
    if client is not None:
        focus_window(client['address'],
                     client.get('workspace', {}).get('name') == 'spark-background')


def focus_window(address, from_background=False):
    """Focus a window, and move it from the startup workspace when needed."""
    if not re.fullmatch(r'0x[0-9a-fA-F]+', address):
        raise ValueError('Unsupported Hyprland window address')
    options = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL, 'timeout': 5}
    if from_background:
        active = json.loads(subprocess.check_output(['hyprctl', 'activeworkspace', '-j'], timeout=5))
        workspace = active['id']
        if not isinstance(workspace, int) or workspace < 1:
            raise ValueError('No active regular workspace')
        move = (f'hl.dsp.window.move({{ workspace = "{workspace}", follow = false, '
                f'window = "address:{address}" }})')
        subprocess.run(['hyprctl', 'dispatch', move], check=True, **options)
    lua = f'hl.dsp.focus({{ window = "address:{address}" }})'
    process = subprocess.run(['hyprctl', 'dispatch', lua], **options)
    if process.returncode:
        subprocess.run(['hyprctl', 'dispatch', 'focuswindow', 'address:' + address],
                       check=True, **options)


def spark_window():
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
        return client
    return None


def open_spark():
    client = spark_window()
    if client is None:
        subprocess.Popen([str(ROOT / 'run-spark.sh')], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        for _ in range(120):
            time.sleep(0.5)
            client = spark_window()
            if client is not None:
                break
        else:
            raise subprocess.SubprocessError('Spark window did not appear')
    focus_window(client['address'],
                 client.get('workspace', {}).get('name') == 'spark-background')


def open_calendar():
    """Open the calendar through Spark's Windows task action."""
    open_spark()
    forward_desktop('--dock-task-id=OPEN_CALENDAR_ACTION')


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['open']:
            open_spark()
        elif sys.argv[1:] == ['open-calendar']:
            open_calendar()
        elif len(sys.argv) == 3 and sys.argv[1] == 'open-email':
            open_email(sys.argv[2])
        elif sys.argv[1:] == ['reminders-sync']:
            print(json.dumps(sync_reminders()))
        elif sys.argv[1:] == ['reminders-clear']:
            print(json.dumps({'ok': True, 'status': 'Calendar reminders disabled',
                              'cancelled': Reminders().clear()}))
        elif sys.argv[1:] in (['list'], ['list', '--reminders'], ['list', '--no-reminders']):
            enabled = None if len(sys.argv) == 2 else sys.argv[2] == '--reminders'
            print(json.dumps(overview(enabled)))
        else:
            sys.exit('usage: helper.py list [--reminders|--no-reminders]|open|open-calendar|open-email <id>|reminders-sync|reminders-clear')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        if sys.argv[1:2] == ['list']:
            print(json.dumps({'status': 'Cannot read the Spark inbox', 'emails': [],
                              'events_label': 'Today',
                              'events_status': 'Cannot read the Spark calendar', 'events': [],
                              'event_starts_ms': [], 'reminders_ok': False,
                              'reminder_status': 'Calendar reminders are unavailable'}))
        elif sys.argv[1:] in (['reminders-sync'], ['reminders-clear']):
            print(json.dumps({'ok': False, 'status': 'Calendar reminders are unavailable'}))
        else:
            sys.exit(1)
