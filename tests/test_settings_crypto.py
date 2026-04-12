"""Tests for mandatory settings.json secret encryption."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from src.storage import SettingsStore
from src.storage.settings_crypto import (
    ENC_PREFIX,
    decrypt_sensitive_blocks,
    encrypt_sensitive_blocks,
)


def test_roundtrip_encrypt_decrypt_in_memory() -> None:
    key = Fernet.generate_key()
    f = Fernet(key)
    settings = {
        "api": {
            "google_gemini_api_key": "secret-gemini",
            "elevenlabs_api_key": "",
        },
        "discord": {"token": "secret-discord"},
    }
    encrypt_sensitive_blocks(settings, f)
    assert settings["api"]["google_gemini_api_key"].startswith(ENC_PREFIX)
    assert settings["discord"]["token"].startswith(ENC_PREFIX)
    decrypt_sensitive_blocks(settings, f)
    assert settings["api"]["google_gemini_api_key"] == "secret-gemini"
    assert settings["discord"]["token"] == "secret-discord"


def test_save_writes_encrypted_when_env_key_set(tmp_path: Path) -> None:
    key = Fernet.generate_key().decode("utf-8")
    path = tmp_path / "settings.json"
    with patch.dict(os.environ, {"SETTINGS_SECRET_KEY": key}, clear=False):
        store = SettingsStore(settings_path=path)
        store.set_api_config(
            google_gemini_api_key="k1",
            google_stt_api_key="k2",
            google_stt_project_id="",
            elevenlabs_api_key="k3",
        )
        store.set_discord_config(token="dt", server_id="")
        assert store.save() is True

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["api"]["google_gemini_api_key"].startswith(ENC_PREFIX)
    assert raw["discord"]["token"].startswith(ENC_PREFIX)

    with patch.dict(os.environ, {"SETTINGS_SECRET_KEY": key}, clear=False):
        store2 = SettingsStore(settings_path=path)
        assert store2.resolve_api_secret("google_gemini_api_key", "GOOGLE_GEMINI_API_KEY") == "k1"
        assert store2.resolve_discord_secret("token", "DISCORD_TOKEN") == "dt"


def test_load_rejects_plaintext_secrets(tmp_path: Path) -> None:
    key = Fernet.generate_key().decode("utf-8")
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "personas": [],
                "api": {"google_gemini_api_key": "plaintext-not-allowed"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    with patch.dict(os.environ, {"SETTINGS_SECRET_KEY": key}, clear=False):
        try:
            SettingsStore(settings_path=path)
        except ValueError as exc:
            assert "plaintext" in str(exc).lower()
        else:
            raise AssertionError("expected ValueError")
