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
registry_file=$(mktemp "$root/tmp/host-filetypes.XXXXXXXX.reg")
trap 'rm -f "$registry_file"' EXIT
cat "$root/share/host-filetypes.reg" > "$registry_file"

# Preserve Windows applications already installed in this prefix. Register
# only types that have no default Wine association. One listing of HKCR
# replaces a reg.exe query per extension.
existing=$(wine_tool 'C:\windows\system32\reg.exe' query 'HKCR' </dev/null 2>/dev/null | tr -d '\r' || true)
has_association() {
  printf '%s\n' "$existing" | grep -qiE "^HKEY_CLASSES_ROOT\\\\\.$1\$"
}
register() {
  local class=$1 filetype extension mime_type
  shift
  for filetype in "$@"; do
    extension=${filetype%%:*}
    mime_type=${filetype#*:}
    has_association "$extension" && continue
    printf '\n[HKEY_CLASSES_ROOT\\.%s]\n@="%s"\n"Content Type"="%s"\n' \
      "$extension" "$class" "$mime_type" >> "$registry_file"
  done
}
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
register sparkhostofficefile "${office_types[@]}"
register sparkhostfile "${document_types[@]}"

wine_tool 'C:\windows\regedit.exe' /S "$registry_file" </dev/null
