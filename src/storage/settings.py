"""Settings file loading and persistence."""

import json
import logging
from pathlib import Path
from typing import Optional, Any, Dict, List

from ..models import Persona

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH = Path("settings.json")


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
            with open(self.settings_path, "r") as f:
                self.settings = json.load(f)

            personas_data = self.settings.get("personas", [])
            self.personas = [
                Persona(
                    persona_id=p["id"],
                    display_name=p["name"],
                    system_instruction=p["system_instruction"],
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

            with open(self.settings_path, "w") as f:
                json.dump(self.settings, f, indent=2)

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
                "language_code": "da-DK",
                "alternative_language_codes": ["en-US", "en-GB"],
            },
        )

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
