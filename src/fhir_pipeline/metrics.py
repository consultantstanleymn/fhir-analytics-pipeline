"""Pipeline metrics, written as a Prometheus textfile.

Airflow runs each task in its own process. So each `record_*` call updates a small JSON state
file, and `write()` renders the whole state as a textfile. A node exporter textfile collector
(or a push step) can then expose it. Neither runs in this repo.

Label values come from fixed sets, so the series count stays small.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from prometheus_client import CollectorRegistry, Gauge, write_to_textfile

METRICS_ENV = "FHIR_METRICS_FILE"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FILE = REPO_ROOT / ".work" / "metrics" / "fhir_pipeline.prom"

TASKS = (
    "list_new_blobs",
    "validate",
    "load",
    "quarantine_gate",
    "source_freshness",
    "dbt_build",
    "publish",
)
LAYERS = ("raw", "staging", "marts")
RESOURCES = ("Patient", "Encounter", "Condition", "Observation", "all")


def metrics_file() -> Path:
    return Path(os.environ.get(METRICS_ENV) or DEFAULT_FILE)


def _state_file() -> Path:
    return metrics_file().with_suffix(".state.json")


def _load() -> dict[str, Any]:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("task_seconds", {})
    data.setdefault("rows", {})
    return data  # type: ignore[no-any-return]


def _save(data: dict[str, Any]) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def _check(value: str, allowed: tuple[str, ...], what: str) -> None:
    if value not in allowed:
        raise ValueError(f"unknown {what}: {value!r}")


def record_task(task: str, seconds: float) -> None:
    _check(task, TASKS, "task")
    data = _load()
    data["task_seconds"][task] = round(float(seconds), 3)
    _save(data)


def record_rows(layer: str, resource: str, count: int) -> None:
    _check(layer, LAYERS, "layer")
    _check(resource, RESOURCES, "resource")
    data = _load()
    data["rows"][f"{layer}|{resource}"] = int(count)
    _save(data)


def record_quarantine_share(share: float) -> None:
    data = _load()
    data["quarantine_share"] = float(share)
    _save(data)


def mark_published(ts: float | None = None) -> None:
    data = _load()
    data["published_ts"] = float(time.time() if ts is None else ts)
    _save(data)


def set_run_success(ok: bool) -> None:
    data = _load()
    data["run_success"] = 1 if ok else 0
    _save(data)


@contextmanager
def timed(task: str) -> Iterator[None]:
    """Time a block and record its duration, also when the block raises."""
    start = time.perf_counter()
    try:
        yield
    finally:
        record_task(task, time.perf_counter() - start)


def build_registry(data: dict[str, Any]) -> CollectorRegistry:
    reg = CollectorRegistry()
    dur = Gauge("fhir_task_duration_seconds", "Duration of the last run of a task", ["task"], registry=reg)
    rows = Gauge("fhir_rows_total", "Rows per layer and resource at the last publish",
                 ["layer", "resource"], registry=reg)
    share = Gauge("fhir_quarantine_share", "Rejected share of input rows in the last run", registry=reg)
    pub = Gauge("fhir_marts_published_timestamp_seconds", "Unix time of the last mart publish", registry=reg)
    ok = Gauge("fhir_run_success", "1 if the last run succeeded, 0 if it failed", registry=reg)
    for task, seconds in sorted(data.get("task_seconds", {}).items()):
        dur.labels(task=task).set(seconds)
    for key, count in sorted(data.get("rows", {}).items()):
        layer, resource = key.split("|")
        rows.labels(layer=layer, resource=resource).set(count)
    share.set(data.get("quarantine_share", 0.0))
    pub.set(data.get("published_ts", 0.0))
    ok.set(data.get("run_success", 0))
    return reg


def write(path: Path | None = None) -> Path:
    """Render the state as a Prometheus textfile and return its path."""
    target = path or metrics_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    write_to_textfile(str(target), build_registry(_load()))
    return target
