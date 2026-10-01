import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('host_browser', ROOT / 'bin' / 'open-host-url.py')
browser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser)


class HostBrowserTests(unittest.TestCase):
    def test_wine_browser_wrapper_forwards_web_links_as_one_argument(self):
        with tempfile.TemporaryDirectory(prefix='spark browser ') as temporary:
            root = Path(temporary)
            tools = root / 'bin' / 'host-tools'
            tools.mkdir(parents=True)
            wrapper = tools / 'xdg-open'
            wrapper.write_bytes((ROOT / 'bin' / 'host-tools' / 'xdg-open').read_bytes())
            wrapper.chmod(0o755)
            (root / 'bin' / 'open-host-url.py').write_text(
                'import json, os, sys\n'
                'from pathlib import Path\n'
                'Path(os.environ["RESULT"]).write_text(json.dumps(sys.argv[1:]))\n')
            result = root / 'result'
            url = 'https://example.test/?a="quoted"&b=$(touch%20oops)'
            subprocess.run([wrapper, url], env=dict(os.environ, RESULT=str(result)),
                           check=True, capture_output=True)
            self.assertEqual(json.loads(result.read_text()), [url])

    def test_accepts_web_links_without_shell_interpretation(self):
        for url in ['https://example.test/?x=a&y=b', 'http://example.test/',
                    'https://example.test/?x=$(touch%20oops)', 'https://example.test/#"quoted"']:
            self.assertTrue(browser.valid_url(url), url)

    def test_rejects_non_web_links_and_control_characters(self):
        for url in ['file:///etc/passwd', 'javascript:alert(1)', 'mailto:a@example.test',
                    '--help', 'https://', 'https://[invalid', 'https://example.test/\nsecret']:
            self.assertFalse(browser.valid_url(url), url)

    def test_errors_do_not_expose_the_url(self):
        url = 'https://example.test/oauth?code=secret'
        with mock.patch.object(browser.sys, 'argv', ['open-host-url.py', url]), \
                mock.patch.object(browser, 'open_url', side_effect=RuntimeError(url)), \
                self.assertRaises(SystemExit) as result:
            browser.main()
        self.assertNotIn('secret', str(result.exception))

    def test_rejected_url_never_reaches_the_portal(self):
        with mock.patch.object(browser.sys, 'argv', ['open-host-url.py', 'file:///secret']), \
                mock.patch.object(browser, 'open_url') as open_url, \
                self.assertRaises(SystemExit):
            browser.main()
        open_url.assert_not_called()

    def test_waits_for_the_portal_response_and_cleans_up(self):
        try:
            from gi.repository import Gio, GLib
        except ImportError:
            self.skipTest('python-gobject is unavailable')
        url = 'https://example.test/?x=a&y=b'
        for response_code in (0, 1, 2):
            with self.subTest(response_code=response_code):
                bus = mock.Mock()
                bus.get_unique_name.return_value = ':1.42'
                bus.call_sync.return_value = GLib.Variant(
                    '(o)', ('/org/freedesktop/portal/desktop/request/1_42/spark_token',))
                bus.signal_subscribe.return_value = 7
                loop = mock.Mock()
                loop.run.side_effect = lambda: bus.signal_subscribe.call_args.args[-1](
                    None, None, None, None, None, GLib.Variant('(ua{sv})', (response_code, {})))
                with mock.patch.object(Gio, 'bus_get_sync', return_value=bus), \
                        mock.patch.object(GLib, 'MainLoop', return_value=loop), \
                        mock.patch.object(GLib, 'timeout_add_seconds', return_value=8), \
                        mock.patch.object(GLib, 'source_remove') as remove, \
                        mock.patch.object(browser.uuid, 'uuid4') as token:
                    token.return_value.hex = 'token'
                    self.assertEqual(browser.open_url(url), response_code)
                parameters = bus.call_sync.call_args.args[4].unpack()
                self.assertEqual(parameters[1], url)
                self.assertFalse(parameters[2]['ask'])
                bus.signal_unsubscribe.assert_called_once_with(7)
                remove.assert_called_once_with(8)
                loop.quit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
