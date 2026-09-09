"""Synthetic second review protects against transcribed or calculated errors."""
import copy
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.effect_verification import (
    create_effect_verification,
    validate_effect_verification_boundary,
)


def mapped_claim(study):
    suffix = "1" if study == "s1" else "2"
    return {"extraction_id": f"claim-{suffix}", "extraction_claim_sha256": "a" * 64,
            "source_id": f"source-{suffix}", "source_retained_file_sha256": "b" * 64,
            "result_direction": "mixed", "interpretive_ceiling": "reviewed_source_claim",
            "citation_verdict": "supported", "citation_checked_location": f"page {suffix}"}


def verification_claim_source(study):
    claim = mapped_claim(study)
    return {
        key: claim[key]
        for key in (
            "extraction_id",
            "extraction_claim_sha256",
            "source_id",
            "source_retained_file_sha256",
            "citation_checked_location",
        )
    }


def source_summary_digest(summary):
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_summary(study_id, status="available"):
    if status == "unavailable":
        return {"study_id": study_id, "status": status, "reason": "No compatible outcome",
                "evidence_location": "results", "experimental": None, "comparator": None}
    return {"study_id": study_id, "status": status, "reason": "Reported arms",
            "evidence_location": "table 1",
            "experimental": {"sample_size": 25, "mean": 4.0, "standard_deviation": 2.0},
            "comparator": {"sample_size": 25, "mean": 3.0, "standard_deviation": 1.0}}


def effects_file(tmp_path):
    summaries = [source_summary("s1"), source_summary("s2", "unavailable")]
    value = {"effect_records_version": 1, "status": "effects_ready",
        "derivation_scope": "recomputed_from_source_reported_arm_summaries", "reviewer": "Effect reviewer",
        "plan_id": "p1", "snapshot_id": "snap", "effect_measure": "mean_difference",
        "source_summaries": summaries, "records": [
            {"study_id": "s1", "status": "available", "reason": "Reported arms",
             "risk_of_bias": "low", "mapped_claims": [mapped_claim("s1")],
             "effect_measure": "mean_difference", "estimate": 1.0,
             "standard_error": 0.4472135954999579, "variance": 0.2,
             "sample_size": 50, "evidence_location": "table 1",
             "derivation": "Recomputed from retained arm summaries"},
            {"study_id": "s2", "status": "unavailable", "reason": "No compatible outcome",
             "risk_of_bias": "unclear", "mapped_claims": [mapped_claim("s2")],
             "effect_measure": "mean_difference", "estimate": None,
             "standard_error": None, "variance": None, "sample_size": None,
             "evidence_location": "results", "derivation": "No compatible outcome"}],
        "study_count": 2, "available_effect_count": 1, "unavailable_effect_count": 1,
        "minimum_independent_studies": 1, "scientific_evidence_eligible": False,
        "conclusion_authorized": False, "publication_authorized": False,
        "limitations": [
            "Effect values are reviewer assertions.",
            "Unavailable statistics remain explicit.",
        ]}
    encoded = (json.dumps(value, sort_keys=True) + "\n").encode(); path = tmp_path / "effects.json"; path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def review(match=True):
    return {"reviewer": "Independent checker", "assessments": [
        {"study_id": "s1", "source_values_match": match, "calculation_matches": True,
         "checked_location": "table 1", "rationale": "Checked source and arithmetic"},
        {"study_id": "s2", "source_values_match": None, "calculation_matches": None,
         "checked_location": "results", "rationale": "Confirmed unavailable"}]}


def test_effect_verification_cli_records_clean_independent_review(tmp_path, capsys):
    effects, digest = effects_file(tmp_path); review_path = tmp_path / "review.json"; review_path.write_text(json.dumps(review()))
    output = tmp_path / "verification"
    assert main(["--json", "literature", "verify-effects", "--effects-file", str(effects),
        "--expected-effects-sha256", digest, "--review-file", str(review_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "effect_verification_recorded" and result["independent_review"] is True
    assert result["scientific_evidence_eligible"] is False
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    assert result["assessments"][0]["retained_source_summary_sha256"] == source_summary_digest(source_summary("s1"))
    assert result["assessments"][1]["retained_source_summary_sha256"] == source_summary_digest(source_summary("s2", "unavailable"))
    with pytest.raises(ValidationError, match="already exists"):
        create_effect_verification(effects, digest, review(), output)


def test_mismatch_is_preserved_and_requires_review(tmp_path):
    effects, digest = effects_file(tmp_path)
    result = create_effect_verification(effects, digest, review(False), tmp_path / "verification")
    assert result["status"] == "review_required" and result["mismatch_study_ids"] == ["s1"]


def test_effect_verification_preserves_canonical_study_handles(tmp_path):
    effects, digest = effects_file(tmp_path)
    result = create_effect_verification(effects, digest, review(), tmp_path / "verification")
    assert result["assessments"][0]["study_id"] == "s1"
    assert result["assessments"][0]["checked_location"] == "table 1"
    assert result["assessments"][0]["claim_source_provenance"] == [verification_claim_source("s1")]
    assert result["assessments"][0]["retained_source_summary_sha256"] == source_summary_digest(source_summary("s1"))


@pytest.mark.parametrize("tamper", [
    "version",
    "effects-hash",
    "plan-id",
    "snapshot-id",
    "independent-review",
    "same-reviewer",
    "assessment-extra",
    "summary-digest",
    "missing-claim-source",
    "duplicate-claim-source",
    "padded-claim-location",
    "padded-rationale",
    "availability-bool",
    "mismatch-drift",
    "status-drift",
])
def test_effect_verification_boundary_replays_retained_assessments(tmp_path, tamper):
    effects, digest = effects_file(tmp_path)
    result = create_effect_verification(effects, digest, review(), tmp_path / "verification")
    candidate = copy.deepcopy(result)
    if tamper == "version":
        candidate["effect_verification_version"] = 2
    elif tamper == "effects-hash":
        candidate["effect_records_sha256"] = "A" * 64
    elif tamper == "plan-id":
        candidate["plan_id"] = " p1 "
    elif tamper == "snapshot-id":
        candidate["snapshot_id"] = " snap "
    elif tamper == "independent-review":
        candidate["independent_review"] = False
    elif tamper == "same-reviewer":
        candidate["verification_reviewer"] = candidate["effect_reviewer"].upper()
    elif tamper == "assessment-extra":
        candidate["assessments"][0]["extra"] = "not retained"
    elif tamper == "summary-digest":
        candidate["assessments"][0]["retained_source_summary_sha256"] = "A" * 64
    elif tamper == "missing-claim-source":
        candidate["assessments"][0]["claim_source_provenance"] = []
    elif tamper == "duplicate-claim-source":
        candidate["assessments"][0]["claim_source_provenance"].append(
            verification_claim_source("s1")
        )
    elif tamper == "padded-claim-location":
        candidate["assessments"][0]["claim_source_provenance"][0][
            "citation_checked_location"
        ] = " page 1 "
    elif tamper == "padded-rationale":
        candidate["assessments"][0]["rationale"] = " Checked source and arithmetic "
    elif tamper == "availability-bool":
        candidate["assessments"][1]["source_values_match"] = False
    elif tamper == "mismatch-drift":
        candidate["assessments"][0]["calculation_matches"] = False
    elif tamper == "status-drift":
        candidate["status"] = "review_required"
    with pytest.raises(ValidationError):
        validate_effect_verification_boundary(candidate)


@pytest.mark.parametrize("failure", [
    "hash",
    "same-reviewer",
    "padded-reviewer",
    "padded-effect-reviewer",
    "padded-effect-study",
    "padded-summary-study",
    "missing",
    "duplicate",
    "padded-duplicate",
    "summary-duplicate",
    "summary-status-drift",
    "summary-padded-reason",
    "summary-padded-location",
    "summary-arm-shape",
    "summary-arm-bool",
    "summary-events-over-n",
    "summary-unavailable-arm",
    "summary-measure",
    "missing-claim-provenance",
    "duplicate-claim-provenance",
    "padded-claim-source",
    "bad-source-anchor",
    "available-null",
    "unavailable-bool",
    "location",
    "padded-location",
    "padded-rationale",
    "authority",
    "conclusion-authority",
    "publication-authority",
    "limitations-missing",
    "count-drift",
    "availability-count-drift",
    "readiness-drift",
])
def test_invalid_effect_verification_never_publishes(tmp_path, failure):
    effects, digest = effects_file(tmp_path); candidate = review()
    if failure == "hash": digest = "0" * 64
    elif failure == "same-reviewer": candidate["reviewer"] = "Effect reviewer"
    elif failure == "padded-reviewer": candidate["reviewer"] = " Independent checker "
    elif failure in {"padded-effect-reviewer", "padded-effect-study", "padded-summary-study"}:
        value = json.loads(effects.read_text())
        if failure == "padded-effect-reviewer":
            value["reviewer"] = " Effect reviewer "
        elif failure == "padded-effect-study":
            value["records"][0]["study_id"] = " s1 "
        elif failure == "padded-summary-study":
            value["source_summaries"][0]["study_id"] = " s1 "
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        effects.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "missing": candidate["assessments"].pop()
    elif failure == "duplicate": candidate["assessments"][1]["study_id"] = "s1"
    elif failure == "padded-duplicate": candidate["assessments"][1]["study_id"] = " s1 "
    elif failure == "summary-duplicate":
        value = json.loads(effects.read_text())
        value["source_summaries"][1]["study_id"] = " s1 "
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        effects.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure in {
        "summary-status-drift",
        "summary-padded-reason",
        "summary-padded-location",
        "summary-arm-shape",
        "summary-arm-bool",
        "summary-events-over-n",
        "summary-unavailable-arm",
        "summary-measure",
    }:
        value = json.loads(effects.read_text())
        if failure == "summary-status-drift":
            value["source_summaries"][0]["status"] = "unavailable"
        elif failure == "summary-padded-reason":
            value["source_summaries"][0]["reason"] = " Reported arms "
        elif failure == "summary-padded-location":
            value["source_summaries"][0]["evidence_location"] = " table 1 "
        elif failure == "summary-arm-shape":
            value["source_summaries"][0]["experimental"]["extra"] = 1
        elif failure == "summary-arm-bool":
            value["source_summaries"][0]["experimental"]["sample_size"] = True
        elif failure == "summary-events-over-n":
            value["effect_measure"] = "log_risk_ratio"
            value["source_summaries"][0]["experimental"] = {"sample_size": 10, "events": 11}
            value["source_summaries"][0]["comparator"] = {"sample_size": 10, "events": 5}
        elif failure == "summary-unavailable-arm":
            value["source_summaries"][1]["experimental"] = {
                "sample_size": 10,
                "mean": 1.0,
                "standard_deviation": 1.0,
            }
        elif failure == "summary-measure":
            value["effect_measure"] = "odds_ratio"
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        effects.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "missing-claim-provenance":
        value = json.loads(effects.read_text())
        value["records"][0]["mapped_claims"] = []
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        effects.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "duplicate-claim-provenance":
        value = json.loads(effects.read_text())
        value["records"][0]["mapped_claims"].append(mapped_claim("s1"))
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        effects.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "padded-claim-source":
        value = json.loads(effects.read_text())
        value["records"][0]["mapped_claims"][0]["source_id"] = " source-1 "
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        effects.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "bad-source-anchor":
        value = json.loads(effects.read_text())
        value["records"][0]["mapped_claims"][0]["source_retained_file_sha256"] = "B" * 64
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        effects.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure in {"authority", "conclusion-authority", "publication-authority",
                     "limitations-missing", "count-drift", "availability-count-drift",
                     "readiness-drift"}:
        value = json.loads(effects.read_text())
        if failure == "authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "publication-authority":
            value["publication_authorized"] = True
        elif failure == "limitations-missing":
            value["limitations"] = []
        elif failure == "count-drift":
            value["study_count"] = 3
        elif failure == "availability-count-drift":
            value["available_effect_count"] = 2
        elif failure == "readiness-drift":
            value["status"] = "insufficient_effects"
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        effects.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "available-null": candidate["assessments"][0]["source_values_match"] = None
    elif failure == "unavailable-bool": candidate["assessments"][1]["calculation_matches"] = True
    elif failure == "location": candidate["assessments"][0]["checked_location"] = ""
    elif failure == "padded-location": candidate["assessments"][0]["checked_location"] = " table 1 "
    elif failure == "padded-rationale": candidate["assessments"][0]["rationale"] = " Checked source and arithmetic "
    output = tmp_path / "verification"
    with pytest.raises(ValidationError): create_effect_verification(effects, digest, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_effect_verification_rejects_malformed_expected_effects_hash(tmp_path, expected):
    effects, _ = effects_file(tmp_path)
    output = tmp_path / "verification"
    with pytest.raises(ValidationError, match="expected_effects_sha256 must be a lowercase SHA-256 digest"):
        create_effect_verification(effects, expected, review(), output)
    assert not output.exists()
