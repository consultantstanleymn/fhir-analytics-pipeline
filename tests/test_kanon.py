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
