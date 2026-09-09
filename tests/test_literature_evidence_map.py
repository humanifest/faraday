"""Evidence maps join synthetic review artifacts without authorizing conclusions."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.evidence_map import create_evidence_map


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
    extraction_sha = write_json(extraction, {"extraction_version": 1, "status": "extraction_recorded", "snapshot_id": "snap",
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
        "extraction_sha256": extraction_sha, "independent_review": True,
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
        {"domain": name, "judgment": bias_judgment, "evidence_locations": ["table 1"]}
        for name in (
            "selection", "confounding", "exposure_or_intervention_classification",
            "deviations_from_intended_conditions", "missing_data", "outcome_measurement",
            "selective_reporting",
        )
    ]
    judgment_counts = {"low": 0, "some_concerns": 0, "high": 0, "unclear": 0}
    judgment_counts[bias_judgment] += 1
    bias_sha = write_json(bias, {"bias_assessment_version": 1, "status": "bias_assessment_recorded",
        "citation_verification_sha256": verification_sha, "independent_review": True,
        "overall_judgment_counts": judgment_counts,
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Overall judgments are conservative deterministic summaries of reviewer-entered domain judgments, not automated validity findings.",
            "The generic domains do not replace design-specific validated instruments or authenticate reviewer expertise or independence.",
            "Risk-of-bias assessment does not make a literature claim true or authorize quantitative synthesis.",
        ],
        "assessments": [{"study_id": "study-1", "overall_judgment": bias_judgment,
            "domains": domains}]})
    reconciliation = tmp_path / "reconciliation.json"
    reconciliation_sha = write_json(reconciliation, {"study_reconciliation_version": 1,
        "status": "study_identities_reconciled", "bias_assessment_sha256": bias_sha,
        "independent_review": True,
        "relationship_counts": {"duplicate_report": 0, "independent": 0, "overlapping_cohort": 0, "unclear": 0},
        "scientific_evidence_eligible": False,
        "limitations": [
            "Pairwise identity judgments are reviewer assertions; metadata similarity cannot prove cohort independence.",
            "Overlap, duplicate, and unclear relationships are preserved and block a reconciled status rather than being silently deduplicated.",
            "Study reconciliation does not validate outcomes, assess applicability, or authorize quantitative synthesis.",
        ],
        "studies": [{"study_id": "study-1"}], "relationships": []})
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
    assert result["scientific_evidence_eligible"] is False
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
    "reconciliation-not-independent", "reconciliation-count-drift",
    "reconciliation-limitations-missing", "reconciliation-padded-limitation",
    "coverage", "padded-extraction-duplicate", "padded-citation-duplicate",
    "padded-bias-duplicate", "padded-reconciliation-duplicate",
    "padded-extraction-source", "padded-extraction-study", "padded-extraction-location",
    "padded-citation-id", "padded-citation-source", "padded-citation-study",
    "padded-citation-location", "padded-citation-rationale", "padded-bias-study",
    "padded-bias-domain", "padded-bias-location", "padded-reconciliation-study",
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
        "reconciliation-count-drift", "reconciliation-limitations-missing",
        "reconciliation-padded-limitation",
    }:
        value = json.loads(reconciliation.read_text())
        if failure == "reconciliation-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "reconciliation-not-independent":
            value["independent_review"] = False
        elif failure == "reconciliation-count-drift":
            value["relationship_counts"]["independent"] = 1
        elif failure == "reconciliation-limitations-missing":
            value["limitations"] = []
        elif failure == "reconciliation-padded-limitation":
            value["limitations"][0] = " " + value["limitations"][0]
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
        value["studies"].append({"study_id": " study-1 "})
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
        verification_sha = write_json(verification, value)
        value = json.loads(bias.read_text()); value["citation_verification_sha256"] = verification_sha; bias_sha = write_json(bias, value)
        value = json.loads(reconciliation.read_text()); value["bias_assessment_sha256"] = bias_sha; digest = write_json(reconciliation, value)
    elif failure in {"padded-bias-study", "padded-bias-domain", "padded-bias-location"}:
        value = json.loads(bias.read_text())
        if failure == "padded-bias-study":
            value["assessments"][0]["study_id"] = " study-1 "
        elif failure == "padded-bias-domain":
            value["assessments"][0]["domains"][0]["domain"] = " selection "
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
