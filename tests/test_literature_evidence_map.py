"""Evidence maps join synthetic review artifacts without authorizing conclusions."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.evidence_map import (
    create_evidence_map,
    validate_evidence_map_boundary,
)


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


def chain(tmp_path, bias_judgment="some_concerns", source_sha="legacy_missing"):
    extraction = tmp_path / "extraction.json"
    extraction_record = {"extraction_id": "e1", "study_id": "study-1",
        "claim_text": "Synthetic claim", "evidence_location": "page fixture",
        "epistemic_layer": "inferred", "result_direction": "mixed",
        "uncertainty": "fixture", "notes": "fixture notes"}
    source_review = {"source_id": "s1", "records": [extraction_record]}
    if source_sha != "legacy_missing":
        source_review["source_retained_file_sha256"] = source_sha
    extraction_sha = write_json(extraction, {"extraction_version": 1, "status": "extraction_recorded",
        "screening_sha256": "1" * 64, "snapshot_id": "snap",
        "record_count": 1, "scientific_evidence_eligible": False,
        "conclusion_authorized": False, "publication_authorized": False,
        "limitations": [
            "Records are reviewer assertions bound to source IDs and locations; the machine has not verified that source text supports them.",
            "Extraction does not perform risk-of-bias assessment, resolve disagreements, accept claims as facts, or conduct synthesis.",
        ],
        "source_reviews": [source_review]})
    verification = tmp_path / "verification.json"
    citation = {"extraction_id": "e1", "study_id": "study-1",
        "source_id": "s1", "verdict": "supported", "checked_location": "page 4",
        "rationale": "fixture citation check",
        "extraction_claim_sha256": claim_digest("s1", extraction_record, source_sha)}
    if source_sha != "legacy_missing":
        citation["source_retained_file_sha256"] = source_sha
    verification_sha = write_json(verification, {"citation_verification_version": 1, "status": "citation_review_recorded",
        "extraction_sha256": extraction_sha, "snapshot_id": "snap",
        "extraction_reviewer": "Extractor", "citation_reviewer": "Citation verifier",
        "independent_review": True,
        "verdict_counts": {"partially_supported": 0, "supported": 1, "unclear": 0, "unsupported": 0},
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "The machine binds an independent review to extraction bytes but does not interpret source text or authenticate either reviewer.",
            "A supported verdict is a reviewer judgment, not proof that a claim is true, unbiased, reproducible, or applicable.",
            "Risk-of-bias assessment, study-identity reconciliation, and quantitative synthesis remain separate gates.",
        ],
        "assessments": [citation]})
    bias = tmp_path / "bias.json"
    domains = [
        {
            "domain": name,
            "judgment": bias_judgment,
            "rationale": "Fixture bias rationale",
            "evidence_locations": ["table 1"],
        }
        for name in (
            "selection", "confounding", "exposure_or_intervention_classification",
            "deviations_from_intended_conditions", "missing_data", "outcome_measurement",
            "selective_reporting",
        )
    ]
    judgment_counts = {"low": 0, "some_concerns": 0, "high": 0, "unclear": 0}
    judgment_counts[bias_judgment] += 1
    bias_sha = write_json(bias, {"bias_assessment_version": 1, "status": "bias_assessment_recorded",
        "citation_verification_sha256": verification_sha, "snapshot_id": "snap",
        "reviewer": "Bias reviewer", "independent_review": True,
        "domain_order": [
            "selection", "confounding", "exposure_or_intervention_classification",
            "deviations_from_intended_conditions", "missing_data", "outcome_measurement",
            "selective_reporting",
        ],
        "overall_judgment_counts": judgment_counts,
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Overall judgments are conservative deterministic summaries of reviewer-entered domain judgments, not automated validity findings.",
            "The generic domains do not replace design-specific risk-of-bias instruments or authenticate reviewer expertise or independence.",
            "Risk-of-bias assessment does not make a literature claim true or authorize quantitative synthesis.",
        ],
        "assessments": [{"study_id": "study-1", "overall_judgment": bias_judgment,
            "study_design": "synthetic fixture", "source_ids": ["s1"],
            "domains": domains, "notes": "Generic fixture assessment"}]})
    reconciliation = tmp_path / "reconciliation.json"
    reconciliation_sha = write_json(reconciliation, {"study_reconciliation_version": 1,
        "status": "study_identities_reconciled", "bias_assessment_sha256": bias_sha,
        "snapshot_id": "snap", "reviewer": "Identity reviewer",
        "independent_review": True,
        "relationship_counts": {"duplicate_report": 0, "independent": 0, "overlapping_cohort": 0, "unclear": 0},
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Pairwise identity judgments are reviewer assertions; metadata similarity cannot prove cohort independence.",
            "Overlap, duplicate, and unclear relationships are preserved and block a reconciled status rather than being silently deduplicated.",
            "Study reconciliation does not validate outcomes, assess applicability, or authorize quantitative synthesis.",
        ],
        "studies": [{
            "study_id": "study-1",
            "source_ids": ["s1"],
            "registration_ids": ["reg-1"],
            "population": "Synthetic population",
            "setting": "Synthetic setting",
            "recruitment_period": "2025-01 through 2025-06",
            "sample_size": 20,
            "identity_notes": "Fixture metadata only",
        }], "relationships": []})
    return extraction, verification, bias, reconciliation, reconciliation_sha


def test_evidence_map_cli_verifies_chain_and_bounds_claim(tmp_path, capsys):
    extraction, verification, bias, reconciliation, digest = chain(tmp_path)
    output = tmp_path / "map"
    assert main(["--json", "literature", "evidence-map", "--extraction-file", str(extraction),
        "--citation-verification-file", str(verification), "--bias-assessment-file", str(bias),
        "--study-reconciliation-file", str(reconciliation),
        "--expected-study-reconciliation-sha256", digest, "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["claims"][0]["interpretive_ceiling"] == "qualified_source_claim"
    assert result["claims"][0]["extracted_evidence_location"] == "page fixture"
    assert result["claims"][0]["extraction_claim_sha256"] == claim_digest(
        "s1", json.loads(extraction.read_text())["source_reviews"][0]["records"][0]
    )
    assert result["claims"][0]["citation_checked_location"] == "page 4"
    assert result["claims"][0]["bias_domain_judgments"][0]["evidence_locations"] == ["table 1"]
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    assert result["scientific_evidence_eligible"] is False
    assert result["reviewer_identity_authenticated"] is False
    with pytest.raises(ValidationError, match="already exists"):
        create_evidence_map(extraction, verification, bias, reconciliation, digest, output)


def test_evidence_map_preserves_canonical_join_handles(tmp_path):
    extraction, verification, bias, reconciliation, digest = chain(tmp_path)
    result = create_evidence_map(extraction, verification, bias, reconciliation, digest, tmp_path / "map")
    assert result["claims"][0]["extraction_id"] == "e1"
    assert result["claims"][0]["study_id"] == "study-1"
    assert result["claims"][0]["source_id"] == "s1"
    assert result["claims"][0]["extraction_claim_sha256"] == claim_digest(
        "s1", json.loads(extraction.read_text())["source_reviews"][0]["records"][0]
    )
    assert result["claims"][0]["bias_domain_judgments"][0]["domain"] == "selection"
    assert result["claims"][0]["bias_domain_judgments"][0]["evidence_locations"] == ["table 1"]


def test_evidence_map_preserves_and_replays_retained_source_byte_anchor(tmp_path):
    extraction, verification, bias, reconciliation, digest = chain(tmp_path, source_sha="b" * 64)
    result = create_evidence_map(
        extraction, verification, bias, reconciliation, digest, tmp_path / "map"
    )
    assert result["claims"][0]["source_retained_file_sha256"] == "b" * 64
    assert result["claims"][0]["extraction_claim_sha256"] == claim_digest(
        "s1",
        json.loads(extraction.read_text())["source_reviews"][0]["records"][0],
        "b" * 64,
    )


@pytest.mark.parametrize("tamper", [
    "version",
    "input-hash",
    "input-extra",
    "snapshot-id",
    "status",
    "reviewer-authenticated",
    "limitation-overclaim",
    "study-count",
    "claim-study-padding",
])
def test_evidence_map_boundary_replays_artifact_envelope(tmp_path, tamper):
    extraction, verification, bias, reconciliation, digest = chain(tmp_path)
    result = create_evidence_map(
        extraction, verification, bias, reconciliation, digest, tmp_path / "map"
    )
    candidate = json.loads(json.dumps(result))
    if tamper == "version":
        candidate["evidence_map_version"] = 2
    elif tamper == "input-hash":
        candidate["inputs"]["bias_assessment_sha256"] = "A" * 64
    elif tamper == "input-extra":
        candidate["inputs"]["extra_sha256"] = "0" * 64
    elif tamper == "snapshot-id":
        candidate["snapshot_id"] = " snap "
    elif tamper == "status":
        candidate["status"] = "map_reviewed"
    elif tamper == "reviewer-authenticated":
        candidate["reviewer_identity_authenticated"] = True
    elif tamper == "limitation-overclaim":
        candidate["limitations"][0] = "This deterministic map confirmed the source claim."
    elif tamper == "study-count":
        candidate["study_count"] = 99
    elif tamper == "claim-study-padding":
        candidate["claims"][0]["study_id"] = " study-1 "

    with pytest.raises(ValidationError):
        validate_evidence_map_boundary(candidate, candidate["claims"])


@pytest.mark.parametrize("failure", [
    "terminal-hash", "extraction-link", "verification-link", "bias-link", "unresolved",
    "extraction-authority", "extraction-conclusion-authority",
    "extraction-publication-authority", "extraction-count-drift",
    "extraction-limitations-missing", "extraction-padded-limitation",
    "verification-authority", "verification-conclusion-authority",
    "verification-publication-authority", "verification-not-independent",
    "verification-count-drift", "verification-limitations-missing",
    "verification-padded-limitation",
    "bias-authority", "bias-conclusion-authority", "bias-publication-authority",
    "bias-not-independent", "bias-count-drift", "bias-limitations-missing",
    "bias-padded-limitation", "reconciliation-authority",
    "reconciliation-conclusion-authority", "reconciliation-publication-authority",
    "reconciliation-not-independent", "reconciliation-count-drift",
    "reconciliation-limitations-missing", "reconciliation-padded-limitation",
    "reconciliation-missing-contract-field", "reconciliation-padded-source",
    "reconciliation-padded-registration", "reconciliation-sample",
    "reconciliation-padded-metadata", "reconciliation-overclaim-notes",
    "coverage", "padded-extraction-duplicate", "padded-citation-duplicate",
    "padded-bias-duplicate", "padded-reconciliation-duplicate",
    "padded-extraction-source", "padded-extraction-study", "padded-extraction-location",
    "padded-citation-id", "padded-citation-source", "padded-citation-study",
    "padded-citation-location", "padded-citation-rationale",
    "overclaim-citation-rationale", "padded-bias-study",
    "padded-bias-domain", "overclaim-bias-rationale", "overclaim-bias-notes",
    "padded-bias-location", "padded-reconciliation-study",
    "citation-provenance", "bias-provenance", "claim-digest", "claim-payload",
    "source-anchor-mismatch",
])
def test_broken_or_incomplete_chain_never_publishes(tmp_path, failure):
    extraction, verification, bias, reconciliation, digest = chain(tmp_path)
    if failure == "terminal-hash": digest = "0" * 64
    elif failure == "extraction-link":
        value = json.loads(verification.read_text()); value["extraction_sha256"] = "0" * 64; write_json(verification, value)
    elif failure == "verification-link":
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = "0" * 64; write_json(bias, value)
    elif failure == "bias-link":
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = "0" * 64; digest = write_json(reconciliation, value)
    elif failure == "unresolved":
        value = json.loads(reconciliation.read_text()); value["status"] = "review_required"; digest = write_json(reconciliation, value)
    elif failure in {
        "extraction-authority", "extraction-conclusion-authority",
        "extraction-publication-authority", "extraction-count-drift",
        "extraction-limitations-missing", "extraction-padded-limitation",
    }:
        value = json.loads(extraction.read_text())
        if failure == "extraction-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "extraction-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "extraction-publication-authority":
            value["publication_authorized"] = True
        elif failure == "extraction-count-drift":
            value["record_count"] = 2
        elif failure == "extraction-limitations-missing":
            value["limitations"] = []
        elif failure == "extraction-padded-limitation":
            value["limitations"][0] = " " + value["limitations"][0]
        extraction_sha = write_json(extraction, value)
        value = json.loads(verification.read_text()); value["extraction_sha256"] = extraction_sha; verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure in {
        "verification-authority", "verification-conclusion-authority",
        "verification-publication-authority", "verification-not-independent", "verification-count-drift",
        "verification-limitations-missing", "verification-padded-limitation",
    }:
        value = json.loads(verification.read_text())
        if failure == "verification-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "verification-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "verification-publication-authority":
            value["publication_authorized"] = True
        elif failure == "verification-not-independent":
            value["independent_review"] = False
        elif failure == "verification-count-drift":
            value["verdict_counts"]["supported"] = 0
            value["verdict_counts"]["partially_supported"] = 1
        elif failure == "verification-limitations-missing":
            value["limitations"] = []
        elif failure == "verification-padded-limitation":
            value["limitations"][0] = " " + value["limitations"][0]
        verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure in {
        "bias-authority", "bias-conclusion-authority", "bias-publication-authority",
        "bias-not-independent", "bias-count-drift", "bias-limitations-missing",
        "bias-padded-limitation",
    }:
        value = json.loads(bias.read_text())
        if failure == "bias-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "bias-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "bias-publication-authority":
            value["publication_authorized"] = True
        elif failure == "bias-not-independent":
            value["independent_review"] = False
        elif failure == "bias-count-drift":
            value["overall_judgment_counts"]["low"] = 1
            value["overall_judgment_counts"]["some_concerns"] = 0
        elif failure == "bias-limitations-missing":
            value["limitations"] = []
        elif failure == "bias-padded-limitation":
            value["limitations"][0] = " " + value["limitations"][0]
        bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure in {
        "reconciliation-authority", "reconciliation-not-independent",
        "reconciliation-conclusion-authority", "reconciliation-publication-authority",
        "reconciliation-count-drift", "reconciliation-limitations-missing",
        "reconciliation-padded-limitation", "reconciliation-missing-contract-field",
        "reconciliation-padded-source", "reconciliation-padded-registration",
        "reconciliation-sample", "reconciliation-padded-metadata",
        "reconciliation-overclaim-notes",
    }:
        value = json.loads(reconciliation.read_text())
        if failure == "reconciliation-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "reconciliation-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "reconciliation-publication-authority":
            value["publication_authorized"] = True
        elif failure == "reconciliation-not-independent":
            value["independent_review"] = False
        elif failure == "reconciliation-count-drift":
            value["relationship_counts"]["independent"] = 1
        elif failure == "reconciliation-limitations-missing":
            value["limitations"] = []
        elif failure == "reconciliation-padded-limitation":
            value["limitations"][0] = " " + value["limitations"][0]
        elif failure == "reconciliation-missing-contract-field":
            del value["studies"][0]["identity_notes"]
        elif failure == "reconciliation-padded-source":
            value["studies"][0]["source_ids"] = [" s1 "]
        elif failure == "reconciliation-padded-registration":
            value["studies"][0]["registration_ids"] = [" reg-1 "]
        elif failure == "reconciliation-sample":
            value["studies"][0]["sample_size"] = True
        elif failure == "reconciliation-padded-metadata":
            value["studies"][0]["population"] = " Synthetic population "
        elif failure == "reconciliation-overclaim-notes":
            value["studies"][0]["identity_notes"] = "Confirmed independent cohort"
        digest = write_json(reconciliation, value)
    elif failure == "coverage":
        value = json.loads(verification.read_text()); value["assessments"] = []; verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure == "claim-digest":
        value = json.loads(verification.read_text())
        value["assessments"][0]["extraction_claim_sha256"] = "0" * 64
        verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure == "claim-payload":
        value = json.loads(extraction.read_text())
        value["source_reviews"][0]["records"][0]["notes"] = "changed fixture notes"
        extraction_sha = write_json(extraction, value)
        value = json.loads(verification.read_text())
        value["extraction_sha256"] = extraction_sha
        verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure == "source-anchor-mismatch":
        extraction, verification, bias, reconciliation, digest = chain(
            tmp_path, source_sha="b" * 64
        )
        value = json.loads(verification.read_text())
        value["assessments"][0]["source_retained_file_sha256"] = "c" * 64
        verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure == "padded-extraction-duplicate":
        value = json.loads(extraction.read_text())
        duplicate = dict(value["source_reviews"][0]["records"][0])
        duplicate["extraction_id"] = " e1 "
        value["source_reviews"][0]["records"].append(duplicate)
        extraction_sha = write_json(extraction, value)
        value = json.loads(verification.read_text()); value["extraction_sha256"] = extraction_sha; verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure == "padded-citation-duplicate":
        value = json.loads(verification.read_text())
        duplicate = dict(value["assessments"][0])
        duplicate["extraction_id"] = " e1 "
        value["assessments"].append(duplicate)
        verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure == "padded-bias-duplicate":
        value = json.loads(bias.read_text())
        duplicate = dict(value["assessments"][0])
        duplicate["study_id"] = " study-1 "
        value["assessments"].append(duplicate)
        bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure == "padded-reconciliation-duplicate":
        value = json.loads(reconciliation.read_text())
        duplicate = dict(value["studies"][0])
        duplicate["study_id"] = " study-1 "
        value["studies"].append(duplicate)
        digest = write_json(reconciliation, value)
    elif failure in {"padded-extraction-source", "padded-extraction-study", "padded-extraction-location"}:
        value = json.loads(extraction.read_text())
        if failure == "padded-extraction-source":
            value["source_reviews"][0]["source_id"] = " s1 "
        elif failure == "padded-extraction-study":
            value["source_reviews"][0]["records"][0]["study_id"] = " study-1 "
        elif failure == "padded-extraction-location":
            value["source_reviews"][0]["records"][0]["evidence_location"] = " page fixture "
        extraction_sha = write_json(extraction, value)
        value = json.loads(verification.read_text()); value["extraction_sha256"] = extraction_sha; verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure in {
        "padded-citation-id", "padded-citation-source", "padded-citation-study",
        "padded-citation-location", "padded-citation-rationale",
        "overclaim-citation-rationale",
    }:
        value = json.loads(verification.read_text())
        if failure == "padded-citation-id":
            value["assessments"][0]["extraction_id"] = " e1 "
        elif failure == "padded-citation-source":
            value["assessments"][0]["source_id"] = " s1 "
        elif failure == "padded-citation-study":
            value["assessments"][0]["study_id"] = " study-1 "
        elif failure == "padded-citation-location":
            value["assessments"][0]["checked_location"] = " page 4 "
        elif failure == "padded-citation-rationale":
            value["assessments"][0]["rationale"] = " fixture citation check "
        elif failure == "overclaim-citation-rationale":
            value["assessments"][0]["rationale"] = "Confirmed source support"
        verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure in {
        "padded-bias-study",
        "padded-bias-domain",
        "overclaim-bias-rationale",
        "overclaim-bias-notes",
        "padded-bias-location",
    }:
        value = json.loads(bias.read_text())
        if failure == "padded-bias-study":
            value["assessments"][0]["study_id"] = " study-1 "
        elif failure == "padded-bias-domain":
            value["assessments"][0]["domains"][0]["domain"] = " selection "
        elif failure == "overclaim-bias-rationale":
            value["assessments"][0]["domains"][0]["rationale"] = "Validated selection risk"
        elif failure == "overclaim-bias-notes":
            value["assessments"][0]["notes"] = "Confirmed low risk"
        elif failure == "padded-bias-location":
            value["assessments"][0]["domains"][0]["evidence_locations"] = [" table 1 "]
        bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure == "padded-reconciliation-study":
        value = json.loads(reconciliation.read_text())
        value["studies"][0]["study_id"] = " study-1 "
        digest = write_json(reconciliation, value)
    elif failure == "citation-provenance":
        value = json.loads(verification.read_text()); value["assessments"][0]["checked_location"] = ""; verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure == "bias-provenance":
        value = json.loads(bias.read_text()); value["assessments"][0]["domains"][0]["evidence_locations"] = []; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    output = tmp_path / "map"
    with pytest.raises(ValidationError):
        create_evidence_map(extraction, verification, bias, reconciliation, digest, output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_evidence_map_rejects_malformed_expected_reconciliation_hash(tmp_path, expected):
    extraction, verification, bias, reconciliation, _ = chain(tmp_path)
    output = tmp_path / "map"
    with pytest.raises(
        ValidationError,
        match="expected_study_reconciliation_sha256 must be a lowercase SHA-256 digest",
    ):
        create_evidence_map(extraction, verification, bias, reconciliation, expected, output)
    assert not output.exists()
