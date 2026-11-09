from __future__ import annotations

import json

import pytest

from fhir_pipeline.pseudonymize import Keyring, load_keyring, pseudonymize, token


def _patient() -> dict:
    return {"resourceType": "Patient", "id": "P1", "gender": "female", "birthDate": "1960-01-02",
            "identifier": [{"value": "MRN-1"}], "address": [{"state": "MN"}]}


def test_token_has_kid_prefix() -> None:
    t = token(b"k", "Patient", "P1", "v7")
    kid, _, digest = t.partition(".")
    assert kid == "v7"
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
    out = pseudonymize(_patient(), Keyring({"v7": b"k"}, "v7"))
    assert out["patient_token"].startswith("v7.") and out["mrn_token"].startswith("v7.")


def test_new_kid_gives_new_token() -> None:
    ring = Keyring({"v1": b"old-key", "v2": b"new-key"}, "v1")
    old = pseudonymize(_patient(), ring)["patient_token"]
    new = pseudonymize(_patient(), Keyring(ring.keys, "v2"))["patient_token"]
    assert old != new
    assert old.startswith("v1.") and new.startswith("v2.")
    # same key bytes under another id still differ, because the id is part of the token
    assert token(b"same", "Patient", "P1", "v1") != token(b"same", "Patient", "P1", "v2")


def test_same_ring_same_token() -> None:
    ring = Keyring({"v1": b"k"}, "v1")
    assert pseudonymize(_patient(), ring) == pseudonymize(_patient(), ring)


def test_legacy_single_key_env_maps_to_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FHIR_HMAC_KEYS", raising=False)
    monkeypatch.delenv("FHIR_HMAC_ACTIVE", raising=False)
    monkeypatch.setenv("FHIR_HMAC_KEY", "legacy-key")
    ring = load_keyring()
    assert ring.active == "v1" and ring.keys == {"v1": b"legacy-key"}


def test_keyring_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHIR_HMAC_KEYS", json.dumps({"v1": "a", "v2": "b"}))
    monkeypatch.setenv("FHIR_HMAC_ACTIVE", "v2")
    ring = load_keyring()
    assert ring.active == "v2" and ring.key == b"b" and set(ring.keys) == {"v1", "v2"}


def test_missing_active_kid_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHIR_HMAC_KEYS", json.dumps({"v1": "a"}))
    monkeypatch.delenv("FHIR_HMAC_ACTIVE", raising=False)
    with pytest.raises(RuntimeError, match="FHIR_HMAC_ACTIVE"):
        load_keyring()
    monkeypatch.setenv("FHIR_HMAC_ACTIVE", "v9")
    with pytest.raises(RuntimeError, match="not in the keyring"):
        load_keyring()


def test_bad_key_id_and_bad_json_are_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        Keyring({"v.1": b"k"}, "v.1")  # a dot would break the token format
    monkeypatch.setenv("FHIR_HMAC_KEYS", "not json")
    monkeypatch.setenv("FHIR_HMAC_ACTIVE", "v1")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        load_keyring()
    monkeypatch.setenv("FHIR_HMAC_KEYS", json.dumps({"v1": ""}))
    with pytest.raises(RuntimeError, match="non-empty"):
        load_keyring()


def _use_ring(monkeypatch: pytest.MonkeyPatch, active: str) -> None:
    monkeypatch.setenv("FHIR_HMAC_KEYS", json.dumps({"v1": "first-test-key", "v2": "second-test-key"}))
    monkeypatch.setenv("FHIR_HMAC_ACTIVE", active)


def _new_warehouse(monkeypatch: pytest.MonkeyPatch, root, name: str) -> None:
    monkeypatch.setenv("DUCKDB_PATH", str(root / f"{name}.duckdb"))
    monkeypatch.setenv("FHIR_WORK_DIR", str(root / f"work-{name}"))


@pytest.mark.dbt
def test_old_curated_parquet_still_readable_after_rotation(env, dbt_bin, monkeypatch) -> None:
    from pathlib import Path

    import duckdb

    from fhir_pipeline import pipeline

    fixture = Path(__file__).parent / "fixtures" / "readmission"
    monkeypatch.setenv("DBT_BIN", dbt_bin)
    out = env / "parquet"
    out.mkdir()

    def build_and_export(active: str, name: str) -> None:
        _use_ring(monkeypatch, active)
        _new_warehouse(monkeypatch, env, name)
        pipeline.ingest_dir(fixture, "2026-01-01")
        pipeline.dbt_build()
        con = duckdb.connect(str(env / f"{name}.duckdb"), read_only=True)
        for mart in ("dim_patient", "fct_encounters", "mart_readmissions_30d"):
            target = out / f"{name}-{mart}.parquet"
            con.execute(f"COPY (SELECT * FROM marts.{mart}) TO '{target}' (FORMAT PARQUET)")
        con.close()

    build_and_export("v1", "run1")
    build_and_export("v2", "run2")

    # Old files stay readable after rotation and keep their key id.
    q = duckdb.connect()

    def token_column(file: str) -> list[str]:
        sql = f"select patient_token from read_parquet('{out / file}')"
        return [r[0] for r in q.execute(sql).fetchall()]

    old = token_column("run1-dim_patient.parquet")
    new = token_column("run2-dim_patient.parquet")
    assert old and new and len(old) == len(new)
    assert all(t.startswith("v1.") for t in old)
    assert all(t.startswith("v2.") for t in new)
    assert all(t.startswith("v1.") for t in token_column("run1-fct_encounters.parquet"))

    # Marts without tokens give the same values under both key versions.
    def readmissions(name: str):
        file = out / f"{name}-mart_readmissions_30d.parquet"
        return q.execute(f"select * from read_parquet('{file}') order by department").fetchall()

    assert readmissions("run1") == readmissions("run2")
    assert len(readmissions("run1")) == 3


def test_tokens_do_not_link_across_versions(env, monkeypatch) -> None:
    """Documented property: the same patient gets unrelated tokens under v1 and v2."""
    from pathlib import Path

    import duckdb

    from fhir_pipeline import pipeline

    fixture = Path(__file__).parent / "fixtures" / "readmission"

    def tokens(active: str, name: str) -> set[str]:
        _use_ring(monkeypatch, active)
        _new_warehouse(monkeypatch, env, name)
        pipeline.ingest_dir(fixture, "2026-01-01")
        con = duckdb.connect(str(env / f"{name}.duckdb"), read_only=True)
        sql = "select json_extract_string(resource, '$.patient_token') from raw.raw_patient"
        rows = con.execute(sql).fetchall()
        con.close()
        return {r[0] for r in rows}

    v1, v2 = tokens("v1", "a"), tokens("v2", "b")
    assert v1 and len(v1) == len(v2)
    assert v1.isdisjoint(v2)
    # Even the 64-character digests differ, so a join on the digest part does not link them either.
    assert {t.split(".")[1] for t in v1}.isdisjoint({t.split(".")[1] for t in v2})
