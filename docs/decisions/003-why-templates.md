# 003 - Why Posting Templates

## Context
Posting manuali ripetitivi aumentano il rischio di errori (ruoli account sbagliati, importi sbilanciati, fee inconsistenti).

## Decision
Introduciamo `PostingTemplate` + `TemplateEngine`: ruoli dichiarativi, regole entry e amount expressions (`amount - fee`).

## Consequences
- I flussi ricorrenti diventano standardizzati e riusabili.
- Le validazioni su ruoli/tipi/currency avvengono prima del posting.
- Estendere NeoCore richiede definire template, non riscrivere logica imperativa.
