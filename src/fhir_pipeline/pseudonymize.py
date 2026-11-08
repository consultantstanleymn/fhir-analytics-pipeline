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
import os
from typing import Any

KEY_ENV = "FHIR_HMAC_KEY"


def load_key() -> bytes:
    key = os.environ.get(KEY_ENV)
    if not key:
        raise RuntimeError(f"{KEY_ENV} is not set. Set it in the environment, never in code.")
    return key.encode("utf-8")


def token(key: bytes, namespace: str, value: str) -> str:
    return hmac.new(key, f"{namespace}|{value}".encode(), hashlib.sha256).hexdigest()


def pseudonymize(resource: dict[str, Any], key: bytes) -> dict[str, Any]:
    rtype = resource["resourceType"]
    if rtype == "Patient":
        return _patient(resource, key)
    out = {
        k: v
        for k, v in resource.items()
        if k not in ("text", "note", "subject", "contained", "extension")
    }
    ref = resource["subject"]["reference"]
    out["patient_token"] = token(key, "Patient", ref.removeprefix("Patient/"))
    return out


def _patient(resource: dict[str, Any], key: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {
        "resourceType": "Patient",
        "meta": resource.get("meta", {}),
        "patient_token": token(key, "Patient", resource["id"]),
        "gender": resource.get("gender"),
    }
    mrns = [i.get("value") for i in resource.get("identifier", []) if i.get("value")]
    if mrns:
        out["mrn_token"] = token(key, "MRN", mrns[0])
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
