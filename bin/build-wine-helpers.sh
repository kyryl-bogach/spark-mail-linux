#!/usr/bin/env bash
# Build the optional Wine helpers outside the extracted Spark app.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
out=$root/.build
# Prefer the bundled runtime so the helpers match the Wine that runs them.
winegcc=$root/runtime/usr/bin/winegcc
[ -x "$winegcc" ] || winegcc=$(command -v winegcc || true)
[ -n "$winegcc" ] || {
  echo 'error: winegcc is required for the Wine helpers.' >&2
  exit 1
}
mkdir -p "$out"
build() {
  local name=$1
  shift
  "$winegcc" -m64 -O2 -Wall -Wextra \
    "$root/bin/$name.c" -o "$out/$name.exe" "$@" -luser32 -lkernel32
  test -x "$out/$name.exe.so"
  echo "Built $out/$name.exe.so"
}
build clipboard-image -lgdiplus -lole32
build window-rescue
