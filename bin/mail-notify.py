#!/usr/bin/env python3
"""Bridge Spark's incoming mail to native Linux notifications.

Wine does not display Windows toast notifications, so Spark's new-mail alerts
vanish silently. Spark still writes every synced message to a local SQLite
database, so this watcher polls that database and calls notify-send.

run-spark.sh starts this watcher. A flock guard keeps the OAuth callback path,
which also runs run-spark.sh, from starting a second copy.
"""
import fcntl
import glob
import os
import signal
import sqlite3
import subprocess
import sys
import time

ROOT = os.environ.get('SPARK_ROOT') or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, 'mail-notify.state')
LOCK = os.path.join(ROOT, 'mail-notify.lock')
POLL_SECONDS = int(os.environ.get('SPARK_POLL_SECONDS', '15'))

# Spark stores the database under the Wine user's AppData. The prefix user name
# follows the host user, so find it instead of hard-coding a name.
DB_GLOB = os.path.join(
    ROOT, 'prefix/drive_c/users/*/AppData/Local/Spark Desktop'
          '/core-data/databases/messages.sqlite')

MATCH = 'unseen = 1 AND inInbox = 1 AND inSent = 0'
NEW_ROWS = ('SELECT pk, messageFromMailbox, subject FROM messages '
            'WHERE ' + MATCH + ' AND pk > ? ORDER BY pk')
MAX_PK = 'SELECT COALESCE(MAX(pk), 0) FROM messages'


def find_db():
    for path in sorted(glob.glob(DB_GLOB)):
        if os.sep + 'Public' + os.sep not in path:
            return 'file:' + path + '?mode=ro'
    return None


def read_mark():
    try:
        with open(STATE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return -1  # first run: adopt the current maximum, notify nothing


def write_mark(mark):
    tmp = STATE + '.tmp'
    with open(tmp, 'w') as f:
        f.write(str(mark))
    os.replace(tmp, STATE)


def notify(sender, subject):
    # '--' guards against a subject that starts with '-', which notify-send
    # would otherwise read as an option and reject.
    subprocess.run(['notify-send', '-a', 'Spark', '-i', 'mail-unread', '--',
                    sender or 'Spark', subject or '(no subject)'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def poll(db, mark):
    """Notify for new matching rows and return the new watermark.

    The watermark advances only past rows the filter matched. Spark inserts a
    message row before it sets the inbox and unseen flags, so a watermark that
    tracked MAX(pk) over every row could step over a message during that gap
    and never notify for it.
    """
    try:
        con = sqlite3.connect(db, uri=True, timeout=2)
        try:
            if mark < 0:
                return con.execute(MAX_PK).fetchone()[0]
            rows = con.execute(NEW_ROWS, (mark,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return mark  # Spark is restarting or the database is busy; retry later
    for pk, sender, subject in rows:
        notify(sender, subject)
        mark = max(mark, pk)
    return mark


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    lock = open(LOCK, 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # another watcher already holds the lock
    mark = read_mark()
    while True:
        db = find_db()
        if db:
            new_mark = poll(db, mark)
            if new_mark != mark:
                mark = new_mark
                write_mark(mark)
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
