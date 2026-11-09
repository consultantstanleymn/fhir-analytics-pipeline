"""DuckDB raw layer: schema, quarantine, load. The dbt project reads these tables."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

DB_ENV = "DUCKDB_PATH"
RAW_TABLES = {
    "Patient": "raw_patient",
    "Encounter": "raw_encounter",
    "Condition": "raw_condition",
    "Observation": "raw_observation",
}


def db_path() -> Path:
    value = os.environ.get(DB_ENV)
    if not value:
        raise RuntimeError(f"{DB_ENV} is not set.")
    return Path(value)


def connect(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(target))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    for table in RAW_TABLES.values():  # table names come from the fixed RAW_TABLES map
        con.execute(  # nosemgrep: fhir-no-fstring-sql
            f"""CREATE TABLE IF NOT EXISTS raw.{table} (
                resource_id VARCHAR,
                last_updated VARCHAR,
                resource JSON,
                _loaded_at TIMESTAMP,
                _source_blob VARCHAR)"""
        )
    con.execute(
        """CREATE TABLE IF NOT EXISTS raw.quarantine (
            resource_type VARCHAR,
            reason VARCHAR,
            raw_line VARCHAR,
            _loaded_at TIMESTAMP,
            _source_blob VARCHAR)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS raw.load_log (
            source_blob VARCHAR PRIMARY KEY,
            resource_type VARCHAR,
            rows_in INTEGER,
            rows_loaded INTEGER,
            rows_quarantined INTEGER,
            loaded_at TIMESTAMP)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS raw.gate_hold (
            run_date VARCHAR PRIMARY KEY,
            share DOUBLE,
            tripped_at TIMESTAMP,
            released_at TIMESTAMP)"""
    )


def already_loaded(con: duckdb.DuckDBPyConnection, source_blob: str) -> bool:
    row = con.execute(
        "SELECT count(*) FROM raw.load_log WHERE source_blob = ?", [source_blob]
    ).fetchone()
    return bool(row and row[0])


def stored_run_totals(con: duckdb.DuckDBPyConnection, run_date: str) -> tuple[int, int]:
    """Return (rows_in, rows_quarantined) from the load log for all blobs of one run date."""
    row = con.execute(
        "SELECT coalesce(sum(rows_in), 0), coalesce(sum(rows_quarantined), 0) "
        "FROM raw.load_log WHERE source_blob LIKE ?",
        [f"%/{run_date}/%"],
    ).fetchone()
    return (int(row[0]), int(row[1])) if row else (0, 0)


def hold_state(con: duckdb.DuckDBPyConnection, run_date: str) -> str | None:
    """Return None (no hold), 'held' or 'released' for one run date."""
    row = con.execute(
        "SELECT released_at IS NOT NULL FROM raw.gate_hold WHERE run_date = ?", [run_date]
    ).fetchone()
    if row is None:
        return None
    return "released" if row[0] else "held"


def record_hold(con: duckdb.DuckDBPyConnection, run_date: str, share: float) -> None:
    """Record a tripped gate. A released hold stays released."""
    if hold_state(con, run_date) is None:
        con.execute(
            "INSERT INTO raw.gate_hold VALUES (?, ?, ?, NULL)",
            [run_date, share, datetime.now(UTC).replace(tzinfo=None)],
        )


def release_hold(con: duckdb.DuckDBPyConnection, run_date: str) -> bool:
    """Release the hold on purpose. Return False when the run date has no open hold."""
    if hold_state(con, run_date) != "held":
        return False
    con.execute(
        "UPDATE raw.gate_hold SET released_at = ? WHERE run_date = ?",
        [datetime.now(UTC).replace(tzinfo=None), run_date],
    )
    return True


def load_resources(
    con: duckdb.DuckDBPyConnection,
    resource_type: str,
    source_blob: str,
    resources: Iterable[dict[str, Any]],
    quarantined: Iterable[tuple[str, str]],
    rows_in: int,
) -> dict[str, int]:
    """Append resources and quarantine rows in one transaction. Skips a blob loaded before."""
    from .pseudonymize import resource_key  # local import keeps the module graph small

    if already_loaded(con, source_blob):
        return {"rows_in": 0, "rows_loaded": 0, "rows_quarantined": 0, "skipped": 1}
    now = datetime.now(UTC).replace(tzinfo=None)
    good = [
        (resource_key(r), (r.get("meta") or {}).get("lastUpdated"), json.dumps(r), now, source_blob)
        for r in resources
    ]
    bad = [(resource_type, reason, line, now, source_blob) for reason, line in quarantined]
    table = RAW_TABLES[resource_type]
    con.execute("BEGIN")
    try:
        if good:
            # Table name comes from the fixed RAW_TABLES map above, never from input.
            con.executemany(  # nosemgrep: fhir-no-fstring-sql
                f"INSERT INTO raw.{table} VALUES (?, ?, ?, ?, ?)", good  # nosec B608
            )
        if bad:
            con.executemany("INSERT INTO raw.quarantine VALUES (?, ?, ?, ?, ?)", bad)
        con.execute(
            "INSERT INTO raw.load_log VALUES (?, ?, ?, ?, ?, ?)",
            [source_blob, resource_type, rows_in, len(good), len(bad), now],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"rows_in": rows_in, "rows_loaded": len(good), "rows_quarantined": len(bad),
            "skipped": 0}
