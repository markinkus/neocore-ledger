# 002 - Why Append-Only

## Context
Un ledger deve mantenere tracciabilita' storica completa e auditabile.

## Decision
`transactions` e `entries` sono append-only. Nessuna API di update/delete. Correzioni tramite nuove transazioni.

## Consequences
- Il passato resta verificabile e non mutabile.
- Gli errori operativi si risolvono con reversal/adjustment espliciti.
- Store in-memory e SQLite condividono lo stesso modello immutabile.
