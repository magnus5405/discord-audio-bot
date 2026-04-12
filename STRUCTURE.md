# Discord Audio Bot - Project Structure

## Directory Organization

The project is organized into responsibility-focused packages under `src/`.

```text
discord-audio-bot/
|-- src/
|   |-- __init__.py
|   |-- main.py                      # CLI entrypoint and shared runtime orchestration
|   |-- conversation/                # GenAI chat, personas, reply policy, transcript prompt shaping
|   |-- discord/                     # Discord connection, playback, receive sink, preflight checks
|   |-- models/                      # Core data structures (Persona, AudioFrame, TranscriptSegment, usage)
|   |-- session/                     # Shared voice-session runner and live metrics
|   |-- storage/                     # settings.json, transcript persistence, reply-locale helpers
|   |-- transcription/               # STT v1/v2 clients, preprocessing, per-user coordination
|   |-- tts/                         # ElevenLabs synthesis
|   `-- ui/                          # Textual TUI
|       |-- __init__.py
|       |-- main.py                  # TUI entry re-exports
|       |-- dashboard/
|       |   |-- __init__.py
|       |   |-- app.py               # Main dashboard app
|       |   |-- formatting.py        # Metric formatting helpers
|       |   `-- layout.py            # Dashboard layout and CSS
|       |-- settings/
|       |   |-- __init__.py
|       |   |-- __main__.py
|       |   |-- app.py               # Standalone settings runner
|       |   |-- gemini_models.py     # Dynamic Gemini text-model discovery for the TUI
|       |   |-- layout.py            # Settings layout and CSS
|       |   |-- screen.py            # Settings orchestration and save/load logic
|       |   `-- page/
|       |       |-- __init__.py
|       |       |-- characters.py
|       |       |-- cooldowns.py
|       |       |-- discord.py
|       |       |-- speech_to_text.py
|       |       `-- text_to_speech.py
|       `-- widgets/
|           |-- __init__.py
|           |-- dashboard.py         # Metric tiles used by the dashboard
|           `-- status.py            # Legacy status widget
|-- tests/
|-- transcripts/
|-- .env.example
|-- PLAN.md
|-- README.md
|-- STRUCTURE.md
`-- settings.json
```

## UI Settings Layout

The Textual settings editor is intentionally split into small page modules:

- `Characters`
  - ID
  - Model
  - Name
  - Voice ID
  - Character instructions
- `Discord`
  - Discord token
  - Discord server ID
- `Speech-to-Text`
  - Primary language
  - Alternative languages
  - Backend selector (`v1` or `v2`)
  - `v1`: Google STT API key
  - `v2`: service account JSON path, project ID, location, model
- `Text-to-Speech`
  - Reply language
  - Gemini API key
  - ElevenLabs API key
- `Cooldowns`
  - Reply silence seconds
  - Reply cooldown seconds
  - Mention window seconds

## Module Organization Principles

### 1. Responsibility segregation

Each package owns one domain:

- `models/` contains data structures only
- `discord/` contains Discord integration only
- `transcription/` contains STT/audio processing only
- `conversation/` contains GenAI conversation and reply triggering only
- `tts/` contains synthesis clients only
- `storage/` contains persistence and config resolution only
- `ui/` contains Textual UI only

### 2. Keep files focused

- Prefer narrow modules over "blob" files
- Split UI pages, layouts, and apps into separate files
- Move reusable resolution logic into storage/runtime helpers instead of widget code

### 3. Clear import hierarchy

```text
main.py
  -> discord/ + transcription/ + conversation/ + tts/ + storage/ + session/ + ui/
  -> models/ (lowest level)
```

Lower-level packages should not import from higher-level orchestration packages.

## Phase Mapping

| Phase | Primary Location | Status |
|-------|------------------|--------|
| 1 | `discord/client.py`, `discord/playback.py` | Voice connectivity and playback |
| 2 | `discord/voice_sink.py` | Voice receive and pause/resume |
| 3 | `transcription/stt.py`, `transcription/preprocessing.py` | STT integration |
| 4 | `conversation/chat.py`, `conversation/policy.py` | GenAI and reply triggers |
| 5 | `tts/elevenlabs.py` | ElevenLabs TTS and playback loop |
| 6 | `ui/dashboard/app.py`, `ui/settings/`, `session/conversation_runner.py` | TUI, settings editor, session runner |

## Testing Strategy

Tests mirror the source layout where practical:

- `tests/test_transcription.py` for STT clients and coordinator behavior
- `tests/test_discord.py` for Discord integration behavior
- `tests/test_settings_resolution.py` for settings-first config precedence
- `tests/test_reply_locale_resolution.py` for reply-language resolution

Run checks with:

```bash
python -m compileall src tests
pytest
```

## Documentation Sources

- `README.md` for setup and runtime usage
- `.env.example` for supported environment variables
- `settings.json` for persisted TUI settings
- `PLAN.md` for architecture and roadmap
- `STRUCTURE.md` for package and module layout
