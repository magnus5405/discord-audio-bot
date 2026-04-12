# Quick start

## 1. Python environment

Requires **Python 3.11+**.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -e .
```

Use `pip install -e ".[dev]"` if you plan to run tests, Ruff, or mypy.

## 2. Configure `.env`

```bash
cp .env.example .env
```

Fill in at minimum:

- `DISCORD_TOKEN`, `DISCORD_SERVER_ID`
- `GOOGLE_GEMINI_API_KEY`
- `GOOGLE_STT_API_KEY` (when using Speech-to-Text **v1**), or the v2 service-account variables from `.env.example`
- `ELEVENLABS_API_KEY` for spoken replies

See [README.md](README.md) for portal links and intent notes.

## 3. `settings.json`

Create or edit **`settings.json`** in the project root (personas, STT language, UI defaults). You can:

- Copy the example block from [README.md](README.md), or
- Run **`python -m src.ui.settings`** to edit and save without Discord, or
- Use **Settings** inside **`python -m src.main --tui`** after you have a working `.env`.

**Overrides**: values saved in `settings.json` (especially API keys and Discord fields from the TUI) take precedence over the same keys in `.env`. Keep `.env` for defaults and secrets on fresh machines; use the editor when you want everything in one file.

## 4. Run the bot

```bash
python -m src.main --tui
```

Pick a server, voice channel, and persona, then **Start**.

### Other entrypoints

| Command | Purpose |
|--------|---------|
| `python -m src.main` | Headless: uses `DISCORD_VOICE_CHANNEL_ID` and `BOT_TEST_AUDIO_PATH` if set |
| `python -m src.main --list-voice-channels` | Print guild and voice channel IDs |
| `python -m src.main --channel-id … --audio-path …` | Join and play one file |
| `python -m src.main … --receive-smoke` | Receive smoke test around playback |
| `python -m src.main … --transcribe` | STT-only session |
| `python -m src.main … --converse` | Full STT + GenAI + TTS loop |
| `python -m src.ui.settings` | Settings editor only |

Full behavior and architecture: [README.md](README.md).

## 5. Troubleshooting

```bash
pip install --upgrade pip setuptools wheel
pip install -e .
```

Discord voice stack:

```bash
pip install --upgrade 'discord.py[voice]'
```

Google STT: confirm `GOOGLE_STT_API_KEY` and that Speech-to-Text is enabled on the GCP project tied to that key.

## 6. Repo layout (where to look)

Application code lives under **`src/`** in packages such as `discord/`, `transcription/`, `conversation/`, `session/`, `storage/`, `tts/`, and `ui/`. See the **package map** in [README.md](README.md) for file names.

## 7. Quality checks (optional)

```bash
ruff check src/ tests/
mypy src/ --ignore-missing-imports --strict
pytest
```

Contributor notes: [`.github/copilot-instructions.md`](.github/copilot-instructions.md).
