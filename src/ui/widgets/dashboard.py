"""Session dashboard tiles (2x2 grid) for live metrics while a voice session runs."""

from __future__ import annotations

from rich.markup import escape
from textual.widgets import Static


class MetricTile(Static):
    """Two-line tile: metric label and current value."""

    DEFAULT_CSS = """
    MetricTile {
        border: round $primary;
        padding: 0 1;
        margin: 0 1;
        width: 1fr;
        min-height: 3;
        content-align: center middle;
        text-align: center;
    }
    """

    def __init__(self, *, tile_id: str, label: str) -> None:
        super().__init__(id=tile_id, classes="metric-tile")
        self._label = label
        self.set_value("—")

    def set_value(self, value: str) -> None:
        """Update the value line under the fixed label."""
        self.update(f"[b]{self._label}[/b]\n{escape(value)}")


class SessionTimerTile(MetricTile):
    """Elapsed time since session start."""

    def __init__(self) -> None:
        super().__init__(tile_id="dash_session_timer", label="Running")


class STTMinutesTile(MetricTile):
    """Cumulative STT audio minutes."""

    def __init__(self) -> None:
        super().__init__(tile_id="dash_stt_minutes", label="STT (minutes)")


class TokensTile(MetricTile):
    """Cumulative GenAI tokens (input / output) with estimated cost."""

    def __init__(self) -> None:
        super().__init__(tile_id="dash_tokens", label="GenAI tokens")


class ElevenlabsCharactersTile(MetricTile):
    """Cumulative ElevenLabs characters synthesized with estimated cost."""

    def __init__(self) -> None:
        super().__init__(tile_id="dash_eleven_chars", label="ElevenLabs (chars)")


class CooldownTile(MetricTile):
    """Seconds until the post-reply cooldown allows another non-mention trigger."""

    def __init__(self) -> None:
        super().__init__(tile_id="dash_cooldown", label="Reply cooldown")


class MentionWindowTile(MetricTile):
    """Whether a nickname mention opened the timed reply window."""

    def __init__(self) -> None:
        super().__init__(tile_id="dash_mention", label="Mention window")
