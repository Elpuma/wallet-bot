from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import discord
from discord import app_commands

from wallet_bot.constants import MAX_AUDIT_PREVIEW_LENGTH
from wallet_bot.db.database import WalletDB
from wallet_bot.services.audit import send_audit_message
from wallet_bot.utils.amounts import fmt_amount, normalize_amount
from wallet_bot.utils.discord_helpers import defer_interaction, is_admin_member, run_blocking, send_interaction_message
from wallet_bot.utils.validators import validate_collector, validate_note, validate_ticket_id
from wallet_bot.views.set_confirm_view import SetConfirmView
from wallet_bot.utils.amounts import fmt_compact_amount

logger = logging.getLogger("wallet-bot")


class WalletFieldChoice:
    GP_WALLET = "gp_wallet"
    IRL_WALLET = "irl_wallet"
    DEPOSIT_WALLET = "deposit_wallet"
    CUTS_AMOUNT = "cuts_amount"
    LOYALTY_TOKENS = "loyalty_tokens"
    COMPLETED_TICKETS = "completed_tickets"
    TOTAL_GENERATED = "total_generated"
    HOLD_GP = "hold_gp"
    HOLD_IRL = "hold_irl"


WALLET_ADD_CHOICES = [
    app_commands.Choice(name="GP Wallet", value=WalletFieldChoice.GP_WALLET),
    app_commands.Choice(name="IRL Wallet", value=WalletFieldChoice.IRL_WALLET),
    app_commands.Choice(name="Deposit Wallet", value=WalletFieldChoice.DEPOSIT_WALLET),
    app_commands.Choice(name="Cuts Amount", value=WalletFieldChoice.CUTS_AMOUNT),
    app_commands.Choice(name="Loyalty Tokens", value=WalletFieldChoice.LOYALTY_TOKENS),
    app_commands.Choice(name="Completed Tickets", value=WalletFieldChoice.COMPLETED_TICKETS),
    app_commands.Choice(name="Total Generated", value=WalletFieldChoice.TOTAL_GENERATED),
    app_commands.Choice(name="Hold GP", value=WalletFieldChoice.HOLD_GP),
    app_commands.Choice(name="Hold IRL", value=WalletFieldChoice.HOLD_IRL),
]

WALLET_SET_CHOICES = [
    app_commands.Choice(name="GP Wallet", value=WalletFieldChoice.GP_WALLET),
    app_commands.Choice(name="IRL Wallet", value=WalletFieldChoice.IRL_WALLET),
    app_commands.Choice(name="Deposit Wallet", value=WalletFieldChoice.DEPOSIT_WALLET),
    app_commands.Choice(name="Cuts Amount", value=WalletFieldChoice.CUTS_AMOUNT),
    app_commands.Choice(name="Loyalty Tokens", value=WalletFieldChoice.LOYALTY_TOKENS),
    app_commands.Choice(name="Completed Tickets", value=WalletFieldChoice.COMPLETED_TICKETS),
    app_commands.Choice(name="Total Generated", value=WalletFieldChoice.TOTAL_GENERATED),
]

AUTH_DESTINATION_CHOICES = [
    app_commands.Choice(name="GP Wallet", value="gp_wallet"),
    app_commands.Choice(name="IRL Wallet", value="irl_wallet"),
    app_commands.Choice(name="Deposit Wallet", value="deposit_wallet"),
    app_commands.Choice(name="Cuts Amount", value="cuts_amount"),
    app_commands.Choice(name="Total Generated", value="total_generated"),
]


def short_preview(value: Optional[str]) -> str:
    if not value:
        return "-"
    if len(value) <= MAX_AUDIT_PREVIEW_LENGTH:
        return value
    return value[: MAX_AUDIT_PREVIEW_LENGTH - 3] + "..."


def build_wallet_embed(
    member: discord.Member | discord.User,
    wallet_view: dict,
    holds: list[dict],
) -> discord.Embed:
    gp_on_hold = sum((Decimal(h["amount"]) for h in holds if h["currency"] == "GP"), Decimal("0.0000"))
    irl_on_hold = sum((Decimal(h["amount"]) for h in holds if h["currency"] == "IRL"), Decimal("0.0000"))
    total_on_hold = gp_on_hold + irl_on_hold

    embed = discord.Embed(
        title="Wallet Details",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )

    avatar_url = getattr(getattr(member, "display_avatar", None), "url", None)
    if avatar_url:
        embed.set_author(name=str(member), icon_url=avatar_url)
    else:
        embed.set_author(name=str(member))

    embed.add_field(name="GP Wallet", value=fmt_compact_amount(wallet_view["gp_wallet"]), inline=True)
    embed.add_field(name="IRL Wallet", value=fmt_compact_amount(wallet_view["irl_wallet"]), inline=True)
    embed.add_field(name="Loyalty Tokens", value=str(wallet_view["loyalty_tokens"]), inline=True)

    embed.add_field(name="On Hold Amount", value=fmt_compact_amount(total_on_hold), inline=True)
    embed.add_field(name="Cuts Amount", value=fmt_compact_amount(wallet_view["cuts_amount"]), inline=True)
    embed.add_field(name="Completed Tickets", value=str(wallet_view["completed_tickets"]), inline=True)

    embed.add_field(name="Total Generated", value=fmt_compact_amount(wallet_view["total_generated"]), inline=True)
    embed.add_field(name="Deposit Wallet", value=fmt_compact_amount(wallet_view["deposit_wallet"]), inline=True)
    embed.add_field(name="Hold Breakdown", value=f"GP: {fmt_compact_amount(gp_on_hold)}\nIRL: {fmt_compact_amount(irl_on_hold)}", inline=True)

    if holds:
        lines = []
        for hold in holds[:8]:
            ticket_channel_id = hold.get("ticket_id")
            collector_text = short_preview(hold.get("collector_text")) or "N/A"

            ticket_display = f"<#{ticket_channel_id}>" if ticket_channel_id else "N/A"

            line = (
                f"Ticket: {ticket_display} | "
                f"{hold['currency']} {fmt_compact_amount(hold['amount'])} | "
                f"Collector: {collector_text}"
            )

            if len(line) > 250:
                line = line[:247] + "..."

            lines.append(line)

        if len(holds) > 8:
            lines.append(f"... and {len(holds) - 8} more active hold(s)")

        embed.add_field(name="On Hold Details", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="On Hold Details", value="No active holds.", inline=False)

    embed.set_footer(text="RuneXei Services Wallet system")
    return embed


class WalletCommandGroup(app_commands.Group):
    def __init__(self, *, db: WalletDB, admin_role_id: int, admin_role_name: str, log_channel_id: int, bot_client):
        super().__init__(name="wallet", description="Wallet commands")
        self.db = db
        self.admin_role_id = admin_role_id
        self.admin_role_name = admin_role_name
        self.log_channel_id = log_channel_id
        self.bot_client = bot_client

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return is_admin_member(
            interaction.user,
            admin_role_id=self.admin_role_id,
            admin_role_name=self.admin_role_name,
        )

    @app_commands.command(name="check", description="Check your wallet, or another user's wallet if you are an admin.")
    @app_commands.describe(user="Optional. Admins can check another user's wallet.")
    async def check(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if user is not None and user.id != interaction.user.id and not self._is_admin(interaction):
            await send_interaction_message(interaction, "You can only check your own wallet.", ephemeral=True)
            return

        if not await defer_interaction(interaction, ephemeral=True):
            return

        try:
            target = user or interaction.user
            await run_blocking(self.db.ensure_wallet, str(target.id), str(target))
            wallet_view = await run_blocking(self.db.get_wallet_view, str(target.id))
            holds = await run_blocking(self.db.get_hold_entries_view, str(target.id), "ON_HOLD")
            embed = build_wallet_embed(target, wallet_view, holds)
            await send_interaction_message(interaction, embed=embed, ephemeral=True)
        except Exception as exc:
            logger.exception("Wallet check failed.")
            await send_interaction_message(interaction, f"❌ Wallet check failed: {exc}", ephemeral=True)

    @app_commands.command(name="add", description="Admin only. Add value to a wallet field or create a hold.")
    @app_commands.describe(
        user="Target user",
        field="Field to increase",
        amount="Amount to add",
        ticket_id="Required when creating a hold",
        collector="Optional collector text for hold entries",
        note="Optional note",
    )
    @app_commands.choices(field=WALLET_ADD_CHOICES)
    async def add(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        field: app_commands.Choice[str],
        amount: str,
        ticket_id: Optional[str] = None,
        collector: Optional[str] = None,
        note: Optional[str] = None,
    ):
        if not self._is_admin(interaction):
            await send_interaction_message(interaction, "Only admins can use this command.", ephemeral=True)
            return

        if not await defer_interaction(interaction, ephemeral=True):
            return

        try:
            amount_dec = normalize_amount(amount)
            ticket_id = validate_ticket_id(ticket_id)
            collector = validate_collector(collector)
            note = validate_note(note)

            if field.value in {"hold_gp", "hold_irl"} and not ticket_id:
                raise ValueError("ticket_id is required for hold entries.")

            if field.value in {"loyalty_tokens", "completed_tickets"} and amount_dec != amount_dec.to_integral_value():
                raise ValueError(f"{field.name} only accepts whole numbers.")

            tx_id, hold_id = await run_blocking(
                self.db.add_to_field,
                user_id=str(user.id),
                username=str(user),
                field_name=field.value,
                amount=amount_dec if field.value not in {"loyalty_tokens", "completed_tickets"} else int(amount_dec),
                performed_by=str(interaction.user.id),
                note=note,
                ticket_id=ticket_id,
                collector_text=collector,
            )

            #message = f"✅ Added `{amount_dec}` to `{field.name}` for {user.mention}. Transaction ID: `{tx_id}`"
            message = f"✅ Added `{fmt_compact_amount(amount_dec)}` to `{field.name}` for {user.mention}. Transaction ID: `{tx_id}`"
            if hold_id:
                message += f" | Hold ID: `{hold_id}`"

            await send_interaction_message(interaction, message, ephemeral=True)
            await send_audit_message(
                self.bot_client,
                self.log_channel_id,
                f"[WALLET][ADD] admin={interaction.user} target={user} field={field.value} amount={fmt_compact_amount(amount_dec)} ticket={short_preview(ticket_id)} collector={short_preview(collector)} hold_id={hold_id or '-'} tx={tx_id} note={short_preview(note)}",
            )
        except Exception as exc:
            logger.exception("Wallet add failed.")
            await send_interaction_message(interaction, f"❌ Add failed: {exc}", ephemeral=True)

    @app_commands.command(name="set", description="Admin only. Set a wallet field to an exact value with confirmation.")
    @app_commands.describe(
        user="Target user",
        field="Field to set",
        value="New value",
        note="Optional note",
    )
    @app_commands.choices(field=WALLET_SET_CHOICES)
    async def set(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        field: app_commands.Choice[str],
        value: str,
        note: Optional[str] = None,
    ):
        if not self._is_admin(interaction):
            await send_interaction_message(interaction, "Only admins can use this command.", ephemeral=True)
            return

        if not await defer_interaction(interaction, ephemeral=True):
            return

        try:
            value_dec = normalize_amount(value)
            note = validate_note(note)

            if field.value in {"loyalty_tokens", "completed_tickets"} and value_dec != value_dec.to_integral_value():
                raise ValueError(f"{field.name} only accepts whole numbers.")

            stored_value = (
                str(int(value_dec))
                if field.value in {"loyalty_tokens", "completed_tickets"}
                else str(value_dec)
            )

            prompt = (
                f"⚠️ Confirm set action\n"
                f"Target: {user.mention}\n"
                f"Field: `{field.name}`\n"
                f"New value: `{stored_value}`\n"
                f"Note: `{note or '-'}`"
            )

            view = SetConfirmView(
                actor_id=interaction.user.id,
                action_payload={
                    "target_user_id": str(user.id),
                    "target_username": str(user),
                    "target_mention": user.mention,
                    "field_name": field.value,
                    "value": stored_value,
                    "note": note,
                },
                db=self.db,
                bot_client=self.bot_client,
                log_channel_id=self.log_channel_id,
            )

            sent_message = await interaction.followup.send(
                prompt,
                ephemeral=True,
                view=view,
                wait=True,
            )
            view.message = sent_message

        except Exception as exc:
            logger.exception("Wallet set validation failed.")
            await send_interaction_message(interaction, f"❌ Set validation failed: {exc}", ephemeral=True)

    @app_commands.command(name="deposit", description="Admin only. Move funds from GP wallet to Deposit wallet.")
    @app_commands.describe(user="Target user", amount="Amount to move", note="Optional note")
    async def deposit(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: str,
        note: Optional[str] = None,
    ):
        if not self._is_admin(interaction):
            await send_interaction_message(interaction, "Only admins can use this command.", ephemeral=True)
            return

        if not await defer_interaction(interaction, ephemeral=True):
            return

        try:
            amount_dec = normalize_amount(amount)
            note = validate_note(note)

            tx_id = await run_blocking(
                self.db.transfer_between_wallets,
                user_id=str(user.id),
                username=str(user),
                source_wallet="gp_wallet",
                target_wallet="deposit_wallet",
                amount=amount_dec,
                performed_by=str(interaction.user.id),
                note=note,
            )
            await send_interaction_message(
                interaction,
                f"✅ Moved `{fmt_compact_amount(amount_dec)}` from GP Wallet to Deposit Wallet for {user.mention}. Transaction ID: `{tx_id}`",
                ephemeral=True,
            )
            await send_audit_message(
                self.bot_client,
                self.log_channel_id,
                f"[WALLET][DEPOSIT] admin={interaction.user} target={user} amount={fmt_compact_amount(amount_dec)} tx={tx_id} note={short_preview(note)}",
            )
        except Exception as exc:
            logger.exception("Wallet deposit failed.")
            await send_interaction_message(interaction, f"❌ Deposit failed: {exc}", ephemeral=True)

    @app_commands.command(name="depositwithdraw", description="Admin only. Move funds from Deposit wallet back to GP wallet.")
    @app_commands.describe(user="Target user", amount="Amount to move", note="Optional note")
    async def depositwithdraw(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: str,
        note: Optional[str] = None,
    ):
        if not self._is_admin(interaction):
            await send_interaction_message(interaction, "Only admins can use this command.", ephemeral=True)
            return

        if not await defer_interaction(interaction, ephemeral=True):
            return

        try:
            amount_dec = normalize_amount(amount)
            note = validate_note(note)

            tx_id = await run_blocking(
                self.db.transfer_between_wallets,
                user_id=str(user.id),
                username=str(user),
                source_wallet="deposit_wallet",
                target_wallet="gp_wallet",
                amount=amount_dec,
                performed_by=str(interaction.user.id),
                note=note,
            )
            await send_interaction_message(
                interaction,
                f"✅ Moved `{fmt_compact_amount(amount_dec)}` from Deposit Wallet to GP Wallet for {user.mention}. Transaction ID: `{tx_id}`",
                ephemeral=True,
            )
            await send_audit_message(
                self.bot_client,
                self.log_channel_id,
                f"[WALLET][DEPOSITWITHDRAW] admin={interaction.user} target={user} amount={fmt_compact_amount(amount_dec)} tx={tx_id} note={short_preview(note)}",
            )
        except Exception as exc:
            logger.exception("Wallet deposit withdrawal failed.")
            await send_interaction_message(interaction, f"❌ Deposit withdrawal failed: {exc}", ephemeral=True)

    @app_commands.command(name="holdlist", description="Admin only. List all users with active holds.")
    async def holdlist(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await send_interaction_message(interaction, "Only admins can use this command.", ephemeral=True)
            return

        if not await defer_interaction(interaction, ephemeral=True):
            return

        try:
            rows = await run_blocking(self.db.list_users_with_holds)
            if not rows:
                await send_interaction_message(interaction, "There are no active holds right now.", ephemeral=True)
                return

            embed = discord.Embed(title="Active Hold List", color=discord.Color.orange())
            lines = []
            for row in rows[:20]:
                gp = Decimal(row.gp_on_hold_units) / Decimal("10000")
                irl = Decimal(row.irl_on_hold_units) / Decimal("10000")

                lines.append(
                    f"**{row.username}** | Holds: {row.hold_count} | "
                    f"GP: {fmt_compact_amount(gp)} | IRL: {fmt_compact_amount(irl)}"
                )
            if len(rows) > 20:
                lines.append(f"... and {len(rows) - 20} more user(s)")
            embed.description = "\n".join(lines)
            await send_interaction_message(interaction, embed=embed, ephemeral=True)
        except Exception as exc:
            logger.exception("Wallet hold list failed.")
            await send_interaction_message(interaction, f"❌ Hold list failed: {exc}", ephemeral=True)

    @app_commands.command(name="authenticate", description="Admin only. Authenticate a hold and move it into a destination bucket.")
    @app_commands.describe(
        hold_id="Hold ID to authenticate",
        destination="Where the amount should go",
        note="Optional note",
    )
    @app_commands.choices(destination=AUTH_DESTINATION_CHOICES)
    async def authenticate(
        self,
        interaction: discord.Interaction,
        hold_id: str,
        destination: app_commands.Choice[str],
        note: Optional[str] = None,
    ):
        if not self._is_admin(interaction):
            await send_interaction_message(interaction, "Only admins can use this command.", ephemeral=True)
            return

        if not await defer_interaction(interaction, ephemeral=True):
            return

        try:
            note = validate_note(note)

            tx_id = await run_blocking(
                self.db.authenticate_hold,
                hold_id=hold_id.strip(),
                destination_field=destination.value,
                performed_by=str(interaction.user.id),
                note=note,
            )
            await send_interaction_message(
                interaction,
                f"✅ Hold `{hold_id}` authenticated into `{destination.name}`. Transaction ID: `{tx_id}`",
                ephemeral=True,
            )
            await send_audit_message(
                self.bot_client,
                self.log_channel_id,
                f"[WALLET][AUTHENTICATE] admin={interaction.user} hold_id={hold_id.strip()} destination={destination.value} tx={tx_id} note={short_preview(note)}",
            )
        except Exception as exc:
            logger.exception("Wallet authenticate failed.")
            await send_interaction_message(interaction, f"❌ Authentication failed: {exc}", ephemeral=True)

    @app_commands.command(name="reverse", description="Admin only. Reverse a previous wallet transaction.")
    @app_commands.describe(transaction_id="Transaction ID to reverse", note="Optional reason for reversal")
    async def reverse(
        self,
        interaction: discord.Interaction,
        transaction_id: str,
        note: Optional[str] = None,
    ):
        if not self._is_admin(interaction):
            await send_interaction_message(interaction, "Only admins can use this command.", ephemeral=True)
            return

        if not await defer_interaction(interaction, ephemeral=True):
            return

        try:
            note = validate_note(note)

            reverse_id = await run_blocking(
                self.db.reverse_transaction,
                transaction_id=transaction_id.strip(),
                performed_by=str(interaction.user.id),
                note=note,
            )
            await send_interaction_message(
                interaction,
                f"✅ Transaction reversed successfully. Reverse Transaction ID: `{reverse_id}`",
                ephemeral=True,
            )
            await send_audit_message(
                self.bot_client,
                self.log_channel_id,
                f"[WALLET][REVERSE] admin={interaction.user} original_tx={transaction_id.strip()} reverse_tx={reverse_id} note={short_preview(note)}",
            )
        except Exception as exc:
            logger.exception("Wallet reverse failed.")
            await send_interaction_message(interaction, f"❌ Reverse failed: {exc}", ephemeral=True)
