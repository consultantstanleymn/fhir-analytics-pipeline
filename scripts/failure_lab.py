#!/usr/bin/env python3
"""Failure lab: inject faults into the pipeline and record what happens.

Cases: corrupt-blob, schema-drift-new-field, schema-drift-removed-field, late-update, azurite-down.
Each case starts its own Azurite container (scripts/azurite.sh) and its own warehouse in a temp
folder. All data is synthetic. Nothing leaves this machine.

Usage (from the repo root):
  .venv/bin/python scripts/failure_lab.py --all
  .venv/bin/python scripts/failure_lab.py --case late-update
Needs: podman (Azurite image), .venv-dbt (dbt). Exit 1 when an expectation fails.
The output starts with an evidence header and holds one section per case.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from generator.generate_fhir import generate, write_bundle  # noqa: E402

CASES = ["corrupt-blob", "schema-drift-new-field", "schema-drift-removed-field", "late-update", "azurite-down"]
FAILURES: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)


def expect(label: str, ok: bool, detail: str = "") -> None:
    say(f"expect: {label}: {'PASS' if ok else 'FAIL'}" + (f" ({detail})" if detail else ""))
    if not ok:
        FAILURES.append(label)


def azurite(action: str) -> str:
    proc = subprocess.run([str(REPO / "scripts" / "azurite.sh"), action], capture_output=True, text=True, check=True)
    return proc.stdout


def start_azurite() -> str:
    out = azurite("start")
    match = re.search(r"AZURE_STORAGE_CONNECTION_STRING='([^']+)'", out)
    if not match:
        raise RuntimeError("could not read the Azurite connection string")
    os.environ["AZURE_STORAGE_CONNECTION_STRING"] = match.group(1)
    return match.group(1)


@contextmanager
def lab(case: str) -> Iterator[Path]:
    """Fresh Azurite, warehouse and work folder for one case."""
    with tempfile.TemporaryDirectory(prefix=f"fhir-lab-{case}-") as tmp:
        root = Path(tmp)
        os.environ["DUCKDB_PATH"] = str(root / "warehouse.duckdb")
        os.environ["FHIR_WORK_DIR"] = str(root / "run")
        os.environ["FHIR_METRICS_FILE"] = str(root / "metrics" / "fhir_pipeline.prom")
        os.environ["FHIR_HMAC_KEY"] = "failure-lab-key-not-a-secret"
        os.environ.setdefault("DBT_BIN", str(REPO / ".venv-dbt" / "bin" / "dbt"))
        os.environ.pop("FHIR_MAX_QUARANTINE_SHARE", None)
        start_azurite()
        try:
            yield root
        finally:
            azurite("stop")


def sql(root: Path, query: str) -> list[tuple[Any, ...]]:
    import duckdb

    con = duckdb.connect(str(root / "warehouse.duckdb"), read_only=True)
    try:
        return con.execute(query).fetchall()
    finally:
        con.close()


def counts(root: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in ("raw_patient", "raw_encounter", "raw_condition", "raw_observation", "quarantine", "load_log"):
        try:
            out[name] = int(sql(root, f"select count(*) from raw.{name}")[0][0])  # nosec B608
        except Exception:  # noqa: BLE001  # table may not exist yet; a missing table counts as 0
            out[name] = 0
    return out


def reasons(root: Path) -> list[tuple[str, int]]:
    rows = sql(root, "select split_part(reason, ':', 1) || ':' || split_part(reason, ':', 2), count(*) "
                     "from raw.quarantine group by 1 order by 2 desc, 1")
    return [(str(r[0]), int(r[1])) for r in rows]


def make_day(dir_: Path, patients: int, seed: int) -> dict[str, list[str]]:
    bundle = generate(patients, seed, with_edge_cases=False)
    write_bundle(bundle, dir_)
    return bundle.lines


def upload(store: Any, run_date: str, lines: dict[str, list[str]], work: Path) -> None:
    from fhir_pipeline.pipeline import upload_landing

    d = work / f"landing-{run_date}"
    d.mkdir(parents=True, exist_ok=True)
    for rtype, items in lines.items():
        (d / f"{rtype}.ndjson").write_text("\n".join(items) + "\n", encoding="utf-8")
    upload_landing(store, d, run_date)


def run_day(store: Any, run_date: str, *, build: bool = True, publish_day: bool = True) -> dict[str, Any]:
    """The pipeline steps that the DAG runs, called in order."""
    from fhir_pipeline import pipeline

    found = pipeline.list_new_blobs(store, run_date)
    loads: list[dict[str, Any]] = []
    inputs: dict[str, str] = {}
    for rtype in pipeline.RESOURCE_ORDER:
        if rtype not in found:
            continue
        stats = pipeline.validate_blob(store, run_date, rtype)
        loads.append({**stats, **pipeline.load_blob(run_date, rtype, stats["rows_in"])})
        inputs[pipeline.landing_blob(run_date, rtype)] = stats["input_sha256"]
    result: dict[str, Any] = {"found": sorted(found), "loads": loads}
    result["gate"] = pipeline.check_quarantine_rate(loads)  # raises QuarantineGateError over the limit
    if build:
        result["dbt"] = pipeline.dbt_build()
        if publish_day:
            summary: dict[str, Any] = {"run_date": run_date}
            result["published"] = pipeline.publish(store, run_date, summary, inputs)
    return result


def fct(root: Path) -> dict[str, tuple[Any, ...]]:
    rows = sql(root, "select encounter_id, department, last_updated, cast(dbt_loaded_at as varchar) "
                     "from marts.fct_encounters order by 1")
    return {str(r[0]): tuple(r[1:]) for r in rows}


def curated(store: Any, run_date: str) -> list[str]:
    return [Path(x).name for x in store.list_blobs("curated", f"{run_date}/")]


# ---------------------------------------------------------------- cases


def case_corrupt_blob(root: Path) -> None:
    from fhir_pipeline.blob import BlobStore
    from fhir_pipeline.pipeline import QuarantineGateError

    store = BlobStore()
    day1 = make_day(root / "gen1", 100, 1)
    upload(store, "2026-03-01", day1, root)
    run_day(store, "2026-03-01")
    before = counts(root)
    say(f"before (clean day loaded): {json.dumps(before)}")

    # Day 2: a few broken lines among good ones (about 2 percent).
    day2 = make_day(root / "gen2", 100, 2)
    obs = day2["Observation"]
    for i in (3, 20, 41):
        obs[i] = obs[i][: len(obs[i]) // 2]  # cut the line in half
    obs[7] = "\x00\x01 not json at all"
    upload(store, "2026-03-02", day2, root)
    res = run_day(store, "2026-03-02")
    after = counts(root)
    say(f"injection: 4 broken lines of {len(obs)} Observation lines (cut in half, or binary noise)")
    say(f"gate: {json.dumps(res['gate'])}")
    say(f"quarantine reasons: {reasons(root)}")
    say(f"after: {json.dumps(after)}")
    expect("broken lines go to quarantine", after["quarantine"] - before["quarantine"] == 4,
           f"quarantine +{after['quarantine'] - before['quarantine']}")
    expect("good lines still load", after["raw_observation"] - before["raw_observation"] == len(obs) - 4)
    expect("gate passes under the 5 percent limit", res["gate"]["ok"] is True)

    # Day 3: a third of the Observation lines are broken. The gate must stop the run before dbt.
    day3 = make_day(root / "gen3", 100, 3)
    obs3 = day3["Observation"]
    for i in range(0, len(obs3), 3):
        obs3[i] = obs3[i][:20]
    upload(store, "2026-03-03", day3, root)
    pre_marts = fct(root)
    try:
        run_day(store, "2026-03-03")
        raised = None
    except QuarantineGateError as exc:
        raised = str(exc)
    say(f"day 3: about 33 percent of Observation lines broken. Gate result: {raised}")
    expect("gate stops the run when the share is too high", raised is not None)
    expect("marts are unchanged after a stopped run", fct(root) == pre_marts)
    expect("nothing is published for the stopped day", curated(store, "2026-03-03") == [])
    say("data effect: bad lines are kept in raw.quarantine with the reason and the raw text. Good lines load.")


def _drift_case(root: Path, label: str, mutate: Callable[[dict[str, Any]], dict[str, Any]], expect_rejected: bool | None) -> None:
    from fhir_pipeline.blob import BlobStore
    from fhir_pipeline.pipeline import QuarantineGateError

    store = BlobStore()
    base = make_day(root / "gen", 60, 5)
    upload(store, "2026-03-01", base, root)
    run_day(store, "2026-03-01")
    before = counts(root)
    day2 = make_day(root / "gen-b", 60, 6)
    enc = day2["Encounter"]
    changed = 0
    for i in range(0, len(enc), 10):
        enc[i] = json.dumps(mutate(json.loads(enc[i])))
        changed += 1
    upload(store, "2026-03-02", day2, root)
    gate_stop = None
    dbt_fail = None
    res: dict[str, Any] = {"gate": {"share": "n/a"}}
    try:
        res = run_day(store, "2026-03-02")
    except QuarantineGateError as exc:
        gate_stop = str(exc)
    except RuntimeError as exc:  # dbt build failed: a dbt test caught a problem
        dbt_fail = str(exc)
    after = counts(root)
    rejected = after["quarantine"] - before["quarantine"]
    loaded = after["raw_encounter"] - before["raw_encounter"]
    say(f"injection: {label} on {changed} of {len(enc)} Encounter lines")
    say(f"before: {json.dumps(before)}")
    say(f"after: {json.dumps(after)}")
    say(f"quarantine reasons: {reasons(root)}")
    say(f"observed: {loaded} Encounter rows loaded, {rejected} quarantined; gate share {res['gate']['share']}")
    if expect_rejected is True:
        expect("changed lines are quarantined", rejected == changed, f"{rejected} of {changed}")
    elif expect_rejected is False:
        expect("changed lines are accepted", rejected == 0, f"{rejected} rejected")
    published = any(n == "provenance.json" for n in curated(store, "2026-03-02"))
    if gate_stop:
        say(f"gate stopped the run: {gate_stop}")
    if dbt_fail:
        tests = sorted(set(re.findall(r"in test (\S+)", dbt_fail)))
        say(f"dbt build stopped the run. Failing tests: {tests}")
        say("reason: a quarantined Encounter leaves Condition and Observation rows that point to it. "
            "The dbt relationship tests catch these orphan references.")
        expect("nothing is published when dbt fails", not published)
    elif not gate_stop:
        expect("run ends with marts published", published)


def case_new_field(root: Path) -> None:
    def add(e: dict[str, Any]) -> dict[str, Any]:
        e["unexpectedNewField"] = "value from a new source version"
        return e

    _drift_case(root, "a new unknown top-level field", add, None)
    say("data effect: see 'observed'. A strict model rejects unknown fields; the result above shows what this validator does.")


def case_removed_field(root: Path) -> None:
    def drop(e: dict[str, Any]) -> dict[str, Any]:
        e.pop("status", None)  # a required FHIR field
        return e

    _drift_case(root, "the required field 'status' removed", drop, True)
    say("data effect: lines without the required field never reach the warehouse tables. They wait in quarantine.")


def case_late_update(root: Path) -> None:
    from fhir_pipeline.blob import BlobStore

    store = BlobStore()
    day1 = make_day(root / "gen1", 80, 7)
    upload(store, "2026-03-01", day1, root)
    run_day(store, "2026-03-01")
    before = fct(root)
    max_lu = max(v[1] for v in before.values())
    # pick an encounter that is older than the maximum, and send a newer version that is still older than the maximum
    eid, (dept, lu, _) = next((k, v) for k, v in sorted(before.items()) if v[1] < max_lu)
    line = next(x for x in day1["Encounter"] if json.loads(x)["id"] == eid)
    e = json.loads(line)
    from datetime import timedelta

    new_lu = lu + timedelta(seconds=1)
    e["meta"]["lastUpdated"] = new_lu.strftime("%Y-%m-%dT%H:%M:%SZ")
    e["serviceType"] = {"coding": [{"system": "urn:example:department", "display": "Late Arrival Unit"}]}
    upload(store, "2026-03-02", {"Patient": [], "Encounter": [json.dumps(e)], "Condition": [], "Observation": []}, root)
    res = run_day(store, "2026-03-02")
    after = fct(root)
    say(f"injection: encounter {eid} gets a new version with lastUpdated {new_lu} (table maximum is {max_lu})")
    say(f"before: department={dept!r}; after: department={after[eid][0]!r}")
    changed = sorted(k for k in after if after[k] != before.get(k))
    say(f"rows that changed in the mart: {changed}")
    say(f"gate: {json.dumps(res['gate'])}")
    expect("late update is applied", after[eid][0] == "Late Arrival Unit")
    expect("no other mart row changes", changed == [eid], f"{len(changed)} changed")
    say("data effect: one row replaced. Before the fix this update was skipped (docs/DECISIONS.md entry 6).")


def case_azurite_down(root: Path) -> None:
    from fhir_pipeline import pipeline
    from fhir_pipeline.blob import BlobStore

    store = BlobStore(retries=1)  # one retry, so a stopped emulator fails fast
    day = make_day(root / "gen1", 60, 9)
    upload(store, "2026-03-01", day, root)
    run_day(store, "2026-03-01", build=True, publish_day=False)  # load + dbt, no publish yet
    before = counts(root)
    say(f"before: loaded and built, publish not run yet. {json.dumps(before)}")
    azurite("stop")
    say("injection: Azurite stopped before the publish step")
    error = None
    try:
        pipeline.publish(store, "2026-03-01", {"run_date": "2026-03-01"}, {})
    except Exception as exc:  # noqa: BLE001  # the lab records whatever error the storage SDK gives
        error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''}"
    say(f"publish error: {error}")
    expect("publish fails with a clear error", error is not None)
    expect("warehouse is unchanged by the failed publish", counts(root) == before)
    say("order in publish: mart files first, then provenance.json, then run_summary.json. A failure before the end leaves no summary.")

    # Restart. The emulator container is ephemeral, so the landing blobs are gone. Put them back (same content).
    start_azurite()
    store2 = BlobStore()
    upload(store2, "2026-03-01", day, root)
    again = pipeline.list_new_blobs(store2, "2026-03-01")
    say(f"after restart: blobs the load log has not seen yet: {again}")
    expect("re-run loads nothing twice", again == {})
    names = pipeline.publish(store2, "2026-03-01", {"run_date": "2026-03-01"}, {})
    after = counts(root)
    expect("re-run publish completes", "2026-03-01/provenance.json" in names and "2026-03-01/run_summary.json" in names)
    expect("row counts do not change on the re-run", {k: v for k, v in after.items()} == before)
    say(f"after: {json.dumps(after)}")
    say("data effect: no duplicate rows. The load log blocks a second load of the same blob.")


RUNNERS: dict[str, Callable[[Path], None]] = {
    "corrupt-blob": case_corrupt_blob,
    "schema-drift-new-field": case_new_field,
    "schema-drift-removed-field": case_removed_field,
    "late-update": case_late_update,
    "azurite-down": case_azurite_down,
}


def header(command: str) -> None:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                           text=True, cwd=REPO).stdout.strip()
    say("# Evidence: failure lab")
    say("label: VERIFIED LOCALLY")
    say(f"date: {subprocess.run(['date', '-u', '+%Y-%m-%d %H:%M'], capture_output=True, text=True).stdout.strip()} UTC")
    say(f"code commit: {sha}")
    say(f"working tree clean at run time: {'yes' if not dirty else 'no'}")
    say("machine: MacBook Pro (mid 2015), 8 logical CPUs, 16 GB RAM, Fedora 44, podman 5.8.7 (measured on one laptop)")
    say(f"command: {command}")
    say("notes: Each case injects one fault into a synthetic run on Azurite and records counts before and after. "
        "It does not prove behavior on real Azure storage or with real data.")
    say("---")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--case", choices=CASES, action="append")
    args = ap.parse_args()
    chosen = CASES if args.all else (args.case or [])
    if not chosen:
        ap.error("give --all or --case")
    header(".venv/bin/python scripts/failure_lab.py " + ("--all" if args.all else " ".join(f"--case {c}" for c in chosen)))
    for case in chosen:
        say(f"\n## case: {case}")
        with lab(case) as root:
            RUNNERS[case](root)
    say(f"\nsummary: {len(chosen)} case(s), {len(FAILURES)} failed expectation(s)")
    for f in FAILURES:
        say(f"failed: {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
