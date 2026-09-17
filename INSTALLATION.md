# Installation

This document is written for coding agents. Humans can follow it too.
The recommended way to install this project is to give the repository to an
agent and point it at this file.

Scope: Arch Linux and Arch-based systems such as Omarchy. Other distributions
need equivalent packages, which this document does not cover.

## 1. Ask the user first

Resolve these questions with the user before you change anything.
Do not guess the answers.

1. Where should the repository live? Example: `~/Projects/spark-mail-linux`.
2. Is Wine installed? If not, may you run `sudo pacman -S wine`?
3. Does the user have the `Spark.exe` installer? If not, download it yourself
   (see step 2).
4. Which window manager does the user run? Omarchy/Hyprland changes the
   post-install advice (see step 6).
5. Should the `spark` CLI go on PATH through a symlink in `~/.local/bin`?
6. Should the notification watcher stay enabled? One crash is open against it
   (see Caveats). Default to enabled unless the user objects.

Do not ask about `--disable-gpu` up front. Ask only if the first launch fails
with a GPU error (see Caveats).

## 2. Get the installer

The repository contains no Spark code. Download the official Windows installer
from Readdle.

1. Open the release notes: https://sparkmailapp.com/spark3/win/changelog
2. Confirm the current version and the direct download URL on that page.
3. Download the file. Verify it is a Windows executable: the first two bytes
   must be `MZ`.

Never trust a version or URL from memory. Release notes change.

## 3. Install

Clone the repository into the location the user approved. From the repository
root, run:

```bash
./install.sh /path/to/Spark.exe
```

The script checks dependencies, extracts the installer, verifies the
extraction, builds the shims, patches `Foundation.dll`, and registers the
login handler. It stops with a clear error if any step fails.

If you must install manually, run these commands from the repository root:

```bash
sudo pacman -S wine bubblewrap python libarchive clang binutils libnotify desktop-file-utils

mkdir -p app
bsdtar -xf /path/to/Spark.exe -C app
OUT_DIR=app ./shims/build.sh
python3 shims/patch-foundation.py
python3 shims/patch-iphlpapi.py
./install-handler.sh
./run-spark.sh
```

Warning: the manual path has no extraction check. A silent partial extraction
causes confusing errors later (see Caveats). Prefer `./install.sh`.

## 4. Verify the installation

Check every item. A live process alone does not prove a successful startup.

1. Extraction: `install.sh` already verified it. On the manual path, compare
   `bsdtar -tf Spark.exe` against the files under `app/`.
2. Shims: `sprkenv.dll` and `sprkiphl.dll` exist beside `Spark Desktop.exe`.
3. Patches: `objdump -p` on `Foundation.dll` lists imports from `sprkenv.dll`
   and `sprkiphl.dll`. Its path relative to `app/` is
   `resources/app.asar.unpacked/node_modules/@readdle/sparkcore-win/bin/Release/SparkCore.bundle/Foundation.dll`.
4. Desktop integration: `~/.local/share/applications/spark-mail-linux.desktop`
   and `spark-mail-linux-auth.desktop` exist. The first is the visible app
   launcher; the second handles browser sign-in callbacks and Spark deep links.
5. First launch: run `./run-spark.sh`. Confirm a visible, mapped window.
   On Hyprland, `hyprctl clients` must list the Spark window.

Never print message content, OAuth URLs, tokens, or account details from logs
or checks. Report only sanitized evidence.

## 5. First launch and login

Spark opens its onboarding in the app. Google sign-in uses the host browser.
The login handler registered in step 3 forwards the callback into the running
instance.

If Spark was already running before the handler was registered, restart it
once through `./run-spark.sh`.

## 6. Post-install options

Apply only the options the user approved in step 1.

**Spark CLI on PATH:**

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/bin/spark" ~/.local/bin/spark
```

The CLI needs a running Spark Desktop and access enabled under
Settings > AI Agents. See the README for details.

**Hyprland tiling.** Spark's window (class `spark desktop.exe`) can open
floating. Add a rule to the user's files under `~/.config/hypr/`.
Never edit `/usr/share/omarchy/`.

Standard Hyprland config syntax:

```
windowrulev2 = tile, class:^(spark desktop\.exe)$
```

Omarchy 4 Lua syntax:

```lua
o.window({ class = "^spark desktop\\.exe$" }, { tile = true })
```

The tray tile rule in `share/hyprland-spark-tray.conf` is a separate fix for a
different window.

**Omarchy keybinding.** Omarchy binds `SUPER+SHIFT+E` by default. Unbind it
before reuse. Example for `~/.config/hypr/bindings.lua`:

```lua
hl.unbind("SUPER + SHIFT + E")
o.bind("SUPER + SHIFT + E", "Spark Mail", {
  launch = "/path/to/spark-mail-linux/run-spark.sh",
})
```

Test the exact shortcut end-to-end. A terminal test of an equivalent command
does not prove the shortcut works.

**Notification watcher.** The launcher starts `bin/mail-notify.py` by default.
Set `SPARK_NOTIFY=0` to skip it. Treat that as a diagnostic switch, not as
proof that notifications work or do not work.

## 7. Caveats and known gotchas

**Incomplete extraction.** `bsdtar` can stop silently partway through the
NSIS installer. Symptoms at launch: `Error loading V8 startup snapshot file`
or `Cannot find module '@readdle/sparkcore-win'`. Fix: remove the `app/`
directory and run `./install.sh` again. Accounts and settings live outside
`app/`, so nothing is lost. The script refuses to overwrite an existing
`app/`; that guard is what forces the clean re-extraction.

**GPU process failure.** On one Omarchy host, the first launch failed with
`GPU process isn't usable. Goodbye.` The same version starts with the default
settings on other hosts. If you hit it, launch with:

```bash
./run-spark.sh --disable-gpu
```

If the fix works, tell the user to add the flag to their shortcut command.

**Observed crash with the notification watcher.** One launch with the watcher
enabled reached `Application is ready` and then died with
`FATAL ERROR ... spark-js-addon ... CNAPI.swift ... invalid_arg`. The cause is
unproven. The watcher is a separate read-only Python process and cannot write
to the app. If the crash reproduces, run with `SPARK_NOTIFY=0` and keep a
sanitized log.

**PowerShell debugger dialogs.** Spark runs optional hardware probes through
PowerShell when it finds one in the Wine prefix. PowerShell 7 under Wine can
fail every probe and open many `winedbg` dialogs while Spark itself continues.
The default DLL overrides disable `powershell.exe` and `pwsh.exe`; Spark then
continues without that diagnostic hardware metadata. A custom
`SPARK_OVERRIDES` value must preserve those entries unless the prefix has a
verified working PowerShell installation.

**Floating window in Hyprland.** See the tiling rule in step 6.

**Everything lives in the repository.** The app, the Wine prefix, and the
home overlay stay in the project directory. The only system-wide changes are
the desktop launcher and handler entries plus any symlink the user approved.

## 8. Update Spark later

Do not use Spark's update button. Do not run the Windows installer directly.
Follow the update procedure in [AGENTS.md](AGENTS.md#update-spark). It backs
up the state, replaces the app, and verifies the result. Rollback steps are
included.
