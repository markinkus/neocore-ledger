"""Tests for NeoCore public invariants."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from neocore.exceptions import (
    CurrencyMismatchError,
    DuplicateTransactionError,
    InsufficientFundsError,
    UnbalancedTransactionError,
)
from neocore.invariants import (
    OverdraftPolicy,
    assert_balanced,
    assert_currency_consistency,
    assert_idempotent,
    assert_no_negative_balance,
    assert_valid_account_type_for_entry,
)
from neocore.ledger.models import Account, AccountType, Entry, EntryType, Transaction
from neocore.ledger.store import MemoryStore
from neocore.money import Money


def _entry(
    *,
    tx_id: str,
    account_id: str,
    kind: EntryType,
    amount: str,
    currency: str = "EUR",
) -> Entry:
    return Entry(
        id=f"{tx_id}:{account_id}:{kind.value}",
        account_id=account_id,
        entry_type=kind,
        amount=Money(Decimal(amount), currency),
        transaction_id=tx_id,
        created_at=datetime.now(tz=UTC),
    )


def test_assert_balanced_passes_for_balanced_entries() -> None:
    entries = (
        _entry(tx_id="t1", account_id="cash", kind=EntryType.DEBIT, amount="10.00"),
        _entry(tx_id="t1", account_id="bank", kind=EntryType.CREDIT, amount="10.00"),
    )

    assert_balanced(entries)


def test_assert_balanced_raises_for_unbalanced_entries() -> None:
    entries = (
        _entry(tx_id="t1", account_id="cash", kind=EntryType.DEBIT, amount="10.00"),
        _entry(tx_id="t1", account_id="bank", kind=EntryType.CREDIT, amount="9.00"),
    )

    with pytest.raises(UnbalancedTransactionError):
        assert_balanced(entries)


def test_assert_currency_consistency_raises() -> None:
    account = Account(
        id="cash",
        name="Cash",
        account_type=AccountType.ASSET,
        currency="EUR",
        parent_id=None,
        metadata={},
    )

    with pytest.raises(CurrencyMismatchError):
        assert_currency_consistency(account, Money(Decimal("10.00"), "USD"))


def test_assert_no_negative_balance_strict_raises() -> None:
    with pytest.raises(InsufficientFundsError) as exc:
        assert_no_negative_balance(
            account_id="cash",
            balance=Money(Decimal("-1.00"), "EUR"),
            policy=OverdraftPolicy.strict(),
        )

    assert exc.value.available == Decimal("-1.00")
    assert exc.value.required == Decimal("0")


def test_assert_no_negative_balance_limit_allows_within_limit() -> None:
    assert_no_negative_balance(
        account_id="cash",
        balance=Money(Decimal("-2.00"), "EUR"),
        policy=OverdraftPolicy.overdraft_limit(Decimal("5.00")),
    )


def test_assert_no_negative_balance_limit_raises_if_exceeded() -> None:
    with pytest.raises(InsufficientFundsError):
        assert_no_negative_balance(
            account_id="cash",
            balance=Money(Decimal("-6.00"), "EUR"),
            policy=OverdraftPolicy.overdraft_limit(Decimal("5.00")),
        )


def test_assert_idempotent_detects_duplicate_key() -> None:
    store = MemoryStore()
    store.create_account(
        Account(
            id="cash",
            name="Cash",
            account_type=AccountType.ASSET,
            currency="EUR",
            parent_id=None,
            metadata={},
        )
    )
    store.create_account(
        Account(
            id="bank",
            name="Bank",
            account_type=AccountType.LIABILITY,
            currency="EUR",
            parent_id=None,
            metadata={},
        )
    )
    tx = Transaction(
        id="tx-1",
        idempotency_key="dup-key",
        description="x",
        entries=(
            _entry(tx_id="tx-1", account_id="cash", kind=EntryType.DEBIT, amount="1.00"),
            _entry(tx_id="tx-1", account_id="bank", kind=EntryType.CREDIT, amount="1.00"),
        ),
        created_at=datetime.now(tz=UTC),
        metadata={},
    )
    store.append_transaction(tx)

    with pytest.raises(DuplicateTransactionError):
        assert_idempotent("dup-key", store)


def test_assert_valid_account_type_for_entry_warns_on_unusual_side() -> None:
    account = Account(
        id="cash",
        name="Cash",
        account_type=AccountType.ASSET,
        currency="EUR",
        parent_id=None,
        metadata={},
    )

    with pytest.warns(UserWarning):
        assert_valid_account_type_for_entry(account, EntryType.CREDIT)
