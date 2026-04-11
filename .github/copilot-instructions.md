---
description: "Guidelines for developing the Discord Audio Bot using GitHub Copilot"
---

# GitHub Copilot Instructions for discord-audio-bot

## Project Overview for Copilot

You are assisting with development of a **Discord voice-channel conversational AI bot** written in Python 3.11+. The bot:
- Joins Discord voice channels
- Transcribes per-user speech in real-time (Google Cloud Speech-to-Text)
- Maintains multi-turn conversations (Google GenAI / Gemini)
- Generates synthesized replies (ElevenLabs TTS)
- Plays audio back into the Discord channel
- Is controlled entirely via a Textual TUI (no slash commands)

**Do NOT generate Discord text commands or message handlers.** All control flows through the TUI.

## Architecture Principles

### Module Organization
Follow the responsibility-driven structure in `src/`:

- **Discord integration**: `discord_client.py`, `voice_receive.py`, `voice_playback.py`
- **Transcription**: `stt_google.py`, `audio_preprocess.py`, `vad.py` (optional)
- **Conversation**: `genai_chat.py`, `trigger_policy.py`, `conversation_log.py`, `persona.py`
- **Synthesis**: `tts_elevenlabs.py`
- **UI**: `tui_main.py`, `tui_settings.py`, `settings_store.py`
- **Orchestration**: `main.py`

Each module should have a single, clear responsibility. Import only what is needed.

### Threading & Async Boundaries (Critical)

Three concurrency domains must be kept separate to avoid deadlocks:

1. **Discord asyncio loop** (`discord.py` runs on its own event loop)
   - Use `discord_client.py` as the single entry point to the Discord event loop
   - All Discord API calls must happen on the Discord asyncio context

2. **Voice receive sink callbacks** (often called from a receive thread, not async)
   - Minimize work in sink callbacks
   - Forward audio frames to an `asyncio.Queue` using `loop.call_soon_threadsafe(queue.put_nowait, ...)`
   - Never block or call Discord API from a sink callback

3. **Textual UI event loop** (has its own async runtime)
   - TUI runs independently and communicates with the Discord loop via message passing
   - Use reactive attributes for live counter updates
   - Use Workers for long-running tasks

**Pattern**: Callbacks → thread-safe queue → async task consumer → Discord context or TUI update.

### Type Hints & Data Models

Use **type hints in all functions** and **dataclasses for events/data passing**:

```python
from dataclasses import dataclass
from typing import Optional
import time

@dataclass
class AudioFrame:
    user_id: int
    pcm_bytes: bytes
    sample_rate_hz: int
    channels: int
    timestamp_monotonic: float

@dataclass
class TranscriptSegment:
    user_id: int
    username: str
    text: str
    start_ts: float
    end_ts: float
    is_final: bool
    language_code: Optional[str] = None
```

This makes cross-module communication explicit and enables IDE autocomplete.

### Error Handling: Fail Fast

Per the PLAN, **do not retry on errors**. Any fatal exception stops the session:

```python
# Good: Let exceptions propagate
try:
    await discord_client.join_voice_channel(channel_id)
except Exception as e:
    logger.error(f"Failed to join voice channel: {e}", exc_info=True)
    raise  # Stop the session
```

This aligns with the stated requirement: "crash/stop the session on error (no retries)."

## Code Style & Conventions

### Naming
- **Module names**: `snake_case` (e.g., `audio_preprocess.py`, `stt_google.py`)
- **Class names**: `PascalCase` (e.g., `DiscordClient`, `GoogleSTTClient`)
- **Functions/methods**: `snake_case` with clear intent (e.g., `pause_listening()`, `emit_transcript_segment()`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `SILENCE_TIMEOUT_SECONDS = 5`)

### Imports
- Standard library first
- Third-party (discord, google, textual, etc.)
- Local imports in `src/`
- Use `from module import Class` for clarity; avoid `from module import *`

Example:
```python
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import discord
from google.cloud import speech_v1

from .audio_preprocess import convert_to_linear16
from .conversation_log import ConversationLog
```

### Logging
Use the standard library `logging` module, never `print()` for application output:

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Bot connected to voice channel")
logger.error(f"STT failed: {e}", exc_info=True)
logger.debug(f"Received {len(data)} bytes from user {user_id}")
```

## Library-Specific Guidance

### discord.py + discord-ext-voice-recv

- **VoiceClient.play()** is the entry point for sending audio. Keep playback calls on the Discord event loop.
- **AudioSink** receives frames in a callback: do minimal work (validation, buffering) and forward to `asyncio.Queue` via `call_soon_threadsafe()`.
- **DAVE is mandatory** as of March 1, 2026. Ensure dependencies are current. If `VoiceClient` raises "DAVE not found," update `discord.py[voice]`.
- **Pause listening** when the bot starts speaking (set a flag or stop adding frames to transcript). Resume after playback completes via the `after` callback.

### Google Cloud Speech-to-Text

- **Streaming is gRPC-only.** Use `google.cloud.speech_v1p1beta1.SpeechClient` for streaming recognition.
- **Audio encoding**: LINEAR16 is ideal; if using native Discord 48 kHz, accept it (Google says "native rate is better than resampling").
- **Multi-language**: Set `language_code` and `alternative_language_codes` in the recognition config. Results include `language_code` field so you know which language was detected.
- **Interim vs final**: Only persist final results (`is_final=True`) to the conversation log; use interim for mention detection / live TUI updates.

### Google GenAI (python-genai)

- **Chat sessions** are stateful: `client.chats.create()` creates a session; `send_message()` is multi-turn; history is preserved.
- **System instruction** can be set via the config or by seeding the first message as a system turn.
- **Usage metadata**: Every response includes `usage_metadata` with `prompt_token_count`, `candidates_token_count`, `total_token_count`. Sum `total_token_count` across calls for session totals.
- **Environment variables**: Reads `GOOGLE_API_KEY` automatically if not passed explicitly.
- **Token counting**: Call `count_tokens()` to estimate cost before sending, if needed.

### ElevenLabs TTS

- **Streaming endpoint**: `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream`
- **Header**: `xi-api-key: <your_key>` (NOT a query parameter)
- **Output format**: MP3 is fine (e.g., `mp3_44100_128`)
- **Streaming response**: Returns chunked HTTP response; iterate over chunks and forward to FFmpeg or accumulate into a temp file.
- **Voice IDs**: Available in the ElevenLabs account dashboard; store in `settings.json` per persona.
- **Usage**: Call `/v1/usage/character-stats` for account-level metrics; compute per-session duration locally from generated audio.

### Textual Framework

- **Reactive attributes** keep UI in sync: define `@reactive.var` properties, and UI auto-updates when they change.
- **Workers**: Use for long-running tasks that would block the UI thread. Workers run in the event loop and report back via messages.
- **Cross-process communication**: If TUI runs in a separate terminal/process, use message queues or IPC (e.g., multiprocessing Queue, or HTTP if simpler).
- **Containers & layouts**: Use `Container`, `Horizontal`, `Vertical` for layout; `Button`, `Select`, `Static` for widgets.

Example:
```python
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Button, Static

class BotStatus(Static):
    tokens_spent = reactive(0)
    voice_minutes = reactive(0.0)

    def render(self) -> str:
        return f"Tokens: {self.tokens_spent} | Voice: {self.voice_minutes:.1f}m"
```

## Common Patterns

### Async Task Management
```python
async def run_session():
    # Start main tasks as separate coroutines
    await asyncio.gather(
        discord_client.run(),
        transcription_task(),
        reply_trigger_task(),
        await_ui_commands(),  # May be a queue or IPC
    )
```

### Queue-Based Frame Forwarding (Sink Callback → Async)
```python
# In sink callback (non-async context):
def on_audio_frame(user_id, pcm_data):
    frame = AudioFrame(user_id, pcm_data, 48000, 2, time.monotonic())
    try:
        discord_loop.call_soon_threadsafe(audio_queue.put_nowait, frame)
    except Exception as e:
        logger.error(f"Failed to queue audio frame: {e}")

# In async STT task:
async def transcribe_audio():
    while running:
        frame = await audio_queue.get()
        # Process frame, call STT, emit TranscriptSegment
```

### Persona & System Instruction Management
```python
# In genai_chat.py:
def apply_persona(chat, persona: Persona):
    # Option 1: Set via config
    config = genai.types.GenerateContentConfig(
        system_instruction=persona.system_instruction
    )
    # Or Option 2: Seed the chat with a system turn
    chat.send_message(f"[System]: {persona.system_instruction}")
```

## Testing & Debugging

- **pytest** for unit tests: test data models, transcript merging, trigger logic in isolation
- **pytest-asyncio** for async function testing
- **Logging**: Use `DEBUG`, `INFO`, `WARNING`, `ERROR` levels appropriately
- **Transcript output**: Save per-session JSON to `transcripts/` for post-mortem debugging
- **Manual testing**: Start with Phase One (playback) before integrating full pipeline

## Git & Contribution Workflow

- **Commit messages**: Use present tense, be specific  
  - ✅ "Add Google STT streaming client and per-user transcript buffering"
  - ❌ "Fixed bugs" or "WIP stuff"
- **Branch naming**: `feature/component-name` (e.g., `feature/voice-receive`, `fix/mention-detection`)
- **Before pushing**: Run `black src/`, `isort src/`, and `ruff check src/` to ensure code style

## When Copilot Suggests non-Discord Solutions

**Guard against these pitfalls:**

1. **Don't suggest Discord slash commands** → All control is TUI-only
2. **Don't add text message handlers** → The bot only speaks in voice
3. **Don't use discord.py.ext.commands** → Not needed for this application
4. **Don't retry network calls** → Fail fast per design spec
5. **Don't block the Discord event loop** → Always use async/await or defer to a queue
6. **Don't spawn threads for Discord calls** → Discord expects asyncio context

## Phase-by-Phase Milestones (Reference)

1. **Phase 1**: Voice connectivity + playback (can join and play test MP3)
2. **Phase 2**: Voice receive + pause/resume (sink receives frames, listens pause during speech)
3. **Phase 3**: STT integration (live per-user transcripts appear)
4. **Phase 4**: Conversation policy + GenAI (5s silence trigger, mention detection, ChatSession)
5. **Phase 5**: ElevenLabs TTS + playback loop (end-to-end voice conversation)
6. **Phase 6**: Textual TUI polish (guild/channel selection, persona selection, settings editor)

When implementing a new feature, tag code with "Phase N" or reference it in comments if the context is non-obvious.

---

**Remember**: Refer to [PLAN.md](../PLAN.md) for the complete design decisions and rationale. When Copilot suggests an alternative approach, evaluate it against the documented constraints and design goals in PLAN.md.
