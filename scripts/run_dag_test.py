"""Generate synthetic data, upload to Azurite, run the DAG with dag.test(), print a JSON report.

Needs: AZURE_STORAGE_CONNECTION_STRING (Azurite), DBT_BIN (dbt venv), FHIR_HMAC_KEY.
Usage: python scripts/run_dag_test.py --patients 1000 --run-date 2026-11-07 --workdir .work/e2e
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--run-date", default="2026-11-07")
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    work = args.workdir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    os.environ["AIRFLOW_HOME"] = str(work / "airflow_home")
    os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"
    os.environ["AIRFLOW__CORE__DAGS_FOLDER"] = str(REPO / "dags")
    os.environ["DUCKDB_PATH"] = str(work / "warehouse.duckdb")
    os.environ["FHIR_WORK_DIR"] = str(work / "run")
    os.environ.setdefault("FHIR_HMAC_KEY", "local-demo-key-not-a-secret")

    import subprocess

    subprocess.run([sys.executable, "-m", "airflow", "db", "migrate"], check=True,
                   capture_output=True)

    from generator.generate_fhir import generate, write_bundle

    from fhir_pipeline.blob import CURATED, BlobStore
    from fhir_pipeline.pipeline import upload_landing

    t0 = time.perf_counter()
    bundle = generate(args.patients, args.seed)
    write_bundle(bundle, work / "gen")
    gen_s = time.perf_counter() - t0
    store = BlobStore()
    t1 = time.perf_counter()
    upload_landing(store, work / "gen", args.run_date)
    upload_s = time.perf_counter() - t1

    sys.path.insert(0, str(REPO / "dags"))
    from fhir_daily import dag  # noqa: E402

    t2 = time.perf_counter()
    dag.test(run_conf={"run_date": args.run_date})
    dag_s = time.perf_counter() - t2

    summary = json.loads(store.download_bytes(CURATED, f"{args.run_date}/run_summary.json"))
    run_results = REPO / "dbt" / "fhir_analytics" / "target" / "run_results.json"
    dbt_s = json.loads(run_results.read_text())["elapsed_time"] if run_results.exists() else None
    report = {
        "patients": args.patients,
        "resources_generated": sum(bundle.counts.values()),
        "generate_seconds": round(gen_s, 1),
        "upload_seconds": round(upload_s, 1),
        "dag_seconds": round(dag_s, 1),
        "dbt_build_seconds": round(dbt_s, 1) if dbt_s is not None else None,
        "curated_blobs": store.list_blobs(CURATED, f"{args.run_date}/"),
        "summary": summary,
    }
    print("REPORT_JSON=" + json.dumps(report))


if __name__ == "__main__":
    main()
