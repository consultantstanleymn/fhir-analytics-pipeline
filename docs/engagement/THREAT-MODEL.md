# Threat model

Short model for the main risks. All data is synthetic. A full STRIDE table for a larger service is in the sibling console project and is not repeated here.

| Threat | How it could happen | Control today | Gap |
|---|---|---|---|
| Re-identification of a person from the marts | A reader joins birth year, state and gender with outside data | k-anonymity (k=5) with generalization and dropping before the curated file. Small-cell rule on the prevalence mart | Encounter-level marts keep exact dates. The check covers only three quasi-identifiers |
| Linking of tokens across tables | The same key gives the same token for one patient in every table | Different namespace per field. Key id in the token | Linking inside one key version is by design. A leaked key lets an attacker test guesses |
| Key leak | The key sits in an environment variable or a log | The key is read from the environment and never written to a file or log. Rotation steps are written | No vault read. No rotation schedule. No alert on key use |
| Landing zone access | A reader opens the landing blobs and sees source ids and names | Separate zone in the design. Private blob access in the Bicep file | No role check at run time. Not deployed |
| Manifest tampering | Someone edits the manifest or an input file after the run | The manifest holds SHA-256 hashes of the inputs and of the dbt manifest | The manifest has no signature. Anyone with write access can replace both the file and the hash |
| Bad input floods the marts | A source sends many broken or changed rows | Quarantine-rate gate. dbt contracts. Source freshness check | The gate limit is one number for all resources |
| Silent late data | An update arrives late and is skipped | Incremental model on the load time. Test for a late update | None known |

See `docs/engagement/HIPAA-STYLE-MAP.md` for the control map and `docs/engagement/RISK-DECISION.md` for the accepted risk.
