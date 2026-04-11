"""Conversation log management and merging."""

import logging
import time
from typing import List

from ..models import TranscriptSegment, ConversationTurn

logger = logging.getLogger(__name__)


class ConversationLog:
    """
    Maintains and merges per-user transcript segments into ordered log.

    Handles overlaps, user attribution, and "since last bot turn" slicing.

    Phase 4: Conversation policy
    """

    def __init__(self) -> None:
        """Initialize conversation log."""
        self.segments: List[TranscriptSegment] = []
        self.turns: List[ConversationTurn] = []
        self.last_bot_turn_index: int = 0
        logger.info("ConversationLog initialized")

    def add_segment(self, segment: TranscriptSegment) -> None:
        """Add a transcript segment (final transcript only)."""
        self.segments.append(segment)
        logger.debug(f"Added transcript from {segment.username}: '{segment.text[:50]}...'")

    def merge_segments(self) -> str:
        """
        Merge recent segments into "since last bot turn" formatted text.

        Returns:
            Formatted transcript text
        """
        logger.debug(f"Merging {len(self.segments)} segments")
        return ""

    def add_bot_turn(self, response_text: str) -> None:
        """Record a bot response turn."""
        turn = ConversationTurn(
            role="model", text=response_text, timestamp=time.time()
        )
        self.turns.append(turn)
        self.last_bot_turn_index = len(self.segments)
        logger.debug(f"Bot turn recorded: '{response_text[:50]}...'")

    def get_conversation_for_prompt(self) -> str:
        """Get conversation context to send to GenAI."""
        return self.merge_segments()

    def clear_session(self) -> None:
        """Clear all segments and turns for new session."""
        self.segments.clear()
        self.turns.clear()
        self.last_bot_turn_index = 0
        logger.info("Conversation log cleared")
