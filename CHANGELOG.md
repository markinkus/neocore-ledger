# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-03-05
### Added
- Strict ledger kernel with double-entry validation per currency.
- Decimal-only `Money` primitives with explicit rounding and FX conversion rules.
- Append-only `MemoryStore` and `SQLiteStore` with idempotency key persistence.
- `LedgerEngine` APIs for posting, balances, statements, and reconciliation.
- Posting templates and builtin payment flow templates.
- End-to-end `PaymentRailScenario` with five reference scenarios.
- Test suite, mypy strict typing, and Ruff linting configuration.

## [0.1.1] - 2026-03-05
### Changed
- Publish distribution name changed from `neocore` to `neocore-ledger` due existing PyPI project name conflict.
- Packaging metadata aligned for first public PyPI release of NeoCore ledger kernel.
