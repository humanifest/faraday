"""Synthetic deviation disclosures never rewrite preregistration."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.deviations import create_synthesis_deviations


def plan_file(tmp_path):
    value = {"synthesis_plan_version": 1, "status": "synthesis_plan_frozen",
             "plan_id": "p1", "snapshot_id": "snap",
             "synthesis_type": "quantitative",
             "research_question": "Fixture question?",
             "primary_outcome": "Fixture outcome",
             "effect_measure": "mean_difference",
             "contrast_definition": "experimental minus comparator",
             "statistical_model": "fixed_effect",
             "minimum_independent_studies": 2,
             "included_source_ids_at_freeze": ["s1", "s2"],
             "conclusion_rule": "Bound conclusions",
             "deviation_policy": "Disclose all departures",
             "scientific_evidence_eligible": False,
             "conclusion_authorized": False,
             "publication_authorized": False,
             "limitations": [
                 "A frozen synthesis plan is a prospective commitment, not evidence.",
             ]}
    encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
    path = tmp_path / "plan.json"; path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest(), encoded


def disclosure(timing="before_synthesis"):
    return {"reviewer": "Deviation reviewer", "deviations": [{"deviation_id": "d1",
        "stage": "effect_preparation", "frozen_commitment": "Use reported standard errors",
        "actual_method": "Derived one standard error from a confidence interval",
        "reason": "Reported standard error unavailable", "timing": timing,
        "impact_assessment": "May introduce rounding error", "corrective_action": "Sensitivity check",
        "evidence_location": "review log section 2"}]}


def test_prospective_deviation_cli_is_write_once_and_does_not_amend_plan(tmp_path, capsys):
    plan, digest, original = plan_file(tmp_path)
    disclosure_path = tmp_path / "disclosure.json"; disclosure_path.write_text(json.dumps(disclosure()))
    output = tmp_path / "deviations"
    assert main(["--json", "literature", "record-deviations", "--plan-file", str(plan),
        "--expected-plan-sha256", digest, "--disclosure-file", str(disclosure_path),
        "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "prospective_deviations_recorded"
    assert result["plan_amended"] is False and result["claim_ceiling_effect"] == "cannot_raise"
    assert result["scientific_evidence_eligible"] is False
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    assert result["frozen_plan_commitments"]["synthesis_type"] == "quantitative"
    assert result["frozen_plan_commitments"]["included_source_ids_at_freeze"] == ["s1", "s2"]
    assert result["timing_counts"]["before_synthesis"] == 1
    assert result["deviations"][0]["evidence_location"] == "review log section 2"
    assert plan.read_bytes() == original
    with pytest.raises(ValidationError, match="already exists"):
        create_synthesis_deviations(plan, digest, disclosure(), output)


def test_explicit_no_deviations_declaration_is_recorded(tmp_path):
    plan, digest, _ = plan_file(tmp_path)
    result = create_synthesis_deviations(plan, digest, {"reviewer": "Reviewer", "deviations": []}, tmp_path / "none")
    assert result["status"] == "no_deviations_declared"
    assert result["deviations"] == []


@pytest.mark.parametrize("timing", ["after_results_seen", "unknown"])
def test_retrospective_or_uncertain_timing_requires_review(tmp_path, timing):
    plan, digest, _ = plan_file(tmp_path)
    result = create_synthesis_deviations(plan, digest, disclosure(timing), tmp_path / "deviations")
    assert result["status"] == "retrospective_or_uncertain_deviation_review_required"


@pytest.mark.parametrize("failure", [
    "hash",
    "plan-authority",
    "plan-conclusion-authority",
    "plan-publication-authority",
    "plan-limitations-missing",
    "not-array",
    "duplicate",
    "stage",
    "timing",
    "reason",
    "location",
    "qualitative-effect-stage",
])
def test_invalid_deviation_disclosure_never_publishes(tmp_path, failure):
    plan, digest, _ = plan_file(tmp_path); candidate = disclosure()
    if failure == "hash": digest = "0" * 64
    elif failure in {"plan-authority", "plan-conclusion-authority",
                     "plan-publication-authority", "plan-limitations-missing"}:
        value = json.loads(plan.read_text())
        if failure == "plan-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "plan-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "plan-publication-authority":
            value["publication_authorized"] = True
        else:
            value["limitations"] = []
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        plan.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "not-array": candidate["deviations"] = None
    elif failure == "duplicate": candidate["deviations"].append(dict(candidate["deviations"][0]))
    elif failure == "stage": candidate["deviations"][0]["stage"] = "invent_results"
    elif failure == "timing": candidate["deviations"][0]["timing"] = "preregistered_later"
    elif failure == "reason": candidate["deviations"][0]["reason"] = ""
    elif failure == "location": candidate["deviations"][0]["evidence_location"] = ""
    elif failure == "qualitative-effect-stage":
        value = json.loads(plan.read_text())
        value["synthesis_type"] = "qualitative"
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        plan.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    output = tmp_path / "deviations"
    with pytest.raises(ValidationError):
        create_synthesis_deviations(plan, digest, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reviewer", " Deviation reviewer", "deviation reviewer must be canonical"),
        ("deviation_id", " d1", "deviation_id must be canonical"),
        ("frozen_commitment", " Use reported standard errors", "frozen_commitment must be canonical"),
        ("actual_method", "Derived one standard error from a confidence interval ", "actual_method must be canonical"),
        ("reason", " Reported standard error unavailable", "deviation reason must be canonical"),
        ("impact_assessment", "May introduce rounding error ", "impact_assessment must be canonical"),
        ("corrective_action", " Sensitivity check", "corrective_action must be canonical"),
        ("evidence_location", "review log section 2 ", "deviation evidence_location must be canonical"),
    ],
)
def test_deviation_disclosure_text_must_be_canonical(tmp_path, field, value, message):
    plan, digest, _ = plan_file(tmp_path)
    candidate = disclosure()
    if field == "reviewer":
        candidate[field] = value
    else:
        candidate["deviations"][0][field] = value
    output = tmp_path / "deviations"
    with pytest.raises(ValidationError, match=message):
        create_synthesis_deviations(plan, digest, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_deviation_disclosure_rejects_malformed_expected_plan_hash(tmp_path, expected):
    plan, _, _ = plan_file(tmp_path)
    output = tmp_path / "deviations"
    with pytest.raises(ValidationError, match="expected_plan_sha256 must be a lowercase SHA-256 digest"):
        create_synthesis_deviations(plan, expected, disclosure(), output)
    assert not output.exists()
