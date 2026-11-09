# Decision records

The design decisions for this project are in one file: `docs/DECISIONS.md`. Each entry has a choice and a reason.

| Entry | Topic |
|---|---|
| 1 | DuckDB as the warehouse |
| 4 | Pseudonymize before load |
| 5 | Raw tables are append-only |
| 6 | Incremental model on the raw load time |
| 10 | Azure: emulator and Bicep only |
| 13 | k-anonymity at publish, small cells in one mart |

The risk decision is in `docs/engagement/RISK-DECISION.md`.
