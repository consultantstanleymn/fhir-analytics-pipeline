"""Airflow tests. They run Airflow in a subprocess with its own AIRFLOW_HOME."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest
from generator.generate_fhir import generate

pytestmark = pytest.mark.airflow
REPO = Path(__file__).resolve().parents[1]

DAGBAG_SCRIPT = """
import json, sys, time
t = time.perf_counter()
from airflow.dag_processing.dagbag import DagBag
bag = DagBag(dag_folder=sys.argv[1])
elapsed = time.perf_counter() - t
heavy = [m for m in ("duckdb", "fhir.resources", "azure.storage.blob", "fhir_pipeline.pipeline")
         if m in sys.modules]
print("RESULT=" + json.dumps({
    "errors": {k: v[:200] for k, v in bag.import_errors.items()},
    "dags": sorted(bag.dags),
    "tasks": sorted(t for d in bag.dags.values() for t in d.task_ids),
    "heavy_modules_loaded": heavy,
}))
"""


def _airflow_env(home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "AIRFLOW_HOME": str(home),
        "AIRFLOW__CORE__LOAD_EXAMPLES": "False",
        "AIRFLOW__CORE__DAGS_FOLDER": str(REPO / "dags"),
    }


def test_dagbag_has_no_import_errors_and_no_heavy_top_level_imports(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-c", DAGBAG_SCRIPT, str(REPO / "dags")],
        env=_airflow_env(tmp_path), capture_output=True, text=True, check=True,
    )
    line = next(x for x in proc.stdout.splitlines() if x.startswith("RESULT="))
    result = json.loads(line.removeprefix("RESULT="))
    assert result["errors"] == {}
    assert result["dags"] == ["fhir_daily"]
    assert "list_new_blobs" in result["tasks"]
    assert "dbt_build_task" in result["tasks"] and "publish_task" in result["tasks"]
    assert result["heavy_modules_loaded"] == []


@pytest.mark.azurite
def test_dag_end_to_end_1000_patients(azurite_conn, dbt_bin, tmp_path):
    env = {**os.environ, "AZURE_STORAGE_CONNECTION_STRING": azurite_conn, "DBT_BIN": dbt_bin,
           "FHIR_HMAC_KEY": "e2e-key-not-a-secret"}
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run_dag_test.py"), "--patients", "1000",
         "--run-date", "2026-02-02", "--workdir", str(tmp_path)],
        env=env, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    line = next(x for x in proc.stdout.splitlines() if x.startswith("REPORT_JSON="))
    report = json.loads(line.removeprefix("REPORT_JSON="))
    summary = report["summary"]

    expected = generate(1000, 42).counts
    for rtype, count in expected.items():
        res = summary["resources"][rtype]
        assert res["rows_in"] == count
        assert res["loaded"] + res["quarantined"] == count
        assert res["quarantined"] > 0  # the edge cases were injected on purpose
    assert summary["quarantine_total"] == sum(r["quarantined"] for r in summary["resources"].values())
    assert summary["dbt"].get("error", 0) == 0 and summary["dbt"].get("fail", 0) == 0
    assert summary["mart_rows"]["dim_patient"] == 1000

    names = {Path(b).name for b in report["curated_blobs"]}
    assert names == {
        "fct_encounters.parquet", "dim_patient.parquet", "dim_department.parquet",
        "mart_readmissions_30d.parquet", "mart_los.parquet", "mart_encounters_weekly.parquet",
        "mart_condition_prevalence.parquet", "provenance.json", "run_summary.json"}

    # The published Parquet files are real and match the warehouse.
    from fhir_pipeline.blob import CURATED, BlobStore

    store = BlobStore(azurite_conn)
    parquet = tmp_path / "fct.parquet"
    parquet.write_bytes(store.download_bytes(CURATED, "2026-02-02/fct_encounters.parquet"))
    con = duckdb.connect()
    n_parquet = con.execute(f"select count(*) from read_parquet('{parquet}')").fetchone()
    wh = duckdb.connect(str(tmp_path / "warehouse.duckdb"), read_only=True)
    n_wh = wh.execute("select count(*) from marts.fct_encounters").fetchone()
    assert n_parquet == n_wh
    assert n_wh[0] == summary["mart_rows"]["fct_encounters"]

    # The provenance manifest is valid and its input hashes match the landing blobs.
    import hashlib

    import jsonschema

    from fhir_pipeline import provenance

    manifest = json.loads(store.download_bytes(CURATED, "2026-02-02/provenance.json"))
    jsonschema.validate(manifest, provenance.load_schema())
    assert manifest == report["provenance"]
    assert len(manifest["inputs"]) == 4
    for item in manifest["inputs"]:
        landing = store.download_bytes("landing", item["blob"])
        assert hashlib.sha256(landing).hexdigest() == item["sha256"]
    assert manifest["row_counts"]["marts"]["dim_patient"] == 1000
    patients = summary["resources"]["Patient"]
    assert manifest["row_counts"]["raw"]["raw_patient"] == patients["loaded"]
    assert summary["provenance"] == "2026-02-02/provenance.json"

    # The metrics textfile has the pipeline series for this run.
    prom = Path(os.environ["FHIR_METRICS_FILE"]).read_text()
    assert 'fhir_task_duration_seconds{task="dbt_build"}' in prom
    assert 'fhir_task_duration_seconds{task="publish"}' in prom
    assert 'fhir_rows_total{layer="raw",resource="Patient"}' in prom
    assert "fhir_run_success 1.0" in prom
    assert "fhir_marts_published_timestamp_seconds 1." in prom

    # No direct identifier reached the warehouse.
    leaked = wh.execute(
        "select count(*) from raw.raw_patient where resource::varchar ilike '%Example Street%' "
        "or resource::varchar ilike '%family%'").fetchone()
    assert leaked == (0,)
