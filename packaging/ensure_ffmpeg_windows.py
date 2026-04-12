"""Download and cache FFmpeg essentials (ffmpeg.exe, ffprobe.exe) for Windows PyInstaller builds."""

from __future__ import annotations

import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

FFMPEG_ESSENTIALS_ZIP = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def ffmpeg_cache_dir(project_root: Path) -> Path:
    return project_root / "build" / "ffmpeg-win-cache"


def ensure_ffmpeg_binaries(project_root: Path) -> list[tuple[str, str]]:
    """Return PyInstaller ``binaries`` list entries for Windows; empty on other OS."""
    if sys.platform != "win32":
        return []

    cache = ffmpeg_cache_dir(project_root)
    cache.mkdir(parents=True, exist_ok=True)
    ffmpeg_dst = cache / "ffmpeg.exe"
    ffprobe_dst = cache / "ffprobe.exe"

    if ffmpeg_dst.is_file() and ffprobe_dst.is_file():
        return [
            (str(ffmpeg_dst), "."),
            (str(ffprobe_dst), "."),
        ]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "ffmpeg-essentials.zip"
        urllib.request.urlretrieve(FFMPEG_ESSENTIALS_ZIP, zip_path)
        extracted = tmp_path / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extracted)

        ff = next(extracted.rglob("ffmpeg.exe"), None)
        if ff is None or not ff.is_file():
            raise FileNotFoundError("ffmpeg.exe not found in FFmpeg essentials archive")
        probe = ff.parent / "ffprobe.exe"
        if not probe.is_file():
            raise FileNotFoundError("ffprobe.exe not found next to ffmpeg.exe in archive")

        shutil.copy2(ff, ffmpeg_dst)
        shutil.copy2(probe, ffprobe_dst)

    return [
        (str(ffmpeg_dst), "."),
        (str(ffprobe_dst), "."),
    ]
