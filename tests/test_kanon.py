from __future__ import annotations

import random

import pytest

from fhir_pipeline import kanon

QI = ("birth_year", "state", "gender")


def _row(year: int, state: str, gender: str = "female") -> dict:
    return {"patient_token": f"{year}{state}{gender}", "birth_year": year, "state": state, "gender": gender}


def test_group_sizes_counts() -> None:
    rows = [_row(1960, "MN"), _row(1960, "MN"), _row(1961, "MN"), _row(1960, "WI", "male")]
    sizes = kanon.group_sizes(rows)
    assert sizes[(1960, "MN", "female")] == 2
    assert sizes[(1961, "MN", "female")] == 1
    assert sum(sizes.values()) == 4


def test_enforce_k_generalizes_birth_year_first() -> None:
    # Same state and gender, ten birth years in one decade: years alone are too small.
    rows = [_row(1960 + i % 10, "MN") for i in range(20)]
    out, report = kanon.enforce_k(rows, 5)
    assert report["steps_applied"] == ["birth_decade"]
    assert {r["birth_year"] for r in out} == {"1960s"}
    assert {r["state"] for r in out} == {"MN"}  # state is still exact
    assert report["suppressed_rows"] == 0
    assert report["min_group_size"] == 20


def test_enforce_k_uses_region_when_decade_is_not_enough() -> None:
    rows = [_row(1960, s) for s in ("MN", "WI", "IA", "ND", "SD")]
    out, report = kanon.enforce_k(rows, 5)
    assert report["steps_applied"] == ["birth_decade", "region"]
    assert {r["state"] for r in out} == {"Midwest"}
    assert report["min_group_size"] == 5


def test_enforce_k_suppresses_last_resort() -> None:
    rows = [_row(1960, "MN") for _ in range(10)] + [_row(1990, "TX", "male")]
    out, report = kanon.enforce_k(rows, 5)
    assert report["steps_applied"][-1] == "suppress"
    assert report["suppressed_rows"] == 1
    assert len(out) == 10
    assert all(r["gender"] == "female" for r in out)


def test_nothing_changes_when_every_group_is_large() -> None:
    rows = [_row(1960, "MN") for _ in range(6)]
    out, report = kanon.enforce_k(rows, 5)
    assert out == rows
    assert report["steps_applied"] == []


def test_no_group_under_k_after_enforce() -> None:
    rng = random.Random(3)
    rows = [
        _row(rng.randint(1930, 2005), rng.choice(["MN", "WI", "IA", "TX", "CA", "NY", "ZZ"]),
             rng.choice(["female", "male", "other"]))
        for _ in range(400)
    ]
    for k in (2, 5, 10, 25):
        out, report = kanon.enforce_k(rows, k)
        sizes = kanon.group_sizes(out)
        assert all(n >= k for n in sizes.values())
        assert report["min_group_size"] == min(sizes.values(), default=0)


def test_report_counts_match() -> None:
    rows = [_row(1960, "MN") for _ in range(10)] + [_row(1990, "TX", "male"), _row(1991, "TX", "male")]
    out, report = kanon.enforce_k(rows, 5)
    assert report["k"] == 5
    assert report["rows_in"] == 12
    assert report["rows_out"] == len(out) == 10
    assert report["suppressed_rows"] == 2
    assert report["groups"] == len(kanon.group_sizes(out))
    assert report["quasi_identifiers"] == list(QI)


def test_input_rows_are_not_changed() -> None:
    rows = [_row(1960 + i, "MN") for i in range(10)]
    before = [dict(r) for r in rows]
    kanon.enforce_k(rows, 5)
    assert rows == before


def test_empty_input() -> None:
    out, report = kanon.enforce_k([], 5)
    assert out == [] and report["min_group_size"] == 0 and report["groups"] == 0


def test_k_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FHIR_K_ANON", raising=False)
    assert kanon.get_k() == 5
    monkeypatch.setenv("FHIR_K_ANON", "8")
    assert kanon.get_k() == 8
    rows = [_row(1960, "MN") for _ in range(6)]
    _, report = kanon.enforce_k(rows)
    assert report["k"] == 8 and report["suppressed_rows"] == 6
    monkeypatch.setenv("FHIR_K_ANON", "0")
    with pytest.raises(ValueError):
        kanon.get_k()


class _FakeStore:
    """Directory-backed stand-in for BlobStore. Only the calls that publish makes."""

    def __init__(self, root) -> None:
        self.root = root

    def ensure_container(self, name: str) -> None:
        (self.root / name).mkdir(parents=True, exist_ok=True)

    def upload_file(self, container: str, blob: str, path) -> None:
        dest = self.root / container / blob
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())

    def upload_bytes(self, container: str, blob: str, data: bytes) -> None:
        dest = self.root / container / blob
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def _warehouse(env, patients: int = 120):
    """Minimal warehouse with the seven marts. Patients are spread over a few small groups."""
    import duckdb

    from fhir_pipeline import pipeline

    rng = random.Random(11)
    con = duckdb.connect(str(env / "wh.duckdb"))
    for schema in ("raw", "staging", "marts"):
        con.execute(f"create schema {schema}")
    for name in ("raw_patient", "raw_encounter", "raw_condition", "raw_observation"):
        con.execute(f"create table raw.{name} (x int)")
    for name in pipeline.STAGING_MODELS:
        con.execute(f"create table staging.{name} (x int)")
    for name in pipeline.MARTS:
        if name not in ("dim_patient", "mart_condition_prevalence"):
            con.execute(f"create table marts.{name} (x int)")
    con.execute(
        "create table marts.dim_patient (patient_token varchar, mrn_token varchar, gender varchar, "
        "birth_year integer, birth_decade double, state varchar)"
    )
    for i in range(patients):
        year = rng.randint(1940, 2000)
        con.execute(
            "insert into marts.dim_patient values (?, ?, ?, ?, ?, ?)",
            [f"v1.p{i}", f"v1.m{i}", rng.choice(["female", "male"]), year, year // 10 * 10.0,
             rng.choice(["MN", "WI", "IA", "ND", "SD", "IL"])],
        )
    con.execute(
        "create table marts.mart_condition_prevalence (condition_code varchar, condition_display varchar, "
        "patients_with_condition bigint, total_patients bigint, prevalence double)"
    )
    con.execute("insert into marts.mart_condition_prevalence values ('A', 'common', 100, 120, 0.8333), "
                "('B', 'rare', 2, 120, 0.0167)")
    con.close()


def _publish(env, monkeypatch, k: int):
    from fhir_pipeline import pipeline

    fake = env / "manifest.json"
    fake.write_text('{"nodes": {}}')
    monkeypatch.setattr(pipeline, "DBT_MANIFEST", fake)
    monkeypatch.setenv("FHIR_K_ANON", str(k))
    store = _FakeStore(env / "blobs")
    pipeline.publish(store, "2026-05-05", {"run_date": "2026-05-05"}, {})
    return env / "blobs" / "curated" / "2026-05-05"


def test_curated_dim_patient_has_no_group_under_k(env, monkeypatch) -> None:
    import duckdb

    _warehouse(env)
    out = _publish(env, monkeypatch, 5)
    con = duckdb.connect()
    rows = con.execute(
        f"select birth_year, state, gender from read_parquet('{out / 'dim_patient.parquet'}')"
    ).fetchall()
    assert rows  # not everything was dropped
    sizes = kanon.group_sizes([dict(zip(QI, r, strict=True)) for r in rows])
    assert min(sizes.values()) >= 5
    # the warehouse table still holds exact values for all 120 patients
    wh = duckdb.connect(str(env / "wh.duckdb"), read_only=True)
    assert wh.execute("select count(*) from marts.dim_patient").fetchone() == (120,)


def test_small_cell_rows_are_hidden_in_prevalence(env, monkeypatch) -> None:
    import duckdb

    _warehouse(env)
    out = _publish(env, monkeypatch, 5)
    rows = duckdb.connect().execute(
        f"select condition_code, patients_with_condition, prevalence, suppressed "
        f"from read_parquet('{out / 'mart_condition_prevalence.parquet'}') order by condition_code"
    ).fetchall()
    assert rows == [("A", 100, 0.8333, False), ("B", None, None, True)]


def test_manifest_contains_kanon_report(env, monkeypatch) -> None:
    import json

    _warehouse(env)
    out = _publish(env, monkeypatch, 5)
    manifest = json.loads((out / "provenance.json").read_text())
    summary = json.loads((out / "run_summary.json").read_text())
    report = manifest["kanon"]
    assert report["k"] == 5 and report["min_group_size"] >= 5
    assert report["rows_in"] == 120
    assert report["small_cell_suppressed"] == {"mart_condition_prevalence": 1}
    assert summary["kanon"] == report


@pytest.mark.dbt
def test_curated_dim_patient_from_fixture_warehouse(env, dbt_bin, monkeypatch) -> None:
    """Real dbt marts from the readmission fixture. Few patients, so groups under k are dropped."""
    from pathlib import Path

    import duckdb

    from fhir_pipeline import pipeline

    monkeypatch.setenv("DBT_BIN", dbt_bin)
    pipeline.ingest_dir(Path(__file__).parent / "fixtures" / "readmission", "2026-01-01")
    pipeline.dbt_build()
    store = _FakeStore(env / "blobs")
    monkeypatch.setenv("FHIR_K_ANON", "3")
    pipeline.publish(store, "2026-05-06", {"run_date": "2026-05-06"}, {})
    path = env / "blobs" / "curated" / "2026-05-06" / "dim_patient.parquet"
    rows = duckdb.connect().execute(
        f"select birth_year, state, gender from read_parquet('{path}')"
    ).fetchall()
    sizes = kanon.group_sizes([dict(zip(QI, r, strict=True)) for r in rows])
    assert all(n >= 3 for n in sizes.values())
