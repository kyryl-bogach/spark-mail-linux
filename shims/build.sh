#!/usr/bin/env bash
# Build the two Foundation.dll compatibility shims as PE DLLs.
#
# Requires clang and a PE-capable ld (Arch: pacman -S clang llvm binutils).
# The shims link against Wine's own PE import libraries, so a mingw-w64
# toolchain is not needed.
#
# Set WINE_PE_LIBDIR if the search below does not find those libraries.
# Set OUT_DIR to choose the output directory (default: this directory).
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
out=${OUT_DIR:-$here}
target=x86_64-w64-windows-gnu

find_pe_libdir() {
  local candidate
  for candidate in \
    "${WINE_PE_LIBDIR:-}" \
    "$here/../runtime/usr/lib/wine/x86_64-windows" \
    /usr/lib/wine/x86_64-windows \
    /opt/wine-stable/lib/wine/x86_64-windows
  do
    if [ -n "$candidate" ] && [ -f "$candidate/libkernel32.a" ]; then
      (cd "$candidate" && pwd)
      return 0
    fi
  done
  echo "error: no Wine PE import libraries found. Set WINE_PE_LIBDIR." >&2
  return 1
}

libdir=$(find_pe_libdir)
mkdir -p "$out"

# sprkenv.dll replaces Foundation's USERENV import. The .def file names both
# exports and forwards GetProfilesDirectoryW to Wine's own userenv.
# This DLL has no DllMain on purpose, so the linker reports no entry symbol.
# A zero entry point is valid for a DLL; the loader simply calls nothing.
clang --target="$target" -nostdlib -shared \
  -L "$libdir" \
  -o "$out/sprkenv.dll" \
  "$here/profile-shim.c" "$here/profile-shim.def" \
  -lkernel32 2>&1 | grep -v 'cannot find entry symbol DllMainCRTStartup' || true

# sprkiphl.dll replaces Foundation's IPHLPAPI import. It imports nothing, so
# it declares its own entry point and links against no import library.
clang --target="$target" -nostdlib -shared \
  -o "$out/sprkiphl.dll" \
  "$here/adapter-shim.c"

for dll in sprkenv.dll sprkiphl.dll; do
  test -f "$out/$dll" || { echo "error: $dll was not produced" >&2; exit 1; }
done
echo "Built $out/sprkenv.dll and $out/sprkiphl.dll"
echo "Copy both next to 'Spark Desktop.exe', then run the patch scripts."
