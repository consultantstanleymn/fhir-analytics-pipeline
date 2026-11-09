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
