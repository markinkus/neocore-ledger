"""Tests for builtin templates."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from neocore.invariants import OverdraftPolicy
from neocore.ledger.engine import LedgerEngine
from neocore.ledger.models import AccountType, EntryType
from neocore.ledger.store import LedgerStore, MemoryStore, SQLiteStore
from neocore.money import Money
from neocore.templates.engine import TemplateEngine
from neocore.templates.registry import DEFAULT_REGISTRY


@pytest.fixture(params=["memory", "sqlite"])
def builtins_engine(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> tuple[TemplateEngine, LedgerEngine]:
    store: LedgerStore
    if request.param == "memory":
        store = MemoryStore()
    else:
        store = SQLiteStore(tmp_path / "builtins.sqlite")

    ledger = LedgerEngine(store)
    ledger.create_account(
        id="customer",
        name="Customer",
        account_type=AccountType.ASSET,
        currency="EUR",
        metadata={},
    )
    ledger.create_account(
        id="clearing",
        name="Clearing",
        account_type=AccountType.LIABILITY,
        currency="EUR",
        metadata={},
    )
    ledger.create_account(
        id="merchant",
        name="Merchant",
        account_type=AccountType.LIABILITY,
        currency="EUR",
        metadata={},
    )
    ledger.create_account(
        id="bank",
        name="Bank",
        account_type=AccountType.LIABILITY,
        currency="EUR",
        metadata={},
    )
    ledger.create_account(
        id="fees",
        name="Fees",
        account_type=AccountType.INCOME,
        currency="EUR",
        metadata={},
    )

    return TemplateEngine(ledger=ledger, registry=DEFAULT_REGISTRY), ledger


def test_default_registry_contains_payment_templates() -> None:
    names = set(DEFAULT_REGISTRY.names())
    assert {"PAYMENT.AUTHORIZE", "PAYMENT.CAPTURE", "PAYMENT.SETTLE", "PAYMENT.REVERSE"}.issubset(
        names
    )


def test_builtin_authorize_template(builtins_engine: tuple[TemplateEngine, LedgerEngine]) -> None:
    engine, _ = builtins_engine

    tx = engine.apply(
        template_name="PAYMENT.AUTHORIZE",
        account_map={"customer_account": "customer", "clearing_account": "clearing"},
        amounts={"amount": Money(Decimal("100.00"), "EUR")},
        idempotency_key="auth-1",
        metadata={},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )

    assert [entry.entry_type for entry in tx.entries] == [EntryType.DEBIT, EntryType.CREDIT]


def test_builtin_settle_template_splits_fee(
    builtins_engine: tuple[TemplateEngine, LedgerEngine],
) -> None:
    engine, _ = builtins_engine

    tx = engine.apply(
        template_name="PAYMENT.SETTLE",
        account_map={
            "merchant_account": "merchant",
            "bank_account": "bank",
            "fee_account": "fees",
        },
        amounts={
            "amount": Money(Decimal("100.00"), "EUR"),
            "fee": Money(Decimal("1.00"), "EUR"),
        },
        idempotency_key="settle-1",
        metadata={},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )

    assert len(tx.entries) == 3
    assert [entry.amount.amount for entry in tx.entries] == [
        Decimal("100.00"),
        Decimal("99.00"),
        Decimal("1.00"),
    ]


def test_builtin_reverse_template(builtins_engine: tuple[TemplateEngine, LedgerEngine]) -> None:
    engine, _ = builtins_engine

    tx = engine.apply(
        template_name="PAYMENT.REVERSE",
        account_map={"clearing_account": "clearing", "customer_account": "customer"},
        amounts={"amount": Money(Decimal("25.00"), "EUR")},
        idempotency_key="rev-1",
        metadata={"transaction_id": "original-tx"},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )

    assert [entry.entry_type for entry in tx.entries] == [EntryType.DEBIT, EntryType.CREDIT]
