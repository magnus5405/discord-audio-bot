# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: TUI-only console build (onedir). Run from repo root."""

import shutil
import struct
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

def _spec_dir() -> Path:
    sp = SPECPATH  # type: ignore[name-defined]
    if isinstance(sp, (list, tuple)):
        return Path(sp[0]).resolve()
    return Path(sp).resolve()


project_root = _spec_dir().parent
sys.path.insert(0, str(_spec_dir()))
from ensure_ffmpeg_windows import ensure_ffmpeg_binaries
entry_script = project_root / "src" / "tui_frozen_main.py"

_default_settings_src = project_root / "settings-example.json"
_bundle_settings_dir = project_root / "build" / "pyinstaller-data"
_bundle_settings_dir.mkdir(parents=True, exist_ok=True)
_bundle_settings_path = _bundle_settings_dir / "settings.json"
shutil.copyfile(_default_settings_src, _bundle_settings_path)

hiddenimports = (
    collect_submodules("textual")
    + collect_submodules("discord")
    + collect_submodules("google.cloud.speech_v1")
    + collect_submodules("google.cloud.speech_v2")
    + [
        "discord.ext.voice_recv",
        "discord.ext.commands",
        "google.genai",
        "elevenlabs",
        "pydub",
        "webrtcvad",
        "google.api_core",
        "grpc",
        "cryptography",
        "cryptography.fernet",
    ]
)

datas = collect_data_files("textual") + [(str(_bundle_settings_path), ".")]

_ffmpeg_bins = ensure_ffmpeg_binaries(project_root)

# discord.opus loads libopus from discord/bin/*.dll; PyInstaller does not ship that folder by default.
_discord_opus_bins: list[tuple[str, str]] = []
if sys.platform == "win32":
    import discord as _discord_for_opus

    _discord_root = Path(_discord_for_opus.__file__).resolve().parent
    _bitness = struct.calcsize("P") * 8
    _opus_name = f"libopus-0.{'x64' if _bitness > 32 else 'x86'}.dll"
    _opus_path = _discord_root / "bin" / _opus_name
    if _opus_path.is_file():
        _discord_opus_bins = [(str(_opus_path), "discord/bin")]

a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root)],
    binaries=_ffmpeg_bins + _discord_opus_bins,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DiscordAudioBotTUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_trace=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Keep libraries + bundled ``datas`` (e.g. ``settings.json``) next to the exe so
    # ``app_bundle_dir()`` matches where users expect ``.env`` / ``settings.json``.
    contents_directory=".",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["ffmpeg.exe", "ffprobe.exe", "libopus-0.x64.dll", "libopus-0.x86.dll"],
    name="DiscordAudioBotTUI",
)
