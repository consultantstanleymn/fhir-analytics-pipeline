# Performance (local, recorded, not a benchmark)

Machine: MacBook Pro mid 2015, Intel Core i7-4770HQ, 8 threads, 16 GB RAM, Fedora Linux 44. Other programs ran at the same time (a browser and other builds), and the pipeline ran under `nice -n 10`. Treat the numbers as a rough order of magnitude.

Setup: Python 3.12.16, Airflow 3.4.0 (`dag.test()`, one process), dbt-core 1.12.6, dbt-duckdb 1.11.1, DuckDB 2.0.0, Azurite 3.35.0 in rootless podman. The DAG time includes Airflow task start-up for 13 tasks, so it is not just data work.

| Run | Patients | FHIR resources in files | Generate | Upload | Whole DAG (`dag.test()`) | `dbt build` | Quarantined |
|---|---|---|---|---|---|---|---|
| Routine (2026-11-07) | 1,000 | 6,038 | 1.3 s | 0.3 s | 98.9 s | 8.3 s | 51 |
| Scale (2026-11-07) | 10,000 | 60,413 | 2.5 s | 0.4 s | 130.1 s (2.2 min) | 4.5 s | 501 |

Observations:
- The 10,000-patient DAG run took 130 s. The 1,000-patient run took 99 s. Ten times the data cost about 30 percent more time, so fixed costs dominate (Airflow task start-up for 13 tasks, dbt start-up). An earlier 1,000-patient run inside the pytest suite finished faster (the whole test took well under a minute), so the 99 s figure varies with load on the shared laptop. The cause of the variation was not investigated.
- dbt took 4.5 s on 10,000 patients, so dbt on DuckDB is not the bottleneck. The 8.3 s for 1,000 patients also reflects load.
- The per-stage split inside the DAG was not measured. Only the two totals above were recorded.
- The same code is exercised in CI with 1,000 patients. CI times will differ.

How to repeat:
```bash
eval "$(scripts/azurite.sh start)"
export DBT_BIN=$PWD/.venv-dbt/bin/dbt FHIR_HMAC_KEY=local-demo-key-not-a-secret
.venv/bin/python scripts/run_dag_test.py --patients 10000 --run-date 2026-03-03 --workdir .work/perf10k
```
