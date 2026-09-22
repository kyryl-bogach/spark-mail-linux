"""Use synthetic email data to check the CLI boundary."""
import unittest
from unittest import mock
from helper import focus_window, no_accounts, parse_emails


class ParserTests(unittest.TestCase):
    def table(self, fields):
        widths = [6, 24, 32, 18, 38, 0]
        def line(values):
            return '  ' + ''.join(value.ljust(width) for value, width in zip(values, widths))
        return '\n'.join([
            'Emails in Unified Inbox', '',
            line(['ID', 'Account', 'From', 'Date', 'Subject', 'Flags']),
            line(fields), '', 'Page 1 of 1 (1 total emails)',
        ])

    def test_columns_preserve_spaces_and_unicode(self):
        rows = parse_emails(self.table(['42', 'a@example.test', 'Renée Test',
                                       '2026-09-12 10:00', '<b>Two  spaces</b>', 'unread']))
        self.assertEqual(rows[0]['subject'], '<b>Two  spaces</b>')
        self.assertEqual(rows[0]['sender'], 'Renée Test')
        self.assertEqual(rows[0]['id'], '42')

    def test_error_is_not_an_empty_inbox(self):
        with self.assertRaises(ValueError):
            parse_emails('Access denied')

    def test_unknown_row_fails(self):
        with self.assertRaises(ValueError):
            parse_emails(self.table(['oops', '', '', '', '', '']))

    def test_empty_inbox(self):
        self.assertEqual(parse_emails('Emails in Unified Inbox\n\nNo emails found.'), [])
        self.assertEqual(parse_emails('No emails found.'), [])

    def test_capped_pagination_totals(self):
        output = self.table(['42', 'a@example.test', 'Test Sender',
                             '2026-09-12 10:00', 'Subject', 'unread'])
        output = output.replace('Page 1 of 1 (1 total emails)',
                                'Page 1 of 20+ (1000+ total emails)')
        self.assertEqual(len(parse_emails(output)), 1)

    def test_no_accounts_is_distinct_from_an_empty_inbox(self):
        self.assertTrue(no_accounts('No accounts found.\r\n'))
        self.assertFalse(no_accounts('No emails found.\r\n'))

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


if __name__ == '__main__':
    unittest.main()
