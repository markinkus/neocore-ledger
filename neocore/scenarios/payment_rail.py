"""Reference payment rail scenario."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import ClassVar

from neocore.invariants import OverdraftPolicy
from neocore.ledger.engine import LedgerEngine, PostingInstruction
from neocore.ledger.models import AccountType, EntryType, Transaction
from neocore.ledger.store import LedgerStore
from neocore.money import Money
from neocore.templates.engine import TemplateEngine
from neocore.templates.registry import DEFAULT_REGISTRY


@dataclass(slots=True)
class PaymentRailScenario:
    """Executable reference flow for a card-like payment rail."""

    store: LedgerStore
    ledger: LedgerEngine = field(init=False)
    templates: TemplateEngine = field(init=False)
    _counter: count[int] = field(init=False, default_factory=lambda: count(1))

    CUSTOMER_ACCOUNT: ClassVar[str] = "customer"
    CLEARING_ACCOUNT: ClassVar[str] = "clearing"
    MERCHANT_ACCOUNT: ClassVar[str] = "merchant"
    BANK_ACCOUNT: ClassVar[str] = "bank"
    FEES_ACCOUNT: ClassVar[str] = "fees"

    def __post_init__(self) -> None:
        self.ledger = LedgerEngine(self.store)
        self.templates = TemplateEngine(ledger=self.ledger, registry=DEFAULT_REGISTRY)
        self._setup_accounts()

    def run_happy_path(self, *, amount: Money, fee: Money) -> dict[str, Money]:
        """Scenario 1: authorize -> capture -> settle."""

        self._fund_customer(amount)
        self.authorize(amount=amount, idempotency_key=self._next_key("authorize"))
        self.capture(amount=amount, idempotency_key=self._next_key("capture"))
        self.settle(amount=amount, fee=fee, idempotency_key=self._next_key("settle"))
        return self._balances()

    def run_partial_capture(self, *, authorized: Money, captured: Money) -> dict[str, Money]:
        """Scenario 2: capture less than authorized and reverse the remainder."""

        if captured.amount > authorized.amount:
            raise ValueError("captured amount cannot exceed authorized amount")

        self._fund_customer(authorized)
        authorization = self.authorize(
            amount=authorized,
            idempotency_key=self._next_key("authorize"),
        )
        self.capture(amount=captured, idempotency_key=self._next_key("capture"))
        clearing_after_capture = self.ledger.get_balance(self.CLEARING_ACCOUNT)

        remainder = authorized - captured
        if remainder.amount > 0:
            self.reverse(
                amount=remainder,
                original_transaction_id=authorization.id,
                idempotency_key=self._next_key("reverse"),
            )

        return {
            "clearing_after_capture": clearing_after_capture,
            "clearing_final": self.ledger.get_balance(self.CLEARING_ACCOUNT),
        }

    def run_duplicate_event(self, *, amount: Money, idempotency_key: str) -> dict[str, bool | int]:
        """Scenario 3: duplicated external event must remain side-effect free."""

        self._fund_customer(amount)
        first = self.authorize(amount=amount, idempotency_key=idempotency_key)
        second = self.authorize(amount=amount, idempotency_key=idempotency_key)
        return {
            "same_transaction": first.id == second.id,
            "customer_statement_entries": len(self.ledger.get_statement(self.CUSTOMER_ACCOUNT)),
        }

    def run_late_reverse(self, *, amount: Money, fee: Money) -> dict[str, str | Money]:
        """Scenario 4: reverse after capture+settle has already happened."""

        self._fund_customer(amount)
        authorization = self.authorize(amount=amount, idempotency_key=self._next_key("authorize"))
        self.capture(amount=amount, idempotency_key=self._next_key("capture"))
        self.settle(amount=amount, fee=fee, idempotency_key=self._next_key("settle"))
        reverse = self.reverse(
            amount=amount,
            original_transaction_id=authorization.id,
            idempotency_key=self._next_key("late-reverse"),
        )
        balances = self._balances()
        return {
            "reverse_transaction_id": reverse.id,
            "customer": balances["customer"],
            "clearing": balances["clearing"],
        }

    def run_insufficient_funds(self, *, funded: Money, requested: Money) -> Transaction:
        """Scenario 5: authorization fails when requested amount exceeds available funds."""

        self._fund_customer(funded)
        return self.authorize(amount=requested, idempotency_key=self._next_key("authorize"))

    def authorize(self, *, amount: Money, idempotency_key: str) -> Transaction:
        return self.templates.apply(
            template_name="PAYMENT.AUTHORIZE",
            account_map={
                "customer_account": self.CUSTOMER_ACCOUNT,
                "clearing_account": self.CLEARING_ACCOUNT,
            },
            amounts={"amount": amount},
            idempotency_key=idempotency_key,
            metadata={},
            overdraft_policy=OverdraftPolicy.strict(),
        )

    def capture(self, *, amount: Money, idempotency_key: str) -> Transaction:
        return self.templates.apply(
            template_name="PAYMENT.CAPTURE",
            account_map={
                "clearing_account": self.CLEARING_ACCOUNT,
                "merchant_account": self.MERCHANT_ACCOUNT,
            },
            amounts={"amount": amount},
            idempotency_key=idempotency_key,
            metadata={},
            overdraft_policy=OverdraftPolicy.allow_overdraft(),
        )

    def settle(self, *, amount: Money, fee: Money, idempotency_key: str) -> Transaction:
        return self.templates.apply(
            template_name="PAYMENT.SETTLE",
            account_map={
                "merchant_account": self.MERCHANT_ACCOUNT,
                "bank_account": self.BANK_ACCOUNT,
                "fee_account": self.FEES_ACCOUNT,
            },
            amounts={"amount": amount, "fee": fee},
            idempotency_key=idempotency_key,
            metadata={},
            overdraft_policy=OverdraftPolicy.allow_overdraft(),
        )

    def reverse(
        self,
        *,
        amount: Money,
        original_transaction_id: str,
        idempotency_key: str,
    ) -> Transaction:
        return self.templates.apply(
            template_name="PAYMENT.REVERSE",
            account_map={
                "clearing_account": self.CLEARING_ACCOUNT,
                "customer_account": self.CUSTOMER_ACCOUNT,
            },
            amounts={"amount": amount},
            idempotency_key=idempotency_key,
            metadata={"transaction_id": original_transaction_id},
            overdraft_policy=OverdraftPolicy.allow_overdraft(),
        )

    def _fund_customer(self, amount: Money) -> Transaction:
        return self.ledger.post(
            idempotency_key=self._next_key("fund"),
            description="Seed customer balance",
            entries=(
                self._posting(self.BANK_ACCOUNT, EntryType.DEBIT, amount),
                self._posting(self.CUSTOMER_ACCOUNT, EntryType.CREDIT, amount),
            ),
            metadata={},
            overdraft_policy=OverdraftPolicy.allow_overdraft(),
        )

    def _setup_accounts(self) -> None:
        self.ledger.create_account(
            id=self.CUSTOMER_ACCOUNT,
            name="Customer Wallet",
            account_type=AccountType.ASSET,
            currency="EUR",
            metadata={},
        )
        self.ledger.create_account(
            id=self.CLEARING_ACCOUNT,
            name="Clearing",
            account_type=AccountType.LIABILITY,
            currency="EUR",
            metadata={},
        )
        self.ledger.create_account(
            id=self.MERCHANT_ACCOUNT,
            name="Merchant",
            account_type=AccountType.LIABILITY,
            currency="EUR",
            metadata={},
        )
        self.ledger.create_account(
            id=self.BANK_ACCOUNT,
            name="Bank",
            account_type=AccountType.LIABILITY,
            currency="EUR",
            metadata={},
        )
        self.ledger.create_account(
            id=self.FEES_ACCOUNT,
            name="Fee Income",
            account_type=AccountType.INCOME,
            currency="EUR",
            metadata={},
        )

    def _next_key(self, prefix: str) -> str:
        return f"{prefix}-{next(self._counter)}"

    @staticmethod
    def _posting(account_id: str, entry_type: EntryType, amount: Money) -> PostingInstruction:
        return PostingInstruction(account_id=account_id, entry_type=entry_type, amount=amount)

    def _balances(self) -> dict[str, Money]:
        return {
            "customer": self.ledger.get_balance(self.CUSTOMER_ACCOUNT),
            "clearing": self.ledger.get_balance(self.CLEARING_ACCOUNT),
            "merchant": self.ledger.get_balance(self.MERCHANT_ACCOUNT),
            "bank": self.ledger.get_balance(self.BANK_ACCOUNT),
            "fees": self.ledger.get_balance(self.FEES_ACCOUNT),
        }


__all__ = ["PaymentRailScenario"]
