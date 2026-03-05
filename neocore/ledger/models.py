"""Ledger domain models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import TypeAlias

from neocore.exceptions import UnbalancedTransactionError
from neocore.money import Money

MetadataValue: TypeAlias = str | int | bool | Decimal | None
Metadata: TypeAlias = Mapping[str, MetadataValue]


class EntryType(StrEnum):
    """Entry side in a double-entry transaction."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountType(StrEnum):
    """Account class according to accounting equation."""

    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"

    def normal_balance(self) -> EntryType:
        if self in {AccountType.ASSET, AccountType.EXPENSE}:
            return EntryType.DEBIT
        return EntryType.CREDIT


@dataclass(frozen=True, slots=True)
class Account:
    """Chart-of-accounts entry."""

    id: str
    name: str
    account_type: AccountType
    currency: str
    parent_id: str | None
    metadata: Metadata

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", self.currency.upper())
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def normal_balance(self) -> EntryType:
        return self.account_type.normal_balance()


@dataclass(frozen=True, slots=True)
class Entry:
    """A single debit or credit line."""

    id: str
    account_id: str
    entry_type: EntryType
    amount: Money
    transaction_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.amount.amount <= Decimal("0"):
            raise ValueError("entry amount must be positive")


@dataclass(frozen=True, slots=True)
class Transaction:
    """An immutable collection of balanced entries."""

    id: str
    idempotency_key: str
    description: str
    entries: tuple[Entry, ...]
    created_at: datetime
    metadata: Metadata

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        self._validate_entry_links()
        self._validate_balance()

    def _validate_entry_links(self) -> None:
        for entry in self.entries:
            if entry.transaction_id != self.id:
                raise ValueError(
                    "entry "
                    f"{entry.id} transaction_id {entry.transaction_id} does not match "
                    f"{self.id}",
                )

    def _validate_balance(self) -> None:
        debit_totals: dict[str, Decimal] = {}
        credit_totals: dict[str, Decimal] = {}
        for entry in self.entries:
            totals = debit_totals if entry.entry_type is EntryType.DEBIT else credit_totals
            currency = entry.amount.currency
            totals[currency] = totals.get(currency, Decimal("0")) + entry.amount.amount

        for currency in sorted(set(debit_totals) | set(credit_totals)):
            debit_total = debit_totals.get(currency, Decimal("0"))
            credit_total = credit_totals.get(currency, Decimal("0"))
            if debit_total != credit_total:
                raise UnbalancedTransactionError(
                    currency=currency,
                    debit_total=debit_total,
                    credit_total=credit_total,
                    difference=debit_total - credit_total,
                )


__all__ = [
    "Account",
    "AccountType",
    "Entry",
    "EntryType",
    "Metadata",
    "MetadataValue",
    "Transaction",
]
