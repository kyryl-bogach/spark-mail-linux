#!/usr/bin/env python3
"""Read release metadata and validate an extracted Spark update."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

FEED = 'https://downloads.sparkmailapp.com/Spark3/win/dist/appcast.xml'
NOTES = 'https://sparkmailapp.com/spark3/win/changelog'
NS = '{http://www.andymatuschak.org/xml-namespaces/sparkle}'
CORE = 'resources/app.asar.unpacked/node_modules/@readdle/sparkcore-win/bin/Release/SparkCore.bundle'
# Match only the directories that update-spark.sh creates with mktemp.
UPDATER_DIRS = {kind: re.compile(kind + r'-\d+\.\d+\.\d+\.\d+-[A-Za-z0-9]{6}')
                for kind in ('pre-update', 'update')}


def version_key(version):
    if not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', version):
        raise ValueError('Unsupported Spark version')
    return tuple(map(int, version.split('.')))


def installed_version(app):
    with (Path(app) / 'resources/app.asar').open('rb') as stream:
        header = struct.unpack('<4I', stream.read(16))
        if not 0 < header[3] < 32 * 1024 * 1024:
            raise ValueError('Unsupported ASAR header')
        tree = json.loads(stream.read(header[3]))
        entry = tree['files']['dist']['files']['config']['files']['default.json']
        if entry.get('unpacked') or not 0 < entry['size'] < 1024 * 1024:
            raise ValueError('Unsupported Spark configuration')
        stream.seek(8 + header[1] + int(entry['offset']))
        version = json.loads(stream.read(entry['size']))['fullVersion']
        version_key(version)
        return version


def fetch(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        if not response.url.startswith('https://'):
            raise ValueError('Insecure release redirect')
        data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError('Release metadata is too large')
        return data


def release(data):
    candidates = []
    for item in ET.fromstring(data).findall('./channel/item'):
        enclosure = item.find('enclosure')
        if enclosure is None:
            continue
        version = enclosure.get(NS + 'version', '')
        key = version_key(version)
        url = f'https://downloads.sparkmailapp.com/Spark3/win/dist/{version}/Spark.exe'
        if enclosure.get('url') != url:
            raise ValueError('Unexpected installer URL')
        size = int(enclosure.get('length', '0'))
        if size <= 0:
            raise ValueError('Missing installer size')
        candidates.append((key, dict(version=version, url=url, size=size,
                                     date=item.findtext('pubDate', ''))))
    if not candidates:
        raise ValueError('No Windows release in the update feed')
    return max(candidates, key=lambda row: row[0])[1]


def check(app):
    current = installed_version(app)
    latest = release(fetch(FEED))
    # The release page currently has a DMG typo. The Windows feed supplies the URL.
    # Readdle can ship a rebuild without an update to the notes, so ignore the build number.
    release_version = latest['version'].rsplit('.', 1)[0]
    notes = fetch(NOTES).decode('utf-8')
    if not re.search(r'Version\s+' + re.escape(release_version) + r'(?!\d)', notes):
        raise ValueError('The release notes do not confirm the feed version')
    return dict(latest, installed=current,
                available=version_key(latest['version']) > version_key(current))


def missing_entries(installer, app):
    manifest = subprocess.check_output(['bsdtar', '-tf', str(installer)], text=True)
    missing = []
    for entry in manifest.splitlines():
        name = entry.replace('\\', '/').removeprefix('./').rstrip('/')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or ':' in name:
            raise ValueError('Unsafe installer entry')
        if name and not (Path(app) / name).exists():
            missing.append(entry)
    return missing


def verify_imports(app):
    output = subprocess.check_output(['objdump', '-p', str(Path(app) / CORE / 'Foundation.dll')], text=True)
    for dll, expected in (('sprkenv.dll', {'GetProfilesDirectoryW', 'GetAllUsersProfileDirectoryW'}),
                          ('sprkiphl.dll', {'GetAdaptersAddresses'})):
        blocks = re.findall(r'DLL Name: ([^\n]+)\n(.*?)(?=DLL Name:|The Function Table|$)', output, re.S)
        block = next((body for name, body in blocks if name.strip() == dll), '')
        functions = set(re.findall(r'^\s+[0-9a-f]+\s+(?:<none>\s+)?[0-9a-f]+\s+(\w+)\s*$', block, re.M))
        if functions != expected:
            raise ValueError(f'Unexpected Foundation imports for {dll}')
        if not (Path(app) / dll).is_file():
            raise ValueError(f'Missing {dll}')
    if re.search(r'DLL Name: (?:USERENV|IPHLPAPI)\.dll', output, re.I):
        raise ValueError('Foundation still has unpatched imports')
    for name in ('Spark Desktop.exe', f'{CORE}/spark.exe', 'resources.pak', 'snapshot_blob.bin', 'v8_context_snapshot.bin'):
        if not (Path(app) / name).is_file():
            raise ValueError(f'Missing application file: {name}')


def owned_processes(root, prefix, proc=Path('/proc')):
    result = []
    for path in proc.glob('[0-9]*/environ'):
        try:
            env = path.read_bytes().split(b'\0')
            command = (path.parent / 'cmdline').read_bytes().split(b'\0')
            wine = (os.fsencode(f'SPARK_ROOT={root}') in env and
                    os.fsencode(f'WINEPREFIX={prefix}') in env)
            helper = any(arg in (os.fsencode(str(Path(root) / 'bin' / name))
                                for name in ('mail-notify.py', 'clipboard-image-watch.py', 'close-tray.py'))
                         for arg in command)
            if wine or helper:
                result.append(int(path.parent.name))
        except (OSError, ValueError):
            continue
    return result


def stop_helpers(root, prefix):
    # The prefix server stops Wine. Stop only the host helpers here.
    for pid in owned_processes(root, prefix):
        try:
            command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            if any(arg.endswith(b'/mail-notify.py') or arg.endswith(b'/clipboard-image-watch.py')
                   or arg.endswith(b'/close-tray.py') for arg in command):
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def stop_main(root, prefix):
    for pid in owned_processes(root, prefix):
        try:
            command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            main = any(arg.lower().endswith(b'spark desktop.exe') for arg in command)
            if main and not any(arg.startswith(b'--type=') for arg in command):
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(100):
        active = False
        for pid in owned_processes(root, prefix):
            try:
                command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                active |= (any(arg.lower().endswith(b'spark desktop.exe') for arg in command)
                           and not any(arg.startswith(b'--type=') for arg in command))
            except FileNotFoundError:
                pass
        if not active:
            return
        time.sleep(0.1)
    raise ValueError('Spark did not stop. The application was not replaced.')


def wait_stopped(root, prefix):
    for attempt in range(100):
        remaining = owned_processes(root, prefix)
        if not remaining:
            return
        if attempt == 50:
            # Wine can leave a disconnected device process after its server exits.
            # Give only this installation's remaining processes a normal termination signal.
            for pid in remaining:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        time.sleep(0.1)
    raise ValueError('Spark processes remain active. The application was not replaced.')


def startup(root, prefix, version, log=None):
    if installed_version(Path(root) / 'app') != version:
        raise ValueError('Installed version does not match the update')
    for _ in range(60):
        processes = owned_processes(root, prefix)
        core_loaded = False
        for pid in processes:
            try:
                core_loaded |= '/Foundation.dll' in Path(f'/proc/{pid}/maps').read_text()
            except OSError:
                pass
        windows = json.loads(subprocess.check_output(['hyprctl', 'clients', '-j'], timeout=5))
        visible = any(w.get('class', '').lower() == 'spark desktop.exe' and
                      w.get('pid') in processes and not w.get('hidden', False) and
                      w.get('mapped', True) for w in windows)
        runtime_version = log is None or (Path(log).is_file() and version in Path(log).read_text(errors='replace'))
        if visible and core_loaded and runtime_version:
            time.sleep(2)
            if set(processes) & set(owned_processes(root, prefix)):
                return
        time.sleep(1)
    raise ValueError('Startup was not confirmed. Check the saved launch log.')


def prune(archive, backup, stage, keep):
    """Keep the current backup and update directory and the newest older ones, up to keep each."""
    if not (Path(backup).is_dir() and Path(stage).is_dir()):
        raise ValueError('The current update directory is missing. No backups were removed.')
    removed = 0
    for kind, current in (('pre-update', Path(backup)), ('update', Path(stage))):
        # Never follow a symbolic link out of the archive.
        older = [path for path in Path(archive).iterdir()
                 if path != current and UPDATER_DIRS[kind].fullmatch(path.name)
                 and path.is_dir() and not path.is_symlink()]
        # An attempt that stopped before the copy leaves an empty backup. Remove those first.
        older.sort(key=lambda path: (any(path.iterdir()), path.stat().st_mtime), reverse=True)
        for path in older[int(keep) - 1:]:
            shutil.rmtree(path)
            removed += 1
    return removed


def main():
    command, *args = sys.argv[1:]
    if command == 'check':
        print(json.dumps(check(args[0])))
    elif command == 'version':
        print(installed_version(args[0]))
    elif command == 'missing':
        print('\n'.join(missing_entries(*args)), end='')
    elif command == 'verify':
        verify_imports(args[0])
    elif command == 'startup':
        startup(*args)
    elif command == 'stop-helpers':
        stop_helpers(*args)
    elif command == 'stop-main':
        stop_main(*args)
    elif command == 'wait-stopped':
        wait_stopped(*args)
    elif command == 'prune':
        removed = prune(*args)
        if removed:
            print(f'Removed {removed} older backups and update directories from archive/.')
    else:
        raise ValueError('Unsupported update command')


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        sys.exit(f'error: {error}')
    except (OSError, KeyError, TypeError, struct.error, ET.ParseError, subprocess.SubprocessError):
        sys.exit('error: Spark update check failed. No account data was printed.')
