"""Slash commands for consent and transcript deletion (issue #8)."""

from __future__ import annotations

import logging
from collections.abc import Callable

import discord
from discord import app_commands

from ..runtime_dirs import app_bundle_dir
from ..storage.consent import ConsentStore
from ..storage.transcripts import scrub_user_data_from_transcripts

logger = logging.getLogger(__name__)

DISCLOSURE_MESSAGE = """\
**Discord Audio Bot — data processing disclosure**

By accepting, you **direct** this application to process your voice and related Discord data as follows:

1. **Google Cloud Speech-to-Text** — Your voice audio is sent for real-time transcription.
2. **Google GenAI (Gemini)** — Transcripts and conversation context may be sent to generate replies.
3. **ElevenLabs** — Reply text may be sent to synthesize speech played back in the voice channel.
4. **Local storage** — Transcript segments and session metadata may be saved as JSON files on the machine running the bot.

You can **revoke** consent with `/consent revoke` and request removal of saved transcript segments with `/data delete` (see command description for confirmation).

This message is recorded as proof of disclosure. Timestamp: saved when you ran `/consent accept`.
"""


def register_consent_commands(
    tree: app_commands.CommandTree,
    consent_store: ConsentStore,
    *,
    activity_sink: Callable[[str], None] | None = None,
) -> None:
    """Register `/consent` and `/data` command groups on ``tree``."""
    transcripts_dir = app_bundle_dir() / "transcripts"

    consent_group = app_commands.Group(
        name="consent",
        description="Opt in or out of third-party voice and transcript processing",
    )

    @consent_group.command(name="accept", description="Opt in: receive disclosure by DM and allow voice processing")
    async def consent_accept(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            dm_message = await interaction.user.send(DISCLOSURE_MESSAGE)
        except discord.Forbidden:
            await interaction.followup.send(
                "Could not send you a DM (DMs may be closed). Open DMs from server members "
                "or start a DM with this bot, then run `/consent accept` again.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            logger.warning("DM disclosure failed: %s", exc)
            await interaction.followup.send(
                "Could not deliver the disclosure DM. Please try again later.",
                ephemeral=True,
            )
            return

        consent_store.record_acceptance(
            interaction.user.id,
            disclosure_dm_channel_id=dm_message.channel.id,
            disclosure_message_id=dm_message.id,
        )
        if activity_sink is not None:
            who = f"{interaction.user} ({interaction.user.id})"
            activity_sink(f"Consent accepted: {who}; disclosure DM id {dm_message.id}")
        await interaction.followup.send(
            "Consent recorded. Check your DMs for the full disclosure.",
            ephemeral=True,
        )

    @consent_group.command(name="revoke", description="Withdraw consent for third-party processing")
    async def consent_revoke(interaction: discord.Interaction) -> None:
        had_active = consent_store.revoke(interaction.user.id)
        if activity_sink is not None:
            who = f"{interaction.user} ({interaction.user.id})"
            activity_sink(f"Consent revoked: {who}" + (" (was active)" if had_active else " (was not active)"))
        if had_active:
            await interaction.response.send_message(
                "Your consent has been revoked. Your voice will not be sent for transcription until you opt in again.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "You did not have active consent. Nothing to revoke.",
                ephemeral=True,
            )

    data_group = app_commands.Group(
        name="data",
        description="Manage locally stored session data",
    )

    @data_group.command(name="delete", description="Remove your transcript segments from all saved session files")
    @app_commands.describe(confirm='Type exactly "DELETE" to confirm')
    async def data_delete(interaction: discord.Interaction, confirm: str) -> None:
        if confirm != "DELETE":
            await interaction.response.send_message(
                'Confirmation failed: pass `confirm: DELETE` (the word DELETE in capitals).',
                ephemeral=True,
            )
            return
        stats = scrub_user_data_from_transcripts(transcripts_dir, interaction.user.id)
        if activity_sink is not None:
            who = f"{interaction.user} ({interaction.user.id})"
            activity_sink(
                f"/data delete by {who}: removed {stats.segments_removed} segment(s) "
                f"from {stats.files_touched} file(s)"
            )
        await interaction.response.send_message(
            (
                f"Removed **{stats.segments_removed}** transcript segment(s) from "
                f"**{stats.files_touched}** file(s). "
                "Bot reply lines in those files were not modified."
            ),
            ephemeral=True,
        )

    tree.add_command(consent_group)
    tree.add_command(data_group)
