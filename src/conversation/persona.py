"""Persona management and configuration."""

import logging
from typing import Optional, List

from ..models import Persona

logger = logging.getLogger(__name__)


class PersonaManager:
    """
    Manages bot personas and system instructions.

    Loads personas from settings, applies current persona to chat,
    supports persona changes mid-session.

    Phase 4: Conversation + GenAI
    """

    def __init__(self, personas: Optional[List[Persona]] = None) -> None:
        """
        Initialize persona manager.

        Args:
            personas: List of available personas
        """
        self.personas = personas or []
        self.current_persona: Optional[Persona] = None
        logger.info(f"PersonaManager initialized with {len(self.personas)} personas")

    def add_persona(self, persona: Persona) -> None:
        """Add a persona to available list."""
        self.personas.append(persona)
        logger.debug(f"Persona added: {persona.display_name}")

    def get_persona(self, persona_id: str) -> Optional[Persona]:
        """Get persona by ID."""
        for p in self.personas:
            if p.persona_id == persona_id:
                return p
        return None

    def set_current_persona(self, persona_id: str) -> bool:
        """
        Switch to a different persona.

        Args:
            persona_id: ID of persona to switch to

        Returns:
            True if successful, False if not found
        """
        persona = self.get_persona(persona_id)
        if not persona:
            logger.warning(f"Persona not found: {persona_id}")
            return False

        self.current_persona = persona
        logger.info(f"Persona switched to: {persona.display_name}")
        return True

    def get_current_persona(self) -> Optional[Persona]:
        """Get currently active persona."""
        return self.current_persona

    def list_personas(self) -> List[Persona]:
        """Get all available personas."""
        return self.personas
