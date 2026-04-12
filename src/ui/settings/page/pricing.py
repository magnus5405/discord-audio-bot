"""Estimated API pricing for live session cost tiles."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label


class PricingSettingsPage(Vertical):
    """USD rate card used by the dashboard session tiles."""

    def __init__(self) -> None:
        super().__init__(classes="settings_page")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="settings_scroll"):
            with Vertical(classes="settings_form"):
                with Vertical(classes="settings_field_group"):
                    yield Label("ElevenLabs — USD per 1,000 characters")
                    yield Input(id="pricing_elevenlabs_per_1k_chars", placeholder="0.1")
                with Vertical(classes="settings_field_group"):
                    yield Label("GenAI — USD per 1,000 input tokens")
                    yield Input(id="pricing_genai_input_per_1m", placeholder="0.25")
                with Vertical(classes="settings_field_group"):
                    yield Label("GenAI — USD per 1,000 output tokens")
                    yield Input(id="pricing_genai_output_per_1m", placeholder="1.5")
                with Vertical(classes="settings_field_group"):
                    yield Label("Google STT — USD per audio minute")
                    yield Input(id="pricing_google_stt_per_minute", placeholder="0.016")
        with Horizontal(classes="settings_action_row"):
            yield Button("Save Pricing", id="btn_save_pricing", variant="success")
