"""Check the Spark boundary with sample data and no mailbox writes."""
from datetime import date, datetime, timezone
import json
import os
import subprocess
import time
import unittest
from unittest import mock
from helper import (
    calendar_view, focus_window, inbox, open_calendar, open_email, open_spark,
    overview, parse_emails, parse_events, sync_reminders,
)


def event(title='Design review', event_id='event-1', start='2026-10-06T15:00:00+02:00',
          end='2026-10-06T15:30:00+02:00', **extra):
    return dict(id=event_id, title=title, start=start, end=end, all_day=False,
                attending_status='accepted', **extra)


def calendar_output(*rows):
    return json.dumps({'events': list(rows)})


def email_output(**overrides):
    row = dict(id=42, account='a@example.test', date='2026-10-06T15:00:00+02:00',
               subject='Two  spaces', **{'from': [{'name': 'Renée Test', 'email': 'a@example.test'}]})
    row.update(overrides)
    return json.dumps({'emails': [row], 'page': {'total_count': 1000, 'has_more': True}})


class CalendarTests(unittest.TestCase):
    def setUp(self):
        previous = os.environ.get('TZ')
        os.environ['TZ'] = 'Europe/Madrid'
        time.tzset()
        def restore():
            if previous is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = previous
            time.tzset()
        self.addCleanup(restore)

    def view(self, *rows, today=date(2026, 10, 6)):
        return calendar_view('ok', parse_events(calendar_output(*rows)), today)

    def test_json_preserves_titles_and_absolute_times(self):
        rows = parse_events(calendar_output(event(title='Review: <b>two  spaces</b>')))
        self.assertEqual(rows[0]['title'], 'Review: <b>two  spaces</b>')
        self.assertEqual(rows[0]['day'], '2026-10-06')
        self.assertEqual(rows[0]['time'], '15:00 – 15:30')
        self.assertEqual(rows[0]['start_ms'], int(datetime(2026, 10, 6, 13, tzinfo=timezone.utc).timestamp() * 1000))

    def test_empty_and_invalid_results_are_distinct(self):
        self.assertEqual(parse_events(calendar_output()), [])
        for output in ('Access denied', '{"events":null}', calendar_output({'all_day': False}),
                       calendar_output(dict(event(), start='2026-10-06T15:00:00'))):
            with self.subTest(output=output), self.assertRaises(ValueError):
                parse_events(output)

    def test_declined_events_are_excluded_from_view_and_alerts(self):
        rows = [dict(event(), attending_status='declined'), dict(event(), attending_status='no')]
        self.assertEqual(parse_events(calendar_output(*rows)), [])

    def test_all_day_events_remain_visible_without_alert_times(self):
        result = self.view(dict(event(), all_day=True, start='2026-10-06'))
        self.assertEqual(result['events'], [{'title': 'Design review', 'time': 'All day', 'location': ''}])
        self.assertEqual(result['start_times'], [])

    def test_event_location_reaches_the_popup(self):
        cases = [({'location': ' Room 3 '}, 'Room 3'),
                 ({'location': '42 Example Street', 'conference_url': 'https://meet.google.com/abc'}, '42 Example Street'),
                 ({'conference_url': 'https://meet.google.com/abc'}, 'Google Meet'),
                 ({'location': 'https://us02web.zoom.us/j/123'}, 'Zoom'),
                 ({'conference_url': 'https://teams.microsoft.com/l/meetup-join/123'}, 'Microsoft Teams'),
                 ({'conference_url': 'https://video.example.test/123'}, 'Online meeting'),
                 ({'conference_url': 'https://meet.google.com.example.test/123'}, 'Online meeting'),
                 ({'location': None}, ''), ({'location': 123}, ''),
                 ({'conference_url': 'https://[invalid'}, ''), ({}, '')]
        for metadata, expected in cases:
            with self.subTest(metadata=metadata):
                result = self.view(event(**metadata))
                self.assertEqual(result['events'][0]['location'], expected)

    def test_all_day_utc_midnight_is_grouped_by_local_date(self):
        rows = [event(title='Thursday meeting', start='2026-10-08T15:00:00+02:00',
                      end='2026-10-08T15:30:00+02:00'),
                dict(event(title='Friday holiday'), all_day=True,
                     start='2026-10-08T22:00:00Z', end='2026-10-09T22:00:00Z')]
        parsed = parse_events(calendar_output(*rows))
        self.assertEqual(parsed[1]['day'], '2026-10-09')
        self.assertIsNone(parsed[1]['start_ms'])
        result = calendar_view('ok', parsed, date(2026, 10, 6))
        self.assertEqual(result['label'], 'Thursday, Oct 8')
        self.assertEqual([row['title'] for row in result['events']], ['Thursday meeting'])

    def test_all_day_dates_respect_offsets_and_preserve_date_only_values(self):
        cases = [('2026-10-08T22:00:00Z', '2026-10-09'),
                 ('2026-12-08T23:00:00Z', '2026-12-09'),
                 ('2026-10-09T00:00:00+02:00', '2026-10-09'),
                 ('2026-10-09T00:00:00+09:00', '2026-10-08'),
                 ('2026-10-09', '2026-10-09')]
        for start, expected in cases:
            with self.subTest(start=start):
                parsed = parse_events(calendar_output(dict(event(), all_day=True, start=start)))
                self.assertEqual(parsed[0]['day'], expected)
                self.assertIsNone(parsed[0]['start_ms'])

    def test_today_tomorrow_and_later_day_labels(self):
        cases = [('2026-10-06', 'Today'), ('2026-10-07', 'Tomorrow'), ('2026-10-08', 'Thursday, Oct 8')]
        for day, label in cases:
            with self.subTest(day=day):
                result = self.view(event(start=day+'T15:00:00+02:00', end=day+'T15:30:00+02:00'))
                self.assertEqual(result['label'], label)

    def test_first_day_is_shown_and_later_start_times_remain_available(self):
        result = self.view(event(title='Later', event_id='later', start='2026-10-07T00:05:00+02:00', end='2026-10-07T00:30:00+02:00'),
                           dict(event(title='Today'), all_day=True))
        self.assertEqual(result['label'], 'Today')
        self.assertEqual([row['title'] for row in result['events']], ['Today'])
        self.assertEqual(len(result['start_times']), 1)

    def test_dst_fold_keeps_two_absolute_starts_distinct(self):
        rows = parse_events(calendar_output(
            event(start='2026-10-25T02:30:00+02:00', end='2026-10-25T02:45:00+02:00'),
            event(event_id='second', start='2026-10-25T02:30:00+01:00', end='2026-10-25T02:45:00+01:00')))
        self.assertEqual(rows[1]['start_ms'] - rows[0]['start_ms'], 3600000)
        self.assertEqual(rows[0]['time'], rows[1]['time'])


class InboxTests(unittest.TestCase):
    def test_full_metadata_preserves_unicode_spaces_and_large_ids(self):
        row = parse_emails(email_output(id=9007199254740993, subject='<b>Two  spaces</b>'))[0]
        self.assertEqual(row['id'], '9007199254740993')
        self.assertEqual(row['sender'], 'Renée Test')
        self.assertEqual(row['subject'], '<b>Two  spaces</b>')

    def test_empty_result_is_valid_and_errors_are_not_empty_mail(self):
        self.assertEqual(parse_emails('{"emails":[]}'), [])
        for output in ('Access denied', '{"emails":null}', email_output(id=True), email_output(id='oops')):
            with self.subTest(output=output), self.assertRaises(ValueError):
                parse_emails(output)

    @mock.patch('helper.spark_running', return_value=True)
    def test_no_shared_accounts_are_not_reported_as_an_empty_inbox(self, running):
        with mock.patch('helper.run_cli', side_effect=[('ok', '{"emails":[]}'), ('ok', '{"accounts":[]}')]):
            self.assertIn('No accounts shared', inbox()['status'])


class SnapshotTests(unittest.TestCase):
    @mock.patch('helper.Reminders')
    @mock.patch('helper.spark_running', return_value=True)
    def test_popup_and_reminders_share_one_calendar_read(self, running, reminders):
        reminders.return_value.sync.return_value = {'scheduled': 2, 'cancelled': 0}
        with mock.patch('helper.run_cli', side_effect=[('ok', calendar_output(event())), ('ok', email_output())]) as cli:
            result = overview(True, datetime(2026, 10, 11, 12))
        self.assertEqual(cli.call_count, 2)
        self.assertEqual(cli.call_args_list[0].args, ('events', '--start', '2026-10-11T12:00', '--end', '2026-10-13', '--json'))
        self.assertEqual(cli.call_args_list[1].args, ('emails', '--json'))
        self.assertTrue(result['reminders_ok'])
        self.assertEqual(len(result['emails']), 1)
        self.assertEqual(len(reminders.return_value.sync.call_args.args[0]), 1)

    @mock.patch('helper.Reminders')
    @mock.patch('helper.spark_running', return_value=True)
    def test_calendar_error_preserves_mail_and_queued_reminders(self, running, reminders):
        with mock.patch('helper.run_cli', side_effect=[('ok', 'bad calendar'), ('ok', email_output())]):
            result = overview(True, datetime(2026, 10, 6, 12))
        self.assertEqual(len(result['emails']), 1)
        self.assertEqual(result['events'], [])
        self.assertFalse(result['reminders_ok'])
        reminders.assert_not_called()

    @mock.patch('helper.Reminders')
    @mock.patch('helper.spark_running', return_value=True)
    def test_inbox_error_preserves_the_calendar(self, running, reminders):
        with mock.patch('helper.run_cli', side_effect=[('ok', calendar_output(event())), ('ok', 'bad mail')]):
            result = overview(now=datetime(2026, 10, 6, 12))
        self.assertEqual(result['emails'], [])
        self.assertEqual(len(result['events']), 1)
        reminders.assert_not_called()

    @mock.patch('helper.Reminders')
    @mock.patch('helper.spark_running', return_value=False)
    @mock.patch('helper.run_cli')
    def test_closed_spark_preserves_queued_reminders(self, cli, running, reminders):
        result = overview(True)
        self.assertEqual(result['status'], 'Spark is closed')
        self.assertTrue(result['reminders_ok'])
        cli.assert_not_called()
        reminders.assert_not_called()

    @mock.patch('helper.Reminders')
    @mock.patch('helper.spark_running', return_value=False)
    def test_disabled_reminders_clear_the_owned_queue_even_when_spark_is_closed(self, running, reminders):
        reminders.return_value.clear.return_value = 2
        result = overview(False)
        reminders.return_value.clear.assert_called_once()
        reminders.return_value.sync.assert_not_called()
        self.assertIn('disabled', result['reminder_status'])

    @mock.patch('helper.Reminders')
    @mock.patch('helper.spark_running', return_value=True)
    def test_read_only_snapshot_never_updates_the_queue(self, running, reminders):
        with mock.patch('helper.run_cli', side_effect=[('ok', calendar_output(event())), ('ok', email_output())]):
            overview(now=datetime(2026, 10, 6, 12))
        reminders.assert_not_called()

    @mock.patch('helper.Reminders')
    @mock.patch('helper.spark_running', return_value=True)
    @mock.patch('helper.run_cli', return_value=('timeout', ''))
    def test_manual_reminder_sync_preserves_the_queue_on_cli_failure(self, cli, running, reminders):
        self.assertFalse(sync_reminders()['ok'])
        reminders.assert_not_called()


class OpenEmailTests(unittest.TestCase):
    THREAD = 'Thread summary\nLink: https://sparkmailapp.com/dpl/bl?token=abc123\n'

    @mock.patch('helper.spark_window', return_value=None)
    @mock.patch('helper.subprocess.run')
    @mock.patch('helper.run_cli', return_value=('ok', THREAD))
    def test_forwards_the_thread_link(self, run_cli, run, window):
        run.return_value.returncode = 0
        open_email('14625')
        run_cli.assert_called_once_with('thread', '14625')
        command = run.call_args.args[0]
        self.assertIn('--win-open-url', command)
        self.assertTrue(command[-1].startswith('https://sparkmailapp.com/dpl/bl?'))

    @mock.patch('helper.focus_window')
    @mock.patch('helper.spark_window', return_value={'address': '0x123abc', 'workspace': {'name': '1'}})
    @mock.patch('helper.subprocess.run')
    @mock.patch('helper.run_cli', return_value=('ok', THREAD))
    def test_focuses_the_window(self, run_cli, run, window, focus):
        run.return_value.returncode = 0
        open_email('14625')
        focus.assert_called_once_with('0x123abc', False)

    def test_rejects_non_numeric_id(self):
        with self.assertRaises(ValueError):
            open_email('1; os.exit()')

    @mock.patch('helper.run_cli', return_value=('ok', 'no link here'))
    def test_missing_link_fails(self, run_cli):
        with self.assertRaises(ValueError):
            open_email('14625')

    @mock.patch('helper.subprocess.run')
    @mock.patch('helper.run_cli', return_value=('ok', 'Link: https://evil.example.test/dpl/bl?token=x\n'))
    def test_rejects_foreign_link(self, run_cli, run):
        with self.assertRaises(ValueError):
            open_email('14625')
        run.assert_not_called()

    @mock.patch('helper.subprocess.run')
    @mock.patch('helper.run_cli', return_value=('timeout', ''))
    def test_cli_failure_fails(self, run_cli, run):
        with self.assertRaises(subprocess.SubprocessError):
            open_email('14625')
        run.assert_not_called()


class OpenCalendarTests(unittest.TestCase):
    @mock.patch('helper.subprocess.run')
    @mock.patch('helper.open_spark')
    def test_focuses_spark_before_it_dispatches_the_calendar_action(self, open_spark, run):
        calls = mock.Mock()
        calls.attach_mock(open_spark, 'open_spark')
        calls.attach_mock(run, 'run')

        open_calendar()

        self.assertEqual([call[0] for call in calls.mock_calls], ['open_spark', 'run'])
        command = run.call_args.args[0]
        self.assertTrue(command[0].endswith('/run-spark.sh'))
        self.assertEqual(command[1:], ['--dock-task-id=OPEN_CALENDAR_ACTION'])
        options = run.call_args.kwargs
        self.assertEqual(options['env']['SPARK_NOTIFY'], '0')
        self.assertEqual(options['env']['SPARK_CLOSE_TRAY'], '0')
        self.assertEqual(options['env']['SPARK_IMAGE_BRIDGE'], '0')
        self.assertTrue(options['check'])
        self.assertEqual(options['timeout'], 30)
        self.assertEqual(options['stdout'], subprocess.DEVNULL)
        self.assertEqual(options['stderr'], subprocess.DEVNULL)

    @mock.patch('helper.subprocess.run')
    @mock.patch('helper.open_spark', side_effect=subprocess.SubprocessError('No window'))
    def test_does_not_dispatch_when_spark_cannot_open(self, open_spark, run):
        with self.assertRaises(subprocess.SubprocessError):
            open_calendar()
        run.assert_not_called()

    @mock.patch('helper.open_spark')
    def test_reports_launcher_failure_and_timeout(self, open_spark):
        errors = [subprocess.CalledProcessError(1, ['launcher']),
                  subprocess.TimeoutExpired(['launcher'], 30)]
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                    mock.patch('helper.subprocess.run', side_effect=error), \
                    self.assertRaises(subprocess.SubprocessError):
                open_calendar()


class FocusTests(unittest.TestCase):
    @mock.patch('helper.subprocess.run')
    def test_focus_uses_current_hyprland_dispatcher(self, run):
        run.return_value.returncode = 0
        focus_window('0x123abc')
        self.assertEqual(run.call_args.args[0], [
            'hyprctl', 'dispatch',
            'hl.dsp.focus({ window = "address:0x123abc" })',
        ])

    @mock.patch('helper.subprocess.run')
    def test_focus_falls_back_for_older_hyprland(self, run):
        run.side_effect = [mock.Mock(returncode=1), mock.Mock(returncode=0)]
        focus_window('0x123abc')
        self.assertEqual(run.call_args_list[1].args[0], [
            'hyprctl', 'dispatch', 'focuswindow', 'address:0x123abc',
        ])

    def test_focus_rejects_invalid_address(self):
        with self.assertRaises(ValueError):
            focus_window('activewindow; os.exit()')

    @mock.patch('helper.subprocess.check_output', return_value=b'{"id": 6}')
    @mock.patch('helper.subprocess.run')
    def test_background_window_moves_to_active_workspace_before_focus(self, run, check_output):
        run.return_value.returncode = 0
        focus_window('0x123abc', from_background=True)
        self.assertEqual(check_output.call_args.args[0], ['hyprctl', 'activeworkspace', '-j'])
        self.assertEqual(run.call_args_list[0].args[0], [
            'hyprctl', 'dispatch',
            'hl.dsp.window.move({ workspace = "6", follow = false, window = "address:0x123abc" })',
        ])
        self.assertEqual(run.call_args_list[1].args[0], [
            'hyprctl', 'dispatch', 'hl.dsp.focus({ window = "address:0x123abc" })',
        ])

    @mock.patch('helper.focus_window')
    @mock.patch('helper.time.sleep')
    @mock.patch('helper.subprocess.Popen')
    @mock.patch('helper.spark_window')
    def test_cold_launch_reveals_window_after_it_appears(self, window, popen, sleep, focus):
        window.side_effect = [None, {'address': '0x123abc', 'workspace': {'name': 'spark-background'}}]
        open_spark()
        popen.assert_called_once()
        sleep.assert_called_once_with(0.5)
        focus.assert_called_once_with('0x123abc', True)


if __name__ == '__main__':
    unittest.main()
