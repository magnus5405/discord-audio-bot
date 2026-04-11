"""Tests for Discord connectivity, playback, and preflight helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.discord.client as client_module
import src.discord.playback as playback_module
import src.discord.preflight as preflight_module
from src.discord.client import DiscordClient
from src.discord.playback import VoicePlaybackManager
from src.discord.preflight import PreflightError, validate_voice_runtime


class FakeConnectedVoiceClient:
    """Simple fake connected voice client."""

    def __init__(self, channel: object | None = None) -> None:
        self.channel = channel
        self.connected = True
        self.disconnect_calls: list[bool] = []

    def is_connected(self) -> bool:
        return self.connected

    async def disconnect(self, *, force: bool = False) -> None:
        self.disconnect_calls.append(force)
        self.connected = False


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


def make_client_factory(fake_client: FakeGatewayClient):
    """Create a client factory that returns a specific fake client."""

    def factory(*, intents):
        fake_client.intents = intents
        return fake_client

    return factory


@pytest.mark.asyncio
async def test_connect_waits_for_ready() -> None:
    """DiscordClient.connect waits for on_ready before returning."""
    fake_client = FakeGatewayClient(intents=None)
    discord_client = DiscordClient("token123", client_factory=make_client_factory(fake_client))

    await discord_client.connect()

    assert discord_client.client is fake_client
    assert fake_client.started_with == "token123"
    assert fake_client.intents.guilds is True
    assert fake_client.intents.voice_states is True

    await discord_client.disconnect()


@pytest.mark.asyncio
async def test_connect_surfaces_gateway_startup_failure() -> None:
    """DiscordClient.connect surfaces startup failures from the gateway task."""
    fake_client = FakeGatewayClient(intents=None, start_error=RuntimeError("boom"))
    discord_client = DiscordClient("token123", client_factory=make_client_factory(fake_client))

    with pytest.raises(RuntimeError, match="startup failed"):
        await discord_client.connect()

    await discord_client.disconnect()


@pytest.mark.asyncio
async def test_channel_discovery_uses_ready_cache() -> None:
    """Guild and voice channel discovery uses the ready cache."""
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


@pytest.mark.asyncio
async def test_join_voice_channel_validates_and_stores_active_client(monkeypatch) -> None:
    """join_voice_channel rejects bad channels and stores the active voice client."""
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


@pytest.mark.asyncio
async def test_play_file_creates_ffmpeg_source_and_waits_for_completion(monkeypatch) -> None:
    """play_file builds an FFmpegOpusAudio source and waits for playback completion."""
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


@pytest.mark.asyncio
async def test_stop_playback_unblocks_pending_wait() -> None:
    """stop_playback stops the client and unblocks the playback wait."""
    voice_client = FakePlaybackVoiceClient(auto_finish=False)
    playback_manager = VoicePlaybackManager(voice_client)

    playback_task = asyncio.create_task(playback_manager.play_audio(object()))
    await asyncio.sleep(0)
    await playback_manager.stop_playback()
    await playback_task

    assert voice_client.stop_called is True
    assert playback_manager.is_playing() is False


def test_validate_voice_runtime_checks_audio_file(monkeypatch, tmp_path: Path) -> None:
    """Preflight fails fast when the audio file is missing."""
    monkeypatch.setattr(preflight_module.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(preflight_module, "has_nacl", True)
    monkeypatch.setattr(preflight_module, "has_dave", True)

    with pytest.raises(PreflightError, match="Audio file was not found"):
        validate_voice_runtime(tmp_path / "missing.wav")
