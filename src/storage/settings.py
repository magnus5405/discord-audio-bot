"""Settings file loading and persistence."""

import json
import logging
import os
from pathlib import Path
from typing import Optional, Any, Dict, List

from ..models import Persona

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH = Path("settings.json")
# Used when ``stt.language_code`` is missing or blank (BCP-47).
DEFAULT_STT_LANGUAGE_CODE = "en-US"


def repair_utf8_mojibake(text: str) -> str:
    """If *text* looks like UTF-8 mis-decoded as Latin-1, repair to proper Unicode.

    Common when ``settings.json`` is UTF-8 but was read with a legacy Windows code page.
    """
    if not text:
        return text
    if "\u00c3" not in text and "\u00c2" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return text


def _clean_optional_text(value: Any) -> str:
    """Normalize user-provided config strings from settings/env."""
    if value is None:
        return ""
    return str(value).strip().strip('"').strip("'")


def _set_clean_optional_text(mapping: Dict[str, Any], key: str, value: Any) -> None:
    """Write a trimmed optional string, deleting the key when the value is blank."""
    cleaned = _clean_optional_text(value)
    if cleaned:
        mapping[key] = cleaned
    elif key in mapping:
        del mapping[key]


class SettingsStore:
    """
    Loads and saves bot settings from JSON file.

    Manages personas, UI preferences, and STT language config.

    Phase 6: Settings management
    """

    def __init__(self, settings_path: Optional[Path] = None) -> None:
        """
        Initialize settings store.

        Args:
            settings_path: Path to settings.json
        """
        self.settings_path = settings_path or DEFAULT_SETTINGS_PATH
        self.settings: Dict[str, Any] = {}
        self.personas: List[Persona] = []

        if self.settings_path.exists():
            self.load()
        else:
            logger.warning(f"Settings file not found: {self.settings_path}")

    def load(self) -> bool:
        """Load settings from JSON file."""
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                self.settings = json.load(f)

            personas_data = self.settings.get("personas", [])
            self.personas = [
                Persona(
                    persona_id=p["id"],
                    display_name=repair_utf8_mojibake(str(p["name"])),
                    system_instruction=repair_utf8_mojibake(str(p["system_instruction"])),
                    genai_model=p["genai_model"],
                    elevenlabs_voice_id=p["elevenlabs_voice_id"],
                )
                for p in personas_data
            ]

            logger.info(f"Settings loaded: {len(self.personas)} personas")
            return True
        except Exception as e:
            logger.error(f"Failed to load settings: {e}", exc_info=True)
            return False

    def save(self) -> bool:
        """Save current settings to JSON file."""
        try:
            personas_data = [
                {
                    "id": p.persona_id,
                    "name": p.display_name,
                    "system_instruction": p.system_instruction,
                    "genai_model": p.genai_model,
                    "elevenlabs_voice_id": p.elevenlabs_voice_id,
                }
                for p in self.personas
            ]

            self.settings["personas"] = personas_data

            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)

            logger.info(f"Settings saved to {self.settings_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save settings: {e}", exc_info=True)
            return False

    def get_personalities(self) -> List[Persona]:
        """Get all available personas."""
        return self.personas

    def get_stt_config(self) -> Dict[str, Any]:
        """Get Speech-to-Text configuration."""
        return self.settings.get(
            "stt",
            {
                "language_code": DEFAULT_STT_LANGUAGE_CODE,
                "alternative_language_codes": ["en-US", "en-GB"],
                "speech_backend": "",
                "google_application_credentials": "",
                "project_id": "",
                "location": "",
                "model": "",
            },
        )

    def resolve_stt_api_key(self) -> str | None:
        """STT API key from settings first, then environment."""
        return self.resolve_api_secret("google_stt_api_key", "GOOGLE_STT_API_KEY")

    def resolve_stt_project_id(self) -> str | None:
        """STT v2 project id from settings first, then legacy API block, then environment."""
        stt = self.get_stt_config()
        value = _clean_optional_text(stt.get("project_id"))
        if value:
            return value
        return self.resolve_api_secret(
            "google_stt_project_id",
            "GOOGLE_STT_PROJECT_ID",
            "GOOGLE_CLOUD_PROJECT",
            "GCLOUD_PROJECT",
        )

    def resolve_stt_speech_backend(self) -> str | None:
        """STT backend selector from settings first, then environment."""
        stt = self.get_stt_config()
        value = _clean_optional_text(stt.get("speech_backend"))
        if value:
            return value
        return _clean_optional_text(os.getenv("GOOGLE_STT_SPEECH_BACKEND")) or None

    def resolve_stt_credentials_path(self) -> str | None:
        """Speech v2 service-account JSON path from settings first, then environment."""
        stt = self.get_stt_config()
        value = _clean_optional_text(stt.get("google_application_credentials"))
        if value:
            return value
        return _clean_optional_text(os.getenv("GOOGLE_APPLICATION_CREDENTIALS")) or None

    def resolve_stt_location(self) -> str | None:
        """Speech v2 location from settings first, then environment."""
        stt = self.get_stt_config()
        value = _clean_optional_text(stt.get("location"))
        if value:
            return value
        return _clean_optional_text(os.getenv("GOOGLE_STT_LOCATION")) or None

    def resolve_stt_model(self) -> str | None:
        """Speech v2 model from settings first, then environment."""
        stt = self.get_stt_config()
        value = _clean_optional_text(stt.get("model"))
        if value:
            return value
        return _clean_optional_text(os.getenv("GOOGLE_STT_MODEL")) or None

    def set_stt_config(
        self,
        language_code: str,
        alternative_language_codes: list[str],
        *,
        speech_backend: str | None = None,
        google_application_credentials: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
        model: str | None = None,
        update_backend_fields: bool = False,
    ) -> None:
        """Replace or merge the in-memory ``stt`` block (call ``save()`` to write ``settings.json``)."""
        stt = dict(self.get_stt_config())
        stt["language_code"] = language_code.strip() or DEFAULT_STT_LANGUAGE_CODE
        stt["alternative_language_codes"] = alternative_language_codes
        if update_backend_fields:
            _set_clean_optional_text(stt, "speech_backend", speech_backend)
            _set_clean_optional_text(
                stt,
                "google_application_credentials",
                google_application_credentials,
            )
            _set_clean_optional_text(stt, "project_id", project_id)
            _set_clean_optional_text(stt, "location", location)
            _set_clean_optional_text(stt, "model", model)
        self.settings["stt"] = stt
        logger.debug("STT config updated in memory")

    def update_stt_config(self, **values: Any) -> None:
        """Update only selected STT keys while preserving the rest of the block."""
        stt = dict(self.get_stt_config())
        for key, value in values.items():
            if key == "alternative_language_codes":
                stt[key] = list(value)
            elif key == "language_code":
                stt[key] = _clean_optional_text(value) or DEFAULT_STT_LANGUAGE_CODE
            else:
                _set_clean_optional_text(stt, key, value)
        self.settings["stt"] = stt
        logger.debug("STT config partially updated in memory")

    def apply_stt_api_secrets(
        self,
        *,
        google_stt_api_key: str | None = None,
        google_stt_project_id: str | None = None,
    ) -> None:
        """Merge STT secrets into ``api``; empty strings remove keys so ``.env`` applies again."""
        api = dict(self.get_api_config())
        updates = []
        if google_stt_api_key is not None:
            updates.append(("google_stt_api_key", google_stt_api_key))
        if google_stt_project_id is not None:
            updates.append(("google_stt_project_id", google_stt_project_id))
        for key, raw in updates:
            _set_clean_optional_text(api, key, raw)
        self.settings["api"] = api
        logger.debug("STT API secrets merged into api config")

    def get_runtime_config(self) -> Dict[str, Any]:
        """Get persisted runtime overrides that take precedence over ``.env``."""
        return self.settings.get("runtime", {})

    def set_runtime_config(
        self,
        *,
        reply_silence_seconds: float,
        reply_cooldown_seconds: float,
        mention_window_seconds: float,
        reply_language: str,
        greet_on_join: bool = True,
    ) -> None:
        """Replace the in-memory runtime overrides block."""
        self.settings["runtime"] = {
            "reply_silence_seconds": reply_silence_seconds,
            "reply_cooldown_seconds": reply_cooldown_seconds,
            "mention_window_seconds": mention_window_seconds,
            "reply_language": reply_language.strip(),
            "greet_on_join": greet_on_join,
        }
        logger.debug("Runtime config updated in memory")

    def update_runtime_config(self, **values: Any) -> None:
        """Update only selected runtime override keys."""
        runtime = dict(self.get_runtime_config())
        runtime.update(values)
        self.settings["runtime"] = runtime
        logger.debug("Runtime config partially updated in memory")

    def resolve_runtime_float(self, key: str, env_name: str, default: float) -> float:
        """Resolve a positive float from settings first, then environment, then default."""
        runtime = self.get_runtime_config()
        raw_value = runtime.get(key)
        if raw_value not in (None, ""):
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"settings.runtime.{key} must be a valid float.") from exc
            if value <= 0:
                raise ValueError(f"settings.runtime.{key} must be greater than zero.")
            return value

        env_value = os.getenv(env_name)
        if env_value is None:
            return default
        try:
            value = float(env_value)
        except ValueError as exc:
            raise ValueError(f"{env_name} must be a valid float.") from exc
        if value <= 0:
            raise ValueError(f"{env_name} must be greater than zero.")
        return value

    def resolve_runtime_text(self, key: str, *env_names: str) -> str | None:
        """Resolve a string override from settings first, then environment."""
        runtime = self.get_runtime_config()
        value = _clean_optional_text(runtime.get(key))
        if value:
            return value
        for env_name in env_names:
            env_value = _clean_optional_text(os.getenv(env_name))
            if env_value:
                return env_value
        return None

    def resolve_runtime_bool(
        self,
        key: str,
        env_name: str,
        *,
        default: bool = True,
    ) -> bool:
        """Resolve a boolean from settings first, then environment, then default."""
        runtime = self.get_runtime_config()
        raw_value = runtime.get(key)
        if raw_value is not None and raw_value != "":
            if isinstance(raw_value, bool):
                return raw_value
            if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
                return bool(raw_value)
            s = str(raw_value).strip().lower()
            if s in ("0", "false", "no", "off"):
                return False
            if s in ("1", "true", "yes", "on"):
                return True
            raise ValueError(f"settings.runtime.{key} must be a boolean-like value.")

        env_value = os.getenv(env_name)
        if env_value is None or env_value.strip() == "":
            return default
        return env_value.strip().lower() not in ("0", "false", "no", "off")

    def get_api_config(self) -> Dict[str, Any]:
        """Get persisted API/auth overrides that take precedence over ``.env``."""
        return self.settings.get("api", {})

    def set_api_config(
        self,
        *,
        google_gemini_api_key: str,
        google_stt_api_key: str,
        google_stt_project_id: str,
        elevenlabs_api_key: str,
        discord_token: str | None = None,
    ) -> None:
        """Replace the in-memory API/auth block."""
        self.settings["api"] = {
            "google_gemini_api_key": google_gemini_api_key.strip(),
            "google_stt_api_key": google_stt_api_key.strip(),
            "google_stt_project_id": google_stt_project_id.strip(),
            "elevenlabs_api_key": elevenlabs_api_key.strip(),
        }
        if discord_token is not None:
            self.settings["api"]["discord_token"] = discord_token.strip()
        logger.debug("API/auth config updated in memory")

    def update_api_config(self, **values: Any) -> None:
        """Update only selected API/auth keys."""
        api = dict(self.get_api_config())
        for key, value in values.items():
            api[key] = str(value).strip()
        self.settings["api"] = api
        logger.debug("API/auth config partially updated in memory")

    def resolve_api_secret(self, key: str, *env_names: str) -> str | None:
        """Resolve a secret from settings first, then environment."""
        api = self.get_api_config()
        value = _clean_optional_text(api.get(key))
        if value:
            return value
        for env_name in env_names:
            env_value = _clean_optional_text(os.getenv(env_name))
            if env_value:
                return env_value
        return None

    def get_discord_config(self) -> Dict[str, Any]:
        """Get persisted Discord-specific config that takes precedence over ``.env``."""
        return self.settings.get("discord", {})

    def set_discord_config(self, *, token: str, server_id: str) -> None:
        """Replace the in-memory Discord config block."""
        self.settings["discord"] = {
            "token": token.strip(),
            "server_id": server_id.strip(),
        }
        logger.debug("Discord config updated in memory")

    def update_discord_config(self, **values: Any) -> None:
        """Update only selected Discord config keys."""
        discord = dict(self.get_discord_config())
        for key, value in values.items():
            discord[key] = str(value).strip()
        self.settings["discord"] = discord
        logger.debug("Discord config partially updated in memory")

    def resolve_discord_secret(self, key: str, *env_names: str) -> str | None:
        """Resolve a Discord secret from settings first, then environment."""
        discord = self.get_discord_config()
        value = _clean_optional_text(discord.get(key))
        if value:
            return value
        if key == "token":
            legacy_value = _clean_optional_text(self.get_api_config().get("discord_token"))
            if legacy_value:
                return legacy_value
        for env_name in env_names:
            env_value = _clean_optional_text(os.getenv(env_name))
            if env_value:
                return env_value
        return None

    def resolve_discord_text(self, key: str, *env_names: str) -> str | None:
        """Resolve a Discord text value from settings first, then environment."""
        discord = self.get_discord_config()
        value = _clean_optional_text(discord.get(key))
        if value:
            return value
        for env_name in env_names:
            env_value = _clean_optional_text(os.getenv(env_name))
            if env_value:
                return env_value
        return None

    def resolve_discord_int(self, key: str, *env_names: str) -> int | None:
        """Resolve an optional integer Discord config value from settings first, then env."""
        raw = self.resolve_discord_text(key, *env_names)
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"Discord config {key} must be a valid integer.") from exc

    def get_pricing_config(self) -> Dict[str, float]:
        """USD rate card for live session cost estimates (merged with defaults)."""
        defaults: Dict[str, float] = {
            "elevenlabs_usd_per_1k_characters": 0.1,
            "genai_usd_per_1k_input_tokens": 0.25,
            "genai_usd_per_1k_output_tokens": 1.5,
            "google_stt_usd_per_minute": 0.016,
        }
        stored = self.settings.get("pricing")
        if not isinstance(stored, dict):
            return dict(defaults)
        merged = dict(defaults)
        for key in defaults:
            raw_value = stored.get(key)
            if raw_value in (None, ""):
                continue
            try:
                merged[key] = float(raw_value)
            except (TypeError, ValueError):
                logger.warning("Ignoring invalid settings.pricing.%s: %r", key, raw_value)
        return merged

    def set_pricing_config(
        self,
        *,
        elevenlabs_usd_per_1k_characters: float,
        genai_usd_per_1k_input_tokens: float,
        genai_usd_per_1k_output_tokens: float,
        google_stt_usd_per_minute: float,
    ) -> None:
        """Replace the in-memory pricing block (call ``save()`` to write ``settings.json``)."""
        self.settings["pricing"] = {
            "elevenlabs_usd_per_1k_characters": float(elevenlabs_usd_per_1k_characters),
            "genai_usd_per_1k_input_tokens": float(genai_usd_per_1k_input_tokens),
            "genai_usd_per_1k_output_tokens": float(genai_usd_per_1k_output_tokens),
            "google_stt_usd_per_minute": float(google_stt_usd_per_minute),
        }
        logger.debug("Pricing config updated in memory")

    def resolve_pricing_config(self) -> Dict[str, float]:
        """Non-negative USD rates: explicit ``settings.pricing`` value, else env, else default."""
        raw_block = self.settings.get("pricing")
        raw: Dict[str, Any] = raw_block if isinstance(raw_block, dict) else {}
        specs: list[tuple[str, str, float]] = [
            ("elevenlabs_usd_per_1k_characters", "ELEVENLABS_USD_PER_1K_CHARACTERS", 0.1),
            ("genai_usd_per_1k_input_tokens", "GENAI_USD_PER_1K_INPUT_TOKENS", 0.25),
            ("genai_usd_per_1k_output_tokens", "GENAI_USD_PER_1K_OUTPUT_TOKENS", 1.5),
            ("google_stt_usd_per_minute", "GOOGLE_STT_USD_PER_MINUTE", 0.016),
        ]
        resolved: Dict[str, float] = {}
        for key, env_name, default in specs:
            value: float | None = None
            if key in raw:
                inner = raw.get(key)
                if inner not in (None, ""):
                    try:
                        value = float(inner)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"settings.pricing.{key} must be a valid float.") from exc
                    if value < 0:
                        raise ValueError(f"settings.pricing.{key} must be zero or greater.")
            if value is None:
                env_raw = os.getenv(env_name)
                if env_raw is not None and str(env_raw).strip() != "":
                    try:
                        value = float(env_raw)
                    except ValueError as exc:
                        raise ValueError(f"{env_name} must be a valid float.") from exc
                    if value < 0:
                        raise ValueError(f"{env_name} must be zero or greater.")
            resolved[key] = float(default if value is None else value)
        return resolved

    def get_ui_preferences(self) -> Dict[str, Any]:
        """Get UI preferences."""
        return self.settings.get("ui", {})

    def update_ui_preference(self, key: str, value: Any) -> None:
        """Update a UI preference."""
        if "ui" not in self.settings:
            self.settings["ui"] = {}

        self.settings["ui"][key] = value
        logger.debug(f"UI preference updated: {key}={value}")

    def add_persona(self, persona: Persona) -> None:
        """Add a new persona to settings."""
        self.personas.append(persona)
        logger.debug(f"Persona added: {persona.display_name}")

    def remove_persona(self, persona_id: str) -> bool:
        """Remove a persona by ID."""
        for i, p in enumerate(self.personas):
            if p.persona_id == persona_id:
                self.personas.pop(i)
                logger.debug(f"Persona removed: {persona_id}")
                return True
        return False
