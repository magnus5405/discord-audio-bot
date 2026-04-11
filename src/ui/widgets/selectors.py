"""Selector widgets for UI."""

from textual.widgets import Static


class ChannelSelector(Static):
    """Select guild and voice channel."""

    def render(self) -> str:
        """Render channel selector."""
        return """
No guild selected
"""


class PersonaSelector(Static):
    """Select active persona."""

    def render(self) -> str:
        """Render persona selector."""
        return """
Persona: [Select...]
"""
