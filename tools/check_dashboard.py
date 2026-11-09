#!/usr/bin/env python3
"""Check a Grafana dashboard JSON file.

Usage: check_dashboard.py <dashboard.json>
Rules:
- The dashboard has `title`, `uid` and a non-empty `panels` list.
- Each panel has `title`, `type` and `targets`, and each target has an `expr`.
- Every metric name in an `expr` is a known metric. Known metrics are the gauges in
  src/fhir_pipeline/metrics.py and the recorded series in observability/rules/*.rules.yml.
Exit 1 on any failure.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FUNCTIONS = {"sum", "by", "avg", "max", "min", "rate", "increase", "avg_over_time", "round", "time", "hour",
             "without", "on", "and", "or", "bool", "count", "histogram_quantile", "irate", "clamp_min"}
NAME = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")


def known_metrics() -> set[str]:
    names = set(re.findall(r'Gauge\(\s*"([a-z_]+)"', (REPO / "src/fhir_pipeline/metrics.py").read_text()))
    for rules in (REPO / "observability" / "rules").glob("*.rules.yml"):
        names.update(re.findall(r"record:\s*([a-zA-Z_:][a-zA-Z0-9_:]*)", rules.read_text()))
    return names


def metrics_in(expr: str) -> set[str]:
    stripped = re.sub(r'"[^"]*"', "", expr)  # drop strings
    stripped = re.sub(r"\{[^}]*\}", "", stripped)  # drop label matchers
    stripped = re.sub(r"\[[^\]]*\]", "", stripped)  # drop ranges
    stripped = re.sub(r"\b(by|without|on)\s*\([^)]*\)", "", stripped)
    found = set()
    for m in NAME.finditer(stripped):
        word = m.group(0)
        if word in FUNCTIONS or word.isdigit():
            continue
        # a name followed by "(" is a function
        rest = stripped[m.end():].lstrip()
        if rest.startswith("("):
            continue
        found.add(word)
    return found


def check(path: Path) -> list[str]:
    errors: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("title", "uid"):
        if not data.get(key):
            errors.append(f"missing {key}")
    panels = data.get("panels") or []
    if not panels:
        errors.append("panels is empty")
    known = known_metrics()
    for i, panel in enumerate(panels):
        for key in ("title", "type", "targets"):
            if not panel.get(key):
                errors.append(f"panel {i}: missing {key}")
        for target in panel.get("targets") or []:
            expr = target.get("expr")
            if not expr:
                errors.append(f"panel {i}: target without expr")
                continue
            for name in sorted(metrics_in(expr) - known):
                errors.append(f"panel {i}: unknown metric {name}")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    errors = check(Path(argv[1]))
    for e in errors:
        print(f"FAIL: {e}")
    if not errors:
        print("dashboard ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
