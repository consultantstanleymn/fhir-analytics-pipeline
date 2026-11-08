# Security

This is a portfolio project. It is not a production system. It does not claim HIPAA compliance.

## What the project does
- Uses synthetic data only. A seeded script generates it. No real patient data is in the repository or used by the tests.
- Replaces patient ids and MRNs with HMAC-SHA256 tokens before any data reaches the warehouse.
- Drops names, street addresses, phone numbers and free text. It reduces birth date to birth year and address to state.
- Reads the HMAC key from `FHIR_HMAC_KEY` and the storage connection string from `AZURE_STORAGE_CONNECTION_STRING`. Neither is in code.
- Describes the Azure target with TLS 1.2 minimum, HTTPS only, no public blob access, Key Vault soft delete and purge protection. Tests check these flags in the compiled template.

## What the project does not do
- It does not meet HIPAA. It has no risk analysis, no access audit trail, no breach process and no business associate agreements.
- Pseudonymization here is a design demo. Tokens from one key can be linked across tables. Rare birth years, states and dates can still identify people in a small real population. De-identification of real data needs expert review.
- The key is a plain environment variable. A real system keeps it in a vault with rotation. The Bicep file has a Key Vault, but nothing reads from it.
- Nothing is deployed to Azure. The Bicep file is compiled and linted only.
- The DuckDB file and the Parquet files are not encrypted by this project.
- The Azurite connection string in tests and scripts uses the public, documented emulator account key. It is not a secret. Secret scanners may flag it.

## Reporting
Open an issue in the repository for any problem you find. Do not post real patient data.
