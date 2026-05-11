from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands

from wallet_bot.utils.discord_helpers import send_interaction_message


FEEDBACK_CHANNEL_ID = 1173509044082839602
FEEDBACK_CATEGORY_ID = 1173508830844436531


async def get_feedback_channel(interaction: discord.Interaction) -> discord.TextChannel:
    channel = interaction.client.get_channel(FEEDBACK_CHANNEL_ID)

    if channel is None:
        channel = await interaction.client.fetch_channel(FEEDBACK_CHANNEL_ID)

    if not isinstance(channel, discord.TextChannel):
        raise ValueError("Configured feedback channel is not a text channel.")

    if channel.category_id != FEEDBACK_CATEGORY_ID:
        raise ValueError("Configured feedback channel is not inside the expected category.")

    return channel


def build_feedback_embed(
    *,
    message: str,
    author: discord.Member | discord.User,
    anonymous: bool,
) -> discord.Embed:
    title = "Anonymous Feedback" if anonymous else "Public Feedback"

    embed = discord.Embed(
        title=title,
        description=message,
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )

    if not anonymous:
        avatar_url = getattr(getattr(author, "display_avatar", None), "url", None)
        if avatar_url:
            embed.set_author(name=str(author), icon_url=avatar_url)
        else:
            embed.set_author(name=str(author))

    embed.set_footer(text="Thank you for your feedback!")
    return embed


@app_commands.command(name="feedback-anonymous", description="Send anonymous feedback.")
@app_commands.describe(message="Feedback message to send.")
async def feedback_anonymous(interaction: discord.Interaction, message: str):
    try:
        channel = await get_feedback_channel(interaction)

        embed = build_feedback_embed(
            message=message,
            author=interaction.user,
            anonymous=True,
        )

        await channel.send(embed=embed)

        await send_interaction_message(
            interaction,
            "✅ Your anonymous feedback was sent.",
            ephemeral=True,
        )

    except Exception as exc:
        await send_interaction_message(
            interaction,
            f"❌ Feedback failed: {exc}",
            ephemeral=True,
        )


@app_commands.command(name="feedback-public", description="Send public feedback.")
@app_commands.describe(message="Feedback message to send.")
async def feedback_public(interaction: discord.Interaction, message: str):
    try:
        channel = await get_feedback_channel(interaction)

        embed = build_feedback_embed(
            message=message,
            author=interaction.user,
            anonymous=False,
        )

        await channel.send(embed=embed)

        await send_interaction_message(
            interaction,
            "✅ Your public feedback was sent.",
            ephemeral=True,
        )

    except Exception as exc:
        await send_interaction_message(
            interaction,
            f"❌ Feedback failed: {exc}",
            ephemeral=True,
        )