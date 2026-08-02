"""Local ``whisper.cpp`` speech-to-text backend helpers and client."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import threading
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from ..models import TranscriptSegment
from ..runtime_dirs import app_bundle_dir
from ..storage.settings import (
    DEFAULT_LOCAL_STT_MODEL,
    DEFAULT_STT_LANGUAGE_CODE,
    default_local_stt_models_dir,
)

logger = logging.getLogger(__name__)

WHISPERCPP_BACKEND_ID = "whispercpp"
WHISPERCPP_MODEL_IDS = [
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3-turbo-q5_0",
]
_WHISPERCPP_MODEL_URL_TEMPLATE = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model_id}.bin"
)
_WHISPERCPP_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_WHISPERCPP_SAMPLE_RATE_HZ = 16000
_WHISPERCPP_TIMESTAMP_SECONDS = 0.01
_IGNORED_TRANSCRIPT_TEXT_CASEFOLDS = frozenset({"[blank_audio]"})

_WINDOWS_NATIVE_STDERR_REDIRECT_LOCK = threading.Lock()
_WINDOWS_NATIVE_STDERR_REDIRECT_DONE = False
_WINDOWS_NATIVE_STDERR_STREAM: Any | None = None


def _windows_native_redirect_enabled() -> bool:
    """Whether risky native stdio swapping is explicitly enabled on Windows.

    Default is disabled to keep Textual responsive. Enable only for debugging.
    """
    raw = (os.getenv("WHISPERCPP_WINDOWS_NATIVE_REDIRECT") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _resolve_whispercpp_native_log_path() -> Path:
    """Dedicated sink for native whisper.cpp stderr on Windows.

    Keep this separate from app logs so native lines never paint over the TUI.
    """
    target = _resolve_whispercpp_log_redirect_target()
    if isinstance(target, str) and target.strip():
        try:
            base_path = Path(target)
            if base_path.name:
                return base_path.with_name("whispercpp-native.log")
        except Exception:
            pass
    return app_bundle_dir() / "logs" / "whispercpp-native.log"


def _ensure_windows_native_stderr_redirected(log_path: Path) -> None:
    """Route process stderr to *log_path* once to capture native whisper.cpp output."""
    global _WINDOWS_NATIVE_STDERR_REDIRECT_DONE
    global _WINDOWS_NATIVE_STDERR_STREAM

    if os.name != "nt":
        return
    if _WINDOWS_NATIVE_STDERR_REDIRECT_DONE:
        return

    with _WINDOWS_NATIVE_STDERR_REDIRECT_LOCK:
        if _WINDOWS_NATIVE_STDERR_REDIRECT_DONE:
            return
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = open(log_path, "a", encoding="utf-8", buffering=1)
        try:
            with suppress(Exception):
                sys.stderr.flush()
            os.dup2(stream.fileno(), 2)
        except Exception:
            with suppress(Exception):
                stream.close()
            raise
        _WINDOWS_NATIVE_STDERR_STREAM = stream
        _WINDOWS_NATIVE_STDERR_REDIRECT_DONE = True
        logger.info("whisper.cpp native stderr redirected to %s", log_path)


def _available_cpu_threads() -> int:
    """Return the best available logical CPU count for local inference."""
    process_count = getattr(os, "process_cpu_count", None)
    if callable(process_count):
        count = process_count()
        if count:
            return max(1, int(count))
    count = os.cpu_count()
    return max(1, int(count or 1))


def _resolve_whispercpp_log_redirect_target() -> str | bool:
    """Prefer the active file logger so native ``whisper.cpp`` logs stay out of the TUI."""
    for handler in logging.getLogger().handlers:
        base_filename = getattr(handler, "baseFilename", None)
        if isinstance(base_filename, str) and base_filename.strip():
            return base_filename
    log_file = (os.getenv("TUI_LOG_FILE") or "").strip()
    if not log_file:
        return False
    path = Path(log_file)
    if getattr(sys, "frozen", False) and not path.is_absolute():
        path = app_bundle_dir() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def is_ignorable_transcript_text(text: str) -> bool:
    """True when the backend returned a placeholder rather than real speech."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return True
    return cleaned.casefold() in _IGNORED_TRANSCRIPT_TEXT_CASEFOLDS


def _flush_windows_cstdio() -> None:
    """Best-effort flush for native stdio before swapping Windows std handles."""
    if os.name != "nt":
        return
    with suppress(Exception):
        import ctypes

        ctypes.CDLL("msvcrt").fflush(None)


def _redirect_windows_standard_handle(
    stream_name: str,
    *,
    target_fd: int,
) -> tuple[object, object, object] | None:
    """Best-effort Windows std-handle redirect for native libraries outside Python's fd table."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        std_handle_id = (
            ctypes.c_uint(-11).value if stream_name == "stdout" else ctypes.c_uint(-12).value
        )
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        kernel32.SetStdHandle.restype = wintypes.BOOL
        previous_handle = kernel32.GetStdHandle(std_handle_id)
        target_handle = wintypes.HANDLE(msvcrt.get_osfhandle(target_fd))
        _flush_windows_cstdio()
        if not kernel32.SetStdHandle(std_handle_id, target_handle):
            raise OSError(ctypes.get_last_error(), f"SetStdHandle failed for {stream_name}")
        return kernel32, std_handle_id, previous_handle
    except Exception:
        logger.debug(
            "Could not redirect whisper.cpp native %s on Windows.",
            stream_name,
            exc_info=True,
        )
        return None


def _restore_windows_standard_handle(
    handle_state: tuple[object, object, object] | None,
) -> None:
    """Restore one Windows standard handle after a temporary native redirect."""
    if handle_state is None:
        return
    kernel32, std_handle_id, previous_handle = handle_state
    with suppress(Exception):
        _flush_windows_cstdio()
        kernel32.SetStdHandle(std_handle_id, previous_handle)
        _flush_windows_cstdio()


@contextlib.contextmanager
def _safe_pywhispercpp_redirect_stream(
    to: bool | Any | str | None,
    *,
    fallback_stream_name: str,
    fallback_stream_fileobjs: tuple[Any | None, ...],
    fd_candidates: tuple[int, ...],
    python_redirect,
):
    """Robust native + Python stream redirection for Textual/Windows consoles."""
    if to is False:
        yield
        return

    def _resolve_target(target):
        opened_stream = None
        if target is None:
            opened_stream = open(os.devnull, "w", encoding="utf-8")
            return opened_stream, True
        if isinstance(target, str):
            opened_stream = open(target, "a", encoding="utf-8")
            return opened_stream, True
        if hasattr(target, "write"):
            return target, False
        raise ValueError(
            "Invalid `to` parameter; expected None, a filepath string, or a file-like object."
        )

    stream, should_close = _resolve_target(to)
    candidate_fd_values: list[int] = []
    for stream_obj in fallback_stream_fileobjs:
        if stream_obj is None:
            continue
        try:
            fd = int(stream_obj.fileno())
        except (AttributeError, OSError, ValueError):
            continue
        if fd >= 0 and fd not in candidate_fd_values:
            candidate_fd_values.append(fd)
    for fd in fd_candidates:
        if fd not in candidate_fd_values:
            candidate_fd_values.append(fd)

    saved_fd: int | None = None
    active_fd: int | None = None
    target_fd: int | None = None
    windows_handle_state: tuple[object, object, object] | None = None
    # On Windows this redirection path can freeze Textual's writer thread. Keep it
    # disabled by default there unless explicitly opted in for debugging.
    allow_fd_swap = os.name != "nt" or _windows_native_redirect_enabled()
    if allow_fd_swap and hasattr(stream, "fileno"):
        try:
            target_fd = int(stream.fileno())
        except (AttributeError, OSError, ValueError):
            target_fd = None
    if os.name != "nt" and target_fd is not None:
        windows_handle_state = _redirect_windows_standard_handle(
            fallback_stream_name,
            target_fd=target_fd,
        )
    if allow_fd_swap and target_fd is not None:
        for fd in candidate_fd_values:
            try:
                saved_fd = os.dup(fd)
                active_fd = fd
                break
            except OSError:
                continue
    if allow_fd_swap and saved_fd is not None and active_fd is not None and target_fd is not None:
        try:
            os.dup2(target_fd, active_fd)
            yield
        finally:
            with suppress(OSError):
                os.dup2(saved_fd, active_fd)
            with suppress(OSError):
                os.close(saved_fd)
            _restore_windows_standard_handle(windows_handle_state)
            if should_close:
                with suppress(OSError):
                    stream.close()
        return

    try:
        with python_redirect(stream):
            yield
    finally:
        _restore_windows_standard_handle(windows_handle_state)
        if should_close:
            with suppress(OSError):
                stream.close()


@contextlib.contextmanager
def _safe_pywhispercpp_redirect_stderr(to: bool | Any | str | None = False):
    """Robust stderr redirection for ``pywhispercpp`` on Textual/Windows consoles."""
    with _safe_pywhispercpp_redirect_stream(
        to,
        fallback_stream_name="stderr",
        fallback_stream_fileobjs=(getattr(sys, "stderr", None), getattr(sys, "__stderr__", None)),
        fd_candidates=(2,),
        python_redirect=contextlib.redirect_stderr,
    ):
        yield


@contextlib.contextmanager
def _safe_pywhispercpp_redirect_stdout(to: bool | Any | str | None = False):
    """Robust stdout redirection for native ``whisper.cpp`` messages."""
    with _safe_pywhispercpp_redirect_stream(
        to,
        fallback_stream_name="stdout",
        fallback_stream_fileobjs=(getattr(sys, "stdout", None), getattr(sys, "__stdout__", None)),
        fd_candidates=(1,),
        python_redirect=contextlib.redirect_stdout,
    ):
        yield


@dataclass(frozen=True, slots=True)
class WhisperCppModelStatus:
    """UI-facing state for one local model file."""

    state: str
    message: str
    model_path: Path


def whispercpp_model_filename(model_id: str) -> str:
    """Filename for a ``whisper.cpp`` ggml model."""
    return f"ggml-{(model_id or DEFAULT_LOCAL_STT_MODEL).strip()}.bin"


def whispercpp_model_url(model_id: str) -> str:
    """Official upstream download URL for a ``whisper.cpp`` ggml model."""
    cleaned = (model_id or DEFAULT_LOCAL_STT_MODEL).strip()
    return _WHISPERCPP_MODEL_URL_TEMPLATE.format(model_id=cleaned)


def resolve_whispercpp_models_dir(models_dir: str | Path | None) -> Path:
    """Resolve the effective local models directory."""
    raw = str(models_dir).strip() if models_dir is not None else ""
    return Path(raw) if raw else default_local_stt_models_dir()


def resolve_whispercpp_model_path(model_id: str, models_dir: str | Path | None) -> Path:
    """Absolute path for the selected model file."""
    return resolve_whispercpp_models_dir(models_dir) / whispercpp_model_filename(model_id)


def whispercpp_partial_model_path(model_path: Path) -> Path:
    """Temporary path used while downloading one model file."""
    return model_path.with_suffix(model_path.suffix + ".part")


def describe_whispercpp_model_status(
    model_id: str,
    models_dir: str | Path | None,
) -> WhisperCppModelStatus:
    """Summarize whether the selected model exists, is downloading, or is missing."""
    model_path = resolve_whispercpp_model_path(model_id, models_dir)
    part_path = whispercpp_partial_model_path(model_path)
    if model_path.is_file():
        size_bytes = model_path.stat().st_size
        if size_bytes <= 0:
            return WhisperCppModelStatus(
                state="failed",
                message=f"Corrupt: {model_path.name} is empty. Re-download it.",
                model_path=model_path,
            )
        size_mb = size_bytes / (1024.0 * 1024.0)
        return WhisperCppModelStatus(
            state="downloaded",
            message=f"Downloaded: {model_path.name} ({size_mb:.1f} MB)",
            model_path=model_path,
        )
    if part_path.exists():
        return WhisperCppModelStatus(
            state="downloading",
            message=f"Downloading: {model_path.name}",
            model_path=model_path,
        )
    return WhisperCppModelStatus(
        state="missing",
        message=f"Missing: {model_path.name}",
        model_path=model_path,
    )


async def download_whispercpp_model(
    model_id: str,
    models_dir: str | Path | None,
) -> Path:
    """Download a model file atomically via ``*.part`` then rename on success."""
    resolved_model_id = (model_id or DEFAULT_LOCAL_STT_MODEL).strip()
    model_path = resolve_whispercpp_model_path(resolved_model_id, models_dir)
    part_path = whispercpp_partial_model_path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)

    if model_path.is_file() and model_path.stat().st_size > 0:
        return model_path

    with suppress(OSError):
        part_path.unlink(missing_ok=True)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
            async with client.stream("GET", whispercpp_model_url(resolved_model_id)) as response:
                response.raise_for_status()
                with open(part_path, "wb") as handle:
                    async for chunk in response.aiter_bytes(_WHISPERCPP_DOWNLOAD_CHUNK_BYTES):
                        if chunk:
                            handle.write(chunk)
        if not part_path.exists() or part_path.stat().st_size <= 0:
            raise RuntimeError("Downloaded model file is empty.")
        part_path.replace(model_path)
        logger.info("Downloaded whisper.cpp model %s to %s", resolved_model_id, model_path)
        return model_path
    except Exception:
        with suppress(OSError):
            part_path.unlink(missing_ok=True)
        raise


def _import_numpy():
    import numpy as np

    return np


def _import_pywhispercpp_model():
    try:
        import pywhispercpp.model as model_module
        import pywhispercpp.utils as utils_module
    except Exception as exc:  # pragma: no cover - exercised through error wrapping
        raise RuntimeError(
            "Local STT backend 'whisper.cpp' is unavailable. Install the pinned "
            "'pywhispercpp' runtime dependency for this build."
        ) from exc
    utils_module.redirect_stderr = _safe_pywhispercpp_redirect_stderr
    model_module.utils.redirect_stderr = _safe_pywhispercpp_redirect_stderr
    return model_module.Model


def _configured_language_preferences(
    primary_language: str,
    alternative_languages: list[str] | None,
) -> tuple[str | None, str | None]:
    """Convert BCP-47 hints into a Whisper language hint and transcript language code.

    Always prefer the configured primary language as Whisper hint. This prevents
    accidental fallback to auto-detection when alternatives contain different
    subtags (for example primary=da-DK and alternatives include en-US).
    """
    preferred_bcp47 = str(primary_language or "").strip() or None
    if preferred_bcp47 is None:
        for raw_code in alternative_languages or []:
            cleaned = str(raw_code or "").strip()
            if cleaned:
                preferred_bcp47 = cleaned
                break
    if preferred_bcp47 is None:
        return None, None
    subtag = preferred_bcp47.split("-", 1)[0].strip().lower()
    if not subtag:
        return None, preferred_bcp47
    return subtag, preferred_bcp47


def pcm16_bytes_to_float32(audio_bytes: bytes):
    """Convert 16-bit mono PCM bytes into an in-memory ``float32`` NumPy array."""
    np = _import_numpy()
    if not audio_bytes:
        return np.asarray([], dtype=np.float32)
    trimmed = audio_bytes[: len(audio_bytes) - (len(audio_bytes) % 2)]
    if not trimmed:
        return np.asarray([], dtype=np.float32)
    pcm = np.frombuffer(trimmed, dtype=np.int16)
    if pcm.size == 0:
        return np.asarray([], dtype=np.float32)
    return pcm.astype(np.float32) / np.float32(32768.0)


class WhisperCppSTTClient:
    """Local ``whisper.cpp`` client backed by ``pywhispercpp``."""

    def __init__(
        self,
        primary_language: str = DEFAULT_STT_LANGUAGE_CODE,
        alternative_languages: Optional[list[str]] = None,
        *,
        local_model: str | None = None,
        local_models_dir: str | Path | None = None,
        local_backend: str = WHISPERCPP_BACKEND_ID,
        on_inference_seconds: Callable[[float], None] | None = None,
    ) -> None:
        backend = (local_backend or "").strip().lower() or WHISPERCPP_BACKEND_ID
        if backend != WHISPERCPP_BACKEND_ID:
            raise ValueError(f"Unsupported local STT backend: {local_backend!r}")
        self.primary_language = primary_language
        self.alternative_languages = alternative_languages or ["en-US"]
        self.local_backend = backend
        self.local_model = (local_model or DEFAULT_LOCAL_STT_MODEL).strip() or DEFAULT_LOCAL_STT_MODEL
        self.models_dir = resolve_whispercpp_models_dir(local_models_dir)
        self.model_path = resolve_whispercpp_model_path(self.local_model, self.models_dir)
        self._language_hint, self._segment_language_code = _configured_language_preferences(
            self.primary_language,
            self.alternative_languages,
        )
        self._n_threads = _available_cpu_threads()
        self._log_redirect_target = _resolve_whispercpp_log_redirect_target()
        self._native_log_path = _resolve_whispercpp_native_log_path()
        self._on_inference_seconds = on_inference_seconds
        self._model: Any | None = None
        self._inference_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        if os.name == "nt":
            try:
                _ensure_windows_native_stderr_redirected(self._native_log_path)
            except Exception:
                logger.warning("Failed to redirect whisper.cpp native stderr", exc_info=True)
        logger.info(
            "WhisperCppSTTClient initialized: model=%s models_dir=%s language_hint=%s threads=%s",
            self.local_model,
            self.models_dir,
            self._language_hint or "auto",
            self._n_threads,
        )

    def _require_model_file(self) -> None:
        if not self.model_path.is_file():
            raise RuntimeError(
                "Local STT model is missing. Download "
                f"'{self.local_model}' in Settings > Speech-to-Text and store it at {self.model_path}."
            )
        if self.model_path.stat().st_size <= 0:
            raise RuntimeError(
                f"Local STT model file is empty or corrupt: {self.model_path}. Re-download it from the TUI."
            )

    def _ensure_model_loaded_sync(self):
        self._require_model_file()
        if self._model is not None:
            return self._model
        model_cls = _import_pywhispercpp_model()
        try:
            with _safe_pywhispercpp_redirect_stdout(self._log_redirect_target):
                with _safe_pywhispercpp_redirect_stderr(self._log_redirect_target):
                    self._model = model_cls(
                        str(self.model_path),
                        n_threads=self._n_threads,
                        print_realtime=False,
                        print_progress=False,
                        print_timestamps=False,
                        no_context=True,
                        redirect_whispercpp_logs_to=self._log_redirect_target,
                    )
        except Exception as exc:  # pragma: no cover - exercised via wrapped failure tests
            hint = (
                "The model file may be corrupt; try re-downloading it from the TUI."
                if "bad file descriptor" not in str(exc).lower()
                else "The pywhispercpp runtime could not initialize cleanly in this console session."
            )
            raise RuntimeError(
                f"Failed to load the local STT model from {self.model_path}. "
                f"{hint}"
            ) from exc
        return self._model

    def _transcribe_sync(self, audio_f32):
        model = self._ensure_model_loaded_sync()
        params: dict[str, object] = {}
        if self._language_hint:
            params["language"] = self._language_hint
        started_at = time.perf_counter()
        try:
            # Native redirection during active transcription can deadlock Textual on
            # Windows. Keep runtime redirection off by default there.
            if os.name == "nt" and not _windows_native_redirect_enabled():
                result = model.transcribe(audio_f32, **params)
            else:
                with _safe_pywhispercpp_redirect_stdout(self._log_redirect_target):
                    with _safe_pywhispercpp_redirect_stderr(self._log_redirect_target):
                        result = model.transcribe(audio_f32, **params)
        except Exception as exc:
            raise RuntimeError(
                "Local whisper.cpp transcription failed. Verify the selected model file is valid "
                "and compatible with this build."
            ) from exc
        elapsed_seconds = time.perf_counter() - started_at
        if self._on_inference_seconds is not None:
            loop = self._loop
            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(self._notify_inference_seconds, elapsed_seconds)
                except RuntimeError:
                    self._notify_inference_seconds(elapsed_seconds)
            else:
                self._notify_inference_seconds(elapsed_seconds)
        return result

    def _notify_inference_seconds(self, elapsed_seconds: float) -> None:
        if self._on_inference_seconds is None:
            return
        try:
            self._on_inference_seconds(elapsed_seconds)
        except Exception:
            logger.warning("Local STT inference observer failed.", exc_info=True)

    def _map_segments(
        self,
        raw_segments: list[Any],
        *,
        user_id: int,
        username: str,
        utterance_started_at: float,
    ) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        for raw in raw_segments:
            text = str(getattr(raw, "text", "") or "").strip()
            if is_ignorable_transcript_text(text):
                continue
            start_offset = max(0.0, float(getattr(raw, "t0", 0) or 0) * _WHISPERCPP_TIMESTAMP_SECONDS)
            end_offset = max(start_offset, float(getattr(raw, "t1", 0) or 0) * _WHISPERCPP_TIMESTAMP_SECONDS)
            segments.append(
                TranscriptSegment(
                    user_id=user_id,
                    username=username,
                    text=text,
                    start_ts=utterance_started_at + start_offset,
                    end_ts=utterance_started_at + end_offset,
                    is_final=True,
                    language_code=self._segment_language_code,
                )
            )
        return segments

    async def validate_connectivity(self) -> None:
        """Fail fast when the local binding or model file is not usable."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        async with self._inference_lock:
            await asyncio.to_thread(self._ensure_model_loaded_sync)
        logger.info("Local whisper.cpp STT validation succeeded.")

    async def _recognize_segments(
        self,
        *,
        audio_bytes: bytes,
        user_id: int,
        username: str,
        utterance_started_at: float,
    ) -> list[TranscriptSegment]:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        audio_f32 = pcm16_bytes_to_float32(audio_bytes)
        if int(getattr(audio_f32, "size", 0)) <= 0:
            return []
        async with self._inference_lock:
            raw_segments = await asyncio.to_thread(self._transcribe_sync, audio_f32)
        return self._map_segments(
            list(raw_segments),
            user_id=user_id,
            username=username,
            utterance_started_at=utterance_started_at,
        )

    async def stream_recognize(
        self,
        audio_stream: AsyncIterator[bytes],
        user_id: int,
        username: str,
        sample_rate_hz: int = _WHISPERCPP_SAMPLE_RATE_HZ,
        utterance_started_at: float | None = None,
    ) -> AsyncIterator[TranscriptSegment]:
        del sample_rate_hz
        utterance_start = time.time() if utterance_started_at is None else utterance_started_at
        chunks: list[bytes] = []
        async for chunk in audio_stream:
            if chunk:
                chunks.append(chunk)
        if not chunks:
            return
        segments = await self._recognize_segments(
            audio_bytes=b"".join(chunks),
            user_id=user_id,
            username=username,
            utterance_started_at=utterance_start,
        )
        for segment in segments:
            yield segment

    async def recognize_batch(
        self,
        audio_bytes: bytes,
        user_id: int,
        username: str,
        sample_rate_hz: int = _WHISPERCPP_SAMPLE_RATE_HZ,
        utterance_started_at: float | None = None,
    ) -> Optional[TranscriptSegment]:
        del sample_rate_hz
        segments = await self._recognize_segments(
            audio_bytes=audio_bytes,
            user_id=user_id,
            username=username,
            utterance_started_at=time.time() if utterance_started_at is None else utterance_started_at,
        )
        return segments[-1] if segments else None
