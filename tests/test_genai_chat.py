"""Unit tests for GenAIChatManager (mocked SDK)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.conversation.chat import GenAIChatManager, format_transcript_user_message
from src.models import Persona


@pytest.fixture
def sample_persona() -> Persona:
    return Persona(
        persona_id="p1",
        display_name="Test",
        system_instruction="You are a test bot.",
        genai_model="gemini-2.0-flash",
        elevenlabs_voice_id="voice1",
    )


def test_genai_manager_requires_api_key() -> None:
    with patch("src.conversation.chat.os.getenv", return_value=None):
        with pytest.raises(ValueError, match="GOOGLE_GEMINI_API_KEY"):
            GenAIChatManager(api_key=None)


@pytest.mark.asyncio
async def test_create_session_and_send_message_accumulates_tokens(sample_persona: Persona) -> None:
    fake_response = MagicMock()
    fake_response.text = "Hello there"
    fake_um = MagicMock()
    fake_um.total_token_count = 42
    fake_response.usage_metadata = fake_um

    fake_chat = AsyncMock()
    fake_chat.send_message = AsyncMock(return_value=fake_response)

    fake_aio = MagicMock()
    fake_aio.chats = MagicMock()
    fake_aio.chats.create = MagicMock(return_value=fake_chat)

    fake_client = MagicMock()
    fake_client.aio = fake_aio

    with patch("src.conversation.chat.genai.Client", return_value=fake_client):
        mgr = GenAIChatManager(api_key="fake-key-for-test", reply_locale="da-DK")
        await mgr.create_chat_session(sample_persona)
        text = await mgr.send_message("What did they say?")

    assert text == "Hello there"
    assert mgr.get_token_usage() == 42
    fake_aio.chats.create.assert_called_once()
    create_kw = fake_aio.chats.create.call_args.kwargs
    assert "da-DK" in create_kw["config"].system_instruction
    fake_chat.send_message.assert_awaited_once()


def test_format_transcript_user_message_wraps_block() -> None:
    out = format_transcript_user_message("Alice: hi")
    assert "Alice: hi" in out
    assert "since your last reply" in out


def test_format_transcript_user_message_includes_locale() -> None:
    out = format_transcript_user_message("Alice: hi", reply_locale="da-DK")
    assert "da-DK" in out
    assert "Alice: hi" in out

