"""CLI entrypoint for Discord headless smoke tests and the Textual TUI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from argparse import Namespace
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Sequence

from src.conversation import ConversationLog
from src.discord import DiscordAudioSink, DiscordClient, VoicePlaybackManager
from src.discord.preflight import (
    PreflightError,
    validate_voice_dependencies,
    validate_voice_runtime,
)
from src.models import AudioFrame
from src.runtime_dirs import app_bundle_dir, load_application_dotenv
from src.session import ConversationRunnerConfig, run_voice_conversation
from src.storage import DEFAULT_STT_LANGUAGE_CODE, SettingsStore, TranscriptSessionWriter
from src.storage.reply_locale import resolve_bot_reply_language_code
from src.transcription import GoogleSTTClient, PerUserTranscriptionCoordinator
from src.tts import resolve_elevenlabs_api_key

logger = logging.getLogger(__name__)


def voice_user_audio_allowed(discord_client: DiscordClient) -> Callable[[int], bool]:
    """Return a sink predicate: only consented users (and never the bot) send audio to STT."""
    inner = getattr(discord_client, "client", None)
    bot_user = getattr(inner, "user", None) if inner is not None else None
    bot_id = getattr(bot_user, "id", None) if bot_user is not None else None
    store = getattr(discord_client, "consent_store", None)
    if store is None:

        def allow_all(_user_id: int) -> bool:
            return True

        return allow_all

    def allowed(user_id: int) -> bool:
        if bot_id is not None and user_id == bot_id:
            return True
        return store.is_consented(user_id)

    return allowed


def configure_logging() -> None:
    """Configure logging after environment variables are loaded."""
    log_level = logging.DEBUG if os.getenv("DEBUG_MODE", "").lower() == "true" else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("discord.ext.voice_recv.reader").setLevel(logging.WARNING)
    logging.getLogger("discord.ext.voice_recv.gateway").setLevel(logging.WARNING)


def configure_logging_for_tui() -> None:
    """Send logs to a file so Textual can own the terminal (see TUI_LOG_FILE)."""
    log_file = (os.getenv("TUI_LOG_FILE") or "logs/tui.log").strip() or "logs/tui.log"
    path = Path(log_file)
    if getattr(sys, "frozen", False) and not path.is_absolute():
        path = app_bundle_dir() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    root.addHandler(handler)
    level = logging.DEBUG if os.getenv("DEBUG_MODE", "").lower() == "true" else logging.INFO
    root.setLevel(level)
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
        help="Run receive smoke flow: listen, play a clip, listen again with a fresh sink",
    )
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Run per-user speech-to-text transcription in the voice channel",
    )
    parser.add_argument(
        "--converse",
        action="store_true",
        help=(
            "Full conversation: STT, Gemini replies, and ElevenLabs playback "
            "(requires personas and API keys; same listen window as --transcribe)"
        ),
    )
    parser.add_argument(
        "--listen-window-seconds",
        type=float,
        help=(
            "Seconds to listen before and after playback in receive smoke mode, "
            "or the total window for --transcribe / --converse (omit to run until Ctrl+C)"
        ),
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Run the Textual dashboard (guild/channel, persona, voice session)",
    )
    return parser.parse_args(argv)


def get_required_token(settings_store: SettingsStore | None = None) -> str:
    """Load the Discord token from settings first, then environment."""
    token = (
        settings_store.resolve_discord_secret("token", "DISCORD_TOKEN")
        if settings_store is not None
        else os.getenv("DISCORD_TOKEN")
    )
    if not token:
        raise ValueError(
            "DISCORD_TOKEN must be set in TUI settings or the environment/.env file."
        )

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
    """Resolve the listen window for receive smoke mode."""
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


def _parse_positive_float_env(name: str, default: float) -> float:
    env_value = os.getenv(name)
    if env_value is None:
        return default
    try:
        value = float(env_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid float.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def resolve_reply_silence_seconds(settings_store: SettingsStore | None = None) -> float:
    """Seconds of silence before a non-mention reply can trigger."""
    if settings_store is not None:
        return settings_store.resolve_runtime_float(
            "reply_silence_seconds",
            "BOT_REPLY_SILENCE_SECONDS",
            5.0,
        )
    return _parse_positive_float_env("BOT_REPLY_SILENCE_SECONDS", 5.0)


def resolve_reply_cooldown_seconds(settings_store: SettingsStore | None = None) -> float:
    """Minimum seconds between bot replies after the last spoken reply."""
    if settings_store is not None:
        return settings_store.resolve_runtime_float(
            "reply_cooldown_seconds",
            "BOT_REPLY_COOLDOWN_SECONDS",
            180.0,
        )
    return _parse_positive_float_env("BOT_REPLY_COOLDOWN_SECONDS", 180.0)


def resolve_mention_window_seconds(settings_store: SettingsStore | None = None) -> float:
    """Seconds to wait after a nickname mention before forcing a reply."""
    if settings_store is not None:
        return settings_store.resolve_runtime_float(
            "mention_window_seconds",
            "BOT_MENTION_WINDOW_SECONDS",
            30.0,
        )
    return _parse_positive_float_env("BOT_MENTION_WINDOW_SECONDS", 30.0)


def resolve_greet_on_join(settings_store: SettingsStore | None = None) -> bool:
    """Whether to greet on voice join (settings, then BOT_GREET_ON_JOIN, default true)."""
    if settings_store is not None:
        return settings_store.resolve_runtime_bool(
            "greet_on_join",
            "BOT_GREET_ON_JOIN",
            default=True,
        )
    raw = os.getenv("BOT_GREET_ON_JOIN", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


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
    """Run receive smoke flow around a playback clip."""
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
    *,
    settings_store: SettingsStore | None = None,
) -> None:
    """Run transcription until interrupted or the optional time window elapses."""
    settings_store = settings_store or SettingsStore()
    stt_config = settings_store.get_stt_config()
    conversation_log = ConversationLog()
    stt_client = GoogleSTTClient(
        primary_language=stt_config.get("language_code", DEFAULT_STT_LANGUAGE_CODE),
        alternative_languages=stt_config.get("alternative_language_codes", ["en-US"]),
        api_key=settings_store.resolve_stt_api_key(),
        project_id=settings_store.resolve_stt_project_id(),
        location=settings_store.resolve_stt_location(),
        model=settings_store.resolve_stt_model(),
        credentials_path=settings_store.resolve_stt_credentials_path(),
        speech_backend=settings_store.resolve_stt_speech_backend(),
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


async def run_async(args: Namespace) -> None:
    """Run the headless Discord smoke flows (``args`` from :func:`parse_args`)."""
    configure_logging()
    settings_store = SettingsStore()
    token = get_required_token(settings_store)
    discord_client = DiscordClient(token)

    try:
        headless_modes = (args.receive_smoke, args.transcribe, args.converse)
        if sum(1 for m in headless_modes if m) > 1:
            raise ValueError(
                "Use at most one of --receive-smoke, --transcribe, or --converse."
            )

        if args.list_voice_channels:
            await discord_client.connect()
            await print_voice_channels(discord_client)
            return

        channel_id = resolve_channel_id(args.channel_id)
        if args.transcribe or args.converse:
            validate_voice_dependencies()
        if not args.transcribe and not args.converse:
            audio_path = validate_voice_runtime(resolve_audio_path(args.audio_path))

        await discord_client.connect()
        voice_client = await discord_client.join_voice_channel(channel_id)

        if args.converse:
            elevenlabs_key = resolve_elevenlabs_api_key(settings_store)
            if not elevenlabs_key:
                raise ValueError(
                    "Set ELEVENLABS_API_KEY (or elevenlabs_api_key in settings) for --converse."
                )
            gemini_key = settings_store.resolve_api_secret(
                "google_gemini_api_key",
                "GOOGLE_GEMINI_API_KEY",
            )
            if not gemini_key:
                raise ValueError(
                    "Set GOOGLE_GEMINI_API_KEY (or google_gemini_api_key in settings) for --converse."
                )
            listen_window_seconds = resolve_transcription_window_seconds(
                args.listen_window_seconds
            )
            runner_config = ConversationRunnerConfig(
                stt_idle_timeout_seconds=resolve_stt_idle_timeout_seconds(),
                reply_silence_seconds=resolve_reply_silence_seconds(settings_store),
                reply_cooldown_seconds=resolve_reply_cooldown_seconds(settings_store),
                mention_window_seconds=resolve_mention_window_seconds(settings_store),
                greet_on_join=resolve_greet_on_join(settings_store),
                reply_locale=resolve_bot_reply_language_code(settings_store),
            )
            await run_voice_conversation(
                discord_client=discord_client,
                voice_client=voice_client,
                listen_window_seconds=listen_window_seconds,
                elevenlabs_api_key=elevenlabs_key,
                settings_store=settings_store,
                runner_config=runner_config,
            )
            return

        if args.transcribe:
            listen_window_seconds = resolve_transcription_window_seconds(args.listen_window_seconds)
            await run_transcription_mode(
                discord_client=discord_client,
                voice_client=voice_client,
                listen_window_seconds=listen_window_seconds,
                settings_store=settings_store,
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


async def run(argv: Sequence[str] | None = None) -> int:
    """Run CLI logic asynchronously (``main`` wraps this in ``asyncio.run``; tests await it)."""
    load_application_dotenv()
    args = parse_args(argv)

    if args.tui:
        print("--tui must be launched via the synchronous CLI entrypoint.")
        return 1

    try:
        await run_async(args)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    except (PreflightError, RuntimeError, ValueError) as exc:
        logger.error("%s", exc)
        return 1

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Synchronous entrypoint for the smoke runner or ``--tui`` dashboard."""
    load_application_dotenv()
    args = parse_args(argv)

    if args.tui:
        if (
            args.list_voice_channels
            or args.receive_smoke
            or args.transcribe
            or args.converse
        ):
            print(
                "--tui cannot be combined with --list-voice-channels, --receive-smoke, "
                "--transcribe, or --converse."
            )
            return 1
        if args.channel_id is not None or args.audio_path is not None:
            print("--tui does not use --channel-id or --audio-path; pick a channel in the UI.")
            return 1
        if args.listen_window_seconds is not None:
            print("--tui does not use --listen-window-seconds.")
            return 1
        try:
            from src.ui.dashboard.app import run_tui_application

            run_tui_application()
        except KeyboardInterrupt:
            logger.warning("Interrupted by user.")
            return 130
        except (RuntimeError, ValueError) as exc:
            print(f"{exc}")
            return 1
        return 0

    try:
        return asyncio.run(run(argv))
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
