# spark-mail-linux

Run [Spark Desktop](https://sparkmailapp.com/) for Windows on Linux under Wine,
with Google sign-in, native notifications and a hidden tray tile.

Spark has no Linux client. This repository holds the three compatibility fixes
that make the Windows build run correctly, plus a launcher that keeps every
file inside one directory.

Status: working. Verified with Spark Desktop 3.30.10 and 3.30.11 (Electron
42.3.3) on Wine 11.16, on Arch Linux with Hyprland.

Verified features: Google login, inbox sync, calendar, sending mail, file
attachments, and new-mail notifications.

## Why plain Wine is not enough

Spark bundles `SparkCore`, a Swift component with its own copy of Apple's
`Foundation.dll`. That component calls two Windows APIs that Wine does not
implement fully. Both calls crash the app, and neither crash is recoverable
from configuration alone.

| Problem | Cause | Fix |
|---|---|---|
| Crash during startup | Wine's `GetAllUsersProfileDirectoryW` is a stub. It leaves the length at zero. Foundation decrements that value unchecked, so it underflows and copies 8 GB. | `sprkenv.dll` returns `C:\ProgramData` with correct sizing. |
| Crash right after login | Wine's `GetAdaptersAddresses` leaves `Address.lpSockaddr` empty. Swift `Host._resolveCurrent` force-unwraps it and traps. | `sprkiphl.dll` reports `ERROR_NO_DATA`, so `hostName` falls back to `localhost`. |
| Login never completes | The host browser owns the OAuth callback URL. Nothing forwards it into Wine. | A host scheme handler forwards the URL with `--win-open-url`. |
| No new-mail alerts | Wine does not render Windows toast notifications. | `mail-notify.py` reads Spark's own database and calls `notify-send`. |
| Floating grey tile | With no `StatusNotifierWatcher`, Wine draws the tray icon as a window. | A Hyprland window rule hides it. |

Each fix redirects one import in the extracted copy of `Foundation.dll`. No
system DLL changes, and no packages are installed. `docs/investigation.md`
records the debugger evidence behind every claim.

## Requirements

- Wine 11.16 or later, 64-bit
- `bubblewrap`, `python3`, `libarchive` (for `bsdtar`), `clang`, `llvm`, `binutils`
- `libnotify` for notifications
- The official Spark Desktop installer for Windows, from sparkmailapp.com

On Arch Linux:

```bash
sudo pacman -S wine bubblewrap python libarchive clang llvm binutils libnotify
```

## Install

Run every step from the repository directory. Set `SPARK_ROOT` if you run the
scripts from somewhere else.

1. Extract the installer. It is an NSIS archive, so no Windows is needed.
   `bsdtar` from libarchive reads it directly.

   ```bash
   mkdir -p app && bsdtar -xf /path/to/Spark.exe -C app
   ```

2. Build both shims and put them beside the executable.

   ```bash
   OUT_DIR=app ./shims/build.sh
   ```

3. Patch the two imports in the extracted `Foundation.dll`.

   ```bash
   python3 shims/patch-foundation.py
   python3 shims/patch-iphlpapi.py
   ```

   The first script saves `Foundation.original.dll`. Keep that file. It is the
   only way back to the unpatched app.

4. Register the OAuth callback handler on the host.

   ```bash
   ./install-handler.sh
   ```

5. Start Spark.

   ```bash
   ./run-spark.sh
   ```

On Hyprland, add the tray rule to hide Wine's fallback tile:

```bash
cat share/hyprland-spark-tray.conf >> ~/.config/hypr/hyprland.conf
```

## How the launcher works

`run-spark.sh` runs Wine inside Bubblewrap. The root filesystem is read-only.
The home directory is overlaid by `test-home/`, and the repository directory
stays writable. The Wine prefix lives in `prefix/`.

The launcher bind-mounts the project-local `tmp/` at `/tmp`. This detail
matters. With a private `/tmp`, the OAuth callback gets its own wineserver
socket, cannot see the running app, and boots a second instance over the same
prefix. A shared `/tmp` lets the callback join the running wineserver, so
Electron delivers the URL to the primary process.

Warning: this is filesystem containment, not a security sandbox. The app keeps
host network access and host display access.

## Layout

```
run-spark.sh          launcher
install-handler.sh    registers the OAuth callback handler
shims/                shim sources, build script, and the two patch scripts
bin/                  mail-notify.py and auth-callback.py
share/                desktop-entry template and the Hyprland tray rule
tools/pe-symbols.py   lists PE imports and resolves RVAs, used for crash work
docs/investigation.md debugger evidence for every fix
```

`app/`, `prefix/`, `test-home/`, `runtime/` and `tmp/` are created at install
time. They hold proprietary binaries and your login state, so `.gitignore`
excludes all of them. Do not commit them.

## Working in this repository

The repository directory doubles as the working directory. `app/`, `prefix/`,
`test-home/`, `runtime/` and `tmp/` hold proprietary binaries and your login
state, so `.gitignore` excludes all of them.

Enable the pre-commit hook once per clone. It refuses any staged runtime path,
binary, state file, or file over 1 MB:

```bash
git config core.hooksPath .githooks
```

## Limits and risks

- A Spark update overwrites the patched `Foundation.dll`. See "After a Spark
  update" below. Do not take an in-app update without reapplying the patches.
- `sprkiphl.dll` hides all network adapters from `SparkCore` only. Mail and
  calendar do not need adapter data, but a future Spark feature might.
- The notification bridge reads Spark's SQLite database directly. A schema
  change in a later version breaks it. It fails quietly and keeps polling.
- Attachments use Wine's built-in file picker. It works, and it shows Unix
  paths under the `Z:` drive. This is cosmetic.
- Spark's OAuth client identifiers are read from the installed app. A future
  version can change them. Update `ALLOWED_SCHEMES` in `bin/auth-callback.py`
  and the `MimeType` line in the desktop template if login stops working.

## After a Spark update

An update replaces `Foundation.dll` with a pristine copy. It leaves the shim
DLLs in place, so the imports point back at Wine's own libraries and the
startup crash returns.

`run-spark.sh` reads the imports before it starts Wine, so it refuses to launch
and prints the two commands to run. Reapply the patches:

```bash
python3 shims/patch-foundation.py
python3 shims/patch-iphlpapi.py
```

`patch-foundation.py` keeps the previous `Foundation.original.dll` under a
timestamped name and backs up the new pristine DLL. Both scripts are safe to
run twice; they report `Already patched; nothing to do.` and exit zero.

Rebuild the shims only if you also changed Wine or the shim sources.

The in-app updater is not the right path here. It runs an NSIS installer that
expects a registered install location, and this app directory is an extracted
archive that was never installed. Download the new installer instead, extract
it over a fresh `app/`, copy both shims back in, then reapply the patches.

The 3.30.10 to 3.30.11 update needed no new work: `Foundation.dll` was byte
identical between the two builds, so both shims applied unchanged.

## Upstream bugs

Both crashes are Wine defects, and the shims only work around them. The real
fixes belong upstream:

- `userenv.GetAllUsersProfileDirectoryW` is a stub that returns `FALSE` and
  never sets the required size.
- `iphlpapi.GetAdaptersAddresses` returns adapter data that
  swift-corelibs-foundation cannot read on the Windows path.

The unchecked failure in Apple's `Foundation` is a second, separate defect.

## Legal

This repository contains no Spark code and no Microsoft code. It ships only
original shim sources, scripts, and documentation. Spark Desktop is proprietary
software owned by Readdle. Download it from the vendor, and follow the vendor's
licence terms.

The shims exist for interoperability. They replace two Windows API imports so
an unmodified application can run on Wine.

## Licence

MIT. See `LICENSE`.
