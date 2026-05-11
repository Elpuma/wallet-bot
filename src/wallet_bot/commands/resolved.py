from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands

from wallet_bot.commands.feedback import FEEDBACK_CHANNEL_ID, FEEDBACK_CATEGORY_ID, build_feedback_embed
from wallet_bot.utils.discord_helpers import send_interaction_message


class FeedbackModal(discord.ui.Modal):
    def __init__(self, *, anonymous: bool):
        title = "Anonymous Feedback" if anonymous else "Public Feedback"
        super().__init__(title=title)

        self.anonymous = anonymous

        self.feedback_message = discord.ui.TextInput(
            label="Your feedback",
            placeholder="Example: Resky is a beast, thank you again!",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1500,
        )

        self.add_item(self.feedback_message)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel = interaction.client.get_channel(FEEDBACK_CHANNEL_ID)

            if channel is None:
                channel = await interaction.client.fetch_channel(FEEDBACK_CHANNEL_ID)

            if not isinstance(channel, discord.TextChannel):
                raise ValueError("Configured feedback channel is not a text channel.")

            if channel.category_id != FEEDBACK_CATEGORY_ID:
                raise ValueError("Configured feedback channel is not inside the expected category.")

            embed = build_feedback_embed(
                message=str(self.feedback_message.value),
                author=interaction.user,
                anonymous=self.anonymous,
            )

            await channel.send(embed=embed)

            feedback_type = "anonymous" if self.anonymous else "public"

            await interaction.response.send_message(
                f"✅ Your {feedback_type} feedback was sent. Thank you!",
                ephemeral=True,
            )

        except Exception as exc:
            await interaction.response.send_message(
                f"❌ Feedback failed: {exc}",
                ephemeral=True,
            )


class ResolvedFeedbackView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Anonymous Feedback",
        emoji="🕵️",
        style=discord.ButtonStyle.primary,
        custom_id="resolved_feedback_anonymous",
    )
    async def anonymous_feedback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal(anonymous=True))

    @discord.ui.button(
        label="Public Feedback",
        emoji="📝",
        style=discord.ButtonStyle.success,
        custom_id="resolved_feedback_public",
    )
    async def public_feedback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal(anonymous=False))


def build_resolved_embed(member: discord.Member | discord.User) -> discord.Embed:
    embed = discord.Embed(
        title="✅ Your Job is Completed!",
        description=(
            f"Hey {member.mention},\n\n"
            "Your order has been successfully marked as **Resolved** 🎉\n\n"
            "📝 **We’d love your feedback:**\n"
            "Use one of the buttons below to submit anonymous or public feedback.\n\n"
            "Your feedback helps us improve our service and reward our helpers!\n\n"
            "---\n"
            "❓ **Need anything else?**\n"
            "We’re happy to help, just let us know!\n\n"
            "Thanks for choosing us 💙"
        ),
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )

    avatar_url = getattr(getattr(member, "display_avatar", None), "url", None)
    if avatar_url:
        embed.set_author(name=str(member), icon_url=avatar_url)

    embed.set_footer(text="RuneXei Services")
    return embed


@app_commands.command(name="resolved", description="Post a resolved job message with feedback buttons.")
@app_commands.describe(user="User whose job was completed.")
async def resolved(interaction: discord.Interaction, user: discord.Member):
    embed = build_resolved_embed(user)
    view = ResolvedFeedbackView()

    await send_interaction_message(
        interaction,
        embed=embed,
        view=view,
        ephemeral=False,
    )