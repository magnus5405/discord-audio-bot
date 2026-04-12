---
description: "Guidelines for developing the Discord Audio Bot using GitHub Copilot"
---

# GitHub Copilot Instructions for discord-audio-bot

## Project overview

You are assisting with a **Discord voice-channel conversational bot** (Python 3.11+). It:

- Joins voice channels and receives audio (`discord.py`, `discord-ext-voice-recv`, DAVE/`davey`)
- Streams per-user audio to **Google Cloud Speech-to-Text**
- Runs reply logic and **Google GenAI (Gemini)** multi-turn chat
- Synthesizes replies with **ElevenLabs** and plays them back into the channel
- Is controlled from a **Textual** terminal UI (dashboard + settings editor), not slash commands

**Do not add Discord text commands, message content handlers, or `discord.py.ext.commands` bots.** Control and configuration are TUI-driven or CLI smoke flags.

## Module map (`src/`)

Use these real paths (not legacy single-file names):

| Area | Location |
|------|-----------|
| CLI entry | `src/main.py` |
| Voice session orchestration | `src/session/conversation_runner.py`, `src/session/metrics.py` |
| Discord gateway / voice | `src/discord/client.py`, `playback.py`, `voice_sink.py`, `voice_recv_patch.py`, `preflight.py` |
| STT pipeline | `src/transcription/coordinator.py`, `stt.py`, `stt_v1.py`, `preprocessing.py`, `vad.py` |
| Conversation | `src/conversation/chat.py`, `policy.py`, `log.py`, `persona.py` |
| Data models | `src/models/audio.py`, `config.py`, `transcript.py` |
| Persistence / resolution | `src/storage/settings.py`, `transcripts.py`, `reply_locale.py` |
| TTS | `src/tts/elevenlabs.py` |
| TUI | `src/ui/dashboard/`, `src/ui/settings/`, `src/ui/widgets/`, `src/ui/main.py` |

Import from the `src` package layout already used in tests (for example `from src.discord import …`).

## Threading and async boundaries

1. **Discord asyncio loop** — all `discord.py` API calls on that loop.
2. **Voice receive sink callbacks** — may run off the cooperative asyncio path; do minimal work, push frames to an `asyncio.Queue` with `loop.call_soon_threadsafe(queue.put_nowait, …)`. Never block or call Discord APIs inside the sink.
3. **Textual** — separate app loop; coordinate with Discord via explicit runner/session boundaries and shared `SettingsStore` / metrics, not ad-hoc cross-thread Discord calls.

**Pattern**: callback → thread-safe queue → async consumer → Discord or UI update.

## Configuration

- **`.env`**: loaded at startup (`python-dotenv`); holds secrets and defaults.
- **`settings.json`**: personas, STT language, UI state, and optional persisted API keys. **Settings from JSON override `.env`** where `SettingsStore` resolves both (see `resolve_api_secret`, Discord helpers, runtime floats/bools).

When suggesting new options, extend `SettingsStore` and the settings TUI consistently; document in [README.md](../README.md).

## Error handling

Per project convention, **avoid silent retries** for fatal integration errors—log and surface failure so the session can stop cleanly. Example shape:

```python
try:
    await discord_client.join_voice_channel(channel_id)
except Exception as e:
    logger.error("Failed to join voice channel: %s", e, exc_info=True)
    raise
```

Do not paper over missing credentials or broken voice state.

## Type hints and models

Prefer dataclasses and explicit types for frames and transcript segments (see `src/models/`). Match existing style: type hints on public functions, minimal comments.

## Library notes (high level)

- **discord.py + voice_recv**: pause inbound transcription while the bot plays TTS; resume after playback completes.
- **Speech-to-Text**: supports v1 (API key) and v2 (service account + project/location/model); configuration flows through `SettingsStore`.
- **Google GenAI**: use the `google-genai` patterns already in `src/conversation/chat.py` (not the older `google-generativeai` package name in examples elsewhere on the web).
- **ElevenLabs**: streaming HTTP; voice id per persona in `settings.json`.
- **Textual**: reactive state and workers for long tasks; keep UI updates on the Textual loop.

## Testing and manual validation

- **pytest** and **pytest-asyncio** for unit and async tests under `tests/`.
- Prefer deterministic fakes for Discord and STT (see `tests/test_discord.py` patterns).
- **Manual order** when validating locally: playback-only → `--receive-smoke` → `--transcribe` → `--converse` → `--tui`.

Session JSON under `transcripts/` helps debug STT and conversation output.

## Git workflow

- Commits: present tense, specific (what changed and why).
- Branches: `feature/…`, `fix/…` as appropriate.
- Before sharing a branch: `black src/ tests/`, `isort src/ tests/`, `ruff check src/ tests/`, `mypy src/ --ignore-missing-imports --strict`, `pytest`.

## Pitfalls to avoid

1. Slash commands or message-based control surfaces
2. Reading text channels for bot control
3. Automatic retry loops that hide API or voice misconfiguration
4. Blocking the Discord event loop
5. Heavy work inside voice sink `write` paths

## Authoritative docs

Use [README.md](../README.md) and [QUICKSTART.md](../QUICKSTART.md) plus the source tree above. When a suggestion conflicts with implemented resolution order or voice lifecycle, **prefer the code in `src/storage/settings.py` and `src/discord/`**.
