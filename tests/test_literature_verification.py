"""Synthetic citation reviews; no fixture claim is scientific evidence."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.verification import create_citation_verification


def extraction_file(tmp_path):
    value = {
        "extraction_version": 1, "status": "extraction_recorded",
        "snapshot_id": "snapshot-fixture", "reviewer": "Extractor One",
        "record_count": 2,
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Records are reviewer assertions bound to source IDs and locations; the machine has not verified that source text supports them.",
            "Extraction does not perform risk-of-bias assessment, resolve disagreements, accept claims as facts, or conduct synthesis.",
        ],
        "source_reviews": [{"source_id": "source-1", "status": "extracted", "reason": "fixture",
            "records": [
                {"extraction_id": "claim-1", "study_id": "study-1", "claim_text": "Synthetic claim one",
                 "evidence_location": "page 1", "epistemic_layer": "inferred", "result_direction": "supports",
                 "uncertainty": "fixture", "notes": "fixture"},
                {"extraction_id": "claim-2", "study_id": "study-1", "claim_text": "Synthetic claim two",
                 "evidence_location": "page 2", "epistemic_layer": "observed", "result_direction": "null",
                 "uncertainty": "fixture", "notes": "fixture"},
            ]}],
    }
    path = tmp_path / "extraction.json"
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


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


def review(verdict="supported"):
    return {"reviewer": "Verifier Two", "assessments": [
        {"extraction_id": "claim-1", "verdict": verdict, "checked_location": "page 1", "rationale": "Text checked"},
        {"extraction_id": "claim-2", "verdict": "partially_supported", "checked_location": "page 2", "rationale": "Qualified wording"},
    ]}


def test_citation_verification_cli_is_exhaustive_independent_and_write_once(tmp_path, capsys):
    extraction, digest = extraction_file(tmp_path)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review()))
    output = tmp_path / "verification"
    assert main(["--json", "literature", "verify-citations", "--extraction-file", str(extraction),
        "--expected-extraction-sha256", digest, "--review-file", str(review_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "citation_review_recorded"
    assert result["independent_review"] is True
    assert result["scientific_evidence_eligible"] is False
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    with pytest.raises(ValidationError, match="already exists"):
        create_citation_verification(extraction, digest, review(), output)


def test_unsupported_claim_is_preserved_and_requires_review(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    result = create_citation_verification(extraction, digest, review("unsupported"), tmp_path / "verification")
    assert result["status"] == "review_required"
    assert result["verdict_counts"]["unsupported"] == 1
    assert any(item["verdict"] == "unsupported" for item in result["assessments"])


def test_citation_verification_preserves_canonical_extraction_handles(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    extraction_record = json.loads(extraction.read_text())["source_reviews"][0]["records"][0]
    result = create_citation_verification(
        extraction, digest, review(), tmp_path / "verification"
    )
    assert result["assessments"][0]["extraction_id"] == "claim-1"
    assert result["assessments"][0]["checked_location"] == "page 1"
    assert result["assessments"][0]["extraction_claim_sha256"] == claim_digest(
        "source-1", extraction_record
    )


def test_citation_verification_binds_retained_source_bytes_when_available(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    retained_source_sha = "b" * 64
    value = json.loads(extraction.read_text())
    value["source_reviews"][0]["source_retained_file_sha256"] = retained_source_sha
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    extraction.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()

    result = create_citation_verification(
        extraction, digest, review(), tmp_path / "verification"
    )
    extraction_record = value["source_reviews"][0]["records"][0]
    assert result["assessments"][0]["source_retained_file_sha256"] == retained_source_sha
    assert result["assessments"][0]["extraction_claim_sha256"] == claim_digest(
        "source-1", extraction_record, retained_source_sha
    )


@pytest.mark.parametrize("failure", [
    "hash",
    "same-reviewer",
    "padded-reviewer",
    "missing",
    "duplicate",
    "padded_duplicate",
    "padded_extraction_duplicate",
    "padded-extractor",
    "padded-source",
    "padded-study",
    "padded-claim-text",
    "padded-evidence-location",
    "extraction-authority",
    "extraction-conclusion-authority",
    "extraction-publication-authority",
    "extraction-count-drift",
    "extraction-limitations-missing",
    "extraction-padded-limitation",
    "unknown",
    "location",
    "padded-location",
    "padded-rationale",
    "verdict",
    "missing-claim-field",
])
def test_invalid_citation_review_never_publishes(tmp_path, failure):
    extraction, digest = extraction_file(tmp_path)
    candidate = review()
    if failure == "hash": digest = "0" * 64
    elif failure == "same-reviewer": candidate["reviewer"] = "Extractor One"
    elif failure == "padded-reviewer": candidate["reviewer"] = " Verifier Two "
    elif failure == "missing": candidate["assessments"].pop()
    elif failure == "duplicate": candidate["assessments"][1]["extraction_id"] = "claim-1"
    elif failure == "padded_duplicate": candidate["assessments"][1]["extraction_id"] = " claim-1 "
    elif failure in {
        "padded_extraction_duplicate",
        "padded-extractor",
        "padded-source",
        "padded-study",
        "padded-claim-text",
        "padded-evidence-location",
        "extraction-authority",
        "extraction-conclusion-authority",
        "extraction-publication-authority",
        "extraction-count-drift",
        "extraction-limitations-missing",
        "extraction-padded-limitation",
        "missing-claim-field",
    }:
        value = json.loads(extraction.read_text())
        if failure == "padded_extraction_duplicate":
            duplicate = dict(value["source_reviews"][0]["records"][0])
            duplicate["extraction_id"] = " claim-1 "
            value["source_reviews"][0]["records"].append(duplicate)
        elif failure == "padded-extractor":
            value["reviewer"] = " Extractor One "
        elif failure == "padded-source":
            value["source_reviews"][0]["source_id"] = " source-1 "
        elif failure == "padded-study":
            value["source_reviews"][0]["records"][0]["study_id"] = " study-1 "
        elif failure == "padded-claim-text":
            value["source_reviews"][0]["records"][0]["claim_text"] = " Synthetic claim one "
        elif failure == "padded-evidence-location":
            value["source_reviews"][0]["records"][0]["evidence_location"] = " page 1 "
        elif failure == "missing-claim-field":
            del value["source_reviews"][0]["records"][0]["notes"]
        elif failure == "extraction-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "extraction-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "extraction-publication-authority":
            value["publication_authorized"] = True
        elif failure == "extraction-count-drift":
            value["record_count"] = 1
        elif failure == "extraction-limitations-missing":
            value["limitations"] = []
        elif failure == "extraction-padded-limitation":
            value["limitations"][0] = " " + value["limitations"][0]
        encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
        extraction.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "unknown": candidate["assessments"][0]["extraction_id"] = "claim-x"
    elif failure == "location": candidate["assessments"][0]["checked_location"] = ""
    elif failure == "padded-location": candidate["assessments"][0]["checked_location"] = " page 1 "
    elif failure == "padded-rationale": candidate["assessments"][0]["rationale"] = " Text checked "
    elif failure == "verdict": candidate["assessments"][0]["verdict"] = "true"
    output = tmp_path / "verification"
    with pytest.raises(ValidationError):
        create_citation_verification(extraction, digest, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_citation_verification_rejects_malformed_expected_extraction_hash(tmp_path, expected):
    extraction, _ = extraction_file(tmp_path)
    output = tmp_path / "verification"
    with pytest.raises(ValidationError, match="expected_extraction_sha256 must be a lowercase SHA-256 digest"):
        create_citation_verification(extraction, expected, review(), output)
    assert not output.exists()
