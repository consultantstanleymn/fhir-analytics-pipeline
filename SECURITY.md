# Security

This is a portfolio project. It is not a production system. It does not claim HIPAA compliance.

## What the project does
- Uses synthetic data only. A seeded script generates it. No real patient data is in the repository or used by the tests.
- Replaces patient ids and MRNs with HMAC-SHA256 tokens before any data reaches the warehouse.
- Drops names, street addresses, phone numbers and free text. It reduces birth date to birth year and address to state.
- Reads the HMAC keys from `FHIR_HMAC_KEYS` and `FHIR_HMAC_ACTIVE` (or the single key `FHIR_HMAC_KEY`, which becomes key id `v1`), and the storage connection string from `AZURE_STORAGE_CONNECTION_STRING`. None of them is in code.
- Puts a key id in every token (`v1.<digest>`). A new key gives new tokens, and old files stay readable. See `docs/engagement/KEY-ROTATION.md`.
- Applies k-anonymity (k=5 by default, `FHIR_K_ANON`) on birth year, state and gender before the curated patient file, and hides small counts in the condition prevalence mart. See `docs/DECISIONS.md` entry 13.
- Writes a provenance manifest for each run, with SHA-256 hashes of the input blobs.
- Maps the controls to HIPAA-style safeguard areas, with status and gaps, in `docs/engagement/HIPAA-STYLE-MAP.md`. The map makes no compliance claim.
- Runs a local security gate (bandit, semgrep, pip-audit, gitleaks, SBOM). See `docs/engagement/SECURITY-GATE.md`.
- Describes the Azure target with TLS 1.2 minimum, HTTPS only, no public blob access, Key Vault soft delete and purge protection. Tests check these flags in the compiled template.

## What the project does not do
- It does not meet HIPAA. It has no risk analysis, no access audit trail, no breach process and no business associate agreements.
- Pseudonymization here is a design demo. Tokens from one key can be linked across tables. Rare birth years, states and dates can still identify people in a small real population. De-identification of real data needs expert review.
- The keys are plain environment variables. A real system keeps them in a vault with a rotation schedule. The Bicep file has a Key Vault, but nothing reads from it.
- k-anonymity lowers the risk of re-identification. It does not remove it. It covers three fields only, and encounter marts keep exact dates.
- The provenance manifest has no signature. A person with write access can change both a file and its hash.
- Nothing is deployed to Azure. The Bicep file is compiled and linted only.
- The DuckDB file and the Parquet files are not encrypted by this project.
- The Azurite connection string in tests and scripts uses the public, documented emulator account key. It is not a secret. Secret scanners may flag it.

## Reporting
Open an issue in the repository for any problem you find. Do not post real patient data.
