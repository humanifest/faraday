"""Synthetic risk-of-bias records; judgments are not scientific findings."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.bias import create_bias_assessment


DOMAINS = ["selection", "confounding", "exposure_or_intervention_classification",
    "deviations_from_intended_conditions", "missing_data", "outcome_measurement", "selective_reporting"]


def verification_file(tmp_path, status="citation_review_recorded"):
    value = {"citation_verification_version": 1, "status": status, "snapshot_id": "snap",
        "extraction_reviewer": "Extractor", "citation_reviewer": "Citation verifier",
        "assessments": [
            {"extraction_id": "e1", "study_id": "study-1", "source_id": "s1"},
            {"extraction_id": "e2", "study_id": "study-1", "source_id": "s2"},
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
    with pytest.raises(ValidationError, match="already exists"):
        create_bias_assessment(verification, digest, review("high"), output)


def test_bias_assessment_normalizes_study_and_source_handles(tmp_path):
    verification, digest = verification_file(tmp_path)
    candidate = review()
    candidate["assessments"][0]["study_id"] = " study-1 "
    candidate["assessments"][0]["source_ids"] = [" s1 ", "s2 "]
    result = create_bias_assessment(verification, digest, candidate, tmp_path / "bias")
    assert result["assessments"][0]["study_id"] == "study-1"
    assert result["assessments"][0]["source_ids"] == ["s1", "s2"]


@pytest.mark.parametrize("failure", ["hash", "unclean", "same-reviewer", "missing-study", "duplicate-study", "source", "padded-source-duplicate", "domain", "location", "judgment"])
def test_invalid_bias_assessment_never_publishes(tmp_path, failure):
    verification, digest = verification_file(tmp_path, "review_required" if failure == "unclean" else "citation_review_recorded")
    candidate = review()
    if failure == "hash": digest = "0" * 64
    elif failure == "same-reviewer": candidate["reviewer"] = " citation VERIFIER "
    elif failure == "missing-study": candidate["assessments"] = []
    elif failure == "duplicate-study":
        duplicate = dict(candidate["assessments"][0])
        duplicate["study_id"] = " study-1 "
        candidate["assessments"].append(duplicate)
    elif failure == "source": candidate["assessments"][0]["source_ids"] = ["s1"]
    elif failure == "padded-source-duplicate": candidate["assessments"][0]["source_ids"] = ["s1", " s1 "]
    elif failure == "domain": candidate["assessments"][0]["domains"].pop()
    elif failure == "location": candidate["assessments"][0]["domains"][0]["evidence_locations"] = []
    elif failure == "judgment": candidate["assessments"][0]["domains"][0]["judgment"] = "safe"
    output = tmp_path / "bias"
    with pytest.raises(ValidationError):
        create_bias_assessment(verification, digest, candidate, output)
    assert not output.exists()
