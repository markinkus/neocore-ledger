# NeoCore
[![CI](https://github.com/markinkus/NeoCore/actions/workflows/ci.yml/badge.svg)](https://github.com/markinkus/NeoCore/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

NeoCore e' un ledger kernel: motore contabile double-entry, append-only, Decimal-only e idempotente per sistemi finanziari.

Non e' un core banking completo: niente layer HTTP, niente auth/IAM, niente orchestrazione di integrazioni esterne.

## Invariants
- `no float`: ogni importo usa `Decimal`, input `float` rifiutati ([tests/test_money.py](tests/test_money.py)).
- `always balanced`: ogni transazione bilancia `DEBIT == CREDIT` per currency ([tests/test_ledger/test_engine.py](tests/test_ledger/test_engine.py)).
- `append-only`: nessun update/delete di entries/transazioni ([tests/test_ledger/test_store.py](tests/test_ledger/test_store.py)).
- `idempotent post`: stessa idempotency key, stessa transaction, zero side effects ([tests/test_ledger/test_engine.py](tests/test_ledger/test_engine.py)).
- `currency-consistent`: account e amount devono condividere currency ([tests/test_invariants.py](tests/test_invariants.py)).

## Install
Runtime (solo stdlib):
```bash
python3.11 -m pip install neocore-ledger
```

Dev setup:
```bash
python3.11 -m pip install ".[dev]"
```

## 20-second demo
Esegui una demo end-to-end del payment rail:
```bash
python3.11 -m neocore.scenarios.payment_rail
```

Alternativa:
```bash
python3.11 examples/payment_rail.py
```

Output esempio:
```text
NeoCore Payment Rail Demo
happy_path(authorize=100, capture=100, settle fee=1)
customer: Money(0.00 EUR)
clearing: Money(0.00 EUR)
merchant: Money(0.00 EUR)
    bank: Money(-1.00 EUR)
    fees: Money(1.00 EUR)
```

## Minimal example
```python
from decimal import Decimal
from neocore.invariants import OverdraftPolicy
from neocore.ledger.engine import LedgerEngine, PostingInstruction
from neocore.ledger.models import AccountType, EntryType
from neocore.ledger.store import MemoryStore
from neocore.money import Money

ledger = LedgerEngine(MemoryStore())
ledger.create_account(id="cash", name="Cash", account_type=AccountType.ASSET, currency="EUR", metadata={})
ledger.create_account(id="bank", name="Bank", account_type=AccountType.LIABILITY, currency="EUR", metadata={})
ledger.post(idempotency_key="ex-1", description="seed", entries=[
    PostingInstruction("cash", EntryType.DEBIT, Money(Decimal("10.00"), "EUR")),
    PostingInstruction("bank", EntryType.CREDIT, Money(Decimal("10.00"), "EUR")),
], metadata={}, overdraft_policy=OverdraftPolicy.allow_overdraft())
print(ledger.get_balance("cash"))
```

## Why NeoCore
- `beancount` / `django-ledger`: ottimi per accounting, NeoCore e' transaction kernel + posting templates + payment rail scenario.
- `Apache Fineract` (e piattaforme simili): piattaforme complete; NeoCore e' un kernel integrabile, piccolo e composabile.
- Focus NeoCore: invariants forti + API Python typed + testability cross-store (memory/sqlite).

## Roadmap
- [x] v0.1.0 - Kernel + templates + payment rail scenario
- [~] v0.2.0 - SQLiteStore + idempotency persistence (parzialmente completa)
- [ ] v0.3.0 - Postgres store
- [ ] v0.4.0 - ISO20022 adapters

## Docs
- [Double-entry in 3 minutes](docs/double-entry-in-3-minutes.md)
- [Idempotency and retry](docs/idempotency-and-retry.md)
- [Posting templates and payment rail](docs/posting-templates-and-payment-rail.md)

## Decision log
- [001 - Why Decimal](docs/decisions/001-why-decimal.md)
- [002 - Why Append-Only](docs/decisions/002-why-append-only.md)
- [003 - Why Templates](docs/decisions/003-why-templates.md)
- [004 - Why Payment Rail](docs/decisions/004-why-payment-rail.md)

## Contributing
Vedi [CONTRIBUTING.md](CONTRIBUTING.md).
