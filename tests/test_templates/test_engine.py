"""Tests for template engine."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from neocore.exceptions import InvalidTemplateError, TemplateNotFoundError
from neocore.invariants import OverdraftPolicy
from neocore.ledger.engine import LedgerEngine
from neocore.ledger.models import AccountType, EntryType
from neocore.ledger.store import LedgerStore, MemoryStore, SQLiteStore
from neocore.money import Money
from neocore.templates.engine import AccountRole, EntryRule, PostingTemplate, TemplateEngine
from neocore.templates.registry import TemplateRegistry


@pytest.fixture(params=["memory", "sqlite"])
def template_engine(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> tuple[TemplateEngine, LedgerEngine]:
    store: LedgerStore
    if request.param == "memory":
        store = MemoryStore()
    else:
        store = SQLiteStore(tmp_path / "template_engine.sqlite")

    ledger = LedgerEngine(store)
    ledger.create_account(
        id="customer",
        name="Customer",
        account_type=AccountType.ASSET,
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

    registry = TemplateRegistry()
    registry.register(
        PostingTemplate(
            name="TEST.TRANSFER",
            description="Simple transfer template",
            required_accounts=[
                AccountRole(role="from_account", required_type=AccountType.ASSET),
                AccountRole(role="to_account", required_type=AccountType.LIABILITY),
            ],
            entry_rules=[
                EntryRule(
                    account_role="from_account",
                    entry_type=EntryType.DEBIT,
                    amount_source="amount",
                    description_template="debit",
                ),
                EntryRule(
                    account_role="to_account",
                    entry_type=EntryType.CREDIT,
                    amount_source="amount",
                    description_template="credit",
                ),
            ],
            pre_conditions=[],
            post_conditions=[],
        )
    )

    return TemplateEngine(ledger=ledger, registry=registry), ledger


def test_template_engine_apply_posts_transaction(
    template_engine: tuple[TemplateEngine, LedgerEngine],
) -> None:
    engine, ledger = template_engine

    tx = engine.apply(
        template_name="TEST.TRANSFER",
        account_map={"from_account": "customer", "to_account": "merchant"},
        amounts={"amount": Money(Decimal("12.30"), "EUR")},
        idempotency_key="tpl-1",
        metadata={},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )

    assert len(tx.entries) == 2
    assert ledger.get_balance("customer").amount == Decimal("12.30")


def test_template_engine_missing_template_raises(
    template_engine: tuple[TemplateEngine, LedgerEngine],
) -> None:
    engine, _ = template_engine

    with pytest.raises(TemplateNotFoundError):
        engine.apply(
            template_name="MISSING",
            account_map={},
            amounts={"amount": Money(Decimal("1.00"), "EUR")},
            idempotency_key="x",
            metadata={},
            overdraft_policy=OverdraftPolicy.allow_overdraft(),
        )


def test_template_engine_validates_required_account_role(
    template_engine: tuple[TemplateEngine, LedgerEngine],
) -> None:
    engine, _ = template_engine

    with pytest.raises(InvalidTemplateError):
        engine.apply(
            template_name="TEST.TRANSFER",
            account_map={"from_account": "customer"},
            amounts={"amount": Money(Decimal("5.00"), "EUR")},
            idempotency_key="tpl-2",
            metadata={},
            overdraft_policy=OverdraftPolicy.allow_overdraft(),
        )


def test_template_engine_supports_amount_expressions(
    template_engine: tuple[TemplateEngine, LedgerEngine],
) -> None:
    engine, ledger = template_engine

    engine.registry.register(
        PostingTemplate(
            name="TEST.FEE",
            description="fee template",
            required_accounts=[
                AccountRole(role="merchant", required_type=AccountType.LIABILITY),
                AccountRole(role="bank", required_type=AccountType.LIABILITY),
            ],
            entry_rules=[
                EntryRule(
                    account_role="merchant",
                    entry_type=EntryType.DEBIT,
                    amount_source="amount",
                    description_template="merchant debit",
                ),
                EntryRule(
                    account_role="bank",
                    entry_type=EntryType.CREDIT,
                    amount_source="amount - fee",
                    description_template="bank credit",
                ),
                EntryRule(
                    account_role="merchant",
                    entry_type=EntryType.CREDIT,
                    amount_source="fee",
                    description_template="fee credit",
                ),
            ],
            pre_conditions=[],
            post_conditions=[],
        )
    )

    tx = engine.apply(
        template_name="TEST.FEE",
        account_map={"merchant": "merchant", "bank": "bank"},
        amounts={
            "amount": Money(Decimal("10.00"), "EUR"),
            "fee": Money(Decimal("1.00"), "EUR"),
        },
        idempotency_key="tpl-3",
        metadata={},
        overdraft_policy=OverdraftPolicy.allow_overdraft(),
    )

    amounts = [entry.amount.amount for entry in tx.entries]
    assert amounts == [Decimal("10.00"), Decimal("9.00"), Decimal("1.00")]
    assert ledger.get_balance("merchant").amount == Decimal("-9.00")
