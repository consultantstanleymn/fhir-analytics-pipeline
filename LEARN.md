# LEARN: how this project works, in plain language

This file is for the owner. After you read it, you can explain every part in an interview. It uses short sentences on purpose.

## 1. The story in one minute

A hospital network sends clinical data as FHIR files. Each line in a file is one record. Records can be broken, repeated or out of date.

This pipeline does six jobs:
1. It takes the files from blob storage (an Azure Blob container; here the Azurite emulator).
2. It checks every record. Bad records go to a quarantine table with a reason.
3. It replaces patient identifiers with tokens and removes names and addresses.
4. It loads the good records into DuckDB (a small database in one file).
5. It uses dbt to turn raw JSON into clean tables and answers: encounters per department per week, 30-day readmission rate, length of stay, condition prevalence.
6. It writes the answers as Parquet files back to blob storage. Airflow runs steps 1 to 6 in order.

Everything is synthetic. A script I wrote makes the data. It is not Synthea. It is not real patient data.

## 2. Words you must know

**FHIR.** A standard for health data. The name means Fast Healthcare Interoperability Resources. This project uses release R4 (more exactly the R4B models, version 4.3.0). Do not say "HL7" alone. HL7 v2 is an older, different standard. This project does not use it.

**Resource.** One FHIR record type. We use four:
- Patient: who the person is.
- Encounter: one visit or stay. It points to a Patient with `subject.reference = "Patient/<id>"`.
- Condition: a diagnosis, for example heart failure. It points to a Patient and an Encounter.
- Observation: a measurement, for example heart rate. It points to a Patient and an Encounter.

**Bulk export, NDJSON.** FHIR servers can export all data as files. NDJSON means one JSON object per line. We get one file per resource type. This is easy to stream and easy to break: one bad line does not stop the file.

**`meta.lastUpdated`.** A time stamp on each resource. A newer version of the same id means an update. We use it to pick the latest version and for incremental loading.

**Pseudonymization.** We replace an identifier with a token. We use HMAC-SHA256 with a secret key. The same patient always gets the same token, so we can still join tables. Without the key you can not reverse the token or guess it for a known id. It is not the same as full anonymization. See section 7.

**Azurite.** A free emulator for Azure Blob Storage. It runs in a container on your laptop. The same Python SDK code works on it and on real Azure. We never touch real Azure here.

**Bicep.** Microsoft's language to describe Azure resources as code. `infra/main.bicep` describes a storage account, two containers, a Key Vault, an identity and role assignments. CI compiles it to ARM JSON and lints it. We never deploy it. This is why the claim is "Bicep validated in CI" and not "deployed to Azure".

**DuckDB.** A database in one file, made for analytics. It stands in for a cloud warehouse. It has one writer at a time.

**dbt.** A tool that runs SQL models in order and tests them. Each model is a SELECT statement in a file. dbt works out the order from `ref()` calls.

**Airflow.** A scheduler that runs tasks in a graph (a DAG). Our DAG is `fhir_daily`.

## 3. The layers in dbt, and why

- **raw** (not dbt, loaded by Python): the JSON as it arrived (after validation and pseudonymization). Append-only. Has `_loaded_at` and `_source_blob`.
- **staging** (`stg_*`): one model per resource. Picks the newest version of each id. Flattens JSON into typed columns. No business rules here.
- **intermediate** (`int_*`): joins and derived fields. `int_encounters_enriched` adds length of stay, flags and patient attributes. `int_index_stays` marks readmissions.
- **marts**: tables for people to use. Facts and dimensions: `fct_encounters`, `dim_patient`, `dim_department`. Metrics: `mart_readmissions_30d`, `mart_los`, `mart_encounters_weekly`, `mart_condition_prevalence`.

Why separate layers? Each layer has one job. If a source field changes, you fix staging only. If a metric definition changes, you fix one mart only. Tests sit at each layer.

## 4. How the incremental model works

`fct_encounters` is `incremental`. On the first run it builds the whole table. On later runs dbt adds a filter:

```sql
where e.last_updated > (select max(last_updated) from <this table>)
```

So dbt reads only encounters newer than the newest row already stored. The strategy is `delete+insert` on `encounter_id`. dbt deletes rows with the same id, then inserts the new version. Rows that did not change are not touched. The test proves it. It adds a batch with one updated encounter and one new encounter. Only those two rows get a new `dbt_loaded_at` value.

The gap, which you must say out loud: an update with an older `lastUpdated` than the maximum would be skipped. A production design adds a lookback window.

## 5. The readmission metric

- **Index stay:** an inpatient stay that has ended, where the patient did not die.
- **Readmitted:** the same patient starts another inpatient stay on or after the index discharge, within 30 days. Exactly 30 days counts.
- **Rate:** readmissions divided by index stays.

Check with the hand-written fixture (12 encounters, 9 index stays, 3 readmissions):
- E1 to E2: 15 days, counts.
- E5 to E6: exactly 30 days, counts.
- E7 to E8: 1 day, counts.
- E3 to E4: 44 days, does not count.
- E10 died, E11 has no discharge yet: both are not index stays.
- E12 is an outpatient visit: not an index stay and never a readmission.

Not covered: planned readmissions, transfers, observation stays. Real quality measures (for example the CMS ones) are more detailed than this.

## 6. Walk through one run

1. `scripts/run_dag_test.py` makes data with `generator/generate_fhir.py` and uploads it to `landing/<date>/`.
2. DAG task `list_new_blobs` lists the folder and removes blobs already in `raw.load_log`.
3. For each resource type (in order), task `validate` downloads the file. For each line it:
   - parses JSON (bad JSON is rejected);
   - checks the FHIR model (`fhir.resources`);
   - checks required code values and two business rules;
   - pseudonymizes good lines and writes them to a local file; rejected lines go to a second file with the reason.
4. Task `load` appends good lines to `raw.raw_*` and rejected lines to `raw.quarantine`, and writes a row to `raw.load_log`. All in one transaction.
5. Task `dbt_build_task` runs `dbt build`: models plus 41 data tests plus 2 unit tests (56 nodes in total). It stops the run if anything fails.
6. Task `publish_task` copies each mart to Parquet, uploads to `curated/<date>/`, and uploads `run_summary.json` (rows in, loaded, quarantined, dbt results).

## 7. What the generator puts in on purpose

- Optional fields missing (some encounters have no department; some observations have no value). This is valid FHIR.
- Exact duplicate lines.
- Late updates: the same id with a later `lastUpdated`, written at the start of the file, so the older copy comes after it.
- Broken records: wrong status code, bad date, wrong type, no patient reference, a cut-off JSON line.

These make the quarantine table and the "latest version" logic real, not just claimed.

## 8. Things I found while building (good interview stories)

- `fhir.resources` accepted `status: "not-a-status"`. It checks shape, not code lists. I added a small check for the required bindings. Lesson: a library check is not a full validation.
- Airflow 3.4.0 and dbt-core could not be installed in one environment with Airflow's constraints. I split them and call dbt as a subprocess.
- `az bicep lint` printed nothing and exited 0, even for a warning. The Bicep CLI itself prints the warning. My check script runs both and fails on any output.
- A seeded generator must draw the same random numbers in every mode. In my first version a "skip this value" branch skipped a random draw, so two runs with the same seed gave different base data. I fixed it and added a test.

## 9. What is simplified (be honest about all of these)

- Data is synthetic from my own generator. Not Synthea. Not real.
- Four resource types only. No FHIR server, no SMART on FHIR, no HL7 v2, no EHR vendor integration.
- Validation uses R4B models plus a short table of bindings. It does not use FHIR profiles (for example US Core) and does not check terminology (SNOMED, LOINC) against servers.
- Pseudonymization is a design demo. Not a HIPAA claim. Birth year and state can still help re-identify people in a small group. The key is an environment variable, not a vault.
- DuckDB stands in for a cloud warehouse. I do not claim Snowflake, BigQuery or Databricks.
- Azure is used through the Blob SDK on the Azurite emulator, and through Bicep that is compiled and linted in CI. Nothing is deployed. No Data Factory, Synapse, AKS or any live Azure service.
- Airflow runs on one machine. `dag.test()` runs the tasks in one process. I did not run a scheduler, a web server or a multi-worker setup.
- The incremental model has the late-update gap from section 4.
- The readmission rule is a simple version, see section 5.
- The run summary and quarantine table are basic. There is no alerting.

## 10. Interview notes

**Q: What is a FHIR resource and what is a bulk export?**
A resource is one typed record, like Patient or Encounter, as JSON. A bulk export is NDJSON files, one per type. An Encounter points to its Patient through `subject.reference`.

**Q: Why staging, intermediate and marts?**
One job per layer. Staging cleans one source. Intermediate joins and derives. Marts serve users. A change stays local, and tests sit at each layer.

**Q: How does the incremental model choose rows?**
It filters on `last_updated` greater than the maximum already in the table, and replaces rows by `encounter_id`. State the late-update gap.

**Q: How is readmission defined?**
Index stay, 30-day window, exclusions: died, not yet discharged, not inpatient. Give the 3 of 9 fixture.

**Q: How do you handle bad data?**
Validate each line. Quarantine with a reason. Keep the pipeline running. Count quarantined rows in the run summary. Staging dedups duplicates and late updates.

**Q: How do you protect patient identity?**
HMAC tokens with a key from the environment. Drop names, addresses, phones, free text. Reduce birth date and address. Say clearly: demo, not HIPAA compliance.

**Q: What is Azurite and why is Bicep not deployed?**
Azurite is the Azure Storage emulator. The SDK code is the same as for real Azure. Bicep is checked in CI (compile, lint, policy test on the ARM JSON) because there is no paid subscription and no live deploy in this project.

**Q: Why two virtual environments?**
Dependency conflict between Airflow with its constraints and dbt-core. Common fix: isolate dbt and call it as a command.

**Q: Why not run the validators in parallel?**
They can run in parallel. The loads can not, because DuckDB has one writer. The DAG keeps it simple and runs the groups in order.

**Q: How do you know the tests can fail?**
I changed the 30-day boundary in the SQL during the build and watched the unit test and the pytest fixture fail (see `docs/DEMO.md`). I also flipped a Bicep flag and watched the policy test fail.

## 11. Commands to remember

```bash
eval "$(scripts/azurite.sh start)"
.venv/bin/python scripts/run_dag_test.py --patients 1000 --workdir .work/demo
.venv/bin/pytest -q
cd dbt/fhir_analytics && ../../.venv-dbt/bin/dbt build --profiles-dir .
scripts/bicep_check.sh
```
