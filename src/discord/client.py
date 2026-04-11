"""Discord client connection and gateway management."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Callable, Optional

import discord
from discord.ext.voice_recv import VoiceRecvClient

logger = logging.getLogger(__name__)

ClientFactory = Callable[..., discord.Client]


class DiscordClient:
    """
    Manages connection to Discord gateway and voice channel operations.

    Single entry point to the Discord asyncio event loop.
    All Discord API calls must happen in this context.

    Phase 1: Voice connectivity
    """

    def __init__(
        self,
        token: str,
        client_factory: ClientFactory = discord.Client,
    ) -> None:
        """
        Initialize Discord client.

        Args:
            token: Discord bot token
            client_factory: Optional client factory for testing
        """
        self.token = token
        self._client_factory = client_factory
        self.client: Optional[discord.Client] = None
        self.voice_client: Optional[VoiceRecvClient] = None
        self._ready_event = asyncio.Event()
        self._gateway_task: Optional[asyncio.Task[None]] = None
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

    async def connect(self) -> None:
        """Connect bot to Discord gateway."""
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
        """Get list of guilds the bot is in."""
        client = self._require_ready_client()
        return list(client.guilds)

    async def get_voice_channels(self, guild_id: int) -> list[discord.VoiceChannel]:
        """Get voice channels in a guild."""
        client = self._require_ready_client()
        guild = client.get_guild(guild_id)
        if guild is None:
            raise ValueError(f"Guild {guild_id} was not found in the ready cache.")

        return list(guild.voice_channels)

    async def join_voice_channel(self, channel_id: int) -> VoiceRecvClient:
        """
        Join a voice channel.

        Args:
            channel_id: Discord voice channel ID

        Returns:
            Connected VoiceRecvClient
        """
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
        return voice_client

    async def leave_voice_channel(self) -> None:
        """Leave current voice channel."""
        if self.voice_client is None:
            return

        logger.info("Leaving voice channel...")
        try:
            if self.voice_client.is_connected():
                await self.voice_client.disconnect(force=True)
        finally:
            self.voice_client = None

    async def disconnect(self) -> None:
        """Disconnect from Discord."""
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
