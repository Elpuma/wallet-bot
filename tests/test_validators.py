import pytest

from wallet_bot.utils.validators import validate_note, validate_ticket_id


def test_validate_ticket_id():
    assert validate_ticket_id("  ABC-123  ") == "ABC-123"


def test_validate_note_rejects_long_text():
    with pytest.raises(ValueError):
        validate_note("x" * 501)
