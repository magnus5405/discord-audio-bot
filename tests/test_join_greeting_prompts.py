"""Tests for join-related GenAI user prompts."""

from __future__ import annotations

from src.conversation.chat import format_user_join_greeting_prompt


def test_format_user_join_greeting_prompt_english_default() -> None:
    text = format_user_join_greeting_prompt("Alex", reply_locale=None)
    assert "Alex" in text
    assert "unique" in text.lower() or "natural" in text.lower()


def test_format_user_join_greeting_prompt_with_locale_tag() -> None:
    text = format_user_join_greeting_prompt("Bo", reply_locale="da-DK")
    assert "Bo" in text
    assert "da-DK" in text
    assert "Discord voice channel" in text or "welcome" in text.lower()


def test_format_user_join_greeting_prompt_empty_name_fallback() -> None:
    text = format_user_join_greeting_prompt("   ", reply_locale="en-US")
    assert "them" in text
