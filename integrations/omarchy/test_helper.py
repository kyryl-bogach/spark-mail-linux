"""Use synthetic email data to check the CLI boundary."""
import unittest
from helper import parse_emails


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


if __name__ == '__main__':
    unittest.main()
