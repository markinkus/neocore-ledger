# 001 - Why Decimal

## Context
NeoCore gestisce importi monetari e richiede risultati deterministici tra ambienti e store diversi.

## Decision
Usiamo `decimal.Decimal` ovunque (`Money`, entry, conversioni, fee). Input `float` rifiutati con `TypeError`.

## Consequences
- Evitiamo errori binari tipici di `float` (`0.1 + 0.2 != 0.3`).
- I test finanziari restano stabili nel tempo.
- Le integrazioni devono convertire esplicitamente i float prima di chiamare NeoCore.
