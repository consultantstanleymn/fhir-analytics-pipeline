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

from . import metrics
from .blob import CURATED, LANDING, BlobStore
from .kanon import enforce_k, get_k
from .provenance import build_manifest, git_sha, sha256_bytes
from .pseudonymize import load_keyring, pseudonymize
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
    raw = store.download_bytes(LANDING, landing_blob(run_date, rtype))
    stats = validate_text(run_date, rtype, raw.decode("utf-8"))
    stats["input_sha256"] = sha256_bytes(raw)  # hash of the blob as stored, for the manifest
    return stats


def validate_text(run_date: str, rtype: str, data: str) -> dict[str, Any]:
    """Validate NDJSON text; write valid (pseudonymized) and rejected rows to the work dir."""
    keyring = load_keyring()
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
                ok.write(json.dumps(pseudonymize(result.resource, keyring)) + "\n")
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


def _safe_metric(fn: Any, *args: Any) -> None:
    """Metrics never stop a run. A write error (disk, permission) is ignored."""
    try:
        fn(*args)
    except (OSError, ValueError):
        pass


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
    _safe_metric(metrics.record_quarantine_share, share)
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


STAGING_MODELS = ["stg_patient", "stg_encounter", "stg_condition", "stg_observation"]
DBT_MANIFEST = REPO_ROOT / "dbt" / "fhir_analytics" / "target" / "manifest.json"


def export_dim_patient_k(con: Any, path: Path, k: int) -> dict[str, Any]:
    """Write dim_patient to Parquet after k-anonymity. Return the k-anonymity report.

    Groups under k are generalized or suppressed (see `fhir_pipeline.kanon`). No row in a group
    under k reaches the file. If birth year was generalized, that column is text in the file.
    """
    cur = con.execute("SELECT * FROM marts.dim_patient")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    out_rows, report = enforce_k(rows, k)
    types = {"birth_year": "VARCHAR" if "birth_decade" in report["steps_applied"] else "INTEGER",
             "birth_decade": "DOUBLE"}
    ddl = ", ".join(f"{c} {types.get(c, 'VARCHAR')}" for c in cols)
    con.execute("DROP TABLE IF EXISTS _dim_patient_k")
    con.execute(f"CREATE TEMP TABLE _dim_patient_k ({ddl})")  # nosec B608  # nosemgrep: fhir-no-fstring-sql
    marks = ", ".join("?" for _ in cols)
    if out_rows:  # DuckDB rejects an empty parameter list
        con.executemany(
            f"INSERT INTO _dim_patient_k VALUES ({marks})",  # nosec B608
            [[r[c] for c in cols] for r in out_rows],
        )
    con.execute(f"COPY (SELECT * FROM _dim_patient_k) TO '{path}' (FORMAT PARQUET)")  # nosec B608  # nosemgrep: fhir-no-fstring-sql
    con.execute("DROP TABLE _dim_patient_k")
    return report


def export_prevalence_small_cell(con: Any, path: Path, k: int) -> int:
    """Write mart_condition_prevalence with small cells hidden. Return the number of hidden rows.

    A row with fewer than k patients gets NULL counts and rates, and `suppressed` is true.
    """
    k = int(k)  # k is a number here, so it is safe to put in the SQL text
    sql = (
        "SELECT condition_code, condition_display, "
        f"CASE WHEN patients_with_condition < {k} THEN NULL ELSE patients_with_condition END "
        "AS patients_with_condition, total_patients, "
        f"CASE WHEN patients_with_condition < {k} THEN NULL ELSE prevalence END AS prevalence, "
        f"patients_with_condition < {k} AS suppressed "
        "FROM marts.mart_condition_prevalence"
    )
    con.execute(f"COPY ({sql}) TO '{path}' (FORMAT PARQUET)")  # nosec B608  # nosemgrep: fhir-no-fstring-sql
    row = con.execute(  # nosec B608  # nosemgrep: fhir-no-fstring-sql
        f"SELECT count(*) FROM marts.mart_condition_prevalence WHERE patients_with_condition < {k}"
    ).fetchone()
    return int(row[0]) if row else 0


def layer_counts() -> dict[str, dict[str, int]]:
    """Row counts per layer: raw tables, staging views and marts."""
    return {
        "raw": raw_counts(),
        "staging": {m: table_count(f"staging.{m}") for m in STAGING_MODELS},
        "marts": {m: table_count(f"marts.{m}") for m in MARTS},
    }


RAW_RESOURCE = {"raw_patient": "Patient", "raw_encounter": "Encounter",
                "raw_condition": "Condition", "raw_observation": "Observation"}
STAGING_RESOURCE = {"stg_patient": "Patient", "stg_encounter": "Encounter",
                    "stg_condition": "Condition", "stg_observation": "Observation"}


def _record_publish_metrics(counts: dict[str, dict[str, int]]) -> None:
    """Row counts per layer, publish time and success flag. Writes the textfile."""
    for table, n in counts["raw"].items():
        if table in RAW_RESOURCE:
            _safe_metric(metrics.record_rows, "raw", RAW_RESOURCE[table], n)
    for table, n in counts["staging"].items():
        if table in STAGING_RESOURCE:
            _safe_metric(metrics.record_rows, "staging", STAGING_RESOURCE[table], n)
    _safe_metric(metrics.record_rows, "marts", "all", sum(counts["marts"].values()))
    _safe_metric(metrics.mark_published)
    _safe_metric(metrics.set_run_success, True)
    _safe_metric(metrics.write)


def publish(
    store: BlobStore,
    run_date: str,
    summary: dict[str, Any],
    inputs: dict[str, str] | None = None,
) -> list[str]:
    """Export marts to Parquet, upload to curated/{run_date}/, upload manifest and run summary.

    `inputs` maps each landing blob name to its SHA-256, captured when the blob was validated.
    """
    store.ensure_container(CURATED)
    out = work_dir() / run_date / "curated"
    out.mkdir(parents=True, exist_ok=True)
    names = []
    k = get_k()
    kanon_report: dict[str, Any] = {}
    con = connect()
    try:
        for mart in MARTS:
            if mart not in MARTS:  # allow-list guard for the SQL identifier below
                raise ValueError(f"unknown mart: {mart}")
            path = out / f"{mart}.parquet"
            if mart == "dim_patient":
                kanon_report = export_dim_patient_k(con, path, k)
            elif mart == "mart_condition_prevalence":
                kanon_report["small_cell_suppressed"] = {
                    mart: export_prevalence_small_cell(con, path, k)
                }
            else:
                # mart is checked against the MARTS constant; path is built by this code.
                con.execute(  # nosemgrep: fhir-no-fstring-sql
                    f"COPY (SELECT * FROM marts.{mart}) TO '{path}' (FORMAT PARQUET)"  # nosec B608
                )
            blob = f"{run_date}/{mart}.parquet"
            store.upload_file(CURATED, blob, path)
            names.append(blob)
    finally:
        con.close()
    manifest = build_manifest(
        run_date, dict(inputs or {}), git_sha(), DBT_MANIFEST, layer_counts(), kanon_report
    )
    blob = f"{run_date}/provenance.json"
    store.upload_bytes(CURATED, blob, json.dumps(manifest, indent=2).encode())
    names.append(blob)
    summary["provenance"] = blob
    summary["kanon"] = kanon_report
    _record_publish_metrics(manifest["row_counts"])
    blob = f"{run_date}/run_summary.json"
    store.upload_bytes(CURATED, blob, json.dumps(summary, indent=2).encode())
    names.append(blob)
    return names


_TABLE_RE = re.compile(r"^(raw|staging|marts)\.[a-z_0-9]+$")


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
