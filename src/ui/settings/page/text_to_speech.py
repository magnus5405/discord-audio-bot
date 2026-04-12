"""Text-to-Speech settings page widget."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label


class TextToSpeechSettingsPage(Vertical):
    """Scrollable Text-to-Speech settings with a fixed action row."""

    def __init__(self) -> None:
        super().__init__(classes="settings_page")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="settings_scroll"):
            with Vertical(classes="settings_form"):
                with Vertical(classes="settings_field_group"):
                    yield Label("Reply language (BCP-47)")
                    yield Input(
                        id="tts_reply_language",
                        placeholder="Leave blank to follow Speech-to-Text primary language",
                    )
                with Vertical(classes="settings_field_group"):
                    yield Label("Gemini API key")
                    yield Input(id="tts_gemini_api_key", placeholder="GOOGLE_GEMINI_API_KEY", password=True)
                with Vertical(classes="settings_field_group"):
                    yield Label("ElevenLabs API key")
                    yield Input(id="tts_elevenlabs_api_key", placeholder="ELEVENLABS_API_KEY", password=True)
        with Horizontal(classes="settings_action_row"):
            yield Button("Save Text-to-Speech", id="btn_save_tts", variant="success")
