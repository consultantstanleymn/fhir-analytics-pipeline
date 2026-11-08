"""Validate one NDJSON line against FHIR R4 models and our business rules.

We use the R4B models of `fhir.resources` (FHIR 4.3.0, the R4 maintenance release).
Invalid lines are not dropped. They come back as a Rejected value with the reason,
so the caller can write them to the quarantine table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fhir.resources.R4B.condition import Condition
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.patient import Patient
from pydantic import BaseModel, ValidationError

MODELS: dict[str, type[BaseModel]] = {
    "Patient": Patient,
    "Encounter": Encounter,
    "Condition": Condition,
    "Observation": Observation,
}


# `fhir.resources` checks structure and types but NOT required code bindings (a status of
# "not-a-status" passes). We check the required bindings we rely on ourselves.
REQUIRED_BINDINGS: dict[tuple[str, str], frozenset[str]] = {
    ("Encounter", "status"): frozenset({
        "planned", "arrived", "triaged", "in-progress", "onleave", "finished", "cancelled",
        "entered-in-error", "unknown"}),
    ("Observation", "status"): frozenset({
        "registered", "preliminary", "final", "amended", "corrected", "cancelled",
        "entered-in-error", "unknown"}),
    ("Patient", "gender"): frozenset({"male", "female", "other", "unknown"}),
}


@dataclass(frozen=True)
class Accepted:
    resource: dict[str, Any]


@dataclass(frozen=True)
class Rejected:
    reason: str
    raw_line: str


def _short_error(err: ValidationError) -> str:
    first = err.errors()[0]
    loc = ".".join(str(p) for p in first["loc"])
    return f"{loc}: {first['msg']}"


def validate_line(expected_type: str, line: str) -> Accepted | Rejected:
    """Validate a single NDJSON line for the expected resource type."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        return Rejected(f"malformed JSON: {exc.msg}", line)
    if not isinstance(data, dict):
        return Rejected("line is not a JSON object", line)
    if data.get("resourceType") != expected_type:
        return Rejected(f"unexpected resourceType {data.get('resourceType')!r}", line)
    if not data.get("id"):
        return Rejected("missing id", line)
    try:
        MODELS[expected_type].model_validate(data)
    except ValidationError as exc:
        return Rejected(f"fhir validation: {_short_error(exc)}", line)
    for (rtype, field), allowed in REQUIRED_BINDINGS.items():
        if rtype == expected_type and field in data and data[field] not in allowed:
            return Rejected(f"code binding: {field} {data[field]!r} is not allowed", line)
    # Business rules on top of the FHIR schema.
    if expected_type in ("Encounter", "Condition", "Observation"):
        ref = (data.get("subject") or {}).get("reference", "")
        if not ref.startswith("Patient/"):
            return Rejected("business rule: missing Patient subject reference", line)
    if not (data.get("meta") or {}).get("lastUpdated"):
        return Rejected("business rule: missing meta.lastUpdated", line)
    return Accepted(data)
