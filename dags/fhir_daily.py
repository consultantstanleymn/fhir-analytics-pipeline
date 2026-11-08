"""Airflow DAG `fhir_daily`.

landing/{run_date}/*.ndjson -> validate + pseudonymize -> raw DuckDB tables ->
dbt build -> Parquet marts in curated/{run_date}/ plus a run summary.

The file only imports Airflow and the standard library at the top. All heavy work lives in
`fhir_pipeline.pipeline` and is imported inside the tasks, so parsing this file is fast.

Resource groups run one after the other because DuckDB allows one writer at a time.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from airflow.sdk import DAG, Param, TaskGroup, task

RESOURCE_ORDER = ("Patient", "Encounter", "Condition", "Observation")


def _run_date(params: dict[str, Any]) -> str:
    return str(params.get("run_date") or date.today().isoformat())


with DAG(
    dag_id="fhir_daily",
    description="FHIR R4 bulk export to validated, pseudonymized, modeled marts",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    params={"run_date": Param(None, type=["null", "string"], description="YYYY-MM-DD folder")},
    tags=["fhir", "analytics"],
) as dag:

    @task
    def list_new_blobs(params: dict[str, Any]) -> dict[str, str]:
        from fhir_pipeline.blob import BlobStore
        from fhir_pipeline.pipeline import list_new_blobs as _list

        return _list(BlobStore(), _run_date(params))

    listing = list_new_blobs()

    def resource_group(rtype: str) -> Any:
        with TaskGroup(group_id=rtype.lower()) as group:

            @task(task_id="validate")
            def validate(found: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
                from fhir_pipeline.blob import BlobStore
                from fhir_pipeline.pipeline import validate_blob

                if rtype not in found:
                    return {"resource_type": rtype, "rows_in": 0, "valid": 0, "rejected": 0,
                            "skipped": True}
                return validate_blob(BlobStore(), _run_date(params), rtype)

            @task(task_id="load")
            def load(stats: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
                from fhir_pipeline.pipeline import load_blob

                if stats.get("skipped"):
                    return stats
                return {**stats, **load_blob(_run_date(params), rtype, stats["rows_in"])}

            result = load(validate(listing))
        group.result = result  # type: ignore[attr-defined]
        return group

    groups = [resource_group(r) for r in RESOURCE_ORDER]
    for first, second in zip(groups, groups[1:], strict=False):
        first >> second

    @task
    def dbt_build_task(loads: list[dict[str, Any]]) -> dict[str, Any]:
        from fhir_pipeline.pipeline import dbt_build

        return dbt_build()

    @task
    def publish_task(
        loads: list[dict[str, Any]], dbt_result: dict[str, Any], params: dict[str, Any]
    ) -> dict[str, Any]:
        from fhir_pipeline.blob import BlobStore
        from fhir_pipeline.pipeline import publish, quarantine_count, table_count

        summary = {
            "run_date": _run_date(params),
            "resources": {
                x["resource_type"]: {
                    "rows_in": x["rows_in"],
                    "loaded": x.get("rows_loaded", 0),
                    "quarantined": x.get("rows_quarantined", 0),
                }
                for x in loads
            },
            "quarantine_total": quarantine_count(),
            "dbt": dbt_result["dbt_nodes"],
            "mart_rows": {
                m: table_count(f"marts.{m}")
                for m in ("fct_encounters", "dim_patient", "mart_readmissions_30d", "mart_los")
            },
        }
        summary["published"] = publish(BlobStore(), summary["run_date"], summary)  # type: ignore[assignment]
        return summary

    load_results = [g.result for g in groups]  # type: ignore[attr-defined]
    built = dbt_build_task(load_results)
    publish_task(load_results, built)
