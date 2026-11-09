from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AZURITE_IMAGE = "mcr.microsoft.com/azure-storage/azurite:3.35.0"
# Public, documented Azurite emulator account. This is not a secret.
_EMU_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _conn(port: int) -> str:
    return (
        "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
        f"AccountKey={_EMU_KEY};BlobEndpoint=http://127.0.0.1:{port}/devstoreaccount1;"
    )


@pytest.fixture(scope="session")
def azurite_conn() -> Iterator[str]:
    """Connection string for Azurite.

    CI sets AZURITE_CONNECTION_STRING (service container). Locally we start a rootless
    podman container on a random free port and remove it by its exact name afterwards.
    """
    external = os.environ.get("AZURITE_CONNECTION_STRING")
    if external:
        yield external
        return
    if not shutil.which("podman"):
        pytest.skip("no AZURITE_CONNECTION_STRING and no podman")
    port = _free_port()
    name = f"fhir-azurite-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["podman", "run", "-d", "--rm", "--name", name, "-p", f"127.0.0.1:{port}:10000",
         AZURITE_IMAGE, "azurite-blob", "--blobHost", "0.0.0.0", "--skipApiVersionCheck"],
        check=True, capture_output=True,
    )
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Azurite did not start")
        time.sleep(1)
        yield _conn(port)
    finally:
        subprocess.run(["podman", "rm", "-f", name], check=False, capture_output=True)


@pytest.fixture(autouse=True)
def _metrics_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep metrics textfiles out of the repo during tests."""
    monkeypatch.setenv("FHIR_METRICS_FILE", str(tmp_path / "metrics" / "fhir_pipeline.prom"))


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated warehouse file, work dir and test HMAC key."""
    monkeypatch.setenv("FHIR_HMAC_KEY", "test-key-not-a-secret")
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "wh.duckdb"))
    monkeypatch.setenv("FHIR_WORK_DIR", str(tmp_path / "work"))
    return tmp_path


@pytest.fixture(scope="session")
def dbt_bin() -> str:
    candidate = os.environ.get("DBT_BIN") or str(REPO / ".venv-dbt" / "bin" / "dbt")
    if not Path(candidate).exists():
        found = shutil.which("dbt")
        if not found:
            pytest.skip("dbt not available")
        candidate = found
    return candidate
