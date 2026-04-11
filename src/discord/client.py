"""Discord client connection and gateway management."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Callable, Optional

import discord
from discord.ext.voice_recv import AudioSink, VoiceRecvClient

logger = logging.getLogger(__name__)

ClientFactory = Callable[..., discord.Client]


class DiscordClient:
    """
    Manage Discord gateway, voice connection, and receive lifecycle.

    Phase 1 established connection and playback. Phase 2 adds explicit helpers
    for starting and stopping voice receive sessions.
    """

    def __init__(
        self,
        token: str,
        client_factory: ClientFactory = discord.Client,
    ) -> None:
        """Initialize the Discord gateway wrapper."""
        self.token = token
        self._client_factory = client_factory
        self.client: Optional[discord.Client] = None
        self.voice_client: Optional[VoiceRecvClient] = None
        self._ready_event = asyncio.Event()
        self._gateway_task: Optional[asyncio.Task[None]] = None
        self._receive_done_future: Optional[asyncio.Future[None]] = None
        self._receive_shutdown_error: Optional[Exception] = None
        logger.info("DiscordClient initialized")

    def _create_gateway_client(self) -> discord.Client:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        client = self._client_factory(intents=intents)

        @client.event
        async def on_ready() -> None:
            logger.info("Discord gateway ready as %s", client.user)
            self._ready_event.set()

        return client

    async def _wait_until_ready(self) -> None:
        if self._gateway_task is None:
            raise RuntimeError("Discord gateway is not running.")

        if self.client is not None and self.client.is_ready():
            return

        ready_task = asyncio.create_task(self._ready_event.wait())
        done, _ = await asyncio.wait(
            {ready_task, self._gateway_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if ready_task in done:
            await ready_task
            return

        ready_task.cancel()
        with suppress(asyncio.CancelledError):
            await ready_task

        error = self._gateway_task.exception()
        if error is not None:
            raise RuntimeError("Discord gateway startup failed.") from error

        raise RuntimeError("Discord gateway stopped before becoming ready.")

    def _require_ready_client(self) -> discord.Client:
        if self.client is None or not self.client.is_ready():
            raise RuntimeError("Discord client is not connected.")

        return self.client

    def _require_voice_client(self) -> VoiceRecvClient:
        if self.voice_client is None or not self.voice_client.is_connected():
            raise RuntimeError("Discord voice client is not connected.")

        return self.voice_client

    def _reset_receive_state(self) -> None:
        self._receive_done_future = None
        self._receive_shutdown_error = None

    def _finalize_receive_shutdown(self, error: Exception | None) -> None:
        self._receive_shutdown_error = error
        if self._receive_done_future is not None and not self._receive_done_future.done():
            self._receive_done_future.set_result(None)

    async def connect(self) -> None:
        """Connect the bot to the Discord gateway."""
        logger.info("Connecting to Discord...")

        if self.client is not None and self.client.is_ready():
            logger.debug("Discord client already connected")
            return

        if self._gateway_task is not None and not self._gateway_task.done():
            await self._wait_until_ready()
            return

        self._ready_event = asyncio.Event()
        self.client = self._create_gateway_client()
        self._gateway_task = asyncio.create_task(
            self.client.start(self.token),
            name="discord-gateway",
        )
        await self._wait_until_ready()

    async def get_guilds(self) -> list[discord.Guild]:
        """Return the guilds available from the ready cache."""
        client = self._require_ready_client()
        return list(client.guilds)

    async def get_voice_channels(self, guild_id: int) -> list[discord.VoiceChannel]:
        """Return the voice channels in a cached guild."""
        client = self._require_ready_client()
        guild = client.get_guild(guild_id)
        if guild is None:
            raise ValueError(f"Guild {guild_id} was not found in the ready cache.")

        return list(guild.voice_channels)

    async def join_voice_channel(self, channel_id: int) -> VoiceRecvClient:
        """Join a voice channel and return the connected receive client."""
        client = self._require_ready_client()
        channel = client.get_channel(channel_id)
        if channel is None:
            raise ValueError(f"Voice channel {channel_id} was not found in the ready cache.")

        if not isinstance(channel, discord.VoiceChannel):
            raise ValueError(f"Channel {channel_id} is not a voice channel.")

        if self.voice_client is not None and self.voice_client.is_connected():
            if self.voice_client.channel.id == channel_id:
                logger.info("Already connected to voice channel %s", channel_id)
                return self.voice_client

            await self.leave_voice_channel()

        logger.info("Joining voice channel %s (%s)...", channel.name, channel.id)

        try:
            voice_client = await channel.connect(
                cls=VoiceRecvClient,
                reconnect=False,
                self_deaf=False,
                self_mute=False,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to join voice channel {channel_id}.") from exc

        self.voice_client = voice_client
        self._reset_receive_state()
        return voice_client

    async def start_listening(self, sink: AudioSink) -> None:
        """Start receiving voice packets into the provided sink."""
        voice_client = self._require_voice_client()
        if voice_client.is_listening():
            raise RuntimeError("Discord voice receive is already active.")

        if self._receive_done_future is not None and not self._receive_done_future.done():
            raise RuntimeError("Discord voice receive shutdown is already in progress.")

        loop = asyncio.get_running_loop()
        self._receive_done_future = loop.create_future()
        self._receive_shutdown_error = None

        def after(error: Exception | None) -> None:
            loop.call_soon_threadsafe(self._finalize_receive_shutdown, error)

        try:
            voice_client.listen(sink, after=after)
        except Exception as exc:
            self._reset_receive_state()
            raise RuntimeError("Failed to start voice receive.") from exc

    async def stop_listening(self) -> None:
        """Stop the active receive session and wait for cleanup to finish."""
        voice_client = self._require_voice_client()

        if not voice_client.is_listening():
            if self._receive_done_future is None:
                return
        else:
            if self._receive_done_future is None:
                self._receive_done_future = asyncio.get_running_loop().create_future()
            voice_client.stop_listening()

        await self._receive_done_future
        error = self._receive_shutdown_error
        self._reset_receive_state()

        if error is not None:
            raise RuntimeError("Voice receive stopped with an error.") from error

    def is_listening(self) -> bool:
        """Return whether the active voice client is currently receiving audio."""
        return self.voice_client is not None and self.voice_client.is_listening()

    async def leave_voice_channel(self) -> None:
        """Leave the current voice channel, stopping receive first if needed."""
        if self.voice_client is None:
            return

        logger.info("Leaving voice channel...")
        receive_error: Exception | None = None
        try:
            if self.voice_client.is_connected():
                if self.voice_client.is_listening():
                    try:
                        await self.stop_listening()
                    except Exception as exc:
                        receive_error = exc
                await self.voice_client.disconnect(force=True)
        finally:
            self.voice_client = None
            self._reset_receive_state()

        if receive_error is not None:
            raise receive_error

    async def disconnect(self) -> None:
        """Disconnect from Discord gateway and active voice state."""
        logger.info("Disconnecting from Discord...")

        await self.leave_voice_channel()

        if self.client is not None and not self.client.is_closed():
            await self.client.close()

        if self._gateway_task is not None:
            try:
                await self._gateway_task
            except asyncio.CancelledError:
                logger.debug("Discord gateway task cancelled")
            except Exception as exc:
                logger.debug("Discord gateway task finished with error: %s", exc)

        self.client = None
        self._gateway_task = None
        self._ready_event = asyncio.Event()
