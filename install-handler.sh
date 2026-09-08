#!/usr/bin/env bash
# Register the OAuth callback handler with the host desktop.
#
# Google sign-in opens the host browser. Without this handler the callback URL
# has nowhere to go and login cannot finish.
set -euo pipefail

root=${SPARK_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}
template=$root/share/spark-mail-linux-auth.desktop.in
dest_dir=${XDG_DATA_HOME:-$HOME/.local/share}/applications
dest=$dest_dir/spark-mail-linux-auth.desktop

[ -f "$template" ] || { echo "error: missing $template" >&2; exit 1; }

mkdir -p "$dest_dir"
sed "s|@SPARK_ROOT@|$root|g" "$template" > "$dest"
command -v update-desktop-database >/dev/null && update-desktop-database "$dest_dir" || true

echo "Installed $dest"
echo "Registered schemes:"
sed -n 's/^MimeType=//p' "$dest" | tr ';' '\n' | sed '/^$/d;s|^x-scheme-handler/|  |'
