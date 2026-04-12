"""Small formatting helpers for dashboard metrics."""

from __future__ import annotations

from src.session import SessionMetrics


def format_usd_compact(amount: float) -> str:
    """Format a USD amount compactly for metric tiles."""
    sign = "-" if amount < 0 else ""
    mag = abs(float(amount))
    if mag == 0.0:
        return f"{sign}$0"
    body = f"{mag:.6f}".rstrip("0").rstrip(".")
    return f"{sign}${body}"


def format_stt_minutes_with_price(minutes: float, usd_per_minute: float) -> str:
    """STT audio minutes and estimated STT spend."""
    usd = float(minutes) * float(usd_per_minute)
    return f"{minutes:.2f} min ({format_usd_compact(usd)})"


def format_genai_tokens_with_price(
    input_tokens: int,
    output_tokens: int,
    usd_per_1m_input: float,
    usd_per_1m_output: float,
) -> str:
    """Token counts and estimated GenAI spend (input + output)."""
    usd = (input_tokens / 1000.0) * float(usd_per_1m_input) + (output_tokens / 1000.0) * float(
        usd_per_1m_output
    )
    return f"in {int(input_tokens)} · out {int(output_tokens)} ({format_usd_compact(usd)})"


def format_eleven_chars_with_price(characters: int, usd_per_1k_chars: float) -> str:
    """Characters sent to ElevenLabs and estimated spend."""
    usd = (int(characters) / 1000.0) * float(usd_per_1k_chars)
    return f"{int(characters)} ({format_usd_compact(usd)})"


def format_session_timer_with_total(duration_seconds: float, total_usd: float) -> str:
    """Session clock plus rough sum of the three API estimates on the dashboard."""
    return f"{format_duration(duration_seconds)}\n~Total {format_usd_compact(total_usd)}"


def format_duration(seconds: float) -> str:
    """Format seconds into a compact human-readable duration."""
    if seconds < 0:
        seconds = 0.0
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}h {minutes:02d}m {seconds:02d}s"
    return f"{minutes:d}m {seconds:02d}s"


def format_cooldown_tile(seconds: float) -> str:
    """Format reply cooldown text for the metric tile."""
    if seconds <= 0:
        return "Ready"
    return format_duration(seconds)


def format_mention_tile(metrics: SessionMetrics) -> str:
    """Format the mention-window tile from current session metrics."""
    if metrics.mention_waiting:
        left = max(0, int(metrics.mention_seconds_left))
        return f"Yes - up to {left}s left"
    return "No"
