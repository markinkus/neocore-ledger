Eccolo. Un piano che puoi seguire passo passo senza dover pensare a cosa fare dopo.

---

## NeoCore — Piano di Implementazione Completo

### Struttura del repo finale

```
neocore/
├── neocore/
│   ├── __init__.py
│   ├── money.py              # Money, Currency, RoundingRule
│   ├── invariants.py         # assert_balanced, assert_currency_consistency, ecc.
│   ├── ledger/
│   │   ├── __init__.py
│   │   ├── models.py         # Account, Entry, Transaction, Journal
│   │   ├── engine.py         # LedgerEngine
│   │   └── store.py          # LedgerStore protocol + MemoryStore + SQLiteStore
│   ├── templates/
│   │   ├── __init__.py
│   │   ├── engine.py         # TemplateEngine
│   │   ├── registry.py       # Registry dei template
│   │   └── builtins.py       # PAYMENT.AUTHORIZE, CAPTURE, SETTLE, REVERSE
│   └── scenarios/
│       ├── __init__.py
│       └── payment_rail.py   # Demo completa end-to-end
├── tests/
│   ├── test_money.py
│   ├── test_invariants.py
│   ├── test_ledger/
│   │   ├── test_engine.py
│   │   └── test_store.py
│   ├── test_templates/
│   │   ├── test_engine.py
│   │   └── test_builtins.py
│   └── test_scenarios/
│       └── test_payment_rail.py
├── docs/
│   ├── decisions/
│   │   ├── 001-why-decimal.md
│   │   ├── 002-why-append-only.md
│   │   ├── 003-why-templates.md
│   │   └── 004-why-payment-rail.md
│   └── concepts/
│       ├── double-entry.md
│       ├── idempotency.md
│       └── posting-templates.md
├── pyproject.toml
├── README.md
└── CONTRIBUTING.md
```

---

### Fase 0 — Setup ambiente (1 sessione)

**0.1 Crea il repo**
```bash
mkdir neocore && cd neocore
git init
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

**0.2 Installa dev dependencies**
```bash
pip install pytest pytest-cov ruff mypy
```

**0.3 pyproject.toml**
Configura: nome `neocore`, versione `0.1.0`, `requires-python = ">=3.11"`, zero dipendenze obbligatorie. Optional: `sqlite` per SQLiteStore. Dev deps: pytest, ruff, mypy.

**0.4 VSCode settings**
Crea `.vscode/settings.json` con: Python interpreter puntato al venv, ruff come formatter, mypy come type checker, pytest come test runner. Installa le estensioni: Python, Pylance, Ruff, Even Better TOML.

**0.5 `.gitignore`**
Standard Python: `__pycache__`, `.venv`, `.mypy_cache`, `.pytest_cache`, `*.egg-info`, `dist/`.

---

### Fase 1 — Money & Currency (1-2 sessioni)

Questo è il fondamento. Va fatto prima di tutto il resto e va fatto perfettamente.

**1.1 `neocore/money.py`**

Costruisci nell'ordine:

`CurrencyConfig` — dataclass con `code` (ISO 4217), `decimal_places` (int), `rounding_default` (enum). Esempi: EUR ha 2 decimali, JPY ha 0, BTC ha 8.

`RoundingRule` — enum con: `HALF_EVEN` (banker's rounding, default), `HALF_UP` (rounding classico), `FLOOR` (per fee che non si arrotondano mai in favore del cliente).

`OperationType` — enum con: `DEFAULT`, `FEE`, `FX_CONVERSION`, `INTEREST`, `TAX`. Serve per selezionare la rounding rule giusta per operazione.

`CURRENCY_REGISTRY` — dizionario `dict[str, CurrencyConfig]` con almeno: EUR, USD, GBP, JPY, CHF, BTC, USDC. Estendibile dall'utente.

`Money` — frozen dataclass con `amount: Decimal` e `currency: str`. Il `__post_init__` deve: convertire qualsiasi input a Decimal (mai accettare float silenziosamente — raise TypeError se arriva un float), quantize secondo la CurrencyConfig della currency, applicare il rounding rule di default. Implementa: `__add__`, `__sub__`, `__neg__`, `__mul__` (solo per scalari Decimal/int), `__eq__`, `__lt__`, `__le__`, `is_zero()`, `__repr__`. Il metodo `quantize(rule: RoundingRule)` restituisce un nuovo Money con l'arrotondamento specificato. Il metodo `convert(to_currency, rate, operation)` restituisce un nuovo Money nella valuta di destinazione applicando la rounding rule corretta per l'operazione.

**1.2 `tests/test_money.py`**

Scrivi i test prima di considerare il modulo finito. Casi obbligatori: float input solleva TypeError, 10.999 EUR arrotonda a 11.00 con HALF_EVEN, 10.995 EUR arrotonda a 11.00 con HALF_EVEN (non 10.99), somma di stessa currency funziona, somma di currency diverse solleva ValueError, JPY non ha decimali (100.7 JPY → 101 JPY), conversione EUR→USD con rate e rounding corretto, `Money.zero("EUR")` funziona, repr leggibile.

---

### Fase 2 — Ledger Models (1 sessione)

**2.1 `neocore/ledger/models.py`**

`AccountType` — enum: `ASSET`, `LIABILITY`, `EQUITY`, `INCOME`, `EXPENSE`. Ogni tipo ha un `normal_balance` (DEBIT o CREDIT) — questo determina se un debit aumenta o diminuisce il saldo.

`Account` — frozen dataclass: `id: str`, `name: str`, `account_type: AccountType`, `currency: str`, `parent_id: Optional[str]`, `metadata: dict`. Metodo `normal_balance() -> EntryType`.

`EntryType` — enum: `DEBIT`, `CREDIT`.

`Entry` — frozen dataclass: `id: str`, `account_id: str`, `entry_type: EntryType`, `amount: Money`, `transaction_id: str`, `created_at: datetime`. Il `__post_init__` valida che amount sia positivo.

`Transaction` — frozen dataclass: `id: str`, `idempotency_key: str`, `description: str`, `entries: tuple[Entry, ...]`, `created_at: datetime`, `metadata: dict`. Il `__post_init__` chiama `_validate_balance()` che verifica debits == credits per ogni currency presente. Se non bilanciato solleva `UnbalancedTransactionError` con dettaglio su quale currency e di quanto.

---

### Fase 3 — Invarianti come API pubblica (1 sessione)

**3.1 `neocore/invariants.py`**

Questo modulo è sia validazione interna che API pubblica per chi costruisce sopra NeoCore. Ogni funzione deve avere una docstring che spiega *perché* quell'invariante esiste, non solo cosa fa.

`assert_balanced(entries)` — verifica debits == credits per currency. Solleva `UnbalancedTransactionError` con messaggio dettagliato: quale currency, quanto manca, quali sono le entry coinvolte.

`assert_currency_consistency(account, money)` — verifica che la currency del Money corrisponda alla currency dell'Account. Solleva `CurrencyMismatchError`.

`assert_no_negative_balance(account_id, balance, policy)` — `policy` è un enum: `STRICT` (mai negativo), `ALLOW_OVERDRAFT` (negativo OK), `OVERDRAFT_LIMIT(amount)` (negativo fino a un limite). Solleva `InsufficientFundsError` con available e required.

`assert_idempotent(key, store)` — verifica che la chiave non esista già nello store. Se esiste, solleva `DuplicateTransactionError` con l'id della transazione originale.

`assert_valid_account_type_for_entry(account, entry_type)` — warning (non errore) se si fa un entry nel verso "insolito" per quel tipo di conto. Utile per debugging.

**3.2 `neocore/exceptions.py`**

Tutti i custom exceptions in un file solo: `NeoCoreError` (base), `UnbalancedTransactionError`, `CurrencyMismatchError`, `InsufficientFundsError`, `DuplicateTransactionError`, `AccountNotFoundError`, `InvalidTemplateError`, `TemplateNotFoundError`. Ogni exception porta i dati strutturati necessari per logging e debugging, non solo un messaggio stringa.

---

### Fase 4 — Store (1-2 sessioni)

**4.1 `neocore/ledger/store.py`**

`LedgerStore` — Protocol con tutti i metodi necessari. Ogni metodo documentato con le garanzie che deve rispettare (atomicità, idempotency, ecc.).

`MemoryStore` — implementazione in-memory. Deve essere thread-safe (usa `threading.Lock` per le operazioni di write). Non è per production ma deve comportarsi esattamente come un DB store reale — nessuna scorciatoia che poi non funzionerebbe con Postgres.

`SQLiteStore` — implementazione SQLite. Schema: tabella `accounts`, tabella `transactions`, tabella `entries` (append-only — nessun UPDATE/DELETE mai), tabella `idempotency_keys` con unique constraint su `key`. Usa `sqlite3` della stdlib, zero dipendenze esterne. La connessione deve usare `check_same_thread=False` con locking esplicito. Ogni write è in una transaction SQLite esplicita (`BEGIN IMMEDIATE`).

**4.2 Test per entrambi gli store**

I test devono essere parametrizzati con `@pytest.fixture(params=["memory", "sqlite"])` così ogni test gira su entrambi gli store automaticamente. Questo garantisce che MemoryStore e SQLiteStore si comportino identicamente.

---

### Fase 5 — LedgerEngine (1-2 sessioni)

**5.1 `neocore/ledger/engine.py`**

`LedgerEngine` — classe principale. Riceve uno store nel costruttore.

`create_account(id, name, type, currency, parent_id, metadata)` — crea e persiste. Valida che parent esista se specificato. Valida che id non esista già.

`post(idempotency_key, description, entries, metadata, overdraft_policy)` — il metodo più importante. Sequenza esatta: (1) check idempotency — se key esiste ritorna la transazione originale senza fare nulla, (2) valida che tutti gli account esistano, (3) valida currency consistency per ogni entry, (4) costruisce gli Entry objects, (5) costruisce Transaction che valida il balance nel `__post_init__`, (6) check overdraft policy per account ASSET con debit, (7) persiste. Tutto in questo ordine, nessuna eccezione.

`get_balance(account_id, as_of)` — aggrega tutte le entry per quell'account fino a `as_of`. Usa la logica normal_balance per determinare il segno.

`get_statement(account_id, since, until)` — lista cronologica con running balance dopo ogni entry.

`reconcile(account_ids)` — trial balance per un set di account. Ritorna un `ReconciliationReport` con per-account balance e verifica assets+expenses == liabilities+equity+income.

---

### Fase 6 — Posting Templates (2 sessioni)

Questa è la parte più originale del progetto. Prenditi il tempo giusto.

**6.1 `neocore/templates/engine.py`**

Un template descrive: quali account coinvolge (per ruolo, non per id), quali entry genera, quali invarianti deve soddisfare prima e dopo.

`PostingTemplate` — dataclass: `name: str`, `description: str`, `required_accounts: list[AccountRole]`, `entry_rules: list[EntryRule]`, `pre_conditions: list[Callable]`, `post_conditions: list[Callable]`.

`AccountRole` — dataclass: `role: str` (es. `"customer_account"`), `required_type: AccountType`, `required_currency: Optional[str]`.

`EntryRule` — dataclass: `account_role: str`, `entry_type: EntryType`, `amount_source: str` (es. `"amount"`, `"fee"`, `"amount - fee"`), `description_template: str`.

`TemplateEngine.apply(template_name, account_map, amounts, idempotency_key, metadata)` — risolve i ruoli agli account reali, calcola gli importi, genera le entry, applica pre e post conditions, chiama `ledger.post()`. Ritorna la Transaction.

**6.2 `neocore/templates/registry.py`**

`TemplateRegistry` — dizionario di template con `register(template)` e `get(name)`. Singleton globale `DEFAULT_REGISTRY` con i builtin già registrati. L'utente può creare registry personalizzati o aggiungere template al default.

**6.3 `neocore/templates/builtins.py`**

I 4 template del payment rail. Ogni template documentato con: cosa rappresenta nel mondo reale, quali account coinvolge, come si bilancia, quale stato del pagamento produce.

`PAYMENT_AUTHORIZE` — blocca fondi dal conto cliente verso un conto di holding (clearing). Non è ancora un movimento reale, è una prenotazione. Entry: debit customer_account, credit clearing_account.

`PAYMENT_CAPTURE` — conferma il pagamento autorizzato. Sposta i fondi dal clearing verso il merchant. Entry: debit clearing_account, credit merchant_account. Nota: amount può essere ≤ authorized amount (capture parziale).

`PAYMENT_SETTLE` — il settlement finale con la banca. Sposta i fondi al netto delle fee. Entry: debit merchant_account (amount), credit bank_account (amount - fee), credit fee_account (fee).

`PAYMENT_REVERSE` — annulla una transazione. Genera le entry speculari rispetto all'operazione originale. Richiede il `transaction_id` originale. Valida che la transazione originale esista e che la currency corrisponda.

---

### Fase 7 — Reference Scenario: Payment Rail (1-2 sessioni)

**7.1 `neocore/scenarios/payment_rail.py`**

Non è solo una demo — è una specifica eseguibile di come il sistema si comporta in condizioni reali. Deve essere leggibile come documentazione.

`PaymentRailScenario` — classe che configura il chart of accounts necessario (customer, clearing, merchant, bank, fees) e espone metodi per ogni operazione.

Scenario 1 — **Happy path**: authorize 100 EUR → capture 100 EUR → settle 100 EUR (con fee 1 EUR) → verifica balance finale su tutti i conti.

Scenario 2 — **Partial capture**: authorize 100 EUR → capture 80 EUR → verifica che 20 EUR rimangano nel clearing → reverse dei 20 EUR rimanenti.

Scenario 3 — **Duplicate event**: authorize con idempotency key `"pay-001"` → tentativo di seconda authorize con stessa key → verifica che ritorni la transazione originale senza creare entry duplicate → balance immutato.

Scenario 4 — **Late reverse**: authorize → capture → settle → reverse dopo il settle → verifica che il reverse generi entry corrette anche dopo il settlement.

Scenario 5 — **Insufficient funds**: authorize 1000 EUR su account con 500 EUR → verifica InsufficientFundsError con available e required corretti.

**7.2 `tests/test_scenarios/test_payment_rail.py`**

Ogni scenario diventa un test. I test dei scenari sono più importanti dei test unitari per chi valuta il progetto — mostrano comportamento reale, non solo correttezza interna.

---

### Fase 8 — Documentazione (1-2 sessioni, non alla fine — in parallelo)

**8.1 Decision log — `docs/decisions/`**

Ogni file segue il formato: **Contesto** (qual era il problema), **Decisione** (cosa abbiamo scelto), **Conseguenze** (cosa implica, cosa esclude, cosa diventa più facile/difficile). Scrivi questi mentre costruisci, non dopo.

`001-why-decimal.md` — perché Decimal e non float, con esempi concreti di bug che float produce in contesti finanziari.

`002-why-append-only.md` — perché il ledger non ha UPDATE/DELETE, con spiegazione di come si fa un "correction" senza mutare il passato.

`003-why-templates.md` — perché i posting template e non entry manuali, con esempio di cosa succede senza template (inconsistenza possibile) e con template (inconsistenza impossibile).

`004-why-payment-rail.md` — perché il payment rail come reference scenario, quali edge cases espone, perché quegli specifici 5 scenari.

**8.2 `README.md` — struttura esatta**

Sezione 1: una frase su cosa è NeoCore, una frase su cosa non è.
Sezione 2: installazione in 2 comandi.
Sezione 3: esempio minimo funzionante (10 righe, copy-pastabile, produce output visibile).
Sezione 4: il payment rail scenario con output commentato.
Sezione 5: link ai decision log.
Sezione 6: come contribuire.

Il README non deve vendere — deve insegnare. Chi lo legge deve capire double-entry accounting meglio di prima.

---

### Ordine di esecuzione in VSCode

```
Fase 0  →  Setup (fai subito, 30 minuti)
Fase 1  →  money.py + tests  (base di tutto)
Fase 3  →  exceptions.py     (serve prima dell'engine)
Fase 2  →  ledger/models.py  (dipende da Money)
Fase 4  →  store.py          (dipende da models)
Fase 5  →  engine.py         (dipende da store + invariants)
Fase 3  →  invariants.py     (completa dopo engine)
Fase 6  →  templates/        (dipende da engine)
Fase 7  →  scenarios/        (dipende da templates)
Fase 8  →  docs/             (in parallelo da Fase 1)
```

---

### Regole di sviluppo

**Test first su tutto.** Scrivi il test prima dell'implementazione. Se non sai come testarlo, il design è sbagliato.

**Zero dipendenze obbligatorie.** `pip install neocore` deve funzionare senza tirare dentro niente. SQLite è stdlib. Postgres e httpx sono optional.

**Mypy strict su tutto.** Nessun `Any` non giustificato. I type hint sono documentazione eseguibile.

**Ruff su tutto.** Nessuna eccezione. Configura pre-commit hook dal primo giorno.

**Ogni commit rompe o aggiunge un test verde.** Mai committare codice che fa passare test che prima fallivano per ragioni sbagliate.

---

Questo è il piano.