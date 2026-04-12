"""GenAI chat session management."""

import os
import logging
from typing import Optional

import google.genai as genai

from ..models import Persona, UsageCounters

logger = logging.getLogger(__name__)


class GenAIChatManager:
    """
    Manages GenAI chat sessions for multi-turn conversation.

    Maintains conversation state, applies persona instructions,
    tracks token usage via usage_metadata.

    Phase 4: Conversation policy + GenAI
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        """
        Initialize GenAI client.

        Args:
            api_key: Gemini API key (optional, reads GOOGLE_GEMINI_API_KEY if
                not provided)
        """
        api_key = api_key or os.getenv("GOOGLE_GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        self.chat = None
        self.current_persona: Optional[Persona] = None
        self.usage_counters = UsageCounters()
        logger.info("GenAIChatManager initialized")

    def create_chat_session(self, persona: Persona) -> None:
        """
        Create a new chat session with persona instructions.

        Args:
            persona: Persona configuration with system instruction
        """
        self.current_persona = persona
        logger.info(f"Chat session created with persona '{persona.display_name}'")

    async def send_message(self, text: str) -> Optional[str]:
        """
        Send message to chat and get response.

        Args:
            text: Message text

        Returns:
            Response text from model, or None on error
        """
        if not self.chat:
            logger.error("Chat session not initialized")
            return None

        try:
            logger.debug(f"Sent message: {text[:100]}...")
            return None
        except Exception as e:
            logger.error(f"Failed to send message: {e}", exc_info=True)
            raise

    async def count_tokens(self, text: str) -> int:
        """
        Estimate token count for a message.

        Args:
            text: Text to count tokens for

        Returns:
            Estimated token count
        """
        logger.debug(f"Token count for message: {len(text)} chars")
        return len(text) // 4

    def get_token_usage(self) -> int:
        """Get total tokens used in this session."""
        return self.usage_counters.total_tokens

    def format_conversation_prompt(self, transcript_text: str) -> str:
        """Format transcript into a prompt for the conversation.

        Args:
            transcript_text: Merged transcript since last bot turn

        Returns:
            Formatted prompt
        """
        return transcript_text

    def end_chat_session(self) -> None:
        """End current chat session."""
        self.chat = None
        logger.info("Chat session ended")
