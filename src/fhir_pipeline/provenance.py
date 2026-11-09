"""Provenance manifest: what went into a run and what came out.

The manifest lists the input blobs with SHA-256, the code SHA, the dbt manifest hash
and the row counts per layer. It is JSON and follows `provenance.schema.json`.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("provenance.schema.json")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_sha() -> str:
    """Code SHA: GIT_SHA env first, then `git rev-parse HEAD`, else "unknown"."""
    env = os.environ.get("GIT_SHA")
    if env:
        return env
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parent,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return proc.stdout.strip() or "unknown"


def dbt_manifest_hash(path: Path) -> str:
    """SHA-256 of target/manifest.json. A missing file is an error, not an empty hash."""
    if not path.exists():
        raise FileNotFoundError(f"dbt manifest not found: {path}")
    return sha256_bytes(path.read_bytes())


def build_manifest(
    run_date: str,
    inputs: dict[str, bytes | str],
    code_sha: str,
    dbt_manifest_path: Path,
    counts: dict[str, dict[str, int]],
    kanon: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the manifest dict.

    `inputs` maps blob name to its bytes or to a ready SHA-256 hex string.
    `counts` has the layers `raw`, `staging` and `marts`, each a map of name to row count.
    """
    manifest: dict[str, Any] = {
        "run_date": run_date,
        "code_sha": code_sha,
        "inputs": [
            {"blob": name, "sha256": sha256_bytes(v) if isinstance(v, bytes) else v}
            for name, v in sorted(inputs.items())
        ],
        "dbt_manifest_sha256": dbt_manifest_hash(dbt_manifest_path),
        "row_counts": {
            "raw": counts.get("raw", {}),
            "staging": counts.get("staging", {}),
            "marts": counts.get("marts", {}),
        },
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if kanon is not None:
        manifest["kanon"] = kanon
    return manifest


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
