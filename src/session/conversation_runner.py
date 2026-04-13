"""Voice conversation session: STT, GenAI, TTS, Discord playback."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from rich.markup import escape

import discord

from ..conversation import (
    ConversationLog,
    GenAIChatManager,
    PersonaManager,
    ReplyTriggerPolicy,
)
from ..conversation.chat import format_join_greeting_prompt, format_user_join_greeting_prompt
from ..discord import DiscordAudioSink, DiscordClient, VoicePlaybackManager
from ..models import AudioFrame, Persona, TranscriptSegment
from ..runtime_ffmpeg import probe_audio_duration_seconds
from ..storage import DEFAULT_STT_LANGUAGE_CODE, SettingsStore, TranscriptSessionWriter
from ..storage.transcripts import attach_active_transcript_writer, detach_active_transcript_writer
from ..transcription import GoogleSTTClient, PerUserTranscriptionCoordinator
from ..tts import ElevenLabsTTSClient
from .metrics import SessionMetrics

logger = logging.getLogger(__name__)

_DISCORD_NICKNAME_MAX_LEN = 32


def _unlink_temp_file(path: Path) -> None:
    """Delete a temp file; retry briefly on Windows when the file is still locked."""
    for _ in range(20):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.05)
    with suppress(PermissionError):
        path.unlink(missing_ok=True)


def _persona_mention_trigger_sources(persona: Persona) -> list[str]:
    """Display name plus configured transcript aliases (order preserved for policy dedupe)."""
    parts: list[str] = [persona.display_name, *persona.alternative_names]
    return [p for p in parts if str(p).strip()]


async def _try_set_guild_nickname(channel: object | None, display_name: str) -> None:
    """Set the bot's server nickname from settings; non-fatal on permission errors."""
    if channel is None:
        return
    g = getattr(channel, "guild", None)
    if g is None:
        return
    me = g.me
    if me is None:
        return
    nick = (display_name or "").strip()[:_DISCORD_NICKNAME_MAX_LEN]
    if not nick:
        return
    try:
        await me.edit(nick=nick)
        logger.info("Set guild nickname to %r", nick)
    except discord.Forbidden:
        logger.warning(
            "Could not set guild nickname to %r (missing Change Nickname permission).",
            nick,
        )
    except discord.HTTPException as exc:
        logger.warning("Guild nickname update failed: %s", exc)


@dataclass(frozen=True, slots=True)
class ConversationRunnerConfig:
    """Behavior knobs resolved from env / caller (keep runner free of dotenv)."""

    stt_idle_timeout_seconds: float
    reply_silence_seconds: float
    reply_cooldown_seconds: float
    mention_window_seconds: float
    greet_on_join: bool
    reply_locale: str


async def _wait_session_runtime(
    listen_window_seconds: float | None,
    external_stop: asyncio.Event | None,
) -> None:
    """Complete when listen window elapses, external stop is set, or block forever."""
    tasks: list[asyncio.Task[object]] = []
    if listen_window_seconds is not None:
        tasks.append(asyncio.create_task(asyncio.sleep(listen_window_seconds)))
    if external_stop is not None:
        tasks.append(asyncio.create_task(external_stop.wait()))
    if not tasks:
        await asyncio.Event().wait()
        return
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
        with suppress(asyncio.CancelledError):
            await t
    for t in done:
        with suppress(asyncio.CancelledError):
            await t


async def run_voice_conversation(
    discord_client: DiscordClient,
    voice_client: object,
    listen_window_seconds: float | None,
    *,
    elevenlabs_api_key: str,
    settings_store: SettingsStore,
    runner_config: ConversationRunnerConfig,
    persona_id: str | None = None,
    external_stop_event: asyncio.Event | None = None,
    metrics: SessionMetrics | None = None,
    user_audio_allowed: Callable[[int], bool] | None = None,
) -> None:
    """Run STT plus GenAI replies with ElevenLabs TTS and Discord voice playback."""
    if metrics is not None:
        metrics.reset_session_clock()
        metrics.running = True
        metrics.last_error = ""
        metrics.status_line = "starting"

    personas = settings_store.get_personalities()
    if not personas:
        raise ValueError("settings.json must define at least one persona.")

    persona_manager = PersonaManager(personas)
    if persona_id and persona_manager.set_current_persona(str(persona_id)):
        pass
    else:
        ui_prefs = settings_store.get_ui_preferences()
        last_persona_id = ui_prefs.get("last_persona_id")
        if not last_persona_id or not persona_manager.set_current_persona(str(last_persona_id)):
            persona_manager.set_current_persona(personas[0].persona_id)

    persona = persona_manager.get_current_persona()
    if persona is None:
        raise RuntimeError("PersonaManager failed to select a persona.")

    channel = getattr(voice_client, "channel", None)
    guild = getattr(channel, "guild", None)
    if metrics is not None:
        metrics.guild_label = getattr(guild, "name", "") or ""
        metrics.channel_label = getattr(channel, "name", "") or ""

    chat_manager = GenAIChatManager(
        api_key=settings_store.resolve_api_secret(
            "google_gemini_api_key",
            "GOOGLE_GEMINI_API_KEY",
        ),
        reply_locale=runner_config.reply_locale,
    )

    policy = ReplyTriggerPolicy(
        silence_timeout_seconds=runner_config.reply_silence_seconds,
        cooldown_seconds=runner_config.reply_cooldown_seconds,
        mention_window_seconds=runner_config.mention_window_seconds,
    )
    policy.set_mention_triggers(_persona_mention_trigger_sources(persona))

    conversation_log = ConversationLog()
    stt_config = settings_store.get_stt_config()
    stt_primary_language = (
        str(stt_config.get("language_code", DEFAULT_STT_LANGUAGE_CODE)).strip()
        or DEFAULT_STT_LANGUAGE_CODE
    )
    stt_client = GoogleSTTClient(
        primary_language=stt_primary_language,
        alternative_languages=stt_config.get("alternative_language_codes", ["en-US"]),
        api_key=settings_store.resolve_stt_api_key(),
        project_id=settings_store.resolve_stt_project_id(),
        location=settings_store.resolve_stt_location(),
        model=settings_store.resolve_stt_model(),
        credentials_path=settings_store.resolve_stt_credentials_path(),
        speech_backend=settings_store.resolve_stt_speech_backend(),
    )
    await stt_client.validate_connectivity()

    await _try_set_guild_nickname(channel, persona.display_name)

    transcript_writer = TranscriptSessionWriter(
        guild_id=getattr(guild, "id", 0),
        guild_name=getattr(guild, "name", "unknown-guild"),
        channel_id=getattr(channel, "id", 0),
        channel_name=getattr(channel, "name", "unknown-channel"),
    )
    tts_client = ElevenLabsTTSClient(elevenlabs_api_key)
    playback_manager = VoicePlaybackManager(cast(discord.VoiceClient, voice_client))

    def bump_metrics_tokens() -> None:
        inp, out = chat_manager.get_token_usage_breakdown()
        total = inp + out
        transcript_writer.set_genai_token_counts(inp, out)
        if metrics is not None:
            metrics.genai_input_tokens = inp
            metrics.genai_output_tokens = out
            metrics.total_tokens = total

    async def speak_bot_text(text: str, active_persona: Persona) -> None:
        stripped = (text or "").strip()
        if not stripped:
            logger.info("Skipping TTS for empty bot text.")
            return
        if metrics is not None:
            metrics.append_transcript_line(f"[b]Bot[/b]: {escape(stripped)}")
        if metrics is not None:
            metrics.status_line = "synthesizing speech"
        audio_path = await tts_client.synthesize_to_file(stripped, active_persona)
        try:
            if metrics is not None:
                metrics.status_line = "playing audio"
            await playback_manager.play_file(Path(audio_path))
            try:
                duration_seconds = float(probe_audio_duration_seconds(audio_path))
                tts_client.record_tts_duration(duration_seconds)
                transcript_writer.add_tts_seconds(duration_seconds)
            except Exception as exc:
                logger.warning("TTS duration probe failed: %s", exc)
            char_count = len(stripped)
            tts_client.record_tts_characters(char_count)
            transcript_writer.add_tts_characters(char_count)
            if metrics is not None:
                metrics.tts_characters += char_count
                inp, out = chat_manager.get_token_usage_breakdown()
                metrics.genai_input_tokens = inp
                metrics.genai_output_tokens = out
                metrics.total_tokens = inp + out
        finally:
            _unlink_temp_file(Path(audio_path))

    audio_queue: asyncio.Queue[AudioFrame] = asyncio.Queue()

    def handle_final_segment(segment: TranscriptSegment) -> None:
        conversation_log.add_segment(segment)
        transcript_writer.add_segment(segment)
        policy.record_human_speech()
        if policy.text_contains_mention_trigger(segment.text):
            policy.record_mention()
        if metrics is not None:
            metrics.status_line = f"transcript: {segment.username}"
            metrics.append_transcript_line(
                f"[b]{escape(segment.username)}[/b]: {escape(segment.text)}"
            )
        logger.info("Final transcript | %s: %s", segment.username, segment.text)

    def on_stt_audio_seconds(delta: float) -> None:
        if delta <= 0:
            return
        transcript_writer.add_stt_seconds(delta)
        if metrics is not None:
            metrics.add_stt_seconds(delta)

    coordinator = PerUserTranscriptionCoordinator(
        stt_client=stt_client,
        segment_handler=handle_final_segment,
        idle_timeout_seconds=runner_config.stt_idle_timeout_seconds,
        on_stt_audio_seconds=on_stt_audio_seconds,
    )
    consumer_stop_event = asyncio.Event()
    consumer_task = asyncio.create_task(
        coordinator.run(audio_queue=audio_queue, stop_event=consumer_stop_event),
        name="transcription-consumer",
    )

    runtime_task: asyncio.Task[None] | None = None
    supervisor_task: asyncio.Task[None] | None = None
    supervisor_stop = {"go": True}

    try:
        attach_active_transcript_writer(transcript_writer)
        discord_client.set_voice_join_handler(None, None)
        chat_session_ready = False
        if runner_config.greet_on_join and channel is not None:
            if metrics is not None:
                metrics.status_line = "join greeting"
            names: list[str] = []
            for member in getattr(channel, "members", []) or []:
                if getattr(member, "bot", False):
                    continue
                names.append(getattr(member, "display_name", None) or getattr(member, "name", "user"))
            names_str = ", ".join(names) if names else "(none)"
            greeting_prompt = format_join_greeting_prompt(
                names_str,
                reply_locale=runner_config.reply_locale,
            )
            await chat_manager.create_chat_session(persona)
            greeting = await chat_manager.send_message(greeting_prompt)
            conversation_log.add_bot_turn(greeting)
            policy.record_bot_reply()
            transcript_writer.add_bot_reply(greeting, label="greeting")
            bump_metrics_tokens()
            logger.info("Join greeting | %s", greeting)
            await speak_bot_text(greeting, persona)
            chat_session_ready = True

        if not chat_session_ready:
            await chat_manager.create_chat_session(persona)

        sink = DiscordAudioSink(
            audio_queue=audio_queue,
            loop=asyncio.get_running_loop(),
            use_opus=False,
            user_audio_allowed=user_audio_allowed,
        )
        runtime_task = asyncio.create_task(
            _wait_session_runtime(listen_window_seconds, external_stop_event),
            name="conversation-runtime",
        )

        reply_lock = asyncio.Lock()

        async def supervise_loop() -> None:
            while supervisor_stop["go"] and not consumer_stop_event.is_set():
                await asyncio.sleep(0.25)
                if consumer_stop_event.is_set():
                    break
                if metrics is not None:
                    mw, mleft, cleft = policy.snapshot_for_ui()
                    metrics.set_policy_ui_snapshot(mw, mleft, cleft)
                    inp, out = chat_manager.get_token_usage_breakdown()
                    metrics.genai_input_tokens = inp
                    metrics.genai_output_tokens = out
                    metrics.total_tokens = inp + out
                if metrics is not None and discord_client.is_listening():
                    metrics.status_line = "listening"
                async with reply_lock:
                    if not supervisor_stop["go"] or consumer_stop_event.is_set():
                        break
                    pending = conversation_log.has_pending_since_bot()
                    if not policy.should_trigger_reply(has_pending_transcript=pending):
                        continue
                    logger.info("Reply trigger fired; pausing voice receive for GenAI.")
                    if metrics is not None:
                        metrics.status_line = "generating reply"
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
                        bump_metrics_tokens()
                        logger.info("Bot reply | %s", reply)
                        await speak_bot_text(reply, persona)
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
                                user_audio_allowed=user_audio_allowed,
                            )
                            await discord_client.start_listening(resume_sink)

        async def on_voice_user_joined(member: discord.Member) -> None:
            display_name = (
                (getattr(member, "display_name", None) or getattr(member, "name", "") or "").strip()
                or "friend"
            )
            greeting_prompt = format_user_join_greeting_prompt(
                display_name,
                reply_locale=runner_config.reply_locale,
            )
            async with reply_lock:
                if consumer_stop_event.is_set() or not supervisor_stop["go"]:
                    return
                logger.info("User join greeting for %s", display_name)
                if metrics is not None:
                    metrics.status_line = "user join greeting"
                if discord_client.is_listening():
                    await discord_client.stop_listening()
                try:
                    await playback_manager.stop_playback()
                    greeting = await chat_manager.send_message(greeting_prompt)
                    conversation_log.add_bot_turn(greeting)
                    policy.record_bot_reply()
                    transcript_writer.add_bot_reply(greeting, label="greeting_join_user")
                    bump_metrics_tokens()
                    logger.info("User join greeting | %s", greeting)
                    await speak_bot_text(greeting, persona)
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
                            user_audio_allowed=user_audio_allowed,
                        )
                        await discord_client.start_listening(resume_sink)

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

        if metrics is not None:
            metrics.status_line = "listening"

        await discord_client.start_listening(sink)
        if runner_config.greet_on_join and channel is not None:
            discord_client.set_voice_join_handler(int(channel.id), on_voice_user_joined)
        supervisor_task = asyncio.create_task(supervise_loop(), name="genai-supervisor")
        assert runtime_task is not None
        done, _ = await asyncio.wait(
            {consumer_task, runtime_task, supervisor_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for finished in done:
            await finished
    except BaseException as exc:
        if metrics is not None:
            metrics.last_error = str(exc)
            metrics.status_line = "error"
        raise
    finally:
        try:
            discord_client.set_voice_join_handler(None, None)
            supervisor_stop["go"] = False
            if supervisor_task is not None:
                supervisor_task.cancel()
                with suppress(asyncio.CancelledError):
                    await supervisor_task

            if runtime_task is not None:
                runtime_task.cancel()
                with suppress(asyncio.CancelledError):
                    await runtime_task

            if discord_client.is_listening():
                await discord_client.stop_listening()

            consumer_stop_event.set()
            await consumer_task
            logger.info("Conversation mode stopped. Snapshot saved to %s", transcript_writer.path)

            inp, out = chat_manager.get_token_usage_breakdown()
            transcript_writer.set_genai_token_counts(inp, out)
            if metrics is not None:
                metrics.genai_input_tokens = inp
                metrics.genai_output_tokens = out
                metrics.total_tokens = inp + out
                metrics.running = False
                if metrics.status_line != "error":
                    metrics.status_line = "stopped"
        finally:
            detach_active_transcript_writer(transcript_writer)
