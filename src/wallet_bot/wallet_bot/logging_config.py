from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_file_path: str) -> logging.Logger:
    # Keep logging simple and explicit.
    # We make sure the parent directory exists first.
    log_path = Path(log_file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    return logging.getLogger("wallet-bot")
