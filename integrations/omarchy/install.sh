#!/usr/bin/env bash
# Install the local plugin and preserve the previous shell configuration.
set -euo pipefail
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$source_dir/../.." && pwd)
config=${XDG_CONFIG_HOME:-$HOME/.config}/omarchy
plugin=$config/plugins/local.spark-mail

wait_for_shell() {
  local attempt
  for attempt in {1..480}; do
    if omarchy-shell shell ping >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo 'omarchy-shell did not become ready' >&2
  return 1
}

omarchy plugin validate "$source_dir"
mkdir -p "$root/archive" "$config/plugins"
backup=$(mktemp -d "$root/archive/omarchy-install-XXXXXX")
if [[ -f $config/shell.json ]]; then
  cp -a "$config/shell.json" "$backup/shell.json"
fi
link_changed=0
if [[ -L $plugin ]] && [[ $(readlink -f "$plugin" 2>/dev/null || true) == "$source_dir" ]]; then
  : # Already linked correctly; avoid an expensive full plugin reload.
elif [[ -e $plugin || -L $plugin ]]; then
  mv "$plugin" "$backup/plugin"
  ln -s "$source_dir" "$plugin"
  link_changed=1
else
  ln -s "$source_dir" "$plugin"
  link_changed=1
fi
if ((link_changed)); then
  wait_for_shell
  # A successful rescan can restart the shell before the IPC client receives
  # its reply. Readiness after the call is the reliable completion signal.
  omarchy-shell shell rescanPlugins || true
  wait_for_shell
fi
omarchy plugin enable local.spark-mail --section right --before omarchy.tray
printf 'Backup: %s\n' "$backup"
