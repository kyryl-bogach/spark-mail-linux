#!/usr/bin/env bash
# Register unassociated document attachments with Wine's Unix file opener.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
prefix=${SPARK_PREFIX:-$root/prefix}
prefix=$(readlink -f "$prefix")
wine=${SPARK_WINE:-}
if [ -z "$wine" ]; then
  if [ -x "$root/runtime/usr/bin/wine" ]; then
    wine=$root/runtime/usr/bin/wine
  else
    wine=$(command -v wine)
  fi
fi

# A running Spark instance can later write its cached registry state over
# changes made by another Wine process. Require a stopped desktop instance.
if python3 - "$prefix" <<'PY'
from pathlib import Path
import sys

prefix = ('WINEPREFIX=' + sys.argv[1]).encode()
for process in Path('/proc').iterdir():
    if not process.name.isdigit():
        continue
    try:
        environ = (process / 'environ').read_bytes().split(b'\0')
        command = (process / 'cmdline').read_bytes()
    except OSError:
        continue
    if prefix in environ and b'Spark Desktop.exe' in command:
        raise SystemExit(0)
raise SystemExit(1)
PY
then
  echo 'error: quit Spark before registering document associations.' >&2
  exit 1
fi

mkdir -p "$prefix" "$root/test-home" "$root/tmp"

bwrap_args=(
  --ro-bind / /
  --dev-bind /dev /dev
  --proc /proc
  --bind "$root/test-home" "$HOME"
  --bind "$root" "$root"
  --bind "$root/tmp" /tmp
  --ro-bind /tmp/.X11-unix /tmp/.X11-unix
  --setenv WINEPREFIX "$prefix"
  --setenv WINEDEBUG -all
  --chdir "$root"
)

registry_file=$(mktemp "$root/tmp/host-filetypes.XXXXXXXX.reg")
trap 'rm -f "$registry_file"' EXIT
cat "$root/share/host-filetypes.reg" > "$registry_file"

# Preserve Windows applications already installed in this prefix. Register
# only document types that have no default Wine association.
filetypes=(
  'doc:application/msword'
  'docx:application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  'xls:application/vnd.ms-excel'
  'xlsx:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  'ppt:application/vnd.ms-powerpoint'
  'pptx:application/vnd.openxmlformats-officedocument.presentationml.presentation'
  'odt:application/vnd.oasis.opendocument.text'
  'ods:application/vnd.oasis.opendocument.spreadsheet'
  'odp:application/vnd.oasis.opendocument.presentation'
  'csv:text/csv'
  'tsv:text/tab-separated-values'
)
for filetype in "${filetypes[@]}"; do
  extension=${filetype%%:*}
  mime_type=${filetype#*:}
  if bwrap "${bwrap_args[@]}" "$wine" reg query "HKCR\\.$extension" /ve >/dev/null 2>&1; then
    continue
  fi
  printf '\n[HKEY_CLASSES_ROOT\\.%s]\n@="sparkhostofficefile"\n"Content Type"="%s"\n' \
    "$extension" "$mime_type" >> "$registry_file"
done

bwrap "${bwrap_args[@]}" "$wine" regedit /S "$registry_file"
