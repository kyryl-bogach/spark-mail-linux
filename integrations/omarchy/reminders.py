"""Keep Spark calendar alerts in Omarchy's native reminder queue."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
LEADS = (5, 1)
HORIZON_MS = 24 * 60 * 60 * 1000
MAX_LATENESS_MS = 30 * 1000


def write_private(path, content):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(descriptor, 'w') as output:
            output.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Reminders:
    def __init__(self, root=ROOT, runtime=None):
        self.root = Path(root).resolve()
        self.installation = hashlib.sha256(os.fsencode(self.root)).hexdigest()[:12]
        runtime = Path(runtime or os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
        self.directory = runtime / 'spark-calendar-reminders' / self.installation
        self.messages = runtime / 'omarchy-reminders'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.messages.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.pattern = re.compile(r'omarchy-reminder-(?:5|1)m-spark-' + self.installation + r'-[0-9a-f]{16}')

    @contextmanager
    def locked(self):
        descriptor = os.open(self.directory / 'lock', os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def record_path(self, unit):
        if not self.pattern.fullmatch(unit):
            raise ValueError('Unknown calendar reminder')
        return self.directory / (unit + '.json')

    def read_record(self, unit):
        try:
            record = json.loads(self.record_path(unit).read_text())
            return record if isinstance(record, dict) else {}
        except (OSError, ValueError):
            return {}

    def run(self, arguments, capture=False):
        return subprocess.run(arguments, check=True, timeout=10, text=True,
                              stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)

    def active_units(self):
        result = self.run(['systemctl', '--user', 'list-timers', '--all', '--output=json', '--no-pager',
                           f'omarchy-reminder-*m-spark-{self.installation}-*.timer'], capture=True)
        rows = json.loads(result.stdout)
        return {row['unit'].removesuffix('.timer') for row in rows
                if self.pattern.fullmatch(row['unit'].removesuffix('.timer'))}

    def desired(self, events, now_ms):
        desired = {}
        for event in events:
            start = event['start_ms']
            if not now_ms < start <= now_ms + HORIZON_MS:
                continue
            identity = hashlib.sha256(f"{event['id']}:{start}".encode()).hexdigest()[:16]
            for lead in LEADS:
                unit = f'omarchy-reminder-{lead}m-spark-{self.installation}-{identity}'
                desired[unit] = {'unit': unit, 'start_ms': start, 'lead': lead,
                                 'fire_ms': start - lead * 60000, 'title': event['title']}
        return desired

    def cancel(self, unit):
        self.record_path(unit)
        # Stop only units owned by this installation. A collected service can already be absent.
        subprocess.run(['systemctl', '--user', 'stop', unit + '.timer', unit + '.service'],
                       timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.record_path(unit).unlink(missing_ok=True)
        (self.messages / (unit + '.message')).unlink(missing_ok=True)

    def schedule(self, record):
        at = datetime.fromtimestamp(record['fire_ms'] / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f UTC')
        self.run(['systemd-run', '--user', '--quiet', '--collect', '--expand-environment=no',
                  '--unit=' + record['unit'], '--on-calendar=' + at,
                  '--timer-property=AccuracySec=1s', '--property=StandardOutput=null',
                  '--property=StandardError=null', sys.executable,
                  str(self.root / 'integrations/omarchy/reminders.py'), 'fire', record['unit']])

    def refresh_indicator(self):
        try:
            subprocess.run(['omarchy-shell', '-q', 'omarchy.indicators', 'refresh'], timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def sync(self, events, now_ms=None):
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        desired = self.desired(events, now_ms)
        created = cancelled = 0
        with self.locked():
            active = self.active_units()
            for unit in active - desired.keys():
                self.cancel(unit)
                cancelled += 1
            for path in self.directory.glob('*.json'):
                unit = path.stem
                if not self.pattern.fullmatch(unit) or unit in desired:
                    continue
                record = self.read_record(unit)
                if record.get('start_ms', 0) > now_ms or record.get('start_ms', 0) < now_ms - 3600000:
                    self.cancel(unit)
            for unit, record in desired.items():
                previous = self.read_record(unit)
                if previous.get('delivered_at') is not None:
                    continue
                if record['fire_ms'] <= now_ms:
                    continue
                write_private(self.record_path(unit), json.dumps(record))
                label = escape(f"{record['title']} · {record['lead']} min before")
                write_private(self.messages / (unit + '.message'), label)
                if unit not in active:
                    self.schedule(record)
                    created += 1
        if created or cancelled:
            self.refresh_indicator()
        return {'scheduled': created, 'cancelled': cancelled}

    def clear(self):
        with self.locked():
            units = self.active_units()
            for path in self.directory.glob('*.json'):
                if self.pattern.fullmatch(path.stem):
                    units.add(path.stem)
            for unit in units:
                self.cancel(unit)
        if units:
            self.refresh_indicator()
        return len(units)

    def fire(self, unit, now_ms=None):
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        delivered = False
        with self.locked():
            record = self.read_record(unit)
            if record and record.get('delivered_at') is None:
                due = now_ms - record['fire_ms']
                if 0 <= due <= MAX_LATENESS_MS and now_ms < record['start_ms']:
                    remaining = max(1, round((record['start_ms'] - now_ms) / 60000))
                    headline = f'Meeting in {remaining} minute' + ('s' if remaining != 1 else '')
                    result = self.run(['omarchy-notification-send', '--app-name', 'Spark Calendar', '-g', '󰃭',
                                       '-u', 'normal', '-p', headline, escape('Event: ' + record['title']),
                                       '--exec', sys.executable,
                                       str(self.root / 'integrations/omarchy/helper.py'), 'open-calendar'], capture=True)
                    record['delivered_at'] = now_ms
                    record['notification_id'] = int(result.stdout.strip())
                    write_private(self.record_path(unit), json.dumps(record))
                    delivered = True
                if due >= 0:
                    (self.messages / (unit + '.message')).unlink(missing_ok=True)
        self.refresh_indicator()
        return delivered


if __name__ == '__main__':
    try:
        if len(sys.argv) == 3 and sys.argv[1] == 'fire':
            Reminders().fire(sys.argv[2])
        else:
            sys.exit('usage: reminders.py fire <unit>')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        sys.exit('error: cannot deliver the calendar reminder')
