from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import discord
from discord import app_commands

from wallet_bot.utils.amounts import fmt_compact_amount, normalize_amount
from wallet_bot.utils.discord_helpers import send_interaction_message


SUPPORT_ROLE_ID = 1483159004741107732
OWNER_ROLE_ID = 1417483466886615059

ALLOWED_ROLE_NAMES = {"support", "owner", "owners", "admin"}


def member_can_convert(member: discord.Member | discord.User) -> bool:
    roles = getattr(member, "roles", [])

    for role in roles:
        role_id = getattr(role, "id", None)
        role_name = getattr(role, "name", "").strip().lower()

        if role_id in {SUPPORT_ROLE_ID, OWNER_ROLE_ID}:
            return True

        if role_name in ALLOWED_ROLE_NAMES:
            return True

    return False


def format_usd(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${rounded:,.2f}"


def build_converter_embed(
    *,
    gp_amount: Decimal,
    requester: discord.Member | discord.User,
    bot_user: discord.ClientUser | discord.User | None,
) -> discord.Embed:
    million_units = gp_amount / Decimal("1000000")

    crypto_total = million_units * Decimal("0.27")
    paypal_total = million_units * Decimal("1.04") * Decimal("0.27")

    embed = discord.Embed(
        title="💱 GP to IRL Converter",
        description=(
            f"Converting: 🪙 **{fmt_compact_amount(gp_amount)} GP**\n"
            f"to IRL"
        ),
        color=discord.Color.blue(),
    )

    embed.add_field(
        name="🪙 Crypto",
        value=(
            "Rate: `$0.27 / 1m GP`\n"
            f"Total: **{format_usd(crypto_total)}**"
        ),
        inline=True,
    )

    embed.add_field(
        name="💵 PayPal",
        value=(
            "Rate: `$1.04 / 1m GP`\n"
            f"Total: **{format_usd(paypal_total)}**"
        ),
        inline=True,
    )

    avatar_url = None

    if bot_user and getattr(bot_user, "display_avatar", None):
        avatar_url = bot_user.display_avatar.url

    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    requester_avatar = getattr(getattr(requester, "display_avatar", None), "url", None)
    if requester_avatar:
        embed.set_author(name=str(requester), icon_url=requester_avatar)
    else:
        embed.set_author(name=str(requester))

    embed.set_footer(text="Rate Tracker")
    return embed


@app_commands.command(name="convert", description="Convert a GP amount to IRL values.")
@app_commands.describe(gp_amount="GP amount to convert. Example: 1m, 500m, 2b")
async def convert(interaction: discord.Interaction, gp_amount: str):
    if not member_can_convert(interaction.user):
        await send_interaction_message(
            interaction,
            "❌ Only Support and OWNER can use this command.",
            ephemeral=True,
        )
        return

    try:
        amount_dec = normalize_amount(gp_amount)

        if amount_dec <= 0:
            raise ValueError("Amount must be greater than zero.")

        embed = build_converter_embed(
            gp_amount=amount_dec,
            requester=interaction.user,
            bot_user=interaction.client.user,
        )

        await send_interaction_message(interaction, embed=embed, ephemeral=False)

    except Exception as exc:
        await send_interaction_message(
            interaction,
            f"❌ Convert failed: {exc}",
            ephemeral=True,
        )