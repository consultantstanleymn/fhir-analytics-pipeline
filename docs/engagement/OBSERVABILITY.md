# Observability

This file describes the pipeline metrics, the freshness objective, the alert rules and the dashboard. All data is synthetic. Time values are UTC.

## Metrics

The pipeline writes a Prometheus textfile at the end of each task and at publish. The default path is `.work/metrics/fhir_pipeline.prom`. Set `FHIR_METRICS_FILE` to change it. The code is in `src/fhir_pipeline/metrics.py`.

| Metric | Labels | Meaning |
|---|---|---|
| `fhir_task_duration_seconds` | `task` | Duration of the last run of a task |
| `fhir_rows_total` | `layer`, `resource` | Rows per layer and resource at the last publish |
| `fhir_quarantine_share` | none | Rejected share of input rows in the last run |
| `fhir_marts_published_timestamp_seconds` | none | Unix time of the last mart publish |
| `fhir_run_success` | none | 1 if the last run succeeded, 0 if a task failed |

The rules add two recorded series:

| Series | Meaning |
|---|---|
| `fhir:marts_on_time:daily` | 1 or 0 for each day, sampled between 06:00 and 06:59 |
| `fhir:marts_on_time:ratio_28d` | Share of on-time days over the last 28 days |

Label values come from fixed sets, so the number of series stays small.

| Label | Allowed values |
|---|---|
| `task` | `list_new_blobs`, `validate`, `load`, `quarantine_gate`, `source_freshness`, `dbt_build`, `publish` |
| `layer` | `raw`, `staging`, `marts` |
| `resource` | `Patient`, `Encounter`, `Condition`, `Observation`, `all` |

The maximum is 7 task series, 15 row series and 3 single series. A test checks that any other value is an error.

## How the textfile reaches Prometheus

Two options exist. Neither runs in this repo.

1. The node exporter textfile collector reads the file from a directory on the host.
2. A push step sends the file to a Pushgateway after each run.

The state of each run goes to a small JSON file next to the textfile. This lets separate Airflow task processes add to one file.

## Freshness SLO

Statement: the marts are published by 06:00 UTC on at least 96.4 percent of days, measured over 28 days.

The first goal said 99 percent of days. The arithmetic below shows why the target is now 96.4 percent.

| Window | Days allowed late at 99 percent | Result |
|---|---|---|
| 28 days | 28 x 0.01 = 0.28 | 0 late days, so one late day breaks the target |
| 90 days | 90 x 0.01 = 0.9 | 0 late days, so one late day breaks the target |
| 100 days | 100 x 0.01 = 1.0 | 1 late day |

A 28-day window with 99 percent means 27.72 on-time days are needed. Only 28 on-time days pass. So no late day is allowed. That target is too strict for a daily batch with one run each day, because a single late run would use the whole budget and also hide the signal.

Choice: 28-day window, target 96.4 percent.

- 28 days x 0.036 = 1.008. This allows 1 late day in 28.
- 27 of 28 days is 0.9643, which is above 0.964. The test shows this.
- 26 of 28 days is 0.9286, which is below the target. The alert fires.

Reason: a 28-day window is short enough to react to a change and long enough to show a trend. One late day is a warning. Two late days in a window show a real problem.

Other option: keep 99 percent and use a window of 100 days or more (1 late day allowed). That window reacts more slowly to a change, so it was not chosen.

This target is less strict than the first goal. `docs/engagement/ACCEPTANCE.md` (F-6) records both.

Measured result: none. The pipeline has no real run history, so no on-time ratio was measured. The promtool tests prove the rule logic on synthetic series only (see `docs/engagement/evidence/promtool-freshness.txt`).

## Alerts

| Alert | Fires when | Severity |
|---|---|---|
| `FhirMartsLate` | There is no publish yet today, it is 06:00 UTC or later, for 5 minutes | page |
| `FhirMartsSloBreach` | `fhir:marts_on_time:ratio_28d` is below 0.964 for 1 hour | ticket |

The rules are in `observability/rules/freshness.rules.yml`. The tests are in `observability/rules/freshness.rules.test.yml`. Time zone assumption: the pipeline host and the rules use UTC. A host in another time zone needs changes to the 06:00 hour check.

Known gap: if the metric is missing (the pipeline never ran), the rules produce no sample. A separate rule for a missing series is not built.

Alert routing is authored, not run. No Alertmanager, pager or ticket tool is set up. The `severity` label shows where each alert would go.

## Dashboard

The file `observability/grafana/fhir-pipeline.json` has five panels: last publish time, 28-day on-time ratio, quarantine share, rows per layer and task duration. The script `tools/check_dashboard.py` checks the structure and that each query names a known metric.

Authored, not run: this file is written and checked with `tools/check_dashboard.py`. It was not loaded into Grafana. Reason: no Grafana is installed here and no screenshot was taken.

## Run the checks

```
podman run --rm -v "$PWD/observability/rules:/r:ro,z" --entrypoint promtool \
  docker.io/prom/prometheus:v2.55.1 test rules /r/freshness.rules.test.yml
python3 tools/check_dashboard.py observability/grafana/fhir-pipeline.json
.venv/bin/python -m pytest tests/test_metrics.py tests/test_observability.py -q
```
