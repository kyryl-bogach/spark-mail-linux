# Project instructions

## Purpose and scope

This project runs the official Windows Spark Desktop application on Linux through Wine.
It provides compatibility shims, a launcher, OAuth callbacks, native desktop notifications, and a wrapper for Spark CLI.
It is unofficial and has no affiliation with Readdle.

Keep the solution small and specific to demonstrated Wine compatibility problems.
Use the existing Wine and Bubblewrap setup for runtime checks.
Docker does not replace the host display, Wine prefix, or desktop integration in this project.

## Project map

| Path | Purpose |
| --- | --- |
| `run-spark.sh` | Checks the patches and launches Spark inside Bubblewrap. |
| `install.sh` | Verifies dependencies and extraction, then builds, patches, and registers. |
| `INSTALLATION.md` | Agent-facing install guide with user questions, checks, and caveats. |
| `shims/build.sh` | Builds the two compatibility DLLs with Clang and Wine import libraries. |
| `shims/patch-foundation.py` | Redirects Foundation's USERENV import to `sprkenv.dll` and saves the original DLL. |
| `shims/patch-iphlpapi.py` | Redirects Foundation's IPHLPAPI import to `sprkiphl.dll`. |
| `bin/auth-callback.py` | Validates Spark URL schemes and forwards them through the launcher. |
| `bin/mail-notify.py` | Reads Spark's database and emits native notifications. |
| `bin/spark` | Runs the bundled Windows CLI through the desktop launcher. |
| `install-handler.sh` | Registers the app launcher and URL handler with the host desktop. |
| `share/` | Contains desktop integration templates. |
| `tests/` | Covers desktop registration, OAuth validation, and notification polling. |
| `docs/investigation.md` | Records the Wine failures and the evidence for each workaround. |
| `.githooks/pre-commit` | Blocks runtime state, proprietary binaries, and large files from commits. |

`sprkenv.dll` handles the profile-directory API that causes an unchecked length underflow in Foundation.
`sprkiphl.dll` returns no network adapters to avoid a crash in Foundation's host resolution.
Both patches change import names without changing the DLL layout.

The launcher uses `app/`, `prefix/`, `test-home/`, `tmp/`, and an optional bundled `runtime/`.
Bubblewrap contains filesystem writes but retains network and display access.
Wine control commands must use the launcher's prefix and Bubblewrap mounts, including the shared `/tmp`.

## Work rules

- Read `git status` before edits. Preserve unrelated changes, including untracked files.
- Keep proprietary files, installers, mailbox data, credentials, dumps, and logs out of Git.
- Keep backups under the ignored `archive/` directory.
- Never print message content, OAuth URLs, tokens, or account details during checks.
- Inspect logs locally and report only the relevant, sanitized evidence.
- Do not send mail or change mailbox contents to test an update without explicit authorization.
- Enable the repository hook with `git config core.hooksPath .githooks` when needed.
- Stage only the files that belong to the requested change.
- Never credit an agent or assistant in commits, PR descriptions, or coauthor lines.
- Keep `CLAUDE.md` as a relative symlink to `AGENTS.md`.

## Spark CLI

The bundled `spark.exe` sits beside `Foundation.dll` inside `SparkCore.bundle`.
It communicates with Spark Desktop through a Windows named pipe within the Wine prefix.
Spark Desktop must run, and Settings > AI Agents must permit access to the selected account.

`bin/spark` resolves its real path, so a symlink in `~/.local/bin` can point to it.
It sets `SPARK_EXE` and reuses the launcher's prefix, runtime, DLL overrides, and Bubblewrap mounts.
It sets `SPARK_NOTIFY=0` and `SPARK_CLOSE_TRAY=0` so short CLI calls do not
start desktop-only background helpers.

Preserve that guard when you change the launcher.
Do not run the CLI through a separate prefix or bypass the Foundation checks.
Keep desktop launch and CLI checks separate: a successful help command does not prove desktop connectivity.

CLI 1.3.1 passed `--help`, `--version`, `accounts`, `folders`, and `emails` checks with live desktop data.
Those checks used read-only access. Triage and send operations remain unverified and depend on the plan and account permissions.
Do not enable broader access or change mail to verify the wrapper.

### Agent usage skill

Spark includes an installable agent skill for CLI usage. It is separate from this project's update procedure.
Use the installed CLI's help to find its current skill installation command.
Do not assume that the Windows installer writes into the host home directory.

Bubblewrap maps the home directory to `test-home/`, so the skill installer can write into that overlay.
Inspect the generated skill before you copy it to the intended host tool's skill directory.
For Kimi Code, that destination is `~/.kimi-code/skills/use-spark/SKILL.md`.

Preserve any existing host skill before replacement. Keep generated skills and personal tool configuration out of this repository.

## Update Spark

Treat a request to update Spark as permission to prepare, back up, replace, and restart this local installation.
Explain the restart before you stop the application.
Do not use Spark's update button or run the Windows installer directly.

### 1. Identify the release

Read the [official Windows release notes](https://sparkmailapp.com/spark3/win/changelog) each time.
Confirm the release date, full version, and installer URL from that page.
Do not assume that a previously documented version is still the latest.

Check the installed version from `app/resources/app.asar` package metadata or Spark's version display.
Record the current version and check whether Spark already runs.
Do not expose window titles, which can contain mailbox details.

### 2. Prepare an isolated copy

Run these commands from the repository root.
Replace the example version and URL with the verified release values.
The unique directory prevents a repeated attempt from overwriting earlier files.

```bash
set -euo pipefail
root=$PWD
version=3.30.12.140844
url="https://downloads.sparkmailapp.com/Spark3/win/dist/$version/Spark.exe"
mkdir -p "$root/archive"
stage=$(mktemp -d "$root/archive/update-$version-XXXXXX")
mkdir "$stage/app"
curl -fL --retry 3 "$url" -o "$stage/Spark.exe"
bsdtar -xf "$stage/Spark.exe" -C "$stage/app"
OUT_DIR="$stage/app" ./shims/build.sh
SPARK_ROOT="$stage" python3 shims/patch-foundation.py
SPARK_ROOT="$stage" python3 shims/patch-iphlpapi.py
```

Keep `root`, `version`, and `stage` for the later steps.
If any command fails, stop before you replace the live app.

`bsdtar` can stop silently partway through the NSIS installer.
Compare the archive manifest against the extracted tree before you build the shims:

```bash
diff <(bsdtar -tf "$stage/Spark.exe" | tr '\\' '/' | sed 's|^\./||' | grep -v '/$' | sort) \
     <(cd "$stage/app" && find . -mindepth 1 -type f | sed 's|^\./||' | sort)
```

Extract any missing entries with `bsdtar -xf "$stage/Spark.exe" -C "$stage/app" -T <list>`.
Never patch a partially extracted tree.

Confirm that the extracted application reports the requested version.
Confirm that both shim DLLs exist beside `Spark Desktop.exe`.
Use `objdump -p` to inspect the patched Foundation DLL's import table.
Its path relative to `app/` is:

```text
resources/app.asar.unpacked/node_modules/@readdle/sparkcore-win/bin/Release/SparkCore.bundle/Foundation.dll
```

Verify that `sprkenv.dll` imports include `GetProfilesDirectoryW` and `GetAllUsersProfileDirectoryW`.
Verify that `sprkiphl.dll` imports include `GetAdaptersAddresses`.
If the imports change, investigate before you adapt the patches.
Never relax the patch scripts' checks merely to accept a new DLL.

### 3. Stop Spark and preserve rollback state

Ask Spark to quit normally, then verify that its processes exit.
A window-close request can leave Spark active in the tray.
If necessary, send SIGTERM to the verified Spark main process for this installation.
Never use a global Wine kill command or target unrelated Wine applications.

Stop this installation's notification watcher before the backup.
If Wine processes remain, stop only this installation's Wine server through the same Bubblewrap mounts.
If a transient service owns the processes, target that specific service.
Reserve forced termination for processes that do not stop normally.

Warning: Do not copy live mailbox databases while Spark still writes to them.
After Spark stops, save the state and replace the app:

```bash
backup=$(mktemp -d "$root/archive/pre-update-$version-XXXXXX")
cp -a --reflink=auto "$root/prefix" "$root/test-home" "$backup/"
if [ -f "$root/Foundation.original.dll" ]; then
  cp -a "$root/Foundation.original.dll" "$backup/"
fi
for state in mail-notify.state mail-notify.lock; do
  if [ -f "$root/$state" ]; then
    cp -a "$root/$state" "$backup/"
  fi
done
mv "$root/app" "$backup/app"
mv "$stage/app" "$root/app"
cp "$stage/Foundation.original.dll" "$root/Foundation.original.dll"
```

Preserve the existing prefix, home overlay, and runtime in their live locations.
Do not initialize a fresh prefix or change the Wine version as part of a routine Spark update.
If the replacement fails, restore the old app before you launch Spark.

### 4. Verify the update

Run both patch scripts again against the live app.
They must report that the DLL is already patched.
Launch through `run-spark.sh` with the normal settings.

When the shell cannot preserve background processes, use a transient user service.
Direct its output to a file under the ignored update directory:

```bash
systemd-run --user --collect --unit="spark-update-$(date +%s)" \
  --setenv="DISPLAY=$DISPLAY" \
  --setenv="XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" \
  --property="StandardOutput=append:$stage/launch.log" \
  --property="StandardError=append:$stage/launch.log" \
  --working-directory="$root" "$root/run-spark.sh"
```

During the 3.30.12 update, launches through captured output or the journal stalled before a window appeared.
The same version opened with output directed to a file and Wine diagnostics disabled.
Treat this as an observed launch condition, not a proven Wine root cause.

Verify all of these conditions:

- The main process remains active.
- Spark creates a visible window.
- The runtime reports the new version.
- SparkCore loads without the known Foundation crashes.
- The existing account state remains available.

Check that the updated bundle still contains `spark.exe` at the path used by `bin/spark`.
Run `./bin/spark --help` and `./bin/spark --version`.
If account access is enabled, run a read-only command to verify desktop connectivity without exposing its results.
Record the CLI version separately from the desktop version.
If access is disabled, report that limitation instead of changing permissions.

A live process alone does not prove a successful startup.
Do not claim that mail, calendar, attachments, or notifications work unless you checked those operations.
If diagnostic flags help, repeat the check with normal settings before you declare success.

### 5. Document the result

Update `README.md` with the exact version and the checks that passed.
Separate startup verification from functional verification.
Run `git diff --check` and inspect the final diff.
Report the installed version, validation limits, and rollback directory.
Commit or push only when the user requests it.

### Rollback

Stop Spark and its watcher before rollback.
Move the failed app into a separate ignored directory, then restore the saved `app/` and matching original Foundation DLL.
Keep the failed version and logs for investigation.

Warning: Restoring saved state discards local changes made after the backup.
Restore the prefix and home overlay only if necessary for compatibility, with explicit authorization for any loss of newer state.
Preserve the current state before that restoration.
Launch the old version through `run-spark.sh` and verify its window and version.
