# Review guide (60 minutes)

This guide walks a reviewer through the engagement. The customer is fictional (RegionalHealthCo). All data is synthetic. Numbers are measured on one laptop.

## 1. Pitch (5 minutes)

RegionalHealthCo is a three-hospital system. Its quality office wants readmission and length-of-stay marts by 06:00 each day. Its privacy officer asks: can anyone re-identify a patient from the marts, and who can read them?

The pipeline reads synthetic FHIR files, validates each line, replaces identifiers with versioned tokens, builds dbt marts with enforced contracts, and publishes k-anonymous Parquet files with a provenance manifest. Gates stop a bad run. A freshness alert watches the 06:00 goal. A failure lab shows what happens when input or storage breaks.

What it does not do: it makes no compliance claim, it holds no real data, and nothing is deployed to a cloud.

## 2. Demo steps (25 minutes)

Run all commands from the repo root.

| Step | Command | What to see |
|---|---|---|
| 1. Fast checks | `.venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/python -m pytest -q -m "not airflow and not dbt and not bicep and not azurite"` | All pass |
| 2. Contracts and gate | `.venv/bin/python -m pytest tests/test_contracts_gate.py -v` | A broken column type fails the build. The gate raises over the limit |
| 3. One full run | `eval "$(scripts/azurite.sh start)"` then `DBT_BIN=$PWD/.venv-dbt/bin/dbt FHIR_HMAC_KEY=demo .venv/bin/python scripts/run_dag_test.py --patients 1000 --run-date 2026-02-02 --workdir .work/demo` | A JSON report with the summary, the manifest and the k-anonymity report |
| 4. Provenance | open `docs/engagement/evidence/provenance-manifest-sample.json` | Input hashes, code SHA, dbt manifest hash, row counts |
| 5. k-anonymity | `.venv/bin/python -m pytest tests/test_kanon.py -q` and `docs/engagement/evidence/kanon-report.txt` | No group under k=5 in the curated file |
| 6. Key rotation | `.venv/bin/python -m pytest tests/test_key_versions.py -q` | Tokens carry `v1.` or `v2.`. Old files stay readable |
| 7. Freshness alert | `podman run --rm -v "$PWD/observability/rules:/r:ro,z" --entrypoint promtool docker.io/prom/prometheus:v2.55.1 test rules /r/freshness.rules.test.yml` | SUCCESS |
| 8. Failure lab | `.venv/bin/python scripts/failure_lab.py --case late-update` | Before and after rows, expectations PASS |
| 9. Security gate | commands in `docs/engagement/SECURITY-GATE.md` | bandit, semgrep, pip-audit, gitleaks pass |
| 10. Control map | `.venv/bin/python scripts/check_map_links.py docs/engagement/HIPAA-STYLE-MAP.md` | links ok |

Stop Azurite when done: `scripts/azurite.sh stop`.

## 3. Likely questions (20 minutes)

| # | Question | Short answer | Where |
|---|---|---|---|
| 1 | Can anyone re-identify a patient from the marts? | Risk is lower, not zero. Direct identifiers are gone, and birth year, state and gender go through k=5 before the curated file. Encounter marts keep exact dates | `src/fhir_pipeline/kanon.py`, `docs/engagement/THREAT-MODEL.md` |
| 2 | Who can read the marts? | Today, anyone with access to the files. The Bicep file describes roles. There is no read audit. This is an accepted risk with a review date | `docs/engagement/RISK-DECISION.md` |
| 3 | Why k=5? | A common starting value. It is set by `FHIR_K_ANON`. A real value needs a privacy review | `docs/DECISIONS.md` entry 13 |
| 4 | What happens when a group is under k? | Birth year becomes a decade, then state becomes a region, then the remaining rows are dropped from the curated file only | `tests/test_kanon.py` |
| 5 | Why only one mart has a small-cell rule? | Only the prevalence mart counts patients per group. The others count encounters | `docs/DECISIONS.md` entry 13 |
| 6 | How do you prove which input made a mart? | The manifest holds SHA-256 of each landing blob, the code SHA and the dbt manifest hash | `src/fhir_pipeline/provenance.py` |
| 7 | Can someone edit the manifest? | Yes, with write access. It has no signature. This is listed as a gap | `docs/engagement/THREAT-MODEL.md` |
| 8 | What does a contract do? | It fixes column names and types on each mart. A change fails the build | `tests/test_contracts_gate.py` |
| 9 | What stops a bad input file? | Per-line validation, the quarantine-rate gate (5 percent by default) and dbt contracts | `src/fhir_pipeline/pipeline.py` |
| 10 | Why a load-time filter for the incremental model? | A late update with an old `lastUpdated` was skipped. The load time catches it and leaves unchanged rows alone | `docs/DECISIONS.md` entry 6 |
| 11 | What does key rotation change? | New tokens get a new key id. Old files keep their tokens. Joins across versions need a re-tokenization job that is not built | `docs/engagement/KEY-ROTATION.md` |
| 12 | Why is the SLO 96.4 percent and not 99? | 99 percent over 28 days allows no late day, which a daily batch cannot meet. 96.4 percent allows one | `docs/engagement/OBSERVABILITY.md` |
| 13 | Is the Grafana panel tested? | No. The JSON is checked for structure. It was not loaded into Grafana | `docs/engagement/OBSERVABILITY.md` |
| 14 | What does Azurite down do? | Publish fails with a clear error. A re-run loads nothing twice | `docs/engagement/FAILURE-LAB.md` |
| 15 | Is this HIPAA compliant? | No. The map lists controls with status and gaps. It makes no compliance claim | `docs/engagement/HIPAA-STYLE-MAP.md` |
| 16 | Did the CI jobs run on GitHub? | The new security jobs were not run or checked there. They are linted with actionlint. The local commands ran | `docs/engagement/SECURITY-GATE.md` |
| 17 | What if the key leaks? | Set a new active key, remove the old one, rebuild from the landing blobs, replace curated files | `docs/engagement/KEY-ROTATION.md` |
| 18 | How big is the data? | 1,000 synthetic patients and 6,038 resources in the main test run. This says nothing about production size | `docs/PERF.md` |
| 19 | What would you change first for real data? | A managed warehouse with access logs and roles, keys in a vault, a signed manifest, a privacy review of k | `docs/engagement/RISK-DECISION.md` |
| 20 | How do the tests avoid fake passes? | Each control has a test that fails when the control is removed. Example: the contract-break test changes a type and expects a failure | `tests/` |

## 4. Remaining risks

- No per-user read audit and no sign-in at run time.
- Keys come from the environment, not from a vault.
- The manifest has no signature.
- k-anonymity covers three fields. Exact dates in encounter marts can still help an attacker.
- The Grafana dashboard and the alert routing were not run.
- The new CI jobs were not run on GitHub.
- Nothing is deployed to a cloud.
