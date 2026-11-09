HIPAA-style control mapping. No compliance claim. No certification. The data is synthetic.

# HIPAA-style control map

This map lists safeguard areas that a health data team usually reviews. Each row names a control theme in plain words, says what this repo does, and points to evidence. The map does not copy legal text. It is not legal advice.

Status values: `built` (works and has a test or output), `partly built`, `not built`, `out of scope`.

## Administrative safeguards

| Safeguard area | Control theme | What this repo does | Evidence | Status |
|---|---|---|---|---|
| Administrative | Risk analysis | Names the main risks in the security notes: re-identification, a leaked key, linking of tokens. No formal risk analysis with owners and dates. | `SECURITY.md`, `docs/engagement/THREAT-MODEL.md`, `docs/engagement/RISK-DECISION.md` | partly built |
| Administrative | Workforce access | The repo has one owner and no user roles. There is no joiner, mover or leaver process. | none | not built |
| Administrative | Access review | No one reviews who can read the data. The warehouse is one local file. | none | not built |
| Administrative | Incident procedures | A runbook lists symptoms and fixes for failed runs. It has no breach or privacy incident steps. | `docs/RUNBOOK.md`, `docs/engagement/RUNBOOK.md` | partly built |
| Administrative | Contingency plan | Raw data is append-only and a day can load again. The runbook explains how to rebuild the incremental table. There is no backup plan for the warehouse file. | `docs/RUNBOOK.md`, `tests/test_dbt_fixture.py` | partly built |
| Administrative | Evaluation | A local security gate runs bandit, semgrep, pip-audit and gitleaks. A CI workflow repeats them. The workflow has not run on GitHub. | `.github/workflows/security.yml`, `docs/engagement/SECURITY-GATE.md`, `docs/engagement/evidence/security-gate-local.txt` | partly built |
| Administrative | Partner agreements | No outside party handles data. No agreements exist. | none | out of scope |

## Physical safeguards

| Safeguard area | Control theme | What this repo does | Evidence | Status |
|---|---|---|---|---|
| Physical | Facility access | The repo has no hosting and no data centre. | none | out of scope |
| Physical | Workstation and device controls | Disk encryption and device rules belong to the host machine. The repo sets none. The DuckDB and Parquet files are not encrypted by the project. | `SECURITY.md` | out of scope |
| Physical | Media disposal | The repo has no disposal step. Work files sit in the `.work` folder and a test or run can delete them. | none | not built |

## Technical safeguards

| Safeguard area | Control theme | What this repo does | Evidence | Status |
|---|---|---|---|---|
| Technical | Access control | The Bicep file gives the pipeline identity two roles: blob data contributor and Key Vault secrets reader. Tests check the compiled template. At run time there is no sign-in and no per-user rule. | `infra/main.bicep`, `test_compiled_arm_policy` | partly built |
| Technical | Audit controls | A load log records each blob that the warehouse loads. Each run also writes a provenance manifest. Nothing records who reads a mart. | `src/fhir_pipeline/warehouse.py`, `src/fhir_pipeline/provenance.py`, `test_manifest_validates_against_schema` | partly built |
| Technical | Integrity | Raw tables are append-only. The manifest holds a SHA-256 for each input blob and for the dbt manifest. dbt contracts fix the mart columns and types. | `docs/DECISIONS.md`, `test_input_hashes_match_content`, `test_contract_break_fails` | built |
| Technical | Transmission security | The Bicep file sets HTTPS only and TLS 1.2 as the minimum. A policy test checks the flags in the compiled template. Local runs use plain HTTP to the emulator. | `infra/main.bicep`, `test_source_policy_flags` | partly built |
| Technical | De-identification style | Direct identifiers are dropped. Birth date becomes birth year. Address becomes state. Ids become tokens. A k-anonymity step (k=5) covers birth year, state and gender before the curated file. | `src/fhir_pipeline/pseudonymize.py`, `test_patient_output_has_no_direct_identifiers`, `test_no_group_under_k_after_enforce` | built |
| Technical | Key management | Tokens carry a key id. A new key gives new tokens. A rotation plan is written. Keys come from the environment. Nothing reads the Key Vault. | `docs/engagement/KEY-ROTATION.md`, `test_token_has_kid_prefix`, `test_old_curated_parquet_still_readable_after_rotation` | partly built |
| Technical | Data quality gates | A quarantine-rate limit stops a run with too many rejected rows. Source freshness checks flag stale tables. | `src/fhir_pipeline/pipeline.py`, `test_gate_raises_over_limit` | built |

## Gaps and next steps

| Gap | Next step |
|---|---|
| No user sign-in and no per-user read rule | Use a managed warehouse with role-based access and tie roles to the Bicep identities |
| No read audit | Turn on access logs in the managed warehouse and keep them |
| Keys live in the environment | Read keys from Key Vault at start-up and rotate on a schedule |
| No re-tokenization job | Build a job inside the trusted zone that maps old tokens to new ones |
| No formal risk analysis | Write one with owners, dates and a review cycle |
| No breach or privacy incident steps | Add steps to the runbook and rehearse them |
| Files at rest are not encrypted by the project | Rely on storage encryption in the target service and check it in a policy test |
| Nothing is deployed | Deploy the template to a test subscription and run the policy tests against it |

## Reading this map

This map shows where the controls of a pipeline sit. It does not show that any rule is met. A real health system needs a formal review by a qualified person.
