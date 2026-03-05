# 004 - Why Payment Rail Scenario

## Context
Serviva una reference behavior-spec che mostrasse idempotenza, partial capture, reverse e insufficient funds in modo realistico.

## Decision
Implementiamo `PaymentRailScenario` con 5 scenari eseguibili:
- happy path
- partial capture + reverse residuo
- duplicate event idempotente
- late reverse
- insufficient funds

## Consequences
- Il dominio pagamenti diventa testabile end-to-end su MemoryStore e SQLiteStore.
- Le regressioni funzionali emergono nei test scenario, non in produzione.
- Il repository include una demo leggibile oltre ai test unitari.
