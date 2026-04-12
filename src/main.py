"""Main phase-one and phase-two entrypoint for Discord voice smoke tests."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from src.conversation import (
    ConversationLog,
    GenAIChatManager,
    PersonaManager,
    ReplyTriggerPolicy,
)
from src.discord import DiscordAudioSink, DiscordClient, VoicePlaybackManager
from src.discord.preflight import (
    PreflightError,
    validate_voice_dependencies,
    validate_voice_runtime,
)
from src.models import AudioFrame
from src.storage import SettingsStore, TranscriptSessionWriter
from src.transcription import GoogleSTTClient, PerUserTranscriptionCoordinator

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure logging after environment variables are loaded."""
    log_level = logging.DEBUG if os.getenv("DEBUG_MODE", "").lower() == "true" else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("discord.ext.voice_recv.reader").setLevel(logging.WARNING)
    logging.getLogger("discord.ext.voice_recv.gateway").setLevel(logging.WARNING)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the smoke runners."""
    parser = argparse.ArgumentParser(description="Discord audio bot smoke runner")
    parser.add_argument(
        "--list-voice-channels",
        action="store_true",
        help="List reachable guild and voice channel IDs from the ready cache",
    )
    parser.add_argument(
        "--channel-id",
        type=int,
        help="Voice channel ID to join for playback",
    )
    parser.add_argument(
        "--audio-path",
        type=Path,
        help="Local MP3/WAV file to play into the selected voice channel",
    )
    parser.add_argument(
        "--receive-smoke",
        action="store_true",
        help="Run the phase-two receive smoke flow around playback",
    )
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Run phase-three per-user speech-to-text transcription",
    )
    parser.add_argument(
        "--converse",
        action="store_true",
        help=(
            "Run phase-four transcription plus GenAI replies (logged text only; "
            "ElevenLabs voice playback is phase five)"
        ),
    )
    parser.add_argument(
        "--listen-window-seconds",
        type=float,
        help=(
            "Seconds to listen before and after playback in receive smoke mode, "
            "or the total transcription window when used with --transcribe"
        ),
    )
    return parser.parse_args(argv)


def get_required_token() -> str:
    """Load the Discord token from the environment."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN must be set in the environment or .env file.")

    return token


def resolve_channel_id(cli_value: int | None) -> int:
    """Resolve the voice channel ID from CLI args or environment."""
    if cli_value is not None:
        return cli_value

    env_value = os.getenv("DISCORD_VOICE_CHANNEL_ID")
    if env_value is None:
        raise ValueError(
            "Provide --channel-id or set DISCORD_VOICE_CHANNEL_ID for playback mode."
        )

    try:
        return int(env_value)
    except ValueError as exc:
        raise ValueError("DISCORD_VOICE_CHANNEL_ID must be a valid integer.") from exc


def resolve_audio_path(cli_value: Path | None) -> Path:
    """Resolve the audio path from CLI args or environment."""
    if cli_value is not None:
        return cli_value

    env_value = os.getenv("BOT_TEST_AUDIO_PATH")
    if env_value is None:
        raise ValueError("Provide --audio-path or set BOT_TEST_AUDIO_PATH for playback mode.")

    return Path(env_value)


def resolve_listen_window_seconds(cli_value: float) -> float:
    """Validate the receive smoke listen window length."""
    if cli_value <= 0:
        raise ValueError("--listen-window-seconds must be greater than zero.")

    return cli_value


def resolve_receive_smoke_window_seconds(cli_value: float | None) -> float:
    """Resolve the listen window for phase-two receive smoke mode."""
    return 10.0 if cli_value is None else resolve_listen_window_seconds(cli_value)


def resolve_transcription_window_seconds(cli_value: float | None) -> float | None:
    """Resolve the optional bounded listen window for transcription mode."""
    if cli_value is None:
        return None

    return resolve_listen_window_seconds(cli_value)


def resolve_stt_idle_timeout_seconds() -> float:
    """Resolve the idle gap threshold that ends one STT utterance."""
    env_value = os.getenv("STT_IDLE_TIMEOUT_SECONDS")
    if env_value is None:
        return 1.2

    try:
        timeout_seconds = float(env_value)
    except ValueError as exc:
        raise ValueError("STT_IDLE_TIMEOUT_SECONDS must be a valid float.") from exc

    if timeout_seconds <= 0:
        raise ValueError("STT_IDLE_TIMEOUT_SECONDS must be greater than zero.")

    return timeout_seconds


def resolve_reply_silence_seconds() -> float:
    """Seconds of channel silence before a default-path reply (from .env)."""
    env_value = os.getenv("BOT_REPLY_SILENCE_SECONDS")
    if env_value is None:
        return 5.0
    return float(env_value)


def resolve_reply_cooldown_seconds() -> float:
    """Minimum seconds between default-path replies (from .env)."""
    env_value = os.getenv("BOT_REPLY_COOLDOWN_SECONDS")
    if env_value is None:
        return 180.0
    return float(env_value)


def resolve_mention_window_seconds() -> float:
    """Seconds to wait after nickname mention before forcing a reply."""
    env_value = os.getenv("BOT_MENTION_WINDOW_SECONDS")
    if env_value is None:
        return 30.0
    return float(env_value)


def resolve_bot_reply_language_code(settings_store: SettingsStore) -> str:
    """BCP-47 locale for GenAI replies: env override, else ``stt.language_code`` in settings."""
    env_override = os.getenv("BOT_REPLY_LANGUAGE", "").strip() or os.getenv("BOT_LANGUAGE", "").strip()
    if env_override:
        return env_override
    stt = settings_store.get_stt_config()
    code = str(stt.get("language_code", "da-DK")).strip()
    return code or "da-DK"


def resolve_greet_on_join() -> bool:
    raw = os.getenv("BOT_GREET_ON_JOIN", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


async def print_voice_channels(discord_client: DiscordClient) -> None:
    """Print reachable guilds and voice channels for manual selection."""
    guilds = await discord_client.get_guilds()
    if not guilds:
        print("No guilds available.")
        return

    for guild in guilds:
        print(f"{guild.name} ({guild.id})")
        voice_channels = await discord_client.get_voice_channels(guild.id)
        if not voice_channels:
            print("  [no voice channels]")
            continue

        for channel in voice_channels:
            print(f"  {channel.name} ({channel.id})")


def log_receive_summary(
    label: str,
    sink: DiscordAudioSink,
    audio_queue: asyncio.Queue[AudioFrame],
) -> None:
    """Log a compact summary for one receive window."""
    logger.info(
        "%s receive summary: %s audio chunks across %s users (queue depth=%s)",
        label,
        sink.total_frames,
        sink.total_users,
        audio_queue.qsize(),
    )
    for line in sink.summary_lines():
        logger.info("%s summary: %s", label, line)


async def run_receive_window(
    discord_client: DiscordClient,
    audio_queue: asyncio.Queue[AudioFrame],
    listen_window_seconds: float,
    label: str,
) -> None:
    """Run a single listen window with a fresh sink instance."""
    sink = DiscordAudioSink(
        audio_queue=audio_queue,
        loop=asyncio.get_running_loop(),
        use_opus=True,
    )
    logger.info("Starting %s receive window for %.1f seconds.", label, listen_window_seconds)
    await discord_client.start_listening(sink)

    try:
        await asyncio.sleep(listen_window_seconds)
    finally:
        await discord_client.stop_listening()

    log_receive_summary(label, sink, audio_queue)


async def run_receive_smoke(
    discord_client: DiscordClient,
    playback_manager: VoicePlaybackManager,
    audio_path: Path,
    listen_window_seconds: float,
) -> None:
    """Run the phase-two receive smoke flow around a playback clip."""
    logger.info(
        "Running receive smoke flow with %.1f second windows before and after playback.",
        listen_window_seconds,
    )
    audio_queue: asyncio.Queue[AudioFrame] = asyncio.Queue()

    await run_receive_window(
        discord_client=discord_client,
        audio_queue=audio_queue,
        listen_window_seconds=listen_window_seconds,
        label="Window A",
    )

    logger.info("Playing validation clip between receive windows.")
    await playback_manager.play_file(audio_path)

    await run_receive_window(
        discord_client=discord_client,
        audio_queue=audio_queue,
        listen_window_seconds=listen_window_seconds,
        label="Window B",
    )
    logger.info("Receive smoke flow completed successfully.")


async def run_transcription_mode(
    discord_client: DiscordClient,
    voice_client: object,
    listen_window_seconds: float | None,
) -> None:
    """Run the phase-three transcription flow until interrupted or timed out."""
    settings_store = SettingsStore()
    stt_config = settings_store.get_stt_config()
    conversation_log = ConversationLog()
    stt_client = GoogleSTTClient(
        primary_language=stt_config.get("language_code", "da-DK"),
        alternative_languages=stt_config.get("alternative_language_codes", ["en-US"]),
    )
    await stt_client.validate_connectivity()

    channel = getattr(voice_client, "channel", None)
    guild = getattr(channel, "guild", None)
    transcript_writer = TranscriptSessionWriter(
        guild_id=getattr(guild, "id", 0),
        guild_name=getattr(guild, "name", "unknown-guild"),
        channel_id=getattr(channel, "id", 0),
        channel_name=getattr(channel, "name", "unknown-channel"),
    )
    audio_queue: asyncio.Queue[AudioFrame] = asyncio.Queue()

    def handle_final_segment(segment) -> None:
        conversation_log.add_segment(segment)
        transcript_writer.add_segment(segment)
        logger.info("Final transcript | %s: %s", segment.username, segment.text)

    coordinator = PerUserTranscriptionCoordinator(
        stt_client=stt_client,
        segment_handler=handle_final_segment,
        idle_timeout_seconds=resolve_stt_idle_timeout_seconds(),
    )
    consumer_stop_event = asyncio.Event()
    consumer_task = asyncio.create_task(
        coordinator.run(audio_queue=audio_queue, stop_event=consumer_stop_event),
        name="transcription-consumer",
    )
    sink = DiscordAudioSink(
        audio_queue=audio_queue,
        loop=asyncio.get_running_loop(),
        use_opus=False,
    )
    runtime_task = asyncio.create_task(
        asyncio.sleep(listen_window_seconds)
        if listen_window_seconds is not None
        else asyncio.Event().wait(),
        name="transcription-runtime",
    )

    logger.info(
        "Starting transcription in channel %s (%s)%s",
        getattr(channel, "name", "unknown-channel"),
        getattr(channel, "id", "unknown"),
        (
            f" for {listen_window_seconds:.1f} seconds"
            if listen_window_seconds is not None
            else " until interrupted"
        ),
    )

    try:
        await discord_client.start_listening(sink)
        done, _ = await asyncio.wait(
            {consumer_task, runtime_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if consumer_task in done:
            await consumer_task
        else:
            await runtime_task
    finally:
        runtime_task.cancel()
        with suppress(asyncio.CancelledError):
            await runtime_task

        if discord_client.is_listening():
            await discord_client.stop_listening()

        consumer_stop_event.set()
        await consumer_task
        logger.info("Transcription stopped. Snapshot saved to %s", transcript_writer.path)


async def run_conversation_mode(
    discord_client: DiscordClient,
    voice_client: object,
    listen_window_seconds: float | None,
) -> None:
    """Run phase-four STT plus GenAI reply loop (text replies logged; TTS is phase five)."""
    settings_store = SettingsStore()
    personas = settings_store.get_personalities()
    if not personas:
        raise ValueError("settings.json must define at least one persona for --converse.")

    persona_manager = PersonaManager(personas)
    ui_prefs = settings_store.get_ui_preferences()
    last_persona_id = ui_prefs.get("last_persona_id")
    if not last_persona_id or not persona_manager.set_current_persona(str(last_persona_id)):
        persona_manager.set_current_persona(personas[0].persona_id)

    persona = persona_manager.get_current_persona()
    if persona is None:
        raise RuntimeError("PersonaManager failed to select a persona.")

    reply_locale = resolve_bot_reply_language_code(settings_store)
    logger.info("GenAI reply locale: %s (set BOT_REPLY_LANGUAGE or BOT_LANGUAGE to override)", reply_locale)

    chat_manager = GenAIChatManager(reply_locale=reply_locale)
    await chat_manager.create_chat_session(persona)

    policy = ReplyTriggerPolicy(
        silence_timeout_seconds=resolve_reply_silence_seconds(),
        cooldown_seconds=resolve_reply_cooldown_seconds(),
        mention_window_seconds=resolve_mention_window_seconds(),
    )

    channel = getattr(voice_client, "channel", None)
    guild = getattr(channel, "guild", None)
    me = getattr(guild, "me", None)
    if me is not None:
        policy.set_bot_nickname(me.display_name or me.name)
    elif discord_client.client and discord_client.client.user:
        u = discord_client.client.user
        policy.set_bot_nickname(u.display_name or u.name)

    conversation_log = ConversationLog()
    stt_config = settings_store.get_stt_config()
    stt_client = GoogleSTTClient(
        primary_language=stt_config.get("language_code", "da-DK"),
        alternative_languages=stt_config.get("alternative_language_codes", ["en-US"]),
    )
    await stt_client.validate_connectivity()

    transcript_writer = TranscriptSessionWriter(
        guild_id=getattr(guild, "id", 0),
        guild_name=getattr(guild, "name", "unknown-guild"),
        channel_id=getattr(channel, "id", 0),
        channel_name=getattr(channel, "name", "unknown-channel"),
    )
    audio_queue: asyncio.Queue[AudioFrame] = asyncio.Queue()

    def handle_final_segment(segment) -> None:
        conversation_log.add_segment(segment)
        transcript_writer.add_segment(segment)
        policy.record_human_speech()
        nick = policy.bot_nickname
        if nick and nick in segment.text.lower():
            policy.record_mention()
        logger.info("Final transcript | %s: %s", segment.username, segment.text)

    coordinator = PerUserTranscriptionCoordinator(
        stt_client=stt_client,
        segment_handler=handle_final_segment,
        idle_timeout_seconds=resolve_stt_idle_timeout_seconds(),
    )
    consumer_stop_event = asyncio.Event()
    consumer_task = asyncio.create_task(
        coordinator.run(audio_queue=audio_queue, stop_event=consumer_stop_event),
        name="transcription-consumer",
    )

    if resolve_greet_on_join() and channel is not None:
        names: list[str] = []
        for member in getattr(channel, "members", []) or []:
            if getattr(member, "bot", False):
                continue
            names.append(getattr(member, "display_name", None) or getattr(member, "name", "user"))
        names_str = ", ".join(names) if names else "(none)"
        greeting_prompt = (
            "You just joined this Discord voice channel. "
            f"Users currently present: {names_str}. "
            "Give a brief, friendly spoken-style hello in 1-2 sentences."
        )
        greeting = await chat_manager.send_message(greeting_prompt)
        conversation_log.add_bot_turn(greeting)
        policy.record_bot_reply()
        transcript_writer.add_bot_reply(greeting, label="greeting")
        transcript_writer.set_total_tokens(chat_manager.get_token_usage())
        logger.info("Join greeting | %s", greeting)

    sink = DiscordAudioSink(
        audio_queue=audio_queue,
        loop=asyncio.get_running_loop(),
        use_opus=False,
    )
    runtime_task = asyncio.create_task(
        asyncio.sleep(listen_window_seconds)
        if listen_window_seconds is not None
        else asyncio.Event().wait(),
        name="conversation-runtime",
    )

    supervisor_stop = {"go": True}
    reply_lock = asyncio.Lock()

    async def supervise_loop() -> None:
        while supervisor_stop["go"] and not consumer_stop_event.is_set():
            await asyncio.sleep(0.25)
            if consumer_stop_event.is_set():
                break
            async with reply_lock:
                if not supervisor_stop["go"] or consumer_stop_event.is_set():
                    break
                pending = conversation_log.has_pending_since_bot()
                if not policy.should_trigger_reply(has_pending_transcript=pending):
                    continue
                logger.info("Reply trigger fired; pausing voice receive for GenAI.")
                if discord_client.is_listening():
                    await discord_client.stop_listening()
                try:
                    prompt = chat_manager.format_conversation_prompt(
                        conversation_log.get_conversation_for_prompt()
                    )
                    reply = await chat_manager.send_message(prompt)
                    conversation_log.add_bot_turn(reply)
                    policy.record_bot_reply()
                    transcript_writer.add_bot_reply(reply, label="reply")
                    transcript_writer.set_total_tokens(chat_manager.get_token_usage())
                    logger.info("Bot reply | %s", reply)
                finally:
                    if (
                        supervisor_stop["go"]
                        and not consumer_stop_event.is_set()
                        and getattr(voice_client, "is_connected", lambda: False)()
                        and not discord_client.is_listening()
                    ):
                        resume_sink = DiscordAudioSink(
                            audio_queue=audio_queue,
                            loop=asyncio.get_running_loop(),
                            use_opus=False,
                        )
                        await discord_client.start_listening(resume_sink)

    supervisor_task: asyncio.Task[None] | None = None

    logger.info(
        "Starting conversation mode in channel %s (%s)%s",
        getattr(channel, "name", "unknown-channel"),
        getattr(channel, "id", "unknown"),
        (
            f" for {listen_window_seconds:.1f} seconds"
            if listen_window_seconds is not None
            else " until interrupted"
        ),
    )

    try:
        await discord_client.start_listening(sink)
        supervisor_task = asyncio.create_task(supervise_loop(), name="genai-supervisor")
        done, _ = await asyncio.wait(
            {consumer_task, runtime_task, supervisor_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for finished in done:
            await finished
    finally:
        supervisor_stop["go"] = False
        if supervisor_task is not None:
            supervisor_task.cancel()
            with suppress(asyncio.CancelledError):
                await supervisor_task

        runtime_task.cancel()
        with suppress(asyncio.CancelledError):
            await runtime_task

        if discord_client.is_listening():
            await discord_client.stop_listening()

        consumer_stop_event.set()
        await consumer_task
        logger.info("Conversation mode stopped. Snapshot saved to %s", transcript_writer.path)


async def run(argv: Sequence[str] | None = None) -> None:
    """Run the headless Discord smoke flows."""
    load_dotenv()
    configure_logging()
    args = parse_args(argv)
    token = get_required_token()
    discord_client = DiscordClient(token)

    try:
        if args.receive_smoke and args.transcribe:
            raise ValueError("--receive-smoke and --transcribe cannot be used together.")
        if args.receive_smoke and args.converse:
            raise ValueError("--receive-smoke and --converse cannot be used together.")
        if args.transcribe and args.converse:
            raise ValueError("--transcribe and --converse cannot be used together.")

        if args.list_voice_channels:
            await discord_client.connect()
            await print_voice_channels(discord_client)
            return

        channel_id = resolve_channel_id(args.channel_id)
        if args.transcribe or args.converse:
            validate_voice_dependencies()
        else:
            audio_path = validate_voice_runtime(resolve_audio_path(args.audio_path))

        await discord_client.connect()
        voice_client = await discord_client.join_voice_channel(channel_id)

        if args.transcribe:
            listen_window_seconds = resolve_transcription_window_seconds(args.listen_window_seconds)
            await run_transcription_mode(
                discord_client=discord_client,
                voice_client=voice_client,
                listen_window_seconds=listen_window_seconds,
            )
            return

        if args.converse:
            listen_window_seconds = resolve_transcription_window_seconds(args.listen_window_seconds)
            await run_conversation_mode(
                discord_client=discord_client,
                voice_client=voice_client,
                listen_window_seconds=listen_window_seconds,
            )
            return

        playback_manager = VoicePlaybackManager(voice_client)

        if args.receive_smoke:
            listen_window_seconds = resolve_receive_smoke_window_seconds(args.listen_window_seconds)
            await run_receive_smoke(
                discord_client=discord_client,
                playback_manager=playback_manager,
                audio_path=audio_path,
                listen_window_seconds=listen_window_seconds,
            )
            return

        await playback_manager.play_file(audio_path)
        logger.info("Playback completed successfully.")
    finally:
        await discord_client.disconnect()


def main(argv: Sequence[str] | None = None) -> int:
    """Synchronous entrypoint for the smoke runner."""
    try:
        asyncio.run(run(argv))
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    except (PreflightError, RuntimeError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
