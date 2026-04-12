"""Resolve GenAI reply locale from settings/env and ``settings.json`` STT block."""

from __future__ import annotations

import logging
import os

from .settings import DEFAULT_STT_LANGUAGE_CODE, SettingsStore

logger = logging.getLogger(__name__)


def resolve_bot_reply_language_code(settings_store: SettingsStore) -> str:
    """BCP-47 locale for GenAI replies.

    Precedence: TUI ``reply_language`` in runtime config, then ``BOT_REPLY_LANGUAGE`` /
    ``BOT_LANGUAGE`` from the environment, then ``stt.language_code`` from settings.
    """
    stt = settings_store.get_stt_config()
    stt_code = (
        str(stt.get("language_code", DEFAULT_STT_LANGUAGE_CODE)).strip()
        or DEFAULT_STT_LANGUAGE_CODE
    )

    runtime = settings_store.get_runtime_config()
    settings_override = str(runtime.get("reply_language", "")).strip()
    if settings_override:
        logger.info("GenAI reply locale uses TUI settings override %s", settings_override)
        return settings_override

    env_override = os.getenv("BOT_REPLY_LANGUAGE", "").strip() or os.getenv("BOT_LANGUAGE", "").strip()
    if env_override:
        return env_override
    return stt_code
