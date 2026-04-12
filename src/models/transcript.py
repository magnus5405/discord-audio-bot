"""Transcript and conversation data models."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TranscriptSegment:
    """Represents a transcript segment from a single user."""

    user_id: int
    username: str
    text: str
    start_ts: float
    end_ts: float
    is_final: bool
    language_code: Optional[str] = None


@dataclass
class ConversationTurn:
    """Represents a single turn in the conversation log."""

    role: str  # "user" or "model"
    text: str
    timestamp: float
    speaker_name: Optional[str] = None  # Only for user turns
