from __future__ import annotations

import re
from pathlib import Path

import pytest

from fhir_pipeline import metrics


@pytest.fixture
def prom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "m" / "fhir.prom"
    monkeypatch.setenv("FHIR_METRICS_FILE", str(path))
    return path


def _series(text: str) -> list[str]:
    return [line for line in text.splitlines() if line and not line.startswith("#")]


def test_textfile_has_expected_series(prom: Path) -> None:
    metrics.record_task("validate", 1.5)
    metrics.record_task("dbt_build", 20.25)
    metrics.record_rows("raw", "Patient", 1020)
    metrics.record_rows("marts", "all", 4000)
    metrics.record_quarantine_share(0.021)
    metrics.mark_published(1_800_000_000.0)
    metrics.set_run_success(True)
    metrics.write()
    text = prom.read_text()
    assert 'fhir_task_duration_seconds{task="validate"} 1.5' in text
    assert 'fhir_task_duration_seconds{task="dbt_build"} 20.25' in text
    assert 'fhir_rows_total{layer="raw",resource="Patient"} 1020.0' in text
    assert 'fhir_rows_total{layer="marts",resource="all"} 4000.0' in text
    assert "fhir_quarantine_share 0.021" in text
    assert "fhir_marts_published_timestamp_seconds 1.8e+09" in text
    assert "fhir_run_success 1.0" in text


def test_label_values_are_bounded(prom: Path) -> None:
    with pytest.raises(ValueError):
        metrics.record_task("not_a_task", 1.0)
    with pytest.raises(ValueError):
        metrics.record_rows("bronze", "Patient", 1)
    with pytest.raises(ValueError):
        metrics.record_rows("raw", "Practitioner", 1)
    for task in metrics.TASKS:
        metrics.record_task(task, 0.1)
    for layer in metrics.LAYERS:
        for resource in metrics.RESOURCES:
            metrics.record_rows(layer, resource, 1)
    metrics.write()
    series = _series(prom.read_text())
    assert len(series) <= len(metrics.TASKS) + len(metrics.LAYERS) * len(metrics.RESOURCES) + 3
    tasks = set(re.findall(r'task="([^"]+)"', prom.read_text()))
    assert tasks <= set(metrics.TASKS)


def test_failure_writes_run_success_zero(prom: Path) -> None:
    metrics.set_run_success(True)
    metrics.set_run_success(False)
    metrics.write()
    assert "fhir_run_success 0.0" in prom.read_text()


def test_timed_records_duration_even_on_error(prom: Path) -> None:
    with pytest.raises(RuntimeError), metrics.timed("publish"):
        raise RuntimeError("boom")
    metrics.write()
    assert 'fhir_task_duration_seconds{task="publish"}' in prom.read_text()


def test_state_survives_between_calls_and_processes(prom: Path) -> None:
    metrics.record_task("load", 2.0)
    # a second "process" is the same code with a fresh read of the state file
    metrics.record_task("validate", 3.0)
    metrics.write()
    text = prom.read_text()
    assert 'task="load"' in text and 'task="validate"' in text


def test_default_path_is_under_work_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FHIR_METRICS_FILE", raising=False)
    assert metrics.metrics_file().parts[-3:] == (".work", "metrics", "fhir_pipeline.prom")
