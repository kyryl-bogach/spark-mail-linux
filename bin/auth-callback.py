#!/usr/bin/env python3
"""Forward a Spark OAuth callback URL from the host into the running app.

Google sign-in opens the host browser, so the host must own the callback URL
schemes. This handler validates the scheme, then re-runs run-spark.sh with
--win-open-url.

Running the full launcher again is deliberate. The callback needs the same
Bubblewrap mounts to reach the running wineserver over the shared /tmp. Wine
then joins that server, and Electron's single-instance handler delivers the URL
to the primary process. No second app instance starts.

The log records the timestamp and the scheme only. The URL carries the
authorization code and is never written to disk.
"""
import os
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = os.environ.get('SPARK_ROOT') or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))

# Spark's own public OAuth client identifiers, read from the installed app.
# A future Spark version can change these. See docs/investigation.md.
ALLOWED_SCHEMES = {
    'com.googleusercontent.apps.681834923750-3p9205dgnfbq0s196910u38tmn61ehc2',
    'com.readdle.spark.auth-bridge.desktop-dist',
    'oauth.redirect.com.readdle.smartmail',
}


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: auth-callback.py <callback-url>')
    scheme = urlsplit(sys.argv[1]).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        sys.exit('Unsupported Spark callback scheme')
    with open(os.path.join(ROOT, 'auth-callback.log'), 'a') as log:
        log.write('%s scheme=%s\n' % (time.strftime('%F %T'), scheme))
    env = dict(os.environ, SPARK_ROOT=ROOT, SPARK_DEBUG='-all')
    result = subprocess.run(
        ['/usr/bin/env', 'bash', os.path.join(ROOT, 'run-spark.sh'),
         '--win-open-url', sys.argv[1]],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
