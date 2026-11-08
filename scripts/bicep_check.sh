#!/usr/bin/env bash
# Compile and lint the Bicep files. No az login, no deployment.
set -euo pipefail
cd "$(dirname "$0")/../infra"
az bicep install >/dev/null 2>&1 || true
az bicep build --file main.bicep --stdout >/dev/null
# `az bicep lint` exits 0 even with warnings, so read its output and fail on any diagnostic.
OUT="$(az bicep lint --file main.bicep 2>&1 || true)"
if echo "$OUT" | grep -Eiq 'warning|error'; then echo "$OUT"; echo "bicep lint reported diagnostics" >&2; exit 1; fi
for f in main.dev.bicepparam main.prod.bicepparam; do
  az bicep build-params --file "$f" --stdout >/dev/null
done
echo "bicep: build OK, lint OK (0 warnings), params OK"
