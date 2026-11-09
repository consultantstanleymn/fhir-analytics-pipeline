Fictional customer. Any match with a real company is not intended.

# Scenario: RegionalHealthCo

All data is synthetic. No real patient data is in the repository, the tests or the output.

## Scenario

RegionalHealthCo is a three-hospital system. The quality office wants two daily reports: the 30-day readmission rate and the length of stay. The reports must be published by 06:00 each day.

The privacy officer asks two questions:

1. Can anyone re-identify a patient from the published marts?
2. Who can read the marts?

The engagement answers these questions with tests and documents. It does not make a compliance claim. It does not certify the system.

### Data

- Input: FHIR R4 NDJSON bulk-export files for Patient, Encounter, Condition and Observation.
- Source: a seeded synthetic generator. The generator adds known defects so the quality gates have work to do.
- Landing zone: Azure Blob Storage, through the Azurite emulator.
- Output: Parquet marts in a curated container, plus a run summary and a provenance manifest.

### Questions the marts answer

- How many inpatient encounters occur per department per week?
- What is the 30-day readmission rate?
- What is the length of stay?
- How common is each recorded condition?

### Scope

- A daily batch run under Airflow.
- Per-line validation. A rejected line goes to quarantine with a reason.
- Pseudonymization before load. Names, street addresses, phone numbers and free text do not reach the warehouse.
- Raw tables in DuckDB, and dbt models for the staging, intermediate and marts layers.
- A Parquet export of each mart.
- Quality gates: dbt tests, source freshness, contracts on the marts and a quarantine-rate limit.
- A provenance manifest for each run.
- k-anonymity on the patient quasi-identifiers in `dim_patient`.
- A versioned HMAC key for tokens.
- A HIPAA-style control map with a status and evidence for each control.
- Metrics, one freshness objective, one alert rule and one dashboard panel.
- A failure lab with four cases.
- A local security gate.

### Out of scope

- Real patient data.
- A deployed Azure subscription. The Bicep files are compiled and linted, not applied.
- A FHIR server, SMART on FHIR, HL7 v2 or an EHR vendor interface.
- A cloud warehouse. DuckDB stands in for it.
- Real-time or streaming ingest.
- A HIPAA compliance claim, a certification or a legal opinion.
- Production identity and access management. The control map describes this gap.

### Acceptance criteria

The eight acceptance criteria are in `docs/engagement/ACCEPTANCE.md`. Each criterion has a measurable check, a proof command and an evidence file. The status starts at `not started`.

## 1. Users and their questions

- Quality analyst: needs the readmission and length-of-stay marts before 06:00.
- Privacy officer: needs evidence that the marts do not expose a person, and a clear description of who can read them.
- Data engineer: needs a repeatable run, a failure procedure and a stable schema.
- Reviewer: needs a proof for each claim.

## 2. Success

The engagement succeeds when all eight acceptance criteria are met on the local machine. Each claim has a command and a saved output. Performance numbers are measured on one laptop.

## 3. Limits

The system is a portfolio project. It shows the shape of a controlled pipeline. It does not replace a production data platform. The control map lists the controls that are built, partly built, not built and out of scope.
