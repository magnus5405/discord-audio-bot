"""Core data models for the Discord Audio Bot.

This package contains type-safe dataclasses for all core entities used throughout
the application, keeping models isolated and maintainable.
"""

from .audio import AudioFrame
from .config import Persona, UsageCounters
from .transcript import ConversationTurn, TranscriptSegment

__all__ = [
    "AudioFrame",
    "TranscriptSegment",
    "ConversationTurn",
    "Persona",
    "UsageCounters",
]
