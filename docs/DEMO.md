# Demo

Everything below is real output from one run on 2026-11-07 on the build laptop. Data is synthetic. Seed 42, 1,000 patients, run date `2026-11-07`. Tokens and numbers will match if you use the same seed and code; times will differ.

## 1. Start the emulator and run the pipeline

```bash
eval "$(scripts/azurite.sh start)"
export DBT_BIN=$PWD/.venv-dbt/bin/dbt FHIR_HMAC_KEY=local-demo-key-not-a-secret
.venv/bin/python scripts/run_dag_test.py --patients 1000 --run-date 2026-11-07 --workdir .work/demo
```

The script prints one JSON report (curated blob folder shown by file name):

```json
{
  "patients": 1000,
  "resources_generated": 6038,
  "generate_seconds": 1.3,
  "upload_seconds": 0.3,
  "dag_seconds": 98.9,
  "dbt_build_seconds": 8.3,
  "curated_blobs": [
    "dim_department.parquet",
    "dim_patient.parquet",
    "fct_encounters.parquet",
    "mart_condition_prevalence.parquet",
    "mart_encounters_weekly.parquet",
    "mart_los.parquet",
    "mart_readmissions_30d.parquet",
    "run_summary.json"
  ]
}
```

Run summary written to `curated/2026-11-07/run_summary.json`:

```json
{
  "run_date": "2026-11-07",
  "resources": {
    "Patient": {
      "rows_in": 1030,
      "loaded": 1020,
      "quarantined": 10
    },
    "Encounter": {
      "rows_in": 1300,
      "loaded": 1280,
      "quarantined": 20
    },
    "Condition": {
      "rows_in": 1224,
      "loaded": 1214,
      "quarantined": 10
    },
    "Observation": {
      "rows_in": 2484,
      "loaded": 2473,
      "quarantined": 11
    }
  },
  "quarantine_total": 51,
  "dbt": {
    "success": 13,
    "pass": 43
  },
  "mart_rows": {
    "fct_encounters": 1240,
    "dim_patient": 1000,
    "mart_readmissions_30d": 8,
    "mart_los": 7
  }
}
```

Reading the summary: for example, 1,300 Encounter lines came in. 1,280 were valid and 20 went to quarantine. dbt ran 56 nodes: 13 models and 43 tests (41 data tests and 2 unit tests). All passed.

## 2. What was quarantined, and why

```sql
select resource_type, reason, count(*) n from raw.quarantine group by all order by 1,3 desc
```
```
Condition    fhir validation: clinicalStatus: Invalid JSON: expected value at line 1 column 1            10
Encounter    business rule: missing Patient subject reference                                           10
Encounter    code binding: status 'not-a-status' is not allowed                                         10
Observation  fhir validation: valueQuantity.value: Value error, Decimal value string does not match ... 10
Observation  malformed JSON: Expecting ',' delimiter                                                     1
Patient      fhir validation: birthDate: Value error, Date value string does not match spec regex.      10
```

## 3. The marts

30-day readmission rate (department "Unknown" holds encounters with no service type, an edge case on purpose):

```
department        index_stays  readmissions  readmission_rate
ALL                       641            61            0.0952
Cardiology                101            12            0.1188
Emergency                  93             9            0.0968
General Medicine          103             9            0.0874
Oncology                  110            11            0.1
Orthopedics               100             7            0.07
Pediatrics                111             9            0.0811
Unknown                    23             4            0.1739
```

Length of stay in days (finished inpatient stays):

```
department        stays  avg_los_days  median_los_days  p90_los_days
Cardiology          107          4.96              5.0           8.0
Emergency            96          4.85              5.0           8.0
General Medicine    106          4.93              5.0           9.0
Oncology            112          5.04              5.0           9.0
Orthopedics         103          4.78              5.0           9.0
Pediatrics          115          5.06              5.0           9.0
Unknown              24          4.96              5.0           7.7
```

Condition prevalence (top 4 of 8):

```
38341003   Hypertensive disorder              160 of 1000   0.16
254837009  Malignant tumor of breast          150 of 1000   0.15
13645005   Chronic obstructive lung disease   141 of 1000   0.141
84114007   Heart failure                      136 of 1000   0.136
```

The patient dimension holds tokens, not identities:

```
patient_token (first 16 chars)  gender  birth_year  state
0072e9339d758ea2...             male    1962        IA
05a14bd90542135f...             male    1951        IL
```

## 4. The tests can fail (mutation checks)

Test 1. I changed the readmission window in `int_index_stays.sql` from `<= 30` to `<= 29` and ran the dbt fixture test. The hand-computed fixture has one stay at exactly 30 days. Result:

```
RuntimeError: dbt build failed ({'success': 11, 'pass': 35, 'fail': 1, 'skipped': 9}):
 actual differs from expected
 Done. PASS=46 WARN=0 ERROR=1 SKIP=9 NO-OP=0 REUSED=0 TOTAL=56
```

The dbt unit test `index_stays_hand_computed_fixture` failed, and nine downstream nodes were skipped. I reverted the change.

Test 2. I changed `allowBlobPublicAccess: false` to `true` in `infra/main.bicep`. Result:

```
FAILED tests/test_bicep_policy.py::test_source_policy_flags - AssertionError
FAILED tests/test_bicep_policy.py::test_compiled_arm_policy - assert True is ...
2 failed
```

I reverted the change.

## 5. Bicep check

```
$ scripts/bicep_check.sh
bicep: build OK, lint OK (0 warnings), params OK
```

Bicep CLI 0.49.2 (installed by `az` on first use). `az` is the Fedora package azure-cli 2.83.0. Nothing was deployed and `az login` was never run.

## 6. Test suite

```
$ pytest -q
41 passed in 158.35s (0:02:38)
```

By file: test_validate 17, test_pseudonymize 9, test_generator 6, test_dbt_fixture 3, test_blob 2, test_dag 2, test_bicep_policy 2.

The CI unit job selection (no Airflow, no dbt) was also run in a clean virtual environment that has only `requirements/core.txt`: `35 passed, 6 deselected`.

Other checks: `ruff check .` passes, `mypy` (strict) reports no issues in 9 source files, and `sqlfluff lint models tests` reports no violations.

## 7. Stop the emulator

```bash
scripts/azurite.sh stop
```
