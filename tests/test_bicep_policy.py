"""Policy tests for infra/main.bicep.

Two layers:
1. Source test (always runs): regex checks on the Bicep text.
2. Compiled test (needs `az bicep`): compile to ARM JSON and assert on the real result.
   Set REQUIRE_BICEP=1 (CI does) to fail instead of skip when az bicep is missing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parents[1] / "infra"
SOURCE = (INFRA / "main.bicep").read_text()


def test_source_policy_flags():
    assert re.search(r"supportsHttpsTrafficOnly:\s*true", SOURCE)
    assert re.search(r"minimumTlsVersion:\s*'TLS1_2'", SOURCE)
    assert re.search(r"allowBlobPublicAccess:\s*false", SOURCE)
    assert re.search(r"enableSoftDelete:\s*true", SOURCE)
    assert "publicAccess: 'None'" in SOURCE


def _compile() -> dict:  # type: ignore[type-arg]
    az = shutil.which("az")
    if not az:
        if os.environ.get("REQUIRE_BICEP") == "1":
            pytest.fail("az is required (REQUIRE_BICEP=1)")
        pytest.skip("az not installed")
    proc = subprocess.run([az, "bicep", "build", "--file", str(INFRA / "main.bicep"), "--stdout"],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        if os.environ.get("REQUIRE_BICEP") == "1":
            pytest.fail(proc.stderr[-1500:])
        pytest.skip("az bicep is not installed locally")
    return json.loads(proc.stdout)  # type: ignore[no-any-return]


def _resources(arm: dict, rtype: str) -> list[dict]:  # type: ignore[type-arg]
    res = arm["resources"]
    items = res.values() if isinstance(res, dict) else res
    return [r for r in items if r["type"] == rtype]


@pytest.mark.bicep
def test_compiled_arm_policy():
    arm = _compile()
    (storage,) = _resources(arm, "Microsoft.Storage/storageAccounts")
    props = storage["properties"]
    assert props["supportsHttpsTrafficOnly"] is True
    assert props["minimumTlsVersion"] == "TLS1_2"
    assert props["allowBlobPublicAccess"] is False
    containers = _resources(arm, "Microsoft.Storage/storageAccounts/blobServices/containers")
    assert {re.findall(r"'(\w+)'\)\]$", c["name"])[0] for c in containers} == {"landing", "curated"}
    assert all(c["properties"]["publicAccess"] == "None" for c in containers)
    (vault,) = _resources(arm, "Microsoft.KeyVault/vaults")
    assert vault["properties"]["enableSoftDelete"] is True
    assert vault["properties"]["enablePurgeProtection"] is True
    assert len(_resources(arm, "Microsoft.Authorization/roleAssignments")) == 2
    assert len(_resources(arm, "Microsoft.ManagedIdentity/userAssignedIdentities")) == 1
