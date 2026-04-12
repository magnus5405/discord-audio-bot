"""Resolve install / working directory for config and logs (PyInstaller vs dev)."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv


def app_bundle_dir() -> Path:
    """Directory for user config beside the exe when frozen; cwd when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def load_application_dotenv() -> None:
    """Load ``.env`` from the bundle dir first, then cwd (fills gaps, does not override)."""
    load_dotenv(app_bundle_dir() / ".env")
    load_dotenv()
