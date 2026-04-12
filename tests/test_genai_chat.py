"""Unit tests for GenAIChatManager (mocked SDK)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.conversation.chat import (
    GenAIChatManager,
    format_join_greeting_prompt,
    format_transcript_user_message,
    join_greeting_chat_history,
)
from src.models import Persona
from src.storage.settings import repair_utf8_mojibake


@pytest.fixture
def sample_persona() -> Persona:
    return Persona(
        persona_id="p1",
        display_name="Test",
        system_instruction="You are a test bot.",
        genai_model="gemini-2.5-flash",
        elevenlabs_voice_id="voice1",
    )


def test_genai_manager_requires_api_key() -> None:
    with patch("src.conversation.chat.os.getenv", return_value=None):
        with pytest.raises(ValueError, match="GOOGLE_GEMINI_API_KEY"):
            GenAIChatManager(api_key=None)


@pytest.mark.asyncio
async def test_send_message_accumulates_tokens_from_total_only(sample_persona: Persona) -> None:
    """When the API omits prompt/candidates counts, fall back to total_token_count."""
    fake_response = MagicMock()
    fake_response.text = "ok"
    fake_um = MagicMock()
    fake_um.prompt_token_count = None
    fake_um.candidates_token_count = None
    fake_um.total_token_count = 100
    fake_response.usage_metadata = fake_um
    fake_chat = AsyncMock()
    fake_chat.send_message = AsyncMock(return_value=fake_response)
    fake_aio = MagicMock()
    fake_aio.chats = MagicMock()
    fake_aio.chats.create = MagicMock(return_value=fake_chat)
    fake_client = MagicMock()
    fake_client.aio = fake_aio
    with patch("src.conversation.chat.genai.Client", return_value=fake_client):
        mgr = GenAIChatManager(api_key="fake-key-for-test")
        await mgr.create_chat_session(sample_persona)
        await mgr.send_message("hi")
    assert mgr.get_token_usage_breakdown() == (0, 100)


@pytest.mark.asyncio
async def test_create_session_and_send_message_accumulates_tokens(sample_persona: Persona) -> None:
    fake_response = MagicMock()
    fake_response.text = "Hello there"
    fake_um = MagicMock()
    fake_um.prompt_token_count = 30
    fake_um.candidates_token_count = 12
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
    assert mgr.get_token_usage_breakdown() == (30, 12)
    fake_aio.chats.create.assert_called_once()
    create_kw = fake_aio.chats.create.call_args.kwargs
    si = create_kw["config"].system_instruction
    assert "da-DK" in si
    assert "OUTPUT LANGUAGE" in si
    assert create_kw["config"].temperature == 0.65
    fake_chat.send_message.assert_awaited_once()


def test_format_transcript_user_message_wraps_block() -> None:
    out = format_transcript_user_message("Alice: hi")
    assert "Alice: hi" in out
    assert "since your last reply" in out


def test_format_transcript_user_message_includes_locale() -> None:
    out = format_transcript_user_message("Alice: hi", reply_locale="da-DK")
    assert "Alice: hi" in out
    assert "da-DK" in out
    assert "since your last reply" in out


def test_format_join_greeting_prompt_requires_locale() -> None:
    out = format_join_greeting_prompt("A, B", reply_locale="da-DK")
    assert "A, B" in out
    assert "da-DK" in out
    assert "Discord voice channel" in out


def test_format_join_greeting_prompt_secondary_locale_uses_english_instructions() -> None:
    out = format_join_greeting_prompt("A", reply_locale="de-DE")
    assert "de-DE" in out
    assert "Do not use English" in out


def test_repair_utf8_mojibake_scandinavian_chars() -> None:
    broken = "hj\u00c3\u00a6lpsom p\u00c3\u00a5 norsk"
    fixed = repair_utf8_mojibake(broken)
    assert "æ" in fixed
    assert "å" in fixed
    assert "\u00c3" not in fixed


def test_repair_utf8_mojibake_ascii_unchanged() -> None:
    assert repair_utf8_mojibake("hello") == "hello"


def test_join_greeting_chat_history_roles() -> None:
    hist = join_greeting_chat_history("user turn", "model turn")
    assert len(hist) == 2
    assert hist[0].role == "user"
    assert hist[1].role == "model"


@pytest.mark.asyncio
async def test_create_chat_session_passes_history(sample_persona: Persona) -> None:
    fake_chat = AsyncMock()
    fake_aio = MagicMock()
    fake_aio.chats = MagicMock()
    fake_aio.chats.create = MagicMock(return_value=fake_chat)
    fake_client = MagicMock()
    fake_client.aio = fake_aio
    hist = join_greeting_chat_history("hi", "hello")

    with patch("src.conversation.chat.genai.Client", return_value=fake_client):
        mgr = GenAIChatManager(api_key="fake-key-for-test")
        await mgr.create_chat_session(sample_persona, history=hist)

    kw = fake_aio.chats.create.call_args.kwargs
    assert len(kw["history"]) == 2


def test_format_join_greeting_prompt_without_locale() -> None:
    out = format_join_greeting_prompt("(none)", reply_locale=None)
    assert "Discord voice channel" in out
    assert "(none)" in out
    assert "da-DK" not in out

