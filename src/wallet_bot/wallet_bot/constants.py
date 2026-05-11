from __future__ import annotations

# We store amounts as integer minor units to preserve 4 decimal places exactly.
AMOUNT_SCALE = 10_000

# These are the fields that behave like decimal balances.
DECIMAL_FIELDS = {
    "gp_wallet",
    "irl_wallet",
    "deposit_wallet",
    "cuts_amount",
    "total_generated",
}

# These are integer counters.
INTEGER_FIELDS = {
    "loyalty_tokens",
    "completed_tickets",
}

# These represent hold requests, not wallet balances directly.
HOLD_FIELDS = {
    "hold_gp",
    "hold_irl",
}

ADD_ALLOWED_FIELDS = DECIMAL_FIELDS | INTEGER_FIELDS | HOLD_FIELDS
SET_ALLOWED_FIELDS = DECIMAL_FIELDS | INTEGER_FIELDS
AUTH_DESTINATION_FIELDS = DECIMAL_FIELDS
TRANSFER_ALLOWED_FIELDS = {"gp_wallet", "deposit_wallet"}

MAX_TICKET_ID_LENGTH = 64
MAX_COLLECTOR_LENGTH = 120
MAX_NOTE_LENGTH = 500
MAX_AUDIT_PREVIEW_LENGTH = 140
