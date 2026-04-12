"""Session transcript snapshot persistence."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
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
            "genai_input_tokens": 0,
            "genai_output_tokens": 0,
            "tts_seconds_generated": 0.0,
            "tts_characters": 0,
            "stt_seconds_processed": 0.0,
        }
        self._write_lock = threading.Lock()

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
        """Set cumulative GenAI token total (legacy helper; counts all as input)."""
        t = max(0, int(total))
        self.usage["genai_input_tokens"] = t
        self.usage["genai_output_tokens"] = 0
        self.usage["total_tokens"] = t
        self.write_snapshot()

    def set_genai_token_counts(self, input_tokens: int, output_tokens: int) -> None:
        """Set GenAI prompt/output breakdown and derived total for this session snapshot."""
        inp = max(0, int(input_tokens))
        out = max(0, int(output_tokens))
        self.usage["genai_input_tokens"] = inp
        self.usage["genai_output_tokens"] = out
        self.usage["total_tokens"] = inp + out
        self.write_snapshot()

    def add_tts_seconds(self, delta: float) -> None:
        """Add generated TTS playback duration (seconds) to session usage."""
        current = float(self.usage.get("tts_seconds_generated", 0.0) or 0.0)
        self.usage["tts_seconds_generated"] = current + float(delta)
        self.write_snapshot()

    def add_tts_characters(self, delta: int) -> None:
        """Add synthesized TTS character count (ElevenLabs billing unit)."""
        if delta <= 0:
            return
        current = int(self.usage.get("tts_characters", 0) or 0)
        self.usage["tts_characters"] = current + int(delta)
        self.write_snapshot()

    def add_stt_seconds(self, delta: float) -> None:
        """Add audio duration (seconds) sent through STT to session usage."""
        if delta <= 0:
            return
        current = float(self.usage.get("stt_seconds_processed", 0.0) or 0.0)
        self.usage["stt_seconds_processed"] = current + float(delta)
        self.write_snapshot()

    def add_token_usage(self, delta: int) -> None:
        """Increment cumulative GenAI token counter by ``delta`` (applied to output tally)."""
        current_out = int(self.usage.get("genai_output_tokens", 0) or 0)
        self.usage["genai_output_tokens"] = current_out + int(delta)
        inp = int(self.usage.get("genai_input_tokens", 0) or 0)
        self.usage["total_tokens"] = inp + self.usage["genai_output_tokens"]
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
        serialized = json.dumps(payload, indent=2)
        with self._write_lock:
            temp_path = self.path.parent / f"{self.path.stem}.{uuid.uuid4().hex}.tmp"
            temp_path.write_text(serialized, encoding="utf-8")
            try:
                self._replace_with_retries(temp_path, self.path)
            except PermissionError:
                self.path.write_text(serialized, encoding="utf-8")
            finally:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _replace_with_retries(src: Path, dst: Path) -> None:
        """Windows often briefly locks the destination; retry before giving up."""
        delay = 0.02
        last_error: PermissionError | None = None
        for attempt in range(8):
            try:
                os.replace(src, dst)
                return
            except PermissionError as exc:
                last_error = exc
                if attempt == 7:
                    break
                time.sleep(delay)
                delay = min(delay * 2.0, 0.25)
        assert last_error is not None
        raise last_error
