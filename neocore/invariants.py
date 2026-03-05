"""Public invariant checks for NeoCore.

Each assertion is designed as a reusable safety rail for integrators:
the goal is not only to reject invalid data, but to prevent silent accounting
drift that is expensive to debug after the fact.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from neocore.exceptions import (
    CurrencyMismatchError,
    DuplicateTransactionError,
    InsufficientFundsError,
    UnbalancedTransactionError,
)
from neocore.ledger.models import Account, Entry, EntryType
from neocore.ledger.store import LedgerStore
from neocore.money import Money


class OverdraftMode(StrEnum):
    """Overdraft policy mode for negative balances."""

    STRICT = "STRICT"
    ALLOW_OVERDRAFT = "ALLOW_OVERDRAFT"
    OVERDRAFT_LIMIT = "OVERDRAFT_LIMIT"


@dataclass(frozen=True, slots=True)
class OverdraftPolicy:
    """Policy used to decide when a negative balance is acceptable."""

    mode: OverdraftMode
    limit: Decimal = Decimal("0")

    @classmethod
    def strict(cls) -> OverdraftPolicy:
        return cls(mode=OverdraftMode.STRICT)

    @classmethod
    def allow_overdraft(cls) -> OverdraftPolicy:
        return cls(mode=OverdraftMode.ALLOW_OVERDRAFT)

    @classmethod
    def overdraft_limit(cls, limit: Decimal | int) -> OverdraftPolicy:
        if isinstance(limit, float):
            raise TypeError("limit does not accept float")
        decimal_limit = limit if isinstance(limit, Decimal) else Decimal(str(limit))
        if decimal_limit < Decimal("0"):
            raise ValueError("overdraft limit cannot be negative")
        return cls(mode=OverdraftMode.OVERDRAFT_LIMIT, limit=decimal_limit)


def assert_balanced(entries: Sequence[Entry]) -> None:
    """Why: double-entry integrity requires every transaction to net to zero per currency."""

    debit_totals: dict[str, Decimal] = {}
    credit_totals: dict[str, Decimal] = {}
    for entry in entries:
        bucket = debit_totals if entry.entry_type is EntryType.DEBIT else credit_totals
        currency = entry.amount.currency
        bucket[currency] = bucket.get(currency, Decimal("0")) + entry.amount.amount

    for currency in sorted(set(debit_totals) | set(credit_totals)):
        debit_total = debit_totals.get(currency, Decimal("0"))
        credit_total = credit_totals.get(currency, Decimal("0"))
        if debit_total != credit_total:
            entry_ids = tuple(entry.id for entry in entries if entry.amount.currency == currency)
            raise UnbalancedTransactionError(
                currency=currency,
                debit_total=debit_total,
                credit_total=credit_total,
                difference=debit_total - credit_total,
                entry_ids=entry_ids,
            )


def assert_currency_consistency(account: Account, money: Money) -> None:
    """Why: mixed-currency postings against one account break deterministic reconciliation."""

    if account.currency != money.currency:
        raise CurrencyMismatchError(
            account_id=account.id,
            account_currency=account.currency,
            money_currency=money.currency,
        )


def assert_no_negative_balance(account_id: str, balance: Money, policy: OverdraftPolicy) -> None:
    """Why: overdraft checks enforce account-level solvency rules at posting time."""

    if policy.mode is OverdraftMode.ALLOW_OVERDRAFT:
        return

    if balance.amount >= Decimal("0"):
        return

    if policy.mode is OverdraftMode.STRICT:
        raise InsufficientFundsError(
            account_id=account_id,
            available=balance.amount,
            required=Decimal("0"),
        )

    if balance.amount < -policy.limit:
        raise InsufficientFundsError(
            account_id=account_id,
            available=policy.limit,
            required=-balance.amount,
        )


def assert_idempotent(key: str, store: LedgerStore) -> None:
    """Why: reprocessing the same external event must not duplicate ledger side effects."""

    existing = store.get_transaction_by_idempotency_key(key)
    if existing is not None:
        raise DuplicateTransactionError(idempotency_key=key, transaction_id=existing.id)


def assert_valid_account_type_for_entry(account: Account, entry_type: EntryType) -> None:
    """Why: unusual debit/credit direction is often legal but commonly signals modeling mistakes."""

    if entry_type is account.normal_balance():
        return
    warnings.warn(
        (
            f"entry side {entry_type.value} is unusual for account type "
            f"{account.account_type.value} ({account.id})"
        ),
        UserWarning,
        stacklevel=2,
    )


__all__ = [
    "OverdraftMode",
    "OverdraftPolicy",
    "assert_balanced",
    "assert_currency_consistency",
    "assert_idempotent",
    "assert_no_negative_balance",
    "assert_valid_account_type_for_entry",
]
