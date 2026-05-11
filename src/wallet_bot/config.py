from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    # Main bot configuration.
    discord_bot_token: str
    admin_role_id: int
    admin_role_name: str
    log_channel_id: int
    guild_id: int
    db_path: str
    log_file_path: str

    @property
    def db_path_obj(self) -> Path:
        return Path(self.db_path)

    @property
    def log_file_path_obj(self) -> Path:
        return Path(self.log_file_path)


def load_settings() -> Settings:
    load_dotenv()

    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing DISCORD_BOT_TOKEN environment variable.")

    return Settings(
        discord_bot_token=token,
        admin_role_id=int(os.getenv("ADMIN_ROLE_ID", "0") or 0),
        admin_role_name=os.getenv("ADMIN_ROLE_NAME", "Admin").strip() or "Admin",
        log_channel_id=int(os.getenv("LOG_CHANNEL_ID", "0") or 0),
        guild_id=int(os.getenv("GUILD_ID", "0") or 0),
        db_path=os.getenv("DB_PATH", "data/wallet.sqlite3").strip(),
        log_file_path=os.getenv("LOG_FILE_PATH", "logs/wallet_audit.log").strip(),
    )
