"""Tests for conversation module."""

import pytest
from src.conversation import ReplyTriggerPolicy, TriggerState, PersonaManager
from src.models import Persona


class TestReplyTriggerPolicy:
    """Test reply trigger policy."""

    def test_policy_initialization(self):
        """Test initializing ReplyTriggerPolicy."""
        policy = ReplyTriggerPolicy()
        assert policy.state == TriggerState.LISTENING
        assert policy.silence_timeout_seconds == 5.0
        assert policy.cooldown_seconds == 180.0

    def test_no_trigger_without_speech(self):
        """Test no trigger when no speech recorded."""
        policy = ReplyTriggerPolicy()
        assert policy.should_trigger_reply() is False

    def test_trigger_after_silence(self):
        """Test trigger after silence period."""
        policy = ReplyTriggerPolicy(silence_timeout_seconds=0.1)
        policy.record_human_speech()

        import time

        time.sleep(0.2)
        assert policy.should_trigger_reply() is True


class TestPersonaManager:
    """Test persona management."""

    def test_manager_initialization(self):
        """Test PersonaManager initialization."""
        personas = [
            Persona(
                persona_id="test",
                display_name="Test Persona",
                system_instruction="Test",
                genai_model="gemini-2.0-flash",
                elevenlabs_voice_id="voice123",
            )
        ]
        manager = PersonaManager(personas)
        assert len(manager.list_personas()) == 1

    def test_get_persona(self):
        """Test getting persona by ID."""
        persona = Persona(
            persona_id="test",
            display_name="Test",
            system_instruction="Test",
            genai_model="gemini-2.0-flash",
            elevenlabs_voice_id="voice123",
        )
        manager = PersonaManager([persona])
        found = manager.get_persona("test")
        assert found is not None
        assert found.display_name == "Test"

    def test_switch_persona(self):
        """Test switching personas."""
        personas = [
            Persona(
                persona_id="p1",
                display_name="First",
                system_instruction="First",
                genai_model="gemini-2.0-flash",
                elevenlabs_voice_id="v1",
            ),
            Persona(
                persona_id="p2",
                display_name="Second",
                system_instruction="Second",
                genai_model="gemini-2.0-flash",
                elevenlabs_voice_id="v2",
            ),
        ]
        manager = PersonaManager(personas)
        manager.set_current_persona("p2")
        assert manager.get_current_persona().persona_id == "p2"
