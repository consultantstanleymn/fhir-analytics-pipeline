# fhir-analytics-pipeline

A batch analytics pipeline for clinical data in HL7 FHIR R4 format. All data is synthetic.

Airflow runs a daily DAG. It reads FHIR bulk-export files (NDJSON) from Azure Blob Storage (the Azurite emulator), validates each record, pseudonymizes patient identifiers, loads raw tables into DuckDB, runs dbt models and tests, and publishes curated Parquet marts back to Blob Storage. The target Azure resources are described in Bicep, which CI compiles and lints.

The marts answer four operations questions: encounters per department per week, 30-day readmission rate, length of stay, and condition prevalence.

```mermaid
flowchart LR
    G[generator<br/>seeded synthetic FHIR R4] -->|NDJSON per type| L[(Blob: landing/date/)]
    L --> V[validate<br/>fhir.resources + bindings + rules]
    V -->|bad lines + reason| Q[(raw.quarantine)]
    V --> P[pseudonymize<br/>HMAC-SHA256, drop names and addresses]
    P --> R[(DuckDB raw_* tables<br/>_loaded_at, _source_blob)]
    R --> D[dbt: stg, int, marts<br/>41 data tests + 2 unit tests]
    D --> X[export Parquet]
    X --> C[(Blob: curated/date/<br/>marts + run_summary.json)]
    B[infra/main.bicep<br/>storage, Key Vault, identity] -.compiled and linted in CI, not deployed.-> C
```

dbt lineage (generated from `manifest.json` by `scripts/lineage_svg.py`):

![dbt lineage](docs/img/lineage.png)

## Verified locally

Each line ran on one laptop on 2026-11-09. Raw output is in `docs/engagement/evidence/`. No GitHub Actions run was started or checked for the new work.

| Claim | Command | Evidence file |
|---|---|---|
| Baseline: lint, types, unit, Azurite, dbt and Airflow tests pass before the engagement work | see the file | `docs/engagement/evidence/baseline-local.txt` |
| dbt contracts on all marts, with a test that a contract break fails the build; source freshness checks; a quarantine-rate gate that stops a run over 5 percent | `.venv/bin/python -m pytest tests/test_contracts_gate.py -v` | `docs/engagement/evidence/contracts-gate.txt` |
| A provenance manifest for every run (input hashes, code SHA, dbt manifest hash, row counts), checked against a JSON schema | `.venv/bin/python -m pytest tests/test_provenance.py -v` | `docs/engagement/evidence/provenance-manifest-sample.txt` and `.json` |
| k-anonymity (k=5) at publish: no group under k reaches the curated Parquet file | `.venv/bin/python -m pytest tests/test_kanon.py -q` | `docs/engagement/evidence/kanon-report.txt` |
| Versioned HMAC keys: a key id in each token, old files readable after a rotation | `.venv/bin/python -m pytest tests/test_key_versions.py -v` | `docs/engagement/evidence/key-versions.txt` |
| Late-update fix: an update with an old `lastUpdated` is applied, nothing else changes, a re-run is idempotent | `.venv/bin/python -m pytest -m dbt -v` | `docs/engagement/evidence/dbt-tests.txt` and `docs/DECISIONS.md` entry 6 |
| Pipeline metrics and a 06:00 freshness alert, with rule tests that promtool ran | `podman run ... promtool test rules` (see the file) | `docs/engagement/evidence/promtool-freshness.txt` |
| Failure lab: corrupt blob, schema drift (new and removed field), late update, Azurite down | `.venv/bin/python scripts/failure_lab.py --all` | `docs/engagement/evidence/failure-lab.txt` |
| bandit, semgrep, pip-audit, gitleaks and an SBOM pass | commands in `docs/engagement/SECURITY-GATE.md` | `docs/engagement/evidence/security-gate-local.txt` |

## Authored, not run

| File | What it would do | Why it did not run |
|---|---|---|
| `.github/workflows/security.yml` and the CodeQL job | Run the security checks on GitHub | Authored, not run: this file is written and syntax-checked with `actionlint 1.7.12`. It was not executed against GitHub Actions. Reason: needs GitHub Actions. |
| New jobs in `.github/workflows/ci.yml` (promtool, dashboard and map checks) | Run the same checks in CI | Authored, not run: this file is written and syntax-checked with `actionlint 1.7.12`. It was not executed against GitHub Actions. Reason: needs GitHub Actions. |
| `observability/grafana/fhir-pipeline.json` | Show the five pipeline panels in Grafana | Authored, not run: this file is written and checked with `tools/check_dashboard.py`. It was not loaded into Grafana. Reason: tool not installed. |
| Alert routing for `FhirMartsLate` and `FhirMartsSloBreach` | Page or ticket on a late run | Authored, not run: the severity labels are written. No Alertmanager was set up. Reason: no cloud account by design. |
| Key Vault reads for the HMAC keys (Bicep only) | Give the pipeline its keys from a vault | Authored, not run: `infra/main.bicep` is compiled and linted. It was not deployed. Reason: no cloud account by design. |

## What this is not

- The data is synthetic, from my own generator. It is not Synthea output and not real patient data.
- It handles four FHIR resource types only: Patient, Encounter, Condition, Observation. There is no FHIR server, no SMART on FHIR, no HL7 v2 and no EHR vendor integration.
- Pseudonymization is a design demo. The project does not claim HIPAA compliance. See `SECURITY.md`.
- DuckDB stands in for a cloud warehouse. There is no Snowflake, BigQuery or Databricks.
- Azure is used only through the Blob Storage SDK against the Azurite emulator, and through Bicep that is compiled and linted. Nothing is deployed to an Azure subscription. No Data Factory, Synapse, AKS or other Azure service is used.
- Airflow runs on a single machine. Tests use `dag.test()`. A scheduler and web server were not run for this project.
- Validation uses the R4B models of `fhir.resources` (FHIR 4.3.0) plus a short table of required code bindings. It does not use profiles such as US Core and does not check terminology servers.
- The incremental model skips an update that is older than the newest row already loaded (see `docs/DECISIONS.md`, entry 6).

## Results (real, recorded 2026-11-07 on one laptop)

| Check | Result |
|---|---|
| pytest (all) | 41 passed in 158 s |
| dbt build on 1,000 patients | 56 nodes: 13 models, 41 data tests, 2 unit tests, all pass |
| Hand-written readmission fixture | 9 index stays, 3 readmissions, matches `mart_readmissions_30d` exactly |
| Incremental model | second run on the same data changes no row; an update batch changes only the 2 touched rows |
| DAG end to end, 1,000 patients (6,038 resources) | 98.9 s, 51 quarantined, all marts published |
| DAG end to end, 10,000 patients (60,413 resources) | 130.1 s, dbt 4.5 s, 501 quarantined (`docs/PERF.md`) |
| Bicep | build and lint with 0 warnings, ARM policy test passes |
| ruff, mypy (strict), sqlfluff | clean |

CI status: the workflow in `.github/workflows/ci.yml` has five jobs (`lint`, `unit`, `dbt`, `airflow-e2e`, `bicep`). It has not run on GitHub yet, because the repository has not been pushed. I ran the same commands for each job locally. Do not treat the project as CI-verified until the jobs are green on `main`.

## Quick start

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements/base.txt -c requirements/airflow-constraints.txt && .venv/bin/pip install -e . --no-deps
python3.12 -m venv .venv-dbt && .venv-dbt/bin/pip install -r requirements/dbt.txt
eval "$(scripts/azurite.sh start)"
export DBT_BIN=$PWD/.venv-dbt/bin/dbt FHIR_HMAC_KEY=local-demo-key-not-a-secret
.venv/bin/python scripts/run_dag_test.py --patients 1000 --workdir .work/demo
.venv/bin/pytest -q
scripts/azurite.sh stop
```

Details: `docs/ONBOARDING.md`.

## Layout

| Path | Content |
|---|---|
| `generator/` | Seeded synthetic FHIR generator with deliberate defects |
| `src/fhir_pipeline/` | Validator, pseudonymizer, Blob client, DuckDB loader, pipeline steps |
| `dags/fhir_daily.py` | The Airflow DAG |
| `dbt/fhir_analytics/` | dbt project: staging, intermediate, marts, tests, unit tests |
| `infra/` | Bicep template and parameter files (compiled and linted only) |
| `tests/` | pytest suites and hand-written fixtures |
| `scripts/` | Azurite helper, end-to-end runner, Bicep check, lineage drawing |
| `docs/` | `ONBOARDING.md`, `RUNBOOK.md`, `DEMO.md`, `DECISIONS.md`, `PERF.md` |
| `LEARN.md` | Plain-language guide and interview notes |

## Data quality gates

1. Per line: JSON parse, FHIR model, required code bindings, business rules. Rejects go to `raw.quarantine` with a reason.
2. Before load: pseudonymization. A test asserts that no name or address field survives.
3. In dbt: `unique`, `not_null`, `relationships`, `accepted_values`, two singular tests, and two unit tests with hand-computed answers. A failing test stops the run.

## License

MIT. Copyright Stanley Sujith Nelavala.
