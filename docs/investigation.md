# Investigation

Debugger evidence behind each fix in this repository. Host identifiers, crash
dump files and account data are not included. Raw dump text is not published,
because register and stack contents hold the host name and a LAN address.

Environment: Wine 11.16, 64-bit. Spark Desktop 3.30.10, Electron 42.3.3.
Arch Linux with Hyprland.

## What did not work

The first theory was a C or C++ runtime mismatch. `SparkCore` ships its own
Visual C++ runtime DLLs. Three configurations were tested, and all three
crashed during startup with access violation `0xC0000005`:

1. Native Microsoft UCRT only. The loader confirmed native `ucrtbase.dll`.
   Mixed-runtime export errors also appeared.
2. Native UCRT plus native Visual C++ overrides. `SparkCore` loaded its
   bundled `VCRUNTIME140.dll`. The export errors cleared. The crash stayed.
3. Bundled Visual C++ DLLs replaced by the current Microsoft v14
   redistributable. The crash stayed.

Conclusion: the C and C++ runtime is not the cause. Replacing it changes
nothing. This theory cost the most time and produced no result.

## Fix 1: the startup crash

Crashpad wrote a minidump during startup. The stack, in module-relative
offsets, ran from a memory copy in `vcruntime140` up through nine `Foundation`
frames into `RDCalendarsAPI`:

```
vcruntime140+0x1dc91   (memory copy)
Foundation+0x32cad5
Foundation+0x32d0dc
Foundation+0x3857ed
Foundation+0x36cf0c
Foundation+0x36db2d
Foundation+0x36d714
Foundation+0x36d744
Foundation+0x2da612
RDCalendarsAPI+0x250915
RDCalendarsAPI+0x24c2a5
```

The `Foundation` import address table at RVA `0x41d1b8` resolves to
`USERENV.dll!GetAllUsersProfileDirectoryW`.

At RVA `0x3857a0`, `Foundation` does the following:

1. It initializes a `DWORD` length to zero.
2. It calls `GetAllUsersProfileDirectoryW` twice.
3. It ignores both return values.
4. It loads that length and decrements it as a 32-bit integer, at RVA
   `0x3857d8`.

Wine 11.16 implements this function as a stub. It returns `FALSE` and never
writes the size. See
[`dlls/userenv/userenv_main.c`](https://github.com/wine-mirror/wine/blob/wine-11.16/dlls/userenv/userenv_main.c).

So the length stays zero, and the decrement underflows to `0xffffffff`. At
`Foundation+0x32d0a4` the code doubles that value for UTF-16 bytes, which gives
`0x1fffffffe`. The fault registers confirmed it: `R8` and `RBX` both held
`0x1fffffffe`, that is 8,589,934,590 bytes. The launch log recorded both API
calls immediately before the exception.

Cause: an unimplemented Wine API, combined with an unchecked failure in Apple's
`Foundation`.

Fix: `profile-shim.c`, built as `sprkenv.dll`. It returns `C:\ProgramData`, and
it implements the documented size-query and insufficient-buffer behaviour.
`GetProfilesDirectoryW` forwards to Wine's own `userenv` through the `.def`
file, because Wine implements that one correctly.

`patch-foundation.py` rewrites the single `USERENV.dll\0` import name to the
equal-length `sprkenv.dll\0`. Equal length means the patch needs no relocation
work. The script asserts that exactly one occurrence exists.

Result: the shim loaded in the main process and in every worker. Spark finished
bootstrap and stayed running past the previous crash point.

## Fix 2: the crash after login

Onboarding then succeeded, and Spark crashed as soon as the main UI and
calendar loaded. Crashpad wrote a 612 MB dump. Non-interactive `winedbg`
showed:

- A `ud2` instruction, the Swift fatal trap, at `Foundation+0xe42d6`, on a
  `SmartMailCommon` dispatch worker thread.
- This backtrace: `ProcessInfo.hostName` at `+0x277f04`, then `Host.name`,
  `Host.names`, `Host._resolve`, and `Host._resolveCurrent(withInfo:)` as the
  caller at `+0xe4377`.
- Registers and stack held the host name as ASCII, and a LAN IP address as a
  string. That is adapter enumeration data.
- Disassembly of `_resolveCurrent` showed a `testq` and a `je` to `ud2`
  directly after an indirect call. That is a Swift implicit-unwrap trap.

In swift-corelibs-foundation, the Windows path of `Host._resolveCurrent` walks
`IP_ADAPTER_ADDRESSES` and force-unwraps `Address.lpSockaddr`. Wine fills those
structures so that the pointer is empty, or laid out differently, so the unwrap
traps.

The fallback path was checked before choosing the fix. Disassembly of
`ProcessInfo.hostName` at `Foundation+0x277f13` shows a nil check that
substitutes the string `"localhost"` when `Host.name` is nil. Reporting no
adapters is therefore safe.

Fix: `adapter-shim.c`, built as `sprkiphl.dll`. It exports
`GetAdaptersAddresses` and returns `ERROR_NO_DATA`, which is 232, for every
call. `_resolveCurrent` then returns early, `Host.name` is nil, and `hostName`
becomes `"localhost"`.

`patch-iphlpapi.py` rewrites the single `IPHLPAPI.DLL\0` import name to the
equal-length `sprkiphl.dll\0`. `Foundation` imports nothing else from that
library, so redirecting the whole descriptor is safe.

Result: relaunch no longer crashes. Main UI, inbox sync, calendar view and
sending mail all work.

## Fix 3: the OAuth callback

Spark is an Electron app. At launch it registers its URL schemes in the Wine
prefix under `HKCU`. Each entry points at `"Spark Desktop.exe" --win-open-url
"%1"`.

Google sign-in opens the host browser, so the host needs
`x-scheme-handler` entries for the three callback schemes Spark registers. The
desktop template in `share/` provides them, and `auth-callback.py` validates
the scheme against an allowlist before it acts.

The important fix was in the launcher, not the handler. The launcher used
`--tmpfs /tmp`. A callback invocation therefore got a fresh wineserver socket
directory, could not see the running instance, and booted a second full
instance over the same prefix. Electron's single-instance forwarding never
fired.

The launcher now bind-mounts a persistent project-local `tmp/` at `/tmp`. The
callback joins the running wineserver, and Spark's second-instance handler
receives the URL in the primary process.

Result: Google consent completed in the host browser, the callback reached
Spark, and login and onboarding succeeded.

## Tray tile and notifications

Spark registers a tray icon. The log shows `fixme:systray:Shell_NotifyIconGetRect`
stubs. With no `StatusNotifierWatcher` on the session bus, Wine's
`explorer.exe` draws the icon as a small floating tile. That window has class
`explorer.exe` and an empty title. The Hyprland rule in `share/` sends it to a
hidden workspace and denies it initial focus.

Spark's new-mail notifications use Windows toasts, which Wine stubs out. Mail
events arrive, and the push pipeline is visible in the log, but nothing
displays.

`mail-notify.py` bridges this. It polls Spark's own `messages.sqlite`
read-only, every 15 seconds, for rows where `unseen = 1 AND inInbox = 1 AND
inSent = 0`. It calls `notify-send` for each new row.

Two details matter in the watermark logic:

- On first run the watermark adopts the current maximum primary key, so the
  existing backlog produces no notifications.
- The watermark advances only past rows that matched the filter. Spark inserts
  a message row before it sets the inbox and unseen flags. A watermark that
  tracked the maximum key over every row could step over a message during that
  gap, and never notify for it.

A `flock` guard keeps the OAuth callback path, which also runs the launcher,
from starting a second watcher.

Result: a real incoming message produced a native desktop notification within
one poll interval.

## Current shim stack on Foundation.dll

| Import | Was | Now | Shim behaviour |
|---|---|---|---|
| `GetAllUsersProfileDirectoryW` | `USERENV.dll`, a Wine stub | `sprkenv.dll` | Returns `C:\ProgramData` with correct sizing |
| `GetProfilesDirectoryW` | `USERENV.dll` | `sprkenv.dll` | Forwards to Wine `userenv` through the `.def` file |
| `GetAdaptersAddresses` | `IPHLPAPI.DLL` | `sprkiphl.dll` | Returns `ERROR_NO_DATA`, an empty adapter list |

## Restore the unpatched app

Stop Spark, then copy the backup over the patched file:

```bash
cp Foundation.original.dll \
  "app/resources/app.asar.unpacked/node_modules/@readdle/sparkcore-win/bin/Release/SparkCore.bundle/Foundation.dll"
```

This removes both import redirects. The shim DLLs then stay on disk, unused.
To keep only the profile shim, run `shims/patch-foundation.py` again.

## Open observations

These conditions were seen during a 3.30.12 install on Omarchy 4.0.3 with
Wine 11.17. None has a proven root cause. Treat each as a recorded condition,
not a diagnosis.

**Partial extraction.** `bsdtar` stopped silently partway through the NSIS
installer. About 170 files never reached `app/`, including `Spark
Desktop.exe`, the V8 snapshots, and most of the SparkCore bundle. The later
errors (`Error loading V8 startup snapshot file`, `Cannot find module
'@readdle/sparkcore-win'`) pointed nowhere near the real cause. Recovery:
compare `bsdtar -tf` against the extracted tree, then extract the missing
entries with `bsdtar -T`. `install.sh` now runs this check on every install.

**GPU process failure.** The first launch failed with `GPU process isn't
usable. Goodbye.` Adding Electron's `--disable-gpu` argument worked. The same
version starts with default settings on the reference host, so the condition
is host-dependent.

**Fatal error with the notification watcher.** One launch with the watcher
enabled reached `Application is ready` and then died with `FATAL ERROR ...
spark-js-addon ... CNAPI.swift ... invalid_arg`. Launches with
`SPARK_NOTIFY=0` stayed up. The watcher is a separate read-only Python
process, so a causal link is doubtful and unproven. Isolation work is open.
