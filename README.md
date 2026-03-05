# NeoCore
NeoCore è un **ledger kernel**: un motore contabile **double-entry**, **append-only**, **Decimal-only** e **idempotente** per sistemi finanziari.
Non è un core banking completo: è la parte che non vuoi sbagliare quando costruisci wallet, PSP, marketplace, e-money o accounting interno.

## A cosa serve?
NeoCore serve a garantire che la contabilità del tuo prodotto finanziario sia corretta e auditabile:
double-entry, append-only, Decimal-only e idempotenza.
È il motore contabile su cui costruisci API, auth e workflow senza reinventare la parte più critica.

## What NeoCore is
- **Double-entry**: ogni transazione deve bilanciare DEBIT == CREDIT (per valuta).
- **Append-only**: niente UPDATE/DELETE sul ledger. Le correzioni sono nuove transazioni.
- **Idempotente**: eventi duplicati (retry webhook/polling) non duplicano scritture.
- **Decimal-only**: vietati float. Armonizza rounding per valuta e per tipo operazione.
- **Posting templates**: struttura bancaria per flussi standard (payment rail authorize/capture/settle/reverse).

## What NeoCore is NOT
- Non è un framework web (niente HTTP, routing, versioning API).
- Non include auth/authz, multi-tenant, ruoli o IAM.
- Non è un orchestratore di workflow o integrazioni esterne.
- Non è “un sostituto di COBOL”: è un kernel affidabile da integrare in architetture moderne.

## Install
Runtime (nessuna dipendenza obbligatoria oltre alla stdlib):
```bash
python3.11 -m pip install .
python3.11 -m pip install pytest ruff mypy
```

## Minimal Example
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

Output atteso:
```text
Money(10.00 EUR)
```

## Payment Rail Demo
```python
from decimal import Decimal
from neocore.ledger.store import MemoryStore
from neocore.money import Money
from neocore.scenarios.payment_rail import PaymentRailScenario

scenario = PaymentRailScenario(MemoryStore())
result = scenario.run_happy_path(
    amount=Money(Decimal("100.00"), "EUR"),
    fee=Money(Decimal("1.00"), "EUR"),
)
print(result["fees"], result["clearing"])  # fee contabilizzata, clearing chiuso
```

## Decision Log
- [001 - Why Decimal](docs/decisions/001-why-decimal.md)
- [002 - Why Append-Only](docs/decisions/002-why-append-only.md)
- [003 - Why Templates](docs/decisions/003-why-templates.md)
- [004 - Why Payment Rail](docs/decisions/004-why-payment-rail.md)

## Contributing
Vedi [CONTRIBUTING.md](CONTRIBUTING.md).
