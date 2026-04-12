"""Ensure discord.py can load libopus on Windows frozen (PyInstaller) builds."""

from __future__ import annotations

import struct
import sys
from pathlib import Path


def load_discord_opus_if_frozen() -> None:
    """Load bundled ``discord/bin/libopus-0.*.dll`` when the default loader fails (e.g. PyInstaller)."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return

    import discord.opus as opus_mod

    if opus_mod.is_loaded():
        return

    target = "x64" if struct.calcsize("P") * 8 > 32 else "x86"
    name = f"libopus-0.{target}.dll"

    import discord

    pkg = Path(discord.__file__).resolve().parent
    meipass = getattr(sys, "_MEIPASS", None)
    candidates: list[Path] = [
        pkg / "bin" / name,
        Path(sys.executable).resolve().parent / "discord" / "bin" / name,
        Path(sys.executable).resolve().parent / "_internal" / "discord" / "bin" / name,
    ]
    if meipass:
        candidates.insert(1, Path(meipass) / "discord" / "bin" / name)

    for dll in candidates:
        if dll.is_file():
            opus_mod.load_opus(str(dll))
            return
