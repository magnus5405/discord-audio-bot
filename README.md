# Discord Audio Bot

A Discord voice-channel conversational bot with a [Textual TUI](https://textual.textualize.io/). The bot joins voice channels, listens to speakers, transcribes speech in real time, maintains multi-turn conversations using [Google GenAI](https://github.com/googleapis/python-genai), and replies with synthesized speech via [ElevenLabs](https://github.com/elevenlabs/elevenlabs-python).

## Features

- **Voice integration**: Joins Discord voice channels via [discord.py](https://github.com/Rapptz/discord.py) and [discord-ext-voice-recv](https://github.com/imayhaveborkedit/discord-ext-voice-recv) with DAVE encryption support
- **Real-time transcription**: Per-user speech-to-text via [Google Cloud Speech-to-Text](https://github.com/googleapis/python-speech)
- **Conversational AI**: Multi-turn chat with [Google GenAI](https://github.com/googleapis/python-genai) and conversation context
- **Text-to-speech**: [ElevenLabs](https://github.com/elevenlabs/elevenlabs-python) streaming TTS
- **Smart reply triggers**:
  - Default: reply after a silence window (configurable), with a cooldown between replies
  - Mention mode: wait for silence after the bot name is mentioned, within a configurable window
  - Join greeting: optional spoken greeting when the bot joins or others enter mid-session
- **[Textual](https://textual.textualize.io/)**: No Discord slash commands—control runs from the terminal
- **Personas**: System instructions, Gemini model, and ElevenLabs voice per persona
- **Session logging**: JSON transcripts and usage counters per session

## Installation

### Windows (GitHub release)

Tagged releases publish **Windows** artifacts on [GitHub Releases](https://github.com/Magnus5405/discord-audio-bot/releases):

| Asset | What it is |
|-------|------------|
| **`DiscordAudioBotTUI-Setup.exe`** | Inno Setup installer — installs under Program Files, adds a Start Menu entry, and optionally a desktop shortcut. |
| **`DiscordAudioBotTUI-windows.zip`** | Portable folder — extract anywhere and run `DiscordAudioBotTUI.exe`. |

Both bundles include **FFmpeg** next to the executable — no separate FFmpeg install. The build ships a template `settings.json` beside the app; configure secrets in the **Settings** TUI editor (see [Configuration](#3-configuration-env-and-settingsjson) below).

**macOS / Linux** — install and run **from source**; follow [Development](#development) (clone, venv, `pip install -e .`, FFmpeg on `PATH`).
No official releases for macOS and Linux, but contributions are welcome to implement this.

### API credentials

You need accounts for **Discord**, **Google** (Gemini + Speech-to-Text), and **ElevenLabs**:

- **Discord**: [Developer Portal](https://discord.com/developers/applications) — bot token; enable `GUILDS` and `GUILD_VOICE_STATES`; the bot does not use message content in servers.
- **Gemini**: API key from [Google AI Studio](https://aistudio.google.com/) → `GOOGLE_GEMINI_API_KEY`
- **Speech-to-Text**: Cloud API key with Speech-to-Text API enabled → `GOOGLE_STT_API_KEY` (v1 backend), or service account + project fields for v2 (see `.env.example`).
- **ElevenLabs**: [API keys](https://elevenlabs.io/app/settings/api-keys) → `ELEVENLABS_API_KEY` (or `ELEVEN_API_KEY` as fallback).

### Running

Launch **`DiscordAudioBotTUI.exe`** (installed or portable). In the TUI, choose a **server**, **voice channel**, and **persona**, then press **Start** to connect. For dashboard behavior, logging paths, and the settings editor, see [Textual dashboard](#textual-dashboard) under Development.

---

## Development

### Prerequisites

- **[Python 3.11+](https://www.python.org/downloads/)**
- **[FFmpeg](https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip)**: required for audio encode/decode when **running from source** (install on `PATH`). **Official Windows TUI builds** (installer and portable zip) ship **ffmpeg.exe** and **ffprobe.exe** next to the executable — no separate FFmpeg install for those.
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt-get install ffmpeg`
  - Windows (dev / source only): [ffmpeg.org](https://ffmpeg.org/download.html) or `choco install ffmpeg`
- **System Opus** (optional): can help voice performance
  - macOS: `brew install opus`
  - Ubuntu/Debian: `sudo apt-get install libopus0`

### Setup

#### 1. Clone and install

```bash
git clone https://github.com/Magnus5405/discord-audio-bot.git
cd discord-audio-bot
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

#### 2. API credentials

You need Discord, Google (Gemini + Speech-to-Text), and ElevenLabs. Step-by-step links stay the same as in earlier docs:

- **Discord**: [Developer Portal](https://discord.com/developers/applications) — bot token; enable `GUILDS` and `GUILD_VOICE_STATES`; the bot does not use message content in servers.
- **Gemini**: API key from [Google AI Studio](https://aistudio.google.com/) → `GOOGLE_GEMINI_API_KEY`
- **Speech-to-Text**: Cloud API key with Speech-to-Text API enabled → `GOOGLE_STT_API_KEY` (v1 backend), or service account + project fields for v2 (see `.env.example`).
- **ElevenLabs**: [API keys](https://elevenlabs.io/app/settings/api-keys) → `ELEVENLABS_API_KEY` (or `ELEVEN_API_KEY` as fallback).

### 3. Configuration: `.env` and `settings.json`
There are two layers:

1. **`.env`** — secrets and machine-local defaults (loaded via `python-dotenv` on startup).
   `.env.example` documents defaults for reply timing, STT backend, optional pricing hints, `DEBUG_MODE`, and `TUI_LOG_FILE`.
2. **`settings.json`** in the project root — personas, STT language, UI selections, and optional persisted API keys or Discord fields when you save from the TUI settings editor.

**Precedence**:

- API secrets such as Gemini, STT, ElevenLabs, and Discord token are resolved with **values saved in `settings.json` first**, then fall back to environment variables (see `SettingsStore.resolve_api_secret` and related helpers in [`src/storage/settings.py`](src/storage/settings.py)).
- Discord-specific overrides and runtime fields (for example reply language from the TUI) follow the same pattern: **settings file overrides `.env`** where both exist.
- Reply **locale** for GenAI: TUI/runtime `reply_language` → `BOT_REPLY_LANGUAGE` / `BOT_LANGUAGE` in `.env` → `stt.language_code` in `settings.json` (see [`src/storage/reply_locale.py`](src/storage/reply_locale.py)).

You can edit `settings.json` or generate it entirely from **Settings** inside the dashboard TUI (`python -m src.main --tui`).

**Encrypting secrets in `settings.json`:** Set **`SETTINGS_SECRET_KEY`** in `.env` (Fernet key: 44-character url-safe base64) when you store API keys under `settings.api` or the Discord token under `settings.discord`. Those fields must use an `enc:v1:` prefix at rest; plaintext values are rejected on load. A template-only `settings.json` (no `api` / `discord` secrets) loads without this key. Anyone with the key and the file can decrypt — treat it like a master password. If you still have plaintext secrets in an older `settings.json`, remove those keys or re-save them from the TUI once this key is set so they are rewritten encrypted.

**FFmpeg:** TTS playback uses FFmpeg. **Released Windows TUI builds** include FFmpeg next to `DiscordAudioBotTUI.exe`. When **developing from a clone**, install FFmpeg on `PATH` or set **`FFMPEG_PATH`** to the `ffmpeg` / `ffmpeg.exe` binary for a custom location.

**Windows releases:** GitHub Actions produces **`DiscordAudioBotTUI-Setup.exe`** (Inno Setup) and a portable **`DiscordAudioBotTUI-windows.zip`**.

The repo ships **`settings-example.json`** as a neutral template; the PyInstaller build copies it to **`settings.json`** next to the executable.

### Release branch (`latest`)

Production Windows releases are driven off the **`latest`** branch:

1. Open a pull request **into `latest`**. CI runs **lint / typecheck / tests** (same as other PRs) plus a **version check**: `pyproject.toml` `[project] version` and `src/__init__.py` `__version__` must **match** each other, and the version must be **strictly greater** than on the current `latest` tip (semver).
2. After merge, the [**Release**](.github/workflows/cd.yml) workflow runs on **`latest`**: it builds the Windows artifacts and creates a **GitHub Release** (and git tag **`v{version}`** from `[project] version`) via the release API. Pushes of `GITHUB_TOKEN` do not chain-trigger other workflows, so this path avoids a separate tag-push job.

In GitHub: create the **`latest`** branch if it does not exist yet, then under **Settings → Rules → Rulesets** (or branch protection), require the **`require-version-bump`** check (and your usual CI jobs) before merging into `latest`. The **`SETTINGS_SECRET_KEY`** repository secret is optional for the Windows build job; if unset, CI generates a throwaway key for the runner only (it is not embedded in the app). For local installs, set **`SETTINGS_SECRET_KEY`** in `.env` whenever you persist encrypted API keys or a Discord token in `settings.json`.

#### 4. Example `settings.json`

```json
{
  "personas": [
    {
      "id": "default",
      "name": "Default Bot",
      "system_instruction": "You are a helpful Discord bot in a voice channel conversation. Be concise (1-2 sentences), friendly, and conversational.",
      "genai_model": "gemini-2.5-flash",
      "elevenlabs_voice_id": "JBFqnCBsd6RMkjVDRZzb"
    }
  ],
  "ui": {
    "last_guild_id": null,
    "last_channel_id": null,
    "last_persona_id": "default"
  }
}
```

ElevenLabs voice IDs are listed in your ElevenLabs account ([voices docs](https://elevenlabs.io/docs/voices)).

### Running

#### Headless smoke and pipeline checks

```bash
python -m src.main --list-voice-channels
python -m src.main --channel-id 123456789012345678 --audio-path /path/to/local-test-clip.mp3
python -m src.main --channel-id 123456789012345678 --audio-path /path/to/local-test-clip.mp3 --receive-smoke
python -m src.main --channel-id 123456789012345678 --transcribe
python -m src.main --channel-id 123456789012345678 --transcribe --listen-window-seconds 30
python -m src.main --channel-id 123456789012345678 --converse --listen-window-seconds 60
python -m src.main --tui
```

What these modes do:

1. Load `.env` and merge with `settings.json` where applicable.
2. Connect and print guild/voice channel IDs (`--list-voice-channels`).
3. Join a channel and play a local MP3/WAV once.
4. **Receive smoke** (`--receive-smoke`): listen, play the clip, listen again with a fresh sink; logs receive summaries.
5. **Transcription** (`--transcribe`): PCM receive, per-user STT, session JSON under `transcripts/`.
6. **Conversation** (`--converse`): same STT path as transcription, plus GenAI replies and ElevenLabs playback (requires keys and personas); usage fields updated in the session JSON.
7. Disconnect when the selected mode finishes (or on Ctrl+C).

If you set `DISCORD_VOICE_CHANNEL_ID` and `BOT_TEST_AUDIO_PATH`, you can run `python -m src.main` without repeating `--channel-id` / `--audio-path`.

#### Textual dashboard

```bash
python -m src.main --tui
```

Same credential expectations as full conversation mode. Do **not** combine `--tui` with `--converse`, `--transcribe`, `--channel-id`, or other headless flags.

- Pick a **server**, **voice channel**, and **persona**, then **Start**.
- Metrics refresh periodically (session time, STT audio minutes, GenAI tokens, TTS minutes).
- **Stop** ends the voice session cleanly; the bot stays logged in for another run.
- **Settings** (default binding: comma) opens the tabbed editor (personas, STT, Discord, API keys, cooldowns, pricing display).
- Logs go to **`logs/tui.log`** by default so the terminal stays clean; override with `TUI_LOG_FILE`.

#### Standalone settings editor

```bash
python -m src.ui.settings
```

Edits and saves `settings.json` without starting Discord.

### Format, lint, typecheck

```bash
ruff check src/ tests/
mypy src/ --ignore-missing-imports --strict
```

### Tests

```bash
pytest
pytest -v
pytest tests/test_models.py
pytest --cov=src --cov-report=html
```

## Architecture

End-to-end data flow:

```text
Discord voice receive → preprocessing / optional VAD → Google STT
  → conversation log + reply policy → Google GenAI → ElevenLabs TTS → Discord playback
```

`settings.json` and `.env` feed STT backend choice, languages, personas, API keys, and reply timing.

### `src/` package map

```
src/
├── main.py                 # CLI: headless modes and --tui dispatch
├── session/
│   ├── conversation_runner.py   # Voice session: STT, policy, GenAI, TTS, playback
│   └── metrics.py               # Live counters for the TUI
├── conversation/
│   ├── chat.py             # GenAI chat manager
│   ├── log.py              # Transcript merge / conversation log
│   ├── persona.py          # Persona selection
│   └── policy.py           # Reply trigger state machine
├── discord/
│   ├── client.py           # Gateway, voice join, receive lifecycle
│   ├── playback.py         # VoiceClient playback
│   ├── voice_sink.py       # Incoming audio sink → queues
│   ├── voice_recv_patch.py # Compatibility patches
│   └── preflight.py        # FFmpeg / voice dependency checks
├── models/
│   ├── audio.py            # AudioFrame
│   ├── config.py           # Persona, usage counters
│   └── transcript.py     # TranscriptSegment, ConversationTurn
├── storage/
│   ├── settings.py         # settings.json load/save and resolution helpers
│   ├── transcripts.py    # Session JSON writer
│   └── reply_locale.py     # Reply BCP-47 resolution
├── transcription/
│   ├── coordinator.py      # Per-user STT orchestration
│   ├── preprocessing.py    # PCM helpers
│   ├── stt.py              # STT client factory / streaming API
│   ├── stt_v1.py           # Speech-to-Text v1 client
│   └── vad.py              # Optional WebRTC VAD
├── tts/
│   └── elevenlabs.py       # ElevenLabs HTTP client
└── ui/
    ├── main.py             # TUI entry re-exports / `BotUI` alias
    ├── dashboard/          # Main Textual dashboard (app, layout, formatting)
    ├── settings/           # Settings editor (screen, pages, layout)
    └── widgets/            # Dashboard widgets
```

**Concurrency**: Discord runs on asyncio; voice sink callbacks may run off the main async path—forward work to `asyncio.Queue` with `loop.call_soon_threadsafe` instead of blocking. The Textual app has its own loop; the dashboard communicates with the Discord side via the session runner and shared settings/metrics—do not call Discord APIs from sink callbacks.

## Other considerations

### Voice encryption (DAVE)

Discord expects DAVE-capable clients. Keep `discord.py`, `PyNaCl`, `davey`, and related packages current. `discord.py`’s `[voice]` extra (pulled in by `discord-ext-voice-recv`) requires **PyNaCl below 1.6**; this repo matches that range so pip can resolve.

```bash
pip install --upgrade discord.py "PyNaCl>=1.5,<1.6" davey
```

### Transcription language

If `settings.json` has no `stt` block, the app defaults to `en-US` with English alternatives where the code supplies them. Set `stt.language_code` and `stt.alternative_language_codes` for your session ([supported languages](https://cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages)).

### No overlap while speaking

The bot pauses listening while it plays TTS. Mention detection does not run during playback by design.

### Session-only memory

Conversation state is not persisted across runs; transcript JSON under `transcripts/` is for debugging and analysis.

## Troubleshooting

### "DAVE library not found"

```bash
pip install --upgrade discord.py "PyNaCl>=1.5,<1.6" davey
```

Ensure `PyNaCl` (compatible with `discord.py[voice]`) and `davey` are installed.

### Speech-to-Text errors

Confirm `GOOGLE_STT_API_KEY` (v1) or v2 service account variables match `.env.example`, and that the API is enabled for the GCP project.

### No bot audio

- `ffmpeg -version`
- ElevenLabs key and persona `elevenlabs_voice_id` in `settings.json`
- Bot can **Connect** and **Speak** in the voice channel

### Bot not in server

Check token, intents, and OAuth2 scopes when generating the invite link.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, checks, and pull request expectations. Architecture and coding guardrails are in [`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## License

This project is released under the MIT License; see the [`LICENSE`](LICENSE) file.