# Security gate

The gate has five jobs in `.github/workflows/security.yml`. The same checks run on this laptop.

## Jobs and fail rules

| Job | What it checks | Fails when |
|---|---|---|
| `sast` | bandit on `src`, `generator`, `dags` (medium and high); semgrep with `.semgrep.yml` | Any bandit finding at medium or high, or any semgrep error |
| `codeql` | CodeQL for Python | Any error-level result |
| `secrets` | gitleaks on full history and on the tree, with `.gitleaks.toml` | Any finding |
| `deps` | pip-audit on `requirements/app.lock` and `requirements/dbt.lock` | A known vulnerability with a fix |
| `sbom` | trivy builds a CycloneDX SBOM from the two lock files | The tool fails |

There is no image job. This repo builds no container image.

A finding in `security/exceptions.json` does not fail a job until its `expires` date. Each item needs `id`, `tool`, `reason`, `owner`, `expires` (at most 90 days ahead) and `review_note`. `scripts/check_security_exceptions.py` enforces this. The list is empty now.

## Allowlist

`.gitleaks.toml` allows the public Azurite emulator account key. Azure documents this key for the emulator. It is not a secret. The file also allows a public Azure built-in role id and local folders that git does not track.

## Run each check locally

```
TV=<path to the shared tools venv>
$TV/bin/bandit -r src generator dags -ll
$TV/bin/semgrep --config .semgrep.yml --metrics=off --error src generator dags
$TV/bin/pip-audit -r requirements/app.lock --no-deps --disable-pip
$TV/bin/pip-audit -r requirements/dbt.lock --no-deps --disable-pip
gitleaks git --config .gitleaks.toml --redact --no-banner --exit-code 1 .
gitleaks dir --config .gitleaks.toml --redact --no-banner .
python3 scripts/check_security_exceptions.py security/exceptions.json
actionlint .github/workflows/security.yml
```

For the SBOM, copy each lock file to a folder as `requirements.txt` and run `trivy fs --format cyclonedx --output <file> <folder>`.

## Code changes that this gate drove

Bandit flagged three SQL strings. Each builds SQL with an f-string from an internal name. The code now checks each name against an allow-list before it builds the string. Each line carries a `nosec` or `nosemgrep` comment that names the guard.

## Status

| Check | Status | Evidence |
|---|---|---|
| bandit, semgrep, pip-audit, gitleaks, SBOM, exceptions check | Verified locally | `docs/engagement/evidence/security-gate-local.txt` |
| Workflow syntax | Verified locally with actionlint | same file |
| Workflow run on GitHub, CodeQL | Authored, not run: needs GitHub Actions | none |

Action versions are unverified until a run. The workflow uses the same major versions as `ci.yml`, and `codeql-action@v3`, `upload-artifact@v4`. The gitleaks and trivy install lines pin a version and were not run on a runner.

Authored, not run: `.github/workflows/security.yml` is written and syntax-checked with `actionlint 1.7.12`. It was not executed against GitHub Actions. Reason: needs GitHub Actions.
