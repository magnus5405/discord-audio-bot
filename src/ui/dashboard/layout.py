"""Composable layout helpers and CSS for the main dashboard."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Label, LoadingIndicator, Log, Select, Static

from src.ui.widgets import (
    CooldownTile,
    ElevenlabsCharactersTile,
    MentionWindowTile,
    SessionTimerTile,
    STTMinutesTile,
    TokensTile,
)

DASHBOARD_CSS = """
Screen {
    align: left top;
}
#main {
    width: 100%;
    height: 1fr;
    min-height: 0;
    padding: 0 1;
}
#dashboard_scroll {
    width: 100%;
    height: 1fr;
    min-height: 0;
}
#scroll_body {
    width: 100%;
    height: auto;
}
#content_area {
    height: auto;
    min-height: 0;
    padding-bottom: 0;
}
#selector_block {
    height: auto;
}
#selector_loader_row {
    height: auto;
    min-height: 11;
    padding: 1 0;
    align: center middle;
}
#selector_loader_row LoadingIndicator {
    margin: 0;
}
#selector_row {
    height: auto;
    min-height: 0;
    padding: 1 0;
    display: none;
}
#selector_row > Vertical {
    height: auto;
    min-height: 0;
}
#session_dashboard {
    height: auto;
    min-height: 1;
    display: none;
    padding-top: 0;
}
#session_dashboard Horizontal {
    height: auto;
    min-height: 1;
    align: center middle;
    padding: 0;
    margin-bottom: 0;
}
.dashboard_column_title {
    width: 100%;
    text-align: center;
    margin-bottom: 1;
    text-style: bold;
}
#guild_table, #channel_table {
    width: 1fr;
    height: 8;
    max-height: 8;
    min-height: 3;
    margin: 0 1;
    border: round $surface-lighten-1;
}
#right_col {
    width: 38;
    align: center top;
}
#right_col Select {
    width: 100%;
}
#persona_hint {
    width: 100%;
    text-align: center;
    margin-top: 1;
    color: $text-muted;
}
#btn_row {
    height: auto;
    align: center middle;
    padding: 0 0 1 0;
    border-top: tall $surface-lighten-1;
}
#btn_row Button {
    margin: 0 1;
}
#dash_row_3 {
    height: auto;
}
#footer_block {
    height: auto;
    min-height: 6;
    border-top: tall $surface-lighten-1;
    padding-top: 1;
}
#transcript_wrap {
    height: auto;
    min-height: 4;
    margin-bottom: 1;
    border: round $primary;
    display: none;
}
#transcript_wrap Label {
    padding: 0 1;
    text-align: center;
    width: 100%;
    text-style: bold;
}
#transcript_log {
    height: 12;
    min-height: 4;
    border-top: tall $primary;
}
#event_log_wrap {
    height: auto;
    min-height: 6;
    border: round $primary;
}
#event_log_wrap Label {
    padding: 0 1;
    text-align: center;
    width: 100%;
    text-style: bold;
}
#event_log {
    height: 14;
    min-height: 6;
    border-top: tall $primary;
}
"""


def compose_dashboard_layout(persona_options: list[tuple[str, str]]) -> ComposeResult:
    """Compose the dashboard layout widgets."""
    with Vertical(id="main"):
        with VerticalScroll(id="dashboard_scroll"):
            with Vertical(id="scroll_body"):
                with Vertical(id="content_area"):
                    with Vertical(id="selector_block"):
                        with Horizontal(id="selector_loader_row"):
                            yield LoadingIndicator(id="selector_loader")
                        with Horizontal(id="selector_row"):
                            with Vertical():
                                yield Label("Servers", classes="dashboard_column_title")
                                yield DataTable(id="guild_table", cursor_type="row", zebra_stripes=True)
                            with Vertical():
                                yield Label("Voice channels", classes="dashboard_column_title")
                                yield DataTable(id="channel_table", cursor_type="row", zebra_stripes=True)
                            with Vertical(id="right_col"):
                                yield Label("Character", classes="dashboard_column_title")
                                yield Select(
                                    persona_options,
                                    id="persona_select",
                                    prompt="Character",
                                )
                                yield Static("", id="persona_hint")
                    with Vertical(id="session_dashboard"):
                        with Horizontal(id="dash_row_1"):
                            yield SessionTimerTile()
                            yield STTMinutesTile()
                        with Horizontal(id="dash_row_2"):
                            yield TokensTile()
                            yield ElevenlabsCharactersTile()
                        with Horizontal(id="dash_row_3"):
                            yield CooldownTile()
                            yield MentionWindowTile()
                with Horizontal(id="btn_row"):
                    yield Button("Start", id="btn_start", variant="success", disabled=True)
                    yield Button("Stop", id="btn_stop", variant="error", disabled=True)
                    yield Button("Refresh servers", id="btn_refresh")
                    yield Button("Settings", id="btn_settings")
                with Vertical(id="footer_block"):
                    with Vertical(id="transcript_wrap"):
                        yield Label("Live transcript")
                        yield Log(id="transcript_log", max_lines=200, auto_scroll=True)
                    with Vertical(id="event_log_wrap"):
                        yield Label("Activity log")
                        yield Log(id="event_log", max_lines=300, auto_scroll=True)
