"""Synthetic study identities; pairwise judgments are reviewer assertions."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.studies import create_study_reconciliation


def bias_file(tmp_path):
    value = {"bias_assessment_version": 1, "status": "bias_assessment_recorded",
        "snapshot_id": "snap", "reviewer": "Bias reviewer", "assessments": [
            {"study_id": "study-1", "source_ids": ["s1", "s1-followup"]},
            {"study_id": "study-2", "source_ids": ["s2"]},
        ]}
    encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
    path = tmp_path / "bias.json"
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def review(relationship="independent"):
    def study(study_id, sources, registration):
        return {"study_id": study_id, "source_ids": sources, "registration_ids": [registration],
            "population": "Synthetic population", "setting": "Synthetic setting",
            "recruitment_period": "2025-01 through 2025-06", "sample_size": 20,
            "identity_notes": "Fixture metadata only"}
    return {"reviewer": "Identity reviewer", "studies": [
        study("study-1", ["s1", "s1-followup"], "reg-1"), study("study-2", ["s2"], "reg-2")],
        "relationships": [{"study_ids": ["study-2", "study-1"], "relationship": relationship,
            "rationale": "Compared registrations and recruitment", "evidence_locations": ["methods"]}]}


def test_reconciliation_cli_covers_pairs_and_is_write_once(tmp_path, capsys):
    bias, digest = bias_file(tmp_path)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review()))
    output = tmp_path / "reconciliation"
    assert main(["--json", "literature", "reconcile-studies", "--bias-assessment-file", str(bias),
        "--expected-bias-assessment-sha256", digest, "--review-file", str(review_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "study_identities_reconciled"
    assert result["relationships"][0]["study_ids"] == ["study-1", "study-2"]
    assert result["scientific_evidence_eligible"] is False
    with pytest.raises(ValidationError, match="already exists"):
        create_study_reconciliation(bias, digest, review(), output)


@pytest.mark.parametrize("relationship", ["overlapping_cohort", "duplicate_report", "unclear"])
def test_nonindependent_relationship_is_preserved_and_requires_review(tmp_path, relationship):
    bias, digest = bias_file(tmp_path)
    result = create_study_reconciliation(bias, digest, review(relationship), tmp_path / "reconciliation")
    assert result["status"] == "review_required"
    assert result["relationship_counts"][relationship] == 1


@pytest.mark.parametrize("failure", ["hash", "same-reviewer", "missing-study", "source", "sample", "missing-pair", "duplicate-pair", "location"])
def test_invalid_reconciliation_never_publishes(tmp_path, failure):
    bias, digest = bias_file(tmp_path)
    candidate = review()
    if failure == "hash": digest = "0" * 64
    elif failure == "same-reviewer": candidate["reviewer"] = " bias REVIEWER "
    elif failure == "missing-study": candidate["studies"].pop()
    elif failure == "source": candidate["studies"][0]["source_ids"].pop()
    elif failure == "sample": candidate["studies"][0]["sample_size"] = True
    elif failure == "missing-pair": candidate["relationships"] = []
    elif failure == "duplicate-pair": candidate["relationships"].append(dict(candidate["relationships"][0]))
    elif failure == "location": candidate["relationships"][0]["evidence_locations"] = []
    output = tmp_path / "reconciliation"
    with pytest.raises(ValidationError):
        create_study_reconciliation(bias, digest, candidate, output)
    assert not output.exists()
