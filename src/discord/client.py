"""Discord client connection and gateway management."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from contextlib import suppress
from typing import Awaitable, Callable, Optional, cast

from discord.errors import DiscordServerError
from discord.ext.voice_recv import AudioSink, VoiceRecvClient

import discord
from discord import app_commands

from ..storage.consent import ConsentStore
from .consent_commands import register_consent_commands
from .voice_recv_patch import apply_discord_ext_voice_recv_patches

logger = logging.getLogger(__name__)

ClientFactory = Callable[..., discord.Client]

_GATEWAY_RETRY_ATTEMPTS = 5
_GATEWAY_RETRY_BASE_SECONDS = 2.0


def _transient_gateway_failure(exc: BaseException | None) -> bool:
    """True when Discord login / gateway may succeed after a short wait (5xx, network blips)."""
    if exc is None:
        return False
    if isinstance(exc, DiscordServerError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    try:
        import aiohttp

        return isinstance(
            exc,
            (
                aiohttp.ClientConnectorError,
                aiohttp.ClientOSError,
                aiohttp.ServerDisconnectedError,
            ),
        )
    except ImportError:
        return False


def _app_command_sync_guild_id_from_env() -> int | None:
    """Optional guild id from env for fast `tree.sync` (DISCORD_SERVER_ID or DISCORD_GUILD_ID)."""
    for key in ("DISCORD_SERVER_ID", "DISCORD_GUILD_ID"):
        raw = os.getenv(key, "").strip()
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            logger.warning("Invalid integer for %s; skipping guild command sync.", key)
    return None


class DiscordClient:
    """
    Manage Discord gateway, voice connection, and receive lifecycle.

    Handles gateway connection, voice join, playback hooks, and explicit
    start/stop for voice receive sessions.
    """

    def __init__(
        self,
        token: str,
        client_factory: ClientFactory = discord.Client,
        consent_store: ConsentStore | None = None,
        app_command_sync_guild_id: int | None = None,
    ) -> None:
        """Initialize the Discord gateway wrapper."""
        self.token = token
        self._client_factory = client_factory
        self.consent_store = consent_store or ConsentStore()
        self._app_command_sync_guild_id = app_command_sync_guild_id
        self.client: Optional[discord.Client] = None
        self.voice_client: Optional[VoiceRecvClient] = None
        self._ready_event = asyncio.Event()
        self._gateway_task: Optional[asyncio.Task[None]] = None
        self._receive_done_future: Optional[asyncio.Future[None]] = None
        self._receive_shutdown_error: Optional[Exception] = None
        self._voice_join_channel_id: Optional[int] = None
        self._voice_member_joined_handler: Optional[Callable[[discord.Member], Awaitable[None]]] = None
        self._command_tree: Optional[app_commands.CommandTree] = None
        self._synced_app_commands_for_client: Optional[int] = None
        self._activity_log_sink: Callable[[str], None] | None = None
        self.last_app_command_sync_summary: str = ""
        apply_discord_ext_voice_recv_patches()
        logger.info("DiscordClient initialized")

    def set_activity_log_sink(self, sink: Callable[[str], None] | None) -> None:
        """Optional callback for slash-command / consent events (e.g. Textual activity log)."""
        self._activity_log_sink = sink

    def _emit_activity(self, message: str) -> None:
        line = (message or "").strip()
        if not line:
            return
        logger.info("[activity] %s", line)
        sink = self._activity_log_sink
        if sink is not None:
            try:
                sink(line)
            except Exception:
                logger.exception("activity log sink failed")

    def _pick_command_sync_guild(self, gateway: discord.Client) -> int | None:
        """Prefer explicit id, then env, then the sole guild if the bot only belongs to one server."""
        if self._app_command_sync_guild_id is not None:
            return self._app_command_sync_guild_id
        env_gid = _app_command_sync_guild_id_from_env()
        if env_gid is not None:
            return env_gid
        guilds = list(getattr(gateway, "guilds", []) or [])
        if len(guilds) == 1:
            return cast(int, guilds[0].id)
        return None

    def _create_gateway_client(self) -> discord.Client:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        client = self._client_factory(intents=intents)
        # Test doubles may omit ``http``; :class:`app_commands.CommandTree` requires a real client.
        if getattr(client, "http", None) is not None:
            tree = app_commands.CommandTree(client)
            register_consent_commands(
                tree,
                self.consent_store,
                activity_sink=self._emit_activity,
            )
            self._command_tree = tree
        else:
            self._command_tree = None

        @client.event
        async def on_ready() -> None:
            logger.info("Discord gateway ready as %s", client.user)
            self._ready_event.set()
            if self._command_tree is not None and self._synced_app_commands_for_client != id(client):
                self.last_app_command_sync_summary = ""
                guild_for_sync = self._pick_command_sync_guild(client)
                try:
                    if guild_for_sync is not None:
                        if client.get_guild(guild_for_sync) is None:
                            logger.warning(
                                "Slash sync guild id %s is not in this bot's guild cache yet (or bot left that server). "
                                "If commands are missing, check DISCORD_SERVER_ID / settings server_id matches the server "
                                "where the bot is installed.",
                                guild_for_sync,
                            )
                        # add_command() without guild= registers globals only; sync(guild=) uploads _guild_commands
                        # only. copy_global_to fills that mapping so the bulk upsert is not empty (discord.py pattern).
                        self._command_tree.copy_global_to(guild=discord.Object(id=guild_for_sync))
                        synced = await self._command_tree.sync(guild=discord.Object(id=guild_for_sync))
                        self._synced_app_commands_for_client = id(client)
                        names = [getattr(cmd, "name", "?") for cmd in (synced or [])]
                        logger.info(
                            "Synced %d application command(s) to guild %s: %s",
                            len(synced or []),
                            guild_for_sync,
                            names,
                        )
                        if not synced:
                            logger.warning(
                                "Guild command sync returned no commands for guild %s — check registration and permissions.",
                                guild_for_sync,
                            )
                        self.last_app_command_sync_summary = (
                            f"Slash commands registered for guild {guild_for_sync} ({len(synced or [])} top-level). "
                            "In Discord open the / menu and choose this bot's commands "
                            "(re-invite with applications.commands if they are missing). "
                            "Plain chat text like /consent does not run commands."
                        )
                    else:
                        synced = await self._command_tree.sync()
                        self._synced_app_commands_for_client = id(client)
                        names = [getattr(cmd, "name", "?") for cmd in (synced or [])]
                        logger.info(
                            "Synced %d application command(s) globally: %s",
                            len(synced or []),
                            names,
                        )
                        self.last_app_command_sync_summary = (
                            "Slash commands registered globally — they can take up to ~1 hour to appear. "
                            "Set server_id in Settings or DISCORD_SERVER_ID in .env (or use a bot in only one server) "
                            "for instant registration. Use Discord's / menu, not normal chat text."
                        )
                except Exception as exc:
                    self._synced_app_commands_for_client = None
                    logger.exception("Application command sync failed")
                    self.last_app_command_sync_summary = (
                        f"Slash command sync failed: {exc}. See logs. "
                        "Ensure the bot token is valid, the bot is in that server, and the invite includes "
                        "applications.commands."
                    )

        @client.event
        async def on_voice_state_update(
            member: discord.Member,
            before: discord.VoiceState,
            after: discord.VoiceState,
        ) -> None:
            await self._dispatch_voice_member_joined(member, before, after)

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

    async def _cleanup_failed_gateway_startup(self) -> None:
        """Tear down a failed ``client.start()`` so a retry can run cleanly."""
        self._ready_event = asyncio.Event()
        if self._gateway_task is not None:
            if not self._gateway_task.done():
                self._gateway_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._gateway_task
            else:
                with suppress(Exception):
                    await self._gateway_task
            self._gateway_task = None
        if self.client is not None:
            with suppress(Exception):
                if not self.client.is_closed():
                    await self.client.close()
            self.client = None

    async def _start_gateway_once(self) -> None:
        self._ready_event = asyncio.Event()
        self.client = self._create_gateway_client()
        self._gateway_task = asyncio.create_task(
            self.client.start(self.token),
            name="discord-gateway",
        )
        await self._wait_until_ready()

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

    def set_voice_join_handler(
        self,
        channel_id: int | None,
        handler: Callable[[discord.Member], Awaitable[None]] | None,
    ) -> None:
        """Notify when a non-bot member enters ``channel_id`` (or clear with ``None``)."""
        self._voice_join_channel_id = channel_id
        self._voice_member_joined_handler = handler

    async def _dispatch_voice_member_joined(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        cid = self._voice_join_channel_id
        handler = self._voice_member_joined_handler
        if cid is None or handler is None:
            return
        after_ch = after.channel
        before_ch = before.channel
        if after_ch is None or after_ch.id != cid:
            return
        if before_ch is not None and before_ch.id == cid:
            return
        client_user = self.client.user if self.client is not None else None
        bot_id = getattr(client_user, "id", None)
        if bot_id is not None and member.id == bot_id:
            return
        if getattr(member, "bot", False):
            return

        async def _run() -> None:
            try:
                await handler(member)
            except Exception:
                logger.exception("Voice join handler failed for member %s", member.id)

        asyncio.create_task(_run())

    def _finalize_receive_shutdown(self, error: Exception | None) -> None:
        self._receive_shutdown_error = error
        if self._receive_done_future is not None and not self._receive_done_future.done():
            self._receive_done_future.set_result(None)

    async def connect(self) -> None:
        """Connect the bot to the Discord gateway (retries transient 5xx / network errors)."""
        logger.info("Connecting to Discord...")

        if self.client is not None and self.client.is_ready():
            logger.debug("Discord client already connected")
            return

        if self._gateway_task is not None and not self._gateway_task.done():
            await self._wait_until_ready()
            return

        last_error: BaseException | None = None
        for attempt in range(1, _GATEWAY_RETRY_ATTEMPTS + 1):
            try:
                await self._start_gateway_once()
                return
            except RuntimeError as exc:
                last_error = exc
                cause = exc.__cause__
                if attempt >= _GATEWAY_RETRY_ATTEMPTS or not _transient_gateway_failure(cause):
                    raise
                delay = min(
                    30.0,
                    _GATEWAY_RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0.0, 1.5),
                )
                logger.warning(
                    "Discord gateway failed (attempt %s/%s): %s — retrying in %.1fs",
                    attempt,
                    _GATEWAY_RETRY_ATTEMPTS,
                    cause or exc,
                    delay,
                )
                await self._cleanup_failed_gateway_startup()
                await asyncio.sleep(delay)

        raise RuntimeError("Discord gateway startup failed after retries.") from last_error

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
