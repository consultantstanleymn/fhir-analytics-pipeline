"""Seeded generator for synthetic FHIR R4 bulk-export NDJSON.

It writes one NDJSON file per resource type (Patient, Encounter, Condition,
Observation). All data is invented. The output is NOT Synthea output.

Edge cases written on purpose:
- valid resources with missing optional fields (no serviceType, no Observation value)
- exact duplicate lines
- late-arriving updates (same id, later meta.lastUpdated, written earlier in the file)
- invalid resources that must go to quarantine (bad enum, bad date, malformed JSON,
  missing subject)
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

RESOURCE_TYPES = ("Patient", "Encounter", "Condition", "Observation")

DEPARTMENTS = ["Cardiology", "Emergency", "Oncology", "Orthopedics", "Pediatrics", "General Medicine"]
FIRST = ["Ava", "Liam", "Noor", "Mateo", "Zara", "Ivan", "Mei", "Omar", "Lena", "Kofi", "Ana", "Raj"]
LAST = ["Stone", "Rivera", "Khan", "Novak", "Okafor", "Tanaka", "Silva", "Berg", "Hale", "Moreau"]
STATES = ["MN", "WI", "IA", "ND", "SD", "IL"]
CONDITIONS = [
    ("44054006", "Type 2 diabetes mellitus"),
    ("38341003", "Hypertensive disorder"),
    ("13645005", "Chronic obstructive lung disease"),
    ("49436004", "Atrial fibrillation"),
    ("84114007", "Heart failure"),
    ("195967001", "Asthma"),
    ("254837009", "Malignant tumor of breast"),
    ("396275006", "Osteoarthritis"),
]
# (LOINC code, display, unit, low, high)
VITALS = [
    ("8867-4", "Heart rate", "/min", 48, 130),
    ("8310-5", "Body temperature", "Cel", 35.5, 39.8),
    ("8480-6", "Systolic blood pressure", "mm[Hg]", 90, 190),
    ("2339-0", "Glucose [Mass/volume] in Blood", "mg/dL", 60, 320),
]
PATIENT_SYSTEM = "urn:example:synthetic-mrn"
DEPT_SYSTEM = "urn:example:department"
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Bundle:
    """All resources of one generated batch, as lists of JSON strings."""

    lines: dict[str, list[str]] = field(default_factory=lambda: {t: [] for t in RESOURCE_TYPES})
    counts: dict[str, int] = field(default_factory=lambda: {t: 0 for t in RESOURCE_TYPES})

    def add(self, rtype: str, resource: dict[str, Any] | str) -> None:
        self.lines[rtype].append(resource if isinstance(resource, str) else json.dumps(resource))
        self.counts[rtype] += 1


def _patient(rng: random.Random, n: int, updated: datetime) -> dict[str, Any]:
    birth = datetime(1935, 1, 1) + timedelta(days=rng.randint(0, 29000))
    return {
        "resourceType": "Patient",
        "id": f"pat-{n:06d}",
        "meta": {"lastUpdated": _iso(updated)},
        "identifier": [{"system": PATIENT_SYSTEM, "value": f"MRN{rng.randint(10**7, 10**8 - 1)}"}],
        "name": [{"family": rng.choice(LAST), "given": [rng.choice(FIRST)]}],
        "gender": rng.choice(["female", "male", "other", "unknown"]),
        "birthDate": birth.strftime("%Y-%m-%d"),
        "address": [
            {
                "line": [f"{rng.randint(1, 9999)} Example Street"],
                "city": "Exampleville",
                "state": rng.choice(STATES),
                "postalCode": f"{rng.randint(10000, 99999)}",
            }
        ],
        "telecom": [{"system": "phone", "value": f"555-01{rng.randint(0, 99):02d}"}],
    }


def _encounter(
    eid: str,
    pid: str,
    start: datetime,
    end: datetime | None,
    cls: str,
    dept: str | None,
    updated: datetime,
    status: str,
    disposition: str = "home",
) -> dict[str, Any]:
    res: dict[str, Any] = {
        "resourceType": "Encounter",
        "id": eid,
        "meta": {"lastUpdated": _iso(updated)},
        "status": status,
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": cls,
        },
        "subject": {"reference": f"Patient/{pid}"},
        "period": {"start": _iso(start)},
        "text": {"status": "generated", "div": "<div>free text narrative</div>"},
    }
    if end is not None:
        res["period"]["end"] = _iso(end)
        res["hospitalization"] = {"dischargeDisposition": {"coding": [{"code": disposition}]}}
    if dept is not None:
        res["serviceType"] = {"coding": [{"system": DEPT_SYSTEM, "display": dept}]}
    return res


def generate(n_patients: int, seed: int, *, with_edge_cases: bool = True) -> Bundle:
    """Generate a full initial export for n_patients patients."""
    rng = random.Random(seed)
    bundle = Bundle()
    enc_n = cond_n = obs_n = 0
    for p in range(n_patients):
        updated = BASE_TIME + timedelta(days=rng.randint(0, 5))
        pat = _patient(rng, p, updated)
        bundle.add("Patient", pat)
        pid = pat["id"]
        # About 18% of patients are heavy users, so readmissions happen.
        n_visits = rng.choice([1, 1, 2, 2, 3, 4]) if rng.random() < 0.18 else rng.choice([0, 1, 1, 2])
        cursor = BASE_TIME + timedelta(days=rng.randint(0, 120))
        for _ in range(n_visits):
            enc_n += 1
            inpatient = rng.random() < 0.55
            start = cursor + timedelta(hours=rng.randint(0, 20))
            los_days = rng.randint(1, 9) if inpatient else 0
            end = start + (timedelta(days=los_days, hours=rng.randint(1, 6)) if inpatient
                           else timedelta(hours=rng.randint(1, 4)))
            dept = rng.choice(DEPARTMENTS)
            last_upd = end + timedelta(hours=1)
            eid = f"enc-{enc_n:07d}"
            disposition = "exp" if inpatient and rng.random() < 0.03 else "home"
            drop_dept = rng.random() < 0.03  # drawn always, so seeds match with and without edges
            enc = _encounter(
                eid, pid, start, end, "IMP" if inpatient else "AMB",
                None if with_edge_cases and drop_dept else dept,
                last_upd, "finished", disposition,
            )
            bundle.add("Encounter", enc)
            for _c in range(rng.choice([0, 1, 1, 2])):
                cond_n += 1
                code, display = rng.choice(CONDITIONS)
                bundle.add("Condition", {
                    "resourceType": "Condition",
                    "id": f"cond-{cond_n:07d}",
                    "meta": {"lastUpdated": _iso(last_upd)},
                    "clinicalStatus": {"coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": rng.choice(["active", "active", "resolved"])}]},
                    "code": {"coding": [{"system": "http://snomed.info/sct", "code": code,
                                         "display": display}]},
                    "subject": {"reference": f"Patient/{pid}"},
                    "encounter": {"reference": f"Encounter/{eid}"},
                    "recordedDate": _iso(start),
                    "note": [{"text": "free text clinical note"}],
                })
            for _o in range(rng.choice([1, 2, 3])):
                obs_n += 1
                loinc, disp, unit, lo, hi = rng.choice(VITALS)
                obs: dict[str, Any] = {
                    "resourceType": "Observation",
                    "id": f"obs-{obs_n:07d}",
                    "meta": {"lastUpdated": _iso(last_upd)},
                    "status": "final",
                    "category": [{"coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs"}]}],
                    "code": {"coding": [{"system": "http://loinc.org", "code": loinc,
                                         "display": disp}]},
                    "subject": {"reference": f"Patient/{pid}"},
                    "encounter": {"reference": f"Encounter/{eid}"},
                    "effectiveDateTime": _iso(start + timedelta(minutes=rng.randint(5, 90))),
                }
                drop_value = rng.random() < 0.04
                value = round(rng.uniform(lo, hi), 1)  # always drawn, keeps seeds aligned
                if not (with_edge_cases and drop_value):  # a missing value is valid FHIR
                    obs["valueQuantity"] = {"value": value, "unit": unit}
                bundle.add("Observation", obs)
            # Next visit starts 3 to 60 days after this one ends.
            cursor = end + timedelta(days=rng.randint(3, 60))
    if with_edge_cases:
        _add_edge_cases(bundle, rng, n_patients, enc_n)
    return bundle


def _add_edge_cases(bundle: Bundle, rng: random.Random, n_patients: int, enc_n: int) -> None:
    n_dup = max(2, n_patients // 50)
    n_bad = max(2, n_patients // 100)
    # Exact duplicate lines.
    for rtype in RESOURCE_TYPES:
        for line in rng.sample(bundle.lines[rtype], min(n_dup, len(bundle.lines[rtype]))):
            bundle.add(rtype, line)
    # Late-arriving updates: same id, newer lastUpdated, written near the START of the file.
    late: list[str] = []
    for line in rng.sample(bundle.lines["Encounter"], min(n_dup, len(bundle.lines["Encounter"]))):
        enc = json.loads(line)
        if "serviceType" not in enc:
            enc["serviceType"] = {"coding": [{"system": DEPT_SYSTEM, "display": "General Medicine"}]}
        else:
            enc["serviceType"]["coding"][0]["display"] = rng.choice(DEPARTMENTS)
        enc["meta"]["lastUpdated"] = _iso(BASE_TIME + timedelta(days=400))
        late.append(json.dumps(enc))
    bundle.lines["Encounter"] = late + bundle.lines["Encounter"]
    bundle.counts["Encounter"] += len(late)
    # Invalid resources that no valid resource references.
    for i in range(n_bad):
        bundle.add("Encounter", {"resourceType": "Encounter", "id": f"enc-bad-{i}",
                                 "status": "not-a-status", "class": {"code": "IMP"},
                                 "subject": {"reference": "Patient/pat-000000"}})
        bundle.add("Encounter", {"resourceType": "Encounter", "id": f"enc-nosubj-{i}",
                                 "status": "finished", "class": {"code": "AMB"}})
        bundle.add("Patient", {"resourceType": "Patient", "id": f"pat-bad-{i}",
                               "birthDate": "not-a-date"})
        bundle.add("Condition", {"resourceType": "Condition", "id": f"cond-bad-{i}",
                                 "subject": {"reference": "Patient/pat-000000"},
                                 "clinicalStatus": "should-be-an-object"})
        bundle.add("Observation", {"resourceType": "Observation", "id": f"obs-bad-{i}",
                                   "status": "final", "code": {"text": "x"},
                                   "valueQuantity": {"value": "abc"}})
    bundle.add("Observation", '{"resourceType": "Observation", "id": "obs-truncated"')


def make_update_batch(seed: int, n_patients: int, n_updates: int, new_encounters: int) -> Bundle:
    """A second batch for incremental tests: updates of existing encounters plus new ones.

    Updated encounters get a later lastUpdated and a different department.
    New encounters use ids that do not exist in the initial batch.
    """
    rng = random.Random(seed)
    initial = generate(n_patients, seed, with_edge_cases=False)
    bundle = Bundle()
    encs = [json.loads(x) for x in initial.lines["Encounter"] if '"enc-0' in x]
    for enc in rng.sample(encs, min(n_updates, len(encs))):
        enc["serviceType"] = {"coding": [{"system": DEPT_SYSTEM, "display": "Updated Dept"}]}
        enc["meta"]["lastUpdated"] = _iso(BASE_TIME + timedelta(days=500))
        bundle.add("Encounter", enc)
    for i in range(new_encounters):
        pid = f"pat-{rng.randrange(n_patients):06d}"
        start = BASE_TIME + timedelta(days=450 + i)
        bundle.add("Encounter", _encounter(
            f"enc-new-{i:05d}", pid, start, start + timedelta(days=2), "IMP", "Cardiology",
            BASE_TIME + timedelta(days=500, hours=1), "finished"))
    return bundle


def write_bundle(bundle: Bundle, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for rtype in RESOURCE_TYPES:
        if not bundle.lines[rtype]:
            continue
        path = out_dir / f"{rtype}.ndjson"
        path.write_text("\n".join(bundle.lines[rtype]) + "\n", encoding="utf-8")
        paths[rtype] = path
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patients", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-edge-cases", action="store_true")
    parser.add_argument("--update-batch", action="store_true",
                        help="write an update batch (needs the same --patients and --seed)")
    args = parser.parse_args()
    if args.update_batch:
        bundle = make_update_batch(args.seed, args.patients, max(5, args.patients // 20),
                                   max(5, args.patients // 50))
    else:
        bundle = generate(args.patients, args.seed, with_edge_cases=not args.no_edge_cases)
    write_bundle(bundle, args.out)
    total = sum(bundle.counts.values())
    print(json.dumps({"resources": total, **bundle.counts}))


if __name__ == "__main__":
    main()
