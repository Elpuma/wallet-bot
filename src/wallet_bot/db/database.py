from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from wallet_bot.constants import (
    ADD_ALLOWED_FIELDS,
    AUTH_DESTINATION_FIELDS,
    DECIMAL_FIELDS,
    INTEGER_FIELDS,
    TRANSFER_ALLOWED_FIELDS,
)
from wallet_bot.utils.amounts import decimal_to_units, fmt_amount, units_to_decimal
from wallet_bot.utils.discord_helpers import parse_json_safe

logger = logging.getLogger("wallet-bot")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class HoldSummaryRow:
    user_id: str
    username: str
    hold_count: int
    gp_on_hold_units: int
    irl_on_hold_units: int


class WalletDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        # timeout helps reduce "database is locked" noise during short bursts.
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        return conn

    @contextmanager
    def _write_transaction(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._write_transaction() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS wallets (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    gp_wallet_units INTEGER NOT NULL DEFAULT 0,
                    irl_wallet_units INTEGER NOT NULL DEFAULT 0,
                    deposit_wallet_units INTEGER NOT NULL DEFAULT 0,
                    cuts_amount_units INTEGER NOT NULL DEFAULT 0,
                    loyalty_tokens INTEGER NOT NULL DEFAULT 0,
                    completed_tickets INTEGER NOT NULL DEFAULT 0,
                    total_generated_units INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS hold_entries (
                    hold_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    currency TEXT NOT NULL CHECK(currency IN ('GP', 'IRL')),
                    amount_units INTEGER NOT NULL,
                    ticket_id TEXT,
                    collector_text TEXT,
                    status TEXT NOT NULL CHECK(status IN ('ON_HOLD', 'AUTHENTICATED', 'REVERSED')),
                    created_by TEXT NOT NULL,
                    authenticated_by TEXT,
                    reversed_by TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    note TEXT,
                    FOREIGN KEY(user_id) REFERENCES wallets(user_id)
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    field_name TEXT,
                    amount_units INTEGER,
                    currency TEXT,
                    source_wallet TEXT,
                    target_wallet TEXT,
                    ticket_id TEXT,
                    collector_text TEXT,
                    note TEXT,
                    performed_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reversed_transaction_id TEXT,
                    extra_json TEXT,
                    FOREIGN KEY(user_id) REFERENCES wallets(user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_hold_entries_user_status
                ON hold_entries(user_id, status);

                CREATE INDEX IF NOT EXISTS idx_transactions_reversed_transaction_id
                ON transactions(reversed_transaction_id);

                CREATE INDEX IF NOT EXISTS idx_transactions_user_created_at
                ON transactions(user_id, created_at);
                """
            )
        logger.info("Database initialized at %s", self.db_path)

    def ensure_wallet(self, user_id: str, username: str) -> None:
        now = utc_now_iso()
        with self._write_transaction() as conn:
            conn.execute(
                """
                INSERT INTO wallets (user_id, username, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    updated_at = excluded.updated_at
                """,
                (user_id, username, now, now),
            )

    def get_wallet(self, user_id: str) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("Wallet not found.")
            return row

    def get_hold_entries(self, user_id: str, status: str = "ON_HOLD") -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT *
                FROM hold_entries
                WHERE user_id = ? AND status = ?
                ORDER BY created_at ASC
                """,
                (user_id, status),
            ).fetchall()

    def list_users_with_holds(self) -> List[HoldSummaryRow]:
        # We aggregate using integer units, not REAL, so totals stay exact.
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    w.user_id,
                    w.username,
                    COUNT(h.hold_id) AS hold_count,
                    COALESCE(SUM(CASE WHEN h.currency = 'GP' THEN h.amount_units ELSE 0 END), 0) AS gp_on_hold_units,
                    COALESCE(SUM(CASE WHEN h.currency = 'IRL' THEN h.amount_units ELSE 0 END), 0) AS irl_on_hold_units
                FROM wallets w
                JOIN hold_entries h ON w.user_id = h.user_id
                WHERE h.status = 'ON_HOLD'
                GROUP BY w.user_id, w.username
                ORDER BY w.username COLLATE NOCASE ASC
                """
            ).fetchall()

        return [
            HoldSummaryRow(
                user_id=row["user_id"],
                username=row["username"],
                hold_count=row["hold_count"],
                gp_on_hold_units=row["gp_on_hold_units"],
                irl_on_hold_units=row["irl_on_hold_units"],
            )
            for row in rows
        ]

    def _field_column(self, field_name: str) -> str:
        if field_name in DECIMAL_FIELDS:
            return f"{field_name}_units"
        if field_name in INTEGER_FIELDS:
            return field_name
        raise ValueError(f"Unsupported field_name: {field_name}")

    def _log_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        action_type: str,
        performed_by: str,
        field_name: Optional[str] = None,
        amount_units: Optional[int] = None,
        currency: Optional[str] = None,
        source_wallet: Optional[str] = None,
        target_wallet: Optional[str] = None,
        ticket_id: Optional[str] = None,
        collector_text: Optional[str] = None,
        note: Optional[str] = None,
        reversed_transaction_id: Optional[str] = None,
        extra_json: Optional[Dict[str, Any]] = None,
    ) -> str:
        transaction_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO transactions (
                transaction_id, user_id, action_type, field_name, amount_units, currency,
                source_wallet, target_wallet, ticket_id, collector_text, note,
                performed_by, created_at, reversed_transaction_id, extra_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                user_id,
                action_type,
                field_name,
                amount_units,
                currency,
                source_wallet,
                target_wallet,
                ticket_id,
                collector_text,
                note,
                performed_by,
                utc_now_iso(),
                reversed_transaction_id,
                json.dumps(extra_json or {}),
            ),
        )
        return transaction_id

    def add_to_field(
        self,
        *,
        user_id: str,
        username: str,
        field_name: str,
        amount,
        performed_by: str,
        note: Optional[str] = None,
        ticket_id: Optional[str] = None,
        collector_text: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        if field_name not in ADD_ALLOWED_FIELDS:
            raise ValueError("Unsupported field_name for add operation.")

        self.ensure_wallet(user_id, username)
        now = utc_now_iso()
        hold_id: Optional[str] = None

        with self._write_transaction() as conn:
            row = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("Wallet not found after ensure_wallet.")

            if field_name in DECIMAL_FIELDS:
                amount_units = decimal_to_units(amount)
                column = self._field_column(field_name)
                old_units = int(row[column])
                new_units = old_units + amount_units

                conn.execute(
                    f"UPDATE wallets SET {column} = ?, updated_at = ? WHERE user_id = ?",
                    (new_units, now, user_id),
                )
                tx_id = self._log_transaction(
                    conn,
                    user_id=user_id,
                    action_type="ADD",
                    field_name=field_name,
                    amount_units=amount_units,
                    performed_by=performed_by,
                    note=note,
                    ticket_id=ticket_id,
                    collector_text=collector_text,
                    extra_json={
                        "old_units": old_units,
                        "new_units": new_units,
                        "old_value": fmt_amount(units_to_decimal(old_units)),
                        "new_value": fmt_amount(units_to_decimal(new_units)),
                    },
                )
                return tx_id, None

            if field_name in INTEGER_FIELDS:
                amount_units = int(amount)
                old_value = int(row[field_name])
                new_value = old_value + amount_units

                conn.execute(
                    f"UPDATE wallets SET {field_name} = ?, updated_at = ? WHERE user_id = ?",
                    (new_value, now, user_id),
                )
                tx_id = self._log_transaction(
                    conn,
                    user_id=user_id,
                    action_type="ADD",
                    field_name=field_name,
                    amount_units=amount_units,
                    performed_by=performed_by,
                    note=note,
                    ticket_id=ticket_id,
                    collector_text=collector_text,
                    extra_json={"old_value": old_value, "new_value": new_value},
                )
                return tx_id, None

            if field_name in {"hold_gp", "hold_irl"}:
                amount_units = decimal_to_units(amount)
                hold_currency = "GP" if field_name == "hold_gp" else "IRL"
                hold_id = str(uuid.uuid4())

                conn.execute(
                    """
                    INSERT INTO hold_entries (
                        hold_id, user_id, currency, amount_units, ticket_id, collector_text,
                        status, created_by, created_at, note
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'ON_HOLD', ?, ?, ?)
                    """,
                    (
                        hold_id,
                        user_id,
                        hold_currency,
                        amount_units,
                        ticket_id,
                        collector_text,
                        performed_by,
                        now,
                        note,
                    ),
                )
                tx_id = self._log_transaction(
                    conn,
                    user_id=user_id,
                    action_type="ADD_HOLD",
                    field_name=field_name,
                    amount_units=amount_units,
                    performed_by=performed_by,
                    note=note,
                    ticket_id=ticket_id,
                    collector_text=collector_text,
                    currency=hold_currency,
                    extra_json={"hold_id": hold_id},
                )
                return tx_id, hold_id

            raise ValueError("Unsupported field_name for add operation.")

    def set_field(
        self,
        *,
        user_id: str,
        username: str,
        field_name: str,
        value,
        performed_by: str,
        note: Optional[str] = None,
    ) -> str:
        if field_name not in DECIMAL_FIELDS | INTEGER_FIELDS:
            raise ValueError("Unsupported field_name for set operation.")

        self.ensure_wallet(user_id, username)
        now = utc_now_iso()

        with self._write_transaction() as conn:
            row = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("Wallet not found after ensure_wallet.")

            if field_name in DECIMAL_FIELDS:
                new_units = decimal_to_units(value)
                if new_units < 0:
                    raise ValueError("Negative values are not allowed.")

                column = self._field_column(field_name)
                old_units = int(row[column])

                conn.execute(
                    f"UPDATE wallets SET {column} = ?, updated_at = ? WHERE user_id = ?",
                    (new_units, now, user_id),
                )
                return self._log_transaction(
                    conn,
                    user_id=user_id,
                    action_type="SET",
                    field_name=field_name,
                    amount_units=new_units,
                    performed_by=performed_by,
                    note=note,
                    extra_json={
                        "old_units": old_units,
                        "new_units": new_units,
                        "old_value": fmt_amount(units_to_decimal(old_units)),
                        "new_value": fmt_amount(units_to_decimal(new_units)),
                    },
                )

            new_value = int(value)
            if new_value < 0:
                raise ValueError("Negative values are not allowed.")

            old_value = int(row[field_name])

            conn.execute(
                f"UPDATE wallets SET {field_name} = ?, updated_at = ? WHERE user_id = ?",
                (new_value, now, user_id),
            )
            return self._log_transaction(
                conn,
                user_id=user_id,
                action_type="SET",
                field_name=field_name,
                amount_units=new_value,
                performed_by=performed_by,
                note=note,
                extra_json={"old_value": old_value, "new_value": new_value},
            )

    def transfer_between_wallets(
        self,
        *,
        user_id: str,
        username: str,
        source_wallet: str,
        target_wallet: str,
        amount,
        performed_by: str,
        note: Optional[str] = None,
    ) -> str:
        if source_wallet == target_wallet:
            raise ValueError("Source and target wallets must be different.")

        if source_wallet not in TRANSFER_ALLOWED_FIELDS or target_wallet not in TRANSFER_ALLOWED_FIELDS:
            raise ValueError("Only gp_wallet and deposit_wallet are supported here.")

        self.ensure_wallet(user_id, username)
        now = utc_now_iso()
        amount_units = decimal_to_units(amount)

        with self._write_transaction() as conn:
            row = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("Wallet not found after ensure_wallet.")

            source_column = self._field_column(source_wallet)
            target_column = self._field_column(target_wallet)

            source_value = int(row[source_column])
            target_value = int(row[target_column])

            if source_value < amount_units:
                raise ValueError(f"Insufficient funds in {source_wallet}.")

            new_source = source_value - amount_units
            new_target = target_value + amount_units

            conn.execute(
                f"UPDATE wallets SET {source_column} = ?, {target_column} = ?, updated_at = ? WHERE user_id = ?",
                (new_source, new_target, now, user_id),
            )
            return self._log_transaction(
                conn,
                user_id=user_id,
                action_type="TRANSFER",
                amount_units=amount_units,
                performed_by=performed_by,
                source_wallet=source_wallet,
                target_wallet=target_wallet,
                note=note,
                extra_json={
                    "old_source_units": source_value,
                    "new_source_units": new_source,
                    "old_target_units": target_value,
                    "new_target_units": new_target,
                },
            )

    def authenticate_hold(
        self,
        *,
        hold_id: str,
        destination_field: str,
        performed_by: str,
        note: Optional[str] = None,
    ) -> str:
        if destination_field not in AUTH_DESTINATION_FIELDS:
            raise ValueError("Unsupported destination field.")

        now = utc_now_iso()
        destination_column = self._field_column(destination_field)

        with self._write_transaction() as conn:
            hold = conn.execute("SELECT * FROM hold_entries WHERE hold_id = ?", (hold_id,)).fetchone()
            if hold is None:
                raise ValueError("Hold not found.")
            if hold["status"] != "ON_HOLD":
                raise ValueError("Only ON_HOLD entries can be authenticated.")

            wallet = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (hold["user_id"],)).fetchone()
            if wallet is None:
                raise ValueError("Wallet not found for hold owner.")

            amount_units = int(hold["amount_units"])
            old_destination = int(wallet[destination_column])
            new_destination = old_destination + amount_units

            conn.execute(
                f"UPDATE wallets SET {destination_column} = ?, updated_at = ? WHERE user_id = ?",
                (new_destination, now, hold["user_id"]),
            )
            conn.execute(
                """
                UPDATE hold_entries
                SET status = 'AUTHENTICATED', authenticated_by = ?, resolved_at = ?
                WHERE hold_id = ?
                """,
                (performed_by, now, hold_id),
            )
            return self._log_transaction(
                conn,
                user_id=hold["user_id"],
                action_type="AUTHENTICATE_HOLD",
                amount_units=amount_units,
                performed_by=performed_by,
                field_name=destination_field,
                currency=hold["currency"],
                ticket_id=hold["ticket_id"],
                collector_text=hold["collector_text"],
                note=note,
                extra_json={
                    "hold_id": hold_id,
                    "old_destination_units": old_destination,
                    "new_destination_units": new_destination,
                },
            )

    def _has_newer_related_transactions(self, conn: sqlite3.Connection, tx: sqlite3.Row) -> bool:
        # This is a safety guard against state drift.
        # If newer related transactions exist, reversing an older one can produce a bad final state.
        action_type = tx["action_type"]
        user_id = tx["user_id"]
        created_at = tx["created_at"]
        field_name = tx["field_name"]

        if action_type in {"ADD", "SET"} and field_name:
            newer = conn.execute(
                """
                SELECT 1
                FROM transactions
                WHERE user_id = ?
                  AND created_at > ?
                  AND action_type IN ('ADD', 'SET', 'TRANSFER', 'AUTHENTICATE_HOLD')
                  AND (
                        field_name = ?
                        OR source_wallet = ?
                        OR target_wallet = ?
                      )
                LIMIT 1
                """,
                (user_id, created_at, field_name, field_name, field_name),
            ).fetchone()
            return newer is not None

        if action_type == "TRANSFER":
            newer = conn.execute(
                """
                SELECT 1
                FROM transactions
                WHERE user_id = ?
                  AND created_at > ?
                  AND action_type IN ('ADD', 'SET', 'TRANSFER')
                  AND (
                        field_name IN (?, ?)
                        OR source_wallet IN (?, ?)
                        OR target_wallet IN (?, ?)
                      )
                LIMIT 1
                """,
                (
                    user_id,
                    created_at,
                    tx["source_wallet"],
                    tx["target_wallet"],
                    tx["source_wallet"],
                    tx["target_wallet"],
                    tx["source_wallet"],
                    tx["target_wallet"],
                ),
            ).fetchone()
            return newer is not None

        if action_type in {"ADD_HOLD", "AUTHENTICATE_HOLD"}:
            extra = parse_json_safe(tx["extra_json"])
            hold_id = extra.get("hold_id")
            if not hold_id:
                return True

            newer = conn.execute(
                """
                SELECT 1
                FROM transactions
                WHERE user_id = ?
                  AND created_at > ?
                  AND extra_json LIKE ?
                LIMIT 1
                """,
                (user_id, created_at, f'%"{hold_id}"%'),
            ).fetchone()
            return newer is not None

        return False

    def reverse_transaction(
        self,
        *,
        transaction_id: str,
        performed_by: str,
        note: Optional[str] = None,
    ) -> str:
        now = utc_now_iso()

        with self._write_transaction() as conn:
            tx = conn.execute(
                "SELECT * FROM transactions WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
            if tx is None:
                raise ValueError("Transaction not found.")

            existing_reverse = conn.execute(
                "SELECT transaction_id FROM transactions WHERE reversed_transaction_id = ?",
                (transaction_id,),
            ).fetchone()
            if existing_reverse:
                raise ValueError("This transaction has already been reversed.")

            if self._has_newer_related_transactions(conn, tx):
                raise ValueError(
                    "This transaction cannot be reversed safely because newer related transactions already exist."
                )

            wallet = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (tx["user_id"],)).fetchone()
            if wallet is None:
                raise ValueError("Wallet not found for this transaction.")

            action_type = tx["action_type"]
            amount_units = int(tx["amount_units"] or 0)
            extra = parse_json_safe(tx["extra_json"])

            if action_type == "ADD":
                field_name = tx["field_name"]
                if field_name in DECIMAL_FIELDS:
                    column = self._field_column(field_name)
                    current = int(wallet[column])
                    new_value = current - amount_units
                    if new_value < 0:
                        raise ValueError("Cannot reverse because it would create a negative balance.")
                    conn.execute(
                        f"UPDATE wallets SET {column} = ?, updated_at = ? WHERE user_id = ?",
                        (new_value, now, tx["user_id"]),
                    )
                elif field_name in INTEGER_FIELDS:
                    current = int(wallet[field_name])
                    new_value = current - amount_units
                    if new_value < 0:
                        raise ValueError("Cannot reverse because it would create a negative value.")
                    conn.execute(
                        f"UPDATE wallets SET {field_name} = ?, updated_at = ? WHERE user_id = ?",
                        (new_value, now, tx["user_id"]),
                    )
                else:
                    raise ValueError("This ADD transaction is not reversible with the current logic.")

            elif action_type == "SET":
                field_name = tx["field_name"]
                if field_name in DECIMAL_FIELDS:
                    old_units = extra.get("old_units")
                    if old_units is None:
                        raise ValueError("Original SET transaction does not contain old_units.")
                    column = self._field_column(field_name)
                    conn.execute(
                        f"UPDATE wallets SET {column} = ?, updated_at = ? WHERE user_id = ?",
                        (int(old_units), now, tx["user_id"]),
                    )
                elif field_name in INTEGER_FIELDS:
                    old_value = extra.get("old_value")
                    if old_value is None:
                        raise ValueError("Original SET transaction does not contain old_value.")
                    conn.execute(
                        f"UPDATE wallets SET {field_name} = ?, updated_at = ? WHERE user_id = ?",
                        (int(old_value), now, tx["user_id"]),
                    )
                else:
                    raise ValueError("This SET transaction is not reversible with the current logic.")

            elif action_type == "TRANSFER":
                source_wallet = tx["source_wallet"]
                target_wallet = tx["target_wallet"]

                source_column = self._field_column(source_wallet)
                target_column = self._field_column(target_wallet)

                source_current = int(wallet[source_column])
                target_current = int(wallet[target_column])

                new_source = source_current + amount_units
                new_target = target_current - amount_units
                if new_target < 0:
                    raise ValueError("Cannot reverse because it would create a negative balance.")

                conn.execute(
                    f"UPDATE wallets SET {source_column} = ?, {target_column} = ?, updated_at = ? WHERE user_id = ?",
                    (new_source, new_target, now, tx["user_id"]),
                )

            elif action_type == "ADD_HOLD":
                hold_id = extra.get("hold_id")
                if not hold_id:
                    raise ValueError("Original ADD_HOLD transaction does not contain hold_id.")

                hold = conn.execute("SELECT * FROM hold_entries WHERE hold_id = ?", (hold_id,)).fetchone()
                if hold is None:
                    raise ValueError("Hold entry not found.")
                if hold["status"] != "ON_HOLD":
                    raise ValueError("Only an active hold can be reversed.")

                conn.execute(
                    """
                    UPDATE hold_entries
                    SET status = 'REVERSED', reversed_by = ?, resolved_at = ?
                    WHERE hold_id = ?
                    """,
                    (performed_by, now, hold_id),
                )

            elif action_type == "AUTHENTICATE_HOLD":
                hold_id = extra.get("hold_id")
                field_name = tx["field_name"]
                if not hold_id or not field_name:
                    raise ValueError("Original AUTHENTICATE_HOLD transaction is incomplete.")

                hold = conn.execute("SELECT * FROM hold_entries WHERE hold_id = ?", (hold_id,)).fetchone()
                if hold is None:
                    raise ValueError("Hold entry not found.")

                column = self._field_column(field_name)
                current = int(wallet[column])
                new_value = current - amount_units
                if new_value < 0:
                    raise ValueError("Cannot reverse because it would create a negative balance.")

                conn.execute(
                    f"UPDATE wallets SET {column} = ?, updated_at = ? WHERE user_id = ?",
                    (new_value, now, tx["user_id"]),
                )
                conn.execute(
                    """
                    UPDATE hold_entries
                    SET status = 'ON_HOLD', authenticated_by = NULL, resolved_at = NULL
                    WHERE hold_id = ?
                    """,
                    (hold_id,),
                )
            else:
                raise ValueError(f"Reversal for action_type '{action_type}' is not implemented.")

            return self._log_transaction(
                conn,
                user_id=tx["user_id"],
                action_type="REVERSE",
                performed_by=performed_by,
                amount_units=amount_units,
                note=note,
                reversed_transaction_id=transaction_id,
                extra_json={"reversed_action_type": action_type},
            )

    def get_wallet_view(self, user_id: str) -> Dict[str, Any]:
        # This gives the bot layer a clean view with ready-to-display values.
        row = self.get_wallet(user_id)
        return {
            "user_id": row["user_id"],
            "username": row["username"],
            "gp_wallet": units_to_decimal(row["gp_wallet_units"]),
            "irl_wallet": units_to_decimal(row["irl_wallet_units"]),
            "deposit_wallet": units_to_decimal(row["deposit_wallet_units"]),
            "cuts_amount": units_to_decimal(row["cuts_amount_units"]),
            "loyalty_tokens": row["loyalty_tokens"],
            "completed_tickets": row["completed_tickets"],
            "total_generated": units_to_decimal(row["total_generated_units"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_hold_entries_view(self, user_id: str, status: str = "ON_HOLD") -> List[Dict[str, Any]]:
        rows = self.get_hold_entries(user_id, status)
        return [
            {
                "hold_id": row["hold_id"],
                "user_id": row["user_id"],
                "currency": row["currency"],
                "amount": units_to_decimal(row["amount_units"]),
                "ticket_id": row["ticket_id"],
                "collector_text": row["collector_text"],
                "status": row["status"],
                "created_by": row["created_by"],
                "authenticated_by": row["authenticated_by"],
                "reversed_by": row["reversed_by"],
                "created_at": row["created_at"],
                "resolved_at": row["resolved_at"],
                "note": row["note"],
            }
            for row in rows
        ]
