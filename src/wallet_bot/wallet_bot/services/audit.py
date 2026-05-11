from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("wallet-bot")


async def send_audit_message(bot_client: commands.Bot, log_channel_id: int, content: str) -> None:
    # All state-changing actions should still be visible in logs,
    # even if Discord channel delivery fails.
    logger.info(content)

    if not log_channel_id:
        return

    channel = bot_client.get_channel(log_channel_id)
    if channel is None:
        try:
            channel = await bot_client.fetch_channel(log_channel_id)
        except discord.DiscordException as exc:
            logger.warning("Could not fetch log channel: %s", exc)
            return

    try:
        await channel.send(content)
    except discord.DiscordException as exc:
        logger.warning("Could not send audit log to channel: %s", exc)
