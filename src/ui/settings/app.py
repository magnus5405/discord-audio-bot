"""Standalone settings editor entrypoint app."""

from __future__ import annotations

import logging

from dotenv import load_dotenv
from textual.app import App

from src.main import configure_logging_for_tui
from src.storage import SettingsStore

from .screen import BotSettingsScreen

logger = logging.getLogger(__name__)


class SettingsRunnerApp(App[None]):
    """Minimal host that opens the settings screen then exits."""

    async def on_mount(self) -> None:
        await self.push_screen(
            BotSettingsScreen(SettingsStore()),
            callback=lambda _result: self.exit(),
        )


def run_settings_ui() -> None:
    """Entry point for ``python -m src.ui.settings``."""
    load_dotenv()
    configure_logging_for_tui()
    SettingsRunnerApp().run()
