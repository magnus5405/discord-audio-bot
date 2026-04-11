# Discord Audio Bot

A sophisticated Discord voice-channel conversational bot with a Textual TUI. The bot joins voice channels, listens to speakers, transcribes speech in real-time, maintains multi-turn conversations using Google GenAI, and replies with synthesized speech via ElevenLabs.

## Features

- **Voice Integration**: Joins Discord voice channels via discord.py with DAVE encryption support
- **Real-time Transcription**: Per-user speech-to-text via Google Cloud Speech-to-Text (multi-language: Danish + English)
- **Conversational AI**: Multi-turn chat sessions with Google GenAI (Gemini) that maintain conversation context
- **Text-to-Speech**: Natural speech synthesis via ElevenLabs streaming TTS
- **Smart Reply Triggers**:
  - Default: Reply after 5 seconds of silence (max once per 3 minutes)
  - Mention Mode: Wait up to 30 seconds for silence after bot name is mentioned
  - Join Greeting: Introduce bot upon channel entry
- **Textual TUI**: No Discord slash commands—control everything via an intuitive terminal UI
- **Personas**: Configurable bot personalities with custom system instructions and voice profiles
- **Session Logging**: JSON transcripts and token usage tracking per session

## Project Structure

```
discord-audio-bot/
├── src/
│   ├── __init__.py             # Package metadata and exports
│   ├── main.py                 # Main orchestrator and launcher
│   ├── conversation/           # Chat state, personas, and reply policy
│   ├── discord/                # Discord gateway, receive, and playback
│   ├── models/                 # Core dataclasses and config models
│   ├── storage/                # Settings persistence
│   ├── transcription/          # Audio preprocessing, VAD, and STT
│   ├── tts/                    # ElevenLabs text-to-speech client
│   └── ui/                     # Textual TUI and custom widgets
├── tests/                      # Unit tests
├── transcripts/                # Session transcript outputs
├── .github/                    # GitHub configuration
├── .env.example                # Environment variable template
├── pyproject.toml              # Project metadata and dependencies
├── QUICKSTART.md               # Fast setup guide
├── STRUCTURE.md                # Additional module organization notes
├── README.md                   # This file
└── PLAN.md                     # Detailed architecture and design doc
```

## Prerequisites

- **Python 3.11+**
- **FFmpeg**: Required for audio encoding/decoding
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt-get install ffmpeg`
  - Windows: [Download from ffmpeg.org](https://ffmpeg.org/download.html) or `choco install ffmpeg`
- **System Opus library** (optional but recommended): Improves audio encoding performance
  - macOS: `brew install opus`
  - Ubuntu/Debian: `sudo apt-get install libopus0`

## Setup

### 1. Clone & Install

```bash
git clone https://github.com/yourusername/discord-audio-bot.git
cd discord-audio-bot
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
pip install -e .
```

### 2. Obtain API Credentials

You'll need credentials for three services:

#### Discord Bot Token
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and name it
3. Go to "Bot" → "Add Bot"
4. Under TOKEN, click "Copy" (or regenerate if needed)
5. **Important**: Enable these Intents under the bot settings:
   - `GUILD_VOICE_STATES` (to see who is in voice channels)
   - `GUILDS` (to see server list)
   - Keep `MESSAGE_CONTENT` disabled (the bot doesn't read text messages)

#### Google Cloud Setup
1. Create a [Google Cloud Project](https://console.cloud.google.com/)
2. **Option A - Gemini Developer API (Simpler)**:
   - Go to [Google AI Studio](https://aistudio.google.com/) and click "Get API key"
   - Copy the API key
3. **Option B - Vertex AI (requires billing)**:
   - Enable "Vertex AI API" in your Cloud project
   - Use service account JSON for authentication (see `PLAN.md` for details)
4. For **Speech-to-Text**, enable "Cloud Speech-to-Text API" and create a service account:
   - In Cloud Console: **APIs & Services** → **Credentials** → **Create Service Account**
   - Download JSON key file and save it locally
   - Set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json`

#### ElevenLabs API Key
1. Sign up at [ElevenLabs](https://elevenlabs.io/)
2. Go to Account → API Key
3. Copy your API key

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# Edit .env with your editor
```

Example `.env`:

```
# Discord Bot token
DISCORD_TOKEN=your_discord_bot_token_here

# Discord server ID
DISCORD_SERVER_ID=your_discord_server_id_here

# Google Cloud
GOOGLE_API_KEY=your_gemini_api_key_here

# ElevenLabs
ELEVENLABS_API_KEY=your_elevenlabs_key_here

# Bot Behavior 
BOT_REPLY_SILENCE_SECONDS=5
BOT_REPLY_COOLDOWN_SECONDS=180
BOT_MENTION_WINDOW_SECONDS=30
BOT_GREET_ON_JOIN=true
BOT_LANGUAGE=en-US
```

### 4. Create Initial Settings

Create `settings.json` in the project root:

```json
{
  "personas": [
    {
      "id": "friendly",
      "name": "Friendly Bot",
      "system_instruction": "You are a helpful Discord bot in a voice channel conversation. Be concise (1-2 sentences), friendly, and conversational.",
      "genai_model": "gemini-2.0-flash",
      "elevenlabs_voice_id": "EXAVITQu4vr4xnSDxMaL"
    },
    {
      "id": "witty",
      "name": "Witty Bot",
      "system_instruction": "You are a clever Discord bot known for witty remarks and humor. Keep replies brief and entertaining.",
      "genai_model": "gemini-2.0-flash",
      "elevenlabs_voice_id": "pFZP5JQG7iQjIQuC4Vig"
    }
  ],
  "ui": {
    "last_guild_id": null,
    "last_channel_id": null,
    "last_persona_id": "friendly"
  }
}
```

Note: ElevenLabs voice IDs are available in your account. See [supported voices](https://elevenlabs.io/docs/voices).

## Running

### Phase 1 Smoke Runner

```bash
python -m src.main --list-voice-channels
python -m src.main --channel-id 123456789012345678 --audio-path /path/to/local-test-clip.mp3
```

The current phase-one runner is headless and focused on validating Discord voice connectivity. It can:
1. Load environment variables from `.env`
2. Connect to Discord and print reachable guild/voice channel IDs
3. Join a selected voice channel and play a local MP3/WAV clip once
4. Disconnect cleanly when playback completes

If you prefer env fallbacks instead of repeating flags, set `DISCORD_VOICE_CHANNEL_ID` and `BOT_TEST_AUDIO_PATH`, then run:

```bash
python -m src.main
```

### Planned Later

The Textual TUI scaffold remains in the repository, but it is still phase-six work. The current start/stop, selectors, and settings screens are not wired into the live Discord flow yet.

### Phase 1 Workflow

- Run `python -m src.main --list-voice-channels` to find the target channel ID.
- Run `python -m src.main --channel-id <voice_channel_id> --audio-path <local_mp3_or_wav>` to join and play a clip.
- Ensure `ffmpeg` is on your `PATH`, and that `discord.py[voice]`, `PyNaCl`, and `davey` are installed.

## Development & Architecture

See [PLAN.md](PLAN.md) for the complete design document, including:

- Detailed architecture and data flow
- Component breakdown by responsibility
- Threading and async boundaries
- Phase-by-phase implementation roadmap
- Design decisions and rationale
- Data format specifications

### Project Structure

The `src/` folder is organized into responsibility-focused packages:

```
src/
├── __init__.py              # Package metadata and exports
├── main.py                  # Main entry point and orchestration
├── conversation/
│   ├── __init__.py          # Conversation package exports
│   ├── chat.py              # Google GenAI chat manager
│   ├── log.py               # Conversation history and transcript helpers
│   ├── persona.py           # Persona management
│   └── policy.py            # Reply trigger state machine
├── discord/
│   ├── __init__.py          # Discord integration exports
│   ├── client.py            # Discord client lifecycle
│   ├── playback.py          # Voice playback coordination
│   └── voice_sink.py        # Incoming voice receive sink
├── models/
│   ├── __init__.py          # Shared model exports
│   ├── audio.py             # Audio frame types
│   ├── config.py            # Persona and usage config models
│   └── transcript.py        # Transcript and conversation turn models
├── storage/
│   ├── __init__.py          # Storage package exports
│   └── settings.py          # Settings store
├── transcription/
│   ├── __init__.py          # Transcription package exports
│   ├── preprocessing.py     # Audio conversion utilities
│   ├── stt.py               # Google Speech-to-Text client
│   └── vad.py               # Voice activity detection
├── tts/
│   ├── __init__.py          # TTS package exports
│   └── elevenlabs.py        # ElevenLabs synthesis client
└── ui/
    ├── __init__.py          # UI package exports
    ├── main.py              # Main Textual control screen
    ├── settings.py          # Settings editor UI
    └── widgets/
        ├── __init__.py      # Widget exports
        ├── selectors.py     # Guild/channel and persona selectors
        └── status.py        # Status and counters widget
```

Each module is kept **under 200 lines** for maintainability, with clear separation of concerns.

---

## Development & Testing

### Setup Development Environment

```bash
# Install development dependencies
pip install -e ".[dev]"

# Or using requirements file
pip install -r requirements-dev.txt

# Install pre-commit hooks for automatic code checks
pre-commit install
```

### Code Quality & Linting

We use several tools to maintain code quality:

#### Automatic Formatting (Black + isort)

```bash
# Windows
dev.bat format

# macOS/Linux
./dev.sh format

# Or manually
black src/ tests/
isort src/ tests/
```

#### Linting (Ruff)

```bash
# Windows
dev.bat lint

# macOS/Linux
./dev.sh lint

# Or manually
ruff check src/
```

#### Type Checking (mypy)

```bash
# Windows
dev.bat type

# macOS/Linux
./dev.sh type

# Or manually
mypy src/ --ignore-missing-imports --strict
```

#### All Checks

```bash
# Windows
dev.bat check

# macOS/Linux
./dev.sh check
```

### Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_models.py

# Run with coverage report
pytest --cov=src --cov-report=html

# Windows helper
dev.bat test

# macOS/Linux helper
./dev.sh test
```

### Cleanup

```bash
# Remove cache and build files
# Windows
dev.bat clean

# macOS/Linux
./dev.sh clean
```

### Pre-commit Hooks

The `.pre-commit-config.yaml` automatically runs checks before commits:

```bash
# Install hooks (one-time)
pre-commit install

# Run on all files
pre-commit run --all-files

# Skip hooks for a commit (not recommended)
git commit --no-verify
```

### Code Style Guidelines

- **Max line length**: 100 characters
- **Python version**: 3.11+
- **Formatter**: Black
- **Import sorter**: isort (Black profile)
- **Linter**: Ruff
- **Type checker**: mypy

All files in `src/` should:
- Have comprehensive docstrings
- Include type hints on all functions
- Stay under **200 lines** per file
- Follow existing module organization (see Project Structure)

### Commit Message Format

```
type(scope): short description (50 chars max)

Longer description if needed (72 char wrap)

- Bullet points for changes
- One per line

Closes #123
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`

---

## Key Design Points

### Voice Encryption (DAVE)
As of March 1, 2026, Discord requires DAVE end-to-end encryption. Ensure your `discord.py` and dependencies are up-to-date:

```bash
pip install --upgrade discord.py[voice]
```

### Transcription Language
Default is Danish (`da-DK`) with English alternatives. Modify `BOT_STT_ALTERNATIVE_LANGUAGES` in `.env` to support other languages via [Google Speech-to-Text Codes](https://cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages).

### No Interruptions
The bot stops listening while it is speaking. This is a by-design feature to avoid concurrent transcription and synthesis issues. You cannot detect "mentions" during bot speech; this is documented as a known limitation.

### Session-Only Memory
Conversation state is NOT persisted between sessions. Each run starts fresh. Transcripts are saved to JSON in `transcripts/` for debugging only.

---

## Troubleshooting

### "DAVE library not found" on voice connect
Ensure `discord.py[voice]` is installed and PyNaCl is available:
```bash
pip install --upgrade 'discord.py[voice]'
```

### "Couldn't connect to Google Speech-to-Text"
Verify `GOOGLE_APPLICATION_CREDENTIALS` points to a valid service account JSON:
```bash
echo $GOOGLE_APPLICATION_CREDENTIALS
```

### "No audio from bot"
- Check FFmpeg is installed: `ffmpeg -version`
- Verify ElevenLabs API key and voice_id in `settings.json`
- Check bot has permission to speak in the voice channel

### Discord bot not appearing in server
- Verify bot token in `.env`
- In Developer Portal, grant "View Channels" and "Connect" (voice) permissions
- Re-invite the bot with the correct OAuth2 scope (`bot` + `applications.commands`)

---

## Contributing

See `.github/copilot-instructions.md` for guidelines on code organization and using GitHub Copilot for development.

## License

MIT

## References

- [discord.py Docs](https://discordpy.readthedocs.io/)
- [discord-ext-voice-recv GitHub](https://github.com/imayhaveborkedit/discord-ext-voice-recv)
- [Google Cloud Speech-to-Text](https://cloud.google.com/speech-to-text/docs)
- [Google GenAI Python SDK](https://github.com/google-gemini/generative-ai-python)
- [ElevenLabs API Docs](https://elevenlabs.io/docs/api)
- [Textual Framework](https://textual.textualize.io/)
