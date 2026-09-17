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

    def test_launcher_rejects_an_unpatched_foundation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_root(temporary)
            foundation = next(root.glob('app/**/Foundation.dll'))
            foundation.write_bytes(b'unpatched')
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
            self.assertIn('Foundation.dll does not import', result.stderr)


if __name__ == '__main__':
    unittest.main()
