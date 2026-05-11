from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

import discord

from wallet_bot.db.database import WalletDB
from wallet_bot.services.audit import send_audit_message
from wallet_bot.utils.discord_helpers import send_interaction_message, run_blocking

logger = logging.getLogger("wallet-bot")


class SetConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        actor_id: int,
        action_payload: Dict[str, Any],
        db: WalletDB,
        bot_client,
        log_channel_id: int,
    ):
        super().__init__(timeout=60)
        self.actor_id = actor_id
        self.action_payload = action_payload
        self.db = db
        self.bot_client = bot_client
        self.log_channel_id = log_channel_id
        self.final_message = "Action expired."
        self.completed = False
        self.message: Optional[discord.Message] = None

    def disable_all_buttons(self) -> None:
        for item in self.children:
            item.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.actor_id:
            await send_interaction_message(
                interaction,
                "Only the command author can confirm this action.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer()

            target_user_id = self.action_payload["target_user_id"]
            target_username = self.action_payload["target_username"]
            target_mention = self.action_payload["target_mention"]
            field_name = self.action_payload["field_name"]
            value = Decimal(self.action_payload["value"])
            note = self.action_payload.get("note")

            tx_id = await run_blocking(
                self.db.set_field,
                user_id=target_user_id,
                username=target_username,
                field_name=field_name,
                value=value,
                performed_by=str(interaction.user.id),
                note=note,
            )

            self.final_message = f"✅ Set completed for {target_mention}. Transaction ID: `{tx_id}`"
            self.completed = True
            self.disable_all_buttons()

            await send_audit_message(
                self.bot_client,
                self.log_channel_id,
                f"[WALLET][SET] admin={interaction.user} target={target_username} field={field_name} value={value} tx={tx_id} note={note or '-'}",
            )

            await interaction.edit_original_response(content=self.final_message, view=self)

        except Exception as exc:
            logger.exception("Set confirmation failed.")
            self.disable_all_buttons()

            error_message = f"❌ Set failed: {exc}"

            try:
                if interaction.response.is_done():
                    await interaction.edit_original_response(content=error_message, view=self)
                else:
                    await interaction.response.edit_message(content=error_message, view=self)
            except Exception:
                logger.exception("Failed to update confirmation message after error.")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.final_message = "Action cancelled."
        self.completed = True
        self.disable_all_buttons()
        await interaction.response.edit_message(content=self.final_message, view=self)

    async def on_timeout(self) -> None:
        self.disable_all_buttons()
        if self.message is not None and not self.completed:
            try:
                await self.message.edit(content=self.final_message, view=self)
            except discord.DiscordException:
                logger.warning("Could not edit timed out SetConfirmView message.")