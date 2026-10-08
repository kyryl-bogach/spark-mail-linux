#!/usr/bin/env bash
# Register unassociated attachments with Wine's Unix file opener.
#
# winebrowser.exe hands files to the xdg-open on Wine's PATH, which the
# launcher points at bin/host-tools, so the host desktop opens them.
#
# Wine tools run through run-spark.sh, so they use the launcher's prefix,
# mounts, DLL overrides, and wineserver. A running Spark sees the change.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

wine_tool() {
  local tool=$1
  shift
  SPARK_ROOT=$root SPARK_EXE="$tool" SPARK_DEBUG=-all \
    SPARK_NOTIFY=0 SPARK_CLOSE_TRAY=0 SPARK_IMAGE_BRIDGE=0 \
    "$root/run-spark.sh" "$@"
}

mkdir -p "$root/tmp"
stage=$(mktemp -d "$root/tmp/host-filetypes.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT
registry_file=$stage/fallback.reg
existing=$stage/existing.reg
cat "$root/share/host-filetypes.reg" > "$registry_file"

# Export once to read default values without localized query labels.
if ! windows_stage=$(wine_tool 'C:\windows\system32\winepath.exe' -w "$stage" </dev/null 2>/dev/null | tr -d '\r') || [ -z "$windows_stage" ]; then
  echo 'error: cannot resolve the registry export path. No associations were changed.' >&2
  exit 1
fi
if ! wine_tool 'C:\windows\system32\reg.exe' export HKCR "$windows_stage\\existing.reg" /y </dev/null >/dev/null 2>&1; then
  echo 'error: cannot read Wine file associations. No associations were changed.' >&2
  exit 1
fi
office_types=(
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
# Other common attachment types. Wine ships no handler for them, so a click
# shows an error without this fallback.
document_types=(
  'pdf:application/pdf'
  'txt:text/plain'
  'rtf:application/rtf'
  'md:text/markdown'
  'json:application/json'
  'xml:application/xml'
  'png:image/png'
  'jpg:image/jpeg'
  'jpeg:image/jpeg'
  'gif:image/gif'
  'webp:image/webp'
  'bmp:image/bmp'
  'tif:image/tiff'
  'tiff:image/tiff'
  'svg:image/svg+xml'
  'heic:image/heic'
  'zip:application/zip'
  '7z:application/x-7z-compressed'
  'rar:application/vnd.rar'
  'gz:application/gzip'
  'ics:text/calendar'
  'vcf:text/vcard'
  'eml:message/rfc822'
  'mp3:audio/mpeg'
  'm4a:audio/mp4'
  'wav:audio/wav'
  'mp4:video/mp4'
  'mov:video/quicktime'
)
python3 - "$existing" "$registry_file" "${office_types[@]}" -- "${document_types[@]}" <<'PYTHON'
from pathlib import Path
import re
import sys

raw = Path(sys.argv[1]).read_bytes()
text = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
if not text.startswith(('Windows Registry Editor Version 5.00', 'REGEDIT4')):
    raise SystemExit('error: unsupported registry export. No associations were changed.')
associated = set()
extension = None
for line in text.splitlines():
    if line.startswith('['):
        match = re.fullmatch(r'\[HKEY_CLASSES_ROOT\\\.([^\\]+)\]', line, re.IGNORECASE)
        extension = match[1].lower() if match else None
    elif extension and line.startswith('@=') and line[2:].strip() not in ('""', '-'):
        associated.add(extension)

types = sys.argv[3:]
separator = types.index('--')
with Path(sys.argv[2]).open('a') as output:
    for handler, entries in (('sparkhostofficefile', types[:separator]),
                             ('sparkhostfile', types[separator + 1:])):
        for entry in entries:
            extension, mime = entry.split(':', 1)
            if extension not in associated:
                output.write(f'\n[HKEY_CLASSES_ROOT\\.{extension}]\n@="{handler}"\n"Content Type"="{mime}"\n')
PYTHON

wine_tool 'C:\windows\regedit.exe' /S "$registry_file" </dev/null
