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
login handler and the attachment associations. It also builds the optional
image clipboard converter and the window recovery helper with `winegcc` from
the bundled runtime or the system. If that build fails, the script warns and
continues. It stops with a clear error if a required step fails.

If you must install manually, run these commands from the repository root:

```bash
sudo pacman -S wine bubblewrap python python-gobject libarchive clang binutils libnotify desktop-file-utils xdg-utils xorg-xprop xdg-desktop-portal wl-clipboard

mkdir -p app
bsdtar -xf /path/to/Spark.exe -C app
OUT_DIR=app ./shims/build.sh
./bin/build-wine-helpers.sh
python3 shims/patch-foundation.py
python3 shims/patch-iphlpapi.py
./install-handler.sh
./bin/register-host-filetypes.sh
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
   launcher; the second handles browser sign-in callbacks, Spark deep links,
   and `mailto:` links.
5. First launch: run `./run-spark.sh`. Confirm a visible, mapped window.
   On Hyprland, `hyprctl clients` must list the Spark window.
6. Host integration: with Spark open, run
   `SPARK_EXE='C:\windows\system32\start.exe' SPARK_NOTIFY=0 SPARK_CLOSE_TRAY=0 SPARK_IMAGE_BRIDGE=0 ./run-spark.sh /unix /path/to/a.png`.
   The host image viewer opens. A file saved from Spark appears in the host
   download directory, not under `test-home/`.

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

After Spark's renderer is ready, the launcher closes only Wine's tray window.
Wine hides that window and keeps `explorer.exe` active to manage the clipboard.
The helper checks the process prefix, window class, and process ID before it sends the close request.

No tray-specific Hyprland rule is needed.

Web links use the desktop portal to open the host browser with its existing profile.
Install a portal backend for your desktop if none exists.
Omarchy supplies its portal backend.

If the portal fails, the helper reports an error without the URL.
It does not fall back to a browser in the home overlay.

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

**A browser still opens another mail client.** Chromium-based browsers can
keep a site-level `mailto:` handler that takes priority before Linux receives
the link. Confirm that `xdg-mime query default x-scheme-handler/mailto` returns
`spark-mail-linux-auth.desktop`, then remove the old mail handler under the
browser's protocol-handler settings. If browser sync restores it, explicitly
deny that site's handler request so it is recorded as ignored instead of only
deleted. The installer deliberately does not edit browser profiles.

**Floating window in Hyprland.** See the tiling rule in step 6.

**Flatpak browsers and handlers.** Applications installed as Flatpaks cannot
start inside the Bubblewrap container. Links therefore go through the desktop
portal, and attachments through a transient user service that runs the host
`xdg-open`. Both start on the host. If the portal or the systemd user
manager is missing, the helpers report an error and open nothing.

**JavaScript error in the main process at launch.** GNOME Shell starts
applications with stdout and stderr connected to the journal through a
socket. Under Wine, Electron fails with `open EBADF` when it initializes
`process.stdout` with that socket.

The launcher detects socket stdio on a desktop launch and writes the output
to `tmp/launch.log` instead. Read that file when a launch misbehaves.

**Everything lives in the repository.** The app, the Wine prefix, and the
home overlay stay in the project directory. The only system-wide changes are
the desktop launcher and handler entries plus any symlink the user approved.

## 8. Update Spark later

Run `./update-spark.sh` from the repository root.
If Spark is current, the command exits without a restart.
To check without changes, run `./update-spark.sh --check`.

The Omarchy popup always shows a refresh icon beside **Open Spark**.
Click it to check for updates and install a newer release through the same updater in a terminal.
The updater prepares and validates the new application, stops Spark, saves a backup, replaces the application, and restarts Spark.
It requires the repository installation, a user systemd session, and Hyprland for window checks.
Adopted installations with custom application or prefix paths still require the manual procedure.

See [the update guide](README.md#update) for validation limits and requirements.
Follow [AGENTS.md](AGENTS.md#update-spark) for manual updates and rollback.
Do not use Spark's update button or run the Windows installer directly.

## 9. ARM hosts (Apple silicon, Asahi Linux)

Spark is an x86_64 Windows application. On an aarch64 host it runs as
muvm (a microVM with 4K pages) → FEX-Emu → Wine → Spark. `run-spark.sh`,
`install.sh` and the Bubblewrap container do not apply there. Use the
`spark-arm` launcher in `launcher/` instead.

This was set up once, on a MacBook Air M1 with Omarchy on Asahi Linux, with
Spark 3.32.3.141489 and Wine 11.4. Treat it as experimental.

### Packages

Arch Linux ARM names: `muvm`, `FEX-Emu`, `fex-emu-rootfs-arch`,
`mesa-fex-emu-overlay-x86_64`, `erofs-utils`, `libarchive` (`bsdtar`), `clang`,
and a Rust toolchain (`rustup`). Ask the user before you install any of them.

### Extract Wine out of the FEX rootfs

The FEX rootfs image ships an x86_64 Wine. Wine started from inside the image
cannot open its own fonts. DirectWrite then fails on Tahoma and Spark never
shows a window. Copy Wine into `runtime/`, which is ignored by Git:

```bash
img=/usr/share/fex-emu/RootFS/default.erofs
mkdir -p runtime/usr/lib runtime/usr/share
fsck.erofs --extract=runtime/usr/lib/wine --path=/usr/lib/wine --no-preserve "$img"
fsck.erofs --extract=runtime/usr/bin --path=/usr/bin --no-preserve "$img"
fsck.erofs --extract=runtime/usr/share/wine --path=/usr/share/wine --no-preserve "$img"
```

`runtime/usr/bin/wine` must exist afterwards. The launcher refuses to start
without it.

### Extract and patch Spark

Follow the manual steps in [AGENTS.md](AGENTS.md#2-prepare-an-isolated-copy):
extract the installer with `bsdtar`, compare the manifest, build the shims and
run both patch scripts. Two differences on ARM:

- `shims/build.sh` needs an x86_64 Windows linker. If the host has no `lld`,
  link with the `rust-lld` that ships in the Rust toolchain
  (`…/rustlib/aarch64-unknown-linux-gnu/bin/gcc-ld/ld.lld`). It needs a
  `DllMainCRTStartup` entry symbol in each shim.
- Create the Wine prefix by the first launch. Do not copy one from an x86_64
  machine.

### Build and register the launcher

```bash
cargo build --release --locked --manifest-path launcher/Cargo.toml
mkdir -p .build
cp launcher/target/release/spark-arm .build/spark-arm
.build/spark-arm --root "$PWD" --install-desktop
```

`--install-desktop` writes the same two desktop entries as
`install-handler.sh`, pointed at `spark-arm`, and registers Spark's URL
schemes and `mailto`. Rerun it when the binary or the repository moves.

### What the launcher does

- **Start:** `muvm -m` with the bundled Wine. Output goes to `tmp/launch.log`.
  The window appears one to two minutes after the start.
- **Safe defaults:** `--disable-gpu`, because the GPU process crashes on most
  starts, and `--js-flags=--jitless`, because V8's JIT-compiled code crashes
  Spark under FEX within minutes. `--gpu` and `--jit` turn them back on.
- **Retry:** many starts die within seconds (`GPU process isn't usable`,
  `Network service crashed`) and a few hang. The launcher waits for
  `Application bootstrap is completed` in the log. A start that dies first, or
  is not ready after `--ready-timeout` seconds (default 300), is stopped and
  started again after 10 seconds, three starts at most.
- **Second launch and callbacks:** on x86_64 a second `Spark Desktop.exe`
  hands its arguments to the first and exits. Under FEX the first instance
  dies when that second process starts. So `spark-arm` starts Spark with
  `--inspect=127.0.0.1:9229` and, when the VM is already up, runs itself
  inside the VM as a native helper. The helper connects to that inspector and
  raises Spark's own `second-instance` event with the URL. No second VM and no
  second Spark process start. The URL travels in an owner-only file under
  `tmp/deliveries/`, never on a command line. A link that arrives while
  Spark is still starting waits until Spark listens.
- **Links out of Spark:** Wine calls `xdg-open` inside the VM. The launcher
  puts its own `xdg-open` first on `PATH`. It queues the link in
  `tmp/open-requests/`, and the launcher on the host opens it and deletes the
  file. Never let the system `xdg-open` run inside the VM: it starts a second
  browser on the user's real profile, and the callback cannot return.
- **Stop:** `.build/spark-arm --root "$PWD" --stop`.
- **Logs:** `tmp/launch.log` (Spark and Wine), `tmp/muvm.log` (muvm itself)
  and `tmp/spark-arm.log` (the launcher; it records schemes, never URLs).

The inspector port listens on the loopback interface inside the VM only.
Any process inside that VM can control Spark through it, so run nothing else
in the VM. Change the port with `--inspect-port`.

Settings: `spark-arm --help`. `--mem` (or `SPARK_VM_MEM`) caps the VM's
memory in MiB. `--guest-env KEY=VALUE` and `--spark-arg ARG` pass extra
settings to FEX and to Spark for experiments.

### Limits on ARM

- Rendering is in software and JavaScript runs in V8's interpreter, so Spark
  is slower than on x86_64.
- Startup takes minutes when starts have to be retried, and the VM needs
  several GB of memory.
- There is no Bubblewrap container. Wine sees the real home directory.
- muvm runs one VM per user. The launcher refuses to start while another
  muvm VM is running, for example one started for Steam.
- With the VM capped at 6000 MiB, Spark used almost all of it while idle on
  the welcome screen. Plan for about 6 GB of host memory.
- The notification watcher, tray closer, clipboard image bridge, window
  rescue, `bin/spark` and `update-spark.sh` are untested under muvm and are
  not started by `spark-arm`.
- After a Spark update, rebuild the shims and patch `Foundation.dll` by hand.
