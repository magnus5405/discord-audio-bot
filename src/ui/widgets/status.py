"""Bot status display widget."""

from textual.widgets import Static


class BotStatus(Static):
    """Display bot status and counters."""

    def render(self) -> str:
        """Render status information."""
        return """
Status: [not started]
Tokens: 0
Voice: 0.0 minutes
"""
