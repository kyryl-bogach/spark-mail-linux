#!/usr/bin/env python3
"""Redirect Foundation's IPHLPAPI import to sprkiphl.dll.

Wine's GetAdaptersAddresses data trips a Swift nil force-unwrap in
Host._resolveCurrent, which crashes Spark right after login. See
docs/investigation.md.

Foundation imports nothing else from IPHLPAPI, so redirecting the whole
import descriptor is safe. This patch stacks on top of patch-foundation.py,
and Foundation.original.dll stays the only backup.
"""
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get('SPARK_ROOT') or Path(__file__).resolve().parents[1])
TARGET = ROOT / ('app/resources/app.asar.unpacked/node_modules/@readdle'
                 '/sparkcore-win/bin/Release/SparkCore.bundle/Foundation.dll')
OLD, NEW = b'IPHLPAPI.DLL\0', b'sprkiphl.dll\0'

assert len(OLD) == len(NEW), 'import names must be the same length'

if not TARGET.exists():
    sys.exit('error: %s not found. Extract the installer into app/ first.' % TARGET)

data = TARGET.read_bytes()
count = data.count(OLD)
if count == 0 and data.count(NEW) == 1:
    print('Already patched; nothing to do.')
    raise SystemExit(0)
if count != 1:
    sys.exit('error: expected exactly one IPHLPAPI import name, found %d' % count)

TARGET.write_bytes(data.replace(OLD, NEW, 1))
print('Redirected Foundation IPHLPAPI import to sprkiphl.dll')
