"""Provide sample data for UI screenshots. Never invoke Spark or schedule reminders."""
from datetime import datetime, timedelta
import json

now = datetime.now().astimezone()
tomorrow = (now + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
emails = [
    {'id': '101', 'sender': 'Design team', 'subject': 'Component review and next steps',
     'date': now.strftime('%Y-%m-%d %H:%M')},
    {'id': '102', 'sender': 'Project updates', 'subject': 'The release is ready for review',
     'date': (now - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M')},
    {'id': '103', 'sender': 'Workspace notes', 'subject': 'A longer subject that stays clear of the date',
     'date': (now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M')},
]
events = [
    {'title': 'Design review', 'time': '09:30 – 10:00', 'location': 'Room 3'},
    {'title': 'Daily team check-in', 'time': '10:30 – 10:45', 'location': 'Google Meet'},
    {'title': 'Weekly product planning', 'time': '14:00 – 15:00', 'location': ''},
]
print(json.dumps({'status': 'Inbox', 'emails': emails, 'events': events,
                  'events_label': 'Tomorrow', 'events_status': '',
                  'event_starts_ms': [int(tomorrow.timestamp() * 1000)],
                  'reminders_ok': True, 'reminder_status': ''}))
