# Risk decision

All data is synthetic. This record covers one decision.

| Item | Entry |
|---|---|
| Risk | The warehouse is one local DuckDB file. It has no per-user read audit. Anyone with file access can read all raw and mart tables, and no log shows who did |
| Options | 1. Accept the risk for this stage. 2. Mitigate now with a managed warehouse that has access logs. 3. Transfer the risk to a cloud provider's audit service |
| Decision | Accept |
| Reason | The data is synthetic. A managed warehouse adds cost and setup that gives no value for synthetic data. The gap is written down and has a trigger |
| Owner | Stanley Sujith Nelavala |
| Review date | 2027-02-01, or before the first run with real data, whichever is earlier |
| Mitigation before real data | Use a managed warehouse with access logs. Give roles per user. Write the access review process. Move keys to Key Vault |
| Compensating controls today | Pseudonymized tokens. k-anonymity before the curated files. Small-cell rule on the prevalence mart. A provenance manifest for each run. A load log. Landing blobs stay in a separate zone in the design |
| Evidence | `docs/engagement/HIPAA-STYLE-MAP.md`, `docs/engagement/THREAT-MODEL.md` |

This record does not claim compliance with any rule.
