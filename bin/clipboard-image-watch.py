#!/usr/bin/env python3
"""Add CF_DIB to image-only clipboard selections for Spark.

Wine exposes images to Windows without the DIB needed by Spark's editor.
The converter runs only when Spark has focus and one image type is offered.
"""

import binascii
import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parent.parent
CONVERTER = ROOT / ".build/clipboard-image.exe.so"
INTERVAL = 0.6
NATIVE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/tiff", "image/bmp"}
MAX_IMAGE_BYTES = 64 * 1024 * 1024


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


def image_only_mime() -> str | None:
    types = output(["wl-paste", "--list-types"]).splitlines()
    if len(types) == 1 and types[0].startswith("image/"):
        return types[0]
    return None


def png_from_host(mime: str) -> tuple[bytes, list[str]] | None:
    """Decode a nonnative image in memory and send PNG to the Wine helper."""
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        original = subprocess.run(
            ["wl-paste", "--type", mime], capture_output=True, timeout=5,
            check=True,
        ).stdout
        if not 0 < len(original) <= MAX_IMAGE_BYTES:
            return None
        loader = GdkPixbuf.PixbufLoader.new_with_mime_type(mime)
        loader.write(original)
        loader.close()
        pixbuf = loader.get_pixbuf()
        if pixbuf is None or pixbuf.get_width() > 8192 or pixbuf.get_height() > 8192:
            return None
        png = pixbuf.save_to_bufferv("png", [], [])[1]
        if not 0 < len(png) <= MAX_IMAGE_BYTES:
            return None
        crc = binascii.crc32(original)
        return png, ["--host-png", mime, str(len(original)), f"{crc:08x}"]
    except Exception:
        return None


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
        mime = image_only_mime() if spark_focused() else None
        if mime:
            try:
                converted = png_from_host(mime) if mime not in NATIVE_MIMES else None
                if mime not in NATIVE_MIMES and converted is None:
                    time.sleep(INTERVAL)
                    continue
                payload, args = converted if converted is not None else (None, [])
                subprocess.run(
                    [str(ROOT / "run-spark.sh"), *args], env=env, input=payload,
                    stdin=subprocess.DEVNULL if payload is None else None,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=15, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
