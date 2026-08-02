"""Speech-to-Text settings page widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Select

from src.storage import (
    DEFAULT_LOCAL_STT_BACKEND,
    DEFAULT_STT_LANGUAGE_CODE,
)
from src.transcription.whispercpp import WHISPERCPP_MODEL_IDS


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
                    yield Label("Provider")
                    yield Select(
                        [("Google Cloud", "google"), ("Local whisper.cpp", "local")],
                        id="stt_provider",
                        prompt="Select Speech-to-Text provider...",
                    )
                with Vertical(id="stt_google_section"):
                    with Vertical(classes="settings_field_group"):
                        yield Label("Google STT backend")
                        yield Select(
                            [("v1", "v1"), ("v2", "v2")],
                            id="stt_backend",
                            prompt="Select Google STT backend...",
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
                                [
                                    ("chirp_2", "chirp_2"),
                                    ("chirp_3", "chirp_3"),
                                    ("telephony", "telephony"),
                                ],
                                id="stt_google_model",
                                prompt="Select Google STT model...",
                            )
                with Vertical(id="stt_local_section"):
                    with Vertical(classes="settings_field_group"):
                        yield Label("Local backend")
                        yield Select(
                            [("whisper.cpp", DEFAULT_LOCAL_STT_BACKEND)],
                            id="stt_local_backend",
                            prompt="Select local STT backend...",
                        )
                    with Vertical(classes="settings_field_group"):
                        yield Label("Local model")
                        yield Select(
                            [(model_id, model_id) for model_id in WHISPERCPP_MODEL_IDS],
                            id="stt_local_model",
                            prompt="Select local model...",
                        )
                    with Vertical(classes="settings_field_group"):
                        yield Label("Models directory")
                        yield Input(
                            id="stt_local_models_dir",
                            placeholder="Leave blank to use the default folder beside the app",
                        )
                        yield Label("", id="stt_local_models_dir_hint")
                    with Vertical(classes="settings_field_group"):
                        yield Label("Model status")
                        yield Label("Missing", id="stt_local_model_status")
                    with Horizontal(classes="settings_action_row", id="stt_local_actions"):
                        yield Button("Use Default Folder", id="btn_stt_local_use_default")
                        yield Button("Download Model", id="btn_stt_local_download", variant="primary")
        with Horizontal(classes="settings_action_row"):
            yield Button("Save Speech-to-Text", id="btn_save_stt", variant="success")
