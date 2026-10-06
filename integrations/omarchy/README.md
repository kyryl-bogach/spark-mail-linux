# Omarchy plugin

This optional plugin shows the output of `bin/spark events` and `bin/spark emails` in an Omarchy popup.
The event list shows today's remaining calendar events from all shared calendars.
If no events remain today, the list shows the next day with events.
The calendar query covers the remaining week and at least the following day.
The email list includes read and unread emails from the unified inbox.
The command returns its default first page, currently up to 50 emails.

The mail icon uses the theme accent when the unified inbox contains pending emails.
Read emails also count as pending until they leave the inbox.
The icon has no count badge.

A separate calendar badge appears when a timed event starts within 15 minutes.
The tooltip reports the remaining minutes.
The badge clears after the event's start time.

All-day events do not trigger the calendar badge.
The plugin converts event timestamps to the local timezone before it groups events by date.
Date-only all-day events keep their stated date.
The calendar badge does not change the mail indicator.

The popup shows the inbox above a calendar section.
Emails and events share one card layout, with an icon, two text lines, and date or time metadata.
The header stays visible when the lists scroll.

The popup fits its content up to 80% of the screen height, while respecting the bar and screen margins.
If the content exceeds that limit, the popup scrolls.
The scroll bar appears only when the content exceeds the viewport.

The calendar section title reads **Today**, **Tomorrow**, or the day of the first day with events.
Each event card shows the title, time range, and calendar action as plain text.
The popup shows each sender, subject, and date as plain text.

The plugin reads full email metadata through CLI JSON and elides long text only for display.

Click the icon to show the popup. Click an email to open its thread in Spark.
Click an event to open Spark's calendar. The click does not select the specific event.
Click **Open Spark** to focus Spark without a specific view.
If Spark has no window, the helper calls the existing launcher.
Middle-click the icon to open Spark directly. Press Escape to close the popup.

An email click reads the thread's deep link through the CLI and forwards it to the running app.
The list command does not return email links, so the helper fetches the link only on click.
Calendar clicks use Spark's Windows task action, `--dock-task-id=OPEN_CALENDAR_ACTION`, through the existing launcher.
The URL handler has no calendar action in the inspected Spark 3.31.5 bundle.
The Windows task action is internal and can change after an update.
The plugin uses read-only CLI access.

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

The calendar indicator checks the cached event times every 15 seconds without another CLI call.
The indicator checks all returned days, even when the popup shows only the first day.
Calendar JSON supplies absolute timestamps. The popup displays times in the host's local time.

If Spark is closed, the plugin shows that state without a background launch.
If CLI access is enabled but no account is shared, the plugin points back to
Spark's AI Agents settings instead of reporting an empty inbox.
The events section reports an empty calendar when the query returns no events.

The helper reuses `bin/spark`, its Wine settings, optional Bubblewrap mounts, and notification guard.
Popup data stays in memory. Pending calendar reminders use private runtime files described below.

The helper suppresses CLI diagnostics.
One calendar read feeds the popup, bar indicator, and reminder scheduler.
If a read fails, only the affected section clears.

Queued reminders survive calendar read failures.
The plugin requires CLI commands with JSON output and passes checks with CLI 1.4.0.

The open action requires Hyprland.
It checks the window class and Wine prefix before it focuses a window.
If Spark waits on the startup workspace, the helper moves it to the active workspace.
If no window matches, it calls `run-spark.sh` and waits for the new window.

## Calendar reminders

The plugin creates Omarchy reminders five minutes and one minute before timed events.
All-day events and declined events do not create reminders.
Click a notification to open Spark's calendar.

The scheduler checks the calendar every 60 seconds and when the popup opens.
It schedules the next 24 hours with absolute systemd timers and one-second timer accuracy.
The timers appear in Omarchy's reminder queue without a confirmation notification for each scheduled alert.

Calendar changes update or cancel this installation's timers after the next successful refresh.
Queued timers can fire when Spark closes or the bar restarts.
Spark must run to discover new events and calendar changes.

The scheduler skips alert times that have already passed.
It suppresses notifications more than 30 seconds late, including missed alerts after sleep.
Existing Spark notifications stay enabled during validation.

Pending reminders store titles and timing data in private files under `XDG_RUNTIME_DIR`.
The scheduler removes expired records on a successful refresh.
It keeps no calendar data in the repository.

Normal desktop notifications respect Omarchy's Do Not Disturb setting.
Scheduler errors appear in the popup and its tooltip.

To disable these reminders, set `calendarReminders` to `false` in this plugin's inline settings in `shell.json`.
The next refresh clears only this installation's calendar reminders.

Do not use `omarchy reminder clear` for this task. That command clears unrelated reminders too.

To clear them after disabling the plugin, run:

```bash
python3 integrations/omarchy/helper.py reminders-clear
```

## Checks

Run the parser tests and manifest check:

```bash
python3 -m unittest discover -s integrations/omarchy -p 'test_*.py'
omarchy plugin validate "$PWD/integrations/omarchy"
```

The local checks confirm a live inbox read, a live calendar read, popup activation,
thread navigation through the deep link, and focus of the existing Spark window.
The calendar helper passes a live check with Spark 3.31.5 and displays its calendar controls.
The updated event click still needs a direct check in the popup.

The cold launch path remains unverified.
Native layout checks use synthetic data to cover long lists, narrow popups, empty states, and the height limit.
Reminder tests cover both alert times, duplicate prevention, calendar changes, expired alerts, and isolation from unrelated reminders.

Live reminder checks confirm both alert times against a synthetic meeting through Omarchy's notification service.
Verify a real meeting before disabling Spark's calendar notifications.

## UI screenshots

Run the screenshot fixture from the repository root:

```bash
python3 integrations/omarchy/preview/render.py
```

The fixture renders the current widget and Omarchy's notification cards with sample data.
Its mock helper cannot invoke Spark, Wine, or the reminder scheduler.
It writes the popup, bar states, and reminder images to `docs/screenshots/`.

Use `--output /path/to/directory` to save previews elsewhere.
The fixture keeps its temporary files and diagnostics under the ignored `archive/` directory.
Review the generated images before committing them.

## Disable

```bash
omarchy plugin disable local.spark-mail
```
