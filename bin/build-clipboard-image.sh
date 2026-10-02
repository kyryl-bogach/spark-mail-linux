#!/usr/bin/env bash
# Build the Wine clipboard image converter outside the extracted Spark app.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
out=${SPARK_IMAGE_BRIDGE_DIR:-$root/.build}
command -v winegcc >/dev/null 2>&1 || {
  echo 'error: winegcc is required for image clipboard support.' >&2
  exit 1
}
mkdir -p "$out"
winegcc -m64 -O2 -Wall -Wextra \
  "$root/bin/clipboard-image.c" -o "$out/clipboard-image.exe" \
  -lgdiplus -lole32 -luser32 -lkernel32
test -x "$out/clipboard-image.exe.so"
echo "Built $out/clipboard-image.exe.so"
