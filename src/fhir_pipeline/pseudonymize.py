"""Pseudonymization: replace identifiers with HMAC-SHA256 tokens, drop direct identifiers.

This is a design demo. It is NOT a claim of HIPAA compliance.
- Patient id and MRN become tokens. The same input and key give the same token.
- Names, street addresses, phone numbers and free text are dropped.
- Birth date is reduced to birth year. Address is reduced to state.
- Encounter, Condition and Observation keep their own ids and the clinical content;
  the Patient reference becomes patient_token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Any

KEY_ENV = "FHIR_HMAC_KEY"  # legacy single key; becomes key id "v1"
KEYS_ENV = "FHIR_HMAC_KEYS"  # JSON object: key id -> key
ACTIVE_ENV = "FHIR_HMAC_ACTIVE"  # key id that new tokens use
LEGACY_KID = "v1"
_KID_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")


@dataclass(frozen=True)
class Keyring:
    """HMAC keys by key id, and the id that new tokens use."""

    keys: dict[str, bytes]
    active: str

    def __post_init__(self) -> None:
        for kid in self.keys:
            if not _KID_RE.fullmatch(kid):
                raise ValueError(f"bad key id: {kid!r} (letters, digits, - and _ only)")
        if self.active not in self.keys:
            raise RuntimeError(f"active key id {self.active!r} is not in the keyring")

    @property
    def key(self) -> bytes:
        return self.keys[self.active]


def load_key() -> bytes:
    """Legacy single key. New code uses `load_keyring`."""
    key = os.environ.get(KEY_ENV)
    if not key:
        raise RuntimeError(f"{KEY_ENV} is not set. Set it in the environment, never in code.")
    return key.encode("utf-8")


def load_keyring() -> Keyring:
    """Read the keyring from the environment.

    `FHIR_HMAC_KEYS` is a JSON object of key id to key. `FHIR_HMAC_ACTIVE` names the key id for new
    tokens. If `FHIR_HMAC_KEYS` is not set, the legacy `FHIR_HMAC_KEY` becomes key id `v1`.
    """
    raw = os.environ.get(KEYS_ENV)
    if not raw:
        return Keyring({LEGACY_KID: load_key()}, LEGACY_KID)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{KEYS_ENV} is not valid JSON") from exc
    if not isinstance(data, dict) or not data or not all(isinstance(v, str) and v for v in data.values()):
        raise RuntimeError(f"{KEYS_ENV} must be a JSON object of key id to non-empty key")
    active = os.environ.get(ACTIVE_ENV)
    if not active:
        raise RuntimeError(f"{ACTIVE_ENV} is not set. Name the key id for new tokens.")
    return Keyring({k: v.encode("utf-8") for k, v in data.items()}, active)


def token(key: bytes, namespace: str, value: str, kid: str) -> str:
    """HMAC-SHA256 token with the key id as prefix: `<kid>.<hex>`."""
    digest = hmac.new(key, f"{namespace}|{value}".encode(), hashlib.sha256).hexdigest()
    return f"{kid}.{digest}"


def pseudonymize(resource: dict[str, Any], keyring: Keyring | bytes) -> dict[str, Any]:
    if isinstance(keyring, bytes):  # compatibility: a bare key is key id v1
        keyring = Keyring({LEGACY_KID: keyring}, LEGACY_KID)
    rtype = resource["resourceType"]
    if rtype == "Patient":
        return _patient(resource, keyring)
    out = {
        k: v
        for k, v in resource.items()
        if k not in ("text", "note", "subject", "contained", "extension")
    }
    ref = resource["subject"]["reference"]
    out["patient_token"] = token(keyring.key, "Patient", ref.removeprefix("Patient/"), keyring.active)
    return out


def _patient(resource: dict[str, Any], keyring: Keyring) -> dict[str, Any]:
    key, kid = keyring.key, keyring.active
    out: dict[str, Any] = {
        "resourceType": "Patient",
        "meta": resource.get("meta", {}),
        "patient_token": token(key, "Patient", resource["id"], kid),
        "gender": resource.get("gender"),
    }
    mrns = [i.get("value") for i in resource.get("identifier", []) if i.get("value")]
    if mrns:
        out["mrn_token"] = token(key, "MRN", mrns[0], kid)
    birth = resource.get("birthDate")
    if birth:
        out["birth_year"] = int(birth[:4])
    addresses = resource.get("address") or []
    if addresses and addresses[0].get("state"):
        out["state"] = addresses[0]["state"]
    return out


def resource_key(resource: dict[str, Any]) -> str:
    """Stable id of a pseudonymized resource (patient token or own id)."""
    return str(resource["patient_token"] if resource["resourceType"] == "Patient"
               else resource["id"])
