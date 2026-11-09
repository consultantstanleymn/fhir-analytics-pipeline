"""Pipeline steps. The Airflow DAG calls these functions; tests call them directly.

Heavy work lives here, not in the DAG file, so the DAG file imports fast.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .blob import CURATED, LANDING, BlobStore
from .pseudonymize import load_key, pseudonymize
from .validate import Accepted, validate_line
from .warehouse import RAW_TABLES, already_loaded, connect, init_schema, load_resources

RESOURCE_ORDER = ("Patient", "Encounter", "Condition", "Observation")
MARTS = [
    "fct_encounters",
    "dim_patient",
    "dim_department",
    "mart_readmissions_30d",
    "mart_los",
    "mart_encounters_weekly",
    "mart_condition_prevalence",
]
REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_QUARANTINE_ENV = "FHIR_MAX_QUARANTINE_SHARE"
DEFAULT_MAX_QUARANTINE_SHARE = 0.05


class QuarantineGateError(RuntimeError):
    """Raised when the rejected share of input rows passes the set limit."""


def work_dir() -> Path:
    return Path(os.environ.get("FHIR_WORK_DIR", REPO_ROOT / ".work" / "run"))


def landing_blob(run_date: str, rtype: str) -> str:
    return f"{run_date}/{rtype}.ndjson"


def upload_landing(store: BlobStore, local_dir: Path, run_date: str) -> list[str]:
    """Upload generator output to landing/{run_date}/."""
    store.ensure_container(LANDING)
    names = []
    for rtype in RESOURCE_ORDER:
        path = local_dir / f"{rtype}.ndjson"
        if path.exists():
            store.upload_file(LANDING, landing_blob(run_date, rtype), path)
            names.append(landing_blob(run_date, rtype))
    return names


def list_new_blobs(store: BlobStore, run_date: str) -> dict[str, str]:
    """Blobs in landing/{run_date}/ that the warehouse has not loaded yet."""
    store.ensure_container(LANDING)
    found = set(store.list_blobs(LANDING, f"{run_date}/"))
    con = connect()
    try:
        init_schema(con)
        return {
            rtype: landing_blob(run_date, rtype)
            for rtype in RESOURCE_ORDER
            if landing_blob(run_date, rtype) in found
            and not already_loaded(con, f"{LANDING}/{landing_blob(run_date, rtype)}")
        }
    finally:
        con.close()


def validate_blob(store: BlobStore, run_date: str, rtype: str) -> dict[str, Any]:
    """Download one blob, validate each line, pseudonymize valid rows, write local files."""
    data = store.download_bytes(LANDING, landing_blob(run_date, rtype)).decode("utf-8")
    return validate_text(run_date, rtype, data)


def validate_text(run_date: str, rtype: str, data: str) -> dict[str, Any]:
    """Validate NDJSON text; write valid (pseudonymized) and rejected rows to the work dir."""
    key = load_key()
    out = work_dir() / run_date
    out.mkdir(parents=True, exist_ok=True)
    rows_in = valid = 0
    with (out / f"{rtype}.valid.ndjson").open("w", encoding="utf-8") as ok, \
            (out / f"{rtype}.rejected.jsonl").open("w", encoding="utf-8") as bad:
        for line in data.splitlines():
            if not line.strip():
                continue
            rows_in += 1
            result = validate_line(rtype, line)
            if isinstance(result, Accepted):
                ok.write(json.dumps(pseudonymize(result.resource, key)) + "\n")
                valid += 1
            else:
                bad.write(json.dumps({"reason": result.reason, "raw_line": result.raw_line}) + "\n")
    return {"resource_type": rtype, "rows_in": rows_in, "valid": valid,
            "rejected": rows_in - valid}


def load_blob(run_date: str, rtype: str, rows_in: int) -> dict[str, int]:
    return load_blob_as(run_date, rtype, rows_in, f"{LANDING}/{landing_blob(run_date, rtype)}")


def load_blob_as(run_date: str, rtype: str, rows_in: int, source_blob: str) -> dict[str, int]:
    out = work_dir() / run_date
    resources = [json.loads(x) for x in (out / f"{rtype}.valid.ndjson").read_text().splitlines()]
    rejected = [
        (d["reason"], d["raw_line"])
        for d in map(json.loads, (out / f"{rtype}.rejected.jsonl").read_text().splitlines())
    ]
    con = connect()
    try:
        init_schema(con)
        return load_resources(con, rtype, source_blob, resources, rejected, rows_in)
    finally:
        con.close()


def ingest_dir(local_dir: Path, run_date: str) -> dict[str, dict[str, Any]]:
    """Validate and load NDJSON files from a local folder (no blob storage). Used by tests."""
    report: dict[str, dict[str, Any]] = {}
    for rtype in RESOURCE_ORDER:
        path = local_dir / f"{rtype}.ndjson"
        if not path.exists():
            continue
        stats = validate_text(run_date, rtype, path.read_text(encoding="utf-8"))
        stats["load"] = load_blob_as(run_date, rtype, stats["rows_in"], f"local/{run_date}/{rtype}")
        report[rtype] = stats
    return report


def dbt_command() -> list[str]:
    """Command for dbt. DBT_BIN points to the isolated dbt venv; default is dbt on PATH."""
    binary = os.environ.get("DBT_BIN") or shutil.which("dbt") or "dbt"
    return [binary]


def run_dbt(args: list[str], project: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run dbt in the repo project, or in another project dir (tests copy the project)."""
    project = project or REPO_ROOT / "dbt" / "fhir_analytics"
    env = {**os.environ, "DBT_PROFILES_DIR": str(project)}
    cmd = [*dbt_command(), *args, "--project-dir", str(project), "--profiles-dir", str(project)]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)


def dbt_build() -> dict[str, Any]:
    """Run `dbt build` and return pass/fail counts. Raises if any model or test fails."""
    proc = run_dbt(["build"])
    results = REPO_ROOT / "dbt" / "fhir_analytics" / "target" / "run_results.json"
    counts: dict[str, int] = {}
    if results.exists():
        for r in json.loads(results.read_text())["results"]:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").splitlines()[-30:])
        raise RuntimeError(f"dbt build failed ({counts}):\n{tail}")
    return {"dbt_nodes": counts}


def check_quarantine_rate(loads: list[dict[str, Any]], max_share: float | None = None) -> dict[str, Any]:
    """Quarantine-rate gate. Fails the run when rejected rows pass `max_share` of all input rows.

    Each item in `loads` needs `rows_in` and `rows_quarantined` (missing keys count as 0, so a
    skipped resource adds nothing). The limit comes from FHIR_MAX_QUARANTINE_SHARE (default 0.05).
    """
    if max_share is None:
        max_share = float(os.environ.get(MAX_QUARANTINE_ENV, DEFAULT_MAX_QUARANTINE_SHARE))
    rows_in = sum(int(x.get("rows_in", 0)) for x in loads)
    quarantined = sum(int(x.get("rows_quarantined", 0)) for x in loads)
    share = quarantined / rows_in if rows_in else 0.0
    result = {"rows_in": rows_in, "quarantined": quarantined, "share": round(share, 6),
              "max_share": max_share, "ok": share <= max_share}
    if not result["ok"]:
        raise QuarantineGateError(
            f"quarantine share {share:.4f} is above the limit {max_share:.4f} "
            f"({quarantined} of {rows_in} rows)"
        )
    return result


def dbt_source_freshness() -> dict[str, Any]:
    """Run `dbt source freshness` and return the status of each source table.

    Status values are dbt's: pass, warn, error. An error status is not raised here;
    the caller decides. A failed dbt call (no results file) raises RuntimeError.
    """
    target = REPO_ROOT / "dbt" / "fhir_analytics" / "target" / "sources.json"
    target.unlink(missing_ok=True)
    proc = run_dbt(["source", "freshness"])
    if not target.exists():
        tail = "\n".join((proc.stdout or "").splitlines()[-20:])
        raise RuntimeError(f"dbt source freshness produced no result:\n{tail}")
    results = json.loads(target.read_text())["results"]
    sources = {r["unique_id"].split(".")[-1]: r["status"] for r in results}
    return {"sources": sources, "ok": all(v != "error" for v in sources.values())}


def publish(store: BlobStore, run_date: str, summary: dict[str, Any]) -> list[str]:
    """Export marts to Parquet, upload to curated/{run_date}/, upload the run summary."""
    store.ensure_container(CURATED)
    out = work_dir() / run_date / "curated"
    out.mkdir(parents=True, exist_ok=True)
    names = []
    con = connect()
    try:
        for mart in MARTS:
            if mart not in MARTS:  # allow-list guard for the SQL identifier below
                raise ValueError(f"unknown mart: {mart}")
            path = out / f"{mart}.parquet"
            # mart is checked against the MARTS constant; path is built by this code.
            con.execute(  # nosemgrep: fhir-no-fstring-sql
                f"COPY (SELECT * FROM marts.{mart}) TO '{path}' (FORMAT PARQUET)"  # nosec B608
            )
            blob = f"{run_date}/{mart}.parquet"
            store.upload_file(CURATED, blob, path)
            names.append(blob)
    finally:
        con.close()
    blob = f"{run_date}/run_summary.json"
    store.upload_bytes(CURATED, blob, json.dumps(summary, indent=2).encode())
    names.append(blob)
    return names


_TABLE_RE = re.compile(r"^(raw|marts)\.[a-z_0-9]+$")


def table_count(table: str) -> int:
    if not _TABLE_RE.fullmatch(table):  # allow-list guard for the SQL identifier below
        raise ValueError(f"unsafe table name: {table}")
    con = connect()
    try:
        row = con.execute(  # nosemgrep: fhir-no-fstring-sql
            f"SELECT count(*) FROM {table}"  # nosec B608
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()


def quarantine_count() -> int:
    return table_count("raw.quarantine")


def raw_counts() -> dict[str, int]:
    return {name: table_count(f"raw.{name}") for name in RAW_TABLES.values()}


if __name__ == "__main__":  # tiny manual helper: python -m fhir_pipeline.pipeline <dir> <date>
    store = BlobStore()
    print(upload_landing(store, Path(sys.argv[1]), sys.argv[2]))
