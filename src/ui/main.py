"""Main Textual TUI for bot control and monitoring."""

import logging

from textual.app import ComposeResult, App
from textual.widgets import Header, Footer, Static
from textual.containers import Container, Horizontal, Vertical

from .widgets import BotStatus, ChannelSelector, PersonaSelector

logger = logging.getLogger(__name__)


class BotControlPanel(Static):
    """Control panel for start/stop and settings."""

    def render(self) -> str:
        """Render control buttons."""
        return """
[S] Start  [H] Stop  [?] Settings
"""


class BotUI(App):
    """
    Main Textual TUI application for bot control.

    Shows running status, token totals, voice minutes, start/stop controls,
    guild/channel selection, persona picker, and settings menu.

    Phase 6: Textual TUI polish
    """

    BINDINGS = [
        ("s", "start", "Start"),
        ("h", "stop", "Stop"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the TUI layout."""
        yield Header()
        with Container():
            with Horizontal():
                yield BotStatus()
            with Horizontal():
                yield ChannelSelector()
                yield PersonaSelector()
            with Horizontal():
                yield BotControlPanel()
        yield Footer()

    def action_start(self) -> None:
        """Start the bot session."""
        logger.info("Start action triggered from TUI")

    def action_stop(self) -> None:
        """Stop the bot session."""
        logger.info("Stop action triggered from TUI")

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()


def run_tui() -> None:
    """Run the main Textual TUI."""
    app = BotUI()
    app.run()


if __name__ == "__main__":
    run_tui()
