import json

from generator.generate_fhir import generate, make_update_batch

from fhir_pipeline.validate import Accepted, validate_line


def test_same_seed_same_output():
    a, b = generate(50, 7), generate(50, 7)
    assert a.lines == b.lines


def test_clean_and_edge_runs_share_base_data():
    clean = generate(50, 7, with_edge_cases=False)
    edge = generate(50, 7, with_edge_cases=True)
    assert clean.counts["Patient"] == 50
    assert edge.counts["Patient"] > clean.counts["Patient"]


def test_edge_cases_present():
    bundle = generate(200, 3)
    enc_lines = bundle.lines["Encounter"]
    assert len(enc_lines) != len(set(enc_lines)), "expected exact duplicate lines"
    ids = [json.loads(x)["id"] for x in enc_lines if x.startswith("{") and x.endswith("}")]
    assert len(ids) != len(set(ids))
    assert any(not x.endswith("}") for x in bundle.lines["Observation"]), "truncated JSON line"
    assert any("not-a-status" in x for x in enc_lines)


def test_late_update_is_written_before_original():
    bundle = generate(200, 3)
    first = json.loads(bundle.lines["Encounter"][0])
    originals = [json.loads(x) for x in bundle.lines["Encounter"][1:]
                 if x.endswith("}") and json.loads(x)["id"] == first["id"]]
    assert originals, "the late update must have an older original later in the file"
    assert first["meta"]["lastUpdated"] > originals[0]["meta"]["lastUpdated"]


def test_clean_run_is_fully_valid():
    bundle = generate(30, 5, with_edge_cases=False)
    for rtype, lines in bundle.lines.items():
        assert all(isinstance(validate_line(rtype, x), Accepted) for x in lines)


def test_update_batch_ids_are_new_or_existing_encounters():
    base_ids = {json.loads(x)["id"] for x in generate(100, 11).lines["Encounter"]
                if x.endswith("}")}
    batch = make_update_batch(11, 100, 5, 3)
    ids = [json.loads(x)["id"] for x in batch.lines["Encounter"]]
    assert sum(i.startswith("enc-new-") for i in ids) == 3
    assert all(i in base_ids for i in ids if not i.startswith("enc-new-"))
