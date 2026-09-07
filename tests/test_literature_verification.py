"""Synthetic citation reviews; no fixture claim is scientific evidence."""
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.verification import create_citation_verification


def extraction_file(tmp_path):
    value = {
        "extraction_version": 1, "status": "extraction_recorded",
        "snapshot_id": "snapshot-fixture", "reviewer": "Extractor One",
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
    import hashlib
    return path, hashlib.sha256(encoded).hexdigest()


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
    with pytest.raises(ValidationError, match="already exists"):
        create_citation_verification(extraction, digest, review(), output)


def test_unsupported_claim_is_preserved_and_requires_review(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    result = create_citation_verification(extraction, digest, review("unsupported"), tmp_path / "verification")
    assert result["status"] == "review_required"
    assert result["verdict_counts"]["unsupported"] == 1
    assert any(item["verdict"] == "unsupported" for item in result["assessments"])


def test_citation_verification_normalizes_extraction_handles(tmp_path):
    extraction, digest = extraction_file(tmp_path)
    candidate = review()
    candidate["assessments"][0]["extraction_id"] = " claim-1 "
    result = create_citation_verification(
        extraction, digest, candidate, tmp_path / "verification"
    )
    assert result["assessments"][0]["extraction_id"] == "claim-1"


@pytest.mark.parametrize("failure", ["hash", "same-reviewer", "missing", "duplicate", "padded_duplicate", "padded_extraction_duplicate", "unknown", "location", "verdict"])
def test_invalid_citation_review_never_publishes(tmp_path, failure):
    extraction, digest = extraction_file(tmp_path)
    candidate = review()
    if failure == "hash": digest = "0" * 64
    elif failure == "same-reviewer": candidate["reviewer"] = " extractor one "
    elif failure == "missing": candidate["assessments"].pop()
    elif failure == "duplicate": candidate["assessments"][1]["extraction_id"] = "claim-1"
    elif failure == "padded_duplicate": candidate["assessments"][1]["extraction_id"] = " claim-1 "
    elif failure == "padded_extraction_duplicate":
        value = json.loads(extraction.read_text())
        duplicate = dict(value["source_reviews"][0]["records"][0])
        duplicate["extraction_id"] = " claim-1 "
        value["source_reviews"][0]["records"].append(duplicate)
        encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
        extraction.write_bytes(encoded)
        import hashlib
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "unknown": candidate["assessments"][0]["extraction_id"] = "claim-x"
    elif failure == "location": candidate["assessments"][0]["checked_location"] = ""
    elif failure == "verdict": candidate["assessments"][0]["verdict"] = "true"
    output = tmp_path / "verification"
    with pytest.raises(ValidationError):
        create_citation_verification(extraction, digest, candidate, output)
    assert not output.exists()
