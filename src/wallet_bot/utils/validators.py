from __future__ import annotations

from typing import Optional

from wallet_bot.constants import (
    MAX_COLLECTOR_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_TICKET_ID_LENGTH,
)


def validate_optional_text(value: Optional[str], *, label: str, max_length: int) -> Optional[str]:
    # We keep text cleanup very light on purpose.
    # The goal is to reject bad or oversized input, not rewrite the user's note.
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    if len(cleaned) > max_length:
        raise ValueError(f"{label} is too long. Maximum length is {max_length} characters.")

    return cleaned


def validate_ticket_id(ticket_id: Optional[str]) -> Optional[str]:
    return validate_optional_text(ticket_id, label="ticket_id", max_length=MAX_TICKET_ID_LENGTH)


def validate_collector(collector: Optional[str]) -> Optional[str]:
    return validate_optional_text(collector, label="collector", max_length=MAX_COLLECTOR_LENGTH)


def validate_note(note: Optional[str]) -> Optional[str]:
    return validate_optional_text(note, label="note", max_length=MAX_NOTE_LENGTH)
