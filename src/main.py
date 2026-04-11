"""Main phase-one and phase-two entrypoint for Discord voice smoke tests."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from src.discord import DiscordAudioSink, DiscordClient, VoicePlaybackManager
from src.discord.preflight import PreflightError, validate_voice_runtime
from src.models import AudioFrame

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure logging after environment variables are loaded."""
    log_level = logging.DEBUG if os.getenv("DEBUG_MODE", "").lower() == "true" else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


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
        "--listen-window-seconds",
        type=float,
        default=10.0,
        help="Seconds to listen before and after playback in receive smoke mode",
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


async def run(argv: Sequence[str] | None = None) -> None:
    """Run the headless Discord smoke flows."""
    load_dotenv()
    configure_logging()
    args = parse_args(argv)
    token = get_required_token()
    discord_client = DiscordClient(token)

    try:
        if args.list_voice_channels:
            await discord_client.connect()
            await print_voice_channels(discord_client)
            return

        channel_id = resolve_channel_id(args.channel_id)
        audio_path = validate_voice_runtime(resolve_audio_path(args.audio_path))

        await discord_client.connect()
        voice_client = await discord_client.join_voice_channel(channel_id)
        playback_manager = VoicePlaybackManager(voice_client)

        if args.receive_smoke:
            listen_window_seconds = resolve_listen_window_seconds(args.listen_window_seconds)
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
