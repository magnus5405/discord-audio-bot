"""Google Cloud Speech-to-Text v2 streaming transcription."""

from __future__ import annotations

import json
import logging
import os
import time
from array import array
from collections.abc import AsyncIterator
from typing import Callable, Optional, Protocol, runtime_checkable

import google.auth
from google.api_core import exceptions as google_exceptions
from google.api_core.client_options import ClientOptions
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import speech_v2
from google.oauth2 import service_account

from ..models import TranscriptSegment
from ..storage.settings import DEFAULT_STT_LANGUAGE_CODE
from .preprocessing import get_audio_duration
from .stt_v1 import GoogleSTTV1Client
from .whispercpp import WHISPERCPP_BACKEND_ID, WhisperCppSTTClient

logger = logging.getLogger(__name__)

# Speech v2 requires a non-empty model on RecognitionConfig for the implicit recognizer (_).
# Regional gRPC host must match the recognizer path: ``{location}-speech.googleapis.com``.
# See https://stackoverflow.com/a/77116432
#
# Chirp 3 is only offered in multi-regions ``us`` and ``eu`` (not single regions like
# europe-west4). Chirp 2 is offered in us-central1, europe-west4, asia-southeast1.
# https://cloud.google.com/speech-to-text/v2/docs/chirp-model
# https://cloud.google.com/speech-to-text/v2/docs/chirp_2-model
_DEFAULT_STT_V2_MODEL = "chirp_3"
# Chirp 3 rejects >2 language hints on StreamingRecognize / Recognize (generic INVALID_ARGUMENT).
_CHIRP3_MAX_LANGUAGE_CODES = 2


@runtime_checkable
class STTClient(Protocol):
    """Provider-neutral Speech-to-Text client contract."""

    async def validate_connectivity(self) -> None: ...

    async def stream_recognize(
        self,
        audio_stream: AsyncIterator[bytes],
        user_id: int,
        username: str,
        sample_rate_hz: int = 48000,
        utterance_started_at: float | None = None,
    ) -> AsyncIterator[TranscriptSegment]: ...

    async def recognize_batch(
        self,
        audio_bytes: bytes,
        user_id: int,
        username: str,
        sample_rate_hz: int = 48000,
        utterance_started_at: float | None = None,
    ) -> Optional[TranscriptSegment]: ...


class GoogleSTTV2Client:
    """
    Streaming Speech-to-Text client using Google Cloud Speech-to-Text v2.

    Uses gRPC streaming for real-time transcription. See
    https://cloud.google.com/speech-to-text/docs/v2
    """

    def __init__(
        self,
        primary_language: str = DEFAULT_STT_LANGUAGE_CODE,
        alternative_languages: Optional[list[str]] = None,
        api_key: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
        model: str | None = None,
        credentials_path: str | None = None,
        client: speech_v2.SpeechAsyncClient | None = None,
    ) -> None:
        """
        Initialize STT client.

        Args:
            primary_language: Primary language code (BCP-47, e.g. ``en-US``)
            alternative_languages: List of alternative language codes
            api_key: Optional API key (ignored whenever ``GOOGLE_APPLICATION_CREDENTIALS`` is
                set, including values passed from ``SettingsStore`` / the constructor).
            project_id: GCP project id for the v2 recognizer path. Values that look like
                Google AI Studio ids (``gen-lang-client-*``) are skipped in favour of a
                normal Cloud ``project_id`` from env or the service account JSON.
            location: GCP location for the recognizer (``GOOGLE_STT_LOCATION``, or a default
                derived from ``GOOGLE_STT_MODEL`` when unset: ``eu`` for ``chirp_3``, ``europe-west4``
                for ``chirp_2``, else ``global``). Chirp 3 requires ``us`` or ``eu`` per Google docs.
            model: v2 transcription model id (e.g. ``chirp_3``, ``chirp_2``). Reads
                ``GOOGLE_STT_MODEL`` when omitted; defaults to ``chirp_3`` if unset (required by the API).
            credentials_path: Optional path to a Google service-account JSON file.
        """
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        self.primary_language = primary_language
        self.alternative_languages = alternative_languages or ["en-US"]
        self._chirp3_lang_trim_log_done = False
        self._explicit_credentials_path = (
            self._application_credentials_path(credentials_path)
            if credentials_path not in (None, "")
            else None
        )
        self.credentials_path = self._explicit_credentials_path or self._application_credentials_path()
        self.api_key = self._resolve_api_key(api_key, self.credentials_path)
        self.project_id = self._resolve_project_id(project_id, self.credentials_path)
        self.model = (
            (model if model is not None else os.getenv("GOOGLE_STT_MODEL") or "").strip()
            or _DEFAULT_STT_V2_MODEL
        )
        explicit_location = (location or os.getenv("GOOGLE_STT_LOCATION") or "").strip()
        self.location = (
            explicit_location or self._default_location_for_model(self.model)
        ).strip()
        mod_l, loc_l = self.model.lower(), self.location.lower()
        if mod_l.startswith("chirp_3") and loc_l not in ("us", "eu"):
            logger.warning(
                "Speech v2 model %r is only available in locations 'us' or 'eu' (multi-region); "
                "current location is %r. Set GOOGLE_STT_LOCATION=us or GOOGLE_STT_LOCATION=eu.",
                self.model,
                self.location,
            )
        elif loc_l == "global" and mod_l.startswith("chirp"):
            logger.warning(
                "Speech v2 model %r is not available in location=global; set "
                "GOOGLE_STT_LOCATION (e.g. eu or us for chirp_3, europe-west4 for chirp_2).",
                self.model,
            )
        self.recognizer = (
            f"projects/{self.project_id}/locations/{self.location}/recognizers/_"
        )
        if client is None:
            self._ensure_credentials()
        if self.project_id.startswith("gen-lang-client-"):
            logger.warning(
                "GOOGLE_STT_PROJECT_ID looks like a Google AI Studio id (gen-lang-client-*). "
                "Speech-to-Text v2 needs your Google *Cloud* project id from "
                "https://console.cloud.google.com (IAM & Admin → Settings), with the "
                "Cloud Speech-to-Text API enabled and credentials created there."
            )
        self.client = client or self._build_client()
        auth_mode = (
            "API key"
            if self.api_key
            else "Service account JSON"
            if self._explicit_credentials_path
            else "Application Default Credentials"
        )
        logger.info(
            "GoogleSTTV2Client (v2) initialized: %s + %s (project=%s location=%s model=%s auth=%s)",
            primary_language,
            self.alternative_languages,
            self.project_id,
            self.location,
            self.model,
            auth_mode,
        )

    @staticmethod
    def _default_location_for_model(model_id: str) -> str:
        """When ``GOOGLE_STT_LOCATION`` is unset, pick a location known to host the model."""
        m = (model_id or "").strip().lower()
        if m.startswith("chirp_3"):
            return "eu"
        if m.startswith("chirp_2"):
            return "europe-west4"
        return "global"

    @staticmethod
    def _application_credentials_path(explicit_path: str | None = None) -> str | None:
        raw = explicit_path if explicit_path not in (None, "") else os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not raw or not str(raw).strip():
            return None
        path = str(raw).strip().strip('"').strip("'")
        return path or None

    @staticmethod
    def _project_id_from_credentials_file(credentials_path: str | None = None) -> str | None:
        path = GoogleSTTV2Client._application_credentials_path(credentials_path)
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        pid = data.get("project_id")
        return pid if isinstance(pid, str) and pid.strip() else None

    @staticmethod
    def _resolve_api_key(api_key: str | None, credentials_path: str | None = None) -> str | None:
        """Service account file wins over API key (env, settings, or constructor)."""
        if GoogleSTTV2Client._application_credentials_path(credentials_path):
            if api_key not in (None, "") or os.getenv("GOOGLE_STT_API_KEY") not in (None, ""):
                logger.info(
                    "Speech v2: GOOGLE_APPLICATION_CREDENTIALS is set; ignoring API key for STT "
                    "(environment, settings, or constructor)."
                )
            return None
        if api_key not in (None, ""):
            return api_key
        env = os.getenv("GOOGLE_STT_API_KEY")
        return env if env not in (None, "") else None

    @staticmethod
    def _looks_like_ai_studio_project_id(project: str) -> bool:
        return bool(project and project.strip().startswith("gen-lang-client-"))

    def _ensure_credentials(self) -> None:
        if self.api_key or self.credentials_path:
            return
        try:
            google.auth.default()
        except DefaultCredentialsError as exc:
            raise ValueError(
                "No Speech credentials: set GOOGLE_APPLICATION_CREDENTIALS to a service "
                "account JSON (recommended) with role roles/speech.client on a project "
                "where Cloud Speech-to-Text API is enabled, or set GOOGLE_STT_API_KEY to "
                "an API key from APIs & Credentials on that same project, or run "
                "gcloud auth application-default login."
            ) from exc

    @classmethod
    def _resolve_project_id(
        cls,
        project_id: str | None,
        credentials_path: str | None = None,
    ) -> str:
        """Prefer a real Cloud project id; skip ``gen-lang-client-*`` when a better id exists."""
        file_pid = cls._project_id_from_credentials_file(credentials_path)
        candidates = [
            project_id,
            os.getenv("GOOGLE_STT_PROJECT_ID"),
            os.getenv("GOOGLE_CLOUD_PROJECT"),
            os.getenv("GCLOUD_PROJECT"),
        ]
        for raw in candidates:
            if raw is None or not str(raw).strip():
                continue
            s = str(raw).strip()
            if cls._looks_like_ai_studio_project_id(s):
                continue
            return s
        if file_pid and not cls._looks_like_ai_studio_project_id(file_pid):
            return file_pid.strip()
        if file_pid:
            return file_pid.strip()
        for raw in candidates:
            if raw is not None and str(raw).strip():
                return str(raw).strip()
        raise ValueError(
            "Speech-to-Text v2 requires a Google Cloud project id for the recognizer "
            "resource path. Set GOOGLE_STT_PROJECT_ID or GOOGLE_CLOUD_PROJECT, or put "
            "project_id in your service account JSON and set GOOGLE_APPLICATION_CREDENTIALS, "
            "or pass project_id= explicitly."
        )

    def _load_service_account_credentials(self):
        """Load explicit service-account credentials when a settings path is provided."""
        if not self._explicit_credentials_path:
            return None
        return service_account.Credentials.from_service_account_file(self._explicit_credentials_path)

    @staticmethod
    def _speech_regional_api_endpoint(location: str) -> str | None:
        loc = (location or "").strip().lower()
        if not loc or loc == "global":
            return None
        return f"{loc}-speech.googleapis.com"

    def _build_client(self) -> speech_v2.SpeechAsyncClient:
        endpoint = self._speech_regional_api_endpoint(self.location)
        opts: dict[str, str] = {}
        if self.api_key:
            opts["api_key"] = self.api_key
        if endpoint:
            opts["api_endpoint"] = endpoint
        credentials = self._load_service_account_credentials()
        if opts:
            if credentials is not None:
                return speech_v2.SpeechAsyncClient(
                    credentials=credentials,
                    client_options=ClientOptions(**opts),
                )
            return speech_v2.SpeechAsyncClient(client_options=ClientOptions(**opts))
        if credentials is not None:
            return speech_v2.SpeechAsyncClient(credentials=credentials)
        return speech_v2.SpeechAsyncClient()

    def _resolve_language_codes_for_request(self) -> list[str]:
        """Ordered, de-duplicated BCP-47 tags; Chirp 3 caps how many may be sent per request."""
        ordered: list[str] = []
        for code in (self.primary_language, *self.alternative_languages):
            c = (code or "").strip()
            if not c or c in ordered:
                continue
            ordered.append(c)
        if self.model.lower().startswith("chirp_3") and len(ordered) > _CHIRP3_MAX_LANGUAGE_CODES:
            kept = ordered[:_CHIRP3_MAX_LANGUAGE_CODES]
            dropped = ordered[_CHIRP3_MAX_LANGUAGE_CODES:]
            if not self._chirp3_lang_trim_log_done:
                self._chirp3_lang_trim_log_done = True
                logger.info(
                    "Speech v2 chirp_3 allows at most %d language_codes per request; using %s (omitted: %s)",
                    _CHIRP3_MAX_LANGUAGE_CODES,
                    kept,
                    dropped,
                )
            return kept
        return ordered

    def _build_recognition_config(self, sample_rate_hz: int) -> speech_v2.RecognitionConfig:
        language_codes = self._resolve_language_codes_for_request()
        features = speech_v2.RecognitionFeatures(enable_automatic_punctuation=True)
        explicit = speech_v2.ExplicitDecodingConfig(
            encoding=speech_v2.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate_hz,
            audio_channel_count=1,
        )
        return speech_v2.RecognitionConfig(
            explicit_decoding_config=explicit,
            language_codes=language_codes,
            features=features,
            model=self.model,
        )

    def _build_probe_recognition_config(self, sample_rate_hz: int) -> speech_v2.RecognitionConfig:
        """Minimal Recognize config for connectivity checks (matches Chirp 3 sync doc shape)."""
        explicit = speech_v2.ExplicitDecodingConfig(
            encoding=speech_v2.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate_hz,
            audio_channel_count=1,
        )
        return speech_v2.RecognitionConfig(
            explicit_decoding_config=explicit,
            language_codes=[self.primary_language],
            model=self.model,
        )

    def _build_streaming_config(self, sample_rate_hz: int) -> speech_v2.StreamingRecognitionConfig:
        return speech_v2.StreamingRecognitionConfig(
            config=self._build_recognition_config(sample_rate_hz),
            streaming_features=speech_v2.StreamingRecognitionFeatures(interim_results=False),
        )

    async def validate_connectivity(self) -> None:
        """Fail fast if STT credentials or API access are not usable."""
        # Use ~1s of PCM: very short clips can yield generic INVALID_ARGUMENT on Chirp; the
        # official Recognize samples omit RecognitionFeatures and use a single language hint.
        probe_rate_hz = 16000
        silence_bytes = b"\x00\x00" * probe_rate_hz
        try:
            await self.client.recognize(
                recognizer=self.recognizer,
                config=self._build_probe_recognition_config(probe_rate_hz),
                content=silence_bytes,
            )
        except google_exceptions.PermissionDenied as exc:
            raise RuntimeError(
                "Speech-to-Text v2 denied access (speech.recognizers.recognize). "
                "Use the Cloud project id from console.cloud.google.com as GOOGLE_STT_PROJECT_ID "
                "(or omit it and use a service account JSON whose project_id matches that Cloud project). "
                "Enable 'Cloud Speech-to-Text API' on that project. The calling principal needs "
                "roles/speech.client (or equivalent); 'Cloud Speech-to-Text Service Agent' is a "
                "Google-managed service account, not the role for your own service account."
            ) from exc
        except google_exceptions.InvalidArgument as exc:
            raise RuntimeError(
                "Speech-to-Text v2 rejected the connectivity probe (INVALID_ARGUMENT). "
                "Confirm GOOGLE_STT_LOCATION matches the model (chirp_3 → us or eu multi-region) "
                "and the gRPC host is {loc}-speech.googleapis.com. Details: {details}".format(
                    loc=self.location,
                    details=exc.message or str(exc),
                )
            ) from exc
        logger.info("Google STT (v2) connectivity check succeeded.")

    @staticmethod
    def _result_end_seconds(result: object) -> float:
        """End offset from a streaming or batch result (v2 uses ``result_end_offset``)."""
        duration = getattr(result, "result_end_offset", None) or getattr(result, "result_end_time", None)
        if duration is None:
            return 0.0

        seconds = getattr(duration, "seconds", 0) or 0
        nanos = getattr(duration, "nanos", 0) or 0
        return float(seconds) + (float(nanos) / 1_000_000_000.0)

    def _build_segment(
        self,
        *,
        user_id: int,
        username: str,
        transcript_text: str,
        utterance_start: float,
        start_offset: float,
        end_offset: float,
        language_code: str | None,
    ) -> TranscriptSegment:
        if end_offset <= start_offset:
            end_offset = start_offset

        return TranscriptSegment(
            user_id=user_id,
            username=username,
            text=transcript_text,
            start_ts=utterance_start + start_offset,
            end_ts=utterance_start + end_offset,
            is_final=True,
            language_code=language_code,
        )

    async def _recognize_with_batch(
        self,
        *,
        audio_bytes: bytes,
        user_id: int,
        username: str,
        sample_rate_hz: int,
        utterance_started_at: float,
    ) -> list[TranscriptSegment]:
        if not audio_bytes:
            return []

        response = await self.client.recognize(
            recognizer=self.recognizer,
            config=self._build_recognition_config(sample_rate_hz),
            content=audio_bytes,
        )

        audio_duration_seconds = get_audio_duration(
            audio_bytes,
            sample_rate=sample_rate_hz,
            channels=1,
        )
        previous_end_offset = 0.0
        segments: list[TranscriptSegment] = []

        for result in getattr(response, "results", []):
            alternatives = getattr(result, "alternatives", [])
            if not alternatives:
                continue

            transcript_text = (alternatives[0].transcript or "").strip()
            if not transcript_text:
                continue

            end_offset = self._result_end_seconds(result)
            if end_offset <= 0.0:
                end_offset = audio_duration_seconds

            segment = self._build_segment(
                user_id=user_id,
                username=username,
                transcript_text=transcript_text,
                utterance_start=utterance_started_at,
                start_offset=previous_end_offset,
                end_offset=end_offset,
                language_code=getattr(result, "language_code", None) or None,
            )
            previous_end_offset = max(previous_end_offset, end_offset)
            segments.append(segment)

        return segments

    async def stream_recognize(
        self,
        audio_stream: AsyncIterator[bytes],
        user_id: int,
        username: str,
        sample_rate_hz: int = 48000,
        utterance_started_at: float | None = None,
    ) -> AsyncIterator[TranscriptSegment]:
        """
        Stream audio and yield transcript segments as they arrive.

        Args:
            audio_stream: Async iterator of PCM audio bytes
            user_id: Discord user ID
            username: Discord username
            sample_rate_hz: Sample rate of audio

        Yields:
            TranscriptSegment as final results arrive
        """
        logger.debug("Stream recognition started for %s (%s)", username, user_id)
        utterance_start = time.time() if utterance_started_at is None else utterance_started_at
        previous_end_offset = 0.0
        streaming_config = self._build_streaming_config(sample_rate_hz)
        audio_chunks: list[bytes] = []
        audio_chunk_count = 0
        total_audio_bytes = 0
        final_segment_count = 0

        async def requests() -> AsyncIterator[speech_v2.StreamingRecognizeRequest]:
            nonlocal audio_chunk_count, total_audio_bytes
            yield speech_v2.StreamingRecognizeRequest(
                recognizer=self.recognizer,
                streaming_config=streaming_config,
            )
            async for audio_chunk in audio_stream:
                if audio_chunk:
                    audio_chunks.append(audio_chunk)
                    audio_chunk_count += 1
                    total_audio_bytes += len(audio_chunk)
                    yield speech_v2.StreamingRecognizeRequest(audio=audio_chunk)

        responses = await self.client.streaming_recognize(requests=requests())
        async for response in responses:
            for result in getattr(response, "results", []):
                if not getattr(result, "is_final", False):
                    continue

                alternatives = getattr(result, "alternatives", [])
                if not alternatives:
                    continue

                transcript_text = (alternatives[0].transcript or "").strip()
                if not transcript_text:
                    continue

                end_offset = self._result_end_seconds(result)
                segment = self._build_segment(
                    user_id=user_id,
                    username=username,
                    transcript_text=transcript_text,
                    utterance_start=utterance_start,
                    start_offset=previous_end_offset,
                    end_offset=end_offset,
                    language_code=getattr(result, "language_code", None) or None,
                )
                previous_end_offset = max(previous_end_offset, end_offset)
                final_segment_count += 1
                yield segment

        if final_segment_count > 0 or total_audio_bytes <= 0:
            return

        audio_bytes = b"".join(audio_chunks)
        audio_duration_seconds = get_audio_duration(
            audio_bytes,
            sample_rate=sample_rate_hz,
            channels=1,
        )
        rms_level = 0.0
        peak_level = 0
        if audio_bytes:
            samples = array("h")
            samples.frombytes(audio_bytes[: len(audio_bytes) - (len(audio_bytes) % 2)])
            if samples:
                peak_level = max(abs(sample) for sample in samples)
                rms_level = (
                    sum(float(sample) * float(sample) for sample in samples) / float(len(samples))
                ) ** 0.5
        logger.warning(
            (
                "Streaming STT returned no final results for %s (%s) after %s chunks "
                "(%.2fs audio, rms=%.1f, peak=%s). Retrying with batch recognition."
            ),
            username,
            user_id,
            audio_chunk_count,
            audio_duration_seconds,
            rms_level,
            peak_level,
        )

        fallback_segments = await self._recognize_with_batch(
            audio_bytes=audio_bytes,
            user_id=user_id,
            username=username,
            sample_rate_hz=sample_rate_hz,
            utterance_started_at=utterance_start,
        )
        if fallback_segments:
            logger.info(
                "Batch STT fallback recovered %s final segment(s) for %s (%s).",
                len(fallback_segments),
                username,
                user_id,
            )
            for segment in fallback_segments:
                yield segment
            return

        logger.warning(
            "No transcription results were produced for %s (%s) after %.2fs of audio.",
            username,
            user_id,
            audio_duration_seconds,
        )

    async def recognize_batch(
        self,
        audio_bytes: bytes,
        user_id: int,
        username: str,
        sample_rate_hz: int = 48000,
        utterance_started_at: float | None = None,
    ) -> Optional[TranscriptSegment]:
        """
        Recognize audio from a batch/chunk.

        Args:
            audio_bytes: PCM audio data
            user_id: Discord user ID
            username: Discord username
            sample_rate_hz: Sample rate

        Returns:
            TranscriptSegment if recognized, None otherwise
        """
        logger.debug("Batch recognition for %s (%s)", username, user_id)
        segments = await self._recognize_with_batch(
            audio_bytes=audio_bytes,
            user_id=user_id,
            username=username,
            sample_rate_hz=sample_rate_hz,
            utterance_started_at=(time.time() if utterance_started_at is None else utterance_started_at),
        )
        return segments[-1] if segments else None


def _create_google_stt_client(
    primary_language: str = DEFAULT_STT_LANGUAGE_CODE,
    alternative_languages: Optional[list[str]] = None,
    api_key: str | None = None,
    project_id: str | None = None,
    location: str | None = None,
    model: str | None = None,
    credentials_path: str | None = None,
    client: speech_v2.SpeechAsyncClient | None = None,
    speech_backend: str | None = None,
) -> GoogleSTTV2Client | GoogleSTTV1Client:
    """Pick v1 or v2: ``speech_backend`` / env, else v1 for AI Studio ids when an API key exists."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    if client is not None:
        return GoogleSTTV2Client(
            primary_language=primary_language,
            alternative_languages=alternative_languages,
            api_key=api_key,
            project_id=project_id,
            location=location,
            model=model,
            credentials_path=credentials_path,
            client=client,
        )
    raw_api = (api_key if api_key not in (None, "") else None) or (
        (os.getenv("GOOGLE_STT_API_KEY") or "").strip() or None
    )
    credentials_path = GoogleSTTV2Client._application_credentials_path(credentials_path)
    backend = (speech_backend or os.getenv("GOOGLE_STT_SPEECH_BACKEND") or "").strip().lower()
    if backend in ("v1", "1", "legacy"):
        if not raw_api:
            raise ValueError(
                "GOOGLE_STT_SPEECH_BACKEND=v1 requires GOOGLE_STT_API_KEY (or api_key from settings)."
            )
        return GoogleSTTV1Client(
            primary_language=primary_language,
            alternative_languages=alternative_languages,
            api_key=raw_api,
        )
    if backend in ("v2", "2"):
        if project_id is not None and GoogleSTTV2Client._looks_like_ai_studio_project_id(
            str(project_id).strip()
        ):
            raise ValueError(
                "Speech-to-Text v2 cannot use Google AI Studio project ids (gen-lang-client-*). "
                "Use a Google Cloud project id from https://console.cloud.google.com, or remove "
                "GOOGLE_STT_SPEECH_BACKEND=v2 / clear the Speech backend field in settings to allow "
                "automatic legacy v1 with GOOGLE_STT_API_KEY. "
                "Check .env spells GOOGLE_STT_API_KEY correctly (not OOGLE_STT_API_KEY)."
            )
        resolved_project = GoogleSTTV2Client._resolve_project_id(project_id, credentials_path)
        if GoogleSTTV2Client._looks_like_ai_studio_project_id(resolved_project):
            raise ValueError(
                "Speech-to-Text v2 cannot use Google AI Studio project ids (gen-lang-client-*). "
                "Use a Google Cloud project id from https://console.cloud.google.com, or remove "
                "GOOGLE_STT_SPEECH_BACKEND=v2 / clear the Speech backend field in settings to allow "
                "automatic legacy v1 with GOOGLE_STT_API_KEY. "
                "Check .env spells GOOGLE_STT_API_KEY correctly (not OOGLE_STT_API_KEY)."
            )
        return GoogleSTTV2Client(
            primary_language=primary_language,
            alternative_languages=alternative_languages,
            api_key=api_key,
            project_id=project_id,
            location=location,
            model=model,
            credentials_path=credentials_path,
            client=None,
        )
    try:
        resolved_project = GoogleSTTV2Client._resolve_project_id(project_id, credentials_path)
    except ValueError:
        if raw_api and not credentials_path:
            logger.info(
                "Speech: no STT v2 project or credentials configured; using Speech-to-Text v1 with API key."
            )
            return GoogleSTTV1Client(
                primary_language=primary_language,
                alternative_languages=alternative_languages,
                api_key=raw_api,
            )
        raise
    if GoogleSTTV2Client._looks_like_ai_studio_project_id(resolved_project) and raw_api:
        logger.info(
            "Speech: project id looks like Google AI Studio (gen-lang-client-*); "
            "using Speech-to-Text v1 with API key. For v2, set GOOGLE_STT_PROJECT_ID to a "
            "Google Cloud project from https://console.cloud.google.com (IAM → Settings)."
        )
        return GoogleSTTV1Client(
            primary_language=primary_language,
            alternative_languages=alternative_languages,
            api_key=raw_api,
        )
    if GoogleSTTV2Client._looks_like_ai_studio_project_id(resolved_project) and not raw_api:
        raise ValueError(
            "Speech-to-Text v2 cannot use Google AI Studio project ids (gen-lang-client-*). "
            "Set GOOGLE_STT_API_KEY to use legacy Speech v1 automatically, or set GOOGLE_STT_PROJECT_ID "
            "to your Google Cloud console project id with Cloud Speech-to-Text API enabled, "
            "or use a Cloud service account (GOOGLE_APPLICATION_CREDENTIALS) with roles/speech.client."
        )
    return GoogleSTTV2Client(
        primary_language=primary_language,
        alternative_languages=alternative_languages,
        api_key=api_key,
        project_id=project_id,
        location=location,
        model=model,
        credentials_path=credentials_path,
        client=None,
    )


def create_stt_client(
    primary_language: str = DEFAULT_STT_LANGUAGE_CODE,
    alternative_languages: Optional[list[str]] = None,
    provider: str | None = None,
    api_key: str | None = None,
    project_id: str | None = None,
    location: str | None = None,
    model: str | None = None,
    credentials_path: str | None = None,
    client: speech_v2.SpeechAsyncClient | None = None,
    speech_backend: str | None = None,
    local_backend: str | None = None,
    local_model: str | None = None,
    local_models_dir: str | None = None,
    on_inference_seconds: Callable[[float], None] | None = None,
) -> STTClient:
    """Provider-aware STT factory for Google v1/v2 and local whisper.cpp."""
    selected_provider = (provider or "").strip().lower() or "google"
    if selected_provider == "local":
        resolved_local_backend = (local_backend or "").strip().lower() or WHISPERCPP_BACKEND_ID
        if resolved_local_backend != WHISPERCPP_BACKEND_ID:
            raise ValueError(f"Unsupported local STT backend: {local_backend!r}")
        return WhisperCppSTTClient(
            primary_language=primary_language,
            alternative_languages=alternative_languages,
            local_backend=resolved_local_backend,
            local_model=local_model,
            local_models_dir=local_models_dir,
            on_inference_seconds=on_inference_seconds,
        )
    if selected_provider != "google":
        raise ValueError(f"Unsupported STT provider: {provider!r}")
    return _create_google_stt_client(
        primary_language=primary_language,
        alternative_languages=alternative_languages,
        api_key=api_key,
        project_id=project_id,
        location=location,
        model=model,
        credentials_path=credentials_path,
        client=client,
        speech_backend=speech_backend,
    )


def GoogleSTTClient(
    primary_language: str = DEFAULT_STT_LANGUAGE_CODE,
    alternative_languages: Optional[list[str]] = None,
    provider: str | None = None,
    api_key: str | None = None,
    project_id: str | None = None,
    location: str | None = None,
    model: str | None = None,
    credentials_path: str | None = None,
    client: speech_v2.SpeechAsyncClient | None = None,
    speech_backend: str | None = None,
    local_backend: str | None = None,
    local_model: str | None = None,
    local_models_dir: str | None = None,
    on_inference_seconds: Callable[[float], None] | None = None,
) -> STTClient:
    """Backward-compatible STT constructor now selecting Google or local providers."""
    return create_stt_client(
        primary_language=primary_language,
        alternative_languages=alternative_languages,
        provider=provider,
        api_key=api_key,
        project_id=project_id,
        location=location,
        model=model,
        credentials_path=credentials_path,
        client=client,
        speech_backend=speech_backend,
        local_backend=local_backend,
        local_model=local_model,
        local_models_dir=local_models_dir,
        on_inference_seconds=on_inference_seconds,
    )
