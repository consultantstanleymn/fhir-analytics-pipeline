# Acceptance criteria

This table is written before the code. The customer is fictional and the data is synthetic. See `docs/engagement/SCENARIO.md`.

Status values: `not started`, `met locally`, `authored, not run`, `not met`.

A proof command is the command that the reviewer runs. An evidence file holds the raw output. The evidence files are created by the packets that meet each criterion.

| ID | Criterion | Measurable check | Proof command | Evidence file | Status |
|---|---|---|---|---|---|
| F-1 | dbt model contracts on all marts (enforced names and types), source freshness checks, and a quarantine-rate gate: the run fails when the rejected share passes a set limit. | `dbt build` passes; a contract break fails; the gate test passes | `.venv/bin/python -m pytest tests/test_contracts_gate.py -q` | `docs/engagement/evidence/contracts-gate.txt` | met locally |
| F-2 | Each run publishes a provenance manifest: input blob names and SHA-256, code SHA, dbt manifest hash, row counts per layer. | The manifest validates against a JSON schema | `.venv/bin/python -m pytest tests/test_provenance.py -q` | `docs/engagement/evidence/provenance-manifest-sample.json` | met locally |
| F-3 | k-anonymity on the quasi-identifiers in `dim_patient` (birth year, state, gender). Groups under k are generalized or suppressed. No group under k reaches the curated Parquet. | The test passes on the 1,000-patient fixture and on a crafted small set | `.venv/bin/python -m pytest tests/test_kanon.py -q` | `docs/engagement/evidence/kanon-report.txt` | met locally |
| F-4 | The HMAC key has a version id in each token. A new key version gives new tokens; old marts stay readable; the rotation plan is written. | The tests pass | `.venv/bin/python -m pytest tests/test_key_versions.py -q` | `docs/engagement/evidence/key-versions.txt` | not started |
| F-5 | A HIPAA-style control mapping (administrative, physical and technical safeguards to repo controls, with status and evidence). It says: no compliance claim, no certification. | Every evidence path exists | `.venv/bin/python scripts/check_map_links.py docs/engagement/HIPAA-STYLE-MAP.md` | `docs/engagement/HIPAA-STYLE-MAP.md` | met locally |
| F-6 | Pipeline observability: task duration and row counts as metrics, one freshness SLO ("marts published by 06:00 on 99 percent of days"), an alert rule with a promtool test, one Grafana panel. | promtool exits 0; the dashboard check passes | `podman run --rm -v "$PWD/observability/rules:/r:ro,z" --entrypoint promtool docker.io/prom/prometheus:v2.55.1 test rules /r/freshness.rules.test.yml` then `python3 tools/check_dashboard.py observability/grafana/fhir-pipeline.json` | `docs/engagement/evidence/promtool-freshness.txt` | met locally (metrics, promtool); authored, not run (Grafana) |
| F-7 | Failure lab: corrupt blob, schema drift (new field, removed field), late update older than the max (lookback window fix from DECISIONS 6), Azurite down. Evidence per case. | Four evidence sections | `.venv/bin/python scripts/failure_lab.py --all` | `docs/engagement/evidence/failure-lab.txt` | not started |
| F-8 | CI security gate: pip-audit, bandit and semgrep, gitleaks with an allowlist entry for the public Azurite key, SBOM. | The local commands pass | `gitleaks git --config .gitleaks.toml --redact --no-banner --exit-code 1 .`; see `docs/engagement/SECURITY-GATE.md` (bandit, semgrep, pip-audit on the lock files, SBOM from the lock files) | `docs/engagement/evidence/security-gate-local.txt` | met locally |

## Notes

- The status changes only when the proof command runs and its output is saved.
- A failed criterion stays `not met` and the gap is written in the evidence file.
- Performance numbers carry the phrase "measured on one laptop".
- The control map for F-5 names the safeguards and the gaps. It is not a legal opinion.
