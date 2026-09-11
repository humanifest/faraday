"""Synthetic literature records, not source validation or scientific evidence."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.extraction import (
    create_extraction,
    validate_extraction_boundary,
)
from research_machine.literature.screening import create_screening
from research_machine.literature.snapshot import create_snapshot


def prepared_screening(tmp_path):
    files = []
    for index in range(2):
        path = tmp_path / f"source-{index}.txt"
        path.write_text(f"Synthetic source {index}")
        files.append(path)
    snapshot = create_snapshot({"snapshot_id": "fixture", "query": "fixture",
        "inclusion_criteria": ["Eligible"], "exclusion_criteria": ["Ineligible"],
        "sources": [{"source_id": f"s{i}", "title": f"Source {i}", "locator": f"fixture:{i}",
                     "source_class": "primary", "file": str(path)} for i, path in enumerate(files)]},
        tmp_path / "snapshot")
    review = {"reviewer": "Screening fixture", "decisions": [
        {"source_id": "s0", "decision": "include", "reason": "Eligible", "criterion_refs": ["inclusion:1"]},
        {"source_id": "s1", "decision": "exclude", "reason": "Ineligible", "criterion_refs": ["exclusion:1"]}]}
    screening = create_screening(tmp_path / "snapshot/literature-snapshot.json",
        snapshot["snapshot_sha256"], review, tmp_path / "screening")
    return tmp_path / "screening/screening.json", screening["screening_sha256"]


def extraction_review():
    return {"reviewer": "Extraction fixture", "source_reviews": [{
        "source_id": "s0", "status": "extracted", "reason": "One relevant claim",
        "records": [{"extraction_id": "ext-1", "study_id": "study-1",
            "claim_text": "The source reports a synthetic difference.", "evidence_location": "page 2, table 1",
            "epistemic_layer": "inferred", "result_direction": "mixed",
            "uncertainty": "Synthetic fixture uncertainty", "notes": "Requires independent citation verification"}],
    }]}


def test_extraction_cli_is_write_once_and_non_evidentiary(tmp_path, capsys):
    screening, digest = prepared_screening(tmp_path)
    original = screening.read_bytes()
    review_path = tmp_path / "extraction-review.json"
    review_path.write_text(json.dumps(extraction_review()))
    output = tmp_path / "extraction"
    assert main(["--json", "literature", "extract", "--screening-file", str(screening),
        "--expected-screening-sha256", digest, "--review-file", str(review_path),
        "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["record_count"] == 1
    assert result["source_reviews"][0]["records"][0]["evidence_location"] == "page 2, table 1"
    assert result["scientific_evidence_eligible"] is False
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    assert result["reviewer_identity_authenticated"] is False
    assert json.loads(screening.read_text())["conclusion_authorized"] is False
    assert screening.read_bytes() == original
    with pytest.raises(ValidationError, match="already exists"):
        create_extraction(screening, digest, extraction_review(), output)


def test_extraction_preserves_canonical_source_study_and_record_ids(tmp_path):
    screening, digest = prepared_screening(tmp_path)
    review = extraction_review()
    record = review["source_reviews"][0]["records"][0]
    retained_source_sha = json.loads(screening.read_text())["decisions"][0][
        "source_retained_file_sha256"
    ]
    result = create_extraction(screening, digest, review, tmp_path / "extraction")
    source_review = result["source_reviews"][0]
    assert source_review["source_id"] == "s0"
    assert source_review["source_retained_file_sha256"] == retained_source_sha
    assert source_review["records"][0]["extraction_id"] == "ext-1"
    assert source_review["records"][0]["study_id"] == "study-1"


@pytest.mark.parametrize("field", ["source_reason", "uncertainty", "notes"])
def test_extraction_boundary_rejects_retained_overclaiming_prose(tmp_path, field):
    screening, digest = prepared_screening(tmp_path)
    result = create_extraction(screening, digest, extraction_review(), tmp_path / "extraction")
    candidate = json.loads(json.dumps(result))
    if field == "source_reason":
        candidate["source_reviews"][0]["reason"] = "Confirmed source relevance"
    elif field == "uncertainty":
        candidate["source_reviews"][0]["records"][0]["uncertainty"] = "Validated estimate"
    else:
        candidate["source_reviews"][0]["records"][0]["notes"] = "Explained the finding"

    with pytest.raises(ValidationError, match="prohibited overclaiming language"):
        validate_extraction_boundary(
            candidate,
            candidate["record_count"],
            require_source_review_contract=True,
        )


@pytest.mark.parametrize("tamper", [
    "version",
    "screening-hash",
    "snapshot-id",
    "status",
    "reviewer-authenticated",
])
def test_extraction_boundary_replays_artifact_anchors(tmp_path, tamper):
    screening, digest = prepared_screening(tmp_path)
    result = create_extraction(screening, digest, extraction_review(), tmp_path / "extraction")
    candidate = json.loads(json.dumps(result))
    if tamper == "version":
        candidate["extraction_version"] = 2
    elif tamper == "screening-hash":
        candidate["screening_sha256"] = "A" * 64
    elif tamper == "snapshot-id":
        candidate["snapshot_id"] = " fixture "
    elif tamper == "status":
        candidate["status"] = "extraction_reviewed"
    elif tamper == "reviewer-authenticated":
        candidate["reviewer_identity_authenticated"] = True

    with pytest.raises(ValidationError):
        validate_extraction_boundary(candidate, candidate["record_count"])


@pytest.mark.parametrize("failure", [
    "hash", "excluded", "missing", "duplicate", "padded_id", "duplicate_source",
    "duplicate_screening_source", "screening-conclusion", "screening-publication",
    "screening-count", "screening-overclaim-reason", "location", "layer",
    "overclaim-source-reason", "overclaim-uncertainty", "overclaim-notes",
    "empty",
])
def test_invalid_extraction_never_publishes(tmp_path, failure):
    screening, digest = prepared_screening(tmp_path)
    review = extraction_review()
    record = review["source_reviews"][0]["records"][0]
    if failure == "hash": digest = "0" * 64
    elif failure == "excluded": review["source_reviews"][0]["source_id"] = "s1"
    elif failure == "missing": review["source_reviews"] = []
    elif failure == "duplicate": review["source_reviews"][0]["records"].append(dict(record))
    elif failure == "padded_id":
        record["extraction_id"] = " ext-1 "
    elif failure == "duplicate_source":
        duplicate = dict(review["source_reviews"][0])
        duplicate["source_id"] = "s0"
        review["source_reviews"].append(duplicate)
    elif failure == "duplicate_screening_source":
        value = json.loads(screening.read_text())
        value["decisions"].append(dict(value["decisions"][0]))
        screening.write_text(json.dumps(value, sort_keys=True) + "\n")
        digest = hashlib.sha256(screening.read_bytes()).hexdigest()
    elif failure == "screening-conclusion":
        value = json.loads(screening.read_text())
        value["conclusion_authorized"] = True
        screening.write_text(json.dumps(value, sort_keys=True) + "\n")
        digest = hashlib.sha256(screening.read_bytes()).hexdigest()
    elif failure == "screening-publication":
        value = json.loads(screening.read_text())
        value["publication_authorized"] = True
        screening.write_text(json.dumps(value, sort_keys=True) + "\n")
        digest = hashlib.sha256(screening.read_bytes()).hexdigest()
    elif failure == "screening-count":
        value = json.loads(screening.read_text())
        value["source_record_counts"]["include"] = 2
        screening.write_text(json.dumps(value, sort_keys=True) + "\n")
        digest = hashlib.sha256(screening.read_bytes()).hexdigest()
    elif failure == "screening-overclaim-reason":
        value = json.loads(screening.read_text())
        value["decisions"][0]["reason"] = "Confirmed source relevance"
        screening.write_text(json.dumps(value, sort_keys=True) + "\n")
        digest = hashlib.sha256(screening.read_bytes()).hexdigest()
    elif failure == "location": record["evidence_location"] = ""
    elif failure == "layer": record["epistemic_layer"] = "fact"
    elif failure == "overclaim-source-reason":
        review["source_reviews"][0]["reason"] = "Confirmed source relevance"
    elif failure == "overclaim-uncertainty":
        record["uncertainty"] = "Validated estimate"
    elif failure == "overclaim-notes":
        record["notes"] = "Explained the finding"
    elif failure == "empty":
        review["source_reviews"][0]["records"] = []
    output = tmp_path / "extraction"
    with pytest.raises(ValidationError):
        create_extraction(screening, digest, review, output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("target", "value", "message"),
    [
        ("reviewer", " Extraction fixture", "extraction reviewer must be canonical"),
        ("source_id", " s0", "extraction source_id must be canonical"),
        ("source_reason", " One relevant claim", "source extraction reason must be canonical"),
        ("extraction_id", "ext-1 ", "extraction extraction_id must be canonical"),
        ("study_id", " study-1", "extraction study_id must be canonical"),
        ("claim_text", " The source reports a synthetic difference.", "extraction claim_text must be canonical"),
        ("evidence_location", "page 2, table 1 ", "extraction evidence_location must be canonical"),
        ("uncertainty", " Synthetic fixture uncertainty", "extraction uncertainty must be canonical"),
        ("notes", "Requires independent citation verification ", "extraction notes must be canonical"),
    ],
)
def test_extraction_review_text_must_be_canonical(tmp_path, target, value, message):
    screening, digest = prepared_screening(tmp_path)
    review = extraction_review()
    if target == "reviewer":
        review["reviewer"] = value
    elif target == "source_id":
        review["source_reviews"][0]["source_id"] = value
    elif target == "source_reason":
        review["source_reviews"][0]["reason"] = value
    else:
        review["source_reviews"][0]["records"][0][target] = value
    output = tmp_path / "extraction"
    with pytest.raises(ValidationError, match=message):
        create_extraction(screening, digest, review, output)
    assert not output.exists()


def test_extraction_rejects_noncanonical_pinned_screening_source_id(tmp_path):
    screening, digest = prepared_screening(tmp_path)
    record = json.loads(screening.read_text())
    record["decisions"][0]["source_id"] = " s0 "
    screening.write_text(json.dumps(record, sort_keys=True) + "\n")
    digest = hashlib.sha256(screening.read_bytes()).hexdigest()
    review = extraction_review()
    review["source_reviews"][0]["source_id"] = " s0 "
    output = tmp_path / "extraction"
    with pytest.raises(ValidationError, match="screening source_id must be canonical"):
        create_extraction(screening, digest, review, output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_extraction_rejects_malformed_expected_screening_hash(tmp_path, expected):
    screening, _ = prepared_screening(tmp_path)
    output = tmp_path / "extraction"
    with pytest.raises(ValidationError, match="expected_screening_sha256 must be a lowercase SHA-256 digest"):
        create_extraction(screening, expected, extraction_review(), output)
    assert not output.exists()
