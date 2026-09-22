# Omarchy plugin

This optional plugin shows the output of `bin/spark emails` in an Omarchy popup.
It includes read and unread emails from the unified inbox.
The command returns its default first page, currently up to 50 emails.

The bar shows a mail icon without a count.
The popup shows each sender, subject, and date as plain text.
The CLI can truncate sender names and subjects before the plugin receives them.

Click the icon to show the inbox. Click a row or **Open Spark** to focus Spark.
If Spark has no window, the helper calls the existing launcher.
Middle-click the icon to open Spark directly. Press Escape to close the popup.

A row does not open the selected email.
The list command does not return email links, and this plugin does not fetch message bodies to obtain them.
The plugin does not change email state.

## Install

This integration requires Omarchy and Hyprland. The main installer does not install it.

Run this command from the repository root:

```bash
./integrations/omarchy/install.sh
```

The installer links this directory into the user's Omarchy plugin directory.
It enables `local.spark-mail` before the tray in the right section.
It saves the previous shell configuration and any existing plugin under `archive/`.

Keep this repository in place after installation.
Run the installer again if you move the repository.

## Runtime

Spark Desktop must run, and Spark CLI access must permit account reads.
The plugin refreshes every 60 seconds and when the popup opens.
If Spark is closed, the plugin shows that state without a background launch.
If CLI access is enabled but no account is shared, the plugin points back to
Spark's AI Agents settings instead of reporting an empty inbox.

The helper reuses `bin/spark`, its Wine settings, optional Bubblewrap mounts, and notification guard.
Email output stays in memory. The helper suppresses CLI diagnostics.
A failed refresh clears the list and shows an error.

The open action requires Hyprland.
It checks the window class and Wine prefix before it focuses a window.
If no window matches, it calls `run-spark.sh` with output disabled.

## Checks

Run the parser tests and manifest check:

```bash
python3 -m unittest discover -s integrations/omarchy -p 'test_*.py'
omarchy plugin validate "$PWD/integrations/omarchy"
```

The local checks confirm a live inbox read, popup activation, and focus of the existing Spark window.
The cold launch path and selected-email navigation remain unverified.

## Disable

```bash
omarchy plugin disable local.spark-mail
```
