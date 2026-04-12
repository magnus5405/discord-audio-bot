"""Pytest configuration: Fernet key required for SettingsStore in tests."""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _settings_secret_key_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test process gets a valid SETTINGS_SECRET_KEY unless already set."""
    if not (os.getenv("SETTINGS_SECRET_KEY") or "").strip():
        monkeypatch.setenv("SETTINGS_SECRET_KEY", Fernet.generate_key().decode("utf-8"))
