# Runbook additions

The base runbook is `docs/RUNBOOK.md`. It covers environment variables, Azurite, a full run and common failures. This file adds the procedures for the new controls.

## The quarantine gate stopped a run

Symptom: the task `quarantine_gate` fails with "quarantine share ... is above the limit".

1. Open the quarantine table: `select reason, count(*) from raw.quarantine group by 1 order by 2 desc`.
2. Find the source change. A new field, a missing field or broken lines show up as one common reason.
3. Ask the source owner to fix the export, or raise the limit for one run with `FHIR_MAX_QUARANTINE_SHARE` if the data is known to be acceptable.
4. Run the day again. Blobs that already loaded are skipped by the load log.

The marts do not change when the gate stops a run.

Known gap: the gate counts only the rows that the current attempt loads. The rows of the stopped day stay in the raw tables, and the load log marks those blobs as loaded. A re-run loads nothing, so the gate passes, and dbt then builds the marts with the good rows of that day. If those rows must not reach the marts, remove them before the re-run (see "Load the same day again" in `docs/RUNBOOK.md`).

## The marts-late alert fired

Symptom: `FhirMartsLate` fires after 06:00 UTC.

1. Check `fhir_run_success`. A value of 0 means a task failed. Read the failed task log.
2. Check the landing blobs for today. If they are missing, the source has not sent them.
3. Fix the cause and run the DAG for today.
4. Note the late day. Two late days in 28 days breach the freshness objective.

## Upgrade: fct_encounters needs one full refresh

The incremental model `fct_encounters` selects new rows by raw load time. It has a new column, `source_loaded_at`, and `on_schema_change='fail'`. A warehouse built before this change stops with a schema-change error. Rebuild the model once:

```
cd dbt/fhir_analytics && DUCKDB_PATH=... ../../.venv-dbt/bin/dbt run --full-refresh --select fct_encounters --profiles-dir .
```

Then run the normal build. A new warehouse does not need this step. Reason: `docs/DECISIONS.md`, entry 6.

## Key rotation

Follow `docs/engagement/KEY-ROTATION.md`. After a rotation, check that new curated files hold `v2.` tokens and old files keep `v1.` tokens.

## k-anonymity suppression spike

Symptom: `suppressed_rows` in `run_summary.json` or `provenance.json` jumps.

1. Read the `kanon` section: `steps_applied`, `suppressed_rows`, `min_group_size`.
2. A small batch or a new rare value (a state or a birth year) causes this. Check the batch size.
3. Do not lower `FHIR_K_ANON` to remove the spike.
4. If the batch is small by nature, publish later with more data.

## Failure lab replays

Run one case or all cases:

```
.venv/bin/python scripts/failure_lab.py --case late-update
.venv/bin/python scripts/failure_lab.py --all
```

The lab starts its own Azurite container and stops it at the end. See `docs/engagement/FAILURE-LAB.md` for what each case shows.
