"""Persist per-user consent for third-party processing (issue #8)."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..runtime_dirs import app_bundle_dir


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ConsentAcceptEvent:
    """One recorded acceptance with DM proof."""

    at: str
    disclosure_dm_channel_id: int
    disclosure_message_id: int


def _default_records_path() -> Path:
    return app_bundle_dir() / "consent" / "records.json"


class ConsentStore:
    """
    Thread-safe JSON store: per-user append-only events (accept / revoke).
    Active consent means the latest event is accept.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_records_path()
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def is_consented(self, user_id: int) -> bool:
        key = str(user_id)
        with self._lock:
            data = self._load_unlocked()
            return self._is_consented_unlocked(data, key)

    @staticmethod
    def _is_consented_unlocked(data: dict[str, Any], user_key: str) -> bool:
        user = data.get("users", {}).get(user_key)
        if not user or not isinstance(user, dict):
            return False
        events = user.get("events")
        if not events or not isinstance(events, list):
            return False
        last = events[-1]
        if not isinstance(last, dict):
            return False
        return last.get("type") == "accept"

    def record_acceptance(
        self,
        user_id: int,
        *,
        disclosure_dm_channel_id: int,
        disclosure_message_id: int,
        at: str | None = None,
    ) -> None:
        ts = at or _utc_now_iso()
        key = str(user_id)
        event: dict[str, Any] = {
            "type": "accept",
            "at": ts,
            "disclosure_dm_channel_id": disclosure_dm_channel_id,
            "disclosure_message_id": disclosure_message_id,
        }
        with self._lock:
            data = self._load_unlocked()
            users = data.setdefault("users", {})
            bucket = users.setdefault(key, {"events": []})
            if "events" not in bucket or not isinstance(bucket["events"], list):
                bucket["events"] = []
            bucket["events"].append(event)
            self._save_unlocked(data)

    def revoke(self, user_id: int, *, at: str | None = None) -> bool:
        """Append revoke event. Returns True if the user was actively consented before."""
        ts = at or _utc_now_iso()
        key = str(user_id)
        event: dict[str, Any] = {"type": "revoke", "at": ts}
        with self._lock:
            data = self._load_unlocked()
            was_active = self._is_consented_unlocked(data, key)
            users = data.setdefault("users", {})
            if key not in users:
                users[key] = {"events": []}
            bucket = users[key]
            if "events" not in bucket or not isinstance(bucket["events"], list):
                bucket["events"] = []
            bucket["events"].append(event)
            self._save_unlocked(data)
            return was_active

    def last_accept(self, user_id: int) -> ConsentAcceptEvent | None:
        key = str(user_id)
        with self._lock:
            data = self._load_unlocked()
            user = data.get("users", {}).get(key)
            if not user or not isinstance(user, dict):
                return None
            events = user.get("events")
            if not events or not isinstance(events, list):
                return None
            for raw in reversed(events):
                if not isinstance(raw, dict):
                    continue
                if raw.get("type") != "accept":
                    continue
                try:
                    return ConsentAcceptEvent(
                        at=str(raw["at"]),
                        disclosure_dm_channel_id=int(raw["disclosure_dm_channel_id"]),
                        disclosure_message_id=int(raw["disclosure_message_id"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            return None

    def _load_unlocked(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {"version": 1, "users": {}}
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "users": {}}
        if not isinstance(data, dict):
            return {"version": 1, "users": {}}
        users = data.get("users")
        if users is None:
            data["users"] = {}
        elif not isinstance(users, dict):
            data["users"] = {}
        data.setdefault("version", 1)
        return data

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        data["version"] = 1
        serialized = json.dumps(data, indent=2)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.parent / f"{self._path.stem}.{uuid.uuid4().hex}.tmp"
        temp_path.write_text(serialized, encoding="utf-8")
        try:
            self._replace_with_retries(temp_path, self._path)
        except PermissionError:
            self._path.write_text(serialized, encoding="utf-8")
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _replace_with_retries(src: Path, dst: Path) -> None:
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
