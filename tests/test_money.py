"""Tests for money primitives."""

from decimal import Decimal
from typing import cast

import pytest

from neocore.money import Money, OperationType, RoundingRule


def test_money_rejects_float_input() -> None:
    with pytest.raises(TypeError):
        Money(cast(Decimal, 10.5), "EUR")


def test_money_rounds_half_even_for_10999_eur() -> None:
    amount = Money(Decimal("10.999"), "EUR")
    assert amount.amount == Decimal("11.00")


def test_money_rounds_half_even_for_10995_eur() -> None:
    amount = Money(Decimal("10.995"), "EUR")
    assert amount.amount == Decimal("11.00")


def test_money_add_same_currency() -> None:
    result = Money(Decimal("2.40"), "EUR") + Money(Decimal("1.10"), "EUR")
    assert result == Money(Decimal("3.50"), "EUR")


def test_money_add_different_currency_raises_value_error() -> None:
    with pytest.raises(ValueError):
        _ = Money(Decimal("1.00"), "EUR") + Money(Decimal("1.00"), "USD")


def test_money_rounds_jpy_to_zero_decimals() -> None:
    amount = Money(Decimal("100.7"), "JPY")
    assert amount.amount == Decimal("101")


def test_money_convert_eur_to_usd_with_fx_rounding() -> None:
    eur = Money(Decimal("10.00"), "EUR")
    usd = eur.convert(
        to_currency="USD",
        rate=Decimal("1.237"),
        operation=OperationType.FX_CONVERSION,
    )
    assert usd == Money(Decimal("12.37"), "USD")


def test_money_quantize_with_explicit_rule() -> None:
    value = Money(Decimal("10.99"), "EUR").quantize(RoundingRule.FLOOR)
    assert value.amount == Decimal("10.99")


def test_money_zero_helper() -> None:
    assert Money.zero("EUR") == Money(Decimal("0.00"), "EUR")


def test_money_repr_is_readable() -> None:
    text = repr(Money(Decimal("5.10"), "EUR"))
    assert "Money" in text
    assert "5.10" in text
    assert "EUR" in text
