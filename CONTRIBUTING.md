# Contributing

## Requirements
- Python 3.11+

## Setup
```bash
python3.11 -m pip install .
python3.11 -m pip install pytest ruff mypy
```

## Quality Gates
```bash
python3.11 -m pytest -q
python3.11 -m ruff check .
python3.11 -m mypy .
```

## Development Rules
- Test-first: aggiungi test prima della feature.
- Runtime deps: solo stdlib obbligatoria.
- Importi: solo `Decimal` (mai float in input).
- Ledger: append-only, correzioni via nuove transazioni.
- Idempotenza: rispetta il comportamento di `LedgerEngine.post`.
