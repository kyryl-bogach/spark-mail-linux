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
#   SPARK_APP        application directory (default: SPARK_ROOT/app)
#   SPARK_PREFIX     Wine prefix (default: SPARK_ROOT/prefix)
#   SPARK_WINE       wine binary (default: bundled runtime, else wine in PATH)
#   SPARK_DEBUG      WINEDEBUG value
#   SPARK_OVERRIDES  WINEDLLOVERRIDES value
#   SPARK_EXE        Windows executable to run
#   SPARK_CONTAINER  1 for Bubblewrap (default), 0 for direct Wine
set -euo pipefail

root=${SPARK_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}
config=${SPARK_CONFIG:-$root/spark.local.env}
if [ -f "$config" ]; then
  # This optional file is local, ignored by Git, and trusted like the launcher.
  # shellcheck source=/dev/null
  source "$config"
fi
app=$(readlink -f "${SPARK_APP:-$root/app}")
prefix=$(readlink -f "${SPARK_PREFIX:-$root/prefix}")
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

# A Spark update can replace Foundation.dll while leaving old shims beside the
# executable. Reject any vulnerable native imports that still need redirecting.
# Older Spark builds do not import every affected DLL, so require a shim only
# when Foundation actually references its replacement.
foundation=$app/resources/app.asar.unpacked/node_modules/@readdle/sparkcore-win/bin/Release/SparkCore.bundle/Foundation.dll
if [ -f "$foundation" ]; then
  if grep -qai 'USERENV.dll' "$foundation"; then
    echo 'error: Foundation.dll still imports USERENV.dll.' >&2
    echo "A Spark update probably reverted the patches. Reapply them:" >&2
    echo "  python3 $root/shims/patch-foundation.py" >&2
    echo "  python3 $root/shims/patch-iphlpapi.py" >&2
    exit 1
  fi
  for replacement in sprkenv.dll sprkiphl.dll; do
    if grep -qa "$replacement" "$foundation" && [ ! -f "$app/$replacement" ]; then
      echo "error: missing $app/$replacement. Run shims/build.sh." >&2
      exit 1
    fi
  done
  # The adapter crash affects the newer Foundation build that also imports
  # USERENV. Older builds have no USERENV dependency and can keep IPHLPAPI.
  if grep -qa 'sprkenv.dll' "$foundation" && grep -qai 'IPHLPAPI.DLL' "$foundation"; then
    echo 'error: Foundation.dll still imports IPHLPAPI.DLL.' >&2
    echo "Run: python3 $root/shims/patch-iphlpapi.py" >&2
    exit 1
  fi
fi

mkdir -p "$tmp_dir" "$home_overlay"

# Spark's Windows toast notifications do not render under Wine. This watcher
# bridges new mail to notify-send. The trap covers every exit path, including
# a nonzero wine exit under 'set -e' and an interrupt.
# Set SPARK_NOTIFY=0 for short-lived invocations such as the Spark CLI.
watcher=
tray_closer=
cleanup() {
  [ -z "$watcher" ] || kill "$watcher" 2>/dev/null || true
  [ -z "$tray_closer" ] || kill "$tray_closer" 2>/dev/null || true
}
trap cleanup EXIT
if [ "${SPARK_NOTIFY:-1}" != 0 ] && { [ -x "$root/bin/mail-notify.py" ] || [ -f "$root/bin/mail-notify.py" ]; }; then
  SPARK_ROOT=$root SPARK_PREFIX=$prefix python3 "$root/bin/mail-notify.py" &
  watcher=$!
fi

# Wine needs explorer.exe while Spark initializes, but its /desktop process
# later exposes the tray icon as a tiny standalone window. Close only that
# helper, and only after Spark's renderer exists in this exact Wine prefix.
if [ "${SPARK_CLOSE_TRAY:-1}" != 0 ] && [ -f "$root/bin/close-tray.py" ]; then
  python3 "$root/bin/close-tray.py" "$prefix" &
  tray_closer=$!
fi

status=0
overrides=${SPARK_OVERRIDES:-winemenubuilder.exe=d;powershell.exe,pwsh.exe=d;mscoree=d;mshtml=d;ucrtbase,concrt140,msvcp140,msvcp140_1,msvcp140_2,msvcp140_atomic_wait,msvcp140_codecvt_ids,vcamp140,vccorlib140,vcomp140,vcruntime140,vcruntime140_1,vcruntime140_threads=n,b}
debug=${SPARK_DEBUG:--all}
if [ "${SPARK_CONTAINER:-1}" = 0 ]; then
  (
    cd "$app"
    export SPARK_ROOT=$root WINEPREFIX=$prefix WINEDLLOVERRIDES=$overrides WINEDEBUG=$debug
    "$wine" "$exe" "$@"
  ) || status=$?
else
  bwrap \
    --ro-bind / / \
    --dev-bind /dev /dev \
    --proc /proc \
    --bind "$home_overlay" "$HOME" \
    --bind "$root" "$root" \
    --bind "$prefix" "$prefix" \
    --bind "$app" "$app" \
    --bind "$tmp_dir" /tmp \
    --ro-bind /tmp/.X11-unix /tmp/.X11-unix \
    --setenv WINEPREFIX "$prefix" \
    --setenv SPARK_ROOT "$root" \
    --setenv WINEDLLOVERRIDES "$overrides" \
    --setenv WINEDEBUG "$debug" \
    --chdir "$app" \
    "$wine" "$exe" "$@" || status=$?
fi

exit "$status"
