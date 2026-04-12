"""Session transcript snapshot persistence."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..models import TranscriptSegment

DEFAULT_TRANSCRIPTS_DIR = Path("transcripts")


def _sanitize_filename_fragment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "unknown"


class TranscriptSessionWriter:
    """Persist one session transcript JSON file with atomic rewrites."""

    def __init__(
        self,
        *,
        guild_id: int,
        guild_name: str,
        channel_id: int,
        channel_name: str,
        transcripts_dir: Path | None = None,
        session_started_at: datetime | None = None,
    ) -> None:
        self.guild_id = guild_id
        self.guild_name = guild_name
        self.channel_id = channel_id
        self.channel_name = channel_name
        self.transcripts_dir = transcripts_dir or DEFAULT_TRANSCRIPTS_DIR
        self.session_started_at = session_started_at or datetime.now(timezone.utc)
        self.segments: list[TranscriptSegment] = []
        self.bot_replies: list[dict[str, object]] = []
        self.usage: dict[str, object] = {
            "total_tokens": 0,
            "tts_seconds_generated": 0.0,
        }

        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        timestamp = self.session_started_at.strftime("%Y-%m-%d_%H%M%S")
        guild_fragment = _sanitize_filename_fragment(self.guild_name)
        channel_fragment = _sanitize_filename_fragment(self.channel_name)
        self.path = self.transcripts_dir / f"{timestamp}_{guild_fragment}_{channel_fragment}.json"
        self.write_snapshot()

    def add_segment(self, segment: TranscriptSegment) -> None:
        """Append a final transcript segment and rewrite the session snapshot."""
        self.segments.append(segment)
        self.write_snapshot()

    def add_bot_reply(self, text: str, *, label: str = "reply") -> None:
        """Append a bot utterance (e.g. greeting or reply) and persist."""
        self.bot_replies.append(
            {
                "label": label,
                "text": text,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.write_snapshot()

    def set_total_tokens(self, total: int) -> None:
        """Set cumulative GenAI token total for this session snapshot."""
        self.usage["total_tokens"] = int(total)
        self.write_snapshot()

    def add_token_usage(self, delta: int) -> None:
        """Increment cumulative GenAI token counter by ``delta``."""
        current = int(self.usage.get("total_tokens", 0) or 0)
        self.usage["total_tokens"] = current + int(delta)
        self.write_snapshot()

    def write_snapshot(self) -> None:
        """Rewrite the session file atomically so partial progress survives crashes."""
        payload = {
            "session_started_at": self.session_started_at.isoformat(),
            "guild_id": self.guild_id,
            "guild_name": self.guild_name,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "segments": [
                asdict(segment)
                for segment in sorted(
                    self.segments,
                    key=lambda item: (item.end_ts, item.start_ts, item.user_id),
                )
            ],
            "bot_replies": list(self.bot_replies),
            "usage": dict(self.usage),
        }
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        temp_path.replace(self.path)
