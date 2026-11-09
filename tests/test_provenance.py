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
