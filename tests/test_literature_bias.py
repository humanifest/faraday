"""Synthetic risk-of-bias records; judgments are not scientific findings."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.bias import create_bias_assessment


DOMAINS = ["selection", "confounding", "exposure_or_intervention_classification",
    "deviations_from_intended_conditions", "missing_data", "outcome_measurement", "selective_reporting"]


def claim_digest(extraction_id, source_id, study_id, claim_text, evidence_location):
    payload = {
        "source_id": source_id,
        "extraction_id": extraction_id,
        "study_id": study_id,
        "claim_text": claim_text,
        "evidence_location": evidence_location,
        "epistemic_layer": "inferred",
        "result_direction": "supports",
        "uncertainty": "fixture",
        "notes": "fixture",
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def citation_assessment(extraction_id, source_id, verdict):
    study_id = "study-1"
    claim_text = f"Synthetic claim {extraction_id}"
    evidence_location = f"page {extraction_id[-1]}"
    return {
        "extraction_id": extraction_id,
        "study_id": study_id,
        "source_id": source_id,
        "source_retained_file_sha256": "legacy_missing",
        "claim_text": claim_text,
        "extracted_evidence_location": evidence_location,
        "extraction_claim_sha256": claim_digest(
            extraction_id, source_id, study_id, claim_text, evidence_location
        ),
        "verdict": verdict,
        "checked_location": evidence_location,
        "rationale": "Fixture citation rationale",
    }


def verification_file(tmp_path, status="citation_review_recorded"):
    value = {"citation_verification_version": 1, "status": status, "snapshot_id": "snap",
        "extraction_sha256": "1" * 64,
        "extraction_reviewer": "Extractor", "citation_reviewer": "Citation verifier",
        "independent_review": True,
        "verdict_counts": {"partially_supported": 1, "supported": 1, "unclear": 0, "unsupported": 0},
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "The machine binds an independent review to extraction bytes but does not interpret source text or authenticate either reviewer.",
            "A supported verdict is a reviewer judgment, not proof that a claim is true, unbiased, reproducible, or applicable.",
            "Risk-of-bias assessment, study-identity reconciliation, and quantitative synthesis remain separate gates.",
        ],
        "assessments": [
            citation_assessment("e1", "s1", "supported"),
            citation_assessment("e2", "s2", "partially_supported"),
        ]}
    encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
    path = tmp_path / "citation-verification.json"
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def review(judgment="low"):
    return {"reviewer": "Bias reviewer", "assessments": [{
        "study_id": "study-1", "study_design": "synthetic fixture", "source_ids": ["s1", "s2"],
        "domains": [{"domain": name, "judgment": judgment if name == "selection" else "low",
                     "rationale": "Fixture rationale", "evidence_locations": ["methods"]} for name in DOMAINS],
        "notes": "Generic fixture assessment",
    }]}


def test_bias_cli_computes_conservative_overall_and_is_write_once(tmp_path, capsys):
    verification, digest = verification_file(tmp_path)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review("high")))
    output = tmp_path / "bias"
    assert main(["--json", "literature", "assess-bias", "--citation-verification-file", str(verification),
        "--expected-citation-verification-sha256", digest, "--review-file", str(review_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["assessments"][0]["overall_judgment"] == "high"
    assert result["scientific_evidence_eligible"] is False
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    with pytest.raises(ValidationError, match="already exists"):
        create_bias_assessment(verification, digest, review("high"), output)


def test_bias_assessment_preserves_canonical_study_and_source_handles(tmp_path):
    verification, digest = verification_file(tmp_path)
    result = create_bias_assessment(verification, digest, review(), tmp_path / "bias")
    assert result["assessments"][0]["study_id"] == "study-1"
    assert result["assessments"][0]["source_ids"] == ["s1", "s2"]
    assert result["assessments"][0]["domains"][0]["evidence_locations"] == ["methods"]


@pytest.mark.parametrize("failure", [
    "hash",
    "unclean",
    "same-reviewer",
    "padded-reviewer",
    "padded-prior-reviewer",
    "citation-authority",
    "citation-conclusion-authority",
    "citation-publication-authority",
    "citation-not-independent",
    "citation-count-drift",
    "citation-limitations-missing",
    "citation-padded-limitation",
    "citation-unsupported-verdict",
    "citation-unclear-count",
    "citation-bad-verdict",
    "citation-duplicate-extraction",
    "citation-missing-contract-field",
    "citation-padded-checked-location",
    "citation-padded-rationale",
    "citation-claim-digest",
    "citation-source-anchor",
    "padded-citation-study",
    "padded-citation-source",
    "padded-citation-claim",
    "padded-citation-extracted-location",
    "missing-study",
    "duplicate-study",
    "source",
    "padded-study",
    "padded-source",
    "padded-source-duplicate",
    "domain",
    "location",
    "padded-location",
    "padded-rationale",
    "padded-design",
    "padded-notes",
    "judgment",
])
def test_invalid_bias_assessment_never_publishes(tmp_path, failure):
    verification, digest = verification_file(tmp_path, "review_required" if failure == "unclean" else "citation_review_recorded")
    candidate = review()
    if failure == "hash": digest = "0" * 64
    elif failure == "same-reviewer": candidate["reviewer"] = "Citation verifier"
    elif failure == "padded-reviewer": candidate["reviewer"] = " Bias reviewer "
    elif failure in {
        "padded-prior-reviewer",
        "citation-authority",
        "citation-conclusion-authority",
        "citation-publication-authority",
        "citation-not-independent",
        "citation-count-drift",
        "citation-limitations-missing",
        "citation-padded-limitation",
        "citation-unsupported-verdict",
        "citation-unclear-count",
        "citation-bad-verdict",
        "citation-duplicate-extraction",
        "citation-missing-contract-field",
        "citation-padded-checked-location",
        "citation-padded-rationale",
        "citation-claim-digest",
        "citation-source-anchor",
        "padded-citation-study",
        "padded-citation-source",
        "padded-citation-claim",
        "padded-citation-extracted-location",
    }:
        value = json.loads(verification.read_text())
        if failure == "padded-prior-reviewer":
            value["citation_reviewer"] = " Citation verifier "
        elif failure == "citation-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "citation-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "citation-publication-authority":
            value["publication_authorized"] = True
        elif failure == "citation-not-independent":
            value["independent_review"] = False
        elif failure == "citation-count-drift":
            value["verdict_counts"]["supported"] = 2
            value["verdict_counts"]["partially_supported"] = 0
        elif failure == "citation-limitations-missing":
            value["limitations"] = []
        elif failure == "citation-padded-limitation":
            value["limitations"][0] = " " + value["limitations"][0]
        elif failure == "citation-unsupported-verdict":
            value["assessments"][0]["verdict"] = "unsupported"
            value["verdict_counts"] = {
                "partially_supported": 1, "supported": 0, "unclear": 0, "unsupported": 1
            }
        elif failure == "citation-unclear-count":
            value["verdict_counts"]["unclear"] = 1
        elif failure == "citation-bad-verdict":
            value["assessments"][0]["verdict"] = "true"
        elif failure == "citation-duplicate-extraction":
            value["assessments"][1]["extraction_id"] = "e1"
        elif failure == "citation-missing-contract-field":
            del value["assessments"][0]["checked_location"]
        elif failure == "citation-padded-checked-location":
            value["assessments"][0]["checked_location"] = " page 1 "
        elif failure == "citation-padded-rationale":
            value["assessments"][0]["rationale"] = " Fixture citation rationale "
        elif failure == "citation-claim-digest":
            value["assessments"][0]["extraction_claim_sha256"] = "A" * 64
        elif failure == "citation-source-anchor":
            value["assessments"][0]["source_retained_file_sha256"] = "A" * 64
        elif failure == "padded-citation-study":
            value["assessments"][0]["study_id"] = " study-1 "
        elif failure == "padded-citation-source":
            value["assessments"][0]["source_id"] = " s1 "
        elif failure == "padded-citation-claim":
            value["assessments"][0]["claim_text"] = " Synthetic claim e1 "
        elif failure == "padded-citation-extracted-location":
            value["assessments"][0]["extracted_evidence_location"] = " page 1 "
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        verification.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "missing-study": candidate["assessments"] = []
    elif failure == "duplicate-study":
        duplicate = dict(candidate["assessments"][0])
        duplicate["study_id"] = "study-1"
        candidate["assessments"].append(duplicate)
    elif failure == "source": candidate["assessments"][0]["source_ids"] = ["s1"]
    elif failure == "padded-study": candidate["assessments"][0]["study_id"] = " study-1 "
    elif failure == "padded-source": candidate["assessments"][0]["source_ids"] = [" s1 ", "s2"]
    elif failure == "padded-source-duplicate": candidate["assessments"][0]["source_ids"] = ["s1", " s1 "]
    elif failure == "domain": candidate["assessments"][0]["domains"].pop()
    elif failure == "location": candidate["assessments"][0]["domains"][0]["evidence_locations"] = []
    elif failure == "padded-location": candidate["assessments"][0]["domains"][0]["evidence_locations"] = [" methods "]
    elif failure == "padded-rationale": candidate["assessments"][0]["domains"][0]["rationale"] = " Fixture rationale "
    elif failure == "padded-design": candidate["assessments"][0]["study_design"] = " synthetic fixture "
    elif failure == "padded-notes": candidate["assessments"][0]["notes"] = " Generic fixture assessment "
    elif failure == "judgment": candidate["assessments"][0]["domains"][0]["judgment"] = "safe"
    output = tmp_path / "bias"
    with pytest.raises(ValidationError):
        create_bias_assessment(verification, digest, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_bias_assessment_rejects_malformed_expected_verification_hash(tmp_path, expected):
    verification, _ = verification_file(tmp_path)
    output = tmp_path / "bias"
    with pytest.raises(
        ValidationError,
        match="expected_citation_verification_sha256 must be a lowercase SHA-256 digest",
    ):
        create_bias_assessment(verification, expected, review(), output)
    assert not output.exists()
