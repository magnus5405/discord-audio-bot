"""Transcript and conversation data models."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TranscriptSegment:
    """Represents a transcript segment from a single user.
    
    Phase 3: STT integration
    """

    user_id: int
    username: str
    text: str
    start_ts: float
    end_ts: float
    is_final: bool
    language_code: Optional[str] = None


@dataclass
class ConversationTurn:
    """Represents a single turn in the conversation log.
    
    Phase 4: Conversation policy
    """

    role: str  # "user" or "model"
    text: str
    timestamp: float
    speaker_name: Optional[str] = None  # Only for user turns
