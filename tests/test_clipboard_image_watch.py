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

    def test_converts_supported_image_only_offers(self):
        for mime in ('image/png', 'image/jpeg', 'image/gif', 'image/tiff'):
            with self.subTest(mime=mime), patch.object(watch, 'output', return_value=mime + '\n'):
                self.assertEqual(watch.image_only_mime(), mime)

    def test_other_image_mime_uses_host_decoder(self):
        with patch.object(watch, 'output', return_value='image/webp\n'):
            self.assertEqual(watch.image_only_mime(), 'image/webp')

    def test_preserves_mixed_clipboard_offers(self):
        with patch.object(watch, 'output', return_value='image/png\ntext/html\n'):
            self.assertIsNone(watch.image_only_mime())
        with patch.object(watch, 'output', return_value='image/png\nimage/bmp\n'):
            self.assertIsNone(watch.image_only_mime())
        with patch.object(watch, 'output', return_value='text/uri-list\n'):
            self.assertIsNone(watch.image_only_mime())


if __name__ == '__main__':
    unittest.main()
