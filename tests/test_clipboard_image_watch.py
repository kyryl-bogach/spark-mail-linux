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
        for mime in ('image/png', 'image/jpeg', 'image/gif', 'image/tiff', 'image/webp'):
            with self.subTest(mime=mime):
                self.assertEqual(watch.image_only_mime((mime,)), mime)

    def test_preserves_mixed_clipboard_offers(self):
        self.assertIsNone(watch.image_only_mime(('image/png', 'text/html')))
        self.assertIsNone(watch.image_only_mime(('image/png', 'image/bmp')))
        self.assertIsNone(watch.image_only_mime(('text/uri-list',)))

    def test_limits_attempts_until_the_offer_changes(self):
        png = ('image/png',)
        conversions, previous, attempts = 0, None, 0
        for _ in range(10):
            mime, attempts = watch.next_attempt(png, previous, attempts)
            previous = png
            conversions += mime is not None
        self.assertEqual(conversions, watch.MAX_ATTEMPTS)

        mime, attempts = watch.next_attempt(None, png, attempts)
        self.assertIsNone(mime)
        mime, attempts = watch.next_attempt(png, None, attempts)
        self.assertEqual((mime, attempts), ('image/png', 1))


if __name__ == '__main__':
    unittest.main()
