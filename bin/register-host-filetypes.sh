#!/usr/bin/env bash
# Register unassociated document attachments with Wine's Unix file opener.
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
  if wine_tool 'C:\windows\system32\reg.exe' query "HKCR\\.$extension" /ve \
       </dev/null >/dev/null 2>&1; then
    continue
  fi
  printf '\n[HKEY_CLASSES_ROOT\\.%s]\n@="sparkhostofficefile"\n"Content Type"="%s"\n' \
    "$extension" "$mime_type" >> "$registry_file"
done

wine_tool 'C:\windows\regedit.exe' /S "$registry_file" </dev/null
