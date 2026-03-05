"""Money and currency primitives for NeoCore."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Decimal,
    InvalidOperation,
)
from enum import StrEnum
from typing import Final


class RoundingRule(StrEnum):
    """Supported rounding rules."""

    HALF_EVEN = "HALF_EVEN"
    HALF_UP = "HALF_UP"
    FLOOR = "FLOOR"


class OperationType(StrEnum):
    """Type of operation used to pick rounding policy."""

    DEFAULT = "DEFAULT"
    FEE = "FEE"
    FX_CONVERSION = "FX_CONVERSION"
    INTEREST = "INTEREST"
    TAX = "TAX"


@dataclass(frozen=True, slots=True)
class CurrencyConfig:
    """Currency quantization and default rounding settings."""

    code: str
    decimal_places: int
    rounding_default: RoundingRule


CURRENCY_REGISTRY: Final[dict[str, CurrencyConfig]] = {
    "EUR": CurrencyConfig(code="EUR", decimal_places=2, rounding_default=RoundingRule.HALF_EVEN),
    "USD": CurrencyConfig(code="USD", decimal_places=2, rounding_default=RoundingRule.HALF_EVEN),
    "GBP": CurrencyConfig(code="GBP", decimal_places=2, rounding_default=RoundingRule.HALF_EVEN),
    "JPY": CurrencyConfig(code="JPY", decimal_places=0, rounding_default=RoundingRule.HALF_EVEN),
    "CHF": CurrencyConfig(code="CHF", decimal_places=2, rounding_default=RoundingRule.HALF_EVEN),
    "BTC": CurrencyConfig(code="BTC", decimal_places=8, rounding_default=RoundingRule.HALF_EVEN),
    "USDC": CurrencyConfig(code="USDC", decimal_places=6, rounding_default=RoundingRule.HALF_EVEN),
}

_DECIMAL_ROUNDING_MAP: Final[dict[RoundingRule, str]] = {
    RoundingRule.HALF_EVEN: ROUND_HALF_EVEN,
    RoundingRule.HALF_UP: ROUND_HALF_UP,
    RoundingRule.FLOOR: ROUND_FLOOR,
}

_OPERATION_ROUNDING_MAP: Final[dict[OperationType, RoundingRule]] = {
    OperationType.DEFAULT: RoundingRule.HALF_EVEN,
    OperationType.FEE: RoundingRule.FLOOR,
    OperationType.FX_CONVERSION: RoundingRule.HALF_UP,
    OperationType.INTEREST: RoundingRule.HALF_EVEN,
    OperationType.TAX: RoundingRule.HALF_UP,
}


def _currency_config(code: str) -> CurrencyConfig:
    normalized = code.upper()
    if normalized not in CURRENCY_REGISTRY:
        raise ValueError(f"unsupported currency: {code}")
    return CURRENCY_REGISTRY[normalized]


def _coerce_decimal(value: object, *, field_name: str) -> Decimal:
    if isinstance(value, float):
        raise TypeError(f"{field_name} does not accept float")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:  # pragma: no cover - defensive guard
            raise TypeError(f"{field_name} must be Decimal-compatible") from exc
    raise TypeError(f"{field_name} must be Decimal-compatible")


def _quantize_decimal(amount: Decimal, currency: CurrencyConfig, rule: RoundingRule) -> Decimal:
    quantum = Decimal(1).scaleb(-currency.decimal_places)
    return amount.quantize(quantum, rounding=_DECIMAL_ROUNDING_MAP[rule])


@dataclass(frozen=True, slots=True)
class Money:
    """Amount represented in a specific currency."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        currency_code = self.currency.upper()
        config = _currency_config(currency_code)
        normalized_amount = _coerce_decimal(self.amount, field_name="amount")
        quantized_amount = _quantize_decimal(
            normalized_amount,
            config,
            config.rounding_default,
        )
        object.__setattr__(self, "currency", currency_code)
        object.__setattr__(self, "amount", quantized_amount)

    def __repr__(self) -> str:
        return f"Money({self.amount} {self.currency})"

    def __add__(self, other: Money) -> Money:
        self._ensure_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._ensure_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __mul__(self, scalar: Decimal | int) -> Money:
        factor = _coerce_decimal(scalar, field_name="scalar")
        return Money(self.amount * factor, self.currency)

    def __rmul__(self, scalar: Decimal | int) -> Money:
        return self.__mul__(scalar)

    def __lt__(self, other: Money) -> bool:
        self._ensure_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._ensure_same_currency(other)
        return self.amount <= other.amount

    def is_zero(self) -> bool:
        return self.amount.is_zero()

    def quantize(self, rule: RoundingRule) -> Money:
        config = _currency_config(self.currency)
        return Money(_quantize_decimal(self.amount, config, rule), self.currency)

    def convert(
        self,
        to_currency: str,
        rate: Decimal | int,
        operation: OperationType = OperationType.DEFAULT,
    ) -> Money:
        conversion_rate = _coerce_decimal(rate, field_name="rate")
        if conversion_rate <= Decimal("0"):
            raise ValueError("rate must be positive")

        destination_code = to_currency.upper()
        destination = _currency_config(destination_code)
        rounded = _quantize_decimal(
            self.amount * conversion_rate,
            destination,
            _OPERATION_ROUNDING_MAP[operation],
        )
        return Money(rounded, destination_code)

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal("0"), currency)

    def _ensure_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(
                f"currency mismatch: {self.currency} vs {other.currency}",
            )


__all__ = [
    "CURRENCY_REGISTRY",
    "CurrencyConfig",
    "Money",
    "OperationType",
    "RoundingRule",
]
