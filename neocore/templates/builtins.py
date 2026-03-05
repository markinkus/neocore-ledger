"""Builtin payment templates."""

from __future__ import annotations

from collections.abc import Mapping

from neocore.exceptions import InvalidTemplateError
from neocore.ledger.models import AccountType, EntryType, MetadataValue
from neocore.money import Money
from neocore.templates.engine import AccountRole, EntryRule, PostingTemplate


def _payment_authorize_template() -> PostingTemplate:
    """Reserve customer funds into a clearing account before capture."""

    return PostingTemplate(
        name="PAYMENT.AUTHORIZE",
        description="Authorize payment amount in clearing",
        required_accounts=[
            AccountRole(role="customer_account", required_type=AccountType.ASSET),
            AccountRole(role="clearing_account", required_type=AccountType.LIABILITY),
        ],
        entry_rules=[
            EntryRule(
                account_role="customer_account",
                entry_type=EntryType.DEBIT,
                amount_source="amount",
                description_template="Debit customer funds",
            ),
            EntryRule(
                account_role="clearing_account",
                entry_type=EntryType.CREDIT,
                amount_source="amount",
                description_template="Credit clearing reserve",
            ),
        ],
        pre_conditions=[],
        post_conditions=[],
    )


def _payment_capture_template() -> PostingTemplate:
    """Confirm an authorization by moving funds from clearing to merchant."""

    return PostingTemplate(
        name="PAYMENT.CAPTURE",
        description="Capture authorized amount to merchant",
        required_accounts=[
            AccountRole(role="clearing_account", required_type=AccountType.LIABILITY),
            AccountRole(role="merchant_account", required_type=AccountType.LIABILITY),
        ],
        entry_rules=[
            EntryRule(
                account_role="clearing_account",
                entry_type=EntryType.DEBIT,
                amount_source="amount",
                description_template="Release clearing reserve",
            ),
            EntryRule(
                account_role="merchant_account",
                entry_type=EntryType.CREDIT,
                amount_source="amount",
                description_template="Credit merchant pending funds",
            ),
        ],
        pre_conditions=[],
        post_conditions=[],
    )


def _payment_settle_template() -> PostingTemplate:
    """Settle captured funds to bank while booking platform fee."""

    return PostingTemplate(
        name="PAYMENT.SETTLE",
        description="Settle merchant amount to bank net of fee",
        required_accounts=[
            AccountRole(role="merchant_account", required_type=AccountType.LIABILITY),
            AccountRole(role="bank_account", required_type=AccountType.LIABILITY),
            AccountRole(role="fee_account", required_type=AccountType.INCOME),
        ],
        entry_rules=[
            EntryRule(
                account_role="merchant_account",
                entry_type=EntryType.DEBIT,
                amount_source="amount",
                description_template="Debit merchant settlement amount",
            ),
            EntryRule(
                account_role="bank_account",
                entry_type=EntryType.CREDIT,
                amount_source="amount - fee",
                description_template="Credit bank net amount",
            ),
            EntryRule(
                account_role="fee_account",
                entry_type=EntryType.CREDIT,
                amount_source="fee",
                description_template="Credit fee revenue",
            ),
        ],
        pre_conditions=[],
        post_conditions=[],
    )


def _payment_reverse_template() -> PostingTemplate:
    """Reverse a prior payment movement by posting the mirrored transfer."""

    return PostingTemplate(
        name="PAYMENT.REVERSE",
        description="Reverse payment movement",
        required_accounts=[
            AccountRole(role="clearing_account", required_type=AccountType.LIABILITY),
            AccountRole(role="customer_account", required_type=AccountType.ASSET),
        ],
        entry_rules=[
            EntryRule(
                account_role="clearing_account",
                entry_type=EntryType.DEBIT,
                amount_source="amount",
                description_template="Debit clearing for reversal",
            ),
            EntryRule(
                account_role="customer_account",
                entry_type=EntryType.CREDIT,
                amount_source="amount",
                description_template="Credit customer on reversal",
            ),
        ],
        pre_conditions=[_require_transaction_id],
        post_conditions=[],
    )


def _require_transaction_id(
    account_map: Mapping[str, str],
    amounts: Mapping[str, Money],
    metadata: Mapping[str, MetadataValue],
) -> None:
    del account_map
    del amounts
    if "transaction_id" not in metadata:
        raise InvalidTemplateError(
            template_name="PAYMENT.REVERSE",
            reason="metadata.transaction_id is required",
        )


PAYMENT_AUTHORIZE = _payment_authorize_template()
PAYMENT_CAPTURE = _payment_capture_template()
PAYMENT_SETTLE = _payment_settle_template()
PAYMENT_REVERSE = _payment_reverse_template()

BUILTIN_TEMPLATES = (
    PAYMENT_AUTHORIZE,
    PAYMENT_CAPTURE,
    PAYMENT_SETTLE,
    PAYMENT_REVERSE,
)

__all__ = [
    "BUILTIN_TEMPLATES",
    "PAYMENT_AUTHORIZE",
    "PAYMENT_CAPTURE",
    "PAYMENT_REVERSE",
    "PAYMENT_SETTLE",
]
