#!/usr/bin/env bash
# Install Spark Desktop for Windows into this repository.
#
# Usage: ./install.sh /path/to/Spark.exe
#
# The script checks dependencies, extracts the NSIS installer, verifies that
# the extraction is complete, builds the shims, patches Foundation.dll, and
# registers the app launcher and login handler. Nothing is installed
# system-wide except those desktop entries.
#
# Get the installer from the official release notes:
#   https://sparkmailapp.com/spark3/win/changelog
# Confirm the version and URL there. Do not trust a hardcoded link.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
app=$root/app

installer=${1:-}
if [ -z "$installer" ]; then
  echo "usage: $0 /path/to/Spark.exe" >&2
  echo "Download it from https://sparkmailapp.com/spark3/win/changelog" >&2
  exit 2
fi
[ -f "$installer" ] || { echo "error: no such file: $installer" >&2; exit 1; }

# --- Preflight ---------------------------------------------------------------

# command:package pairs for Arch Linux. Wine may come from the bundled
# runtime instead of the system package.
deps=$'bwrap:bubblewrap\npython3:python\nbsdtar:libarchive\nclang:clang\nobjdump:binutils\nnotify-send:libnotify\nupdate-desktop-database:desktop-file-utils\nxdg-mime:xdg-utils'
missing=
while IFS=: read -r cmd pkg; do
  [ -z "$cmd" ] && continue
  if ! command -v "$cmd" >/dev/null 2>&1; then
    missing="$missing  $cmd (pacman -S $pkg)"$'\n'
  fi
done <<< "$deps"
if ! command -v wine >/dev/null 2>&1 && [ ! -x "$root/runtime/usr/bin/wine" ]; then
  missing="$missing  wine (pacman -S wine)"$'\n'
fi
if [ -n "$missing" ]; then
  echo "error: missing dependencies:" >&2
  printf '%s' "$missing" >&2
  exit 1
fi

# --- Validate the installer --------------------------------------------------

# A Windows installer starts with the MZ header. bsdtar rejects anything it
# cannot list, so a bad file fails here and not after a half-empty app/.
if [ "$(head -c 2 "$installer")" != "MZ" ]; then
  echo "error: $installer is not a Windows executable." >&2
  exit 1
fi
if ! bsdtar -tf "$installer" >/dev/null 2>&1; then
  echo "error: bsdtar cannot read $installer as an NSIS archive." >&2
  exit 1
fi

# --- Extract -----------------------------------------------------------------

# Refuse to overwrite an existing install. Account state lives outside app/,
# so a repair can safely delete it. Updates follow the procedure in AGENTS.md.
if [ -e "$app/Spark Desktop.exe" ]; then
  echo "error: app/ already contains an installation." >&2
  echo "To repair a broken install, remove app/ and run this script again." >&2
  echo "To update Spark, follow the update procedure in AGENTS.md." >&2
  exit 1
fi

mkdir -p "$app"
bsdtar -xf "$installer" -C "$app"

# --- Verify extraction completeness ------------------------------------------

# libarchive can stop silently partway through an NSIS archive. The failure
# then surfaces later as 'Error loading V8 startup snapshot file' or
# 'Cannot find module @readdle/sparkcore-win'. Compare the archive manifest
# against the extracted tree and recover missing entries once with -T.
manifest=$(mktemp)
missing_list=$(mktemp)
trap 'rm -f "$manifest" "$missing_list"' EXIT

bsdtar -tf "$installer" > "$manifest"

find_missing() {
  : > "$missing_list"
  local entry norm
  while IFS= read -r entry; do
    # Normalize separators and leading ./ so both sides compare equal.
    norm=${entry//\\//}
    norm=${norm#./}
    norm=${norm%/}
    [ -z "$norm" ] && continue
    [ -e "$app/$norm" ] || printf '%s\n' "$entry" >> "$missing_list"
  done < "$manifest"
}

find_missing
if [ -s "$missing_list" ]; then
  count=$(wc -l < "$missing_list")
  echo "warning: extraction missed $count entries. Recovering them now." >&2
  bsdtar -xf "$installer" -C "$app" -T "$missing_list"
  find_missing
fi
if [ -s "$missing_list" ]; then
  echo "error: extraction is still incomplete after one recovery pass." >&2
  echo "The first missing entries:" >&2
  head -5 "$missing_list" >&2
  exit 1
fi

for required in \
  "Spark Desktop.exe" \
  "resources.pak" \
  "snapshot_blob.bin" \
  "v8_context_snapshot.bin" \
  "resources/app.asar.unpacked/node_modules/@readdle/sparkcore-win/package.json"
do
  [ -e "$app/$required" ] || { echo "error: missing required file: app/$required" >&2; exit 1; }
done

# --- Build, patch, register --------------------------------------------------

OUT_DIR="$app" "$root/shims/build.sh"
python3 "$root/shims/patch-foundation.py"
python3 "$root/shims/patch-iphlpapi.py"
"$root/install-handler.sh"

echo
echo "Install complete. Launch Spark with:"
echo "  $root/run-spark.sh"
echo "If the GPU process fails on this host, use:"
echo "  $root/run-spark.sh --disable-gpu"
