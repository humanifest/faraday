"""Synthetic study identities; pairwise judgments are reviewer assertions."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.studies import create_study_reconciliation


def bias_file(tmp_path):
    value = {"bias_assessment_version": 1, "status": "bias_assessment_recorded",
        "snapshot_id": "snap", "reviewer": "Bias reviewer",
        "independent_review": True,
        "overall_judgment_counts": {"low": 1, "some_concerns": 1, "high": 0, "unclear": 0},
        "scientific_evidence_eligible": False,
        "limitations": [
            "Overall judgments are conservative deterministic summaries of reviewer-entered domain judgments, not automated validity findings.",
            "The generic domains do not replace design-specific validated instruments or authenticate reviewer expertise or independence.",
            "Risk-of-bias assessment does not make a literature claim true or authorize quantitative synthesis.",
        ],
        "assessments": [
            {"study_id": "study-1", "source_ids": ["s1", "s1-followup"], "overall_judgment": "some_concerns"},
            {"study_id": "study-2", "source_ids": ["s2"], "overall_judgment": "low"},
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


def test_reconciliation_preserves_canonical_study_source_and_registration_handles(tmp_path):
    bias, digest = bias_file(tmp_path)
    result = create_study_reconciliation(bias, digest, review(), tmp_path / "reconciliation")
    assert result["studies"][0]["study_id"] == "study-1"
    assert result["studies"][0]["source_ids"] == ["s1", "s1-followup"]
    assert result["studies"][0]["registration_ids"] == ["reg-1"]
    assert result["relationships"][0]["study_ids"] == ["study-1", "study-2"]


@pytest.mark.parametrize("failure", [
    "hash",
    "same-reviewer",
    "padded-reviewer",
    "padded-bias-reviewer",
    "bias-authority",
    "bias-not-independent",
    "bias-count-drift",
    "bias-limitations-missing",
    "bias-padded-limitation",
    "bias-bad-judgment",
    "padded-bias-study",
    "padded-bias-source",
    "missing-study",
    "duplicate-study",
    "padded-study",
    "source",
    "padded-source",
    "padded-source-duplicate",
    "registration-duplicate",
    "padded-registration",
    "padded-population",
    "padded-setting",
    "padded-recruitment",
    "padded-notes",
    "sample",
    "missing-pair",
    "duplicate-pair",
    "padded-pair",
    "padded-duplicate-pair",
    "location",
    "padded-location",
    "padded-rationale",
])
def test_invalid_reconciliation_never_publishes(tmp_path, failure):
    bias, digest = bias_file(tmp_path)
    candidate = review()
    if failure == "hash": digest = "0" * 64
    elif failure == "same-reviewer": candidate["reviewer"] = "Bias reviewer"
    elif failure == "padded-reviewer": candidate["reviewer"] = " Identity reviewer "
    elif failure in {
        "padded-bias-reviewer",
        "bias-authority",
        "bias-not-independent",
        "bias-count-drift",
        "bias-limitations-missing",
        "bias-padded-limitation",
        "bias-bad-judgment",
        "padded-bias-study",
        "padded-bias-source",
    }:
        value = json.loads(bias.read_text())
        if failure == "padded-bias-reviewer":
            value["reviewer"] = " Bias reviewer "
        elif failure == "bias-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "bias-not-independent":
            value["independent_review"] = False
        elif failure == "bias-count-drift":
            value["overall_judgment_counts"]["low"] = 2
            value["overall_judgment_counts"]["some_concerns"] = 0
        elif failure == "bias-limitations-missing":
            value["limitations"] = []
        elif failure == "bias-padded-limitation":
            value["limitations"][0] = " " + value["limitations"][0]
        elif failure == "bias-bad-judgment":
            value["assessments"][0]["overall_judgment"] = "safe"
        elif failure == "padded-bias-study":
            value["assessments"][0]["study_id"] = " study-1 "
        elif failure == "padded-bias-source":
            value["assessments"][0]["source_ids"] = [" s1 ", "s1-followup"]
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        bias.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "missing-study": candidate["studies"].pop()
    elif failure == "duplicate-study":
        duplicate = dict(candidate["studies"][0])
        duplicate["study_id"] = "study-1"
        candidate["studies"].append(duplicate)
    elif failure == "padded-study": candidate["studies"][0]["study_id"] = " study-1 "
    elif failure == "source": candidate["studies"][0]["source_ids"].pop()
    elif failure == "padded-source": candidate["studies"][0]["source_ids"] = [" s1 ", "s1-followup"]
    elif failure == "padded-source-duplicate": candidate["studies"][0]["source_ids"] = ["s1", " s1 "]
    elif failure == "registration-duplicate": candidate["studies"][0]["registration_ids"] = ["reg-1", "reg-1"]
    elif failure == "padded-registration": candidate["studies"][0]["registration_ids"] = [" reg-1 "]
    elif failure == "padded-population": candidate["studies"][0]["population"] = " Synthetic population "
    elif failure == "padded-setting": candidate["studies"][0]["setting"] = " Synthetic setting "
    elif failure == "padded-recruitment": candidate["studies"][0]["recruitment_period"] = " 2025-01 through 2025-06 "
    elif failure == "padded-notes": candidate["studies"][0]["identity_notes"] = " Fixture metadata only "
    elif failure == "sample": candidate["studies"][0]["sample_size"] = True
    elif failure == "missing-pair": candidate["relationships"] = []
    elif failure == "duplicate-pair": candidate["relationships"].append(dict(candidate["relationships"][0]))
    elif failure == "padded-pair": candidate["relationships"][0]["study_ids"] = [" study-2 ", "study-1"]
    elif failure == "padded-duplicate-pair":
        duplicate = dict(candidate["relationships"][0])
        duplicate["study_ids"] = [" study-1 ", "study-2 "]
        candidate["relationships"].append(duplicate)
    elif failure == "location": candidate["relationships"][0]["evidence_locations"] = []
    elif failure == "padded-location": candidate["relationships"][0]["evidence_locations"] = [" methods "]
    elif failure == "padded-rationale": candidate["relationships"][0]["rationale"] = " Compared registrations and recruitment "
    output = tmp_path / "reconciliation"
    with pytest.raises(ValidationError):
        create_study_reconciliation(bias, digest, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_reconciliation_rejects_malformed_expected_bias_hash(tmp_path, expected):
    bias, _ = bias_file(tmp_path)
    output = tmp_path / "reconciliation"
    with pytest.raises(ValidationError, match="expected_bias_assessment_sha256 must be a lowercase SHA-256 digest"):
        create_study_reconciliation(bias, expected, review(), output)
    assert not output.exists()
