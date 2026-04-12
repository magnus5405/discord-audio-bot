"""Helpers for fetching available Gemini text-generation models for the settings UI."""

from __future__ import annotations

import logging

from google import genai

logger = logging.getLogger(__name__)

DEFAULT_TEXT_MODEL_IDS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview"
)

_EXCLUDED_MODEL_TOKENS = (
    "embedding",
    "imagen",
    "veo",
    "lyria",
    "tts",
    "transcribe",
)


def _normalize_model_id(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    return raw.split("/")[-1]


def _is_text_generation_model(model_id: str, supported_actions: list[str] | None) -> bool:
    mid = model_id.lower()
    if not mid.startswith("gemini"):
        return False
    if any(token in mid for token in _EXCLUDED_MODEL_TOKENS):
        return False
    actions = {action.lower() for action in (supported_actions or [])}
    return "generatecontent" in actions


async def list_text_generation_model_ids(api_key: str | None) -> list[str]:
    """Return available Gemini text-generation models, falling back to sensible defaults."""
    if not api_key:
        return list(DEFAULT_TEXT_MODEL_IDS)

    client = genai.Client(api_key=api_key)
    try:
        pager = await client.aio.models.list(config={"page_size": 100, "query_base": True})
        model_ids: list[str] = []
        async for model in pager:
            model_id = _normalize_model_id(getattr(model, "name", None))
            if not _is_text_generation_model(model_id, getattr(model, "supported_actions", None)):
                continue
            if model_id not in model_ids:
                model_ids.append(model_id)
        if model_ids:
            return model_ids
    except Exception:
        logger.exception("Failed to fetch Gemini model list for settings UI")
    finally:
        try:
            await client.aio.aclose()
        except Exception:
            logger.debug("Ignoring async Gemini client close error", exc_info=True)
        try:
            client.close()
        except Exception:
            logger.debug("Ignoring sync Gemini client close error", exc_info=True)

    return list(DEFAULT_TEXT_MODEL_IDS)
