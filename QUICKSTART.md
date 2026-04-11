# Quick Start Guide

## Initial Setup

### 1. Install Python & Dependencies

The project uses Python 3.11+ with all dependencies defined in `pyproject.toml`.

```bash
# Virtual environment already created with dependencies installed
# If you need to reinstall or update:
pip install -e .
```

### 2. Environment Configuration

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
# Edit .env with your text editor
```

**Required credentials to obtain first:**

- **Discord Bot Token** - [Discord Developer Portal](https://discord.com/developers/applications)
- **Google API Key** - [Google AI Studio](https://aistudio.google.com/) or Google Cloud Console
- **ElevenLabs API Key** - [ElevenLabs](https://elevenlabs.io/)

See [README.md](README.md) for detailed setup instructions for each service.

### 3. Settings & Personas

The project includes a default `settings.json` with three example personas:
- **Friendly Bot** - Helpful and conversational
- **Witty Bot** - Humorous and clever
- **Assistant Bot** - Professional and clear

You can edit this file to add/modify personas or they'll be editable via the settings TUI later.

## Running the Bot

### Command Line

```bash
# Activate virtual environment (if needed)
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # macOS/Linux

# Run the bot
python src/main.py
```

The bot will:
1. Load environment variables
2. Connect to Discord
3. Open the Textual control TUI in your terminal

## Development Phases

The implementation follows a phased approach starting with the basics:

**Phase 1**: Voice connectivity + playback (test audio)
**Phase 2**: Voice receive + pause/resume (capture speech)
**Phase 3**: STT integration (transcription)
**Phase 4**: Conversation policy + GenAI response
**Phase 5**: ElevenLabs TTS + full loop
**Phase 6**: Textual TUI polish & settings editor

See [PLAN.md](PLAN.md) for complete architecture documentation.

## Project Structure

```
src/
├── main.py              # Entry point & orchestrator
├── models.py            # Core data structures
├── discord_client.py    # Discord API integration
├── voice_*.py           # Voice connectivity (receive/playback)
├── stt_google.py        # Speech-to-Text transcription
├── genai_chat.py        # GenAI conversation
├── tts_elevenlabs.py    # Text-to-Speech synthesis
├── trigger_policy.py    # Reply trigger state machine
├── conversation_log.py  # Transcript management
├── persona.py           # Persona management
├── settings_store.py    # Settings persistence
└── tui_*.py             # Textual UI applications
```

## Troubleshooting

### Dependencies not installing?
```bash
pip install --upgrade pip setuptools wheel
pip install -e .
```

### Discord voice errors?
Ensure discord.py[voice] is installed with PyNaCl:
```bash
pip install 'discord.py[voice]' --upgrade
```

### Google Cloud credential issues?
Verify GOOGLE_APPLICATION_CREDENTIALS environment variable points to a valid service account JSON file.

## Next Steps

1. **Fill in `.env`** with your API credentials
2. **Review [PLAN.md](PLAN.md)** for architecture details
3. **Check [README.md](README.md)** for setup specifics per service
4. **Start implementing Phase 1** - see comments marked "Phase 1" in code
5. **Use GitHub Copilot** with guidance from `.github/copilot-instructions.md`

## Code Style

The project enforces consistent style before committing:

```bash
# Format code
black src/

# Sort imports
isort src/

# Check for style issues
ruff check src/
```

---

For comprehensive setup details, see [README.md](README.md).
For architecture & design, see [PLAN.md](PLAN.md).
