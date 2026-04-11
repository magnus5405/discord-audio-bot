"""Tests for core data models."""

import pytest
from src.models import AudioFrame, TranscriptSegment, Persona, UsageCounters


class TestAudioFrame:
    """Test AudioFrame model."""

    def test_audio_frame_creation(self):
        """Test creating an AudioFrame."""
        frame = AudioFrame.new(user_id=12345, pcm_bytes=b"test audio")
        assert frame.user_id == 12345
        assert frame.pcm_bytes == b"test audio"
        assert frame.sample_rate_hz == 48000
        assert frame.channels == 2
        assert frame.timestamp_monotonic > 0

    def test_audio_frame_with_custom_params(self):
        """Test creating AudioFrame with custom parameters."""
        pcm_data = b"x" * 1000
        frame = AudioFrame(
            user_id=999,
            pcm_bytes=pcm_data,
            sample_rate_hz=16000,
            channels=1,
            timestamp_monotonic=123.45,
        )
        assert frame.user_id == 999
        assert frame.sample_rate_hz == 16000
        assert frame.channels == 1


class TestTranscriptSegment:
    """Test TranscriptSegment model."""

    def test_segment_creation(self):
        """Test creating a TranscriptSegment."""
        segment = TranscriptSegment(
            user_id=12345,
            username="TestUser",
            text="Hello, world!",
            start_ts=100.0,
            end_ts=102.0,
            is_final=True,
            language_code="en-US",
        )
        assert segment.user_id == 12345
        assert segment.username == "TestUser"
        assert segment.text == "Hello, world!"
        assert segment.is_final is True


class TestPersona:
    """Test Persona model."""

    def test_persona_creation(self):
        """Test creating a Persona."""
        persona = Persona(
            persona_id="friendly",
            display_name="Friendly Bot",
            system_instruction="Be helpful and kind",
            genai_model="gemini-2.0-flash",
            elevenlabs_voice_id="EXAVITQu4vr4xnSDxMaL",
        )
        assert persona.persona_id == "friendly"
        assert persona.display_name == "Friendly Bot"


class TestUsageCounters:
    """Test UsageCounters model."""

    def test_counters_initialization(self):
        """Test UsageCounters initialization."""
        counters = UsageCounters()
        assert counters.total_tokens == 0
        assert counters.tts_seconds_generated == 0.0
        assert counters.session_duration_seconds > 0

    def test_voice_minutes_calculation(self):
        """Test voice_minutes property calculation."""
        counters = UsageCounters()
        counters.tts_seconds_generated = 120.0
        assert counters.voice_minutes == 2.0
