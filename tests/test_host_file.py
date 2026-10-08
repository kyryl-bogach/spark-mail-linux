import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('host_file', ROOT / 'bin' / 'open-host-file.py')
opener = importlib.util.module_from_spec(spec)
spec.loader.exec_module(opener)


class HostFileTests(unittest.TestCase):
    def test_wine_browser_wrapper_forwards_file_urls_as_one_argument(self):
        with tempfile.TemporaryDirectory(prefix='spark file ') as temporary:
            root = Path(temporary)
            tools = root / 'bin' / 'host-tools'
            tools.mkdir(parents=True)
            wrapper = tools / 'xdg-open'
            wrapper.write_bytes((ROOT / 'bin' / 'host-tools' / 'xdg-open').read_bytes())
            wrapper.chmod(0o755)
            (root / 'bin' / 'open-host-file.py').write_text(
                'import json, os, sys\n'
                'from pathlib import Path\n'
                'Path(os.environ["RESULT"]).write_text(json.dumps(sys.argv[1:]))\n')
            result = root / 'result'
            for argument in ['file:///tmp/Report%20"final"%20$(touch%20oops).pdf',
                             '/tmp/Report final $(touch oops).pdf']:
                with self.subTest(argument=argument):
                    subprocess.run([wrapper, argument], env=dict(os.environ, RESULT=str(result)),
                                   check=True, capture_output=True)
                    self.assertEqual(json.loads(result.read_text()), [argument])

    def test_resolves_file_urls_and_absolute_paths_to_existing_files(self):
        with tempfile.TemporaryDirectory(prefix='spark file ') as temporary:
            document = Path(temporary) / 'Report final.pdf'
            document.write_bytes(b'%PDF-')
            quoted = str(document).replace(' ', '%20')
            for argument in [str(document), f'file://{quoted}', f'FILE://{quoted}',
                             f'file://localhost{quoted}']:
                self.assertEqual(opener.file_path(argument), str(document), argument)

    def test_rejects_other_arguments(self):
        with tempfile.TemporaryDirectory(prefix='spark file ') as temporary:
            document = Path(temporary) / 'report.pdf'
            document.write_bytes(b'%PDF-')
            for argument in [temporary, f'file://{temporary}', 'report.pdf',
                             f'file://host{document}', f'{document}\nsecret',
                             'https://example.test/report.pdf', 'file:///missing.pdf', '--help']:
                self.assertIsNone(opener.file_path(argument), argument)

    def test_maps_container_paths_to_the_host(self):
        environ = {'HOME': '/home/user', 'SPARK_CONTAINER_HOME': '/srv/spark/test-home',
                   'SPARK_CONTAINER_TMP': '/srv/spark/tmp', 'SPARK_DOWNLOADS_DIR': '/data/dl'}
        cases = {
            '/tmp/a.pdf': '/srv/spark/tmp/a.pdf',
            '/tmpx/a.pdf': '/tmpx/a.pdf',
            '/home/user/Downloads/a.pdf': '/data/dl/a.pdf',
            '/home/user/.cache/a.pdf': '/srv/spark/test-home/.cache/a.pdf',
            '/home/userx/a.pdf': '/home/userx/a.pdf',
            '/srv/spark/prefix/drive_c/users/user/Temp/a.pdf': '/srv/spark/prefix/drive_c/users/user/Temp/a.pdf',
        }
        for path, expected in cases.items():
            self.assertEqual(opener.host_path(path, environ), expected, path)
        without_mount = dict(environ, SPARK_DOWNLOADS_DIR='')
        self.assertEqual(opener.host_path('/home/user/Downloads/a.pdf', without_mount),
                         '/srv/spark/test-home/Downloads/a.pdf')
        self.assertEqual(opener.host_path('/tmp/a.pdf', {'HOME': '/home/user'}), '/tmp/a.pdf')

    def test_explicit_binds_under_home_keep_their_host_paths(self):
        environ = {'HOME': '/home/user', 'SPARK_CONTAINER_HOME': '/srv/spark/test-home',
                   'SPARK_CONTAINER_TMP': '/srv/spark/tmp',
                   'SPARK_ROOT': '/home/user/Projects/spark',
                   'WINEPREFIX': '/home/user/wine-prefix', 'SPARK_APP': '/home/user/spark-app'}
        for mount in ('SPARK_ROOT', 'WINEPREFIX', 'SPARK_APP'):
            path = environ[mount] + '/report.pdf'
            self.assertEqual(opener.host_path(path, environ), path)
        self.assertEqual(opener.host_path('/tmp/../home/user/report.pdf', environ),
                         '/srv/spark/test-home/report.pdf')

    def test_symlink_to_downloads_maps_to_the_download_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'home'
            downloads = home / 'Downloads'
            downloads.mkdir(parents=True)
            document = downloads / 'report.pdf'
            document.touch()
            link = root / 'prefix-downloads'
            link.symlink_to(downloads, target_is_directory=True)
            environment = {'HOME': str(home), 'SPARK_CONTAINER_HOME': '/srv/overlay',
                           'SPARK_DOWNLOADS_DIR': '/srv/host-downloads'}
            path = opener.file_path(str(link / 'report.pdf'))
            self.assertEqual(opener.host_path(path, environment), '/srv/host-downloads/report.pdf')

    def test_rejects_encoded_controls_and_url_suffixes(self):
        with tempfile.TemporaryDirectory() as temporary:
            document = Path(temporary) / 'report\nsecret.pdf'
            document.touch()
            self.assertIsNone(opener.file_path(document.as_uri()))
            for suffix in ('?query', '#fragment'):
                self.assertIsNone(opener.file_path(document.as_uri() + suffix))

    def test_service_treats_dollar_characters_literally_and_suppresses_output(self):
        path = '/tmp/report ${HOME}.pdf'
        with mock.patch.object(opener.subprocess, 'run') as run:
            opener.open_file(path)
        command = run.call_args.args[0]
        self.assertEqual(command[-1], path)
        self.assertIn('--expand-environment=no', command)
        self.assertIn('--property=StandardOutput=null', command)
        self.assertIn('--property=StandardError=null', command)
        self.assertEqual(run.call_args.kwargs['timeout'], 10)

    def test_starts_the_host_xdg_open_through_the_user_manager(self):
        with tempfile.TemporaryDirectory(prefix='spark file ') as temporary:
            root = Path(temporary)
            fake_bin = root / 'fake-bin'
            fake_bin.mkdir()
            calls = root / 'calls'
            (fake_bin / 'systemd-run').write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$CALLS"\n')
            (fake_bin / 'systemd-run').chmod(0o755)
            document = root / 'tmp' / 'Report final.pdf'
            document.parent.mkdir()
            document.write_bytes(b'%PDF-')
            environment = dict(os.environ, CALLS=str(calls),
                               PATH=f'{fake_bin}:{os.environ["PATH"]}',
                               SPARK_CONTAINER_TMP='/srv/spark/tmp')
            environment.pop('SPARK_CONTAINER_HOME', None)
            environment.pop('SPARK_DOWNLOADS_DIR', None)
            result = subprocess.run(
                [ROOT / 'bin' / 'open-host-file.py', f'file://{root}/tmp/Report%20final.pdf'],
                env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = str(document)
            if expected.startswith('/tmp/'):
                expected = '/srv/spark/tmp' + expected[len('/tmp'):]
            self.assertEqual(calls.read_text().splitlines(),
                             ['--user', '--collect', '--quiet', '--service-type=exec',
                              '--expand-environment=no', '--property=StandardOutput=null',
                              '--property=StandardError=null', '--description=Spark host open',
                              '--', '/usr/bin/xdg-open', expected])

    def test_errors_do_not_expose_the_path(self):
        with tempfile.TemporaryDirectory(prefix='spark file ') as temporary:
            document = Path(temporary) / 'secret-contract.pdf'
            document.write_bytes(b'%PDF-')
            with mock.patch.object(opener.sys, 'argv', ['open-host-file.py', str(document)]), \
                    mock.patch.object(opener, 'open_file', side_effect=RuntimeError(str(document))), \
                    self.assertRaises(SystemExit) as result:
                opener.main()
            self.assertNotIn('secret', str(result.exception))

    def test_rejected_argument_never_starts_a_service(self):
        with mock.patch.object(opener.sys, 'argv', ['open-host-file.py', 'https://example.test/']), \
                mock.patch.object(opener, 'open_file') as open_file, \
                self.assertRaises(SystemExit):
            opener.main()
        open_file.assert_not_called()


if __name__ == '__main__':
    unittest.main()
