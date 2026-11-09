from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("check_dashboard", REPO / "tools" / "check_dashboard.py")
assert _SPEC and _SPEC.loader
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)
DASH = REPO / "observability" / "grafana" / "fhir-pipeline.json"


def test_dashboard_passes_check() -> None:
    assert mod.check(DASH) == []


def test_dashboard_with_unknown_metric_fails(tmp_path: Path) -> None:
    data = json.loads(DASH.read_text())
    data["panels"][0]["targets"][0]["expr"] = "some_other_metric_total"
    bad = tmp_path / "d.json"
    bad.write_text(json.dumps(data))
    assert any("some_other_metric_total" in e for e in mod.check(bad))


def test_dashboard_missing_fields_fail(tmp_path: Path) -> None:
    bad = tmp_path / "d.json"
    bad.write_text(json.dumps({"title": "x", "panels": [{"title": "p", "type": "stat"}]}))
    errors = mod.check(bad)
    assert any("uid" in e for e in errors) and any("targets" in e for e in errors)


def test_known_metrics_include_pipeline_and_rule_series() -> None:
    known = mod.known_metrics()
    assert "fhir_marts_published_timestamp_seconds" in known
    assert "fhir:marts_on_time:ratio_28d" in known
    assert "fhir_task_duration_seconds" in known


def test_rules_file_has_alert_and_slo_rules() -> None:
    text = (REPO / "observability" / "rules" / "freshness.rules.yml").read_text()
    assert "alert: FhirMartsLate" in text and "fhir:marts_on_time:ratio_28d" in text
    assert "UTC" in text


def test_observability_doc_lists_every_metric() -> None:
    doc = (REPO / "docs" / "engagement" / "OBSERVABILITY.md").read_text()
    for name in mod.known_metrics():
        assert f"`{name}`" in doc, name
