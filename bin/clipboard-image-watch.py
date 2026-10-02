#!/usr/bin/env python3
"""Add CF_DIB to PNG-only clipboard images while Spark has focus.

Wine exposes a Wayland PNG selection to Windows as a registered PNG format.
Spark's Chromium editor reads CF_DIB instead. The converter runs only when
Spark's XWayland window is active and the host offers only image/png.
"""

import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parent.parent
CONVERTER = ROOT / ".build/clipboard-image.exe.so"
INTERVAL = 0.6


def output(argv: list[str]) -> str:
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=2, check=True
        )
        return completed.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def spark_focused() -> bool:
    try:
        window = json.loads(output(["hyprctl", "activewindow", "-j"]))
    except json.JSONDecodeError:
        return False
    return window.get("xwayland") is True and window.get("class", "").lower() == "spark desktop.exe"


def png_only() -> bool:
    return output(["wl-paste", "--list-types"]).splitlines() == ["image/png"]


def main() -> None:
    if not CONVERTER.is_file():
        return
    env = os.environ.copy()
    env.update(
        SPARK_EXE=str(CONVERTER),
        SPARK_NOTIFY="0",
        SPARK_CLOSE_TRAY="0",
        SPARK_IMAGE_BRIDGE="0",
    )
    while True:
        if spark_focused() and png_only():
            try:
                subprocess.run(
                    [str(ROOT / "run-spark.sh")], env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=15, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
