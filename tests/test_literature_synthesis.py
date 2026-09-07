"""Synthetic qualitative synthesis verifies commitments without claiming truth."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.synthesis import execute_qualitative_synthesis


def write_json(path, value):
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def artifacts(tmp_path, minimum=1, synthesis_type="qualitative"):
    screening_sha = "1" * 64
    plan = tmp_path / "plan.json"
    plan_sha = write_json(plan, {"synthesis_plan_version": 1, "status": "synthesis_plan_frozen",
        "synthesis_type": synthesis_type, "screening_sha256": screening_sha, "snapshot_id": "snap",
        "plan_id": "p1", "research_question": "Fixture?", "primary_outcome": "Outcome",
        "conclusion_rule": "Bound all wording", "minimum_independent_studies": minimum,
        "included_source_ids_at_freeze": ["s1"]})
    extraction = tmp_path / "extraction.json"
    extraction_sha = write_json(extraction, {"extraction_version": 1, "status": "extraction_recorded",
        "screening_sha256": screening_sha, "snapshot_id": "snap",
        "source_reviews": [{"source_id": "s1"}]})
    claim = {"extraction_id": "e1", "study_id": "study-1", "source_id": "s1",
        "extracted_evidence_location": "page 1", "claim_text": "Synthetic null result",
        "epistemic_layer": "inferred", "result_direction": "null",
        "uncertainty": "Wide", "citation_checked_location": "page 1",
        "citation_rationale": "fixture reviewer check", "citation_verdict": "supported", "risk_of_bias": "high",
        "bias_domain_judgments": [
            {"domain": "selection", "judgment": "high", "evidence_locations": ["table 1"]}
        ],
        "interpretive_ceiling": "insufficient_for_conclusion"}
    evidence_map = tmp_path / "map.json"
    map_sha = write_json(evidence_map, {"evidence_map_version": 1, "status": "evidence_map_recorded",
        "snapshot_id": "snap", "inputs": {"extraction_sha256": extraction_sha}, "claims": [claim]})
    deviations = tmp_path / "deviations.json"
    deviations_sha = write_json(deviations, {"synthesis_deviations_version": 1,
        "synthesis_plan_sha256": plan_sha, "status": "no_deviations_declared", "deviations": [],
        "frozen_plan_commitments": {
            "synthesis_type": synthesis_type,
            "minimum_independent_studies": minimum,
            "conclusion_rule": "Bound all wording",
        }})
    return plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha


def test_qualitative_synthesis_cli_preserves_null_high_bias_claim_and_is_write_once(tmp_path, capsys):
    plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha = artifacts(tmp_path)
    output = tmp_path / "synthesis"
    assert main(["--json", "literature", "synthesize", "--plan-file", str(plan),
        "--expected-plan-sha256", plan_sha, "--extraction-file", str(extraction),
        "--evidence-map-file", str(evidence_map), "--expected-evidence-map-sha256", map_sha,
        "--deviations-file", str(deviations), "--expected-deviations-sha256", deviations_sha,
        "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["result_direction_counts"]["null"] == 1
    assert result["interpretive_ceiling_counts"]["insufficient_for_conclusion"] == 1
    assert result["claims"][0]["citation_checked_location"] == "page 1"
    assert result["claims"][0]["bias_domain_judgments"][0]["judgment"] == "high"
    assert result["deviation_plan_commitments"]["synthesis_type"] == "qualitative"
    assert result["publication_authorized"] is False
    assert "No automated substantive conclusion" in result["bounded_conclusion"]
    with pytest.raises(ValidationError, match="already exists"):
        execute_qualitative_synthesis(plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha, output)


def test_unmet_minimum_is_validly_recorded_without_conclusion(tmp_path):
    plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha = artifacts(tmp_path, minimum=2)
    result = execute_qualitative_synthesis(plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha, tmp_path / "synthesis")
    assert result["status"] == "insufficient_independent_studies"
    assert result["minimum_study_requirement_met"] is False
    assert result["bounded_conclusion"].startswith("No conclusion")


def test_retrospective_deviation_is_embedded_and_forces_review(tmp_path):
    plan, plan_sha, extraction, evidence_map, map_sha, deviations, _ = artifacts(tmp_path)
    value = json.loads(deviations.read_text())
    value["status"] = "retrospective_or_uncertain_deviation_review_required"
    value["deviations"] = [{"deviation_id": "d1", "timing": "after_results_seen",
                            "evidence_location": "review log section 3"}]
    deviations_sha = write_json(deviations, value)
    result = execute_qualitative_synthesis(
        plan, plan_sha, extraction, evidence_map, map_sha,
        deviations, deviations_sha, tmp_path / "synthesis",
    )
    assert result["status"] == "deviation_review_required"
    assert result["deviations"] == value["deviations"]
    assert result["inputs"]["synthesis_deviations_sha256"] == deviations_sha


def test_qualitative_synthesis_normalizes_source_and_claim_handles(tmp_path):
    plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha = artifacts(tmp_path)
    value = json.loads(plan.read_text())
    value["included_source_ids_at_freeze"] = [" s1 "]
    plan_sha = write_json(plan, value)
    value = json.loads(extraction.read_text())
    value["source_reviews"][0]["source_id"] = " s1 "
    extraction_sha = write_json(extraction, value)
    value = json.loads(evidence_map.read_text())
    value["inputs"]["extraction_sha256"] = extraction_sha
    value["claims"][0]["extraction_id"] = " e1 "
    value["claims"][0]["study_id"] = " study-1 "
    value["claims"][0]["source_id"] = " s1 "
    value["claims"][0]["bias_domain_judgments"][0]["domain"] = " selection "
    value["claims"][0]["bias_domain_judgments"][0]["evidence_locations"] = [" table 1 "]
    map_sha = write_json(evidence_map, value)
    value = json.loads(deviations.read_text())
    value["synthesis_plan_sha256"] = plan_sha
    deviations_sha = write_json(deviations, value)
    result = execute_qualitative_synthesis(
        plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha,
        tmp_path / "synthesis",
    )
    assert result["claims"][0]["extraction_id"] == "e1"
    assert result["claims"][0]["study_id"] == "study-1"
    assert result["claims"][0]["source_id"] == "s1"
    assert result["claims"][0]["bias_domain_judgments"][0]["domain"] == "selection"
    assert result["claims"][0]["bias_domain_judgments"][0]["evidence_locations"] == ["table 1"]


@pytest.mark.parametrize("failure", ["plan-hash", "map-hash", "quantitative", "screening", "source-drift", "padded-source-duplicate", "map-link", "snapshot", "claim", "padded-claim-duplicate", "deviation-plan"])
def test_invalid_synthesis_chain_never_publishes(tmp_path, failure):
    plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha = artifacts(tmp_path, synthesis_type="quantitative" if failure == "quantitative" else "qualitative")
    if failure == "plan-hash": plan_sha = "0" * 64
    elif failure == "map-hash": map_sha = "0" * 64
    elif failure == "screening":
        value = json.loads(extraction.read_text()); value["screening_sha256"] = "2" * 64; write_json(extraction, value)
    elif failure == "source-drift":
        value = json.loads(plan.read_text()); value["included_source_ids_at_freeze"] = ["other-source"]; plan_sha = write_json(plan, value)
    elif failure == "padded-source-duplicate":
        value = json.loads(extraction.read_text()); value["source_reviews"].append({"source_id": " s1 "}); write_json(extraction, value)
    elif failure == "map-link":
        value = json.loads(evidence_map.read_text()); value["inputs"]["extraction_sha256"] = "0" * 64; map_sha = write_json(evidence_map, value)
    elif failure == "snapshot":
        value = json.loads(evidence_map.read_text()); value["snapshot_id"] = "other"; map_sha = write_json(evidence_map, value)
    elif failure == "claim":
        value = json.loads(evidence_map.read_text()); del value["claims"][0]["uncertainty"]; map_sha = write_json(evidence_map, value)
    elif failure == "padded-claim-duplicate":
        value = json.loads(evidence_map.read_text())
        duplicate = dict(value["claims"][0])
        duplicate["extraction_id"] = " e1 "
        value["claims"].append(duplicate)
        map_sha = write_json(evidence_map, value)
    elif failure == "deviation-plan":
        value = json.loads(deviations.read_text()); value["frozen_plan_commitments"]["minimum_independent_studies"] = 99; deviations_sha = write_json(deviations, value)
    output = tmp_path / "synthesis"
    with pytest.raises(ValidationError):
        execute_qualitative_synthesis(plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha, output)
    assert not output.exists()
