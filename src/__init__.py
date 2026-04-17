"""Discord Audio Bot - Voice channel conversational AI bot for Discord.

A multi-turn conversational bot that joins Discord voice channels,
transcribes speech in real-time, maintains conversation context via GenAI,
and responds with synthesized speech.

Packages:
- models: Core data structures (audio, transcript, config)
- discord: Discord gateway, voice receive, playback
- transcription: STT, audio preprocessing, VAD
- conversation: Chat sessions, trigger policy, conversation log, personas
- tts: Text-to-speech synthesis
- storage: Settings and configuration persistence
- ui: Textual TUI applications
"""

__version__ = "1.1.1"
__author__ = "Magnus5405"
__license__ = "MIT"

