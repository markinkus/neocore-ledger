"""Template engine for posting workflows."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from neocore.exceptions import AccountNotFoundError, InvalidTemplateError
from neocore.invariants import OverdraftPolicy
from neocore.ledger.engine import LedgerEngine, PostingInstruction
from neocore.ledger.models import AccountType, EntryType, MetadataValue, Transaction
from neocore.money import Money

if TYPE_CHECKING:
    from neocore.templates.registry import TemplateRegistry


class PreCondition(Protocol):
    """Template pre-condition callable."""

    def __call__(
        self,
        account_map: Mapping[str, str],
        amounts: Mapping[str, Money],
        metadata: Mapping[str, MetadataValue],
    ) -> None:
        ...


class PostCondition(Protocol):
    """Template post-condition callable."""

    def __call__(self, transaction: Transaction) -> None:
        ...


@dataclass(frozen=True, slots=True)
class AccountRole:
    """Role required by a template, resolved to a concrete account id at runtime."""

    role: str
    required_type: AccountType
    required_currency: str | None = None


@dataclass(frozen=True, slots=True)
class EntryRule:
    """Rule used to generate one posting line for a template execution."""

    account_role: str
    entry_type: EntryType
    amount_source: str
    description_template: str


@dataclass(frozen=True, slots=True)
class PostingTemplate:
    """Declarative template for repeatable posting flows."""

    name: str
    description: str
    required_accounts: list[AccountRole]
    entry_rules: list[EntryRule]
    pre_conditions: list[PreCondition]
    post_conditions: list[PostCondition]


class TemplateEngine:
    """Template execution layer on top of the core ledger engine."""

    def __init__(self, *, ledger: LedgerEngine, registry: TemplateRegistry) -> None:
        self.ledger = ledger
        self.registry = registry

    def apply(
        self,
        *,
        template_name: str,
        account_map: Mapping[str, str],
        amounts: Mapping[str, Money],
        idempotency_key: str,
        metadata: Mapping[str, MetadataValue] | None = None,
        overdraft_policy: OverdraftPolicy | None = None,
    ) -> Transaction:
        template = self.registry.get(template_name)
        call_metadata: Mapping[str, MetadataValue] = {} if metadata is None else metadata
        resolved_accounts = self._resolve_accounts(template, account_map)
        for condition in template.pre_conditions:
            condition(account_map, amounts, call_metadata)

        postings = [
            PostingInstruction(
                account_id=resolved_accounts[rule.account_role],
                entry_type=rule.entry_type,
                amount=self._resolve_amount(rule.amount_source, amounts, template_name),
            )
            for rule in template.entry_rules
        ]

        transaction = self.ledger.post(
            idempotency_key=idempotency_key,
            description=template.description,
            entries=postings,
            metadata=call_metadata,
            overdraft_policy=overdraft_policy,
        )
        for post_condition in template.post_conditions:
            post_condition(transaction)
        return transaction

    def _resolve_accounts(
        self,
        template: PostingTemplate,
        account_map: Mapping[str, str],
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for role in template.required_accounts:
            account_id = account_map.get(role.role)
            if account_id is None:
                raise InvalidTemplateError(
                    template_name=template.name,
                    reason=f"missing required account role: {role.role}",
                )
            account = self.ledger._store.get_account(account_id)
            if account is None:
                raise AccountNotFoundError(account_id=account_id)
            if account.account_type is not role.required_type:
                raise InvalidTemplateError(
                    template_name=template.name,
                    reason=(
                        f"role {role.role} requires {role.required_type.value}, "
                        f"got {account.account_type.value}"
                    ),
                )
            if role.required_currency is not None and account.currency != role.required_currency:
                raise InvalidTemplateError(
                    template_name=template.name,
                    reason=(
                        f"role {role.role} requires currency {role.required_currency}, "
                        f"got {account.currency}"
                    ),
                )
            resolved[role.role] = account_id
        return resolved

    def _resolve_amount(
        self,
        amount_source: str,
        amounts: Mapping[str, Money],
        template_name: str,
    ) -> Money:
        direct = amounts.get(amount_source)
        if direct is not None:
            return direct

        if not amounts:
            raise InvalidTemplateError(
                template_name=template_name,
                reason=f"missing amount source {amount_source}",
            )

        currencies = {value.currency for value in amounts.values()}
        if len(currencies) != 1:
            raise InvalidTemplateError(
                template_name=template_name,
                reason="amount expressions require a single shared currency",
            )
        currency = next(iter(currencies))
        variables = {name: money.amount for name, money in amounts.items()}
        evaluated = _evaluate_decimal_expression(amount_source, variables, template_name)
        return Money(evaluated, currency)


_ALLOWED_BINARY_NODES = (ast.Add, ast.Sub, ast.Mult, ast.Div)
_ALLOWED_UNARY_NODES = (ast.UAdd, ast.USub)


def _evaluate_decimal_expression(
    expression: str,
    variables: Mapping[str, Decimal],
    template_name: str,
) -> Decimal:
    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise InvalidTemplateError(
            template_name=template_name,
            reason=f"invalid amount expression: {expression}",
        ) from exc
    return _eval_ast(parsed.body, variables, template_name)


def _eval_ast(node: ast.AST, variables: Mapping[str, Decimal], template_name: str) -> Decimal:
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise InvalidTemplateError(
                template_name=template_name,
                reason=f"unknown variable in amount expression: {node.id}",
            )
        return variables[node.id]
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return Decimal(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY_NODES):
        value = _eval_ast(node.operand, variables, template_name)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINARY_NODES):
        left = _eval_ast(node.left, variables, template_name)
        right = _eval_ast(node.right, variables, template_name)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        return left / right
    raise InvalidTemplateError(
        template_name=template_name,
        reason=f"unsupported expression node: {type(node).__name__}",
    )


__all__ = [
    "AccountRole",
    "EntryRule",
    "PostCondition",
    "PostingTemplate",
    "PreCondition",
    "TemplateEngine",
]
