"""Synthetic effect records validate provenance and variance, not scientific truth."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.effects import create_effect_records


def write_json(path, value):
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode(); path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def artifacts(tmp_path, minimum=1):
    screening_sha = "1" * 64
    plan = tmp_path / "plan.json"
    plan_sha = write_json(plan, {"synthesis_plan_version": 1, "status": "synthesis_plan_frozen",
        "synthesis_type": "quantitative", "effect_measure": "log_risk_ratio",
        "minimum_independent_studies": minimum, "screening_sha256": screening_sha,
        "snapshot_id": "snap", "plan_id": "p1", "included_source_ids_at_freeze": ["source-fixture"]})
    extraction = tmp_path / "extraction.json"
    extraction_sha = write_json(extraction, {"extraction_version": 1, "status": "extraction_recorded",
        "screening_sha256": screening_sha, "snapshot_id": "snap",
        "source_reviews": [{"source_id": "source-fixture"}]})
    evidence_map = tmp_path / "map.json"
    claim_template = {
        "source_id": "source-fixture",
        "result_direction": "mixed",
        "interpretive_ceiling": "reviewed_source_claim",
        "citation_verdict": "supported",
        "citation_checked_location": "page fixture",
    }
    map_sha = write_json(evidence_map, {"evidence_map_version": 1, "status": "evidence_map_recorded",
        "snapshot_id": "snap", "inputs": {"extraction_sha256": extraction_sha},
        "claims": [{"study_id": "study-1", "risk_of_bias": "low",
                    "extraction_id": "claim-1", **claim_template},
                   {"study_id": "study-2", "risk_of_bias": "high",
                    "extraction_id": "claim-2", **claim_template}]})
    return plan, plan_sha, extraction, evidence_map, map_sha


def review(second="unavailable"):
    def record(study_id, status):
        available = status == "available"
        return {"study_id": study_id, "status": status, "reason": "Fixture record",
            "effect_measure": "log_risk_ratio", "estimate": 0.2 if available else None,
            "standard_error": 0.1 if available else None, "sample_size": 40 if available else None,
            "evidence_location": "table 2", "derivation": "Reported estimate and standard error"}
    return {"reviewer": "Effect reviewer", "records": [record("study-1", "available"), record("study-2", second)]}


def test_effect_cli_preserves_unavailable_study_and_is_write_once(tmp_path, capsys):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path)
    review_path = tmp_path / "review.json"; review_path.write_text(json.dumps(review()))
    output = tmp_path / "effects"
    assert main(["--json", "literature", "prepare-effects", "--plan-file", str(plan),
        "--expected-plan-sha256", plan_sha, "--extraction-file", str(extraction),
        "--evidence-map-file", str(evidence_map), "--expected-evidence-map-sha256", map_sha,
        "--review-file", str(review_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["available_effect_count"] == 1 and result["unavailable_effect_count"] == 1
    assert result["records"][0]["variance"] == pytest.approx(0.01)
    assert result["records"][1]["risk_of_bias"] == "high"
    assert result["records"][0]["mapped_claims"][0]["extraction_id"] == "claim-1"
    assert result["records"][0]["mapped_claims"][0]["citation_checked_location"] == "page fixture"
    assert result["scientific_evidence_eligible"] is False
    with pytest.raises(ValidationError, match="already exists"):
        create_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, review(), output)


def test_insufficient_effects_is_recorded(tmp_path):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path, minimum=2)
    result = create_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, review(), tmp_path / "effects")
    assert result["status"] == "insufficient_effects"


def test_effect_records_normalize_study_and_source_handles(tmp_path):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path)
    value = json.loads(plan.read_text())
    value["included_source_ids_at_freeze"] = [" source-fixture "]
    plan_sha = write_json(plan, value)
    value = json.loads(extraction.read_text())
    value["source_reviews"][0]["source_id"] = " source-fixture "
    extraction_sha = write_json(extraction, value)
    value = json.loads(evidence_map.read_text())
    value["inputs"]["extraction_sha256"] = extraction_sha
    value["claims"][0]["study_id"] = " study-1 "
    value["claims"][0]["source_id"] = " source-fixture "
    map_sha = write_json(evidence_map, value)
    candidate = review()
    candidate["records"][0]["study_id"] = " study-1 "
    result = create_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, candidate, tmp_path / "effects")
    assert result["records"][0]["study_id"] == "study-1"
    assert result["records"][0]["mapped_claims"][0]["source_id"] == "source-fixture"


@pytest.mark.parametrize("failure", [
    "plan-hash", "map-hash", "measure", "missing", "duplicate", "padded-duplicate",
    "extraction-source-duplicate", "nan", "se", "bool-n", "unavailable-value",
    "plan-source-missing", "plan-source-drift", "map-provenance",
])
def test_invalid_effect_records_never_publish(tmp_path, failure):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path)
    candidate = review()
    if failure == "plan-hash": plan_sha = "0" * 64
    elif failure == "map-hash": map_sha = "0" * 64
    elif failure == "measure": candidate["records"][0]["effect_measure"] = "odds_ratio"
    elif failure == "missing": candidate["records"].pop()
    elif failure == "duplicate": candidate["records"][1]["study_id"] = "study-1"
    elif failure == "padded-duplicate": candidate["records"][1]["study_id"] = " study-1 "
    elif failure == "extraction-source-duplicate":
        value = json.loads(extraction.read_text())
        value["source_reviews"].append({"source_id": " source-fixture "})
        write_json(extraction, value)
    elif failure == "nan": candidate["records"][0]["estimate"] = float("nan")
    elif failure == "se": candidate["records"][0]["standard_error"] = 0
    elif failure == "bool-n": candidate["records"][0]["sample_size"] = True
    elif failure == "unavailable-value": candidate["records"][1]["estimate"] = 0.0
    elif failure == "plan-source-missing":
        value = json.loads(plan.read_text())
        del value["included_source_ids_at_freeze"]
        plan_sha = write_json(plan, value)
    elif failure == "plan-source-drift":
        value = json.loads(plan.read_text())
        value["included_source_ids_at_freeze"] = ["other-source"]
        plan_sha = write_json(plan, value)
    elif failure == "map-provenance":
        value = json.loads(evidence_map.read_text())
        value["claims"][0]["citation_checked_location"] = ""
        map_sha = write_json(evidence_map, value)
    output = tmp_path / "effects"
    with pytest.raises(ValidationError):
        create_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize(("field", "expected"), [
    ("plan", " A" * 32),
    ("map", "g" * 64),
])
def test_effect_records_reject_malformed_expected_hashes(tmp_path, field, expected):
    plan, plan_sha, extraction, evidence_map, map_sha = artifacts(tmp_path)
    if field == "plan":
        plan_sha = expected
        message = "expected_plan_sha256 must be a lowercase SHA-256 digest"
    else:
        map_sha = expected
        message = "expected_evidence_map_sha256 must be a lowercase SHA-256 digest"
    output = tmp_path / "effects"
    with pytest.raises(ValidationError, match=message):
        create_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, review(), output)
    assert not output.exists()
