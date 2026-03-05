"""NeoCore custom exceptions."""

from __future__ import annotations

from decimal import Decimal


class NeoCoreError(Exception):
    """Base error for all NeoCore failures."""


class UnbalancedTransactionError(NeoCoreError):
    """Raised when debits and credits do not net to zero per currency."""

    def __init__(
        self,
        *,
        currency: str,
        debit_total: Decimal,
        credit_total: Decimal,
        difference: Decimal,
        entry_ids: tuple[str, ...] = (),
    ) -> None:
        self.currency = currency
        self.debit_total = debit_total
        self.credit_total = credit_total
        self.difference = difference
        self.entry_ids = entry_ids
        message = (
            "transaction is unbalanced for currency "
            f"{currency}: debit={debit_total} credit={credit_total} diff={difference}"
        )
        if entry_ids:
            message = f"{message} entries={entry_ids}"
        super().__init__(message)


class CurrencyMismatchError(NeoCoreError):
    """Raised when an amount currency does not match account currency."""

    def __init__(self, *, account_id: str, account_currency: str, money_currency: str) -> None:
        self.account_id = account_id
        self.account_currency = account_currency
        self.money_currency = money_currency
        message = (
            f"currency mismatch for account {account_id}: "
            f"account={account_currency} amount={money_currency}"
        )
        super().__init__(message)


class InsufficientFundsError(NeoCoreError):
    """Raised when a debit would violate overdraft policy."""

    def __init__(self, *, account_id: str, available: Decimal, required: Decimal) -> None:
        self.account_id = account_id
        self.available = available
        self.required = required
        super().__init__(
            "insufficient funds for account "
            f"{account_id}: available={available} required={required}",
        )


class DuplicateTransactionError(NeoCoreError):
    """Raised when idempotency key is already mapped to an existing transaction."""

    def __init__(self, *, idempotency_key: str, transaction_id: str) -> None:
        self.idempotency_key = idempotency_key
        self.transaction_id = transaction_id
        super().__init__(
            "duplicate idempotency key "
            f"{idempotency_key}; original transaction={transaction_id}",
        )


class AccountNotFoundError(NeoCoreError):
    """Raised when an account identifier does not exist."""

    def __init__(self, *, account_id: str) -> None:
        self.account_id = account_id
        super().__init__(f"account not found: {account_id}")


class InvalidTemplateError(NeoCoreError):
    """Raised when a template is malformed or receives invalid input."""

    def __init__(self, *, template_name: str, reason: str) -> None:
        self.template_name = template_name
        self.reason = reason
        super().__init__(f"invalid template {template_name}: {reason}")


class TemplateNotFoundError(NeoCoreError):
    """Raised when a template lookup fails."""

    def __init__(self, *, template_name: str) -> None:
        self.template_name = template_name
        super().__init__(f"template not found: {template_name}")


__all__ = [
    "AccountNotFoundError",
    "CurrencyMismatchError",
    "DuplicateTransactionError",
    "InsufficientFundsError",
    "InvalidTemplateError",
    "NeoCoreError",
    "TemplateNotFoundError",
    "UnbalancedTransactionError",
]
