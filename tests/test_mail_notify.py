import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def mail_notify_module():
    spec = importlib.util.spec_from_file_location(
        'mail_notify', ROOT / 'bin' / 'mail-notify.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MailNotifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'messages.sqlite'
        connection = sqlite3.connect(self.database)
        connection.execute(
            'CREATE TABLE messages ('
            'pk INTEGER PRIMARY KEY, messageFromMailbox TEXT, subject TEXT, '
            'unseen INTEGER, inInbox INTEGER, inSent INTEGER)')
        connection.executemany(
            'INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)', [
                (1, 'Old sender', 'Old subject', 1, 1, 0),
                (2, 'Seen sender', 'Seen subject', 0, 1, 0),
                (3, 'Sent sender', 'Sent subject', 1, 1, 1),
            ])
        connection.commit()
        connection.close()
        self.uri = f'file:{self.database}?mode=ro'

    def tearDown(self):
        self.temp.cleanup()

    def test_first_poll_adopts_existing_max_without_notifications(self):
        module = mail_notify_module()
        with mock.patch.object(module, 'notify') as notify:
            mark = module.poll(self.uri, -1)
        self.assertEqual(mark, 3)
        notify.assert_not_called()

    def test_poll_notifies_only_new_unseen_inbox_messages(self):
        module = mail_notify_module()
        connection = sqlite3.connect(self.database)
        connection.executemany(
            'INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)', [
                (4, 'Inbox sender', 'Inbox subject', 1, 1, 0),
                (5, 'Read sender', 'Read subject', 0, 1, 0),
                (6, 'Archive sender', 'Archive subject', 1, 0, 0),
            ])
        connection.commit()
        connection.close()

        with mock.patch.object(module, 'notify') as notify:
            mark = module.poll(self.uri, 3)

        self.assertEqual(mark, 4)
        notify.assert_called_once_with('Inbox sender', 'Inbox subject')


if __name__ == '__main__':
    unittest.main()
