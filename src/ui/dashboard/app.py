"""Main Textual dashboard app for voice-session control."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Button, DataTable, Footer, Header, Log, RichLog, Select, Static

from src.discord import DiscordClient
from src.main import (
    configure_logging_for_tui,
    get_required_token,
    resolve_greet_on_join,
    resolve_mention_window_seconds,
    resolve_reply_cooldown_seconds,
    resolve_reply_silence_seconds,
    resolve_stt_idle_timeout_seconds,
    voice_user_audio_allowed,
)
from src.session import ConversationRunnerConfig, SessionMetrics, run_voice_conversation
from src.storage import SettingsStore
from src.transcription.whispercpp import describe_whispercpp_model_status
from src.storage.reply_locale import resolve_bot_reply_language_code
from src.tts import resolve_elevenlabs_api_key
from src.ui.widgets import MetricTile

from ..settings.screen import BotSettingsScreen
from .formatting import (
    format_cooldown_tile,
    format_eleven_chars_with_price,
    format_genai_tokens_with_price,
    format_mention_tile,
    format_session_timer,
    format_stt_minutes_with_price,
)
from .layout import DASHBOARD_CSS, compose_dashboard_layout

logger = logging.getLogger(__name__)


class BotDashboardApp(App[None]):
    """Main control surface: guild/channel pickers, character, metrics, and start/stop."""

    CSS = DASHBOARD_CSS

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "Quit"),
        ("o", "settings", "Settings"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._settings_store = SettingsStore()
        self._metrics = SessionMetrics()
        self._discord: DiscordClient | None = None
        self._guild_rows: list[tuple[int, str]] = []
        self._selected_guild_id: int | None = None
        self._selected_channel_id: int | None = None
        self._stop_event: asyncio.Event | None = None
        self._session_task: asyncio.Task[None] | None = None
        self._connect_task: asyncio.Task[None] | None = None
        self._user_stopped_session = False
        self._transcript_snapshot: tuple[str, ...] = ()
        self._transcript_rendered_lines = 0
        self._refreshing = False
        self._channels_loading = False
        self._last_status_line = ""

    def _persona_select_options(self) -> list[tuple[str, str]]:
        personas = self._settings_store.get_personalities()
        options = [(persona.display_name, persona.persona_id) for persona in personas]
        if not options:
            options = [("(no characters — edit settings)", "")]
        return options

    def compose(self) -> ComposeResult:
        yield Header()
        yield from compose_dashboard_layout(self._persona_select_options())
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "Discord Audio Bot"
        for table_id, column in (("guild_table", "Server"), ("channel_table", "Channel")):
            table = self.query_one(f"#{table_id}", DataTable)
            table.add_column(column)
        self._reload_persona_select()
        self._connect_task = asyncio.create_task(
            self._connect_discord_body(),
            name="tui-discord-connect",
        )
        self.set_interval(0.5, self._refresh_metrics_bar)
        self.call_later(self._sync_start_button_state)

    async def on_unmount(self) -> None:
        if self._stop_event and not self._stop_event.is_set():
            self._stop_event.set()
        if self._session_task:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._session_task, timeout=60.0)
            if not self._session_task.done():
                self._session_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._session_task
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._connect_task
        if self._discord:
            with suppress(Exception):
                await self._discord.disconnect()

    def _reload_persona_select(self) -> None:
        select = self.query_one("#persona_select", Select)
        options = self._persona_select_options()
        select.set_options(options)
        prefs = self._settings_store.get_ui_preferences()
        last_persona_id = prefs.get("last_persona_id")
        if last_persona_id:
            for _, persona_id in options:
                if persona_id == str(last_persona_id):
                    select.value = persona_id
                    break

    def _set_status(self, text: str) -> None:
        message = (text or "").strip()
        if not message or message == self._last_status_line:
            return
        self._last_status_line = message
        timestamp = time.strftime("%H:%M:%S")
        self.query_one("#event_log", Log).write_line(f"[{timestamp}] {message}")

    def _append_activity_line(self, message: str) -> None:
        """Append a line to the activity log without status de-duplication."""
        line = (message or "").strip()
        if not line:
            return
        timestamp = time.strftime("%H:%M:%S")
        self.query_one("#event_log", Log).write_line(f"[{timestamp}] {line}")

    def _sync_transcript_log(self) -> None:
        if not self._session_live():
            return
        snapshot = tuple(self._metrics.transcript_lines)
        if snapshot == self._transcript_snapshot:
            return
        self._transcript_snapshot = snapshot
        log = self.query_one("#transcript_log", RichLog)
        if len(snapshot) < self._transcript_rendered_lines:
            log.clear()
            self._transcript_rendered_lines = 0
        for line in snapshot[self._transcript_rendered_lines :]:
            log.write(line)
        self._transcript_rendered_lines = len(snapshot)
        log.scroll_end(animate=False)

    def _loading(self) -> bool:
        if self._refreshing:
            return True
        if self._connect_task is not None and not self._connect_task.done():
            return True
        if self._discord is None:
            return False
        client = self._discord.client
        return client is None or not client.is_ready()

    def _selector_loading(self) -> bool:
        return self._channels_loading or self._loading()

    def _sync_selector_loader_visibility(self) -> None:
        busy = self._selector_loading()
        self.query_one("#selector_loader_row").display = busy
        self.query_one("#selector_row").display = not busy

    def _selection_ready(self) -> bool:
        persona_value = self.query_one("#persona_select", Select).value
        return (
            self._selected_guild_id is not None
            and self._selected_channel_id is not None
            and persona_value is not None
            and str(persona_value).strip() != ""
        )

    def _session_live(self) -> bool:
        return (self._session_task is not None and not self._session_task.done()) or self._metrics.running

    def _sync_start_button_state(self) -> None:
        start = self.query_one("#btn_start", Button)
        stop = self.query_one("#btn_stop", Button)
        refresh = self.query_one("#btn_refresh", Button)
        settings = self.query_one("#btn_settings", Button)
        live = self._session_live()
        if live:
            start.disabled = True
            stop.disabled = False
            refresh.disabled = True
            settings.disabled = True
            self._sync_selector_loader_visibility()
            return
        settings.disabled = False
        if self._selector_loading():
            start.disabled = True
            stop.disabled = True
            refresh.disabled = True
            self._sync_selector_loader_visibility()
            return
        start.disabled = not self._selection_ready()
        stop.disabled = True
        refresh.disabled = False
        self._sync_selector_loader_visibility()

    def _show_session_dashboard(self, show: bool) -> None:
        self.query_one("#selector_block").display = not show
        self.query_one("#session_dashboard").display = show

    def _reset_session_ui(self) -> None:
        self._show_session_dashboard(False)
        self.query_one("#transcript_wrap").display = False
        self._transcript_snapshot = ()
        self._transcript_rendered_lines = 0
        self.query_one("#persona_select", Select).disabled = False
        self.query_one("#persona_hint", Static).update("")

    def _preferred_guild_id(self) -> int | None:
        prefs = self._settings_store.get_ui_preferences()
        last_guild_id = prefs.get("last_guild_id")
        if last_guild_id is not None:
            return int(last_guild_id)
        return self._settings_store.resolve_discord_int("server_id", "DISCORD_SERVER_ID")

    def _slash_command_registry_guild_id(self) -> int | None:
        """Guild id for `tree.sync`: prefer settings / env over last UI selection (avoids wrong-server sync)."""
        try:
            configured = self._settings_store.resolve_discord_int("server_id", "DISCORD_SERVER_ID")
        except ValueError:
            logger.warning("Invalid server_id or DISCORD_SERVER_ID; using last selected server for slash sync if any.")
            configured = None
        if configured is not None:
            return configured
        prefs = self._settings_store.get_ui_preferences()
        last_guild_id = prefs.get("last_guild_id")
        if last_guild_id is not None:
            return int(last_guild_id)
        return None

    async def _connect_discord_body(self) -> None:
        self._set_status("Connecting to Discord...")
        self.call_later(self._sync_start_button_state)
        try:
            token = get_required_token(self._settings_store)
            sync_guild = self._slash_command_registry_guild_id()
            self._discord = DiscordClient(token, app_command_sync_guild_id=sync_guild)
            self._discord.set_activity_log_sink(lambda msg: self.call_later(self._append_activity_line, msg))
            await self._discord.connect()
            await self._populate_guild_table()
            summary = (self._discord.last_app_command_sync_summary or "").strip()
            if summary:
                self.call_later(self._append_activity_line, summary)
            self._set_status("Connected to Discord.")
        except Exception as exc:
            logger.exception("Discord connect failed")
            self._set_status(f"Discord error: {exc}")
        finally:
            self.call_later(self._sync_start_button_state)

    async def _populate_guild_table(self) -> None:
        if not self._discord:
            return
        guilds = await self._discord.get_guilds()
        self._guild_rows = [(guild.id, guild.name) for guild in sorted(guilds, key=lambda guild: guild.name.lower())]
        table = self.query_one("#guild_table", DataTable)
        table.clear()
        for guild_id, name in self._guild_rows:
            table.add_row(name, key=str(guild_id))

        preferred_guild_id = self._preferred_guild_id()
        selected_index = 0 if self._guild_rows else None
        if preferred_guild_id is not None:
            for index, (guild_id, _) in enumerate(self._guild_rows):
                if guild_id == preferred_guild_id:
                    selected_index = index
                    break

        if selected_index is not None and self._guild_rows:
            guild_id = self._guild_rows[selected_index][0]
            self._selected_guild_id = guild_id
            table.move_cursor(row=selected_index)
            await self._populate_channel_table(guild_id)
        else:
            self._selected_guild_id = None
            self._selected_channel_id = None
        self.call_later(self._sync_start_button_state)

    async def _populate_channel_table(self, guild_id: int) -> None:
        if not self._discord:
            return
        self._channels_loading = True
        self.call_later(self._sync_selector_loader_visibility)
        try:
            channels = await self._discord.get_voice_channels(guild_id)
            table = self.query_one("#channel_table", DataTable)
            table.clear()
            rows = [(channel.id, channel.name) for channel in sorted(channels, key=lambda channel: channel.name.lower())]
            for channel_id, name in rows:
                table.add_row(name, key=str(channel_id))
            prefs = self._settings_store.get_ui_preferences()
            last_channel_id = prefs.get("last_channel_id")
            selected_index: int | None = 0 if rows else None
            if last_channel_id is not None:
                for index, (channel_id, _) in enumerate(rows):
                    if channel_id == int(last_channel_id):
                        selected_index = index
                        break
            if selected_index is not None and rows:
                table.move_cursor(row=selected_index)
                self._selected_channel_id = rows[selected_index][0]
            else:
                self._selected_channel_id = None
            self.call_later(self._sync_start_button_state)
        finally:
            self._channels_loading = False
            self.call_later(self._sync_selector_loader_visibility)

    def _refresh_metrics_bar(self) -> None:
        try:
            metrics = self._metrics
            if self._session_live():
                rates = self._settings_store.resolve_pricing_config()
                stt_minutes = metrics.stt_seconds / 60.0
                self.query_one("#dash_session_timer", MetricTile).set_value(
                    format_session_timer(metrics.session_duration_seconds())
                )
                self.query_one("#dash_stt_minutes", MetricTile).set_value(
                    format_stt_minutes_with_price(
                        stt_minutes,
                        rates["google_stt_usd_per_minute"],
                        provider=self._settings_store.resolve_stt_provider(),
                        average_inference_seconds=metrics.average_stt_inference_seconds(),
                    )
                )
                self.query_one("#dash_tokens", MetricTile).set_value(
                    format_genai_tokens_with_price(
                        metrics.genai_input_tokens,
                        metrics.genai_output_tokens,
                        rates["genai_usd_per_1m_input_tokens"],
                        rates["genai_usd_per_1m_output_tokens"],
                    )
                )
                self.query_one("#dash_eleven_chars", MetricTile).set_value(
                    format_eleven_chars_with_price(
                        metrics.tts_characters,
                        rates["elevenlabs_usd_per_1k_characters"],
                    )
                )
                self.query_one("#dash_cooldown", MetricTile).set_value(
                    format_cooldown_tile(metrics.cooldown_seconds_left)
                )
                self.query_one("#dash_mention", MetricTile).set_value(format_mention_tile(metrics))
                self._sync_transcript_log()

            if self._session_task and self._session_task.done():
                self._session_task = None
                self._reset_session_ui()
                if metrics.last_error:
                    self._set_status(f"Session ended: {metrics.last_error}")
                elif not self._user_stopped_session:
                    self._set_status("Session finished.")
                self._user_stopped_session = False
                self.call_later(self._sync_start_button_state)
        except Exception:
            logger.exception("Dashboard metrics refresh failed")
            self._set_status("Dashboard metrics refresh failed; check logs.")

    @on(DataTable.RowHighlighted, "#guild_table")
    async def on_guild_highlight(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        guild_id = int(str(event.row_key.value))
        self._selected_guild_id = guild_id
        await self._populate_channel_table(guild_id)

    @on(DataTable.RowHighlighted, "#channel_table")
    def on_channel_highlight(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        self._selected_channel_id = int(str(event.row_key.value))
        self.call_later(self._sync_start_button_state)

    @on(Select.Changed, "#persona_select")
    def on_persona_changed(self, _event: Select.Changed) -> None:
        self.call_later(self._sync_start_button_state)

    @on(Button.Pressed, "#btn_refresh")
    async def on_refresh(self) -> None:
        if self._session_live() or self._selector_loading():
            return
        self._refreshing = True
        self.call_later(self._sync_start_button_state)
        self._set_status("Refreshing Discord servers...")
        try:
            if not self._discord or not self._discord.client or not self._discord.client.is_ready():
                await self._connect_discord_body()
            else:
                await self._populate_guild_table()
                self._set_status("Server list refreshed.")
        finally:
            self._refreshing = False
            self.call_later(self._sync_start_button_state)

    @on(Button.Pressed, "#btn_settings")
    async def on_settings_btn(self) -> None:
        await self.action_settings()

    async def action_settings(self) -> None:
        if self._session_live():
            self._set_status("Stop the session before opening settings.")
            return
        await self.push_screen(
            BotSettingsScreen(self._settings_store),
            callback=self._after_settings_screen,
        )

    def _after_settings_screen(self, _result: object | None = None) -> None:
        self._settings_store.load()
        self._reload_persona_select()
        self.call_later(self._sync_start_button_state)

    @on(Button.Pressed, "#btn_start")
    async def on_start(self) -> None:
        if self._session_live():
            return
        if not self._discord or not self._discord.client or not self._discord.client.is_ready():
            self._set_status("Not connected to Discord yet.")
            return
        if self._selected_channel_id is None:
            self._set_status("Highlight a voice channel row first.")
            return

        gemini_key = self._settings_store.resolve_api_secret(
            "google_gemini_api_key",
            "GOOGLE_GEMINI_API_KEY",
        )
        if not gemini_key:
            self._set_status("Set the Gemini API key in Settings > Text-to-Speech or .env.")
            return
        stt_provider = self._settings_store.resolve_stt_provider()
        if stt_provider == "local":
            status = describe_whispercpp_model_status(
                self._settings_store.resolve_stt_local_model(),
                self._settings_store.resolve_stt_local_models_dir() or None,
            )
            if status.state != "downloaded":
                self._set_status(
                    f"{status.message} Open Settings > Speech-to-Text and download the selected local model before starting."
                )
                return
        else:
            stt_backend = (self._settings_store.resolve_stt_speech_backend() or "").strip().lower()
            stt_key = self._settings_store.resolve_stt_api_key()
            stt_credentials_path = self._settings_store.resolve_stt_credentials_path()
            stt_project = self._settings_store.resolve_stt_project_id()
            stt_location = self._settings_store.resolve_stt_location()
            stt_model = self._settings_store.resolve_stt_model()
            use_stt_v2 = stt_backend == "v2" or (
                not stt_backend
                and any(value for value in (stt_credentials_path, stt_project, stt_location, stt_model))
            )
            if use_stt_v2:
                if not stt_credentials_path:
                    self._set_status("Set the STT service account JSON path in Settings > Speech-to-Text.")
                    return
                if not Path(stt_credentials_path).exists():
                    self._set_status("The STT service account JSON path does not exist.")
                    return
                if not stt_project:
                    self._set_status("Set the Google STT project ID in Settings > Speech-to-Text.")
                    return
                if not stt_location:
                    self._set_status("Set the Google STT location in Settings > Speech-to-Text.")
                    return
                if not stt_model:
                    self._set_status("Set the Google STT model in Settings > Speech-to-Text.")
                    return
            elif not stt_key:
                self._set_status("Set the Google STT API key in Settings > Speech-to-Text or .env.")
                return
        elevenlabs_key = resolve_elevenlabs_api_key(self._settings_store)
        if not elevenlabs_key:
            self._set_status("Set the ElevenLabs API key in Settings > Text-to-Speech or .env.")
            return

        persona_id = self.query_one("#persona_select", Select).value
        if not persona_id or str(persona_id).strip() == "":
            self._set_status("Select a character.")
            return

        self._settings_store.update_ui_preference("last_guild_id", self._selected_guild_id)
        self._settings_store.update_ui_preference("last_channel_id", self._selected_channel_id)
        self._settings_store.update_ui_preference("last_persona_id", persona_id)
        self._settings_store.save()

        self._stop_event = asyncio.Event()
        self._show_session_dashboard(True)
        self.query_one("#transcript_wrap").display = True
        self._transcript_snapshot = ()
        self._transcript_rendered_lines = 0
        self.query_one("#transcript_log", RichLog).clear()
        self.query_one("#persona_select", Select).disabled = True
        self._metrics = SessionMetrics()
        self._session_task = asyncio.create_task(
            self._run_session(int(self._selected_channel_id), str(persona_id), elevenlabs_key),
            name="voice-session",
        )
        self.call_later(self._sync_start_button_state)
        self._set_status("Session starting...")

    @on(Button.Pressed, "#btn_stop")
    async def on_stop(self) -> None:
        self._user_stopped_session = True
        if self._stop_event:
            self._stop_event.set()
        if self._session_task:
            try:
                await asyncio.wait_for(self._session_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._set_status("Stop timed out; cancelling the session task.")
                self._session_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._session_task
            except Exception as exc:
                logger.exception("Session stop observed an error")
                self._set_status(f"Session stop observed an error: {exc}")
            self._session_task = None
        self._metrics.running = False
        self._metrics.status_line = "stopped"
        self._reset_session_ui()
        self._set_status("Stopped.")
        self.call_later(self._sync_start_button_state)

    async def _run_session(self, channel_id: int, persona_id: str, elevenlabs_key: str) -> None:
        assert self._discord is not None
        assert self._stop_event is not None
        try:
            await self._discord.join_voice_channel(channel_id)
            voice_client = self._discord.voice_client
            if voice_client is None:
                raise RuntimeError("Voice client missing after join.")
            config = ConversationRunnerConfig(
                stt_idle_timeout_seconds=resolve_stt_idle_timeout_seconds(),
                reply_silence_seconds=resolve_reply_silence_seconds(self._settings_store),
                reply_cooldown_seconds=resolve_reply_cooldown_seconds(self._settings_store),
                mention_window_seconds=resolve_mention_window_seconds(self._settings_store),
                greet_on_join=resolve_greet_on_join(self._settings_store),
                reply_locale=resolve_bot_reply_language_code(self._settings_store),
            )
            await run_voice_conversation(
                self._discord,
                voice_client,
                None,
                elevenlabs_api_key=elevenlabs_key,
                settings_store=self._settings_store,
                runner_config=config,
                persona_id=persona_id,
                external_stop_event=self._stop_event,
                metrics=self._metrics,
                user_audio_allowed=voice_user_audio_allowed(self._discord),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Session failed")
            self._metrics.last_error = str(exc)
            self._set_status(f"Session error: {exc}")
        finally:
            if self._discord:
                with suppress(Exception):
                    await self._discord.leave_voice_channel()

    def action_quit(self) -> None:
        self.exit()


def run_tui_application() -> None:
    """Blocking entry: load env, file-only logging, then run the dashboard."""
    from src.runtime_dirs import load_application_dotenv

    load_application_dotenv()
    configure_logging_for_tui()
    BotDashboardApp().run()
