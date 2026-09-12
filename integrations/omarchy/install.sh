#!/usr/bin/env bash
# Install the local plugin and preserve the previous shell configuration.
set -euo pipefail
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$source_dir/../.." && pwd)
config=${XDG_CONFIG_HOME:-$HOME/.config}/omarchy
plugin=$config/plugins/local.spark-mail
omarchy plugin validate "$source_dir"
mkdir -p "$root/archive" "$config/plugins"
backup=$(mktemp -d "$root/archive/omarchy-install-XXXXXX")
if [[ -f $config/shell.json ]]; then
  cp -a "$config/shell.json" "$backup/shell.json"
fi
if [[ -e $plugin || -L $plugin ]]; then
  mv "$plugin" "$backup/plugin"
fi
ln -s "$source_dir" "$plugin"
omarchy-shell shell rescanPlugins
omarchy plugin enable local.spark-mail --section right --before omarchy.tray
printf 'Backup: %s\n' "$backup"
