"""Tests for ``src.runtime_opus``."""

from __future__ import annotations

import sys

import pytest


def test_load_discord_opus_skips_when_not_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    import importlib

    ro = importlib.import_module("src.runtime_opus")
    ro.load_discord_opus_if_frozen()


def test_load_discord_opus_skips_when_not_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(sys, "frozen", raising=False)

    import importlib

    ro = importlib.import_module("src.runtime_opus")
    ro.load_discord_opus_if_frozen()
