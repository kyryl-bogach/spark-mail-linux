"""Exercise update checks and failures without Wine, network, or mailbox writes."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('spark_update', ROOT / 'bin/spark-update.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


def asar(app, version='3.32.2.141404'):
    content = json.dumps({'fullVersion': version}).encode()
    tree = {'files': {'dist': {'files': {'config': {'files': {
        'default.json': {'offset': '0', 'size': len(content)}}}}}}}
    header = json.dumps(tree).encode()
    path = Path(app) / 'resources/app.asar'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<4I', 4, len(header) + 8, len(header) + 4, len(header)) + header + content)


def feed(version='3.32.2.141404', url=None):
    url = url or f'https://downloads.sparkmailapp.com/Spark3/win/dist/{version}/Spark.exe'
    return f'''<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"><channel><item>
    <enclosure url="{url}" sparkle:version="{version}" length="123" />
    </item></channel></rss>'''.encode()


class MetadataTests(unittest.TestCase):
    def test_numeric_versions_and_strict_format(self):
        self.assertGreater(update.version_key('3.32.10.1'), update.version_key('3.32.9.2'))
        for version in ('3.32.2', '../bad', '3.2.1.1;command'):
            with self.assertRaises(ValueError):
                update.version_key(version)

    def test_reads_full_version_from_asar(self):
        with tempfile.TemporaryDirectory() as app:
            asar(app)
            self.assertEqual(update.installed_version(app), '3.32.2.141404')

    def test_rejects_wrong_download_and_empty_feed(self):
        for data in (feed(url='https://example.test/Spark.exe'),
                     feed(url='https://downloads.sparkmailapp.com/Spark.dmg'), b'<rss/>'):
            with self.assertRaises(ValueError):
                update.release(data)

    @mock.patch.object(update, 'fetch')
    def test_current_newer_and_older_releases(self, fetch):
        with tempfile.TemporaryDirectory() as app:
            asar(app)
            for version, expected in [('3.32.2.141404', False), ('3.32.3.141500', True), ('3.32.1.141358', False)]:
                fetch.side_effect = [feed(version), f'Version {version}'.encode()]
                self.assertEqual(update.check(app)['available'], expected)
            fetch.side_effect = [feed(), b'Version 3.32.1.141358']
            with self.assertRaises(ValueError):
                update.check(app)

    @mock.patch.object(update.subprocess, 'check_output')
    def test_manifest_normalizes_windows_paths_and_rejects_escape(self, output):
        with tempfile.TemporaryDirectory() as app:
            (Path(app) / 'present').touch()
            output.return_value = './present\nresources\\missing\n'
            self.assertEqual(update.missing_entries('installer', app), ['resources\\missing'])
            for entry in ('../outside', '/outside', 'C:\\outside'):
                output.return_value = entry
                with self.assertRaises(ValueError):
                    update.missing_entries('installer', app)

    @mock.patch.object(update.subprocess, 'check_output')
    def test_imports_require_exact_known_functions(self, output):
        with tempfile.TemporaryDirectory() as app:
            app = Path(app)
            for name in ('sprkenv.dll', 'sprkiphl.dll', 'Spark Desktop.exe', f'{update.CORE}/spark.exe',
                         'resources.pak', 'snapshot_blob.bin', 'v8_context_snapshot.bin'):
                p = app / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch()
            imports = '''DLL Name: sprkenv.dll
 0041d1b0 <none> 0024 GetProfilesDirectoryW
 0041d1b8 <none> 0017 GetAllUsersProfileDirectoryW
DLL Name: sprkiphl.dll
 0041d080 <none> 0043 GetAdaptersAddresses
'''
            output.return_value = imports
            update.verify_imports(app)
            for bad in (imports.replace('GetAdaptersAddresses', 'OtherFunction'),
                        imports + ' 0041d088 <none> 0044 OtherFunction\n',
                        imports + 'DLL Name: USERENV.dll\n'):
                output.return_value = bad
                with self.assertRaises(ValueError):
                    update.verify_imports(app)

    @mock.patch.object(update.time, 'sleep')
    @mock.patch.object(update.os, 'kill')
    @mock.patch.object(update, 'owned_processes')
    def test_disconnected_prefix_process_gets_sigterm_after_grace_period(self, processes, kill, sleep):
        processes.side_effect = [[123]] * 51 + [[]]
        update.wait_stopped('/spark', '/spark/prefix')
        kill.assert_called_once_with(123, update.signal.SIGTERM)

    @mock.patch.object(update.time, 'sleep')
    @mock.patch.object(update.os, 'kill')
    @mock.patch.object(update, 'owned_processes', return_value=[123])
    def test_persistent_process_aborts_before_backup(self, processes, kill, sleep):
        with self.assertRaises(ValueError):
            update.wait_stopped('/spark', '/spark/prefix')
        kill.assert_called_once_with(123, update.signal.SIGTERM)

    def test_process_scope_excludes_other_prefixes(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            for pid, root, prefix in [(1, '/spark', '/spark/prefix'), (2, '/other', '/other/prefix'),
                                      (3, '/spark', '/other/prefix')]:
                directory = proc / str(pid)
                directory.mkdir()
                (directory / 'environ').write_bytes(f'SPARK_ROOT={root}\0WINEPREFIX={prefix}\0'.encode())
                (directory / 'cmdline').write_bytes(b'Spark Desktop.exe\0')
            self.assertEqual(update.owned_processes('/spark', '/spark/prefix', proc), [1])


class UpdaterShellTests(unittest.TestCase):
    def fixture(self, directory, available=True):
        root = Path(directory)
        (root / 'update-spark.sh').write_bytes((ROOT / 'update-spark.sh').read_bytes())
        (root / 'bin').mkdir()
        (root / 'app').mkdir()
        (root / 'prefix').mkdir()
        (root / 'app/original').write_text('keep')
        result = dict(available=available, installed='3.32.2.141404', version='3.32.3.141500',
                      url='https://downloads.sparkmailapp.com/Spark3/win/dist/3.32.3.141500/Spark.exe', size=2)
        (root / 'bin/spark-update.py').write_text('import json\nprint(' + repr(json.dumps(result)) + ')\n')
        fakebin = root / 'fakebin'
        fakebin.mkdir()
        for name in ('clang', 'objdump', 'systemd-run', 'hyprctl', 'bsdtar', 'wine', 'wineserver'):
            p = fakebin / name
            p.write_text('#!/bin/sh\nexit 99\n')
            p.chmod(0o755)
        return root, dict(os.environ, PATH=str(fakebin) + ':' + os.environ['PATH'])

    def run_script(self, root, env, *args):
        return subprocess.run(['bash', str(root / 'update-spark.sh'), *args], env=env,
                              capture_output=True, text=True, timeout=10)

    def prepared_fixture(self, directory):
        root, env = self.fixture(directory)
        (root / 'test-home').mkdir()
        (root / 'prefix/state').write_text('original state')
        (root / 'Foundation.original.dll').write_text('old foundation')
        (root / 'bin/spark-update.py').write_text(
            'import json, os, pathlib, sys\n'
            'cmd, *args = sys.argv[1:]\n'
            'if cmd == "check": print(' + repr(json.dumps(dict(available=True,
                installed='3.32.2.141404', version='3.32.3.141500',
                url='https://downloads.sparkmailapp.com/Spark3/win/dist/3.32.3.141500/Spark.exe', size=2))) + ')\n'
            'elif cmd == "version": print("3.32.3.141500")\n'
            'elif cmd == "verify" and args[0] == str(pathlib.Path(__file__).resolve().parents[1] / "app") and os.getenv("FAIL_VERIFY"):\n'
            ' sys.exit(1)\n')
        scripts = {
            'curl': '#!/bin/bash\nprintf MZ > "${@: -1}"\n',
            'bsdtar': '#!/bin/bash\nwhile [ "$1" != -C ]; do shift; done\nmkdir -p "$2"\nprintf new > "$2/new"\n',
            'systemctl': '#!/bin/sh\nexit 0\n',
            'systemd-run': '#!/bin/sh\nexit 0\n',
            'sleep': '#!/bin/sh\nexit 0\n',
            'mv': '#!/bin/bash\nif [ "${FAIL_PROMOTE:-}" = 1 ] && [[ "$1" == */archive/update-*/app ]]; then exit 1; fi\nexec /usr/bin/mv "$@"\n',
        }
        for name, content in scripts.items():
            path = root / 'fakebin' / name
            path.write_text(content)
            path.chmod(0o755)
        (root / 'shims').mkdir()
        (root / 'shims/build.sh').write_text('#!/bin/sh\ntouch "$OUT_DIR/sprkenv.dll" "$OUT_DIR/sprkiphl.dll"\n')
        (root / 'shims/build.sh').chmod(0o755)
        (root / 'shims/patch-foundation.py').write_text(
            'import os, pathlib\n'
            'if "SPARK_ROOT" in os.environ: (pathlib.Path(os.environ["SPARK_ROOT"]) / "Foundation.original.dll").write_text("new foundation")\n')
        (root / 'shims/patch-iphlpapi.py').write_text('')
        (root / 'run-spark.sh').write_text('#!/bin/sh\nif [ "${SPARK_WINESERVER:-}" = 1 ] && [ "$1" = -k ]; then exit 1; fi\nexit 0\n')
        (root / 'run-spark.sh').chmod(0o755)
        (root / 'bin/spark').write_text('#!/bin/sh\nprintf \'{"accounts": []}\\n\'\n')
        (root / 'bin/spark').chmod(0o755)
        return root, env

    def test_success_preserves_state_and_previous_app(self):
        with tempfile.TemporaryDirectory() as directory:
            root, env = self.prepared_fixture(directory)
            result = self.run_script(root, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / 'app/new').exists())
            backup = next((root / 'archive').glob('pre-update-*'))
            self.assertEqual((backup / 'app/original').read_text(), 'keep')
            self.assertEqual((root / 'prefix/state').read_text(), 'original state')
            self.assertEqual((backup / 'prefix/state').read_text(), 'original state')
            self.assertEqual((root / 'Foundation.original.dll').read_text(), 'new foundation')

    def test_failed_promotion_and_live_check_restore_previous_app(self):
        for failure in ('FAIL_PROMOTE', 'FAIL_VERIFY'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root, env = self.prepared_fixture(directory)
                result = self.run_script(root, dict(env, **{failure: '1'}))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((root / 'app/original').read_text(), 'keep')
                self.assertEqual((root / 'Foundation.original.dll').read_text(), 'old foundation')
                self.assertEqual((root / 'prefix/state').read_text(), 'original state')
                self.assertIn('previous application was restored', result.stderr)

    def test_current_version_does_not_download_or_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root, env = self.fixture(directory, available=False)
            result = self.run_script(root, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('is current', result.stdout)
            self.assertEqual(list((root / 'archive').iterdir()), [])

    def test_download_failure_preserves_app(self):
        with tempfile.TemporaryDirectory() as directory:
            root, env = self.fixture(directory)
            curl = root / 'fakebin/curl'
            curl.write_text('#!/bin/sh\nexit 22\n')
            curl.chmod(0o755)
            result = self.run_script(root, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / 'app/original').read_text(), 'keep')
            self.assertNotIn('Spark will stop', result.stdout)

    def test_custom_app_is_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root, env = self.fixture(directory)
            (root / 'spark.local.env').write_text('SPARK_APP=/different/app\n')
            result = self.run_script(root, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('repository app and prefix', result.stderr)
            self.assertFalse((root / 'archive').exists())
