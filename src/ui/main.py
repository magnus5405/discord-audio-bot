"""Textual TUI dashboard entrypoint."""

from __future__ import annotations

from .dashboard.app import BotDashboardApp, run_tui_application

# Back-compat alias for older imports (`BotUI` -> `BotDashboardApp`).
BotUI = BotDashboardApp


def run_tui() -> None:
    """Run the main control dashboard."""
    run_tui_application()


if __name__ == "__main__":
    run_tui()
