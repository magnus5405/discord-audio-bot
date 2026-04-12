"""Conversation log management and merging."""

from __future__ import annotations

import logging
import time

from ..models import ConversationTurn, TranscriptSegment

logger = logging.getLogger(__name__)


class ConversationLog:
    """
    Maintains and merges per-user transcript segments into ordered log.

    Handles overlaps, user attribution, and "since last bot turn" slicing.
    """

    def __init__(self) -> None:
        """Initialize conversation log."""
        self.segments: list[TranscriptSegment] = []
        self.turns: list[ConversationTurn] = []
        self.last_bot_turn_index: int = 0
        logger.info("ConversationLog initialized")

    def add_segment(self, segment: TranscriptSegment) -> None:
        """Add a transcript segment (final transcript only)."""
        if not segment.is_final or not segment.text.strip():
            return

        self.segments.append(segment)
        logger.debug("Added transcript from %s: '%s...'", segment.username, segment.text[:50])

    def merge_segments(self) -> str:
        """
        Merge recent segments into "since last bot turn" formatted text.

        Returns:
            Formatted transcript text
        """
        recent_segments = sorted(
            self.segments[self.last_bot_turn_index :],
            key=lambda segment: (segment.end_ts, segment.start_ts, segment.user_id),
        )
        logger.debug("Merging %s transcript segments since the last bot turn", len(recent_segments))
        return "\n".join(f"{segment.username}: {segment.text}" for segment in recent_segments)

    def add_bot_turn(self, response_text: str) -> None:
        """Record a bot response turn."""
        turn = ConversationTurn(
            role="model", text=response_text, timestamp=time.time()
        )
        self.turns.append(turn)
        self.last_bot_turn_index = len(self.segments)
        logger.debug("Bot turn recorded: '%s...'", response_text[:50])

    def get_conversation_for_prompt(self) -> str:
        """Get conversation context to send to GenAI."""
        return self.merge_segments()

    def has_pending_since_bot(self) -> bool:
        """True if there is final user transcript since the last bot turn."""
        pending = self.segments[self.last_bot_turn_index :]
        return any(seg.text.strip() for seg in pending)

    def clear_session(self) -> None:
        """Clear all segments and turns for new session."""
        self.segments.clear()
        self.turns.clear()
        self.last_bot_turn_index = 0
        logger.info("Conversation log cleared")
