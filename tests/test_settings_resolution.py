"""Tests for settings-first runtime and secret resolution."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from src.main import get_required_token, resolve_greet_on_join, resolve_reply_cooldown_seconds
from src.storage import SettingsStore
from src.tts import resolve_elevenlabs_api_key


def _store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(settings_path=tmp_path / "settings.json")


def test_reply_cooldown_prefers_settings_over_env(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_runtime_config(
        reply_silence_seconds=5.0,
        reply_cooldown_seconds=45.0,
        mention_window_seconds=30.0,
        reply_language="",
        greet_on_join=True,
    )

    with patch.dict(os.environ, {"BOT_REPLY_COOLDOWN_SECONDS": "999"}, clear=False):
        assert resolve_reply_cooldown_seconds(store) == 45.0


def test_greet_on_join_prefers_settings_over_env(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_runtime_config(
        reply_silence_seconds=5.0,
        reply_cooldown_seconds=180.0,
        mention_window_seconds=30.0,
        reply_language="",
        greet_on_join=False,
    )
    with patch.dict(os.environ, {"BOT_GREET_ON_JOIN": "true"}, clear=False):
        assert resolve_greet_on_join(store) is False


def test_greet_on_join_follows_env_without_settings_override(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with patch.dict(os.environ, {"BOT_GREET_ON_JOIN": "false"}, clear=False):
        assert resolve_greet_on_join(store) is False


def test_discord_token_prefers_settings_over_env(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_discord_config(
        token="settings-token",
        server_id="",
    )
    store.set_api_config(
        google_gemini_api_key="",
        google_stt_api_key="",
        google_stt_project_id="",
        elevenlabs_api_key="",
    )

    with patch.dict(os.environ, {"DISCORD_TOKEN": "env-token"}, clear=False):
        assert get_required_token(store) == "settings-token"


def test_elevenlabs_key_prefers_settings_over_env(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_discord_config(
        token="",
        server_id="",
    )
    store.set_api_config(
        google_gemini_api_key="",
        google_stt_api_key="",
        google_stt_project_id="",
        elevenlabs_api_key="settings-eleven",
    )

    with patch.dict(
        os.environ,
        {"ELEVENLABS_API_KEY": "env-primary", "ELEVEN_API_KEY": "env-fallback"},
        clear=False,
    ):
        assert resolve_elevenlabs_api_key(store) == "settings-eleven"


def test_resolve_stt_project_id_prefers_settings_over_env(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_stt_config(
        "da-DK",
        ["en-US"],
        project_id="settings-project",
        update_backend_fields=True,
    )

    with patch.dict(
        os.environ,
        {"GOOGLE_STT_PROJECT_ID": "env-project", "GOOGLE_CLOUD_PROJECT": "env-cloud-project"},
        clear=False,
    ):
        assert store.resolve_stt_project_id() == "settings-project"


def test_resolve_stt_api_key_prefers_settings_over_env(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_api_config(
        google_gemini_api_key="",
        google_stt_api_key="settings-stt-key",
        google_stt_project_id="",
        elevenlabs_api_key="",
    )
    with patch.dict(os.environ, {"GOOGLE_STT_API_KEY": "env-stt-key"}, clear=False):
        assert store.resolve_stt_api_key() == "settings-stt-key"


def test_resolve_stt_speech_backend_prefers_settings_over_env(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_stt_config("da-DK", ["en-US"], speech_backend="v1", update_backend_fields=True)
    with patch.dict(os.environ, {"GOOGLE_STT_SPEECH_BACKEND": "v2"}, clear=False):
        assert store.resolve_stt_speech_backend() == "v1"


def test_discord_server_id_prefers_settings_over_env(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_discord_config(
        token="",
        server_id="123456789",
    )

    with patch.dict(os.environ, {"DISCORD_SERVER_ID": "987654321"}, clear=False):
        assert store.resolve_discord_int("server_id", "DISCORD_SERVER_ID") == 123456789
