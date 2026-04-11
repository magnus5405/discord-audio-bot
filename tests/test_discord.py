"""Tests for Discord connectivity, receive lifecycle, playback, and smoke flows."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.discord.client as client_module
import src.discord.playback as playback_module
import src.discord.preflight as preflight_module
import src.main as main_module
from src.discord.client import DiscordClient
from src.discord.playback import VoicePlaybackManager
from src.discord.preflight import PreflightError, validate_voice_runtime
from src.discord.voice_sink import DiscordAudioSink


def run_async(awaitable):
    """Run an awaitable in a dedicated event loop for plain pytest."""
    return asyncio.run(awaitable)


class FakeConnectedVoiceClient:
    """Simple fake connected voice client."""

    def __init__(self, channel: object | None = None) -> None:
        self.channel = channel
        self.connected = True
        self.disconnect_calls: list[bool] = []

    def is_connected(self) -> bool:
        return self.connected

    def is_listening(self) -> bool:
        return False

    async def disconnect(self, *, force: bool = False) -> None:
        self.disconnect_calls.append(force)
        self.connected = False


class FakeReceiveVoiceClient(FakeConnectedVoiceClient):
    """Fake voice client with manual receive lifecycle hooks."""

    def __init__(self) -> None:
        super().__init__(channel=SimpleNamespace(id=99))
        self.listen_calls: list[object] = []
        self.stop_listening_calls = 0
        self._after = None
        self._is_listening = False

    def listen(self, sink: object, *, after=None) -> None:
        self.listen_calls.append(sink)
        self._after = after
        self._is_listening = True

    def is_listening(self) -> bool:
        return self._is_listening

    def stop_listening(self) -> None:
        self.stop_listening_calls += 1
        self._is_listening = False

    def finish_listening(self, error: Exception | None = None) -> None:
        if self._after is not None:
            self._after(error)


class FakeVoiceChannel:
    """Fake voice channel with a connect hook."""

    def __init__(self, channel_id: int, name: str = "General") -> None:
        self.id = channel_id
        self.name = name
        self.guild = SimpleNamespace(id=1, name="Guild")
        self.connect_calls: list[dict[str, object]] = []
        self.voice_client = FakeConnectedVoiceClient(channel=self)

    async def connect(self, **kwargs: object) -> FakeConnectedVoiceClient:
        self.connect_calls.append(kwargs)
        return self.voice_client


class FakeTextChannel:
    """Fake non-voice channel."""

    def __init__(self, channel_id: int) -> None:
        self.id = channel_id


class FakeGatewayClient:
    """Minimal fake discord.Client implementation for tests."""

    def __init__(
        self,
        *,
        intents: object,
        guilds: list[object] | None = None,
        channels: dict[int, object] | None = None,
        auto_ready: bool = True,
        start_error: Exception | None = None,
    ) -> None:
        self.intents = intents
        self.guilds = guilds or []
        self._channels = channels or {}
        self._auto_ready = auto_ready
        self._start_error = start_error
        self._closed = False
        self._ready = False
        self._close_event = asyncio.Event()
        self.started_with: str | None = None
        self.user = "fake-bot"

    def event(self, coro):
        setattr(self, coro.__name__, coro)
        return coro

    async def start(self, token: str) -> None:
        self.started_with = token
        if self._start_error is not None:
            raise self._start_error

        if self._auto_ready:
            self._ready = True
            await self.on_ready()

        await self._close_event.wait()

    async def close(self) -> None:
        self._closed = True
        self._close_event.set()

    def is_ready(self) -> bool:
        return self._ready

    def is_closed(self) -> bool:
        return self._closed

    def get_guild(self, guild_id: int) -> object | None:
        for guild in self.guilds:
            if getattr(guild, "id", None) == guild_id:
                return guild
        return None

    def get_channel(self, channel_id: int) -> object | None:
        return self._channels.get(channel_id)


class FakePlaybackVoiceClient:
    """Simple fake playback client."""

    def __init__(self, *, auto_finish: bool = True) -> None:
        self.auto_finish = auto_finish
        self.play_calls: list[object] = []
        self.stop_called = False
        self._after = None
        self._is_playing = False

    def play(self, source: object, *, after) -> None:
        self.play_calls.append(source)
        self._after = after
        self._is_playing = True
        if self.auto_finish:
            asyncio.get_running_loop().call_soon(self.finish)

    def finish(self, error: Exception | None = None) -> None:
        self._is_playing = False
        if self._after is not None:
            self._after(error)

    def is_playing(self) -> bool:
        return self._is_playing

    def stop(self) -> None:
        self.stop_called = True
        self._is_playing = False


class FakeSmokeDiscordClient:
    """Headless fake client used to test src.main orchestration."""

    instances: list["FakeSmokeDiscordClient"] = []

    def __init__(self, token: str) -> None:
        self.token = token
        self.calls: list[object] = []
        self.voice_client = SimpleNamespace(id="voice-client")
        self.start_sinks: list[object] = []
        self.__class__.instances.append(self)

    async def connect(self) -> None:
        self.calls.append("connect")

    async def get_guilds(self) -> list[object]:
        return []

    async def join_voice_channel(self, channel_id: int) -> object:
        self.calls.append(("join_voice_channel", channel_id))
        return self.voice_client

    async def start_listening(self, sink: object) -> None:
        self.calls.append(("start_listening", sink))
        self.start_sinks.append(sink)

    async def stop_listening(self) -> None:
        self.calls.append("stop_listening")

    async def disconnect(self) -> None:
        self.calls.append("disconnect")


class FakeSmokePlaybackManager:
    """Fake playback manager used to test src.main orchestration."""

    instances: list["FakeSmokePlaybackManager"] = []

    def __init__(self, voice_client: object) -> None:
        self.voice_client = voice_client
        self.play_calls: list[Path] = []
        self.__class__.instances.append(self)

    async def play_file(self, audio_path: Path) -> None:
        self.play_calls.append(audio_path)


def make_client_factory(fake_client: FakeGatewayClient):
    """Create a client factory that returns a specific fake client."""

    def factory(*, intents):
        fake_client.intents = intents
        return fake_client

    return factory


def test_connect_waits_for_ready() -> None:
    """DiscordClient.connect waits for on_ready before returning."""

    async def scenario() -> None:
        fake_client = FakeGatewayClient(intents=None)
        discord_client = DiscordClient("token123", client_factory=make_client_factory(fake_client))

        await discord_client.connect()

        assert discord_client.client is fake_client
        assert fake_client.started_with == "token123"
        assert fake_client.intents.guilds is True
        assert fake_client.intents.voice_states is True

        await discord_client.disconnect()

    run_async(scenario())


def test_connect_surfaces_gateway_startup_failure() -> None:
    """DiscordClient.connect surfaces startup failures from the gateway task."""

    async def scenario() -> None:
        fake_client = FakeGatewayClient(intents=None, start_error=RuntimeError("boom"))
        discord_client = DiscordClient("token123", client_factory=make_client_factory(fake_client))

        with pytest.raises(RuntimeError, match="startup failed"):
            await discord_client.connect()

        await discord_client.disconnect()

    run_async(scenario())


def test_channel_discovery_uses_ready_cache() -> None:
    """Guild and voice channel discovery uses the ready cache."""

    async def scenario() -> None:
        voice_channel = FakeVoiceChannel(10, name="Lobby")
        guild = SimpleNamespace(id=1, name="Guild", voice_channels=[voice_channel])
        fake_client = FakeGatewayClient(
            intents=None,
            guilds=[guild],
            channels={voice_channel.id: voice_channel},
        )
        discord_client = DiscordClient("token123", client_factory=make_client_factory(fake_client))

        await discord_client.connect()

        assert await discord_client.get_guilds() == [guild]
        assert await discord_client.get_voice_channels(1) == [voice_channel]

        await discord_client.disconnect()

    run_async(scenario())


def test_join_voice_channel_validates_and_stores_active_client(monkeypatch) -> None:
    """join_voice_channel rejects bad channels and stores the active voice client."""

    async def scenario() -> None:
        monkeypatch.setattr(client_module.discord, "VoiceChannel", FakeVoiceChannel)
        voice_channel = FakeVoiceChannel(10)
        text_channel = FakeTextChannel(20)
        guild = SimpleNamespace(id=1, name="Guild", voice_channels=[voice_channel])
        fake_client = FakeGatewayClient(
            intents=None,
            guilds=[guild],
            channels={voice_channel.id: voice_channel, text_channel.id: text_channel},
        )
        discord_client = DiscordClient("token123", client_factory=make_client_factory(fake_client))

        await discord_client.connect()

        with pytest.raises(ValueError, match="not found"):
            await discord_client.join_voice_channel(999)

        with pytest.raises(ValueError, match="not a voice channel"):
            await discord_client.join_voice_channel(text_channel.id)

        joined_voice_client = await discord_client.join_voice_channel(voice_channel.id)

        assert joined_voice_client is voice_channel.voice_client
        assert discord_client.voice_client is joined_voice_client
        assert voice_channel.connect_calls[0]["cls"] is client_module.VoiceRecvClient
        assert voice_channel.connect_calls[0]["reconnect"] is False

        await discord_client.disconnect()

    run_async(scenario())


def test_start_listening_uses_voice_client_listen() -> None:
    """start_listening delegates to VoiceRecvClient.listen with the provided sink."""

    async def scenario() -> None:
        discord_client = DiscordClient("token123")
        fake_voice_client = FakeReceiveVoiceClient()
        discord_client.voice_client = fake_voice_client
        sink = object()

        await discord_client.start_listening(sink)

        assert fake_voice_client.listen_calls == [sink]
        assert discord_client.is_listening() is True

    run_async(scenario())


def test_stop_listening_waits_for_after_callback() -> None:
    """stop_listening waits until the receive after callback finalizes shutdown."""

    async def scenario() -> None:
        discord_client = DiscordClient("token123")
        fake_voice_client = FakeReceiveVoiceClient()
        discord_client.voice_client = fake_voice_client

        await discord_client.start_listening(object())
        stop_task = asyncio.create_task(discord_client.stop_listening())
        await asyncio.sleep(0)

        assert fake_voice_client.stop_listening_calls == 1
        assert stop_task.done() is False

        fake_voice_client.finish_listening()
        await stop_task

        assert discord_client.is_listening() is False

    run_async(scenario())


def test_stop_listening_surfaces_reader_error() -> None:
    """stop_listening raises when the receive reader reports an error on shutdown."""

    async def scenario() -> None:
        discord_client = DiscordClient("token123")
        fake_voice_client = FakeReceiveVoiceClient()
        discord_client.voice_client = fake_voice_client

        await discord_client.start_listening(object())
        stop_task = asyncio.create_task(discord_client.stop_listening())
        await asyncio.sleep(0)
        fake_voice_client.finish_listening(RuntimeError("reader boom"))

        with pytest.raises(RuntimeError, match="Voice receive stopped with an error"):
            await stop_task

    run_async(scenario())


def test_voice_sink_enqueues_pcm_frames_and_tracks_summary() -> None:
    """DiscordAudioSink queues PCM frames and keeps per-user summary data."""

    async def scenario() -> None:
        audio_queue: asyncio.Queue = asyncio.Queue()
        sink = DiscordAudioSink(
            audio_queue=audio_queue,
            loop=asyncio.get_running_loop(),
            use_opus=False,
        )
        user = SimpleNamespace(id=123, display_name="Alice", name="Alice")

        sink.write(user, SimpleNamespace(pcm=b"hello", opus=b"ignored"))
        await asyncio.sleep(0)
        frame = audio_queue.get_nowait()

        assert frame.user_id == 123
        assert frame.pcm_bytes == b"hello"
        assert sink.total_frames == 1
        assert sink.total_users == 1
        assert sink.summary_lines() == ["Alice (123): speaking starts=0, speaking stops=0, audio chunks=1"]

    run_async(scenario())


def test_voice_sink_skips_missing_user_or_empty_pcm_and_cleanup_is_safe() -> None:
    """DiscordAudioSink ignores unusable packets and supports repeated cleanup."""

    async def scenario() -> None:
        audio_queue: asyncio.Queue = asyncio.Queue()
        sink = DiscordAudioSink(
            audio_queue=audio_queue,
            loop=asyncio.get_running_loop(),
            use_opus=False,
        )
        user = SimpleNamespace(id=123, display_name="Alice", name="Alice")

        sink.write(None, SimpleNamespace(pcm=b"hello", opus=b"hello"))
        sink.write(user, SimpleNamespace(pcm=b"", opus=b"ignored"))
        await asyncio.sleep(0)

        assert audio_queue.empty() is True
        assert sink.total_frames == 0
        sink.cleanup()
        sink.cleanup()

    run_async(scenario())


def test_voice_sink_tracks_speaking_events_in_opus_mode() -> None:
    """DiscordAudioSink should log speaking activity even when using Opus packets."""

    async def scenario() -> None:
        audio_queue: asyncio.Queue = asyncio.Queue()
        sink = DiscordAudioSink(audio_queue=audio_queue, loop=asyncio.get_running_loop())
        user = SimpleNamespace(id=456, display_name="Bob", name="Bob")

        sink.on_voice_member_speaking_start(user)
        sink.write(user, SimpleNamespace(pcm=b"", opus=b"opus-bytes"))
        sink.on_voice_member_speaking_stop(user)
        await asyncio.sleep(0)

        frame = audio_queue.get_nowait()

        assert frame.user_id == 456
        assert frame.pcm_bytes == b"opus-bytes"
        assert sink.total_frames == 1
        assert sink.summary_lines() == ["Bob (456): speaking starts=1, speaking stops=1, audio chunks=1"]

    run_async(scenario())


def test_play_file_creates_ffmpeg_source_and_waits_for_completion(monkeypatch) -> None:
    """play_file builds an FFmpegOpusAudio source and waits for playback completion."""

    async def scenario() -> None:
        created_sources: list[object] = []

        class FakeFFmpegOpusAudio:
            def __init__(self, source: str) -> None:
                self.source = source
                created_sources.append(self)

        monkeypatch.setattr(playback_module.discord, "FFmpegOpusAudio", FakeFFmpegOpusAudio)
        voice_client = FakePlaybackVoiceClient(auto_finish=True)
        playback_manager = VoicePlaybackManager(voice_client)
        audio_path = Path("clip.mp3")

        await playback_manager.play_file(audio_path)

        assert created_sources
        assert created_sources[0].source == str(audio_path)
        assert voice_client.play_calls == created_sources
        assert playback_manager.is_playing() is False

    run_async(scenario())


def test_stop_playback_unblocks_pending_wait() -> None:
    """stop_playback stops the client and unblocks the playback wait."""

    async def scenario() -> None:
        voice_client = FakePlaybackVoiceClient(auto_finish=False)
        playback_manager = VoicePlaybackManager(voice_client)

        playback_task = asyncio.create_task(playback_manager.play_audio(object()))
        await asyncio.sleep(0)
        await playback_manager.stop_playback()
        await playback_task

        assert voice_client.stop_called is True
        assert playback_manager.is_playing() is False

    run_async(scenario())


def test_run_receive_smoke_sequences_listen_play_and_resume(monkeypatch) -> None:
    """The phase-two smoke flow should listen, pause, play, and resume with a fresh sink."""

    async def scenario() -> None:
        FakeSmokeDiscordClient.instances.clear()
        FakeSmokePlaybackManager.instances.clear()
        monkeypatch.setattr(main_module, "load_dotenv", lambda: None)
        monkeypatch.setattr(main_module, "configure_logging", lambda: None)
        monkeypatch.setattr(main_module, "DiscordClient", FakeSmokeDiscordClient)
        monkeypatch.setattr(main_module, "VoicePlaybackManager", FakeSmokePlaybackManager)
        monkeypatch.setattr(main_module, "validate_voice_runtime", lambda path: path)
        monkeypatch.setenv("DISCORD_TOKEN", "token123")

        async def fake_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr(main_module.asyncio, "sleep", fake_sleep)

        await main_module.run(
            [
                "--channel-id",
                "10",
                "--audio-path",
                "clip.mp3",
                "--receive-smoke",
                "--listen-window-seconds",
                "2",
            ]
        )

        smoke_client = FakeSmokeDiscordClient.instances[-1]
        playback_manager = FakeSmokePlaybackManager.instances[-1]
        start_calls = [call for call in smoke_client.calls if isinstance(call, tuple)]

        assert smoke_client.calls[0] == "connect"
        assert smoke_client.calls[1] == ("join_voice_channel", 10)
        assert smoke_client.calls[2] == ("start_listening", smoke_client.start_sinks[0])
        assert smoke_client.calls[3] == "stop_listening"
        assert playback_manager.play_calls == [Path("clip.mp3")]
        assert smoke_client.calls[4] == ("start_listening", smoke_client.start_sinks[1])
        assert smoke_client.calls[5] == "stop_listening"
        assert smoke_client.calls[6] == "disconnect"
        assert len(start_calls) == 3
        assert smoke_client.start_sinks[0] is not smoke_client.start_sinks[1]

    run_async(scenario())


def test_run_phase_one_playback_flow_remains_unchanged(monkeypatch) -> None:
    """The original playback smoke flow should still avoid receive lifecycle calls."""

    async def scenario() -> None:
        FakeSmokeDiscordClient.instances.clear()
        FakeSmokePlaybackManager.instances.clear()
        monkeypatch.setattr(main_module, "load_dotenv", lambda: None)
        monkeypatch.setattr(main_module, "configure_logging", lambda: None)
        monkeypatch.setattr(main_module, "DiscordClient", FakeSmokeDiscordClient)
        monkeypatch.setattr(main_module, "VoicePlaybackManager", FakeSmokePlaybackManager)
        monkeypatch.setattr(main_module, "validate_voice_runtime", lambda path: path)
        monkeypatch.setenv("DISCORD_TOKEN", "token123")

        await main_module.run(["--channel-id", "10", "--audio-path", "clip.mp3"])

        smoke_client = FakeSmokeDiscordClient.instances[-1]
        playback_manager = FakeSmokePlaybackManager.instances[-1]

        assert smoke_client.calls == [
            "connect",
            ("join_voice_channel", 10),
            "disconnect",
        ]
        assert playback_manager.play_calls == [Path("clip.mp3")]

    run_async(scenario())


def test_validate_voice_runtime_checks_audio_file(monkeypatch) -> None:
    """Preflight fails fast when the audio file is missing."""
    monkeypatch.setattr(preflight_module.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(preflight_module, "has_nacl", True)
    monkeypatch.setattr(preflight_module, "has_dave", True)

    with pytest.raises(PreflightError, match="Audio file was not found"):
        validate_voice_runtime(Path("definitely-missing-audio-file.wav"))
