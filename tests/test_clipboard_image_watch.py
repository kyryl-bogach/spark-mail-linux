import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'bin' / 'clipboard-image-watch.py'
SPEC = importlib.util.spec_from_file_location('clipboard_image_watch', SCRIPT)
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)


class ClipboardImageWatchTests(unittest.TestCase):
    def test_acts_only_for_spark_xwayland_window(self):
        with patch.object(watch, 'output', return_value='{"class":"spark desktop.exe","xwayland":true}'):
            self.assertTrue(watch.spark_focused())
        with patch.object(watch, 'output', return_value='{"class":"spark desktop.exe","xwayland":false}'):
            self.assertFalse(watch.spark_focused())
        with patch.object(watch, 'output', return_value='{"class":"Other App","xwayland":true}'):
            self.assertFalse(watch.spark_focused())

    def test_preserves_mixed_clipboard_offers(self):
        with patch.object(watch, 'output', return_value='image/png\n'):
            self.assertTrue(watch.png_only())
        with patch.object(watch, 'output', return_value='image/png\ntext/html\n'):
            self.assertFalse(watch.png_only())
        with patch.object(watch, 'output', return_value='image/png\nimage/bmp\n'):
            self.assertFalse(watch.png_only())


if __name__ == '__main__':
    unittest.main()
