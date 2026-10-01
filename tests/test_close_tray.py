import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(proc_root):
    previous = os.environ.get('SPARK_PROC_ROOT')
    os.environ['SPARK_PROC_ROOT'] = str(proc_root)
    try:
        spec = importlib.util.spec_from_file_location(
            'close_tray', ROOT / 'bin' / 'close-tray.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            os.environ.pop('SPARK_PROC_ROOT', None)
        else:
            os.environ['SPARK_PROC_ROOT'] = previous
    return module


def fake_process(root, pid, command, prefix):
    process = root / str(pid)
    process.mkdir()
    (process / 'cmdline').write_bytes(b'\0'.join(command) + b'\0')
    (process / 'environ').write_bytes(os.fsencode('WINEPREFIX=' + str(prefix)) + b'\0')


class CloseTrayTests(unittest.TestCase):
    def test_selects_only_the_tray_window_of_the_verified_process(self):
        module = load_module('/unused')
        properties = [
            '_NET_CLIENT_LIST(WINDOW): window id # 0x10, 0x20, 0x30',
            '_NET_WM_PID(CARDINAL) = 10\nWM_CLASS(STRING) = "explorer.exe", "explorer.exe"',
            '_NET_WM_PID(CARDINAL) = 20\nWM_CLASS(STRING) = "explorer.exe", "explorer.exe"',
            '_NET_WM_PID(CARDINAL) = 10\nWM_CLASS(STRING) = "spark desktop.exe", "spark desktop.exe"',
        ]
        with mock.patch.object(module.subprocess, 'check_output', side_effect=properties):
            self.assertEqual(list(module.tray_windows(10)), [0x10])

    def test_sends_a_window_close_request_without_terminating_explorer(self):
        module = load_module('/unused')
        x11 = mock.Mock()
        x11.XOpenDisplay.return_value = 123
        x11.XInternAtom.side_effect = [100, 200]
        x11.XSendEvent.return_value = 1
        events = []

        def send(_display, window, _propagate, _mask, pointer):
            event = pointer._obj.client
            events.append((window, event.type, event.message_type, event.data[0]))
            return 1

        x11.XSendEvent.side_effect = send
        with mock.patch.object(module.ctypes, 'CDLL', return_value=x11), \
                mock.patch.object(module, 'tray_windows', return_value=[0x10]), \
                mock.patch.object(module.os, 'kill') as kill:
            self.assertTrue(module.hide_tray(10))
        self.assertEqual(events, [(0x10, 33, 100, 200)])
        kill.assert_not_called()
        x11.XCloseDisplay.assert_called_once_with(123)

    def test_main_preserves_the_clipboard_process(self):
        module = load_module('/unused')
        with mock.patch.object(module.sys, 'argv', ['close-tray.py', '/prefix']), \
                mock.patch.object(module, 'find_processes', return_value=(10, True)), \
                mock.patch.object(module.time, 'sleep'), \
                mock.patch.object(module, 'hide_tray', return_value=True) as hide, \
                mock.patch.object(module.os, 'kill') as kill:
            module.main()
        hide.assert_called_once_with(10)
        kill.assert_not_called()

    def test_finds_tray_and_renderer_only_in_requested_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prefix = root / 'prefix'
            other = root / 'other-prefix'
            fake_process(root, 10, [b'C:\\windows\\explorer.exe', b'/desktop'], prefix)
            fake_process(root, 11, [b'C:\\Spark Desktop.exe', b'--type=renderer'], prefix)
            fake_process(root, 12, [b'C:\\windows\\explorer.exe', b'/desktop'], other)

            module = load_module(root)

            self.assertEqual(module.find_processes(prefix), (10, True))
            self.assertEqual(module.find_processes(other), (12, False))


if __name__ == '__main__':
    unittest.main()
