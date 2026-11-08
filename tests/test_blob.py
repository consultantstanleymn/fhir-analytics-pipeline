import pytest

from fhir_pipeline.blob import LANDING, BlobStore

pytestmark = pytest.mark.azurite


def test_upload_list_download_round_trip(azurite_conn):
    store = BlobStore(azurite_conn)
    store.ensure_container(LANDING)
    store.ensure_container(LANDING)  # idempotent
    store.upload_bytes(LANDING, "rt/2026-01-01/a.ndjson", b'{"a": 1}\n')
    store.upload_bytes(LANDING, "rt/2026-01-01/b.ndjson", b'{"b": 2}\n')
    store.upload_bytes(LANDING, "rt/2026-01-02/c.ndjson", b"x")
    assert store.list_blobs(LANDING, "rt/2026-01-01/") == [
        "rt/2026-01-01/a.ndjson", "rt/2026-01-01/b.ndjson"]
    assert store.download_bytes(LANDING, "rt/2026-01-01/a.ndjson") == b'{"a": 1}\n'
    store.upload_bytes(LANDING, "rt/2026-01-01/a.ndjson", b"new")  # overwrite
    assert store.download_bytes(LANDING, "rt/2026-01-01/a.ndjson") == b"new"


def test_missing_connection_string_is_an_error(monkeypatch):
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    with pytest.raises(RuntimeError):
        BlobStore()
