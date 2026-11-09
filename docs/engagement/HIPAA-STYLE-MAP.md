HIPAA-style control mapping. No compliance claim. No certification. The data is synthetic.

# HIPAA-style control map

This map lists safeguard areas that a health data team usually reviews. Each row names a control theme in plain words, says what this repo does, and points to evidence. The map does not copy legal text. It is not legal advice.

Status values: `built` (works and has a test or output), `partly built`, `not built`, `out of scope`.

## Administrative safeguards

| Safeguard area | Control theme | What this repo does | Evidence | Status |
|---|---|---|---|---|
| Administrative | Risk analysis | Names the main risks in the security notes: re-identification, a leaked key, linking of tokens. No formal risk analysis with owners and dates. | `SECURITY.md`, `docs/DECISIONS.md` | partly built |
| Administrative | Workforce access | The repo has one owner and no user roles. There is no joiner, mover or leaver process. | none | not built |
| Administrative | Access review | No one reviews who can read the data. The warehouse is one local file. | none | not built |
| Administrative | Incident procedures | A runbook lists symptoms and fixes for failed runs. It has no breach or privacy incident steps. | `docs/RUNBOOK.md` | partly built |
| Administrative | Contingency plan | Raw data is append-only and a day can load again. The runbook explains how to rebuild the incremental table. There is no backup plan for the warehouse file. | `docs/RUNBOOK.md`, `tests/test_dbt_fixture.py` | partly built |
| Administrative | Evaluation | A local security gate runs bandit, semgrep, pip-audit and gitleaks. A CI workflow repeats them. The workflow has not run on GitHub. | `.github/workflows/security.yml`, `docs/engagement/SECURITY-GATE.md`, `docs/engagement/evidence/security-gate-local.txt` | partly built |
| Administrative | Partner agreements | No outside party handles data. No agreements exist. | none | out of scope |

## Physical safeguards

| Safeguard area | Control theme | What this repo does | Evidence | Status |
|---|---|---|---|---|
| Physical | Facility access | The repo has no hosting and no data centre. | none | out of scope |
| Physical | Workstation and device controls | Disk encryption and device rules belong to the host machine. The repo sets none. The DuckDB and Parquet files are not encrypted by the project. | `SECURITY.md` | out of scope |
| Physical | Media disposal | The repo has no disposal step. Work files sit in the `.work` folder and a test or run can delete them. | none | not built |
