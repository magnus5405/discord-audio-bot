"""Per-user utterance coordination for streaming speech-to-text."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import AsyncIterator
from collections.abc import Callable
from dataclasses import dataclass

from ..models import AudioFrame, TranscriptSegment
from .preprocessing import convert_to_linear16
from .stt import GoogleSTTClient

logger = logging.getLogger(__name__)

SegmentHandler = Callable[[TranscriptSegment], object]


@dataclass(slots=True)
class _UtteranceSession:
    """Track one active STT streaming session for a single user."""

    user_id: int
    username: str
    sample_rate_hz: int
    utterance_started_at: float
    last_frame_monotonic: float
    audio_queue: asyncio.Queue[bytes | None]
    task: asyncio.Task[None]


class PerUserTranscriptionCoordinator:
    """Split incoming PCM frames into per-user streaming utterances."""

    def __init__(
        self,
        stt_client: GoogleSTTClient,
        segment_handler: SegmentHandler,
        *,
        idle_timeout_seconds: float = 0.5,
        poll_interval_seconds: float = 0.1,
        target_sample_rate_hz: int = 16000,
    ) -> None:
        self.stt_client = stt_client
        self.segment_handler = segment_handler
        self.idle_timeout_seconds = idle_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.target_sample_rate_hz = target_sample_rate_hz
        self._active_sessions: dict[int, _UtteranceSession] = {}
        self._all_tasks: set[asyncio.Task[None]] = set()
        self._worker_error: BaseException | None = None
        self._worker_failed = asyncio.Event()

    @property
    def active_user_count(self) -> int:
        """Return the number of users with active utterances."""
        return len(self._active_sessions)

    async def run(
        self,
        audio_queue: asyncio.Queue[AudioFrame],
        stop_event: asyncio.Event,
    ) -> None:
        """Consume audio frames until the caller signals shutdown."""
        try:
            while True:
                self._raise_worker_error()
                if stop_event.is_set() and audio_queue.empty():
                    break

                try:
                    frame = await asyncio.wait_for(
                        audio_queue.get(),
                        timeout=self.poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    await self._close_idle_sessions()
                    continue

                await self.process_frame(frame)
                await self._close_idle_sessions(reference_monotonic=frame.timestamp_monotonic)
        finally:
            await self.shutdown()
            self._raise_worker_error()

    async def process_frame(self, frame: AudioFrame) -> None:
        """Route one PCM frame into the correct per-user utterance stream."""
        self._raise_worker_error()
        session = self._active_sessions.get(frame.user_id)
        if session is not None:
            idle_gap = frame.timestamp_monotonic - session.last_frame_monotonic
            if idle_gap >= self.idle_timeout_seconds:
                await self._close_session(frame.user_id)
                session = None

        if session is None:
            session = self._start_session(frame)

        session.last_frame_monotonic = frame.timestamp_monotonic
        mono_bytes = convert_to_linear16(
            frame.pcm_bytes,
            from_sample_rate=frame.sample_rate_hz,
            to_sample_rate=self.target_sample_rate_hz,
            channels=frame.channels,
        )
        if mono_bytes:
            session.audio_queue.put_nowait(mono_bytes)

    async def shutdown(self) -> None:
        """Close active STT sessions and wait for all background tasks."""
        for user_id in list(self._active_sessions):
            await self._close_session(user_id)

        if not self._all_tasks:
            return

        await asyncio.gather(*list(self._all_tasks))

    async def _close_idle_sessions(self, reference_monotonic: float | None = None) -> None:
        now = time.monotonic() if reference_monotonic is None else reference_monotonic
        stale_users = [
            user_id
            for user_id, session in self._active_sessions.items()
            if now - session.last_frame_monotonic >= self.idle_timeout_seconds
        ]
        for user_id in stale_users:
            await self._close_session(user_id)

    def _start_session(self, frame: AudioFrame) -> _UtteranceSession:
        audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        utterance_started_at = time.time()
        task = asyncio.create_task(
            self._consume_utterance(
                user_id=frame.user_id,
                username=frame.username,
                sample_rate_hz=self.target_sample_rate_hz,
                utterance_started_at=utterance_started_at,
                audio_queue=audio_queue,
            ),
            name=f"stt-utterance-{frame.user_id}",
        )
        task.add_done_callback(self._all_tasks.discard)
        self._all_tasks.add(task)

        session = _UtteranceSession(
            user_id=frame.user_id,
            username=frame.username,
            sample_rate_hz=self.target_sample_rate_hz,
            utterance_started_at=utterance_started_at,
            last_frame_monotonic=frame.timestamp_monotonic,
            audio_queue=audio_queue,
            task=task,
        )
        self._active_sessions[frame.user_id] = session
        logger.debug("Started STT utterance for %s (%s)", frame.username, frame.user_id)
        return session

    async def _close_session(self, user_id: int) -> None:
        session = self._active_sessions.pop(user_id, None)
        if session is None:
            return

        session.audio_queue.put_nowait(None)
        logger.debug("Closed STT utterance for %s (%s)", session.username, session.user_id)

    async def _consume_utterance(
        self,
        *,
        user_id: int,
        username: str,
        sample_rate_hz: int,
        utterance_started_at: float,
        audio_queue: asyncio.Queue[bytes | None],
    ) -> None:
        async def audio_stream() -> AsyncIterator[bytes]:
            while True:
                chunk = await audio_queue.get()
                if chunk is None:
                    break
                yield chunk

        try:
            async for segment in self.stt_client.stream_recognize(
                audio_stream=audio_stream(),
                user_id=user_id,
                username=username,
                sample_rate_hz=sample_rate_hz,
                utterance_started_at=utterance_started_at,
            ):
                handler_result = self.segment_handler(segment)
                if inspect.isawaitable(handler_result):
                    await handler_result
        except Exception as exc:
            logger.error("STT utterance worker failed for %s (%s)", username, user_id, exc_info=True)
            if self._worker_error is None:
                self._worker_error = exc
                self._worker_failed.set()

    def _raise_worker_error(self) -> None:
        if self._worker_failed.is_set() and self._worker_error is not None:
            raise RuntimeError("Transcription worker failed.") from self._worker_error
