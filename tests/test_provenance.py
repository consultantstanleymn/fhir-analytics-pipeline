from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from fhir_pipeline import provenance


def _manifest(tmp_path: Path, inputs: dict[str, bytes | str] | None = None) -> dict:
    dbt = tmp_path / "manifest.json"
    dbt.write_text('{"nodes": {}}')
    return provenance.build_manifest(
        "2026-01-01",
        inputs if inputs is not None else {"2026-01-01/Patient.ndjson": b"abc"},
        "deadbeef",
        dbt,
        {"raw": {"raw_patient": 3}, "staging": {"stg_patient": 3}, "marts": {"dim_patient": 3}},
    )


def test_manifest_validates_against_schema(tmp_path: Path) -> None:
    m = _manifest(tmp_path)
    jsonschema.validate(m, provenance.load_schema())
    jsonschema.validate(json.loads(json.dumps(m)), provenance.load_schema())


def test_schema_rejects_bad_manifest(tmp_path: Path) -> None:
    m = _manifest(tmp_path)
    del m["code_sha"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, provenance.load_schema())
    m = _manifest(tmp_path)
    m["inputs"][0]["sha256"] = "not-a-hash"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(m, provenance.load_schema())


def test_input_hashes_match_content(tmp_path: Path) -> None:
    m = _manifest(tmp_path, {"b.ndjson": b"two", "a.ndjson": b"one"})
    assert [i["blob"] for i in m["inputs"]] == ["a.ndjson", "b.ndjson"]
    assert m["inputs"][0]["sha256"] == provenance.sha256_bytes(b"one")
    assert m["inputs"][1]["sha256"] == provenance.sha256_bytes(b"two")
    assert provenance.sha256_bytes(b"one") != provenance.sha256_bytes(b"two")


def test_ready_hash_is_kept(tmp_path: Path) -> None:
    h = provenance.sha256_bytes(b"x")
    assert _manifest(tmp_path, {"x": h})["inputs"][0]["sha256"] == h


def test_dbt_manifest_hash_is_file_hash(tmp_path: Path) -> None:
    m = _manifest(tmp_path)
    assert m["dbt_manifest_sha256"] == provenance.sha256_bytes((tmp_path / "manifest.json").read_bytes())


def test_missing_dbt_manifest_is_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        provenance.build_manifest("2026-01-01", {}, "x", tmp_path / "nope.json", {})


def test_git_sha_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_SHA", "abc123")
    assert provenance.git_sha() == "abc123"


def test_git_sha_falls_back_to_git_or_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GIT_SHA", raising=False)
    sha = provenance.git_sha()
    assert sha == "unknown" or len(sha) == 40


@pytest.mark.azurite
def test_publish_uploads_manifest(azurite_conn: str, env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """publish writes provenance.json next to the marts, and records the input hashes it is given."""
    import shutil

    import duckdb
    import jsonschema

    from fhir_pipeline import pipeline
    from fhir_pipeline.blob import CURATED, BlobStore

    # Stand-in dbt manifest so publish does not need a dbt run.
    fake = env / "manifest.json"
    fake.write_text('{"nodes": {}}')
    monkeypatch.setattr(pipeline, "DBT_MANIFEST", fake)
    # Minimal warehouse: empty raw tables, staging views and marts.
    con = duckdb.connect(str(env / "wh.duckdb"))
    for schema in ("raw", "staging", "marts"):
        con.execute(f"create schema {schema}")
    for name in ("raw_patient", "raw_encounter", "raw_condition", "raw_observation"):
        con.execute(f"create table raw.{name} (x int)")
    for name in pipeline.STAGING_MODELS:
        con.execute(f"create table staging.{name} (x int)")
    for name in pipeline.MARTS:
        con.execute(f"create table marts.{name} (x int)")
    con.close()
    shutil.rmtree(env / "work", ignore_errors=True)

    store = BlobStore(azurite_conn)
    h = provenance.sha256_bytes(b"landing bytes")
    names = pipeline.publish(store, "2026-03-03", {"run_date": "2026-03-03"},
                             {"2026-03-03/Patient.ndjson": h})
    assert "2026-03-03/provenance.json" in names
    manifest = json.loads(store.download_bytes(CURATED, "2026-03-03/provenance.json"))
    jsonschema.validate(manifest, provenance.load_schema())
    assert manifest["inputs"] == [{"blob": "2026-03-03/Patient.ndjson", "sha256": h}]
    assert manifest["row_counts"]["marts"]["dim_patient"] == 0
    assert manifest["dbt_manifest_sha256"] == provenance.sha256_bytes(fake.read_bytes())


@pytest.mark.airflow
@pytest.mark.azurite
def test_dag_run_writes_manifest(azurite_conn: str, dbt_bin: str, tmp_path: Path) -> None:
    """Run the DAG on a small dataset. The uploaded manifest is valid and covers all four inputs."""
    import os
    import subprocess
    import sys

    import jsonschema

    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "AZURE_STORAGE_CONNECTION_STRING": azurite_conn, "DBT_BIN": dbt_bin,
           "FHIR_HMAC_KEY": "manifest-key-not-a-secret"}
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "run_dag_test.py"), "--patients", "60",
         "--run-date", "2026-04-04", "--workdir", str(tmp_path)],
        env=env, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    line = next(x for x in proc.stdout.splitlines() if x.startswith("REPORT_JSON="))
    manifest = json.loads(line.removeprefix("REPORT_JSON="))["provenance"]
    jsonschema.validate(manifest, provenance.load_schema())
    assert {i["blob"] for i in manifest["inputs"]} == {
        f"2026-04-04/{r}.ndjson" for r in ("Patient", "Encounter", "Condition", "Observation")
    }
    assert manifest["run_date"] == "2026-04-04"
