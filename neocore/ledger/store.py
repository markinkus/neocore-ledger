"""Ledger store protocol and implementations."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

from neocore.exceptions import AccountNotFoundError, DuplicateTransactionError
from neocore.ledger.models import Account, AccountType, Entry, EntryType, Metadata, Transaction
from neocore.money import Money


class LedgerStore(Protocol):
    """Storage interface for append-only ledger persistence."""

    def create_account(self, account: Account) -> None:
        """Persist a new account. Must reject duplicate identifiers."""

    def get_account(self, account_id: str) -> Account | None:
        """Return an account by identifier, or None if absent."""

    def list_accounts(self) -> list[Account]:
        """Return all accounts."""

    def append_transaction(self, transaction: Transaction) -> None:
        """Atomically persist transaction and entries in append-only mode."""

    def get_transaction(self, transaction_id: str) -> Transaction | None:
        """Return a transaction by identifier, or None if absent."""

    def get_transaction_by_idempotency_key(self, key: str) -> Transaction | None:
        """Lookup transaction associated with idempotency key."""

    def list_entries(
        self,
        account_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Entry]:
        """Return account entries ordered chronologically."""


class MemoryStore(LedgerStore):
    """Thread-safe in-memory implementation with DB-like constraints."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._accounts: dict[str, Account] = {}
        self._transactions: dict[str, Transaction] = {}
        self._idempotency: dict[str, str] = {}
        self._entries_by_account: dict[str, list[Entry]] = defaultdict(list)

    def create_account(self, account: Account) -> None:
        with self._lock:
            if account.id in self._accounts:
                raise ValueError(f"account already exists: {account.id}")
            if account.parent_id is not None and account.parent_id not in self._accounts:
                raise AccountNotFoundError(account_id=account.parent_id)
            self._accounts[account.id] = account

    def get_account(self, account_id: str) -> Account | None:
        with self._lock:
            return self._accounts.get(account_id)

    def list_accounts(self) -> list[Account]:
        with self._lock:
            return list(self._accounts.values())

    def append_transaction(self, transaction: Transaction) -> None:
        with self._lock:
            if transaction.id in self._transactions:
                raise ValueError(f"transaction already exists: {transaction.id}")

            existing_tx_id = self._idempotency.get(transaction.idempotency_key)
            if existing_tx_id is not None:
                raise DuplicateTransactionError(
                    idempotency_key=transaction.idempotency_key,
                    transaction_id=existing_tx_id,
                )

            for entry in transaction.entries:
                if entry.account_id not in self._accounts:
                    raise AccountNotFoundError(account_id=entry.account_id)

            self._transactions[transaction.id] = transaction
            self._idempotency[transaction.idempotency_key] = transaction.id
            for entry in transaction.entries:
                self._entries_by_account[entry.account_id].append(entry)

    def get_transaction(self, transaction_id: str) -> Transaction | None:
        with self._lock:
            return self._transactions.get(transaction_id)

    def get_transaction_by_idempotency_key(self, key: str) -> Transaction | None:
        with self._lock:
            tx_id = self._idempotency.get(key)
            if tx_id is None:
                return None
            return self._transactions[tx_id]

    def list_entries(
        self,
        account_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Entry]:
        with self._lock:
            entries = list(self._entries_by_account.get(account_id, ()))
        filtered = [
            entry
            for entry in entries
            if (since is None or entry.created_at >= since)
            and (until is None or entry.created_at <= until)
        ]
        filtered.sort(key=lambda item: (item.created_at, item.id))
        return filtered


class SQLiteStore(LedgerStore):
    """SQLite-backed store with explicit write locking and append-only entries."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    parent_id TEXT NULL,
                    metadata TEXT NOT NULL,
                    FOREIGN KEY(parent_id) REFERENCES accounts(id)
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES accounts(id),
                    FOREIGN KEY(transaction_id) REFERENCES transactions(id)
                );
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    key TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL UNIQUE,
                    FOREIGN KEY(transaction_id) REFERENCES transactions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_entries_account_created
                    ON entries(account_id, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_entries_transaction
                    ON entries(transaction_id, id);
                """
            )
            self._conn.commit()

    def create_account(self, account: Account) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """
                    INSERT INTO accounts(id, name, account_type, currency, parent_id, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account.id,
                        account.name,
                        account.account_type.value,
                        account.currency,
                        account.parent_id,
                        _to_json(account.metadata),
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                raise ValueError(f"account already exists or invalid parent: {account.id}") from exc

    def get_account(self, account_id: str) -> Account | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, name, account_type, currency, parent_id, metadata
                FROM accounts
                WHERE id = ?
                """,
                (account_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_account(row)

    def list_accounts(self) -> list[Account]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, name, account_type, currency, parent_id, metadata
                FROM accounts
                ORDER BY id
                """
            ).fetchall()
        return [_row_to_account(row) for row in rows]

    def append_transaction(self, transaction: Transaction) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._lookup_transaction_id_by_key_locked(transaction.idempotency_key)
                if existing is not None:
                    raise DuplicateTransactionError(
                        idempotency_key=transaction.idempotency_key,
                        transaction_id=existing,
                    )

                if self._conn.execute(
                    "SELECT 1 FROM transactions WHERE id = ?",
                    (transaction.id,),
                ).fetchone():
                    raise ValueError(f"transaction already exists: {transaction.id}")

                for entry in transaction.entries:
                    account_exists = self._conn.execute(
                        "SELECT 1 FROM accounts WHERE id = ?",
                        (entry.account_id,),
                    ).fetchone()
                    if account_exists is None:
                        raise AccountNotFoundError(account_id=entry.account_id)

                self._conn.execute(
                    """
                    INSERT INTO transactions(id, idempotency_key, description, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        transaction.id,
                        transaction.idempotency_key,
                        transaction.description,
                        transaction.created_at.isoformat(),
                        _to_json(transaction.metadata),
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO idempotency_keys(key, transaction_id)
                    VALUES (?, ?)
                    """,
                    (transaction.idempotency_key, transaction.id),
                )
                self._conn.executemany(
                    """
                    INSERT INTO entries(
                        id, account_id, entry_type, amount, currency, transaction_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            entry.id,
                            entry.account_id,
                            entry.entry_type.value,
                            str(entry.amount.amount),
                            entry.amount.currency,
                            entry.transaction_id,
                            entry.created_at.isoformat(),
                        )
                        for entry in transaction.entries
                    ],
                )
                self._conn.commit()
            except DuplicateTransactionError:
                self._conn.rollback()
                raise
            except (AccountNotFoundError, ValueError):
                self._conn.rollback()
                raise
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                raise ValueError("failed to persist transaction") from exc

    def get_transaction(self, transaction_id: str) -> Transaction | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, idempotency_key, description, created_at, metadata
                FROM transactions
                WHERE id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_transaction_locked(row)

    def get_transaction_by_idempotency_key(self, key: str) -> Transaction | None:
        with self._lock:
            tx_id = self._lookup_transaction_id_by_key_locked(key)
            if tx_id is None:
                return None
            row = self._conn.execute(
                """
                SELECT id, idempotency_key, description, created_at, metadata
                FROM transactions
                WHERE id = ?
                """,
                (tx_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - defensive guard
                return None
            return self._row_to_transaction_locked(row)

    def list_entries(
        self,
        account_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Entry]:
        query = [
            "SELECT id, account_id, entry_type, amount, currency, transaction_id, created_at",
            "FROM entries",
            "WHERE account_id = ?",
        ]
        params: list[str] = [account_id]
        if since is not None:
            query.append("AND created_at >= ?")
            params.append(since.isoformat())
        if until is not None:
            query.append("AND created_at <= ?")
            params.append(until.isoformat())
        query.append("ORDER BY created_at ASC, id ASC")

        with self._lock:
            rows = self._conn.execute("\n".join(query), params).fetchall()
        return [_row_to_entry(row) for row in rows]

    def _lookup_transaction_id_by_key_locked(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT transaction_id FROM idempotency_keys WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return cast(str, row["transaction_id"])

    def _row_to_transaction_locked(self, row: sqlite3.Row) -> Transaction:
        entries_rows = self._conn.execute(
            """
            SELECT id, account_id, entry_type, amount, currency, transaction_id, created_at
            FROM entries
            WHERE transaction_id = ?
            ORDER BY rowid ASC
            """,
            (cast(str, row["id"]),),
        ).fetchall()
        entries = tuple(_row_to_entry(entry_row) for entry_row in entries_rows)
        return Transaction(
            id=cast(str, row["id"]),
            idempotency_key=cast(str, row["idempotency_key"]),
            description=cast(str, row["description"]),
            entries=entries,
            created_at=datetime.fromisoformat(cast(str, row["created_at"])),
            metadata=_from_json(cast(str, row["metadata"])),
        )


def _to_json(metadata: Metadata) -> str:
    return json.dumps(dict(metadata), separators=(",", ":"), sort_keys=True)


def _from_json(payload: str) -> dict[str, str | int | bool | Decimal | None]:
    loaded = cast(dict[str, object], json.loads(payload))
    normalized: dict[str, str | int | bool | Decimal | None] = {}
    for key, value in loaded.items():
        if isinstance(value, bool | int | str) or value is None:
            normalized[key] = value
        else:
            normalized[key] = str(value)
    return normalized


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        id=cast(str, row["id"]),
        name=cast(str, row["name"]),
        account_type=AccountType(cast(str, row["account_type"])),
        currency=cast(str, row["currency"]),
        parent_id=cast(str | None, row["parent_id"]),
        metadata=_from_json(cast(str, row["metadata"])),
    )


def _row_to_entry(row: sqlite3.Row) -> Entry:
    return Entry(
        id=cast(str, row["id"]),
        account_id=cast(str, row["account_id"]),
        entry_type=EntryType(cast(str, row["entry_type"])),
        amount=Money(Decimal(cast(str, row["amount"])), cast(str, row["currency"])),
        transaction_id=cast(str, row["transaction_id"]),
        created_at=datetime.fromisoformat(cast(str, row["created_at"])),
    )


__all__ = ["LedgerStore", "MemoryStore", "SQLiteStore"]
