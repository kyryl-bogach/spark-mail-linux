#!/usr/bin/env bash
# Launch Spark Desktop under Wine inside a Bubblewrap filesystem container.
#
# The repository directory holds the Wine prefix, the extracted app, and a
# writable home overlay. Nothing is installed system-wide.
#
# Warning: this is filesystem containment, not a security sandbox. The app
# keeps host network and host display access.
#
# Environment overrides:
#   SPARK_ROOT       project directory (default: this script's directory)
#   SPARK_WINE       wine binary (default: bundled runtime, else wine in PATH)
#   SPARK_DEBUG      WINEDEBUG value
#   SPARK_OVERRIDES  WINEDLLOVERRIDES value
#   SPARK_EXE        Windows executable to run
set -euo pipefail

root=${SPARK_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}
app=$root/app
prefix=$root/prefix
home_overlay=$root/test-home
tmp_dir=$root/tmp

wine=${SPARK_WINE:-}
if [ -z "$wine" ]; then
  if [ -x "$root/runtime/usr/bin/wine" ]; then
    wine=$root/runtime/usr/bin/wine
  else
    wine=$(command -v wine || true)
  fi
fi
[ -n "$wine" ] && [ -x "$wine" ] || { echo "error: no wine binary. Set SPARK_WINE." >&2; exit 1; }

exe=${SPARK_EXE:-$app/Spark Desktop.exe}
[ -f "$exe" ] || { echo "error: missing $exe. Extract the installer first." >&2; exit 1; }

# The patched Foundation.dll needs both shims beside the executable. Fail here
# rather than inside an 8 GB memcpy at startup.
for dll in sprkenv.dll sprkiphl.dll; do
  [ -f "$app/$dll" ] || { echo "error: missing $app/$dll. Run shims/build.sh." >&2; exit 1; }
done

# Checking that the shims exist is not enough. A Spark update replaces
# Foundation.dll and leaves the shims untouched, so verify the imports really
# point at them. Without this check the app crashes in an 8 GB memcpy instead.
foundation=$app/resources/app.asar.unpacked/node_modules/@readdle/sparkcore-win/bin/Release/SparkCore.bundle/Foundation.dll
if [ -f "$foundation" ]; then
  for name in sprkenv.dll sprkiphl.dll; do
    if ! grep -qa "$name" "$foundation"; then
      echo "error: Foundation.dll does not import $name." >&2
      echo "A Spark update probably reverted the patches. Reapply them:" >&2
      echo "  python3 $root/shims/patch-foundation.py" >&2
      echo "  python3 $root/shims/patch-iphlpapi.py" >&2
      exit 1
    fi
  done
fi

mkdir -p "$tmp_dir" "$home_overlay"

# Spark's Windows toast notifications do not render under Wine. This watcher
# bridges new mail to notify-send. The trap covers every exit path, including
# a nonzero wine exit under 'set -e' and an interrupt.
# Set SPARK_NOTIFY=0 for short-lived invocations such as the Spark CLI.
watcher=
if [ "${SPARK_NOTIFY:-1}" != 0 ] && { [ -x "$root/bin/mail-notify.py" ] || [ -f "$root/bin/mail-notify.py" ]; }; then
  SPARK_ROOT=$root python3 "$root/bin/mail-notify.py" &
  watcher=$!
  trap '[ -n "$watcher" ] && kill "$watcher" 2>/dev/null' EXIT
fi

status=0
bwrap \
  --ro-bind / / \
  --dev-bind /dev /dev \
  --proc /proc \
  --bind "$home_overlay" "$HOME" \
  --bind "$root" "$root" \
  --bind "$tmp_dir" /tmp \
  --ro-bind /tmp/.X11-unix /tmp/.X11-unix \
  --setenv WINEPREFIX "$prefix" \
  --setenv WINEDLLOVERRIDES "${SPARK_OVERRIDES:-winemenubuilder.exe=d;powershell.exe,pwsh.exe=d;mscoree=d;mshtml=d;ucrtbase,concrt140,msvcp140,msvcp140_1,msvcp140_2,msvcp140_atomic_wait,msvcp140_codecvt_ids,vcamp140,vccorlib140,vcomp140,vcruntime140,vcruntime140_1,vcruntime140_threads=n,b}" \
  --setenv WINEDEBUG "${SPARK_DEBUG:--all}" \
  --chdir "$app" \
  "$wine" "$exe" "$@" || status=$?

exit "$status"
