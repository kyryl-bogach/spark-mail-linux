#!/usr/bin/env python3
"""Redirect Foundation's USERENV import to sprkenv.dll.

Wine's GetAllUsersProfileDirectoryW is a stub that leaves the requested length
at zero. Foundation decrements that value unchecked, so it underflows and
attempts an 8 GB copy. See docs/investigation.md.

The new name has the same length as the old one, so the patch needs no
relocation work. The script saves Foundation.original.dll before it writes.
"""
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get('SPARK_ROOT') or Path(__file__).resolve().parents[1])
TARGET = ROOT / ('app/resources/app.asar.unpacked/node_modules/@readdle'
                 '/sparkcore-win/bin/Release/SparkCore.bundle/Foundation.dll')
BACKUP = ROOT / 'Foundation.original.dll'
OLD, NEW = b'USERENV.dll\0', b'sprkenv.dll\0'

assert len(OLD) == len(NEW), 'import names must be the same length'

if not TARGET.exists():
    sys.exit('error: %s not found. Extract the installer into app/ first.' % TARGET)

data = TARGET.read_bytes()
count = data.count(OLD)
if count == 0 and data.count(NEW) == 1:
    sys.exit('Already patched; nothing to do.')
if count != 1:
    sys.exit('error: expected exactly one USERENV import, found %d' % count)
if BACKUP.exists():
    sys.exit('error: %s already exists. Inspect it before patching.' % BACKUP)

BACKUP.write_bytes(data)
TARGET.write_bytes(data.replace(OLD, NEW, 1))
print('Redirected Foundation USERENV import to sprkenv.dll')
print('Original saved as %s' % BACKUP)
