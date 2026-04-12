"""Live session metrics for TUI and observability."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class SessionMetrics:
    """Mutable snapshot updated by the conversation runner; TUI polls periodically."""

    session_started_at: float = field(default_factory=time.monotonic)
    total_tokens: int = 0
    genai_input_tokens: int = 0
    genai_output_tokens: int = 0
    stt_seconds: float = 0.0
    tts_characters: int = 0
    status_line: str = "idle"
    guild_label: str = ""
    channel_label: str = ""
    running: bool = False
    last_error: str = ""
    transcript_lines: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    mention_waiting: bool = False
    mention_seconds_left: float = 0.0
    cooldown_seconds_left: float = 0.0

    def reset_session_clock(self) -> None:
        """Call when a voice session starts."""
        self.session_started_at = time.monotonic()
        self.transcript_lines.clear()
        self.mention_waiting = False
        self.mention_seconds_left = 0.0
        self.cooldown_seconds_left = 0.0

    def session_duration_seconds(self) -> float:
        return time.monotonic() - self.session_started_at

    def add_stt_seconds(self, delta: float) -> None:
        if delta > 0:
            self.stt_seconds += delta

    def append_transcript_line(self, line: str) -> None:
        text = (line or "").strip()
        if text:
            self.transcript_lines.append(text)

    def set_policy_ui_snapshot(
        self, mention_waiting: bool, mention_seconds_left: float, cooldown_seconds_left: float
    ) -> None:
        self.mention_waiting = mention_waiting
        self.mention_seconds_left = mention_seconds_left
        self.cooldown_seconds_left = cooldown_seconds_left
