import json
from pathlib import Path

import pytest

from fhir_pipeline.pseudonymize import Keyring, load_key, pseudonymize, token

KR = Keyring({"v1": b"k"}, "v1")

GOOD = json.loads((Path(__file__).parent / "fixtures" / "validate" / "good.json").read_text())
FORBIDDEN = {"name", "address", "telecom", "line", "city", "postalCode", "family", "given",
             "birthDate", "identifier", "text", "note", "subject", "id"}


def _all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_keys(v)


def test_same_input_same_token():
    assert token(b"k", "Patient", "P1", "v1") == token(b"k", "Patient", "P1", "v1")


def test_different_key_different_token():
    assert token(b"k1", "Patient", "P1", "v1") != token(b"k2", "Patient", "P1", "v1")


def test_namespace_separates_tokens():
    assert token(b"k", "Patient", "X", "v1") != token(b"k", "MRN", "X", "v1")


def test_patient_output_has_no_direct_identifiers():
    out = pseudonymize(GOOD["Patient"], KR)
    assert not (set(_all_keys(out)) & FORBIDDEN)
    assert set(out) == {"resourceType", "meta", "patient_token", "gender", "mrn_token",
                        "birth_year", "state"}
    dumped = json.dumps(out)
    for secret in ("Fixture", "Test Street", "MRN-FIX-1", "Testville", "1951-04-01"):
        assert secret not in dumped
    assert out["birth_year"] == 1951


@pytest.mark.parametrize("rtype", ["Encounter", "Condition", "Observation"])
def test_other_resources_swap_subject_for_token(rtype):
    resource = {**GOOD[rtype], "text": {"div": "free text"}, "note": [{"text": "free text"}]}
    out = pseudonymize(resource, KR)
    assert out["patient_token"] == token(b"k", "Patient", "P1", "v1")
    assert not ({"subject", "text", "note"} & set(out))
    assert out["id"] == resource["id"]


def test_patient_token_matches_reference_token():
    p = pseudonymize(GOOD["Patient"], KR)
    e = pseudonymize(GOOD["Encounter"], KR)
    assert p["patient_token"] == e["patient_token"]


def test_missing_key_is_an_error(monkeypatch):
    monkeypatch.delenv("FHIR_HMAC_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FHIR_HMAC_KEY"):
        load_key()
