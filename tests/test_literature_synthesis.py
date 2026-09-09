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


def claim_digest(source_id, record, source_retained_file_sha256="legacy_missing"):
    payload = {
        "source_id": source_id,
        "extraction_id": record["extraction_id"],
        "study_id": record["study_id"],
        "claim_text": record["claim_text"],
        "evidence_location": record["evidence_location"],
        "epistemic_layer": record["epistemic_layer"],
        "result_direction": record["result_direction"],
        "uncertainty": record["uncertainty"],
        "notes": record["notes"],
    }
    if source_retained_file_sha256 != "legacy_missing":
        payload["source_retained_file_sha256"] = source_retained_file_sha256
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def artifacts(tmp_path, minimum=1, synthesis_type="qualitative"):
    screening_sha = "1" * 64
    plan = tmp_path / "plan.json"
    plan_sha = write_json(plan, {"synthesis_plan_version": 1, "status": "synthesis_plan_frozen",
        "synthesis_type": synthesis_type, "screening_sha256": screening_sha, "snapshot_id": "snap",
        "plan_id": "p1", "research_question": "Fixture?", "primary_outcome": "Outcome",
        "conclusion_rule": "Bound all wording", "minimum_independent_studies": minimum,
        "included_source_ids_at_freeze": ["s1"]})
    extraction = tmp_path / "extraction.json"
    extraction_record = {"extraction_id": "e1", "study_id": "study-1",
        "claim_text": "Synthetic null result", "evidence_location": "page 1",
        "epistemic_layer": "inferred", "result_direction": "null",
        "uncertainty": "Wide", "notes": "fixture notes"}
    extraction_sha = write_json(extraction, {"extraction_version": 1, "status": "extraction_recorded",
        "screening_sha256": screening_sha, "snapshot_id": "snap", "record_count": 1,
        "scientific_evidence_eligible": False,
        "limitations": [
            "Records are reviewer assertions bound to source IDs and locations; the machine has not verified that source text supports them.",
            "Extraction does not perform risk-of-bias assessment, resolve disagreements, accept claims as facts, or conduct synthesis.",
        ],
        "source_reviews": [{"source_id": "s1", "records": [extraction_record]}]})
    claim = {"extraction_id": "e1", "study_id": "study-1", "source_id": "s1",
        "extracted_evidence_location": "page 1", "claim_text": "Synthetic null result",
        "extraction_claim_sha256": claim_digest("s1", extraction_record),
        "epistemic_layer": "inferred", "result_direction": "null",
        "uncertainty": "Wide", "citation_checked_location": "page 1",
        "citation_rationale": "fixture reviewer check", "citation_verdict": "supported", "risk_of_bias": "high",
        "bias_domain_judgments": [
            {"domain": "selection", "judgment": "high", "evidence_locations": ["table 1"]}
        ],
        "interpretive_ceiling": "insufficient_for_conclusion"}
    evidence_map = tmp_path / "map.json"
    limitations = [
        "This deterministic map joins reviewed assertions without authorizing conclusions."
    ]
    map_sha = write_json(evidence_map, {"evidence_map_version": 1, "status": "evidence_map_recorded",
        "snapshot_id": "snap", "inputs": {"extraction_sha256": extraction_sha}, "claims": [claim],
        "claim_count": 1, "study_count": 1,
        "interpretive_ceiling_counts": {"insufficient_for_conclusion": 1},
        "scientific_evidence_eligible": False, "conclusion_authorized": False,
        "limitations": limitations})
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
    extraction_record = json.loads(extraction.read_text())["source_reviews"][0]["records"][0]
    assert result["claims"][0]["extraction_claim_sha256"] == claim_digest("s1", extraction_record)
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


def test_qualitative_synthesis_preserves_canonical_source_and_claim_handles(tmp_path):
    plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha = artifacts(tmp_path)
    result = execute_qualitative_synthesis(
        plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha,
        tmp_path / "synthesis",
    )
    assert result["claims"][0]["extraction_id"] == "e1"
    assert result["claims"][0]["study_id"] == "study-1"
    assert result["claims"][0]["source_id"] == "s1"
    assert result["claims"][0]["bias_domain_judgments"][0]["domain"] == "selection"
    assert result["claims"][0]["bias_domain_judgments"][0]["evidence_locations"] == ["table 1"]


@pytest.mark.parametrize("failure", [
    "plan-hash",
    "map-hash",
    "quantitative",
    "screening",
    "extraction-authority",
    "extraction-count-drift",
    "extraction-limitations-missing",
    "extraction-padded-limitation",
    "extraction-claim-payload",
    "extraction-extra-claim",
    "source-drift",
    "padded-plan-source",
    "padded-source-duplicate",
    "padded-extraction-source",
    "map-link",
    "map-authority",
    "map-claim-count",
    "map-ceiling-count",
    "map-boundary-limitations",
    "snapshot",
    "claim",
    "padded-claim-id",
    "padded-claim-duplicate",
    "padded-claim-study",
    "padded-claim-source",
    "padded-extracted-location",
    "padded-citation-location",
    "padded-citation-rationale",
    "claim-digest",
    "padded-domain",
    "padded-domain-location",
    "deviation-plan",
])
def test_invalid_synthesis_chain_never_publishes(tmp_path, failure):
    plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha = artifacts(tmp_path, synthesis_type="quantitative" if failure == "quantitative" else "qualitative")
    if failure == "plan-hash": plan_sha = "0" * 64
    elif failure == "map-hash": map_sha = "0" * 64
    elif failure == "screening":
        value = json.loads(extraction.read_text()); value["screening_sha256"] = "2" * 64; write_json(extraction, value)
    elif failure in {
        "extraction-authority",
        "extraction-count-drift",
        "extraction-limitations-missing",
        "extraction-padded-limitation",
        "extraction-claim-payload",
        "extraction-extra-claim",
    }:
        value = json.loads(extraction.read_text())
        if failure == "extraction-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "extraction-count-drift":
            value["record_count"] = 2
        elif failure == "extraction-limitations-missing":
            value["limitations"] = []
        elif failure == "extraction-padded-limitation":
            value["limitations"][0] = " " + value["limitations"][0]
        elif failure == "extraction-claim-payload":
            value["source_reviews"][0]["records"][0]["notes"] = "changed notes"
        elif failure == "extraction-extra-claim":
            duplicate = dict(value["source_reviews"][0]["records"][0])
            duplicate["extraction_id"] = "e2"
            value["source_reviews"][0]["records"].append(duplicate)
            value["record_count"] = 2
        extraction_sha = write_json(extraction, value)
        value = json.loads(evidence_map.read_text()); value["inputs"]["extraction_sha256"] = extraction_sha; map_sha = write_json(evidence_map, value)
    elif failure == "source-drift":
        value = json.loads(plan.read_text()); value["included_source_ids_at_freeze"] = ["other-source"]; plan_sha = write_json(plan, value)
    elif failure == "padded-plan-source":
        value = json.loads(plan.read_text()); value["included_source_ids_at_freeze"] = [" s1 "]; plan_sha = write_json(plan, value)
        value = json.loads(deviations.read_text()); value["synthesis_plan_sha256"] = plan_sha; deviations_sha = write_json(deviations, value)
    elif failure == "padded-source-duplicate":
        value = json.loads(extraction.read_text()); value["source_reviews"].append({"source_id": " s1 "}); write_json(extraction, value)
    elif failure == "padded-extraction-source":
        value = json.loads(extraction.read_text())
        value["source_reviews"][0]["source_id"] = " s1 "
        extraction_sha = write_json(extraction, value)
        value = json.loads(evidence_map.read_text()); value["inputs"]["extraction_sha256"] = extraction_sha; map_sha = write_json(evidence_map, value)
    elif failure == "map-link":
        value = json.loads(evidence_map.read_text()); value["inputs"]["extraction_sha256"] = "0" * 64; map_sha = write_json(evidence_map, value)
    elif failure == "map-authority":
        value = json.loads(evidence_map.read_text()); value["conclusion_authorized"] = True; map_sha = write_json(evidence_map, value)
    elif failure == "map-claim-count":
        value = json.loads(evidence_map.read_text()); value["claim_count"] = 2; map_sha = write_json(evidence_map, value)
    elif failure == "map-ceiling-count":
        value = json.loads(evidence_map.read_text())
        value["interpretive_ceiling_counts"] = {"reviewed_source_claim": 1}
        map_sha = write_json(evidence_map, value)
    elif failure == "map-boundary-limitations":
        value = json.loads(evidence_map.read_text()); value["limitations"] = []; map_sha = write_json(evidence_map, value)
    elif failure == "snapshot":
        value = json.loads(evidence_map.read_text()); value["snapshot_id"] = "other"; map_sha = write_json(evidence_map, value)
    elif failure == "claim":
        value = json.loads(evidence_map.read_text()); del value["claims"][0]["uncertainty"]; map_sha = write_json(evidence_map, value)
    elif failure == "claim-digest":
        value = json.loads(evidence_map.read_text())
        value["claims"][0]["extraction_claim_sha256"] = "A" * 64
        map_sha = write_json(evidence_map, value)
    elif failure in {
        "padded-claim-id",
        "padded-claim-study",
        "padded-claim-source",
        "padded-extracted-location",
        "padded-citation-location",
        "padded-citation-rationale",
        "padded-domain",
        "padded-domain-location",
    }:
        value = json.loads(evidence_map.read_text())
        if failure == "padded-claim-id":
            value["claims"][0]["extraction_id"] = " e1 "
        elif failure == "padded-claim-study":
            value["claims"][0]["study_id"] = " study-1 "
        elif failure == "padded-claim-source":
            value["claims"][0]["source_id"] = " s1 "
        elif failure == "padded-extracted-location":
            value["claims"][0]["extracted_evidence_location"] = " page 1 "
        elif failure == "padded-citation-location":
            value["claims"][0]["citation_checked_location"] = " page 1 "
        elif failure == "padded-citation-rationale":
            value["claims"][0]["citation_rationale"] = " fixture reviewer check "
        elif failure == "padded-domain":
            value["claims"][0]["bias_domain_judgments"][0]["domain"] = " selection "
        elif failure == "padded-domain-location":
            value["claims"][0]["bias_domain_judgments"][0]["evidence_locations"] = [" table 1 "]
        map_sha = write_json(evidence_map, value)
    elif failure == "padded-claim-duplicate":
        value = json.loads(evidence_map.read_text())
        duplicate = dict(value["claims"][0])
        duplicate["extraction_id"] = "e1"
        value["claims"].append(duplicate)
        map_sha = write_json(evidence_map, value)
    elif failure == "deviation-plan":
        value = json.loads(deviations.read_text()); value["frozen_plan_commitments"]["minimum_independent_studies"] = 99; deviations_sha = write_json(deviations, value)
    output = tmp_path / "synthesis"
    with pytest.raises(ValidationError):
        execute_qualitative_synthesis(plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha, output)
    assert not output.exists()


@pytest.mark.parametrize(("field", "expected"), [
    ("plan", "A" * 64),
    ("map", "g" * 64),
    ("deviations", "0" * 63),
])
def test_qualitative_synthesis_rejects_malformed_expected_hashes(tmp_path, field, expected):
    plan, plan_sha, extraction, evidence_map, map_sha, deviations, deviations_sha = artifacts(tmp_path)
    if field == "plan":
        plan_sha = expected
        message = "expected_plan_sha256 must be a lowercase SHA-256 digest"
    elif field == "map":
        map_sha = expected
        message = "expected_evidence_map_sha256 must be a lowercase SHA-256 digest"
    else:
        deviations_sha = expected
        message = "expected_deviations_sha256 must be a lowercase SHA-256 digest"
    output = tmp_path / "synthesis"
    with pytest.raises(ValidationError, match=message):
        execute_qualitative_synthesis(
            plan, plan_sha, extraction, evidence_map, map_sha,
            deviations, deviations_sha, output,
        )
    assert not output.exists()
