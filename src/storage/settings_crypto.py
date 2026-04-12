"""Fernet encryption for secrets persisted in ``settings.json`` (mandatory key)."""

from __future__ import annotations

import os
from typing import Any, Final

ENC_PREFIX: Final[str] = "enc:v1:"

# Keys under ``settings["api"]`` that are treated as secrets at rest.
API_SECRET_KEYS: Final[tuple[str, ...]] = (
    "google_gemini_api_key",
    "google_stt_api_key",
    "elevenlabs_api_key",
    "discord_token",
)

# Keys under ``settings["discord"]`` that are treated as secrets at rest.
DISCORD_SECRET_KEYS: Final[tuple[str, ...]] = ("token",)


def settings_load_requires_fernet_key(settings: dict[str, Any]) -> bool:
    """True when ``settings.json`` contains an ``enc:v1:`` blob that must be decrypted."""
    api = settings.get("api")
    if isinstance(api, dict):
        for key in API_SECRET_KEYS:
            v = api.get(key)
            if isinstance(v, str) and v.strip().startswith(ENC_PREFIX):
                return True
    discord = settings.get("discord")
    if isinstance(discord, dict):
        for key in DISCORD_SECRET_KEYS:
            v = discord.get(key)
            if isinstance(v, str) and v.strip().startswith(ENC_PREFIX):
                return True
    return False


def settings_save_requires_fernet_key(settings: dict[str, Any]) -> bool:
    """True when saving would encrypt a non-empty secret that is not already ``enc:v1:``."""
    api = settings.get("api")
    if isinstance(api, dict):
        for key in API_SECRET_KEYS:
            v = api.get(key)
            if not isinstance(v, str):
                continue
            s = v.strip()
            if not s or s.startswith(ENC_PREFIX):
                continue
            return True
    discord = settings.get("discord")
    if isinstance(discord, dict):
        for key in DISCORD_SECRET_KEYS:
            v = discord.get(key)
            if not isinstance(v, str):
                continue
            s = v.strip()
            if not s or s.startswith(ENC_PREFIX):
                continue
            return True
    return False


def require_settings_fernet():
    """Return Fernet for ``SETTINGS_SECRET_KEY`` or raise if missing / invalid."""
    raw = (os.getenv("SETTINGS_SECRET_KEY") or "").strip()
    if not raw:
        raise RuntimeError(
            "SETTINGS_SECRET_KEY is required (output of "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`). "
            "Set it in .env"
        )
    try:
        from cryptography.fernet import Fernet

        return Fernet(raw.encode("utf-8"))
    except Exception as exc:
        raise RuntimeError("SETTINGS_SECRET_KEY is not a valid Fernet key.") from exc


def _reject_plaintext_secret(key_path: str, value: Any) -> None:
    if not isinstance(value, str):
        return
    s = value.strip()
    if not s:
        return
    if s.startswith(ENC_PREFIX):
        return
    raise ValueError(
        f"Refusing to load plaintext secret at {key_path}. "
        "All persisted API keys and the Discord token must be stored encrypted (enc:v1:...). "
        "Save again from the TUI with SETTINGS_SECRET_KEY set, or encrypt using the same repo secret."
    )


def decrypt_settings_value(value: Any, fernet: Any | None) -> Any:
    """Decrypt a stored value; non-empty secrets must use ``enc:v1:`` prefix."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    if not s.startswith(ENC_PREFIX):
        return value
    if fernet is None:
        raise RuntimeError(
            "SETTINGS_SECRET_KEY is required (encrypted secrets in settings.json). "
            "Set it in .env (same as used when those values were saved)."
        )
    payload = s[len(ENC_PREFIX) :].encode("utf-8")
    try:
        return fernet.decrypt(payload).decode("utf-8")
    except Exception as exc:
        raise ValueError("Failed to decrypt a settings secret (wrong SETTINGS_SECRET_KEY?).") from exc


def encrypt_settings_value(value: Any, fernet: Any | None) -> Any:
    """Encrypt a plaintext secret for JSON storage."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    if s.startswith(ENC_PREFIX):
        return value
    if fernet is None:
        raise RuntimeError(
            "SETTINGS_SECRET_KEY is required to save API keys or the Discord token. "
            "Set it in .env"
        )
    token = fernet.encrypt(s.encode("utf-8")).decode("utf-8")
    return f"{ENC_PREFIX}{token}"


def decrypt_sensitive_blocks(settings: dict[str, Any], fernet: Any | None) -> None:
    """Decrypt secret fields in-place after loading JSON; rejects plaintext secrets."""
    api = settings.get("api")
    if isinstance(api, dict):
        for key in API_SECRET_KEYS:
            if key not in api:
                continue
            path = f'settings.api["{key}"]'
            _reject_plaintext_secret(path, api.get(key))
            api[key] = decrypt_settings_value(api.get(key), fernet)
    discord = settings.get("discord")
    if isinstance(discord, dict):
        for key in DISCORD_SECRET_KEYS:
            if key not in discord:
                continue
            path = f'settings.discord["{key}"]'
            _reject_plaintext_secret(path, discord.get(key))
            discord[key] = decrypt_settings_value(discord.get(key), fernet)


def encrypt_sensitive_blocks(settings: dict[str, Any], fernet: Any | None) -> None:
    """Encrypt secret fields in-place before writing JSON."""
    if fernet is None and not settings_save_requires_fernet_key(settings):
        return
    if fernet is None:
        fernet = require_settings_fernet()
    api = settings.get("api")
    if isinstance(api, dict):
        for key in API_SECRET_KEYS:
            if key in api:
                api[key] = encrypt_settings_value(api.get(key), fernet)
    discord = settings.get("discord")
    if isinstance(discord, dict):
        for key in DISCORD_SECRET_KEYS:
            if key in discord:
                discord[key] = encrypt_settings_value(discord.get(key), fernet)
