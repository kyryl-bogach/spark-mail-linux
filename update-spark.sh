#!/usr/bin/env bash
# Prepare, back up, replace, and restart this Spark installation.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
config=${SPARK_CONFIG:-$root/spark.local.env}
if [ -f "$config" ]; then source "$config"; fi
app=$(readlink -m "${SPARK_APP:-$root/app}")
prefix=$(readlink -m "${SPARK_PREFIX:-$root/prefix}")
metadata=$root/bin/spark-update.py
case ${1:-} in
  --check) python3 "$metadata" check "$app"; exit ;;
  '') ;;
  *) echo "usage: $0 [--check]" >&2; exit 2 ;;
esac
# Moving an adopted installation requires a separate update procedure.
if [ "$app" != "$root/app" ] || [ "$prefix" != "$root/prefix" ] ||
   [ -L "$root/app" ] || [ -L "$root/prefix" ]; then
  echo 'error: automatic updates require the repository app and prefix directories.' >&2
  exit 1
fi
for command in python3 curl bsdtar clang objdump flock systemd-run systemctl timeout hyprctl; do
  command -v "$command" >/dev/null || { echo "error: missing $command" >&2; exit 1; }
done
wine=${SPARK_WINE:-}
if [ -z "$wine" ]; then
  if [ -x "$root/runtime/usr/bin/wine" ]; then wine=$root/runtime/usr/bin/wine
  else wine=$(command -v wine || true); fi
fi
[ -x "$wine" ] && [ -x "$(dirname "$(readlink -f "$wine")")/wineserver" ] || {
  echo 'error: the selected Wine runtime must include wineserver.' >&2; exit 1;
}
mkdir -p "$root/tmp" "$root/archive"
exec 8>"$root/tmp/update.lock"
flock -n 8 || { echo 'error: a Spark update is already active.' >&2; exit 1; }
release=$(python3 "$metadata" check "$app")
readarray -t fields < <(python3 -c 'import json,sys; r=json.load(sys.stdin); print(r["available"]); print(r["installed"]); print(r["version"]); print(r["url"]); print(r["size"])' <<< "$release")
if [ "${fields[0]}" = False ]; then
  echo "Spark ${fields[1]} is current."
  exit 0
fi
version=${fields[2]}
echo "Prepare Spark ${fields[1]} -> $version"
stage=$(mktemp -d "$root/archive/update-$version-XXXXXX")
printf '%s\n' "$release" > "$stage/release.json"
chmod 700 "$stage"
curl --proto '=https' --proto-redir '=https' -fL --retry 3 "${fields[3]}" -o "$stage/Spark.exe"
[ "$(stat -c %s "$stage/Spark.exe")" = "${fields[4]}" ] || { echo 'error: installer size mismatch.' >&2; exit 1; }
[ "$(head -c 2 "$stage/Spark.exe")" = MZ ] || { echo 'error: installer is not a Windows executable.' >&2; exit 1; }
mkdir "$stage/app"
# Validate archive paths before extraction. Recover libarchive's partial extraction once.
python3 "$metadata" missing "$stage/Spark.exe" "$stage/app" > "$stage/missing"
bsdtar -xf "$stage/Spark.exe" -C "$stage/app"
python3 "$metadata" missing "$stage/Spark.exe" "$stage/app" > "$stage/missing"
if [ -s "$stage/missing" ]; then
  bsdtar -xf "$stage/Spark.exe" -C "$stage/app" -T "$stage/missing"
  python3 "$metadata" missing "$stage/Spark.exe" "$stage/app" > "$stage/missing"
fi
[ ! -s "$stage/missing" ] || { echo 'error: extraction is incomplete.' >&2; exit 1; }
[ "$(python3 "$metadata" version "$stage/app")" = "$version" ] || { echo 'error: extracted version mismatch.' >&2; exit 1; }
OUT_DIR="$stage/app" "$root/shims/build.sh"
SPARK_ROOT="$stage" python3 "$root/shims/patch-foundation.py"
SPARK_ROOT="$stage" python3 "$root/shims/patch-iphlpapi.py"
python3 "$metadata" verify "$stage/app"
# Confirm that the user service manager is available before stopping Spark.
systemctl --user show-environment >/dev/null
backup=$(mktemp -d "$root/archive/pre-update-$version-XXXXXX")
chmod 700 "$backup"
control() {
  SPARK_UPDATE_CONTROL=1 SPARK_NOTIFY=0 SPARK_CLOSE_TRAY=0 SPARK_IMAGE_BRIDGE=0 \
    SPARK_DEBUG=-all timeout 20 "$root/run-spark.sh" "$@" 8>&- 9>&-
}
# Drain existing launcher calls after Spark stops. New calls are already blocked.
exec 9>"$root/tmp/update-maintenance.lock"
moved=0
replaced=0
cleanup() {
  local status=$?
  trap - EXIT
  if [ "$status" != 0 ] && [ "$moved" = 1 ]; then
    if [ "$replaced" = 1 ]; then mv "$root/app" "$stage/failed-app"; fi
    mv "$backup/app" "$root/app"
    if [ -f "$backup/Foundation.original.dll" ]; then
      cp -a "$backup/Foundation.original.dll" "$root/Foundation.original.dll"
    else
      rm -f "$root/Foundation.original.dll"
    fi
    echo "The previous application was restored. Backup: $backup" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo 'Spark will stop for the backup and restart after the update.'
SPARK_EXE='C:\windows\system32\taskkill.exe' control /IM 'Spark Desktop.exe' > "$stage/stop.log" 2>&1 || true
sleep 3
python3 "$metadata" stop-main "$root" "$prefix"
python3 "$metadata" stop-helpers "$root" "$prefix"
# Use this prefix's Wine server and the launcher's exact Bubblewrap mounts.
# Wine returns nonzero if the graceful quit already stopped its server.
# The wait and process checks below still require complete shutdown.
SPARK_WINESERVER=1 control -k >> "$stage/stop.log" 2>&1 || true
SPARK_WINESERVER=1 timeout 20 env SPARK_UPDATE_CONTROL=1 SPARK_NOTIFY=0 SPARK_CLOSE_TRAY=0 \
  SPARK_IMAGE_BRIDGE=0 SPARK_DEBUG=-all "$root/run-spark.sh" -w >> "$stage/stop.log" 2>&1 8>&- 9>&-
python3 "$metadata" wait-stopped "$root" "$prefix"
timeout 20 flock -x 9
cp -a --reflink=auto "$prefix" "$root/test-home" "$backup/"
for state in Foundation.original.dll mail-notify.state mail-notify.lock; do
  if [ -f "$root/$state" ]; then cp -a "$root/$state" "$backup/"; fi
done
mv "$root/app" "$backup/app"
moved=1
mv "$stage/app" "$root/app"
replaced=1
cp "$stage/Foundation.original.dll" "$root/Foundation.original.dll"
python3 "$root/shims/patch-foundation.py"
python3 "$root/shims/patch-iphlpapi.py"
python3 "$metadata" verify "$root/app"
# Unlock the application before the service starts.
flock -u 9
service_env=()
for name in SPARK_CONTAINER SPARK_OVERRIDES SPARK_DEBUG SPARK_DOWNLOADS SPARK_NOTIFY SPARK_CLOSE_TRAY SPARK_IMAGE_BRIDGE; do
  if [ "${!name+set}" = set ]; then service_env+=("--setenv=$name=${!name}"); fi
done
systemd-run --user --collect "${service_env[@]}" --unit="spark-update-$(date +%s)-$$" \
  --setenv=SPARK_UPDATE_START=1 --setenv="SPARK_CONFIG=$config" --setenv="SPARK_WINE=$wine" --setenv="DISPLAY=${DISPLAY:-}" --setenv="WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}" \
  --setenv="XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-}" \
  --property="StandardOutput=append:$stage/launch.log" \
  --property="StandardError=append:$stage/launch.log" \
  --working-directory="$root" "$root/run-spark.sh" 8>&- 9>&-
# After launch, preserve newer account state even if a startup check fails.
moved=0
echo "Installed Spark $version. Backup: $backup"
echo "Launch log: $stage/launch.log"
# The startup check reads only process IDs and window classes.
python3 "$metadata" startup "$root" "$prefix" "$version" "$stage/launch.log"
SPARK_UPDATE_CONTROL=1 timeout 30 "$root/bin/spark" --help > "$stage/cli-help.log" 2>&1 8>&- 9>&-
SPARK_UPDATE_CONTROL=1 timeout 30 "$root/bin/spark" --version > "$stage/cli-version.log" 2>&1 8>&- 9>&-
echo 'Startup and CLI help/version checks passed.'
if SPARK_UPDATE_CONTROL=1 timeout 30 "$root/bin/spark" accounts --json > "$stage/cli-accounts.json" 2> "$stage/cli-accounts.log" 8>&- 9>&-; then
  python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print("Read-only account access passed." if r.get("accounts") else "No accounts shared with the CLI.")' "$stage/cli-accounts.json"
else
  echo 'CLI account access was not confirmed. Account permissions were not changed.'
fi
echo 'Mail, calendar, attachment, and notification delivery checks remain separate.'
