from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import discord

logger = logging.getLogger("wallet-bot")


def parse_json_safe(text: Optional[str]) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


async def run_blocking(func, /, *args, **kwargs):
    # SQLite work is still blocking.
    # We move it to a thread so the bot loop stays responsive.
    return await asyncio.to_thread(func, *args, **kwargs)


async def defer_interaction(interaction: discord.Interaction, *, ephemeral: bool = True) -> bool:
    try:
        if interaction.response.is_done():
            return True

        if interaction.is_expired():
            logger.warning(
                "Interaction already expired before defer. command=%s user_id=%s",
                getattr(getattr(interaction, "command", None), "qualified_name", "unknown"),
                getattr(getattr(interaction, "user", None), "id", "unknown"),
            )
            return False

        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
        return True

    except discord.InteractionResponded:
        logger.warning(
            "Interaction was already acknowledged before defer. command=%s user_id=%s",
            getattr(getattr(interaction, "command", None), "qualified_name", "unknown"),
            getattr(getattr(interaction, "user", None), "id", "unknown"),
        )
        return True

    except discord.NotFound:
        logger.warning(
            "Interaction expired before defer could be sent. command=%s user_id=%s",
            getattr(getattr(interaction, "command", None), "qualified_name", "unknown"),
            getattr(getattr(interaction, "user", None), "id", "unknown"),
        )
        return False

    except discord.HTTPException as exc:
        error_code = getattr(exc, "code", None)

        if error_code == 40060:
            logger.warning(
                "Interaction was already acknowledged before defer. command=%s user_id=%s",
                getattr(getattr(interaction, "command", None), "qualified_name", "unknown"),
                getattr(getattr(interaction, "user", None), "id", "unknown"),
            )
            return True

        if error_code == 10062:
            logger.warning(
                "Interaction became invalid or expired before defer. command=%s user_id=%s",
                getattr(getattr(interaction, "command", None), "qualified_name", "unknown"),
                getattr(getattr(interaction, "user", None), "id", "unknown"),
            )
            return False

        logger.exception(
            "HTTPException while deferring interaction. command=%s user_id=%s",
            getattr(getattr(interaction, "command", None), "qualified_name", "unknown"),
            getattr(getattr(interaction, "user", None), "id", "unknown"),
        )
        return False


async def send_interaction_message(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    *,
    embed: Optional[discord.Embed] = None,
    ephemeral: bool = True,
    view: Optional[discord.ui.View] = None,
) -> bool:
    def build_kwargs() -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {"ephemeral": ephemeral}
        if content is not None:
            kwargs["content"] = content
        if embed is not None:
            kwargs["embed"] = embed
        if view is not None:
            kwargs["view"] = view
        return kwargs

    try:
        kwargs = build_kwargs()

        if interaction.is_expired():
            logger.warning(
                "Interaction expired before message send. command=%s user_id=%s",
                getattr(getattr(interaction, "command", None), "qualified_name", "unknown"),
                getattr(getattr(interaction, "user", None), "id", "unknown"),
            )
            return False

        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)
        return True

    except discord.InteractionResponded:
        try:
            if interaction.is_expired():
                logger.warning("Interaction expired before followup could be sent.")
                return False
            await interaction.followup.send(**build_kwargs())
            return True
        except discord.NotFound:
            logger.warning("Interaction expired before followup could be sent.")
            return False
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) in (40060, 10062):
                logger.warning("Followup failed because interaction was already acknowledged or expired.")
                return False
            logger.exception("HTTPException while sending followup message.")
            return False

    except discord.NotFound:
        logger.warning("Interaction expired before message could be sent.")
        return False

    except discord.HTTPException as exc:
        if getattr(exc, "code", None) == 40060:
            try:
                if interaction.is_expired():
                    logger.warning("Interaction expired before followup after 40060.")
                    return False
                await interaction.followup.send(**build_kwargs())
                return True
            except Exception:
                logger.exception("Failed followup after 40060.")
                return False

        if getattr(exc, "code", None) == 10062:
            logger.warning("Interaction expired before message could be sent.")
            return False

        logger.exception("HTTPException while sending interaction message.")
        return False


def is_admin_member(
    member: discord.abc.User | discord.Member,
    *,
    admin_role_id: int,
    admin_role_name: str,
) -> bool:
    # We prefer role ID because names can change.
    # The role name stays as a fallback to keep setup flexible.
    if not isinstance(member, discord.Member):
        return False

    if admin_role_id and any(role.id == admin_role_id for role in member.roles):
        return True

    return any(role.name == admin_role_name for role in member.roles)
