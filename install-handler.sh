#!/usr/bin/env bash
# Register Spark's launcher and URL handler with the host desktop.
#
# Browser sign-in and Spark links use custom schemes. Without this handler the
# callback or deep-link URL has nowhere to go.
set -euo pipefail

root=${SPARK_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}
auth_template=$root/share/spark-mail-linux-auth.desktop.in
launcher_template=$root/share/spark-mail-linux.desktop.in
dest_dir=${XDG_DATA_HOME:-$HOME/.local/share}/applications
auth_dest=$dest_dir/spark-mail-linux-auth.desktop
launcher_dest=$dest_dir/spark-mail-linux.desktop

[ -f "$auth_template" ] || { echo "error: missing $auth_template" >&2; exit 1; }
[ -f "$launcher_template" ] || { echo "error: missing $launcher_template" >&2; exit 1; }

mkdir -p "$dest_dir"
escaped_root=${root//\\/\\\\}
escaped_root=${escaped_root//&/\\&}
escaped_root=${escaped_root//|/\\|}
sed "s|@SPARK_ROOT@|$escaped_root|g" "$auth_template" > "$auth_dest"
sed "s|@SPARK_ROOT@|$escaped_root|g" "$launcher_template" > "$launcher_dest"
command -v update-desktop-database >/dev/null && update-desktop-database "$dest_dir" || true

echo "Installed $launcher_dest"
echo "Installed $auth_dest"
echo "Registered schemes:"
while IFS= read -r mime; do
  [ -n "$mime" ] || continue
  xdg-mime default "$(basename "$auth_dest")" "$mime"
  echo "  ${mime#x-scheme-handler/}"
done < <(sed -n 's/^MimeType=//p' "$auth_dest" | tr ';' '\n')
