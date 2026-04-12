"""Tests for resolve_bot_reply_language_code (STT vs env)."""

from __future__ import annotations

import os
from unittest.mock import patch

from src.storage.reply_locale import resolve_bot_reply_language_code


class _FakeSettingsStore:
    def __init__(self, stt_language_code: str, reply_language: str = "") -> None:
        self._stt = stt_language_code
        self._reply_language = reply_language

    def get_stt_config(self) -> dict[str, object]:
        return {"language_code": self._stt, "alternative_language_codes": ["en-US"]}

    def get_runtime_config(self) -> dict[str, object]:
        return {"reply_language": self._reply_language}


def test_resolve_prefers_settings_override_over_stt_and_env() -> None:
    store = _FakeSettingsStore("de-DE", reply_language="en-US")
    with patch.dict(os.environ, {"BOT_REPLY_LANGUAGE": "fr-FR"}, clear=False):
        assert resolve_bot_reply_language_code(store) == "en-US"


def test_resolve_uses_env_over_stt_primary() -> None:
    store = _FakeSettingsStore("nb-NO")
    with patch.dict(os.environ, {"BOT_REPLY_LANGUAGE": "en-US"}, clear=False):
        for k in ("BOT_LANGUAGE",):
            os.environ.pop(k, None)
        assert resolve_bot_reply_language_code(store) == "en-US"


def test_resolve_bot_language_alias() -> None:
    store = _FakeSettingsStore("nb-NO")
    with patch.dict(os.environ, {"BOT_LANGUAGE": "en-GB"}, clear=False):
        os.environ.pop("BOT_REPLY_LANGUAGE", None)
        assert resolve_bot_reply_language_code(store) == "en-GB"


def test_resolve_env_when_stt_differs() -> None:
    store = _FakeSettingsStore("en-US")
    with patch.dict(os.environ, {"BOT_REPLY_LANGUAGE": "de-DE"}, clear=False):
        os.environ.pop("BOT_LANGUAGE", None)
        assert resolve_bot_reply_language_code(store) == "de-DE"


def test_resolve_no_env_uses_stt() -> None:
    store = _FakeSettingsStore("nb-NO")
    removed: dict[str, str] = {}
    for key in ("BOT_REPLY_LANGUAGE", "BOT_LANGUAGE"):
        if key in os.environ:
            removed[key] = os.environ.pop(key)
    try:
        assert resolve_bot_reply_language_code(store) == "nb-NO"
    finally:
        os.environ.update(removed)
