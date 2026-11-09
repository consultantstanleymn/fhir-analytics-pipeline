"""dbt contracts on marts, source freshness and the quarantine-rate gate."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fhir_pipeline import pipeline

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.dbt
def test_contract_break_fails(env: Path, dbt_bin: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A wrong column type in a mart contract must fail the build with a contract error."""
    monkeypatch.setenv("DBT_BIN", dbt_bin)
    pipeline.ingest_dir(FIX / "readmission", "2026-01-01")
    project = env / "dbt_copy"
    shutil.copytree(
        pipeline.REPO_ROOT / "dbt" / "fhir_analytics",
        project,
        ignore=shutil.ignore_patterns("target", "logs", "dbt_packages"),
    )
    schema = project / "models" / "marts" / "schema.yml"
    text = schema.read_text()
    # dim_department.department_name is varchar. Declare it integer to break the contract.
    broken = text.replace(
        "      - name: department_name\n        data_type: varchar",
        "      - name: department_name\n        data_type: integer",
        1,
    )
    assert broken != text
    schema.write_text(broken)
    proc = pipeline.run_dbt(["build", "--select", "+dim_department"], project=project)
    assert proc.returncode != 0
    assert "contract" in (proc.stdout + proc.stderr).lower()


@pytest.mark.dbt
def test_contract_holds_on_fixture(env: Path, dbt_bin: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBT_BIN", dbt_bin)
    pipeline.ingest_dir(FIX / "readmission", "2026-01-01")
    result = pipeline.dbt_build()
    assert result["dbt_nodes"].get("error", 0) == 0


def test_gate_passes_under_limit() -> None:
    loads = [{"rows_in": 100, "rows_quarantined": 3}, {"rows_in": 100, "rows_quarantined": 1}]
    res = pipeline.check_quarantine_rate(loads, 0.05)
    assert res["ok"] is True
    assert res["rows_in"] == 200 and res["quarantined"] == 4
    assert res["share"] == 0.02


def test_gate_raises_over_limit() -> None:
    loads = [{"rows_in": 100, "rows_quarantined": 6}]
    with pytest.raises(pipeline.QuarantineGateError, match="above the limit"):
        pipeline.check_quarantine_rate(loads, 0.05)


def test_gate_at_exact_limit_passes_and_empty_input_passes() -> None:
    assert pipeline.check_quarantine_rate([{"rows_in": 100, "rows_quarantined": 5}], 0.05)["ok"]
    assert pipeline.check_quarantine_rate([], 0.05)["share"] == 0.0
    assert pipeline.check_quarantine_rate([{"skipped": True}], 0.05)["ok"]


def test_gate_uses_env_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    loads = [{"rows_in": 100, "rows_quarantined": 10}]
    monkeypatch.setenv("FHIR_MAX_QUARANTINE_SHARE", "0.2")
    assert pipeline.check_quarantine_rate(loads)["max_share"] == 0.2
    monkeypatch.setenv("FHIR_MAX_QUARANTINE_SHARE", "0.01")
    with pytest.raises(pipeline.QuarantineGateError):
        pipeline.check_quarantine_rate(loads)


def test_gate_default_limit_is_five_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FHIR_MAX_QUARANTINE_SHARE", raising=False)
    assert pipeline.check_quarantine_rate([{"rows_in": 100, "rows_quarantined": 1}])["max_share"] == 0.05


GATE_SCRIPT = """
import json, sys
from airflow.dag_processing.dagbag import DagBag
dag = DagBag(dag_folder=sys.argv[1]).dags["fhir_daily"]
print("RESULT=" + json.dumps({
    "dbt_upstream": sorted(dag.get_task("dbt_build_task").upstream_task_ids),
    "tasks": sorted(dag.task_ids),
}))
"""


@pytest.mark.airflow
def test_dag_has_gate_task_before_dbt(tmp_path: Path) -> None:
    import json
    import os
    import subprocess
    import sys

    dags = str(pipeline.REPO_ROOT / "dags")
    env = {**os.environ, "AIRFLOW_HOME": str(tmp_path), "AIRFLOW__CORE__LOAD_EXAMPLES": "False",
           "AIRFLOW__CORE__DAGS_FOLDER": dags}
    proc = subprocess.run([sys.executable, "-c", GATE_SCRIPT, dags], env=env,
                          capture_output=True, text=True, check=True)
    line = next(x for x in proc.stdout.splitlines() if x.startswith("RESULT="))
    result = json.loads(line.removeprefix("RESULT="))
    assert "quarantine_gate" in result["dbt_upstream"]
    assert "source_freshness" in result["tasks"]


@pytest.mark.dbt
def test_source_freshness_runs(env: Path, dbt_bin: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBT_BIN", dbt_bin)
    pipeline.ingest_dir(FIX / "readmission", "2026-01-01")
    res = pipeline.dbt_source_freshness()
    assert set(res["sources"]) == {"raw_patient", "raw_encounter", "raw_condition", "raw_observation"}
    # The readmission fixture loads Patient and Encounter only. Loaded tables are fresh.
    assert res["sources"]["raw_patient"] == "pass"
    assert res["sources"]["raw_encounter"] == "pass"
    # An empty source table has no load time, so dbt reports it as an error.
    assert res["sources"]["raw_condition"] == "error"
    assert res["ok"] is False


def _load_bad_day(run_date: str) -> list[dict[str, object]]:
    """Load one resource type where 10 of 20 lines are bad. Return the load stats."""
    rows = []
    for i in range(10):
        rows.append(
            f'{{"resourceType":"Patient","id":"p{i}","gender":"female","birthDate":"1980-01-01",'
            '"meta":{"lastUpdated":"2026-01-01T00:00:00Z"}}'
        )
    rows += [f"{{broken line {i}" for i in range(10)]
    stats = pipeline.validate_text(run_date, "Patient", "\n".join(rows) + "\n")
    blob = f"landing/{run_date}/Patient.ndjson"
    load = pipeline.load_blob_as(run_date, "Patient", stats["rows_in"], blob)
    return [{**stats, **load}]


def test_gate_holds_on_rerun_after_trip(env: Path) -> None:
    """A re-run loads 0 rows. The gate must still count the stored rows and stay tripped."""
    first = _load_bad_day("2026-02-01")
    with pytest.raises(pipeline.QuarantineGateError):
        pipeline.check_quarantine_rate(first, 0.05, run_date="2026-02-01")
    rerun = [{"rows_in": 0, "rows_loaded": 0, "rows_quarantined": 0, "skipped": 1}]
    with pytest.raises(pipeline.QuarantineGateError, match="above the limit"):
        pipeline.check_quarantine_rate(rerun, 0.05, run_date="2026-02-01")


def test_gate_hold_clears_when_cause_is_resolved_or_released(env: Path) -> None:
    first = _load_bad_day("2026-02-02")
    rerun = [{"skipped": 1}]
    with pytest.raises(pipeline.QuarantineGateError):
        pipeline.check_quarantine_rate(first, 0.05, run_date="2026-02-02")
    # Cause resolved: the limit is raised on purpose, the stored share is under it.
    assert pipeline.check_quarantine_rate(rerun, 0.6, run_date="2026-02-02")["ok"]
    # Explicit release: the set is accepted, the gate then passes at the old limit.
    with pytest.raises(pipeline.QuarantineGateError):
        pipeline.check_quarantine_rate(rerun, 0.05, run_date="2026-02-02")
    assert pipeline.release_quarantine_hold("2026-02-02") is True
    assert pipeline.check_quarantine_rate(rerun, 0.05, run_date="2026-02-02")["ok"]
    # Another day is not affected.
    assert pipeline.check_quarantine_rate(rerun, 0.05, run_date="2026-02-03")["ok"]
