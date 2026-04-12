"""Discord config settings page widget."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label


class DiscordSettingsPage(Vertical):
    """Scrollable Discord config page with a fixed action row."""

    def __init__(self) -> None:
        super().__init__(classes="settings_page")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="settings_scroll"):
            with Vertical(classes="settings_form"):
                with Vertical(classes="settings_field_group"):
                    yield Label("Discord token")
                    yield Input(id="discord_token", placeholder="Discord bot token", password=True)
                with Vertical(classes="settings_field_group"):
                    yield Label("Discord server ID")
                    yield Input(id="discord_server_id", placeholder="DISCORD_SERVER_ID")
        with Horizontal(classes="settings_action_row"):
            yield Button("Save Discord", id="btn_save_discord", variant="success")
