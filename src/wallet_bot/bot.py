from __future__ import annotations

import logging

import discord
from discord.ext import commands

from wallet_bot.commands.convert import convert
from wallet_bot.commands.wallet import WalletCommandGroup
from wallet_bot.config import load_settings
from wallet_bot.db.database import WalletDB
from wallet_bot.logging_config import configure_logging
from wallet_bot.commands.feedback import feedback_anonymous, feedback_public
from wallet_bot.commands.resolved import resolved

logger = logging.getLogger("wallet-bot")


def build_bot() -> commands.Bot:
    settings = load_settings()
    configure_logging(settings.log_file_path)

    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    db = WalletDB(settings.db_path)

    wallet_group = WalletCommandGroup(
        db=db,
        admin_role_id=settings.admin_role_id,
        admin_role_name=settings.admin_role_name,
        log_channel_id=settings.log_channel_id,
        bot_client=bot,
    )

    bot.tree.add_command(wallet_group)
    bot.tree.add_command(convert)
    bot.tree.add_command(feedback_anonymous)
    bot.tree.add_command(feedback_public)
    bot.tree.add_command(resolved)

    @bot.event
    async def setup_hook():
        try:
            if settings.guild_id:
                guild = discord.Object(id=settings.guild_id)

                bot.tree.copy_global_to(guild=guild)

                synced = await bot.tree.sync(guild=guild)
                logger.info(
                    "Synced %s guild command(s) to guild %s",
                    len(synced),
                    settings.guild_id,
                )
            else:
                synced = await bot.tree.sync()
                logger.info("Synced %s global command(s)", len(synced))
        except Exception:
            logger.exception("Failed to sync application commands during setup_hook.")

    @bot.event
    async def on_ready():
        logger.info("Bot is ready as %s", bot.user)

    return bot


def main() -> None:
    settings = load_settings()
    bot = build_bot()
    bot.run(settings.discord_bot_token)