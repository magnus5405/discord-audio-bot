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
        self.last_bot_turn_timestamp: float | None = None
        logger.info("ConversationLog initialized")

    def add_segment(self, segment: TranscriptSegment) -> None:
        """Add a transcript segment (final transcript only)."""
        if not segment.is_final or not segment.text.strip():
            return

        self.segments.append(segment)
        logger.debug("Added transcript from %s: '%s...'", segment.username, segment.text[:50])

    def _segments_since_last_bot_turn(self) -> list[TranscriptSegment]:
        cutoff = self.last_bot_turn_timestamp
        if cutoff is None:
            return list(self.segments)
        return [segment for segment in self.segments if segment.end_ts > cutoff]

    def merge_segments(self) -> str:
        """
        Merge recent segments into "since last bot turn" formatted text.

        Returns:
            Formatted transcript text
        """
        recent_segments = sorted(
            self._segments_since_last_bot_turn(),
            key=lambda segment: (segment.end_ts, segment.start_ts, segment.user_id),
        )
        logger.debug("Merging %s transcript segments since the last bot turn", len(recent_segments))
        return "\n".join(f"{segment.username}: {segment.text}" for segment in recent_segments)

    def add_bot_turn(self, response_text: str, *, timestamp: float | None = None) -> None:
        """Record a bot response turn."""
        turn = ConversationTurn(
            role="model", text=response_text, timestamp=time.time() if timestamp is None else timestamp
        )
        self.turns.append(turn)
        self.last_bot_turn_timestamp = turn.timestamp
        logger.debug("Bot turn recorded: '%s...'", response_text[:50])

    def get_conversation_for_prompt(self) -> str:
        """Get conversation context to send to GenAI."""
        return self.merge_segments()

    def has_pending_since_bot(self) -> bool:
        """True if there is final user transcript since the last bot turn."""
        return any(seg.text.strip() for seg in self._segments_since_last_bot_turn())

    def clear_session(self) -> None:
        """Clear all segments and turns for new session."""
        self.segments.clear()
        self.turns.clear()
        self.last_bot_turn_timestamp = None
        logger.info("Conversation log cleared")
