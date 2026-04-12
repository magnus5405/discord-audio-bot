"""Configuration and usage tracking models."""

import time
from dataclasses import dataclass, field


@dataclass
class Persona:
    """Represents a bot personality configuration."""

    persona_id: str
    display_name: str
    system_instruction: str
    genai_model: str
    elevenlabs_voice_id: str


@dataclass
class UsageCounters:
    """Tracks token and audio usage for the session."""

    input_tokens: int = 0
    output_tokens: int = 0
    tts_seconds_generated: float = 0.0
    stt_seconds_processed: float = 0.0
    session_start_time: float = field(default_factory=time.time)

    @property
    def total_tokens(self) -> int:
        """Sum of prompt (input) and candidates (output) tokens."""
        return int(self.input_tokens) + int(self.output_tokens)

    @property
    def session_duration_seconds(self) -> float:
        """Get total session duration in seconds."""
        return time.time() - self.session_start_time

    @property
    def voice_minutes(self) -> float:
        """Get generated voice duration in minutes."""
        return self.tts_seconds_generated / 60.0
