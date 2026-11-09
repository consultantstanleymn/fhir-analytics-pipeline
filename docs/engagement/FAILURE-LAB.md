# Failure lab

The failure lab injects one fault at a time into a synthetic run and records what the pipeline does. Each case uses its own Azurite container and its own warehouse. All data is synthetic.

Run it from the repo root:

```
.venv/bin/python scripts/failure_lab.py --all
.venv/bin/python scripts/failure_lab.py --case late-update
```

The raw output of the last full run is in `docs/engagement/evidence/failure-lab.txt`. Every case ended with all expectations met. The run is measured on one laptop and does not say how real Azure storage behaves.

| Case | Injection | Expected | Observed | Data effect | Evidence section |
|---|---|---|---|---|---|
| Corrupt blob | 4 of 270 Observation lines cut in half or replaced by binary noise; later, one third of the lines broken | Broken lines go to quarantine. Good lines load. The gate passes at 0.6 percent and stops the run at 13.8 percent. Marts stay as they were after a stopped run | Matches. Quarantine +4. The stopped day wrote nothing to the curated container | Raw text of each bad line is kept in `raw.quarantine` with the reason | `## case: corrupt-blob` |
| Schema drift, new field | An unknown field on 7 of 67 Encounter lines | The strict validator rejects them | The 7 lines went to quarantine with reason "fhir validation: unexpectedNewField". The dbt relationship tests then failed, because Condition and Observation rows point to the missing Encounters. The run stopped before publish | 60 Encounters loaded. Nothing published for the day | `## case: schema-drift-new-field` |
| Schema drift, removed field | The required field `status` removed from 7 of 67 Encounter lines | The lines go to quarantine | 7 of 7 quarantined. Same dbt orphan-reference failure and no publish | Lines wait in quarantine | `## case: schema-drift-removed-field` |
| Late update | A new version of one encounter with a `lastUpdated` older than the table maximum (2026-03-13 against 2026-07-17) | The update is applied. No other row changes | The department changed. One row changed in the mart | One row replaced | `## case: late-update` |
| Azurite down | The emulator is stopped before the publish step. It is then started again | Publish fails with a clear error. The warehouse does not change. A re-run loads nothing twice and publishes | `ServiceRequestError` with "Connection refused". Counts unchanged. The load log reported no new blobs. The re-run published the manifest and the summary | No duplicate rows | `## case: azurite-down` |

## What the lab shows

- The quarantine gate and the dbt contracts and tests make the pipeline fail closed. A bad run does not publish.
- A change in the source that rejects a few parent records (Encounter) stops the whole day, because the child records (Condition, Observation) lose their parent. This is safe but strict. A later change could move the children of a quarantined parent to quarantine too, so that the rest of the day can publish.
- The late-update fix works at pipeline level, through Azurite, and at model level, in the dbt tests.
- The Azurite container is ephemeral. After a restart the lab puts the landing blobs back. So the statement "nothing partial was published" rests on the order of the uploads in `publish` (mart files, then `provenance.json`, then `run_summary.json`) and on the failed first upload. The lab does not stop the emulator in the middle of a file.

## Limits

- The lab uses small data (60 to 100 patients per case).
- The gate share in the drift cases is not printed, because the dbt step failed first.
- Real storage can fail in other ways, such as slow responses and partial uploads. The lab does not test them.
