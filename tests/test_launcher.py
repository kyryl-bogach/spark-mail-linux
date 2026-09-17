import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
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
            (root / 'bin').mkdir()
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


if __name__ == '__main__':
    unittest.main()
