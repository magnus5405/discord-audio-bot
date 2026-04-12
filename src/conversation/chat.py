"""GenAI chat session management."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from google import genai
from google.genai import types

from ..models import Persona, UsageCounters

logger = logging.getLogger(__name__)


def _reply_locale_system_suffix(locale_tag: str) -> str:
    """Append to system instruction so the model does not default to English."""
    return (
        f'\n\nWrite every reply only in the language/locale "{locale_tag}" (BCP-47), '
        "including join greetings and follow-ups. Do not default to English unless "
        f'the tag is an English locale (e.g. en-US). If user lines are in another language, '
        f"still answer in {locale_tag} unless they explicitly ask for a different language."
    )


def format_transcript_user_message(
    transcript_block: str,
    *,
    reply_locale: str | None = None,
) -> str:
    """Build the user turn sent after each reply trigger.

    The chat session keeps multi-turn history; each trigger sends one block
    describing what was said since the bot last spoke.
    """
    block = transcript_block.strip()
    intro = (
        "Here is what people in the voice channel said since your last reply "
        '(each line is "Username: text"). Give a brief spoken reply in '
        "1–2 short sentences that fits naturally in the conversation."
    )
    if reply_locale:
        intro = (
            f'Your reply must be in locale {reply_locale} (BCP-47), same as the '
            "configured voice session. " + intro
        )
    return f"{intro}\n\n{block}"


class GenAIChatManager:
    """
    Manages GenAI chat sessions for multi-turn conversation.

    Maintains conversation state, applies persona instructions,
    tracks token usage via usage_metadata.

    Phase 4: Conversation policy + GenAI
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        reply_locale: Optional[str] = None,
    ) -> None:
        """
        Initialize GenAI client.

        Args:
            api_key: Gemini API key (optional, reads GOOGLE_GEMINI_API_KEY if
                not provided)
            reply_locale: BCP-47 tag (e.g. da-DK) for spoken replies; aligns with
                ``stt.language_code`` in settings when passed from the orchestrator.
        """
        resolved = api_key or os.getenv("GOOGLE_GEMINI_API_KEY")
        if not resolved:
            raise ValueError(
                "GOOGLE_GEMINI_API_KEY must be set for GenAI (environment or constructor)."
            )
        self._client = genai.Client(api_key=resolved)
        self._chat: Any = None
        self.current_persona: Optional[Persona] = None
        self.usage_counters = UsageCounters()
        self._reply_locale = (reply_locale or "").strip() or None
        logger.info("GenAIChatManager initialized")

    async def create_chat_session(self, persona: Persona) -> None:
        """
        Create a new async chat session with persona instructions.

        Args:
            persona: Persona configuration with system instruction and model id
        """
        self.current_persona = persona
        system_instruction = persona.system_instruction
        if self._reply_locale:
            system_instruction = system_instruction + _reply_locale_system_suffix(self._reply_locale)
            logger.info("GenAI system instruction includes reply locale %s", self._reply_locale)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
        )
        # google-genai: aio.chats.create returns AsyncChat synchronously; await send_message instead.
        self._chat = self._client.aio.chats.create(
            model=persona.genai_model,
            config=config,
        )
        logger.info("Chat session created with persona '%s'", persona.display_name)

    async def send_message(self, text: str) -> str:
        """
        Send message to chat and get response text.

        Args:
            text: Message text

        Returns:
            Response text from model (may be empty if blocked)
        """
        if self._chat is None:
            raise RuntimeError("Chat session not initialized; call create_chat_session first.")

        logger.debug("Sending message (%s chars)", len(text))
        response = await self._chat.send_message(text)
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            total = getattr(usage, "total_token_count", None)
            if isinstance(total, int) and total > 0:
                self.usage_counters.total_tokens += total

        reply = (getattr(response, "text", None) or "").strip()
        logger.debug("Received reply (%s chars)", len(reply))
        return reply

    async def count_tokens(self, text: str) -> int:
        """
        Rough character-based estimate (optional; preflight counting is SDK-specific).

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        logger.debug("Token estimate for message: %s chars", len(text))
        return max(1, len(text) // 4)

    def get_token_usage(self) -> int:
        """Get total tokens used in this session."""
        return self.usage_counters.total_tokens

    def format_conversation_prompt(self, transcript_text: str) -> str:
        """Format merged transcript into the user message for the model."""
        return format_transcript_user_message(transcript_text, reply_locale=self._reply_locale)

    def end_chat_session(self) -> None:
        """End current chat session."""
        self._chat = None
        logger.info("Chat session ended")
