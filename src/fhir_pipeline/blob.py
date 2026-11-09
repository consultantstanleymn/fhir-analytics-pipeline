"""Thin wrapper over the Azure Blob Storage SDK.

In this project it only talks to the Azurite emulator. The connection string comes
from the environment, never from code.
"""

from __future__ import annotations

import os
from pathlib import Path

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient

CONN_ENV = "AZURE_STORAGE_CONNECTION_STRING"
LANDING = "landing"
CURATED = "curated"


class BlobStore:
    def __init__(self, connection_string: str | None = None, retries: int | None = None) -> None:
        """`retries` sets the SDK retry count. None keeps the SDK default (used in the failure lab)."""
        conn = connection_string or os.environ.get(CONN_ENV)
        if not conn:
            raise RuntimeError(f"{CONN_ENV} is not set.")
        if retries is None:
            self._client = BlobServiceClient.from_connection_string(conn)
        else:
            self._client = BlobServiceClient.from_connection_string(conn, retry_total=retries)

    def ensure_container(self, name: str) -> None:
        try:
            self._client.create_container(name)
        except ResourceExistsError:
            pass

    def upload_bytes(self, container: str, blob: str, data: bytes) -> None:
        self._client.get_blob_client(container, blob).upload_blob(data, overwrite=True)

    def upload_file(self, container: str, blob: str, path: Path) -> None:
        with path.open("rb") as fh:
            self._client.get_blob_client(container, blob).upload_blob(fh, overwrite=True)

    def download_bytes(self, container: str, blob: str) -> bytes:
        return self._client.get_blob_client(container, blob).download_blob().readall()

    def list_blobs(self, container: str, prefix: str = "") -> list[str]:
        cc = self._client.get_container_client(container)
        return sorted(b.name for b in cc.list_blobs(name_starts_with=prefix))
