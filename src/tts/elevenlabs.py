"""ElevenLabs text-to-speech client."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, AsyncIterator, Optional

import httpx

from ..models import Persona
from ..storage.settings import SettingsStore

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_ID = "eleven_multilingual_v2"
_ELEVEN_BASE_URL = "https://api.elevenlabs.io"


def resolve_elevenlabs_api_key_from_env() -> Optional[str]:
    """
    Read API key from ELEVENLABS_API_KEY or ELEVEN_API_KEY (common SDK alias).

    Strips whitespace and simple surrounding quotes often copied from docs.
    """
    raw = os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVEN_API_KEY") or ""
    key = raw.strip().strip('"').strip("'")
    return key if key else None


def resolve_elevenlabs_api_key(settings_store: SettingsStore | None = None) -> Optional[str]:
    """Resolve ElevenLabs auth from TUI settings first, then environment."""
    if settings_store is not None:
        key = settings_store.resolve_api_secret(
            "elevenlabs_api_key",
            "ELEVENLABS_API_KEY",
            "ELEVEN_API_KEY",
        )
        if key:
            return key
    return resolve_elevenlabs_api_key_from_env()


async def _raise_for_status_or_tts_auth_hint(response: httpx.Response) -> None:
    """Raise on HTTP errors; attach a clearer message for ElevenLabs auth failures."""
    if response.is_success:
        return
    try:
        await response.aread()
    except Exception:
        pass
    detail = ""
    try:
        detail = (response.text or "").strip()[:400]
    except Exception:
        pass
    if response.status_code in (401, 403):
        raise RuntimeError(
            "ElevenLabs API rejected this API key (HTTP "
            f"{response.status_code}). Set the ElevenLabs key in the TUI API config or "
            "ELEVENLABS_API_KEY / ELEVEN_API_KEY in `.env` to a valid key from "
            "https://elevenlabs.io/app/settings/api-keys - no quotes, no leading/trailing "
            "spaces. Regenerate the key if it was rotated."
            + (f" Response: {detail!r}" if detail else "")
        ) from None
    response.raise_for_status()


class ElevenLabsTTSClient:
    """
    ElevenLabs streaming text-to-speech client.

    Generates audio via streaming endpoint, supports MP3 output.
    Tracks per-session voice generation duration.

    Phase 5: ElevenLabs TTS + playback
    """

    def __init__(
        self,
        api_key: str,
        *,
        model_id: Optional[str] = None,
        http_transport: Optional[Any] = None,
    ) -> None:
        """
        Initialize ElevenLabs client.

        Args:
            api_key: ElevenLabs API key (used as xi-api-key header)
            model_id: TTS model id; falls back to ELEVENLABS_MODEL_ID env or default
            http_transport: Optional httpx transport (for tests)
        """
        self.api_key = api_key.strip().strip('"').strip("'")
        resolved = (model_id or os.getenv("ELEVENLABS_MODEL_ID") or "").strip()
        self.model_id = resolved or _DEFAULT_MODEL_ID
        self._http_transport = http_transport
        self.total_seconds_generated = 0.0
        self.total_characters_synthesized = 0
        logger.info("ElevenLabsTTSClient initialized (model_id=%s)", self.model_id)

    def _tts_url(self, voice_id: str) -> str:
        return f"{_ELEVEN_BASE_URL}/v1/text-to-speech/{voice_id}/stream"

    async def _iter_tts_audio_chunks(
        self,
        text: str,
        persona: Persona,
        output_format: str,
    ) -> AsyncIterator[bytes]:
        """POST stream endpoint and yield response body chunks."""
        url = self._tts_url(persona.elevenlabs_voice_id)
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        params = {"output_format": output_format}
        payload = {"text": text, "model_id": self.model_id}
        timeout = httpx.Timeout(120.0, connect=30.0)
        logger.debug("Streaming TTS for persona '%s'", persona.display_name)
        async with httpx.AsyncClient(timeout=timeout, transport=self._http_transport) as client:
            async with client.stream(
                "POST",
                url,
                params=params,
                json=payload,
                headers=headers,
            ) as response:
                await _raise_for_status_or_tts_auth_hint(response)
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk

    async def stream_synthesize(
        self,
        text: str,
        persona: Persona,
        output_format: str = "mp3_44100_128",
    ) -> AsyncIterator[bytes]:
        """Stream synthesized audio as it is generated (same HTTP stream as ``synthesize_to_file``)."""
        async for chunk in self._iter_tts_audio_chunks(text, persona, output_format):
            yield chunk

    async def synthesize_to_file(
        self, text: str, persona: Persona, output_format: str = "mp3_44100_128"
    ) -> str:
        """
        Synthesize audio and save to temporary file.

        Args:
            text: Text to synthesize
            persona: Persona configuration
            output_format: Output format query value for ElevenLabs

        Returns:
            Path to temporary MP3 file
        """
        logger.debug("TTS synthesis to file (%s chars)", len(text))
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            temp_path = tmp.name

        try:
            with open(temp_path, "wb") as outfile:
                async for chunk in self._iter_tts_audio_chunks(text, persona, output_format):
                    outfile.write(chunk)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

        return temp_path

    def record_tts_duration(self, duration_seconds: float) -> None:
        """Record voice generation duration for session tracking."""
        self.total_seconds_generated += duration_seconds
        logger.debug(
            "TTS duration recorded: +%.1fs (total: %.1fs)",
            duration_seconds,
            self.total_seconds_generated,
        )

    def record_tts_characters(self, character_count: int) -> None:
        """Record characters sent to TTS (ElevenLabs usage unit)."""
        if character_count > 0:
            self.total_characters_synthesized += int(character_count)
            logger.debug(
                "TTS characters recorded: +%d (total: %d)",
                character_count,
                self.total_characters_synthesized,
            )

    async def get_account_usage(self) -> Optional[dict]:
        """Get account-level character/voice usage statistics."""
        logger.debug("Fetching ElevenLabs account usage stats...")
        return None
