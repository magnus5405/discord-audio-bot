# Voice-Channel Conversational Bot for Discord

## Project overview and constraints

You want a single Python program that joins a voice channel in entity["company","Discord","chat platform company"], listens to each speaker, transcribes each user’s speech to text, maintains a rolling multi-turn conversation with entity["company","Google","tech company"]’s GenAI SDK, generates a short spoken reply as a “person in the call,” and speaks that reply back into the same voice channel via entity["company","ElevenLabs","ai voice company"] text-to-speech.

The Discord stack is explicitly: `discord.py` (by entity["people","Rapptz","discord.py maintainer"]) + the community voice receive extension `discord-ext-voice-recv`, because voice receive is not in the core `discord.py` public API in the way voice send is. The extension is built around the idea of a receive “sink,” mirroring `discord.py`’s send “source” API, and calls your sink for each chunk of audio received.

Two constraints are especially important given today’s date (April 11, 2026):

- Modern Discord voice calls require DAVE end-to-end encryption support; Discord announced that starting March 1, 2026, clients/apps without DAVE support can’t participate in calls. So you must ensure your installed voice stack (discord.py + dependencies) is new enough and has the required crypto dependencies.  
- `discord.py` voice now hard-requires both PyNaCl and a DAVE implementation; `VoiceClient` raises at runtime if those are missing.

Your runtime behavior rules (already decided) are:

- Reply trigger policy:  
  - Default: reply after 5 seconds of silence, but at most once every 3 minutes.  
  - Mention: if the bot’s nickname (its current server/channel nickname) is said, wait up to 30 seconds for a 5-second silence; if none arrives, reply at the end of the 30 seconds anyway.  
  - On join: generate and speak a hello after showing the agent the list of users currently present.
  - On other user join: generate and greet the user when they join the channel, announcing their entrance.
- Transcription: use Google Cloud Speech-to-Text (multi-language). Streaming STT is gRPC-only and designed for real-time audio.  
- Speaking vs listening: when the bot begins “processing → generating → speaking,” it stops transcribing the channel until the bot finishes speaking, then resumes. This aligns well with the sink approach because you can stop listening and later resume.  
- Conversation memory: session-only (rolling chat history in the GenAI chat session). The GenAI SDK’s `Chat` object is explicitly designed to maintain conversation state (history) and to send messages in multi-turn style.  
- Transcript structure: the AI gets a merged, ordered conversation log with “username: utterance” entries since last bot turn (or since join), including overlap markers if needed.  
- No text chat output; no Discord slash commands; control is exclusively via a Textual TUI.  
- Failure behavior: crash/stop the session on error (no retries). This is primarily an application design choice, but it is compatible with the libraries’ exception-forwarding model (e.g., Discord voice play raises if already playing; STT/GenAI/TTS calls raise on request errors).

## Additional questions and “smarter options” to decide before coding

You answered 20 important questions already; the items below are additional design decisions that can prevent rework (and in a few cases offer better latency or quality). They’re intentionally practical and implementation-facing.

- Should “mention replies” ignore the 3-minute cooldown entirely, or should there be a separate (shorter) mention cooldown to prevent spam if people repeat the nickname? (This affects the trigger finite-state machine, not the core library integrations.)  
- Do you want interim (partial) transcripts used only for mention detection, or also for updating the live TUI transcript view? Google streaming returns interim vs final results; you likely want to persist only final text in the conversation log, but interim can improve responsiveness for mention detection.  
- What should the bot do if it detects its name mentioned while it is currently speaking (even though you pause STT while speaking)? If you pause listening entirely, you won’t detect mentions during speech; if that’s acceptable, document it as a known limitation.  
- Should the bot’s reply language follow the last speaker’s language, the detected STT language, or a persona-specific “default language”? (This is persona policy + prompt design.)  
- Should the bot address a particular user when multiple people spoke during the segment? For example: respond to the user who mentioned the bot, else the last speaker, else the speaker with the most words since the last bot turn. (This is a transcript-merging heuristic.)  
- Do you want any local pre-processing like VAD (voice activity detection) to segment utterances more cleanly before sending to STT? WebRTC VAD is fast and commonly used for voiced/unvoiced classification, but it adds resampling/mono requirements.  
- Do you want the ElevenLabs TTS to be “download full MP3 then play” (simpler, higher latency) or “stream bytes into playback” (lower latency, more plumbing)? ElevenLabs explicitly supports HTTP chunked streaming for TTS.  
- How “exact” must the “minutes of voice generated” counter be: computed from the audio played (duration measured after generation), or taken from an ElevenLabs usage endpoint (which is time-bucketed and not per-request)? ElevenLabs provides a character usage metrics endpoint with time-axis aggregation that’s great for dashboards, but you’ll still likely want per-request local duration for a per-session counter.  
- How should persona changes behave mid-session: immediate (new system instruction next reply) or “restart chat history” (fresh context)? The GenAI SDK chat model keeps conversation history unless you start a new chat object.  
- Which “Google GenAI endpoint mode” are you using: Gemini Developer API via API key, or Vertex AI via ADC/project/location? The GenAI Python client supports both, and also supports pulling the API key from environment variables.  
- Should transcripts be stored one JSON file per session (recommended), or a rolling append log? “Session file per run” makes debugging deterministic and easy to diff. (Local logging design choice.)

## Documentation-backed building blocks and the parts you need from each dependency

### Discord voice send via `discord.py`

You will rely on `discord.py`’s voice connection object (`VoiceClient`) for actually sending audio into the channel. The key method is `VoiceClient.play(source, after=...)`, which plays an `AudioSource` and invokes an `after` callback when playback ends or errors. You’ll also use `stop()` and `is_playing()` to control “speaking mode” in your pipeline.

Two installation/runtime requirements matter for your design:

- Voice support requires installing discord.py with voice extras (PyNaCl). The official installation guide explicitly calls out `discord.py[voice]` for voice support.  
- PCM-based audio sources require an Opus library to be present/loaded; otherwise you must provide an Opus-encoded source (e.g., via FFmpeg producing Opus). This is called out in the `VoiceClient` documentation.  

Because you want to play MP3 from ElevenLabs, a practical approach is:

- Generate TTS as MP3 (ElevenLabs supports MP3 output formats).  
- Use an FFmpeg-backed Discord audio source to decode/encode as needed (exact choice depends on whether you want to depend on Opus being loaded in Python vs letting FFmpeg output Opus). The overarching constraint (“PCM needs Opus; Opus sources avoid that”) is explicit in the `VoiceClient` docs.  

Finally, DAVE support is mandatory for Discord calls now, and discord.py’s internal voice client checks for a DAVE library at runtime. You should treat this as a hard pre-flight requirement, not a “nice-to-have.”

### Discord voice receive via `discord-ext-voice-recv`

Your receive pipeline depends on `discord-ext-voice-recv`’s sink model. Key concepts to use:

- The extension explicitly mirrors discord.py’s voice send API: send uses `AudioSource`, receive uses `AudioSink`. A sink is effectively “inverse of a source,” called by the library with audio chunks, and sinks can be composed into pipelines.  
- Practically, this gives you the hook you need to attribute audio to specific speakers (per-user audio handling) so you can transcribe “who said what” without doing speaker diarization yourself. (You’ll still need to handle overlaps logically, but you’ll have per-user streams.)

What you need to implement with it:

- A sink that receives audio frames and puts them into per-user buffers (keyed by Discord user ID) with timestamps.
- A mechanism to pause and resume listening when the bot is speaking (you said: stop writing transcript while speaking).
- (Optionally) speaking start/stop events if you want better “silence detection” than just checking the audio buffers. The extension’s design allows callback-based processing pipelines, which is exactly what you need for a VAD/silence-driven trigger.

### Google Cloud Speech-to-Text for transcription

You want real-time capture and multi-language transcription. The critical documentation constraints:

- Streaming recognition is available via gRPC only.  
- For best results, Google recommends using lossless encodings like LINEAR16/FLAC, and recommends 16 kHz as “optimal”; if you can’t, you should use the native sample rate rather than resampling (this matters because Discord audio is typically 48 kHz).  
- The recognition config supports a main `languageCode` and additional alternative language codes (up to 3) for language detection among those options. This is how you can support Danish+English without forcing users to choose a language each time.  
- Streaming results include interim vs final results (`is_final`), and stability can change; you should treat final results as the canonical transcript entries for logging and for prompting the LLM.

Practical design implication for your project:

- Use per-user streaming recognition sessions (one stream per active speaker) OR micro-batch recognition per utterance (send a short WAV/FLAC chunk after VAD determines end-of-utterance).  
- If you want the “5 seconds silence” rule across the whole channel, you’ll want a channel-level “activity clock” plus per-user utterance segmentation, not just raw “no PCM frames” checks (because Discord can deliver silence differently depending on decoder behavior). Google already provides “speech end” behaviors and finalization semantics in streaming, but your policy (5s gap + 3m cooldown + mention exception) is easiest to implement at your own trigger layer using timestamps.  

### Google GenAI SDK (`python-genai`) for conversation and token accounting

You want LLM responses with ongoing session context and accurate token stats.

Key APIs from the SDK documentation:

- Initialize a `genai.Client(...)` and let it read an API key from environment variables (Gemini Developer API key) if you prefer not to pass keys in code. The docs explicitly reference `GOOGLE_API_KEY` / `GOOGLE_API_KEY`-style environment usage.  
- Use `client.chats.create(...)` to create a chat session that maintains conversation state (history) and provides `send_message()`, streaming variants, and `get_history()`.  
- The response from `send_message` includes `usage_metadata` token usage information.  
- You can also count tokens pre-flight with `count_tokens`, including for multi-turn chat history, and `usage_metadata` provides fields like `prompt_token_count`, `candidates_token_count`, and `total_token_count`.  
- You can set “system instructions” (persona instruction) and other generation controls (temperature, max tokens, etc.) via the config for `generate_content` (and you can treat the chat’s first system turn similarly by seeding the chat history).  

Practical implications for your persona system:

- Store persona instructions in your settings file, and apply them consistently as the system instruction (either via config in `generate_content`, or by “priming” the chat history with a system turn depending on the exact method you choose).  
- Track token totals (session cumulative) by summing `usage_metadata.total_token_count` from each model interaction.  

### ElevenLabs TTS for streaming voice output and usage metrics

You want low-latency voice. The ElevenLabs documentation provides:

- A streaming TTS endpoint: `POST https://api.elevenlabs.io/v1/text-to-speech/:voice_id/stream`, which returns audio as an audio stream (chunked). It supports query param `output_format` like `mp3_44100_128`, an optional `optimize_streaming_latency` (deprecated but documented), and request fields such as `text`, `model_id`, and optional voice settings.  
- Authentication: API key in the `xi-api-key` header.  
- A usage endpoint: `GET /v1/usage/character-stats` returning a time axis and aggregated usage values, with options to break down and aggregate. This is useful for “dashboard-level” and time-window usage reporting.  
- A streaming overview: the API uses HTTP chunked transfer encoding, and their official Python SDK includes helpers for handling streaming chunks.  

Practical implications for your “minutes generated” and “low latency” goals:

- For per-session voice minutes, compute locally from the audio you actually play (duration measured from decoded audio or via ffprobe-like tooling). The ElevenLabs usage endpoint is aggregated over time and is not inherently per-request nor per-session.  
- For latency, use the streaming endpoint and start playback as soon as you have enough bytes to feed FFmpeg. The documentation explicitly supports processing streamed bytes incrementally.  

### Textual TUI (`textual` by Textualize.io)

You want a TUI that:

- Shows running status, speech-to-text minutes, token totals,  voice minutes.  
- Offers start/stop.  
- Lists reachable guilds and voice channels and lets you pick one.  
- Provides a dropdown for character selection and a settings editor (preferably separate UI).  

Textual is a Python TUI framework built by entity["company","Textualize","python tui company"], and it is async under the hood and designed to integrate with async libraries. You’ll use:

- `App` as the root class and `run()` to start it.  
- Reactive attributes to keep UI counters (tokens, minutes, running state) synchronized with background state updates.  
- Widgets: `Select` for dropdowns (guild, channel, persona), `Button` for start/stop, and other widgets as needed.  
- Concurrency guidance: Textual provides mechanisms (Worker API) to avoid blocking the UI when you do IO-heavy work, which fits your separation between Discord event loop work and UI updates.  

### `.env` management with python-dotenv

Your desired “all keys in .env” approach is directly supported by `python-dotenv`:

- `load_dotenv()` locates a `.env` file, reads key/value pairs, and sets them in `os.environ` (without overriding existing env by default). This matches your desired pattern for Discord token, Google keys, ElevenLabs key, and cooldown/config values.  

## System architecture and data flow

### High-level pipeline

A robust architecture for your exact behavior is a state machine with three major modes:

- **Listening mode**: bot is in voice channel, receiving audio frames per user, building utterances, transcribing, and appending transcript entries.  
- **Thinking mode**: bot has decided to respond (based on 5-second silence + cooldown, or mention policy). It freezes input (stops listening), sends a single consolidated “conversation since last bot turn” to GenAI chat, and receives a short text reply.  
- **Speaking mode**: bot sends reply text to ElevenLabs, receives audio (MP3 stream or full MP3), plays it into the Discord voice channel, and when playback finishes it returns to Listening mode.  

This matches your requirement that the bot does not interrupt itself or react to new speech while it’s speaking.

### Suggested component breakdown (Python modules)

A maintainable project structure is easiest if you isolate protocol glue from policy logic:

- **Discord layer**  
  - `discord_client.py`: connects the bot, caches guild/channel lists, handles joining/leaving voice channels, owns the active voice client.  
  - `voice_receive.py`: defines the `AudioSink` implementation(s), per-user buffers, and thread-safe forwarding of audio frames into async processing.  
  - `voice_playback.py`: plays back generated audio via `VoiceClient.play`, and exposes “play complete” as an awaitable event to the orchestrator.  

- **Transcription layer**  
  - `stt_google.py`: streaming Speech-to-Text client; starts/stops per-user streams or per-utterance calls, emits final transcript segments with timestamps.  
  - `audio_preprocess.py`: decode to LINEAR16, mono, and (optionally) resample to 16 kHz for best STT performance; or keep 48 kHz native if you follow Google’s “use native sample rate if you can’t 16 kHz” guidance.  
  - `vad.py` (optional): VAD to segment utterances and detect silence boundaries.  

- **Conversation + policy layer**  
  - `conversation_log.py`: merges per-user transcript segments into a single ordered log; tags overlaps; supports “since last bot turn” slicing.  
  - `trigger_policy.py`: implements 5s silence + 3m cooldown and mention override with 30s deadline.  
  - `genai_chat.py`: owns the GenAI `Chat` session; constructs prompt turns; consumes `usage_metadata` to accumulate tokens.  
  - `persona.py`: loads persona settings (name, instruction, voice_id, GenAI model ID), applies system instruction and other config knobs.  

- **TTS layer**  
  - `tts_elevenlabs.py`: calls ElevenLabs streaming speech endpoint, returns an audio byte iterator or a saved MP3 file path, depending on your playback strategy.  
  - `usage_metrics.py` (optional): calls `/v1/usage/character-stats` if you want to display account/workspace usage windows in the UI.  

- **TUI layer**  
  - `tui_main.py`: Textual app with start/stop, server/channel selection, persona selection, stats display. Uses reactive attributes for live counters and a worker/task pipeline for background updates.  
  - `tui_settings.py`: separate Textual app for editing personas and model/voice defaults, saved to a settings file.  

- **Orchestrator**  
  - `main.py`: loads `.env`, starts Discord client, spawns a second terminal window running the TUI (platform-specific), keeps main console for logs, and runs the session state machine. `.env` loading via `load_dotenv()` is standard and matches your key storage requirement.  

### Threading and async boundaries (the “won’t deadlock” approach)

You should assume three concurrency domains:

- The Discord client runs on asyncio (discord.py’s event loop model).  
- The voice receive sink callbacks may be invoked in non-async contexts (often a receive thread). Your sink should do minimal work and forward audio frames into an asyncio queue using a thread-safe mechanism (e.g., `loop.call_soon_threadsafe`). The extension’s sink model is callback-driven, which is consistent with this pattern.  
- The Textual UI runs its own async tasks and expects you not to block the UI thread; use reactives + workers or message passing to update counters.  

This leads to a clean integration pattern:

- **Voice sink (callback)** → minimal frame packaging → push to `asyncio.Queue` thread-safely.  
- **Async STT tasks** consume queue, do buffering + segmentation, call gRPC STT streaming, emit transcript events.  
- **Trigger policy task** watches transcript events + timestamps; on trigger, flips the orchestrator state to Thinking/Speaking.  
- **Speaking state** stops listening, generates reply, plays audio, waits for playback completion via discord.py’s `after` callback → returns to Listening.  

### Data formats you should standardize early

Define these internal event/data structures early (even as dataclasses), because they’re the “interfaces” between modules:

- `AudioFrame`: `{user_id, pcm_bytes, sample_rate_hz, channels, timestamp_monotonic}`  
- `TranscriptSegment`: `{user_id, username, text, start_ts, end_ts, is_final}` (no language code, language is automatically detected)  
- `ConversationTurn`: `{role: "user"|"model", text, ts}` with “user” turns formatted like:  
  - `Magnus: ...`  
  - `Storm: ...`  
  - `[overlap] Storm + Rasmus: ...` (only if needed)  
- `Persona`: `{persona_id, display_name, system_instruction, genai_model, elevenlabs_voice_id}`  
- `UsageCounters`: `{total_tokens, tts_seconds_generated, stt_seconds_processed(optional)}` where token totals come from GenAI `usage_metadata` and audio duration is computed from generated audio.  

## Implementation plan and milestone checkpoints

### Build order that de-risks the project

This order is designed to surface the “hard stuff” (voice connect + DAVE, receive plumbing, playback) early, before you invest in UI polish.

**Phase one: Voice connectivity + playback sanity**

- Install and validate voice dependencies: `discord.py[voice]` so voice is available, and confirm the DAVE requirement is satisfied (otherwise voice will fail at runtime).  
- Implement minimal bot that can:
  - Connect to Discord gateway
  - Join a chosen voice channel
  - Play a known local MP3/wav clip and report completion using `VoiceClient.play(..., after=...)`.  

Checkpoint: you can reliably join a voice channel and play audio end-to-end.

**Phase two: Voice receive plumbing (no STT yet)**

- Integrate `discord-ext-voice-recv` and implement a sink that logs “received audio from user X” and frame counts.  
- Validate “pause listening while speaking”: when you call playback, stop your receive pipeline; when playback completes, resume. This is where you enforce the “no transcription while speaking” rule.  

Checkpoint: you can receive per-user audio frames reliably and pause/resume receiving around playback.

**Phase three: STT integration per user**

- Decide whether you will:  
  - Stream continuously per user (gRPC streaming sessions), or  
  - Segment by VAD and call recognition on each utterance.  
- Implement STT with Google Cloud Speech-to-Text streaming (gRPC-only). Set config for:
  - LINEAR16
  - sample rate (either 48k native or 16k if you resample)
- Emit `TranscriptSegment` events, persist final transcripts only to the conversation log.  

Checkpoint: live per-user transcripts appear and are attributed correctly.

**Phase four: Conversation policy + GenAI**

- Build merged “since last bot turn” transcript formatting.  
- Implement the exact trigger state machine:
  - Track `last_human_speech_ts` (from audio frames or final transcript end timestamps)
  - Track `last_bot_reply_ts`
  - Implement 5s silence trigger (only if you have any transcript since last reply)
  - Implement mention override with 30s deadline.  
- Create GenAI chat session: `client.chats.create(...)`; on each bot response, send a single consolidated message describing the recent transcript block and asking for a short reply. Retrieve `usage_metadata` and accumulate tokens.  
- Add “hello on join” behavior: after joining channel and collecting participant list, send that as a first context message and generate a greeting.  

Checkpoint: bot replies with text that reacts to humans, under the silence + mention rules, and token totals update.

**Phase five: ElevenLabs TTS + Discord playback integration**

- Implement ElevenLabs streaming TTS:
  - `POST /v1/text-to-speech/:voice_id/stream`
  - `xi-api-key` header
  - `output_format=mp3_44100_128` (or your chosen mp3 format).  
- Decide playback strategy:
  - MVP: collect streamed bytes into a temp MP3 file, then play it.  
  - Latency-optimized: pipe bytes to FFmpeg as they stream (requires extra plumbing but aligns with ElevenLabs streaming design).  
- Compute “voice minutes” counter from the audio you generated/played. (Optionally also show ElevenLabs aggregated usage via the character-stats endpoint.)  

Checkpoint: full voice conversation loop works: humans speak → transcript → GenAI → ElevenLabs → bot speaks → repeat.

**Phase six: Textual TUI polish + settings UI**

- Build main TUI:
  - Guild selector
  - Voice channel list and “join” action
  - Persona select dropdown
  - Start/stop toggle
  - Live counters (running, total tokens, generated voice time)
  - Status area showing current guild/channel and last bot action.  
- Build settings UI (separate Textual app) that edits and saves:
  - Personas (instruction, GenAI model, ElevenLabs voice_id)
  - Default cooldown values (or show they come from `.env`)
  - Default language preferences.  
- Launch model: `main.py` stays as the log console; it spawns a terminal running `tui_main.py`. (This is OS-specific; document the supported terminals/commands.) Textual itself is cross-platform and runs in standard terminals.  

Checkpoint: you can run the bot without Discord commands; everything is controlled and observable in the TUI.

## Configuration, local storage, and observability

### Environment variables in `.env`

Use `python-dotenv` at the very start of `main.py`:

- `load_dotenv()` searches for `.env`, loads values into environment variables, and avoids overriding existing env by default. This fits local development and also deployment environments where secrets may be injected differently.  

Recommended `.env` keys (names are suggestions; pick stable names and document them):

- `DISCORD_TOKEN=...`
- `DISCORD_SERVER_ID=...`
- `GOOGLE_API_KEY=...` (if using Gemini Developer API key auth)  
- `ELEVENLABS_API_KEY=...` (used as `xi-api-key`)  
- `BOT_REPLY_SILENCE_SECONDS=5`
- `BOT_REPLY_COOLDOWN_SECONDS=180`
- `BOT_MENTION_WINDOW_SECONDS=30`
- `BOT_DEFAULT_GENAI_MODEL=...` (or store in settings file)
- `BOT_DEFAULT_ELEVEN_VOICE_ID=...` (or store in settings file)  

For Google Speech-to-Text credentials, you will likely also need standard Google Cloud auth environment configuration (implementation detail depends on whether you use service account JSON or ADC), but your core pipeline design is unaffected by that decision.  

### Settings file for personas

Store personas and UI defaults in a JSON (or YAML) file, e.g. `settings.json`:

- `personas`: array of `{id, name, system_instruction, genai_model, elevenlabs_voice_id}`
- `ui`: last selected guild/channel/persona IDs

This cleanly separates “secrets” (in `.env`) from “preferences/config” (settings file).  

### Transcript storage

Write transcripts as JSON for debugging (session-only, not loaded later, per your requirement). Recommended output:

- One file per session: `transcripts/YYYY-MM-DD_HHMMSS_guild_channel.json`
- Store:
  - session metadata (guild_id, channel_id, persona_id, start time)
  - ordered transcript segments
  - bot replies (text) and timestamps
  - token usage per LLM call and cumulative totals  

### Usage counters

- **Total tokens**: sum GenAI `usage_metadata.total_token_count` across interactions.  
- **Voice minutes**: compute from audio you generated and played (local duration) and show cumulative seconds/minutes. ElevenLabs provides aggregated usage stats by time window, but that is a separate “account usage” view, not a session counter.  

## Initial “project generation” prompt

Below is a single prompt you can paste into a coding LLM (or into a “create project” workflow) to generate the initial repository skeleton and MVP implementation. It is intentionally explicit about architecture, file layout, and library usage contracts.

Use it as-is, then iterate.

---

**Prompt**

Create a Python 3.11+ project that implements a Discord voice-channel conversational bot with a Textual TUI. The bot joins a selected voice channel, receives per-user audio via discord-ext-voice-recv, transcribes speech per user via Google Cloud Speech-to-Text, merges transcripts into an ordered conversation log, triggers replies based on silence/mention rules, sends transcript context to Google GenAI (python-genai) as a multi-turn chat session, synthesizes the reply using ElevenLabs streaming TTS, and plays the resulting audio into the Discord voice channel. The program is controlled exclusively via a Textual TUI (no Discord slash commands, no text chat output).

Hard requirements and constraints:

- Use discord.py + discord-ext-voice-recv for voice receive:
  - Connect to a voice channel using VoiceRecvClient (or equivalent supported by the extension).
  - Implement an AudioSink that receives audio frames for each user and forwards them to the async pipeline safely.
  - Provide a way to stop listening while the bot is speaking and then resume listening after playback.
- Use discord.py voice send for playback:
  - Use VoiceClient.play(...) with an FFmpeg-based AudioSource to play MP3 produced by ElevenLabs.
  - Playback must be “blocking” in the sense that the bot stops listening and transcribing while speaking; only resume after playback finishes.
- Transcription:
  - Use Google Cloud Speech-to-Text streaming recognition (gRPC).
  - Automatic language detection.
  - Save final transcript segments (with username attribution) into an in-memory session conversation log; also persist to JSON on disk for debugging (but do not reload across sessions).
- Reply trigger policy (must implement exactly):
  - Default: if there is at least one transcript segment since the bot last spoke (or joined), and the channel has 5 seconds of silence, generate a reply; but no more than once every 3 minutes.
  - Mention override: the bot’s mention name is its current nickname in the guild/channel. If that nickname appears in any transcript since last bot reply, start a 30-second “mention window”: wait for a 5-second silence inside that window; if none occurs, force a reply at the end of the 30 seconds.
  - On join: once connected to a voice channel, generate and speak a hello. Provide the GenAI prompt with: list of users currently in the voice channel and a note that it just joined.
- Conversation and persona:
  - Use python-genai to create a chat session that maintains conversation state across the session only.
  - Personas: only one active persona at a time, selectable from the TUI. Persona has: name, system instruction, GenAI model ID, ElevenLabs voice_id.
  - The bot’s spoken name is dynamic and derived from its current Discord nickname; persona config still has its own “persona name” for internal reference.
  - Replies should be short (1–2 sentences) but may be longer occasionally.
- ElevenLabs:
  - Use the ElevenLabs streaming TTS endpoint to generate MP3 (output format MP3 is fine).
  - Track per-session “seconds/minutes of voice generated” based on audio duration you generated/played.
- TUI (Textual):
  - When main.py runs, keep the main terminal for logs/errors and open a second terminal window for the Textual TUI.
  - Main TUI shows:
    - running status
    - total tokens spent (cumulative from GenAI usage_metadata)
    - minutes of voice generated (cumulative per session)
    - start/stop button for the session
    - server (guild) selector and voice channel picker (click to connect)
    - persona dropdown selector
    - highlight the currently connected voice channel
    - a settings menu entry
  - A second Textual TUI (separate app/screen/process) edits settings:
    - Configure GenAI model selection
    - Create/edit personas (instruction text + ElevenLabs voice_id)
- Secrets in .env:
  - Discord token, Google API key (for python-genai), ElevenLabs API key, and cooldown values go in .env.
  - Use python-dotenv to load .env at startup.
- Failure behavior:
  - No retries. Any fatal exception stops the session and prints the error stack to the main terminal.

Deliverables the code generator must output:

- A complete repository layout with:
  - pyproject.toml (or requirements.txt) including dependencies
  - src/ package with modules separated by responsibility:
    - main.py (orchestrator + TUI launcher)
    - discord_client.py, voice_receive.py, voice_playback.py
    - stt_google.py, audio_preprocess.py (+ optional vad.py)
    - genai_chat.py, trigger_policy.py, conversation_log.py, persona.py
    - tts_elevenlabs.py
    - tui_main.py, tui_settings.py
    - settings_store.py (load/save personas/settings JSON)
  - A README explaining setup steps and where to put .env keys.
- Implement an MVP end-to-end loop:
  - Connect → join voice channel → greet → listen/transcribe → trigger → GenAI reply → ElevenLabs TTS → play audio → resume listening.
- Use type hints, dataclasses for event models, and clear separation between async tasks and callback threads.
- Include clear comments describing where each library’s documented behavior matters (discord VoiceClient.play after callback; STT streaming gRPC only; GenAI usage_metadata; ElevenLabs xi-api-key + stream endpoint; Textual reactive updates).

Important: do not add Discord slash commands or any text channel messaging. The bot only speaks in voice.