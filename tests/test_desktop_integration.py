import configparser
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def desktop_file(path):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read(path)
    return parser['Desktop Entry']


def auth_callback_module():
    spec = importlib.util.spec_from_file_location(
        'auth_callback', ROOT / 'bin' / 'auth-callback.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopIntegrationTests(unittest.TestCase):
    def test_current_hyprland_rule_hides_only_the_wine_tray_helper(self):
        rule = (ROOT / 'share' / 'hyprland-spark-tray.lua').read_text()

        self.assertIn('class = "^explorer[.]exe$"', rule)
        self.assertIn('title = "^$"', rule)
        self.assertIn('xwayland = true', rule)
        self.assertIn('float = true', rule)
        self.assertIn('workspace = "special:spark-tray silent"', rule)
        self.assertIn('no_initial_focus = true', rule)
        self.assertNotIn('spark desktop.exe$', rule)

    def test_callback_allowlist_matches_registered_schemes(self):
        module = auth_callback_module()

        entry = desktop_file(ROOT / 'share' / 'spark-mail-linux-auth.desktop.in')
        registered = {
            value.removeprefix('x-scheme-handler/')
            for value in entry['MimeType'].split(';') if value
        }
        self.assertEqual(module.ALLOWED_SCHEMES, registered)
        self.assertIn('hotmail.com.readdle.smartmail.desktop', registered)
        self.assertIn('msauth.com.readdle.smartmail.desktop', registered)
        self.assertIn('yahoo.com.readdle.smartmail.desktop', registered)
        self.assertIn('spark-mail-url', registered)

    def test_installer_creates_visible_launcher_and_hidden_handler(self):
        with tempfile.TemporaryDirectory() as data_home:
            fake_bin = Path(data_home) / 'bin'
            fake_bin.mkdir()
            mime_calls = Path(data_home) / 'mime-calls'
            xdg_mime = fake_bin / 'xdg-mime'
            xdg_mime.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$MIME_CALLS"\n')
            xdg_mime.chmod(0o755)
            environment = dict(
                os.environ,
                XDG_DATA_HOME=data_home,
                MIME_CALLS=str(mime_calls),
                PATH=f'{fake_bin}:{os.environ["PATH"]}',
            )
            subprocess.run(
                [ROOT / 'install-handler.sh'], env=environment,
                check=True, capture_output=True, text=True)

            applications = Path(data_home) / 'applications'
            launcher = desktop_file(applications / 'spark-mail-linux.desktop')
            handler = desktop_file(applications / 'spark-mail-linux-auth.desktop')

            self.assertNotIn('NoDisplay', launcher)
            self.assertEqual(launcher['Exec'], f'"{ROOT}/run-spark.sh"')
            self.assertEqual(launcher['StartupWMClass'], 'spark desktop.exe')
            self.assertEqual(handler['NoDisplay'], 'true')
            calls = mime_calls.read_text().splitlines()
            self.assertEqual(len(calls), 11)
            self.assertTrue(all(
                call.startswith('default spark-mail-linux-auth.desktop '
                                'x-scheme-handler/')
                for call in calls))

    def test_callback_logs_only_scheme_and_forwards_through_launcher(self):
        module = auth_callback_module()
        secret_url = 'oauth.redirect.com.readdle.smartmail://return?code=secret'
        completed = subprocess.CompletedProcess([], 0)
        with tempfile.TemporaryDirectory() as root:
            module.ROOT = root
            with mock.patch.object(sys, 'argv', ['auth-callback.py', secret_url]), \
                    mock.patch.object(module.subprocess, 'run', return_value=completed) as run:
                with self.assertRaises(SystemExit) as exit_result:
                    module.main()

            self.assertEqual(exit_result.exception.code, 0)
            log = (Path(root) / 'auth-callback.log').read_text()
            self.assertIn('scheme=oauth.redirect.com.readdle.smartmail', log)
            self.assertNotIn('secret', log)
            command = run.call_args.args[0]
            self.assertEqual(command[-2:], ['--win-open-url', secret_url])

    def test_callback_rejects_unknown_scheme_before_launch(self):
        module = auth_callback_module()
        with mock.patch.object(sys, 'argv', ['auth-callback.py', 'https://example.test']), \
                mock.patch.object(module.subprocess, 'run') as run:
            with self.assertRaises(SystemExit):
                module.main()
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
