"""dbt checks on hand-written fixtures. Runs the real loader, then the real dbt project."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from fhir_pipeline import pipeline

pytestmark = pytest.mark.dbt
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def dbt(env: Path, dbt_bin: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DBT_BIN", dbt_bin)
    return pipeline


def _query(env: Path, sql: str):
    con = duckdb.connect(str(env / "wh.duckdb"), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_dbt_build_passes_and_readmission_fixture_matches(env, dbt):
    report = dbt.ingest_dir(FIX / "readmission", "2026-01-01")
    assert report["Encounter"]["valid"] == 12
    result = dbt.dbt_build()
    assert result["dbt_nodes"].get("error", 0) == 0
    assert result["dbt_nodes"].get("fail", 0) == 0
    rows = _query(env, "select department, index_stays, readmissions, readmission_rate "
                       "from marts.mart_readmissions_30d order by department")
    # Hand-computed: 9 index stays and 3 readmissions (E1, E5 at exactly 30 days, E7).
    assert rows == [("ALL", 9, 3, round(3 / 9, 4)),
                    ("Cardiology", 5, 2, 0.4),
                    ("Oncology", 4, 1, 0.25)]


def test_incremental_rerun_and_update_batch(env, dbt):
    dbt.ingest_dir(FIX / "readmission", "2026-01-01")
    dbt.dbt_build()
    before = dict(_query(env, "select encounter_id, cast(dbt_loaded_at as varchar) from marts.fct_encounters"))
    assert len(before) == 12

    # Run twice on the same data: nothing changes.
    dbt.dbt_build()
    again = dict(_query(env, "select encounter_id, cast(dbt_loaded_at as varchar) from marts.fct_encounters"))
    assert again == before

    # Loading the same files again is skipped by the load log.
    skipped = dbt.ingest_dir(FIX / "readmission", "2026-01-01")
    assert skipped["Encounter"]["load"]["skipped"] == 1

    # New batch: E2 changes department, E13 is new. Only those two rows may change.
    dbt.ingest_dir(FIX / "readmission_update", "2026-01-02")
    dbt.dbt_build()
    after = dict(_query(env, "select encounter_id, cast(dbt_loaded_at as varchar) from marts.fct_encounters"))
    assert len(after) == 13
    changed = {k for k in after if before.get(k) != after[k]}
    assert changed == {"E2", "E13"}
    dept = _query(env, "select department from marts.fct_encounters where encounter_id = 'E2'")
    assert dept == [("Neurology",)]
    index_rows = _query(env, "select index_stays from marts.mart_readmissions_30d "
                             "where department = 'ALL'")
    assert index_rows == [(10,)]  # E13 is a tenth index stay


def test_dbt_docs_generate(env, dbt):
    dbt.ingest_dir(FIX / "readmission", "2026-01-01")
    proc = dbt.run_dbt(["docs", "generate"])
    assert proc.returncode == 0, proc.stdout[-500:]
    target = pipeline.REPO_ROOT / "dbt" / "fhir_analytics" / "target"
    assert (target / "catalog.json").exists()
    assert (target / "manifest.json").exists()
