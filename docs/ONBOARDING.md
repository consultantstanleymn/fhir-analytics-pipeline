# Onboarding

Goal: run the full pipeline on your machine in about 15 minutes.

## You need
- Linux or macOS, Python 3.12, `git`.
- `podman` (or Docker) to run the Azurite emulator.
- About 2 GB of free disk space for the two virtual environments.
- Optional: Azure CLI (`az`), only to check the Bicep files.

## Steps
1. Clone the repository and enter it.
2. Create the app environment. It holds Airflow 3.4.0 with the official constraints file.
   ```bash
   python3.12 -m venv .venv
   .venv/bin/pip install -r requirements/base.txt -c requirements/airflow-constraints.txt
   .venv/bin/pip install -e . --no-deps
   ```
3. Create the dbt environment. It is separate on purpose (see `docs/DECISIONS.md`, entry 2).
   ```bash
   python3.12 -m venv .venv-dbt
   .venv-dbt/bin/pip install -r requirements/dbt.txt
   ```
4. Start Azurite.
   ```bash
   eval "$(scripts/azurite.sh start)"
   ```
5. Set the other variables.
   ```bash
   export DBT_BIN=$PWD/.venv-dbt/bin/dbt
   export FHIR_HMAC_KEY=local-demo-key-not-a-secret
   ```
6. Run the whole pipeline for 1,000 synthetic patients.
   ```bash
   .venv/bin/python scripts/run_dag_test.py --patients 1000 --workdir .work/demo
   ```
7. Look at the result.
   ```bash
   .venv/bin/python - <<'PY'
   import duckdb
   con = duckdb.connect(".work/demo/warehouse.duckdb", read_only=True)
   print(con.execute("select * from marts.mart_readmissions_30d order by 1").fetchall())
   PY
   ```
8. Stop Azurite: `scripts/azurite.sh stop`.

## Run the tests
```bash
export AZURITE_CONNECTION_STRING=...   # optional; without it the tests start their own podman container
.venv/bin/pytest -q                    # all tests
.venv/bin/pytest -m "not airflow and not dbt and not bicep"   # the CI unit job
.venv/bin/ruff check . && .venv/bin/mypy
cd dbt/fhir_analytics && DUCKDB_PATH=/tmp/x.duckdb ../../.venv-dbt/bin/sqlfluff lint models tests
scripts/bicep_check.sh                 # needs az
```

## Read the code in this order
1. `generator/generate_fhir.py`: how the fake data and its defects are made.
2. `src/fhir_pipeline/validate.py` and `pseudonymize.py`: the two gates before the warehouse.
3. `src/fhir_pipeline/warehouse.py`: the raw tables and the load log.
4. `dbt/fhir_analytics/models/`: staging, intermediate, marts. Then `schema.yml` files for the tests.
5. `dags/fhir_daily.py` and `src/fhir_pipeline/pipeline.py`: the orchestration.
6. `infra/main.bicep` and `tests/test_bicep_policy.py`: the Azure target and its policy checks.
7. `LEARN.md`: plain-language explanation and interview notes.
