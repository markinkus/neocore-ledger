"""End-to-end tests for payment rail scenario."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from neocore.exceptions import InsufficientFundsError
from neocore.ledger.store import LedgerStore, MemoryStore, SQLiteStore
from neocore.money import Money
from neocore.scenarios.payment_rail import PaymentRailScenario, main, run_demo


@pytest.fixture(params=["memory", "sqlite"])
def scenario(request: pytest.FixtureRequest, tmp_path: Path) -> PaymentRailScenario:
    store: LedgerStore
    if request.param == "memory":
        store = MemoryStore()
    else:
        store = SQLiteStore(tmp_path / "scenario.sqlite")
    return PaymentRailScenario(store)


def test_payment_rail_happy_path(scenario: PaymentRailScenario) -> None:
    result = scenario.run_happy_path(
        amount=Money(Decimal("100.00"), "EUR"),
        fee=Money(Decimal("1.00"), "EUR"),
    )

    assert result["customer"].amount == Decimal("0.00")
    assert result["clearing"].amount == Decimal("0.00")
    assert result["merchant"].amount == Decimal("0.00")
    assert result["fees"].amount == Decimal("1.00")


def test_payment_rail_partial_capture(scenario: PaymentRailScenario) -> None:
    result = scenario.run_partial_capture(
        authorized=Money(Decimal("100.00"), "EUR"),
        captured=Money(Decimal("80.00"), "EUR"),
    )

    assert result["clearing_after_capture"].amount == Decimal("20.00")
    assert result["clearing_final"].amount == Decimal("0.00")


def test_payment_rail_duplicate_event_is_idempotent(scenario: PaymentRailScenario) -> None:
    result = scenario.run_duplicate_event(
        amount=Money(Decimal("30.00"), "EUR"),
        idempotency_key="pay-001",
    )

    assert result["same_transaction"] is True
    assert result["customer_statement_entries"] == 2


def test_payment_rail_late_reverse_after_settle(scenario: PaymentRailScenario) -> None:
    result = scenario.run_late_reverse(
        amount=Money(Decimal("40.00"), "EUR"),
        fee=Money(Decimal("1.00"), "EUR"),
    )

    assert result["reverse_transaction_id"]
    customer_balance = result["customer"]
    assert isinstance(customer_balance, Money)
    assert customer_balance.currency == "EUR"


def test_payment_rail_insufficient_funds(scenario: PaymentRailScenario) -> None:
    with pytest.raises(InsufficientFundsError) as exc:
        scenario.run_insufficient_funds(
            funded=Money(Decimal("500.00"), "EUR"),
            requested=Money(Decimal("1000.00"), "EUR"),
        )

    assert exc.value.available == Decimal("500.00")
    assert exc.value.required == Decimal("1000.00")


def test_run_demo_returns_readable_report() -> None:
    report = run_demo()
    assert "NeoCore Payment Rail Demo" in report
    assert "customer" in report
    assert "fees" in report
    assert "Money(1.00 EUR)" in report


def test_main_prints_demo_report(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main()
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "NeoCore Payment Rail Demo" in captured.out


def test_examples_script_runs_successfully() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "examples" / "payment_rail.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )
    assert result.returncode == 0
    assert "NeoCore Payment Rail Demo" in result.stdout
