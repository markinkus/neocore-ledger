"""Tests for ledger models and engine behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from neocore.exceptions import (
    AccountNotFoundError,
    CurrencyMismatchError,
    InsufficientFundsError,
    UnbalancedTransactionError,
)
from neocore.ledger.engine import LedgerEngine, OverdraftPolicy, PostingInstruction
from neocore.ledger.models import Account, AccountType, Entry, EntryType, Transaction
from neocore.ledger.store import LedgerStore, MemoryStore, SQLiteStore
from neocore.money import Money


def _entry(*, account_id: str, kind: EntryType, amount: str, currency: str = "EUR") -> Entry:
    return Entry(
        id=f"e-{account_id}-{kind.value}",
        account_id=account_id,
        entry_type=kind,
        amount=Money(Decimal(amount), currency),
        transaction_id="tx-1",
        created_at=datetime.now(tz=UTC),
    )


def test_account_normal_balance_mapping() -> None:
    account = Account(
        id="cash",
        name="Cash",
        account_type=AccountType.ASSET,
        currency="EUR",
        parent_id=None,
        metadata={},
    )
    assert account.normal_balance() is EntryType.DEBIT


def test_entry_requires_positive_amount() -> None:
    with pytest.raises(ValueError):
        _entry(account_id="cash", kind=EntryType.DEBIT, amount="0")


def test_transaction_balanced_per_currency() -> None:
    tx = Transaction(
        id="tx-1",
        idempotency_key="k-1",
        description="balanced",
        entries=(
            _entry(account_id="cash", kind=EntryType.DEBIT, amount="10.00"),
            _entry(account_id="bank", kind=EntryType.CREDIT, amount="10.00"),
        ),
        created_at=datetime.now(tz=UTC),
        metadata={},
    )
    assert tx.id == "tx-1"


def test_transaction_unbalanced_raises_structured_exception() -> None:
    with pytest.raises(UnbalancedTransactionError) as exc:
        Transaction(
            id="tx-1",
            idempotency_key="k-1",
            description="unbalanced",
            entries=(
                _entry(account_id="cash", kind=EntryType.DEBIT, amount="10.00"),
                _entry(account_id="bank", kind=EntryType.CREDIT, amount="9.00"),
            ),
            created_at=datetime.now(tz=UTC),
            metadata={},
        )

    assert exc.value.currency == "EUR"
    assert exc.value.debit_total == Decimal("10.00")
    assert exc.value.credit_total == Decimal("9.00")
    assert exc.value.difference == Decimal("1.00")


def test_transaction_balances_independently_by_currency() -> None:
    tx = Transaction(
        id="tx-1",
        idempotency_key="k-1",
        description="balanced multi-currency",
        entries=(
            _entry(account_id="cash-eur", kind=EntryType.DEBIT, amount="10.00", currency="EUR"),
            _entry(account_id="bank-eur", kind=EntryType.CREDIT, amount="10.00", currency="EUR"),
            _entry(account_id="cash-usd", kind=EntryType.DEBIT, amount="4.50", currency="USD"),
            _entry(account_id="bank-usd", kind=EntryType.CREDIT, amount="4.50", currency="USD"),
        ),
        created_at=datetime.now(tz=UTC),
        metadata={},
    )

    assert len(tx.entries) == 4


@pytest.fixture(params=["memory", "sqlite"])
def engine(request: pytest.FixtureRequest, tmp_path: Path) -> LedgerEngine:
    store: LedgerStore = (
        MemoryStore() if request.param == "memory" else SQLiteStore(tmp_path / "engine.sqlite")
    )
    return LedgerEngine(store)


def _create_base_accounts(engine: LedgerEngine) -> None:
    engine.create_account(
        id="cash",
        name="Cash",
        account_type=AccountType.ASSET,
        currency="EUR",
        parent_id=None,
        metadata={},
    )
    engine.create_account(
        id="bank",
        name="Bank",
        account_type=AccountType.LIABILITY,
        currency="EUR",
        parent_id=None,
        metadata={},
    )


def _posting(account_id: str, entry_type: EntryType, amount: str) -> PostingInstruction:
    return PostingInstruction(
        account_id=account_id,
        entry_type=entry_type,
        amount=Money(Decimal(amount), "EUR"),
    )


def test_engine_create_account_validates_parent(engine: LedgerEngine) -> None:
    with pytest.raises(AccountNotFoundError):
        engine.create_account(
            id="child",
            name="Child",
            account_type=AccountType.ASSET,
            currency="EUR",
            parent_id="missing",
            metadata={},
        )


def test_engine_post_is_idempotent(engine: LedgerEngine) -> None:
    _create_base_accounts(engine)

    tx1 = engine.post(
        idempotency_key="same-key",
        description="first",
        entries=[
            _posting("cash", EntryType.DEBIT, "10.00"),
            _posting("bank", EntryType.CREDIT, "10.00"),
        ],
        metadata={"source": "test"},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )
    tx2 = engine.post(
        idempotency_key="same-key",
        description="second",
        entries=[
            _posting("cash", EntryType.DEBIT, "20.00"),
            _posting("bank", EntryType.CREDIT, "20.00"),
        ],
        metadata={},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )

    assert tx2 == tx1
    assert len(engine.get_statement("cash")) == 1


def test_engine_post_rejects_currency_mismatch(engine: LedgerEngine) -> None:
    _create_base_accounts(engine)

    with pytest.raises(CurrencyMismatchError):
        engine.post(
            idempotency_key="mismatch",
            description="mismatch",
            entries=[
                PostingInstruction(
                    account_id="cash",
                    entry_type=EntryType.DEBIT,
                    amount=Money(Decimal("10.00"), "USD"),
                ),
                _posting("bank", EntryType.CREDIT, "10.00"),
            ],
            metadata={},
        )


def test_engine_post_enforces_overdraft_on_asset_debit(engine: LedgerEngine) -> None:
    _create_base_accounts(engine)

    engine.post(
        idempotency_key="funding",
        description="fund cash",
        entries=[
            _posting("bank", EntryType.DEBIT, "50.00"),
            _posting("cash", EntryType.CREDIT, "50.00"),
        ],
        metadata={},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )

    with pytest.raises(InsufficientFundsError) as exc:
        engine.post(
            idempotency_key="spend",
            description="spend",
            entries=[
                _posting("cash", EntryType.DEBIT, "60.00"),
                _posting("bank", EntryType.CREDIT, "60.00"),
            ],
            metadata={},
            overdraft_policy=OverdraftPolicy.strict(),
        )

    assert exc.value.available == Decimal("50.00")
    assert exc.value.required == Decimal("60.00")


def test_engine_get_balance_and_statement(engine: LedgerEngine) -> None:
    _create_base_accounts(engine)
    engine.post(
        idempotency_key="k1",
        description="first",
        entries=[
            _posting("cash", EntryType.DEBIT, "10.00"),
            _posting("bank", EntryType.CREDIT, "10.00"),
        ],
        metadata={},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )
    engine.post(
        idempotency_key="k2",
        description="second",
        entries=[
            _posting("cash", EntryType.CREDIT, "3.00"),
            _posting("bank", EntryType.DEBIT, "3.00"),
        ],
        metadata={},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )

    assert engine.get_balance("cash").amount == Decimal("7.00")
    statement = engine.get_statement("cash")
    assert [line.balance_after.amount for line in statement] == [Decimal("10.00"), Decimal("7.00")]


def test_engine_reconcile_returns_balanced_report(engine: LedgerEngine) -> None:
    _create_base_accounts(engine)
    engine.post(
        idempotency_key="k1",
        description="first",
        entries=[
            _posting("cash", EntryType.DEBIT, "10.00"),
            _posting("bank", EntryType.CREDIT, "10.00"),
        ],
        metadata={},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )

    report = engine.reconcile(["cash", "bank"])
    assert report.is_balanced is True
