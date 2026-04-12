"""User interface package.

Textual TUI applications for main control and settings management.
"""

from .dashboard.app import BotDashboardApp, run_tui_application
from .settings import BotSettingsScreen, PersonaSettingsScreen, SettingsRunnerApp, run_settings_ui

BotUI = BotDashboardApp


def run_tui() -> None:
    """Run the main control dashboard."""
    run_tui_application()


__all__ = [
    "BotDashboardApp",
    "BotUI",
    "BotSettingsScreen",
    "PersonaSettingsScreen",
    "run_settings_ui",
    "run_tui",
    "run_tui_application",
    "SettingsRunnerApp",
]
