# Runbook

How to operate the pipeline on one machine. All commands run from the repository root.

## Environment variables
| Name | Meaning |
|---|---|
| `FHIR_HMAC_KEY` | Key for pseudonymization tokens. Required. |
| `AZURE_STORAGE_CONNECTION_STRING` | Blob endpoint. Locally this is Azurite. |
| `DUCKDB_PATH` | Warehouse file. Required. |
| `FHIR_WORK_DIR` | Local scratch folder for validated files. Default `.work/run`. |
| `DBT_BIN` | Path to the dbt executable in `.venv-dbt`. |
| `AIRFLOW_HOME` | Airflow metadata folder. Use a project-local path. |

## Start and stop Azurite
```bash
eval "$(scripts/azurite.sh start)"   # random free port, prints the export line
scripts/azurite.sh stop              # removes the container by its exact name
```

## Run one day end to end
```bash
python -m generator.generate_fhir --patients 1000 --out .work/gen
python scripts/run_dag_test.py --patients 1000 --run-date 2026-11-07 --workdir .work/e2e
```
The script generates data, uploads it to `landing/2026-11-07/`, runs the DAG with `dag.test()`, and prints a JSON report.

## Symptoms and fixes

### The run fails in a validate task
- Look at `quarantine` first. It holds rejected lines with a reason.
  ```sql
  select resource_type, reason, count(*) from raw.quarantine group by all order by 3 desc;
  ```
- A high count of one reason points to a producer problem. Fix the source, then upload a new file.

### `dbt build` fails
- The DAG error shows the last 30 lines. For full detail run dbt by hand:
  ```bash
  cd dbt/fhir_analytics && DUCKDB_PATH=../../.work/e2e/warehouse.duckdb ../../.venv-dbt/bin/dbt build --profiles-dir .
  ```
- Read a single failure with `dbt show --inline "select ..."` or open `target/run_results.json`.
- A failing `relationships` test usually means a parent resource was quarantined.

### `IOException: Could not set lock on file`
- DuckDB allows one writer. Another process holds the file. Find it with `fuser <file>`. Stop that process. Do not run two pipelines on one file.

### Azure SDK error: API version not supported
- Azurite must run with `--skipApiVersionCheck`. `scripts/azurite.sh` does this.

### Load the same day again
- The load log skips a blob that was loaded. To reload on purpose, delete its row from `raw.load_log` and its rows from the raw tables (match on `_source_blob`). Then run the DAG.

### Rebuild the incremental table from scratch
```bash
cd dbt/fhir_analytics && DUCKDB_PATH=... ../../.venv-dbt/bin/dbt build --full-refresh --profiles-dir .
```

## Where results go
- Warehouse: `$DUCKDB_PATH`, schemas `raw`, `staging`, `intermediate`, `marts`.
- Parquet marts and `run_summary.json`: container `curated`, folder `{run_date}/`.
