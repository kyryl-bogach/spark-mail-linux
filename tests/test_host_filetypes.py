"""Verify association updates without starting Wine or changing the live registry."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HostFiletypeTests(unittest.TestCase):
    def run_registration(self, export, fail=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'bin').mkdir()
            (root / 'share').mkdir()
            shutil.copy2(ROOT / 'bin/register-host-filetypes.sh', root / 'bin')
            shutil.copy2(ROOT / 'share/host-filetypes.reg', root / 'share')
            (root / 'source.reg').write_bytes(export)
            (root / 'run-spark.sh').write_text(
                '#!/usr/bin/env python3\n'
                'import os, sys\n'
                'from pathlib import Path\n'
                'root = Path(os.environ["SPARK_ROOT"])\n'
                'if sys.argv[1] == "-w":\n'
                '    print(sys.argv[2])\n'
                'elif sys.argv[1] == "export":\n'
                '    if os.environ.get("EXPORT_FAIL") == "1": sys.exit(1)\n'
                '    Path(sys.argv[3].replace(chr(92), "/")).write_bytes((root / "source.reg").read_bytes())\n'
                'else:\n'
                '    (root / "imported.reg").write_bytes(Path(sys.argv[2]).read_bytes())\n')
            (root / 'run-spark.sh').chmod(0o755)
            result = subprocess.run([root / 'bin/register-host-filetypes.sh'],
                                    env=dict(os.environ, EXPORT_FAIL='1' if fail else '0'),
                                    capture_output=True, text=True)
            imported = root / 'imported.reg'
            return result, imported.read_text() if imported.exists() else None

    def test_preserves_defaults_and_fills_empty_or_absent_associations(self):
        export = ('Windows Registry Editor Version 5.00\r\n'
                  '[HKEY_CLASSES_ROOT\\.DOCX]\r\n@="existing-office"\r\n'
                  '[HKEY_CLASSES_ROOT\\.pdf]\r\n@=""\r\n'
                  '[HKEY_CLASSES_ROOT\\.png]\r\n"Content Type"="image/png"\r\n'
                  '[HKEY_CLASSES_ROOT\\.txt\\subkey]\r\n@="unrelated"\r\n')
        result, imported = self.run_registration(export.encode('utf-16'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('[HKEY_CLASSES_ROOT\\.docx]', imported)
        for extension in ('pdf', 'png', 'txt', 'xlsx'):
            self.assertIn(f'[HKEY_CLASSES_ROOT\\.{extension}]', imported)

    def test_failed_export_never_imports_associations(self):
        result, imported = self.run_registration(b'REGEDIT4\n', fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(imported)

    def test_invalid_export_never_imports_associations(self):
        result, imported = self.run_registration(b'not registry data')
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(imported)

    def test_repeat_registration_preserves_installed_fallbacks(self):
        result, imported = self.run_registration(b'REGEDIT4\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        result, repeated = self.run_registration(imported.encode())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('[HKEY_CLASSES_ROOT\\.pdf]', repeated)
        self.assertNotIn('[HKEY_CLASSES_ROOT\\.docx]', repeated)
