#!/usr/bin/env python3
"""Open a local file with the host desktop, outside Wine's home overlay.

winebrowser.exe passes attachments to xdg-open as file:// URLs. Inside the
container, xdg-open cannot start Flatpak handlers and gives native handlers a
throwaway home. The desktop portal's OpenFile method does not resolve
descriptors that point into the container's extra mounts either. So this
helper asks the user's service manager to run the host xdg-open as a
transient service, which starts outside the container with the host defaults.

The launcher exports SPARK_CONTAINER_HOME, SPARK_CONTAINER_TMP, and
SPARK_DOWNLOADS_DIR so container paths map back to host paths.
"""
import os
import subprocess
import sys
from urllib.parse import unquote, urlsplit


def file_path(argument):
    """Return the path for a file:// URL or an absolute path to a file, else None."""
    if any(ord(char) < 32 or ord(char) == 127 for char in argument):
        return None
    if argument.startswith('/'):
        path = argument
    else:
        try:
            parsed = urlsplit(argument)
        except ValueError:
            return None
        if parsed.scheme.lower() != 'file' or parsed.netloc not in ('', 'localhost'):
            return None
        path = unquote(parsed.path)
    if not path.startswith('/') or not os.path.isfile(path):
        return None
    return path


def host_path(path, environ):
    """Map a container path to the host path the launcher mounted there."""
    home = environ.get('HOME', '')
    mounts = []
    if environ.get('SPARK_CONTAINER_TMP'):
        mounts.append(('/tmp', environ['SPARK_CONTAINER_TMP']))
    if home and environ.get('SPARK_DOWNLOADS_DIR'):
        mounts.append((home + '/Downloads', environ['SPARK_DOWNLOADS_DIR']))
    if home and environ.get('SPARK_CONTAINER_HOME'):
        mounts.append((home, environ['SPARK_CONTAINER_HOME']))
    for mount, host in mounts:
        if path == mount or path.startswith(mount + '/'):
            return host + path[len(mount):]
    return path


def open_file(path):
    subprocess.run(
        ['systemd-run', '--user', '--collect', '--quiet',
         '--description=Spark host open', '--', 'xdg-open', path],
        check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)


def main():
    path = file_path(sys.argv[1]) if len(sys.argv) == 2 else None
    if path is None:
        sys.exit('error: expected one existing file as a file:// URL or an absolute path.')
    try:
        open_file(host_path(path, os.environ))
    except Exception:
        # Attachment names can identify messages. Report no request details.
        sys.exit('error: the host service manager did not start xdg-open. Check systemd-run.')


if __name__ == '__main__':
    main()
