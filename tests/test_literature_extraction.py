"""Synthetic literature records, not source validation or scientific evidence."""
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.extraction import create_extraction
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
    assert screening.read_bytes() == original
    with pytest.raises(ValidationError, match="already exists"):
        create_extraction(screening, digest, extraction_review(), output)


def test_extraction_normalizes_source_study_and_record_ids(tmp_path):
    screening, digest = prepared_screening(tmp_path)
    review = extraction_review()
    review["source_reviews"][0]["source_id"] = " s0 "
    record = review["source_reviews"][0]["records"][0]
    record["extraction_id"] = " ext-1 "
    record["study_id"] = " study-1 "
    result = create_extraction(screening, digest, review, tmp_path / "extraction")
    source_review = result["source_reviews"][0]
    assert source_review["source_id"] == "s0"
    assert source_review["records"][0]["extraction_id"] == "ext-1"
    assert source_review["records"][0]["study_id"] == "study-1"


@pytest.mark.parametrize("failure", ["hash", "excluded", "missing", "duplicate", "padded_duplicate", "duplicate_source", "location", "layer", "empty"])
def test_invalid_extraction_never_publishes(tmp_path, failure):
    screening, digest = prepared_screening(tmp_path)
    review = extraction_review()
    record = review["source_reviews"][0]["records"][0]
    if failure == "hash": digest = "0" * 64
    elif failure == "excluded": review["source_reviews"][0]["source_id"] = "s1"
    elif failure == "missing": review["source_reviews"] = []
    elif failure == "duplicate": review["source_reviews"][0]["records"].append(dict(record))
    elif failure == "padded_duplicate":
        duplicate = dict(record)
        duplicate["extraction_id"] = " ext-1 "
        review["source_reviews"][0]["records"].append(duplicate)
    elif failure == "duplicate_source":
        duplicate = dict(review["source_reviews"][0])
        duplicate["source_id"] = " s0 "
        review["source_reviews"].append(duplicate)
    elif failure == "location": record["evidence_location"] = ""
    elif failure == "layer": record["epistemic_layer"] = "fact"
    elif failure == "empty":
        review["source_reviews"][0]["records"] = []
    output = tmp_path / "extraction"
    with pytest.raises(ValidationError):
        create_extraction(screening, digest, review, output)
    assert not output.exists()
