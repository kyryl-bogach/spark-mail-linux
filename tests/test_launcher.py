import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_starts_wine_once_and_limits_the_browser_wrapper_to_the_desktop(self):
        with tempfile.TemporaryDirectory(prefix='spark test ') as temporary:
            root = self.make_root(temporary)
            fake_wine = root / 'fake-wine'
            calls = root / 'calls'
            wine_path = root / 'wine-path'
            fake_wine.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "$@" >> "$CALLS"\n'
                'printf "%s" "$PATH" > "$WINE_PATH"\n')
            fake_wine.chmod(0o755)
            environment = dict(os.environ, SPARK_ROOT=str(root), SPARK_CONTAINER='0',
                               SPARK_NOTIFY='0', SPARK_WINE=str(fake_wine), CALLS=str(calls),
                               WINE_PATH=str(wine_path))
            subprocess.run([ROOT / 'run-spark.sh'], env=environment,
                           check=True, capture_output=True)
            self.assertEqual(calls.read_text().splitlines(),
                             [str(root / 'app' / 'Spark Desktop.exe')])
            self.assertEqual(wine_path.read_text(), f'{root}/bin/host-tools:{os.environ["PATH"]}')

            calls.unlink()
            cli = next(root.glob('app/**/Foundation.dll')).with_name('spark.exe')
            cli.touch()
            subprocess.run([ROOT / 'run-spark.sh', '--help'],
                           env=dict(environment, SPARK_CLI='1'), check=True, capture_output=True)
            self.assertEqual(calls.read_text().splitlines(), [str(cli), '--help'])
            self.assertEqual(wine_path.read_text(), os.environ['PATH'])

    def test_missing_browser_helper_does_not_block_desktop_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            (root / 'bin' / 'open-host-url.py').unlink()
            fake_wine = root / 'fake-wine'
            calls = root / 'calls'
            fake_wine.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$1" >> "$CALLS"\n')
            fake_wine.chmod(0o755)
            environment = dict(os.environ, SPARK_ROOT=str(root), SPARK_CONTAINER='0',
                               SPARK_NOTIFY='0', SPARK_WINE=str(fake_wine), CALLS=str(calls))
            result = subprocess.run([ROOT / 'run-spark.sh'], env=environment,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls.read_text().splitlines(),
                             [str(root / 'app' / 'Spark Desktop.exe')])

    def make_root(self, temporary):
        root = Path(temporary)
        app = root / 'app'
        foundation = (app / 'resources' / 'app.asar.unpacked' / 'node_modules' /
                      '@readdle' / 'sparkcore-win' / 'bin' / 'Release' /
                      'SparkCore.bundle' / 'Foundation.dll')
        foundation.parent.mkdir(parents=True)
        foundation.write_bytes(b'sprkenv.dll\0sprkiphl.dll\0')
        (app / 'Spark Desktop.exe').touch()
        (app / 'sprkenv.dll').touch()
        (app / 'sprkiphl.dll').touch()
        (root / 'bin').mkdir()
        (root / 'bin' / 'open-host-url.py').write_bytes(
            (ROOT / 'bin' / 'open-host-url.py').read_bytes())
        return root

    def test_default_overrides_disable_powershell_probes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            fake_bin = root / 'fake-bin'
            fake_bin.mkdir()
            arguments = root / 'bwrap-arguments'
            bwrap = fake_bin / 'bwrap'
            bwrap.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$BWRAP_ARGUMENTS"\n')
            bwrap.chmod(0o755)
            environment = dict(
                os.environ,
                BWRAP_ARGUMENTS=str(arguments),
                PATH=f'{fake_bin}:{os.environ["PATH"]}',
                SPARK_NOTIFY='0',
                SPARK_ROOT=str(root),
                SPARK_WINE='/bin/true',
            )

            subprocess.run(
                [ROOT / 'run-spark.sh'], env=environment,
                check=True, capture_output=True, text=True)

            values = arguments.read_text().splitlines()
            override_index = values.index('WINEDLLOVERRIDES')
            overrides = values[override_index + 1]
            self.assertIn('powershell.exe,pwsh.exe=d', overrides)
            path_index = values.index('PATH')
            self.assertEqual(values[path_index + 1], f'{root}/bin/host-tools:{environment["PATH"]}')
            self.assertEqual(values[-1], str(root / 'app' / 'Spark Desktop.exe'))

    def test_direct_wine_fallback_keeps_launcher_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            fake_wine = root / 'fake-wine'
            result_file = root / 'wine-environment'
            fake_wine.write_text(
                '#!/bin/sh\nprintf "%s\\n%s\\n" "$WINEPREFIX" '
                '"$WINEDLLOVERRIDES" > "$RESULT_FILE"\n')
            fake_wine.chmod(0o755)
            environment = dict(
                os.environ,
                RESULT_FILE=str(result_file),
                SPARK_CONTAINER='0',
                SPARK_NOTIFY='0',
                SPARK_ROOT=str(root),
                SPARK_WINE=str(fake_wine),
            )

            subprocess.run(
                [ROOT / 'run-spark.sh'], env=environment,
                check=True, capture_output=True, text=True)

            values = result_file.read_text().splitlines()
            self.assertEqual(values[0], str(root / 'prefix'))
            self.assertIn('powershell.exe,pwsh.exe=d', values[1])

    def test_launcher_rejects_an_unpatched_foundation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            foundation = next(root.glob('app/**/Foundation.dll'))
            foundation.write_bytes(b'USERENV.dll\0IPHLPAPI.DLL\0')
            environment = dict(
                os.environ,
                SPARK_NOTIFY='0',
                SPARK_ROOT=str(root),
                SPARK_WINE='/bin/true',
            )

            result = subprocess.run(
                [ROOT / 'run-spark.sh'], env=environment,
                capture_output=True, text=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Foundation.dll still imports', result.stderr)

    def test_launcher_accepts_an_older_foundation_without_userenv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            foundation = next(root.glob('app/**/Foundation.dll'))
            foundation.write_bytes(b'IPHLPAPI.DLL\0')
            environment = dict(
                os.environ,
                PATH=f'{root / "fake-bin"}:{os.environ["PATH"]}',
                SPARK_NOTIFY='0',
                SPARK_ROOT=str(root),
                SPARK_WINE='/bin/true',
            )
            fake_bin = root / 'fake-bin'
            fake_bin.mkdir()
            bwrap = fake_bin / 'bwrap'
            bwrap.write_text('#!/bin/sh\nexit 0\n')
            bwrap.chmod(0o755)

            result = subprocess.run(
                [ROOT / 'run-spark.sh'], env=environment,
                capture_output=True, text=True)

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_disables_desktop_background_helpers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            (root / 'bin' / 'spark').write_bytes(
                (ROOT / 'bin' / 'spark').read_bytes())
            (root / 'bin' / 'spark').chmod(0o755)
            (root / 'run-spark.sh').write_bytes(
                (ROOT / 'run-spark.sh').read_bytes())
            (root / 'run-spark.sh').chmod(0o755)

            spark_cli = (root / 'app' / 'resources' / 'app.asar.unpacked' /
                         'node_modules' / '@readdle' / 'sparkcore-win' / 'bin' /
                         'Release' / 'SparkCore.bundle' / 'spark.exe')
            spark_cli.parent.mkdir(parents=True, exist_ok=True)
            spark_cli.touch()
            (root / 'spark.local.env').write_text(
                'SPARK_EXE="/missing/Spark Desktop.exe"\n')

            fake_wine = root / 'fake-wine'
            result_file = root / 'wine-environment'
            fake_wine.write_text(
                '#!/bin/sh\nprintf "%s\\n%s\\n" "$SPARK_NOTIFY" '
                '"$SPARK_CLOSE_TRAY" > "$RESULT_FILE"\n')
            fake_wine.chmod(0o755)
            environment = dict(
                os.environ,
                RESULT_FILE=str(result_file),
                SPARK_CONTAINER='0',
                SPARK_WINE=str(fake_wine),
            )

            subprocess.run(
                [root / 'bin' / 'spark', '--version'], env=environment,
                check=True, capture_output=True, text=True)

            self.assertEqual(result_file.read_text().splitlines(), ['0', '0'])

    def test_launcher_stops_tray_helper_when_wine_exits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            bin_dir = root / 'bin'
            tray_state = root / 'tray-state'
            tray_helper = bin_dir / 'close-tray.py'
            tray_helper.write_text(
                'import os\n'
                'from pathlib import Path\n'
                'import signal\n'
                'import sys\n'
                'import time\n'
                'state = Path(os.environ["TRAY_STATE"])\n'
                'def stop(*_):\n'
                '    state.write_text("stopped")\n'
                '    sys.exit(0)\n'
                'signal.signal(signal.SIGTERM, stop)\n'
                'state.write_text("ready")\n'
                'while True:\n'
                '    time.sleep(1)\n')
            fake_wine = root / 'fake-wine'
            fake_wine.write_text(
                '#!/bin/sh\n'
                'while [ "$(cat "$TRAY_STATE" 2>/dev/null)" != ready ]; do '
                'sleep 0.01; done\n')
            fake_wine.chmod(0o755)
            environment = dict(
                os.environ,
                SPARK_CONTAINER='0',
                SPARK_NOTIFY='0',
                SPARK_ROOT=str(root),
                SPARK_WINE=str(fake_wine),
                TRAY_STATE=str(tray_state),
            )

            subprocess.run(
                [ROOT / 'run-spark.sh'], env=environment,
                check=True, capture_output=True, text=True)

            self.assertEqual(tray_state.read_text(), 'stopped')


if __name__ == '__main__':
    unittest.main()
