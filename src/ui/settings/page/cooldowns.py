"""Cooldown settings page widget."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Switch


class CooldownsSettingsPage(Vertical):
    """Scrollable cooldown settings with a fixed action row."""

    def __init__(self) -> None:
        super().__init__(classes="settings_page")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="settings_scroll"):
            with Vertical(classes="settings_form"):
                with Vertical(classes="settings_field_group"):
                    yield Label("Reply silence seconds")
                    yield Input(id="cooldown_reply_silence_seconds", placeholder="5")
                with Vertical(classes="settings_field_group"):
                    yield Label("Reply cooldown seconds")
                    yield Input(id="cooldown_reply_cooldown_seconds", placeholder="180")
                with Vertical(classes="settings_field_group"):
                    yield Label("Mention window seconds")
                    yield Input(id="cooldown_mention_window_seconds", placeholder="30")
                with Horizontal(classes="settings_field_group settings_toggle_row", id="cooldown_greet_row"):
                    yield Switch(value=True, id="cooldown_greet_on_join")
                    with Vertical(classes="settings_side_label"):
                        yield Label("Greet users when they join the voice channel")
        with Horizontal(classes="settings_action_row"):
            yield Button("Save Cooldowns", id="btn_save_cooldowns", variant="success")
