"""GenAI chat session management."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from google import genai
from google.genai import types

from ..models import Persona, UsageCounters

logger = logging.getLogger(__name__)


def _reply_locale_system_prefix(locale_tag: str) -> str:
    """Prepend so locale wins over persona tone and English-heavy user turns."""
    return (
        f"[OUTPUT LANGUAGE — HIGHEST PRIORITY] Write every assistant message only in "
        f'locale "{locale_tag}" (BCP-47). Do not use English unless that locale is English '
        f"(e.g. en-US). Do not mirror another language from the room or from instructions.\n\n"
    )


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
    tag = (reply_locale or "").strip()
    intro = (
        "Here is what people in the voice channel said since your last reply "
        '(each line is "Username: text"). Give a brief spoken reply in '
        "1–2 short sentences that fits naturally in the conversation."
    )
    if tag:
        intro = (
            f'Your reply must be in locale {tag} (BCP-47), same as the '
            "configured voice session. Do not switch to English or mirror the "
            "transcript language unless that language is the one for this locale. "
            + intro
        )
    parts = [intro, "", block]
    if tag:
        parts.extend(["", f"End with a reply only in locale {tag}; no other language."])
    return "\n".join(parts)


def join_greeting_chat_history(greeting_prompt: str, greeting_text: str) -> list[types.Content]:
    """Seed multiturn chat so later replies see the join exchange."""
    return [
        types.Content(role="user", parts=[types.Part(text=greeting_prompt)]),
        types.Content(role="model", parts=[types.Part(text=greeting_text)]),
    ]


def format_join_greeting_prompt(
    names_str: str,
    *,
    reply_locale: str | None = None,
) -> str:
    """Build the user turn for the join greeting (first model output in the session)."""
    body = (
        "You just joined this Discord voice channel. "
        f"Users currently present: {names_str}. "
        "Give a brief, friendly spoken-style hello in 1-2 sentences."
    )
    tag = (reply_locale or "").strip()
    if not tag:
        return body
    return (
        f'Write your entire greeting only in the language of locale {tag} (BCP-47). '
        "Do not use English unless that locale is an English variant (e.g. en-US).\n\n"
        f"{body}\n\n"
        f"Reminder: the greeting must be entirely in locale {tag}."
    )


def format_user_join_greeting_prompt(
    display_name: str,
    *,
    reply_locale: str | None = None,
) -> str:
    """User turn for greeting someone who just connected to the voice channel (by nickname)."""
    name = (display_name or "").strip() or "them"
    body = (
        f'A user just joined this Discord voice channel. Their display name is "{name}". '
        "Give one brief, friendly spoken-style welcome (1-2 sentences) that feels unique to them "
        f'(use their name naturally — "{name}"). Do not copy a generic template verbatim.'
    )
    tag = (reply_locale or "").strip()
    if not tag:
        return body
    return (
        f'Write your entire welcome only in the language of locale {tag} (BCP-47). '
        "Do not use English unless that locale is an English variant (e.g. en-US).\n\n"
        f"{body}\n\n"
        f"Reminder: the welcome must be entirely in locale {tag}."
    )


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
            reply_locale: BCP-47 tag (e.g. en-US) for spoken replies; aligns with
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

    def _accumulate_usage(self, response: Any) -> None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return
        prompt = getattr(usage, "prompt_token_count", None)
        candidates = getattr(usage, "candidates_token_count", None)
        total = getattr(usage, "total_token_count", None)
        used_breakdown = False
        if isinstance(prompt, int) and prompt > 0:
            self.usage_counters.input_tokens += prompt
            used_breakdown = True
        if isinstance(candidates, int) and candidates > 0:
            self.usage_counters.output_tokens += candidates
            used_breakdown = True
        if not used_breakdown and isinstance(total, int) and total > 0:
            self.usage_counters.output_tokens += total

    def get_token_usage_breakdown(self) -> tuple[int, int]:
        """Cumulative GenAI prompt (input) and candidates (output) tokens."""
        return (self.usage_counters.input_tokens, self.usage_counters.output_tokens)

    async def create_chat_session(
        self,
        persona: Persona,
        *,
        history: Optional[list[types.Content]] = None,
    ) -> None:
        """
        Create a new async chat session with persona instructions.

        Args:
            persona: Persona configuration with system instruction and model id
            history: Optional prior turns (e.g. join greeting) for multiturn context.
        """
        self.current_persona = persona
        system_instruction = persona.system_instruction or ""
        if self._reply_locale:
            system_instruction = (
                _reply_locale_system_prefix(self._reply_locale)
                + system_instruction
                + _reply_locale_system_suffix(self._reply_locale)
            )
            logger.info("GenAI system instruction includes reply locale %s", self._reply_locale)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.65,
        )
        # google-genai: aio.chats.create returns AsyncChat synchronously; await send_message instead.
        self._chat = self._client.aio.chats.create(
            model=persona.genai_model,
            config=config,
            history=list(history) if history else [],
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
        self._accumulate_usage(response)

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
