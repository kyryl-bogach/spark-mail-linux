"""Check calendar reminders without calendar writes or live notifications."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from reminders import MAX_LATENESS_MS, Reminders


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = Reminders(root=Path(self.temporary.name) / 'installation',
                                 runtime=Path(self.temporary.name) / 'runtime')
        self.now = 1_791_300_000_000
        self.event = {'id': 'test-event', 'title': 'Test meeting', 'start_ms': self.now + 600000}
        self.active = set()
        self.notifications = []
        self.timers_output = '[]'
        self.schedule = mock.patch.object(self.manager, 'schedule', side_effect=self.scheduled).start()
        self.units = mock.patch.object(self.manager, 'active_units', side_effect=lambda: self.active.copy()).start()
        self.refresh = mock.patch.object(self.manager, 'refresh_indicator').start()
        self.process = mock.patch('reminders.subprocess.run', side_effect=self.run_command).start()
        self.addCleanup(mock.patch.stopall)

    def scheduled(self, record):
        self.active.add(record['unit'])

    def run_command(self, arguments, **options):
        if arguments[:3] == ['systemctl', '--user', 'stop']:
            self.active.discard(arguments[3].removesuffix('.timer'))
        if arguments[0] == 'omarchy-notification-send':
            self.notifications.append(arguments)
            return subprocess.CompletedProcess(arguments, 0, stdout='123\n')
        return subprocess.CompletedProcess(arguments, 0, stdout=self.timers_output)

    def record(self, lead):
        return next(record for record in self.manager.desired([self.event], self.now).values()
                    if record['lead'] == lead)

    def test_creates_two_exact_alerts_and_does_not_duplicate_a_refresh(self):
        first = self.manager.sync([self.event], self.now)
        second = self.manager.sync([self.event], self.now + 1000)
        self.assertEqual(first, {'scheduled': 2, 'cancelled': 0})
        self.assertEqual(second, {'scheduled': 0, 'cancelled': 0})
        records = [call.args[0] for call in self.schedule.call_args_list]
        self.assertEqual({record['fire_ms'] for record in records},
                         {self.event['start_ms'] - 300000, self.event['start_ms'] - 60000})

    def test_changed_time_cancels_old_timers_and_creates_new_timers(self):
        self.manager.sync([self.event], self.now)
        old_units = self.active.copy()
        updated = dict(self.event, start_ms=self.event['start_ms'] + 1800000)
        result = self.manager.sync([updated], self.now + 1000)
        self.assertEqual(result, {'scheduled': 2, 'cancelled': 2})
        self.assertTrue(self.active.isdisjoint(old_units))

    def test_changed_title_updates_pending_messages_without_new_timers(self):
        self.manager.sync([self.event], self.now)
        self.manager.sync([dict(self.event, title='Updated meeting')], self.now + 1000)
        self.assertEqual(self.schedule.call_count, 2)
        for unit in self.active:
            self.assertEqual(self.manager.read_record(unit)['title'], 'Updated meeting')
            self.assertIn('Updated meeting', (self.manager.messages / (unit + '.message')).read_text())

    def test_removed_event_cancels_only_our_reminders(self):
        unrelated = self.manager.messages / 'omarchy-reminder-5m-unrelated.message'
        unrelated.write_text('User reminder')
        self.manager.sync([self.event], self.now)
        result = self.manager.sync([], self.now + 1000)
        self.assertEqual(result['cancelled'], 2)
        self.assertEqual(self.active, set())
        self.assertTrue(unrelated.exists())

    def test_queue_is_limited_to_the_next_day_and_future_alerts(self):
        rows = [dict(self.event, id='past', start_ms=self.now - 1),
                dict(self.event, id='later', start_ms=self.now + 86400001),
                dict(self.event, id='soon', start_ms=self.now + 80000)]
        result = self.manager.sync(rows, self.now)
        self.assertEqual(result['scheduled'], 1)
        self.assertEqual(self.schedule.call_args.args[0]['lead'], 1)

    def test_fired_alert_survives_reload_and_a_clock_step_without_duplicate_delivery(self):
        self.manager.sync([self.event], self.now)
        record = self.record(5)
        self.assertTrue(self.manager.fire(record['unit'], record['fire_ms'] + 1000))
        self.assertFalse(self.manager.fire(record['unit'], record['fire_ms'] + 2000))
        self.active.discard(record['unit'])
        self.assertEqual(self.manager.sync([self.event], self.now)['scheduled'], 0)
        self.assertEqual(len(self.notifications), 1)

    def test_both_offsets_deliver_and_keep_the_calendar_action(self):
        self.manager.sync([self.event], self.now)
        for lead in (5, 1):
            record = self.record(lead)
            self.assertTrue(self.manager.fire(record['unit'], record['fire_ms']))
        self.assertEqual(len(self.notifications), 2)
        self.assertIn('Meeting in 5 minutes', self.notifications[0])
        self.assertIn('Meeting in 1 minute', self.notifications[1])
        self.assertTrue(all(arguments[-1] == 'open-calendar' for arguments in self.notifications))

    def test_late_alerts_and_started_events_do_not_notify(self):
        self.manager.sync([self.event], self.now)
        record = self.record(5)
        self.assertFalse(self.manager.fire(record['unit'], record['fire_ms'] + MAX_LATENESS_MS + 1))
        self.assertFalse(self.manager.fire(record['unit'], self.event['start_ms']))
        self.assertEqual(self.notifications, [])
        self.assertFalse((self.manager.messages / (record['unit'] + '.message')).exists())

    def test_missing_cancelled_record_does_not_notify(self):
        self.manager.sync([self.event], self.now)
        record = self.record(5)
        self.manager.clear()
        self.assertFalse(self.manager.fire(record['unit'], record['fire_ms']))
        self.assertEqual(self.notifications, [])

    def test_titles_are_data_and_cannot_be_notification_options(self):
        self.event['title'] = '--exec'
        self.manager.sync([self.event], self.now)
        record = self.record(5)
        self.manager.fire(record['unit'], record['fire_ms'])
        self.assertIn('Event: --exec', self.notifications[0])
        self.assertEqual(self.notifications[0].count('--exec'), 1)

    def test_runtime_records_and_native_labels_are_private(self):
        self.manager.sync([self.event], self.now)
        record = self.record(5)
        self.assertEqual(self.manager.record_path(record['unit']).stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.manager.messages / (record['unit'] + '.message')).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.manager.directory.stat().st_mode & 0o777, 0o700)

    def test_titles_cannot_add_notification_markup(self):
        self.event['title'] = '<b>Test</b> & notes'
        self.manager.sync([self.event], self.now)
        record = self.record(5)
        self.assertIn('&lt;b&gt;Test&lt;/b&gt;', (self.manager.messages / (record['unit'] + '.message')).read_text())
        self.manager.fire(record['unit'], record['fire_ms'])
        self.assertIn('Event: &lt;b&gt;Test&lt;/b&gt; &amp; notes', self.notifications[0])

    def test_native_schedule_preserves_absolute_time_and_keeps_titles_out_of_unit_arguments(self):
        record = dict(self.record(5), fire_ms=self.record(5)['fire_ms'] + 123)
        Reminders.schedule(self.manager, record)
        arguments = self.process.call_args.args[0]
        self.assertIn('--timer-property=AccuracySec=1s', arguments)
        self.assertTrue(any(argument.endswith('.123000 UTC') for argument in arguments))
        self.assertNotIn(self.event['title'], arguments)
        self.assertEqual(arguments[-2:], ['fire', record['unit']])

    def test_native_timer_list_filters_other_reminders(self):
        own = self.record(5)['unit']
        self.timers_output = json.dumps([{'unit': own + '.timer'}, {'unit': 'omarchy-reminder-5m-unrelated.timer'}])
        self.assertEqual(Reminders.active_units(self.manager), {own})

    def test_cancel_rejects_other_units(self):
        with self.assertRaises(ValueError):
            self.manager.cancel('omarchy-reminder-5m-unrelated')
        self.process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
