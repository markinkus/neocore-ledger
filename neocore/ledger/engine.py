"""Ledger engine orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from neocore.exceptions import (
    AccountNotFoundError,
    DuplicateTransactionError,
    InsufficientFundsError,
)
from neocore.invariants import OverdraftMode, OverdraftPolicy, assert_currency_consistency
from neocore.ledger.models import (
    Account,
    AccountType,
    Entry,
    EntryType,
    Metadata,
    MetadataValue,
    Transaction,
)
from neocore.ledger.store import LedgerStore
from neocore.money import Money


@dataclass(frozen=True, slots=True)
class PostingInstruction:
    """User-provided posting instruction resolved into persisted entries."""

    account_id: str
    entry_type: EntryType
    amount: Money


@dataclass(frozen=True, slots=True)
class StatementLine:
    """Single statement line with running balance."""

    entry: Entry
    balance_after: Money


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Trial-balance style report for a set of accounts."""

    account_balances: dict[str, Money]
    left_by_currency: dict[str, Money]
    right_by_currency: dict[str, Money]
    is_balanced: bool


class LedgerEngine:
    """Main orchestrator for account management and postings."""

    def __init__(self, store: LedgerStore) -> None:
        self._store = store

    def create_account(
        self,
        *,
        id: str,
        name: str,
        account_type: AccountType,
        currency: str,
        parent_id: str | None = None,
        metadata: dict[str, MetadataValue] | None = None,
    ) -> Account:
        if self._store.get_account(id) is not None:
            raise ValueError(f"account already exists: {id}")
        if parent_id is not None and self._store.get_account(parent_id) is None:
            raise AccountNotFoundError(account_id=parent_id)

        account = Account(
            id=id,
            name=name,
            account_type=account_type,
            currency=currency,
            parent_id=parent_id,
            metadata={} if metadata is None else metadata,
        )
        self._store.create_account(account)
        return account

    def post(
        self,
        *,
        idempotency_key: str,
        description: str,
        entries: Sequence[PostingInstruction],
        metadata: Metadata | None = None,
        overdraft_policy: OverdraftPolicy | None = None,
    ) -> Transaction:
        existing = self._store.get_transaction_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing

        policy = overdraft_policy or OverdraftPolicy.strict()
        accounts = self._load_accounts(entries)
        self._validate_currency_consistency(accounts, entries)

        transaction_id = f"tx_{uuid4().hex}"
        now = datetime.now(tz=UTC)
        persisted_entries = tuple(
            Entry(
                id=f"{transaction_id}:e{index}",
                account_id=instruction.account_id,
                entry_type=instruction.entry_type,
                amount=instruction.amount,
                transaction_id=transaction_id,
                created_at=now,
            )
            for index, instruction in enumerate(entries, start=1)
        )
        transaction = Transaction(
            id=transaction_id,
            idempotency_key=idempotency_key,
            description=description,
            entries=persisted_entries,
            created_at=now,
            metadata={} if metadata is None else metadata,
        )
        self._check_overdraft_policy(accounts, transaction, policy)

        try:
            self._store.append_transaction(transaction)
        except DuplicateTransactionError as exc:
            original = self._store.get_transaction(exc.transaction_id)
            if original is None:  # pragma: no cover - defensive guard
                raise
            return original
        return transaction

    def get_balance(self, account_id: str, *, as_of: datetime | None = None) -> Money:
        account = self._store.get_account(account_id)
        if account is None:
            raise AccountNotFoundError(account_id=account_id)

        entries = self._store.list_entries(account_id, until=as_of)
        balance = Money.zero(account.currency)
        normal_side = account.normal_balance()
        for entry in entries:
            if entry.entry_type is normal_side:
                balance = balance + entry.amount
            else:
                balance = balance - entry.amount
        return balance

    def get_statement(
        self,
        account_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[StatementLine]:
        account = self._store.get_account(account_id)
        if account is None:
            raise AccountNotFoundError(account_id=account_id)

        all_entries = self._store.list_entries(account_id)
        running = Money.zero(account.currency)
        normal_side = account.normal_balance()
        statement: list[StatementLine] = []
        for entry in all_entries:
            if entry.entry_type is normal_side:
                running = running + entry.amount
            else:
                running = running - entry.amount
            if since is not None and entry.created_at < since:
                continue
            if until is not None and entry.created_at > until:
                continue
            statement.append(StatementLine(entry=entry, balance_after=running))
        return statement

    def reconcile(self, account_ids: Sequence[str]) -> ReconciliationReport:
        balances: dict[str, Money] = {}
        left_raw: dict[str, Decimal] = {}
        right_raw: dict[str, Decimal] = {}

        for account_id in account_ids:
            account = self._store.get_account(account_id)
            if account is None:
                raise AccountNotFoundError(account_id=account_id)
            balance = self.get_balance(account_id)
            balances[account_id] = balance
            if account.account_type in {AccountType.ASSET, AccountType.EXPENSE}:
                target = left_raw
            else:
                target = right_raw
            target[balance.currency] = target.get(balance.currency, Decimal("0")) + balance.amount

        currencies = set(left_raw) | set(right_raw)
        is_balanced = all(
            left_raw.get(code, Decimal("0")) == right_raw.get(code, Decimal("0"))
            for code in currencies
        )
        left = {code: Money(value, code) for code, value in left_raw.items()}
        right = {code: Money(value, code) for code, value in right_raw.items()}
        return ReconciliationReport(
            account_balances=balances,
            left_by_currency=left,
            right_by_currency=right,
            is_balanced=is_balanced,
        )

    def _load_accounts(self, entries: Sequence[PostingInstruction]) -> dict[str, Account]:
        loaded: dict[str, Account] = {}
        for entry in entries:
            if entry.account_id in loaded:
                continue
            account = self._store.get_account(entry.account_id)
            if account is None:
                raise AccountNotFoundError(account_id=entry.account_id)
            loaded[entry.account_id] = account
        return loaded

    def _validate_currency_consistency(
        self,
        accounts: dict[str, Account],
        entries: Sequence[PostingInstruction],
    ) -> None:
        for entry in entries:
            account = accounts[entry.account_id]
            assert_currency_consistency(account, entry.amount)

    def _check_overdraft_policy(
        self,
        accounts: dict[str, Account],
        transaction: Transaction,
        policy: OverdraftPolicy,
    ) -> None:
        debit_by_asset_account: dict[str, Decimal] = {}
        for entry in transaction.entries:
            account = accounts[entry.account_id]
            if account.account_type is not AccountType.ASSET:
                continue
            if entry.entry_type is not EntryType.DEBIT:
                continue
            debit_by_asset_account[account.id] = (
                debit_by_asset_account.get(account.id, Decimal("0")) + entry.amount.amount
            )

        for account_id, required in debit_by_asset_account.items():
            available = self._available_for_asset_debit(account_id)
            if policy.mode is OverdraftMode.ALLOW_OVERDRAFT:
                continue
            if policy.mode is OverdraftMode.STRICT and available < required:
                raise InsufficientFundsError(
                    account_id=account_id,
                    available=available,
                    required=required,
                )
            if (
                policy.mode is OverdraftMode.OVERDRAFT_LIMIT
                and (available + policy.limit) < required
            ):
                raise InsufficientFundsError(
                    account_id=account_id,
                    available=available + policy.limit,
                    required=required,
                )

    def _available_for_asset_debit(self, account_id: str) -> Decimal:
        available = Decimal("0")
        for entry in self._store.list_entries(account_id):
            if entry.entry_type is EntryType.CREDIT:
                available += entry.amount.amount
            else:
                available -= entry.amount.amount
        return available


__all__ = [
    "LedgerEngine",
    "OverdraftMode",
    "OverdraftPolicy",
    "PostingInstruction",
    "ReconciliationReport",
    "StatementLine",
]
