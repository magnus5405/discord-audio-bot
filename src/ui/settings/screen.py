"""Modular settings screen composed from smaller page widgets."""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Select, TabbedContent, TabPane, TextArea

from src.main import (
    resolve_mention_window_seconds,
    resolve_reply_cooldown_seconds,
    resolve_reply_silence_seconds,
)
from src.models import Persona
from src.storage import DEFAULT_STT_LANGUAGE_CODE, SettingsStore

from .gemini_models import DEFAULT_TEXT_MODEL_IDS, list_text_generation_model_ids
from .layout import SETTINGS_SCREEN_CSS
from .page import (
    CharactersSettingsPage,
    CooldownsSettingsPage,
    DiscordSettingsPage,
    PricingSettingsPage,
    SpeechToTextSettingsPage,
    TextToSpeechSettingsPage,
)
from .page.characters import CharacterAliasRow

logger = logging.getLogger(__name__)

_DEFAULT_CHARACTER_MODEL = "gemini-2.5-flash"
_DEFAULT_STT_MODEL = "chirp_3"


class BotSettingsScreen(Screen[None]):
    """Edit characters, Discord config, Speech-to-Text, Text-to-Speech, and cooldowns."""

    CSS = SETTINGS_SCREEN_CSS

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss", "Close settings"),
        Binding("o", "ignore_settings_shortcut", show=False, priority=True),
    ]

    def __init__(self, store: SettingsStore) -> None:
        super().__init__()
        self.store = store
        self._current_character_id: str | None = None
        self._character_model_ids: list[str] = list(DEFAULT_TEXT_MODEL_IDS)

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="settings_root"):
            with TabbedContent(id="settings_tabs"):
                with TabPane("Characters", id="tab_characters"):
                    yield CharactersSettingsPage(self.store, self._character_model_options())
                with TabPane("Discord", id="tab_discord"):
                    yield DiscordSettingsPage()
                with TabPane("Speech-to-Text", id="tab_speech_to_text"):
                    yield SpeechToTextSettingsPage()
                with TabPane("Text-to-Speech", id="tab_text_to_speech"):
                    yield TextToSpeechSettingsPage()
                with TabPane("Cooldowns", id="tab_cooldowns"):
                    yield CooldownsSettingsPage()
                with TabPane("Pricing", id="tab_pricing"):
                    yield PricingSettingsPage()
            with Horizontal(id="settings_footer_row"):
                yield Button("Close settings", id="btn_close_settings", variant="warning")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_character_model_options()
        self._reload_character_pick()
        self._load_discord_fields()
        self._load_speech_to_text_fields()
        self._load_text_to_speech_fields()
        self._load_cooldowns_fields()
        self._load_pricing_fields()
        asyncio.create_task(self._refresh_character_model_options())

    def _character_options(self) -> list[tuple[str, str]]:
        personas = self.store.get_personalities()
        options = [(persona.display_name, persona.persona_id) for persona in personas]
        if not options:
            options = [("(add a character)", "")]
        return options

    def _select_text(self, field_id: str) -> str:
        value = self.query_one(field_id, Select).value
        if value in (None, Select.BLANK):
            return ""
        return str(value).strip()

    def _character_model_options(self, current_model: str | None = None) -> list[tuple[str, str]]:
        model_ids: list[str] = []
        for value in [current_model, *self._character_model_ids]:
            cleaned = str(value or "").strip()
            if cleaned and cleaned not in model_ids:
                model_ids.append(cleaned)
        if not model_ids:
            model_ids = [_DEFAULT_CHARACTER_MODEL]
        return [(model_id, model_id) for model_id in model_ids]

    def _apply_character_model_options(self, current_model: str | None = None) -> None:
        select = self.query_one("#character_model", Select)
        previous_value = self._select_text("#character_model")
        options = self._character_model_options(current_model or previous_value)
        select.set_options(options)
        selected_value = (current_model or previous_value or options[0][1]).strip()
        if any(value == selected_value for _, value in options):
            select.value = selected_value
        elif options:
            select.value = options[0][1]

    async def _refresh_character_model_options(self) -> None:
        try:
            api_key = self.store.resolve_api_secret("google_gemini_api_key", "GOOGLE_GEMINI_API_KEY")
            model_ids = await list_text_generation_model_ids(api_key)
        except Exception:
            logger.exception("Failed to refresh Gemini model options in settings UI")
            return
        if not model_ids:
            return
        self._character_model_ids = model_ids
        try:
            current_value = self._select_text("#character_model")
        except Exception:
            return
        self._apply_character_model_options(current_value or None)

    def _reload_character_pick(self) -> None:
        select = self.query_one("#character_pick", Select)
        options = self._character_options()
        select.set_options(options)

        selected_id: str | None = None
        if self._current_character_id and any(pid == self._current_character_id for _, pid in options):
            selected_id = self._current_character_id
        elif options and options[0][1]:
            selected_id = options[0][1]

        if selected_id:
            self._current_character_id = selected_id
            select.value = selected_id
            self._load_form_from_character(selected_id)

    def _character_by_id(self, character_id: str) -> Persona | None:
        for persona in self.store.get_personalities():
            if persona.persona_id == character_id:
                return persona
        return None

    def _load_form_from_character(self, character_id: str) -> None:
        persona = self._character_by_id(character_id)
        if persona is None:
            return
        self.query_one("#character_id", Input).value = persona.persona_id
        self._apply_character_model_options(persona.genai_model)
        self.query_one("#character_name", Input).value = persona.display_name
        self.query_one("#character_voice_id", Input).value = persona.elevenlabs_voice_id
        self.query_one("#character_instructions", TextArea).text = persona.system_instruction
        self._clear_character_aliases()
        for alias in persona.alternative_names:
            self._append_character_alias_row(alias)

    def _clear_character_aliases(self) -> None:
        container = self.query_one("#character_aliases", Vertical)
        for child in list(container.children):
            child.remove()

    def _append_character_alias_row(self, value: str = "") -> None:
        self.query_one("#character_aliases", Vertical).mount(CharacterAliasRow(value))

    def _collect_character_aliases(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for row in self.query(CharacterAliasRow):
            raw = row.alias_value()
            if not raw:
                continue
            key = raw.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(raw)
        return out

    def _load_discord_fields(self) -> None:
        self.query_one("#discord_token", Input).value = (
            self.store.resolve_discord_secret("token", "DISCORD_TOKEN") or ""
        )
        self.query_one("#discord_server_id", Input).value = (
            self.store.resolve_discord_text("server_id", "DISCORD_SERVER_ID") or ""
        )

    def _stt_model_options(self, current_model: str | None = None) -> list[tuple[str, str]]:
        model_ids: list[str] = []
        for value in (current_model, "chirp_2", "chirp_3", "telephony"):
            cleaned = str(value or "").strip()
            if cleaned and cleaned not in model_ids:
                model_ids.append(cleaned)
        return [(model_id, model_id) for model_id in model_ids]

    def _apply_stt_model_options(self, current_model: str | None = None) -> None:
        select = self.query_one("#stt_google_model", Select)
        previous_value = self._select_text("#stt_google_model")
        options = self._stt_model_options(current_model or previous_value or _DEFAULT_STT_MODEL)
        select.set_options(options)
        selected_value = (current_model or previous_value or _DEFAULT_STT_MODEL).strip()
        if any(value == selected_value for _, value in options):
            select.value = selected_value
        elif options:
            select.value = options[0][1]

    def _sync_stt_backend_visibility(self, backend: str | None = None) -> None:
        resolved_backend = (backend or "").strip().lower() or "v1"
        self.query_one("#stt_v1_fields", Vertical).display = resolved_backend == "v1"
        self.query_one("#stt_v2_fields", Vertical).display = resolved_backend == "v2"

    def _load_speech_to_text_fields(self) -> None:
        stt = self.store.get_stt_config()
        self.query_one("#stt_primary_language", Input).value = str(
            stt.get("language_code", DEFAULT_STT_LANGUAGE_CODE)
        )
        alternatives = stt.get("alternative_language_codes", [])
        self.query_one("#stt_alternative_languages", Input).value = ", ".join(
            str(value) for value in alternatives
        )
        backend = (self.store.resolve_stt_speech_backend() or "v1").strip().lower()
        if backend not in ("v1", "v2"):
            backend = "v1"
        self.query_one("#stt_backend", Select).value = backend
        self.query_one("#stt_google_api_key", Input).value = self.store.resolve_stt_api_key() or ""
        self.query_one("#stt_google_application_credentials", Input).value = (
            self.store.resolve_stt_credentials_path() or ""
        )
        self.query_one("#stt_google_project_id", Input).value = self.store.resolve_stt_project_id() or ""
        self.query_one("#stt_google_location", Input).value = self.store.resolve_stt_location() or ""
        self._apply_stt_model_options(self.store.resolve_stt_model() or _DEFAULT_STT_MODEL)
        self._sync_stt_backend_visibility(backend)

    def _load_text_to_speech_fields(self) -> None:
        runtime = self.store.get_runtime_config()
        self.query_one("#tts_reply_language", Input).value = str(runtime.get("reply_language", "")).strip()
        self.query_one("#tts_gemini_api_key", Input).value = (
            self.store.resolve_api_secret("google_gemini_api_key", "GOOGLE_GEMINI_API_KEY") or ""
        )
        self.query_one("#tts_elevenlabs_api_key", Input).value = (
            self.store.resolve_api_secret(
                "elevenlabs_api_key",
                "ELEVENLABS_API_KEY",
                "ELEVEN_API_KEY",
            )
            or ""
        )

    def _load_cooldowns_fields(self) -> None:
        self.query_one("#cooldown_reply_silence_seconds", Input).value = (
            f"{resolve_reply_silence_seconds(self.store):g}"
        )
        self.query_one("#cooldown_reply_cooldown_seconds", Input).value = (
            f"{resolve_reply_cooldown_seconds(self.store):g}"
        )
        self.query_one("#cooldown_mention_window_seconds", Input).value = (
            f"{resolve_mention_window_seconds(self.store):g}"
        )

    def _load_pricing_fields(self) -> None:
        p = self.store.get_pricing_config()
        self.query_one("#pricing_elevenlabs_per_1k_chars", Input).value = str(
            p["elevenlabs_usd_per_1k_characters"]
        )
        self.query_one("#pricing_genai_input_per_1m", Input).value = str(p["genai_usd_per_1m_input_tokens"])
        self.query_one("#pricing_genai_output_per_1m", Input).value = str(p["genai_usd_per_1m_output_tokens"])
        self.query_one("#pricing_google_stt_per_minute", Input).value = str(p["google_stt_usd_per_minute"])

    def _parse_positive_float_field(self, field_id: str, label: str) -> float | None:
        raw_value = self.query_one(field_id, Input).value.strip()
        try:
            value = float(raw_value)
        except ValueError:
            self.notify(f"{label} must be a valid number.", title="Settings", severity="error")
            return None
        if value <= 0:
            self.notify(f"{label} must be greater than zero.", title="Settings", severity="error")
            return None
        return value

    @on(Select.Changed, "#character_pick")
    def on_character_pick_changed(self, event: Select.Changed) -> None:
        character_id = "" if event.value in (None, Select.BLANK) else str(event.value).strip()
        if not character_id:
            return
        self._current_character_id = character_id
        self._load_form_from_character(character_id)

    @on(Select.Changed, "#stt_backend")
    def on_stt_backend_changed(self, event: Select.Changed) -> None:
        backend = "" if event.value in (None, Select.BLANK) else str(event.value).strip().lower()
        backend = backend or "v1"
        self._sync_stt_backend_visibility(backend)

    @on(Button.Pressed, "#btn_add_character_alias")
    def on_add_character_alias(self) -> None:
        self._append_character_alias_row()

    @on(Button.Pressed, "#btn_add_character")
    def on_add_character(self) -> None:
        new_id = f"character_{len(self.store.get_personalities()) + 1}"
        self.store.add_persona(
            Persona(
                persona_id=new_id,
                display_name="New character",
                system_instruction="You are a helpful voice assistant. Keep replies short.",
                genai_model=_DEFAULT_CHARACTER_MODEL,
                elevenlabs_voice_id="",
                alternative_names=[],
            )
        )
        self.store.save()
        self._current_character_id = new_id
        self._reload_character_pick()
        self._load_form_from_character(new_id)
        self.notify("Created a new character.", title="Settings")

    @on(Button.Pressed, "#btn_delete_character")
    def on_delete_character(self) -> None:
        character_id = self.query_one("#character_pick", Select).value
        if not character_id:
            return
        if len(self.store.get_personalities()) <= 1:
            logger.warning("Refusing to delete last character.")
            self.notify(
                "At least one character must remain.",
                title="Settings",
                severity="warning",
            )
            return
        self.store.remove_persona(str(character_id))
        self.store.save()
        self._current_character_id = None
        self._reload_character_pick()
        self.notify("Deleted the selected character.", title="Settings")

    @on(Button.Pressed, "#btn_save_character")
    def on_save_character(self) -> None:
        selected = self._select_text("#character_pick")
        new_id = self.query_one("#character_id", Input).value.strip()
        if not new_id:
            self.notify("ID is required.", title="Settings", severity="error")
            return
        model_value = self._select_text("#character_model")
        model = model_value or _DEFAULT_CHARACTER_MODEL
        name = self.query_one("#character_name", Input).value.strip() or new_id
        voice_id = self.query_one("#character_voice_id", Input).value.strip()
        instructions = self.query_one("#character_instructions", TextArea).text.strip()
        persona = Persona(
            persona_id=new_id,
            display_name=name,
            system_instruction=instructions,
            genai_model=model,
            elevenlabs_voice_id=voice_id,
            alternative_names=self._collect_character_aliases(),
        )
        others = [
            existing
            for existing in self.store.personas
            if existing.persona_id != selected and existing.persona_id != new_id
        ]
        others.append(persona)
        self.store.personas = others
        self.store.save()
        self._current_character_id = new_id
        self._reload_character_pick()
        self._load_form_from_character(new_id)
        self.notify("Character saved.", title="Settings")

    @on(Button.Pressed, "#btn_save_discord")
    def on_save_discord(self) -> None:
        server_id = self.query_one("#discord_server_id", Input).value.strip()
        if server_id:
            try:
                parsed = int(server_id)
            except ValueError:
                self.notify(
                    "Discord server ID must be a valid integer.",
                    title="Settings",
                    severity="error",
                )
                return
            if parsed <= 0:
                self.notify(
                    "Discord server ID must be greater than zero.",
                    title="Settings",
                    severity="error",
                )
                return
        self.store.update_discord_config(
            token=self.query_one("#discord_token", Input).value.strip(),
            server_id=server_id,
        )
        self.store.save()
        self.notify("Discord saved.", title="Settings")

    @on(Button.Pressed, "#btn_save_stt")
    def on_save_speech_to_text(self) -> None:
        primary = (
            self.query_one("#stt_primary_language", Input).value.strip() or DEFAULT_STT_LANGUAGE_CODE
        )
        raw_alternatives = self.query_one("#stt_alternative_languages", Input).value
        alternatives = [entry.strip() for entry in raw_alternatives.split(",") if entry.strip()]
        if not alternatives:
            alternatives = ["en-US"]
        backend = self._select_text("#stt_backend").lower() or "v1"
        self.store.set_stt_config(
            primary,
            alternatives,
            speech_backend=backend,
            google_application_credentials=self.query_one(
                "#stt_google_application_credentials",
                Input,
            ).value,
            project_id=self.query_one("#stt_google_project_id", Input).value,
            location=self.query_one("#stt_google_location", Input).value,
            model=self._select_text("#stt_google_model"),
            update_backend_fields=True,
        )
        self.store.apply_stt_api_secrets(
            google_stt_api_key=self.query_one("#stt_google_api_key", Input).value,
            google_stt_project_id="",
        )
        self.store.save()
        self.notify("Speech-to-Text saved.", title="Settings")

    @on(Button.Pressed, "#btn_save_tts")
    def on_save_text_to_speech(self) -> None:
        self.store.update_runtime_config(
            reply_language=self.query_one("#tts_reply_language", Input).value.strip(),
        )
        self.store.update_api_config(
            google_gemini_api_key=self.query_one("#tts_gemini_api_key", Input).value.strip(),
            elevenlabs_api_key=self.query_one("#tts_elevenlabs_api_key", Input).value.strip(),
        )
        self.store.save()
        self.notify("Text-to-Speech saved.", title="Settings")

    @on(Button.Pressed, "#btn_save_pricing")
    def on_save_pricing(self) -> None:
        eleven = self._parse_non_negative_float_field(
            "#pricing_elevenlabs_per_1k_chars",
            "ElevenLabs USD per 1k characters",
        )
        gin = self._parse_non_negative_float_field(
            "#pricing_genai_input_per_1m",
            "GenAI input USD per 1m tokens",
        )
        gout = self._parse_non_negative_float_field(
            "#pricing_genai_output_per_1m",
            "GenAI output USD per 1m tokens",
        )
        stt = self._parse_non_negative_float_field(
            "#pricing_google_stt_per_minute",
            "Google STT USD per minute",
        )
        if eleven is None or gin is None or gout is None or stt is None:
            return
        self.store.set_pricing_config(
            elevenlabs_usd_per_1k_characters=eleven,
            genai_usd_per_1m_input_tokens=gin,
            genai_usd_per_1m_output_tokens=gout,
            google_stt_usd_per_minute=stt,
        )
        self.store.save()
        self.notify("Pricing saved.", title="Settings")

    @on(Button.Pressed, "#btn_save_cooldowns")
    def on_save_cooldowns(self) -> None:
        silence = self._parse_positive_float_field(
            "#cooldown_reply_silence_seconds",
            "Reply silence seconds",
        )
        cooldown = self._parse_positive_float_field(
            "#cooldown_reply_cooldown_seconds",
            "Reply cooldown seconds",
        )
        mention = self._parse_positive_float_field(
            "#cooldown_mention_window_seconds",
            "Mention window seconds",
        )
        if silence is None or cooldown is None or mention is None:
            return
        self.store.update_runtime_config(
            reply_silence_seconds=silence,
            reply_cooldown_seconds=cooldown,
            mention_window_seconds=mention,
        )
        self.store.save()
        self.notify("Cooldowns saved.", title="Settings")

    @on(Button.Pressed, "#btn_close_settings")
    def on_close(self) -> None:
        self.dismiss()

    def action_dismiss(self) -> None:
        self.dismiss()

    def action_ignore_settings_shortcut(self) -> None:
        """Consume the parent dashboard shortcut so Footer doesn't show it here."""


PersonaSettingsScreen = BotSettingsScreen
