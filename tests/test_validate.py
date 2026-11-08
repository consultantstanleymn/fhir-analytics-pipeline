import json
from pathlib import Path

import pytest

from fhir_pipeline.validate import Accepted, Rejected, validate_line

GOOD = json.loads((Path(__file__).parent / "fixtures" / "validate" / "good.json").read_text())


@pytest.mark.parametrize("rtype", ["Patient", "Encounter", "Condition", "Observation"])
def test_known_good_resources_are_accepted(rtype):
    result = validate_line(rtype, json.dumps(GOOD[rtype]))
    assert isinstance(result, Accepted)
    assert result.resource["id"] == GOOD[rtype]["id"]


def _mutate(rtype, fn):
    data = json.loads(json.dumps(GOOD[rtype]))
    fn(data)
    return json.dumps(data)


BAD_CASES = [
    ("Encounter", _mutate("Encounter", lambda d: d.update(status="not-a-status")), "code binding"),
    ("Encounter", _mutate("Encounter", lambda d: d.pop("status")), "status"),
    ("Encounter", _mutate("Encounter", lambda d: d.pop("subject")), "missing Patient subject"),
    ("Patient", _mutate("Patient", lambda d: d.update(gender="robot")), "code binding"),
    ("Patient", _mutate("Patient", lambda d: d.update(birthDate="not-a-date")), "birthDate"),
    ("Patient", _mutate("Patient", lambda d: d.pop("id")), "missing id"),
    ("Patient", _mutate("Patient", lambda d: d.pop("meta")), "lastUpdated"),
    ("Observation", _mutate("Observation", lambda d: d["valueQuantity"].update(value="abc")), "fhir validation"),
    ("Condition", _mutate("Condition", lambda d: d.update(clinicalStatus="x")), "fhir validation"),
    ("Observation", '{"resourceType": "Observation", "id": "x"', "malformed JSON"),
    ("Observation", "[1, 2]", "not a JSON object"),
    ("Patient", json.dumps(GOOD["Encounter"]), "unexpected resourceType"),
]


@pytest.mark.parametrize(("rtype", "line", "reason"), BAD_CASES)
def test_known_bad_resources_are_rejected_with_reason(rtype, line, reason):
    result = validate_line(rtype, line)
    assert isinstance(result, Rejected)
    assert reason in result.reason
    assert result.raw_line == line


def test_bad_rows_land_in_quarantine_table(env):
    import duckdb

    from fhir_pipeline.pipeline import validate_text, load_blob_as

    lines = [json.dumps(GOOD["Patient"]), json.dumps({**GOOD["Patient"], "birthDate": "nope"}),
             "{broken"]
    stats = validate_text("2026-01-01", "Patient", "\n".join(lines))
    assert (stats["rows_in"], stats["valid"], stats["rejected"]) == (3, 1, 2)
    load_blob_as("2026-01-01", "Patient", stats["rows_in"], "test/blob")
    con = duckdb.connect(str(env / "wh.duckdb"), read_only=True)
    rows = con.execute("select resource_type, reason from raw.quarantine order by reason").fetchall()
    assert len(rows) == 2
    assert all(r[0] == "Patient" for r in rows)
    assert any("birthDate" in r[1] for r in rows)
    assert any("malformed JSON" in r[1] for r in rows)
    assert con.execute("select count(*) from raw.raw_patient").fetchone() == (1,)
