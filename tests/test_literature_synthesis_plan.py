"""Synthetic synthesis plans are commitments, not scientific evidence."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.synthesis_plan import (
    create_synthesis_plan,
    validate_synthesis_plan_boundary,
)


def screening_file(tmp_path, status="screening_recorded"):
    value = {"screening_version": 2, "snapshot_sha256": "a" * 64,
        "status": status, "snapshot_id": "snap", "reviewer": "Screening reviewer",
        "criteria": {"inclusion:1": "Eligible", "exclusion:1": "Ineligible"},
        "decisions": [
            {"source_id": "s1", "decision": "include", "reason": "Eligible",
             "criterion_refs": ["inclusion:1"], "source_retained_file_sha256": "1" * 64},
            {"source_id": "s2", "decision": "exclude", "reason": "Ineligible",
             "criterion_refs": ["exclusion:1"], "source_retained_file_sha256": "2" * 64}],
        "source_record_counts": {"include": 1, "exclude": 1, "unresolved": 0},
        "duplicate_decision_conflicts": [],
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Inclusion is not claim acceptance, evidence admission, or support for any extracted claim."
        ]}
    encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
    path = tmp_path / "screening.json"
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def padded_screening_file(tmp_path):
    value = {"screening_version": 2, "snapshot_sha256": "a" * 64,
        "status": "screening_recorded", "snapshot_id": "snap",
        "reviewer": "Screening reviewer",
        "criteria": {"inclusion:1": "Eligible"},
        "decisions": [{"source_id": " s1", "decision": "include",
            "reason": "Eligible", "criterion_refs": ["inclusion:1"],
            "source_retained_file_sha256": "1" * 64}],
        "source_record_counts": {"include": 1, "exclude": 0, "unresolved": 0},
        "duplicate_decision_conflicts": [],
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Inclusion is not claim acceptance, evidence admission, or support for any extracted claim."
        ]}
    encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
    path = tmp_path / "screening.json"
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def spec(synthesis_type="quantitative"):
    return {"plan_id": "plan-1", "reviewer": "Planner", "research_question": "Fixture question?",
        "primary_outcome": "Fixture outcome", "synthesis_type": synthesis_type,
        "effect_measure": "standardized_mean_difference" if synthesis_type == "quantitative" else "not_applicable",
        "contrast_definition": "experimental minus comparator" if synthesis_type == "quantitative" else "not_applicable",
        "statistical_model": "random_effects" if synthesis_type == "quantitative" else "not_applicable",
        "minimum_independent_studies": 2, "eligibility_policy": "All screened-in studies",
        "missing_statistics_policy": "Do not impute; report unavailable",
        "heterogeneity_policy": "Report tau squared and prediction interval",
        "multiplicity_policy": "Primary outcome only; label all others exploratory",
        "subgroup_analyses": [], "sensitivity_analyses": ["exclude_high_or_unclear_bias"],
        "conclusion_rule": "Bound wording by uncertainty and risk of bias",
        "deviation_policy": "Record and justify every deviation before execution"}


def test_synthesis_plan_cli_freezes_complete_commitments_and_is_write_once(tmp_path, capsys):
    screening, digest = screening_file(tmp_path)
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec()))
    output = tmp_path / "plan"
    assert main(["--json", "literature", "plan-synthesis", "--screening-file", str(screening),
        "--expected-screening-sha256", digest, "--spec-file", str(spec_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "synthesis_plan_frozen"
    assert result["included_source_ids_at_freeze"] == ["s1"]
    assert result["scientific_evidence_eligible"] is False
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    assert result["reviewer_identity_authenticated"] is False
    with pytest.raises(ValidationError, match="already exists"):
        create_synthesis_plan(screening, digest, spec(), output)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ('{"screening_version": 2, "screening_version": 2}\n', "duplicate JSON object key"),
        ('{"screening_version": NaN}\n', "non-finite JSON number"),
    ],
)
def test_synthesis_plan_rejects_ambiguous_screening_json_bytes(tmp_path, payload, message):
    screening, _digest = screening_file(tmp_path)
    screening.write_text(payload, encoding="utf-8")
    tampered_digest = hashlib.sha256(screening.read_bytes()).hexdigest()
    output = tmp_path / "plan"

    with pytest.raises(ValidationError, match=message):
        create_synthesis_plan(screening, tampered_digest, spec(), output)
    assert not output.exists()


def test_synthesis_plan_boundary_rejects_reviewer_authentication(tmp_path):
    screening, digest = screening_file(tmp_path)
    result = create_synthesis_plan(screening, digest, spec(), tmp_path / "plan")
    candidate = dict(result)
    candidate["reviewer_identity_authenticated"] = True
    with pytest.raises(ValidationError, match="authenticate reviewer identity"):
        validate_synthesis_plan_boundary(candidate)


@pytest.mark.parametrize(
    "field",
    ["limitation", "eligibility_policy", "conclusion_rule", "deviation_policy"],
)
def test_synthesis_plan_boundary_rejects_retained_overclaiming_policy(tmp_path, field):
    screening, digest = screening_file(tmp_path)
    result = create_synthesis_plan(screening, digest, spec(), tmp_path / "plan")
    candidate = dict(result)
    if field == "limitation":
        candidate["limitations"] = list(result["limitations"])
        candidate["limitations"][0] = "Synthesis plan confirmed review validity"
    else:
        candidate[field] = "Validated final conclusion"

    with pytest.raises(ValidationError, match="prohibited overclaiming language"):
        validate_synthesis_plan_boundary(candidate)


def test_qualitative_plan_rejects_quantitative_choices(tmp_path):
    screening, digest = screening_file(tmp_path)
    candidate = spec("qualitative")
    candidate["statistical_model"] = "random_effects"
    with pytest.raises(ValidationError, match="qualitative"):
        create_synthesis_plan(screening, digest, candidate, tmp_path / "plan")


@pytest.mark.parametrize("failure", [
    "hash", "screening", "no-included", "screening-conclusion",
    "screening-publication", "screening-count", "minimum", "sensitivity",
    "unknown-sensitivity", "same-model", "quant-effect", "quant-model",
    "overclaim-eligibility", "overclaim-missing", "overclaim-heterogeneity",
    "overclaim-multiplicity", "overclaim-conclusion", "overclaim-deviation",
])
def test_invalid_synthesis_plan_never_publishes(tmp_path, failure):
    screening, digest = screening_file(tmp_path, "review_required" if failure == "screening" else "screening_recorded")
    candidate = spec()
    if failure == "hash": digest = "0" * 64
    elif failure == "no-included":
        value = json.loads(screening.read_text()); value["decisions"][0]["decision"] = "exclude"
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode(); screening.write_bytes(encoded); digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "screening-conclusion":
        value = json.loads(screening.read_text()); value["conclusion_authorized"] = True
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode(); screening.write_bytes(encoded); digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "screening-publication":
        value = json.loads(screening.read_text()); value["publication_authorized"] = True
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode(); screening.write_bytes(encoded); digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "screening-count":
        value = json.loads(screening.read_text()); value["source_record_counts"]["include"] = 2
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode(); screening.write_bytes(encoded); digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "minimum": candidate["minimum_independent_studies"] = True
    elif failure == "sensitivity": candidate["sensitivity_analyses"] = []
    elif failure == "unknown-sensitivity": candidate["sensitivity_analyses"] = ["try_something"]
    elif failure == "same-model": candidate["sensitivity_analyses"] = ["alternate_random_effects"]
    elif failure == "quant-effect": candidate["effect_measure"] = "not_applicable"
    elif failure == "quant-model": candidate["statistical_model"] = "not_applicable"
    elif failure == "overclaim-eligibility": candidate["eligibility_policy"] = "Confirmed eligible sources only"
    elif failure == "overclaim-missing": candidate["missing_statistics_policy"] = "Validated no missing statistics"
    elif failure == "overclaim-heterogeneity": candidate["heterogeneity_policy"] = "Explained all heterogeneity"
    elif failure == "overclaim-multiplicity": candidate["multiplicity_policy"] = "Confirmed no multiplicity risk"
    elif failure == "overclaim-conclusion": candidate["conclusion_rule"] = "Validated final conclusion"
    elif failure == "overclaim-deviation": candidate["deviation_policy"] = "Confirmed no deviations matter"
    output = tmp_path / "plan"
    with pytest.raises(ValidationError):
        create_synthesis_plan(screening, digest, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize("field", [
    "plan_id", "reviewer", "research_question", "primary_outcome", "effect_measure",
    "contrast_definition", "eligibility_policy", "missing_statistics_policy",
    "heterogeneity_policy", "multiplicity_policy", "conclusion_rule", "deviation_policy",
])
def test_synthesis_plan_rejects_padded_commitment_text(tmp_path, field):
    screening, digest = screening_file(tmp_path)
    candidate = spec()
    candidate[field] = f" {candidate[field]} "
    output = tmp_path / "plan"
    with pytest.raises(ValidationError, match="canonical"):
        create_synthesis_plan(screening, digest, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize("field", ["subgroup_analyses", "sensitivity_analyses"])
def test_synthesis_plan_rejects_padded_list_commitments(tmp_path, field):
    screening, digest = screening_file(tmp_path)
    candidate = spec()
    candidate[field] = [f" {candidate[field][0]} "] if candidate[field] else [" subgroup "]
    output = tmp_path / "plan"
    with pytest.raises(ValidationError, match="canonical"):
        create_synthesis_plan(screening, digest, candidate, output)
    assert not output.exists()


def test_synthesis_plan_rejects_padded_frozen_source_ids(tmp_path):
    screening, digest = padded_screening_file(tmp_path)
    output = tmp_path / "plan"
    with pytest.raises(ValidationError, match="screening source_id must be canonical"):
        create_synthesis_plan(screening, digest, spec(), output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_synthesis_plan_rejects_malformed_expected_screening_hash(tmp_path, expected):
    screening, _ = screening_file(tmp_path)
    output = tmp_path / "plan"
    with pytest.raises(ValidationError, match="expected_screening_sha256 must be a lowercase SHA-256 digest"):
        create_synthesis_plan(screening, expected, spec(), output)
    assert not output.exists()
