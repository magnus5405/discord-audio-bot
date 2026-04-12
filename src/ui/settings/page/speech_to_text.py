"""Speech-to-Text settings page widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Select

from src.storage import DEFAULT_STT_LANGUAGE_CODE


class SpeechToTextSettingsPage(Vertical):
    """Scrollable Speech-to-Text settings with a fixed action row."""

    def __init__(self) -> None:
        super().__init__(classes="settings_page")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="settings_scroll"):
            with Vertical(classes="settings_form"):
                with Vertical(classes="settings_field_group"):
                    yield Label("Primary language (BCP-47)")
                    yield Input(id="stt_primary_language", placeholder=DEFAULT_STT_LANGUAGE_CODE)
                with Vertical(classes="settings_field_group"):
                    yield Label("Alternative languages (BCP-47, comma-separated)")
                    yield Input(id="stt_alternative_languages", placeholder="en-US, en-GB")
                with Vertical(classes="settings_field_group"):
                    yield Label("Google STT backend")
                    yield Select(
                        [("v1", "v1"), ("v2", "v2")],
                        id="stt_backend",
                        prompt="Select STT backend...",
                    )
                with Vertical(id="stt_v1_fields"):
                    with Vertical(classes="settings_field_group"):
                        yield Label("Google STT API key")
                        yield Input(
                            id="stt_google_api_key",
                            placeholder="GOOGLE_STT_API_KEY",
                            password=True,
                        )
                with Vertical(id="stt_v2_fields"):
                    with Vertical(classes="settings_field_group"):
                        yield Label("Service account JSON path")
                        yield Input(
                            id="stt_google_application_credentials",
                            placeholder="C:\\path\\to\\service-account.json",
                        )
                    with Vertical(classes="settings_field_group"):
                        yield Label("Google STT project ID")
                        yield Input(id="stt_google_project_id", placeholder="GOOGLE_STT_PROJECT_ID")
                    with Vertical(classes="settings_field_group"):
                        yield Label("Google STT location")
                        yield Input(id="stt_google_location", placeholder="eu")
                    with Vertical(classes="settings_field_group"):
                        yield Label("Google STT model")
                        yield Select(
                            [("chirp_2", "chirp_2"), ("chirp_3", "chirp_3"), ("telephony", "telephony")],
                            id="stt_google_model",
                            prompt="Select STT model...",
                        )
        with Horizontal(classes="settings_action_row"):
            yield Button("Save Speech-to-Text", id="btn_save_stt", variant="success")
