# Wallet Bot

This project is a cleaned and split version of your original wallet bot.

## What changed in this version

The project now includes the fixes and improvements that were identified during the review:

1. The bot was split into a proper package with clear folders.
2. Wallet amounts are stored as integer minor units with 4 decimal precision.
3. SQLite is configured with WAL mode and transactional locking.
4. The `updated_at` timestamp issue was fixed.
5. Admin authorization now supports `ADMIN_ROLE_ID` and falls back to `ADMIN_ROLE_NAME`.
6. Safer reversal rules were added to reduce state drift.
7. Input length validation was added for notes and ticket fields.
8. The old prefix command was removed in favor of slash commands only.
9. The bot no longer requests the privileged `message_content` intent.
10. The set confirmation view now updates itself when it times out.

## Project structure

```text
wallet_bot_project/
├── .env.example
├── README.md
├── requirements.txt
├── run.py
├── src/
│   └── wallet_bot/
│       ├── __init__.py
│       ├── bot.py
│       ├── config.py
│       ├── constants.py
│       ├── logging_config.py
│       ├── commands/
│       │   └── wallet.py
│       ├── db/
│       │   └── database.py
│       ├── services/
│       │   └── audit.py
│       ├── utils/
│       │   ├── amounts.py
│       │   ├── discord_helpers.py
│       │   └── validators.py
│       └── views/
│           └── set_confirm_view.py
└── tests/
    ├── test_amounts.py
    └── test_validators.py
```

## Setup

### 1) Create a virtual environment

Windows:
```bash
python -m venv .venv
.venv\Scripts\activate
```

Linux / macOS:
```bash
python -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

### 3) Create your environment file

Copy `.env.example` to `.env` and fill in the values.

### 4) Run the bot

```bash
python run.py
```

## Notes about the database

This version stores wallet amounts using **4-decimal fixed precision** as integers under the hood.

Example:
- `1.0000` is stored as `10000`
- `10.2500` is stored as `102500`

This avoids floating point issues and keeps math exact.

## Notes about reversals

This version allows reversals, but it blocks certain risky cases when a newer related transaction already exists.  
That helps avoid silent wallet corruption caused by reversing old operations after newer dependent ones were already applied.

## Future improvements you can add later

1. PostgreSQL support
2. Alembic migrations
3. Unit tests for the database layer
4. Better admin dashboard or reporting commands
5. Export commands for audit history
