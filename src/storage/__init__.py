"""Storage and persistence package.

Handles settings management, configuration persistence, and data storage.
"""

from .consent import ConsentAcceptEvent, ConsentStore
from .settings import (
    DEFAULT_LOCAL_STT_BACKEND,
    DEFAULT_LOCAL_STT_MODEL,
    DEFAULT_STT_LANGUAGE_CODE,
    DEFAULT_STT_PROVIDER,
    SettingsStore,
    default_local_stt_models_dir,
)
from .transcripts import (
    TranscriptScrubStats,
    TranscriptSessionWriter,
    scrub_user_data_from_transcripts,
)

__all__ = [
    "ConsentAcceptEvent",
    "ConsentStore",
    "DEFAULT_LOCAL_STT_BACKEND",
    "DEFAULT_LOCAL_STT_MODEL",
    "DEFAULT_STT_LANGUAGE_CODE",
    "DEFAULT_STT_PROVIDER",
    "SettingsStore",
    "TranscriptScrubStats",
    "TranscriptSessionWriter",
    "default_local_stt_models_dir",
    "scrub_user_data_from_transcripts",
]
