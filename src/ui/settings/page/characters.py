"""Characters settings page widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Select, TextArea

from src.storage import SettingsStore


class CharactersSettingsPage(Vertical):
    """Scrollable character editor with a fixed bottom action row."""

    def __init__(self, store: SettingsStore, model_options: list[tuple[str, str]]) -> None:
        super().__init__(classes="settings_page")
        self._store = store
        self._model_options = model_options

    def _character_options(self) -> list[tuple[str, str]]:
        personas = self._store.get_personalities()
        options = [(persona.display_name, persona.persona_id) for persona in personas]
        if not options:
            options = [("(add a character)", "")]
        return options

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="settings_scroll"):
            with Vertical(classes="settings_form"):
                with Horizontal(id="character_selector_row"):
                    with Vertical(classes="settings_side_label"):
                        yield Label("Character")
                    yield Select(
                        self._character_options(),
                        id="character_pick",
                        prompt="Select...",
                    )
                with Horizontal(id="character_fields_row"):
                    with Vertical(classes="settings_column"):
                        with Vertical(classes="settings_field_group"):
                            yield Label("ID")
                            yield Input(placeholder="e.g. friendly", id="character_id")
                        with Vertical(classes="settings_field_group"):
                            yield Label("Name")
                            yield Input(placeholder="Character name", id="character_name")
                    with Vertical(classes="settings_column"):
                        with Vertical(classes="settings_field_group"):
                            yield Label("Model")
                            yield Select(
                                self._model_options,
                                id="character_model",
                                prompt="Select Gemini model...",
                            )
                        with Vertical(classes="settings_field_group"):
                            yield Label("Voice ID")
                            yield Input(placeholder="ElevenLabs voice ID", id="character_voice_id")
                with Vertical(id="character_instruction_group", classes="settings_field_group"):
                    yield Label("Character instructions")
                    yield TextArea(id="character_instructions", language="markdown")
        with Horizontal(classes="settings_action_row"):
            yield Button("Add character", id="btn_add_character", variant="primary")
            yield Button("Delete character", id="btn_delete_character", variant="error")
            yield Button("Save character", id="btn_save_character", variant="success")
