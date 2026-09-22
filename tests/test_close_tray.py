import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


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
