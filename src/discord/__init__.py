"""Discord integration package.

Handles all Discord API interactions including gateway connection,
voice channel management, audio receive, and playback.
"""

from .client import DiscordClient
from .playback import VoicePlaybackManager
from .voice_sink import DiscordAudioSink

__all__ = [
    "DiscordClient",
    "DiscordAudioSink",
    "VoicePlaybackManager",
]
