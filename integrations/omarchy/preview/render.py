#!/usr/bin/env python3
"""Capture the real widget and notification cards with a mock data source."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
IMAGES = ('omarchy-plugin.png', 'omarchy-plugin-indicators.png', 'omarchy-plugin-reminders.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/screenshots')
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    (ROOT / 'archive').mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='plugin-screenshots-', dir=ROOT / 'archive'))
    shell = Path('/usr/share/omarchy/shell')
    if not shell.is_dir():
        parser.error('Omarchy and a desktop session are required')
    for directory in shell.iterdir():
        if directory.is_dir() and directory.name != 'Ui':
            (stage / directory.name).symlink_to(directory, target_is_directory=True)
    ui = stage / 'Ui'
    ui.mkdir()
    for source in (shell / 'Ui').iterdir():
        if source.name == 'KeyboardPanel.qml':
            text = source.read_text().replace('  id: root', '  id: root\n  property alias previewCard: card', 1)
            (ui / source.name).write_text(text)
        else:
            (ui / source.name).symlink_to(source)
    (stage / 'notifications').symlink_to(shell / 'plugins/notifications', target_is_directory=True)
    widget = (ROOT / 'integrations/omarchy/BarWidget.qml').read_text()
    widget = widget.replace('  manageIpc: false', '  manageIpc: false\n  property alias previewPopup: popup', 1)
    plugin = stage / 'plugin'
    plugin.mkdir()
    (plugin / 'BarWidget.qml').write_text(widget)
    shutil.copy2(HERE / 'mock_helper.py', stage / 'mock_helper.py')
    shutil.copy2(HERE / 'shell.qml', stage / 'shell.qml')
    environment = dict(os.environ, SPARK_PREVIEW_OUT_DIR=str(stage))
    process = subprocess.Popen(['quickshell', '-p', str(stage / 'shell.qml'), '--no-color'],
                               env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise SystemExit(f'Screenshot preview timed out. Temporary files: {stage}')
    (stage / 'preview.log').write_text(output)
    if process.returncode or any(term in output for term in ('ReferenceError', 'TypeError', 'Binding loop', 'CAPTURE_FAILED')):
        raise SystemExit(f'Screenshot preview failed. Inspect {stage / "preview.log"}')
    for name in IMAGES:
        image = stage / name
        if not image.is_file() or image.stat().st_size > 1024 * 1024:
            raise SystemExit(f'Missing or oversized screenshot: {name}. Inspect {stage}')
        shutil.copy2(image, options.output / name)
        print(options.output / name)


if __name__ == '__main__':
    main()
