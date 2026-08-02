"""Tests for settings-first runtime and secret resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from src.main import get_required_token, resolve_greet_on_join, resolve_reply_cooldown_seconds
from src.storage import SettingsStore
from src.storage.settings import default_local_stt_models_dir
from src.tts import resolve_elevenlabs_api_key


def _store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(settings_path=tmp_path / "settings.json")


def _write_json(path: Path, payload: dict[str, object]) -> str:
    text = json.dumps(payload, indent=2)
    path.write_text(text, encoding="utf-8")
    return text


def _fallback_payload(persona_id: str = "fallback") -> dict[str, object]:
    return {
        "personas": [
            {
                "id": persona_id,
                "name": f"{persona_id.title()} Bot",
                "system_instruction": "Be concise.",
                "genai_model": "gemini-2.5-flash",
                "elevenlabs_voice_id": "voice-id",
            }
        ],
        "ui": {
            "last_guild_id": None,
            "last_channel_id": None,
            "last_persona_id": persona_id,
        },
        "stt": {"language_code": "en-US"},
    }


def test_loads_settings_example_when_settings_json_missing(tmp_path: Path) -> None:
    _write_json(tmp_path / "settings-example.json", _fallback_payload())

    store = _store(tmp_path)

    assert [persona.persona_id for persona in store.personas] == ["fallback"]
    assert store.get_ui_preferences()["last_persona_id"] == "fallback"
    assert not (tmp_path / "settings.json").exists()


def test_save_after_settings_example_fallback_creates_settings_json(tmp_path: Path) -> None:
    template_path = tmp_path / "settings-example.json"
    original_template = _write_json(template_path, _fallback_payload())
    store = _store(tmp_path)

    store.update_ui_preference("last_persona_id", "saved")

    assert store.save() is True

    saved_path = tmp_path / "settings.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["ui"]["last_persona_id"] == "saved"
    assert template_path.read_text(encoding="utf-8") == original_template


def test_existing_settings_json_takes_precedence_over_template(tmp_path: Path) -> None:
    _write_json(tmp_path / "settings-example.json", _fallback_payload("template"))
    _write_json(tmp_path / "settings.json", _fallback_payload("persisted"))

    store = _store(tmp_path)

    assert [persona.persona_id for persona in store.personas] == ["persisted"]
    assert store.get_ui_preferences()["last_persona_id"] == "persisted"


def test_missing_settings_and_template_leaves_store_empty(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.settings == {}
    assert store.personas == []


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


def test_resolve_stt_provider_defaults_to_google_for_backward_compat(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.settings["stt"] = {"language_code": "da-DK", "speech_backend": "v2"}

    assert store.resolve_stt_provider() == "google"


def test_local_stt_settings_persist_and_use_default_models_dir(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bundle_dir = tmp_path / "bundle"

    with patch("src.storage.settings.app_bundle_dir", return_value=bundle_dir):
        store.set_stt_config(
            "da-DK",
            ["en-US"],
            provider="local",
            local_backend="whispercpp",
            local_model="small",
            local_models_dir="",
            update_backend_fields=True,
        )

        assert store.resolve_stt_provider() == "local"
        assert store.resolve_stt_local_backend() == "whispercpp"
        assert store.resolve_stt_local_model() == "small"
        assert store.resolve_stt_local_models_dir() is None
        assert store.resolve_stt_local_models_dir_path() == default_local_stt_models_dir()
        assert store.save() is True

    reloaded = _store(tmp_path)
    with patch("src.storage.settings.app_bundle_dir", return_value=bundle_dir):
        assert reloaded.resolve_stt_provider() == "local"
        assert reloaded.resolve_stt_local_model() == "small"
        assert reloaded.resolve_stt_local_models_dir_path() == bundle_dir / "stt-models"


def test_switching_between_google_and_local_preserves_provider_specific_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_stt_config(
        "da-DK",
        ["en-US"],
        provider="google",
        speech_backend="v2",
        google_application_credentials="C:\\service-account.json",
        project_id="settings-project",
        location="eu",
        model="chirp_3",
        update_backend_fields=True,
    )

    store.update_stt_config(
        provider="local",
        local_backend="whispercpp",
        local_model="base",
        local_models_dir="D:\\stt-models",
    )
    assert store.resolve_stt_provider() == "local"
    assert store.resolve_stt_project_id() == "settings-project"
    assert store.resolve_stt_model() == "chirp_3"
    assert store.resolve_stt_local_model() == "base"
    assert store.resolve_stt_local_models_dir() == "D:\\stt-models"

    store.update_stt_config(provider="google")
    assert store.resolve_stt_provider() == "google"
    assert store.resolve_stt_project_id() == "settings-project"
    assert store.resolve_stt_local_model() == "base"


def test_discord_server_id_prefers_settings_over_env(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_discord_config(
        token="",
        server_id="123456789",
    )

    with patch.dict(os.environ, {"DISCORD_SERVER_ID": "987654321"}, clear=False):
        assert store.resolve_discord_int("server_id", "DISCORD_SERVER_ID") == 123456789
