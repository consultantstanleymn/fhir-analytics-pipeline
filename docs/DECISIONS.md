# Decisions

Each entry gives the choice, the reason, and the cost.

## 1. DuckDB as the warehouse
- Choice: one DuckDB file holds the raw, staging, intermediate and marts schemas.
- Reason: it runs on a laptop with no service. dbt-duckdb is a real dbt adapter.
- Cost: DuckDB has one writer at a time. A cloud warehouse (Snowflake, BigQuery, Databricks) is not used here.

## 2. Two Python environments
- Choice: Airflow and the pipeline code live in `.venv`. dbt and sqlfluff live in `.venv-dbt`.
- Reason: `pip` can not resolve Airflow 3.4.0 (with its official constraints file) together with dbt-core. This was seen on the build machine.
- Cost: the pipeline starts dbt as a subprocess. `DBT_BIN` points to the dbt venv. Both venvs pin `duckdb==2.0.0`, so the database file is compatible.

## 3. Validate with `fhir.resources` R4B, plus our own checks
- Choice: use the R4B models. R4B is FHIR 4.3.0, the maintenance release of R4. The package has no separate R4 (4.0.1) module.
- Observed: the models check structure and types. They do not check required code bindings. An Encounter with status `not-a-status` passes the model.
- Fix: `validate.py` has a small table of required bindings (Encounter.status, Observation.status, Patient.gender). It also has two business rules: a Patient subject reference and `meta.lastUpdated` must exist.
- Cost: the table covers only the fields this pipeline uses.

## 4. Pseudonymize before load
- Choice: the raw DuckDB tables never hold names, street addresses, phone numbers or free text.
- Method: HMAC-SHA256 with a key from the environment. The same input and key give the same token. A different key gives a different token.
- Reduction: birth date becomes birth year. Address becomes state.
- Cost: this is a design demo. It is not a HIPAA compliance claim. See `SECURITY.md`.

## 5. Raw tables are append-only; dbt picks the latest version
- Choice: every valid line is appended with `_loaded_at` and `_source_blob`. Staging models keep the newest version per resource id (`meta.lastUpdated`, then `_loaded_at`).
- Reason: duplicates and late updates are handled in one place, in SQL, and the raw history stays.
- A load log skips a blob that was loaded before. A second run on the same landing folder adds no rows.

## 6. Incremental `fct_encounters` on the raw load time
- Choice: `delete+insert` on `encounter_id`. Only rows with a raw load time (`_loaded_at`) above the table maximum of `source_loaded_at` are processed.
- The first design filtered on `meta.lastUpdated`. An update with a `lastUpdated` older than the table maximum was skipped. That gap is fixed.
- Why the load time and not a lookback window on `lastUpdated`: a window of N days still misses an update that arrives later than N days. It also rewrites every row in the window on each run, which changes `dbt_loaded_at` for rows that did not change. The load time catches any late arrival and leaves unchanged rows alone.
- Cost: one extra column, `source_loaded_at`, in `fct_encounters`. An existing warehouse needs `dbt run --full-refresh --select fct_encounters` once, because the model fails on a schema change by design. A re-load of an old blob (a new load time, same content) rewrites its rows with identical values.
- When two versions of one encounter exist, the staging model keeps the one with the higher `lastUpdated`. A late update with an older `lastUpdated` than the stored version does not replace it.
- Tests: `test_late_update_older_than_max_is_applied`, `test_incremental_rerun_is_idempotent`, and the update-batch test.

## 7. Readmission definition
- Index stay: inpatient (class `IMP`), finished, patient did not die (`dischargeDisposition = exp` excludes).
- Readmitted: the same patient has another inpatient stay that starts at or after the index discharge and within 30 calendar days. A stay exactly 30 days later counts.
- Not modeled: planned readmissions, transfers between facilities, observation stays.
- The hand-written fixture has 12 encounters, 9 index stays and 3 readmissions. A dbt unit test and a pytest check use it.

## 8. One writer to DuckDB, so resource groups run in order
- Choice: the DAG runs Patient, Encounter, Condition and Observation groups one after another.
- Reason: parallel tasks would fight for the DuckDB write lock.

## 9. DAG file stays light
- Choice: the DAG file imports only Airflow and the standard library. Tasks import the heavy code inside the function.
- Reason: the scheduler parses the file often. A test checks that DuckDB, `fhir.resources` and the Azure SDK are not imported at parse time.

## 10. Azure: emulator and Bicep only
- Choice: the Blob SDK talks to Azurite. Bicep describes the target. CI compiles and lints it. Nothing is deployed.
- `az bicep lint` exits 0 even when it prints warnings. `scripts/bicep_check.sh` also runs the Bicep CLI and fails on any output.

## 11. Azurite flag
- Choice: Azurite starts with `--skipApiVersionCheck`.
- Reason: the Azure SDK can use a newer REST API version than the emulator knows.
- In CI, Azurite starts with a `docker run` step, because a service container cannot pass this flag.

## 12. `int_index_stays` reads a mart
- Choice: the intermediate model `int_index_stays` reads `fct_encounters`, which is a mart. Layer purists would avoid this.
- Reason: `fct_encounters` is the deduplicated, incremental fact table. The lineage image shows the back edge.
- Cost: a full rebuild of the intermediate layer depends on the fact table. The model could move to the marts folder.

## 13. k-anonymity at publish, small cells in one mart
- Choice: `publish` writes `dim_patient` through a k-anonymity step (k from `FHIR_K_ANON`, default 5) on birth year, state and gender. Steps: birth year to decade, state to census region, then drop the rows still in a group under k.
- Choice: only `mart_condition_prevalence` gets a small-cell rule. It is the only mart with a count of patients per group (`patients_with_condition`). A row under k shows NULL for count and rate, and a `suppressed` flag.
- Not changed: `mart_encounters_weekly`, `mart_los` and `mart_readmissions_30d` count encounters or stays, not patients. A patient can have many encounters in one cell, so the encounter count does not map to a patient count. They keep their exact values.
- Cost: a generalized `birth_year` column is text in the curated file. The dbt table in the warehouse stays unchanged. Dropped rows leave the curated file only.
- Limit: k-anonymity lowers the risk of re-identification. It does not remove it. It is not a compliance claim.
