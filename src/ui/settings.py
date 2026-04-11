"""Settings editor Textual TUI."""

import logging

from textual.app import ComposeResult, App
from textual.widgets import Header, Footer, Static
from textual.containers import Container, Vertical

logger = logging.getLogger(__name__)


class PersonaEditor(Static):
    """Edit persona settings."""

    def render(self) -> str:
        """Render persona editor."""
        return """
Persona Editor
==============

Name: [________________]
System Instruction:
[____________________]
[____________________]

GenAI Model: [gemini-2.0-flash]
Voice ID: [________________]

[Save] [Cancel] [Delete]
"""


class STTSettings(Static):
    """Configure speech-to-text settings."""

    def render(self) -> str:
        """Render STT settings."""
        return """
Speech-to-Text Settings
=======================

Primary Language: [da-DK]
Alternative Languages: [en-US, en-GB]

[Save] [Reset to Defaults]
"""


class GeneralSettings(Static):
    """General bot configuration."""

    def render(self) -> str:
        """Render general settings."""
        return """
General Settings
================

Silence Timeout (seconds): [5]
Cooldown (seconds): [180]
Mention Window (seconds): [30]

[Save] [Reset to Defaults]
"""


class SettingsUI(App):
    """
    Settings editor Textual TUI application.

    Create/edit personas, configure GenAI model, select ElevenLabs voice IDs,
    adjust STT language preferences and cooldown timers.

    Phase 6: Settings management
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "save", "Save"),
        ("r", "reset", "Reset"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the settings UI layout."""
        yield Header()
        with Container():
            with Vertical():
                yield PersonaEditor()
                yield GeneralSettings()
                yield STTSettings()
        yield Footer()

    def action_save(self) -> None:
        """Save settings."""
        logger.info("Settings saved")

    def action_reset(self) -> None:
        """Reset settings to defaults."""
        logger.info("Settings reset to defaults")

    def action_quit(self) -> None:
        """Quit settings editor."""
        self.exit()


def run_settings_ui() -> None:
    """Run the settings editor TUI."""
    app = SettingsUI()
    app.run()


if __name__ == "__main__":
    run_settings_ui()
