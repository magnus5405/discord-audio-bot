"""Storage and persistence package.

Handles settings management, configuration persistence, and data storage.
"""

from .consent import ConsentAcceptEvent, ConsentStore
from .settings import DEFAULT_STT_LANGUAGE_CODE, SettingsStore
from .transcripts import (
    TranscriptScrubStats,
    TranscriptSessionWriter,
    scrub_user_data_from_transcripts,
)

__all__ = [
    "ConsentAcceptEvent",
    "ConsentStore",
    "DEFAULT_STT_LANGUAGE_CODE",
    "SettingsStore",
    "TranscriptScrubStats",
    "TranscriptSessionWriter",
    "scrub_user_data_from_transcripts",
]
