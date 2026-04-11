# Discord Audio Bot - Project Structure

## Directory Organization

The project is organized into responsibility-driven packages

```
discord-audio-bot/
├── src/                              # Main package
│   ├── __init__.py                  # Package initialization
│   ├── main.py                      # Entry point & orchestrator
│   │
│   ├── models/                      # Core data structures
│   │   ├── __init__.py
│   │   ├── audio.py                # AudioFrame (≈40 lines)
│   │   ├── transcript.py           # TranscriptSegment, ConversationTurn (≈30 lines)
│   │   └── config.py               # Persona, UsageCounters (≈50 lines)
│   │
│   ├── discord/                     # Discord integration
│   │   ├── __init__.py
│   │   ├── client.py               # DiscordClient (≈60 lines)
│   │   ├── voice_sink.py           # DiscordAudioSink - per-user audio receive (≈70 lines)
│   │   └── playback.py             # VoicePlaybackManager (≈65 lines)
│   │
│   ├── transcription/               # Speech-to-Text pipeline
│   │   ├── __init__.py
│   │   ├── stt.py                  # GoogleSTTClient (≈75 lines)
│   │   ├── preprocessing.py        # Audio conversion utilities (≈60 lines)
│   │   └── vad.py                  # Voice Activity Detection (≈55 lines)
│   │
│   ├── conversation/                # Multi-turn conversation
│   │   ├── __init__.py
│   │   ├── chat.py                 # GenAIChatManager (≈85 lines)
│   │   ├── policy.py               # ReplyTriggerPolicy (≈145 lines)
│   │   ├── log.py                  # ConversationLog (≈65 lines)
│   │   └── persona.py              # PersonaManager (≈65 lines)
│   │
│   ├── tts/                         # Text-to-Speech synthesis
│   │   ├── __init__.py
│   │   └── elevenlabs.py           # ElevenLabsTTSClient (≈95 lines)
│   │
│   ├── storage/                     # Configuration persistence
│   │   ├── __init__.py
│   │   └── settings.py             # SettingsStore (≈145 lines)
│   │
│   └── ui/                          # User interface (Textual TUI)
│       ├── __init__.py
│       ├── main.py                 # Main control TUI (≈65 lines)
│       ├── settings.py             # Settings editor TUI (≈105 lines)
│       └── widgets/                # Custom Textual widgets
│           ├── __init__.py
│           ├── status.py           # BotStatus widget (≈20 lines)
│           └── selectors.py        # Selector widgets (≈30 lines)
│
├── tests/                           # Test suite
│   ├── __init__.py
│   ├── test_models.py              # Model tests
│   └── test_conversation.py        # Conversation tests
│
├── .github/                         # GitHub configuration
│   ├── copilot-instructions.md     # GitHub Copilot guidelines
│   ├── dependabot.yml              # Dependency automation
│   └── workflows/                  # CI/CD workflows (optional)
│
├── transcripts/                     # Session transcript outputs (gitkeep)
│
├── pyproject.toml                   # Project metadata & dependencies
├── requirements.txt                 # Pinned dependencies (pip)
├── requirements-dev.txt             # Development dependencies
├── .env.example                     # Environment template
├── .flake8                          # Flake8 linter config
├── pytest.ini                       # Pytest configuration
├── .pre-commit-config.yaml          # Pre-commit hooks
├── .gitignore                       # Git exclusions
├── dev.sh                           # Development commands (macOS/Linux)
├── dev.bat                          # Development commands (Windows)
├── settings.json                    # Bot persona & settings
├── README.md                        # User documentation
├── QUICKSTART.md                    # 5-minute setup
├── STRUCTURE.md                     # This file
└── PLAN.md                          # Architecture & design decisions
```

## Module Organization Principles

### 1. **Responsibility Segregation**
Each folder/package handles a single domain:
- `models/` - Data structures only (no logic)
- `discord/` - Discord API integration only
- `transcription/` - STT and audio processing only
- `conversation/` - Chat, triggers, and persona logic
- `tts/` - Synthesis API clients only
- `storage/` - Persistence only
- `ui/` - Textual UI only

### 2. **Reduced file line length**
- Keeps individual files focused and readable
- Easier to maintain and review
- Simpler for IDE navigation
- Reduces cognitive load

### 3. **Clear Import Hierarchy**
```
main.py
  ↓
discord/ + transcription/ + conversation/ + tts/ + storage/ + ui/
  ↓
models/ (lowest level - only depends on stdlib)
```

**Reverse imports are avoided** - models don't import from higher-level packages.

### 4. **Minimal External Imports Per File**
Each file imports only what it needs:
- `models/audio.py` → stdlib only
- `discord/client.py` → discord + logging
- `conversation/chat.py` → google.genai + logging + models

## Development Phases and Location

Code is tagged with Phase numbers to indicate implementation progress:

| Phase | Primary Location | Status |
|-------|------------------|--------|
| 1 | `discord/client.py`, `discord/playback.py` | Voice connectivity & playback |
| 2 | `discord/voice_sink.py` | Voice receive & pause/resume |
| 3 | `transcription/stt.py`, `transcription/preprocessing.py` | STT integration |
| 4 | `conversation/chat.py`, `conversation/policy.py` | GenAI & triggers |
| 5 | `tts/elevenlabs.py` | ElevenLabs TTS & playback loop |
| 6 | `ui/main.py`, `ui/settings.py` | TUI & settings editor |

## Import Examples

### Good - Minimal, Clear Imports
```python
# src/discord/voice_sink.py
import asyncio
import logging

import discord
from discord.ext.voice_recv import AudioSink

from ..models import AudioFrame
```

### Good - Namespace Imports
```python
# src/conversation/chat.py
import google.genai as genai
```

### Good - Package-Level Exports
```python
# src/discord/__init__.py
from .client import DiscordClient
from .voice_sink import DiscordAudioSink
from .playback import VoicePlaybackManager

__all__ = ["DiscordClient", "DiscordAudioSink", "VoicePlaybackManager"]
```

### Usage
```python
# In main.py or elsewhere
from src.discord import DiscordClient, VoicePlaybackManager
from src.models import AudioFrame, Persona
from src.conversation import GenAIChatManager
```

## Development Tools

### Code Quality Commands

| Command | Purpose |
|---------|---------|
| `dev.sh format` / `dev.bat format` | Format code (black + isort) |
| `dev.sh lint` / `dev.bat lint` | Lint with ruff |
| `dev.sh type` / `dev.bat type` | Type check with mypy |
| `dev.sh check` / `dev.bat check` | Run all checks |
| `dev.sh test` / `dev.bat test` | Run pytest |
| `dev.sh clean` / `dev.bat clean` | Clean cache files |

### Configuration Files

- **pyproject.toml** - Tool configs (black, ruff, mypy, pytest)
- **.flake8** - Flake8 settings
- **pytest.ini** - Pytest configuration
- **.pre-commit-config.yaml** - Automated pre-commit checks
- **.github/dependabot.yml** - Automated dependency updates

## Adding New Modules

When adding a new feature:

1. **Identify the domain** - Which folder does it belong in?
2. **Create file with clear responsibility** - Narrow scope
3. **Keep under 200 lines** - If growing larger, split into multiple files
4. **Add docstrings** - Module doc + class/function docs
5. **Add type hints** - All functions should have type annotations
6. **Update package `__init__.py`** - Export public API
7. **Write tests** - Add tests to `tests/` with same structure

### Example: Adding New Discord Feature
```
src/discord/
├── __init__.py          (add new class to __all__)
├── client.py            (existing)
├── voice_sink.py        (existing)
├── playback.py          (existing)
└── guild_manager.py     (NEW - <200 lines)

tests/
├── test_discord_client.py       (existing)
└── test_discord_guild.py        (NEW)
```

## Testing Strategy

Tests are organized to mirror `src/` structure:

```
tests/
├── test_models.py           # Models unit tests
├── test_conversation.py     # Conversation logic tests
├── test_discord.py          # Discord integration tests (integration)
├── conftest.py              # Shared fixtures (optional)
└── fixtures/                # Test data (if needed)
```

Run tests with:
```bash
pytest                      # All tests
pytest tests/test_models.py # Specific file
pytest -v                   # Verbose
pytest --cov=src           # With coverage
```

## Documentation

- **README.md** - User setup & running guide
- **QUICKSTART.md** - Quick 5-minute setup
- **PLAN.md** - Architecture & design decisions
- **STRUCTURE.md** - This file (module organization)
- **copilot-instructions.md** - GitHub Copilot guidelines
- Docstrings - In-code documentation on all public APIs

## Key Constraints

✓ **No circular imports** - Use imports only from lower to higher levels
✓ **Models are pure data** - No logic in `src/models/`
✓ **200-line max per file** - Encourages focused, single-purpose modules
✓ **Type hints everywhere** - All function signatures should have types
✓ **Comprehensive docstrings** - Every module, class, and function documented
✓ **No print() statements** - Use logging instead
✓ **Fail fast** - Exceptions propagate, no silent failures or retries
