from __future__ import annotations

import json

import pytest

from fhir_pipeline.pseudonymize import Keyring, load_keyring, pseudonymize, token


def _patient() -> dict:
    return {"resourceType": "Patient", "id": "P1", "gender": "female", "birthDate": "1960-01-02",
            "identifier": [{"value": "MRN-1"}], "address": [{"state": "MN"}]}


def test_token_has_kid_prefix() -> None:
    t = token(b"k", "Patient", "P1", "v7")
    kid, _, digest = t.partition(".")
    assert kid == "v7"
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
    out = pseudonymize(_patient(), Keyring({"v7": b"k"}, "v7"))
    assert out["patient_token"].startswith("v7.") and out["mrn_token"].startswith("v7.")


def test_new_kid_gives_new_token() -> None:
    ring = Keyring({"v1": b"old-key", "v2": b"new-key"}, "v1")
    old = pseudonymize(_patient(), ring)["patient_token"]
    new = pseudonymize(_patient(), Keyring(ring.keys, "v2"))["patient_token"]
    assert old != new
    assert old.startswith("v1.") and new.startswith("v2.")
    # same key bytes under another id still differ, because the id is part of the token
    assert token(b"same", "Patient", "P1", "v1") != token(b"same", "Patient", "P1", "v2")


def test_same_ring_same_token() -> None:
    ring = Keyring({"v1": b"k"}, "v1")
    assert pseudonymize(_patient(), ring) == pseudonymize(_patient(), ring)


def test_legacy_single_key_env_maps_to_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FHIR_HMAC_KEYS", raising=False)
    monkeypatch.delenv("FHIR_HMAC_ACTIVE", raising=False)
    monkeypatch.setenv("FHIR_HMAC_KEY", "legacy-key")
    ring = load_keyring()
    assert ring.active == "v1" and ring.keys == {"v1": b"legacy-key"}


def test_keyring_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHIR_HMAC_KEYS", json.dumps({"v1": "a", "v2": "b"}))
    monkeypatch.setenv("FHIR_HMAC_ACTIVE", "v2")
    ring = load_keyring()
    assert ring.active == "v2" and ring.key == b"b" and set(ring.keys) == {"v1", "v2"}


def test_missing_active_kid_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHIR_HMAC_KEYS", json.dumps({"v1": "a"}))
    monkeypatch.delenv("FHIR_HMAC_ACTIVE", raising=False)
    with pytest.raises(RuntimeError, match="FHIR_HMAC_ACTIVE"):
        load_keyring()
    monkeypatch.setenv("FHIR_HMAC_ACTIVE", "v9")
    with pytest.raises(RuntimeError, match="not in the keyring"):
        load_keyring()


def test_bad_key_id_and_bad_json_are_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        Keyring({"v.1": b"k"}, "v.1")  # a dot would break the token format
    monkeypatch.setenv("FHIR_HMAC_KEYS", "not json")
    monkeypatch.setenv("FHIR_HMAC_ACTIVE", "v1")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        load_keyring()
    monkeypatch.setenv("FHIR_HMAC_KEYS", json.dumps({"v1": ""}))
    with pytest.raises(RuntimeError, match="non-empty"):
        load_keyring()
