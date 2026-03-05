"""Tests for store implementations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from neocore.exceptions import DuplicateTransactionError
from neocore.ledger.models import Account, AccountType, Entry, EntryType, Transaction
from neocore.ledger.store import LedgerStore, MemoryStore, SQLiteStore
from neocore.money import Money


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> LedgerStore:
    if request.param == "memory":
        return MemoryStore()
    db_path = tmp_path / "ledger.sqlite"
    return SQLiteStore(db_path)


def _account(account_id: str, kind: AccountType = AccountType.ASSET) -> Account:
    return Account(
        id=account_id,
        name=account_id.title(),
        account_type=kind,
        currency="EUR",
        parent_id=None,
        metadata={},
    )


def _entry(
    *,
    entry_id: str,
    account_id: str,
    entry_type: EntryType,
    amount: str,
    transaction_id: str,
    created_at: datetime,
) -> Entry:
    return Entry(
        id=entry_id,
        account_id=account_id,
        entry_type=entry_type,
        amount=Money(Decimal(amount), "EUR"),
        transaction_id=transaction_id,
        created_at=created_at,
    )


def _transaction(
    *,
    tx_id: str,
    key: str,
    debit_account: str,
    credit_account: str,
    amount: str,
    created_at: datetime,
) -> Transaction:
    return Transaction(
        id=tx_id,
        idempotency_key=key,
        description="test tx",
        entries=(
            _entry(
                entry_id=f"{tx_id}-d",
                account_id=debit_account,
                entry_type=EntryType.DEBIT,
                amount=amount,
                transaction_id=tx_id,
                created_at=created_at,
            ),
            _entry(
                entry_id=f"{tx_id}-c",
                account_id=credit_account,
                entry_type=EntryType.CREDIT,
                amount=amount,
                transaction_id=tx_id,
                created_at=created_at,
            ),
        ),
        created_at=created_at,
        metadata={},
    )


def test_store_create_and_get_account(store: LedgerStore) -> None:
    account = _account("cash")
    store.create_account(account)

    loaded = store.get_account("cash")
    assert loaded == account


def test_store_rejects_duplicate_account_id(store: LedgerStore) -> None:
    account = _account("cash")
    store.create_account(account)

    with pytest.raises(ValueError):
        store.create_account(account)


def test_store_append_and_lookup_transaction(store: LedgerStore) -> None:
    store.create_account(_account("cash"))
    store.create_account(_account("bank", kind=AccountType.LIABILITY))

    tx = _transaction(
        tx_id="tx-1",
        key="key-1",
        debit_account="cash",
        credit_account="bank",
        amount="10.00",
        created_at=datetime.now(tz=UTC),
    )
    store.append_transaction(tx)

    loaded = store.get_transaction("tx-1")
    assert loaded == tx
    assert store.get_transaction_by_idempotency_key("key-1") == tx

    cash_entries = store.list_entries("cash")
    assert [entry.id for entry in cash_entries] == ["tx-1-d"]


def test_store_enforces_idempotency_uniqueness(store: LedgerStore) -> None:
    store.create_account(_account("cash"))
    store.create_account(_account("bank", kind=AccountType.LIABILITY))

    tx1 = _transaction(
        tx_id="tx-1",
        key="shared-key",
        debit_account="cash",
        credit_account="bank",
        amount="10.00",
        created_at=datetime.now(tz=UTC),
    )
    tx2 = _transaction(
        tx_id="tx-2",
        key="shared-key",
        debit_account="cash",
        credit_account="bank",
        amount="5.00",
        created_at=datetime.now(tz=UTC),
    )

    store.append_transaction(tx1)
    with pytest.raises(DuplicateTransactionError) as exc:
        store.append_transaction(tx2)

    assert exc.value.idempotency_key == "shared-key"
    assert exc.value.transaction_id == "tx-1"
    assert len(store.list_entries("cash")) == 1


def test_store_list_entries_with_time_window(store: LedgerStore) -> None:
    store.create_account(_account("cash"))
    store.create_account(_account("bank", kind=AccountType.LIABILITY))

    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = t1 + timedelta(days=1)

    tx1 = _transaction(
        tx_id="tx-1",
        key="key-1",
        debit_account="cash",
        credit_account="bank",
        amount="10.00",
        created_at=t1,
    )
    tx2 = _transaction(
        tx_id="tx-2",
        key="key-2",
        debit_account="cash",
        credit_account="bank",
        amount="20.00",
        created_at=t2,
    )

    store.append_transaction(tx1)
    store.append_transaction(tx2)

    entries = store.list_entries("cash", since=t2)
    assert [entry.transaction_id for entry in entries] == ["tx-2"]

    entries = store.list_entries("cash", until=t1)
    assert [entry.transaction_id for entry in entries] == ["tx-1"]
