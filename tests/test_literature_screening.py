import json
import pytest

from research_machine.literature.snapshot import create_snapshot
from research_machine.literature.screening import create_screening
from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main


def setup_snapshot(tmp_path):
    paper = tmp_path / "fixture.txt"
    paper.write_text("Synthetic source fixture")
    result = create_snapshot({"snapshot_id": "fixture", "query": "fixture query",
        "inclusion_criteria": ["Meets synthetic fixture criterion"], "exclusion_criteria": ["Fails synthetic fixture criterion"],
        "sources": [{"source_id": source_id, "title": "Fixture", "locator": "fixture:" + source_id,
                     "source_class": "primary", "file": str(paper)} for source_id in ("a", "b")]}, tmp_path / "snapshot")
    path = tmp_path / "snapshot/literature-snapshot.json"
    review = {"reviewer": "Synthetic reviewer", "decisions": [
        {"source_id": "a", "decision": "include", "reason": "Fixture criteria met", "criterion_refs": ["inclusion:1"]},
        {"source_id": "b", "decision": "exclude", "reason": "Conflicting fixture decision", "criterion_refs": ["exclusion:1"]}]}
    return path, result["snapshot_sha256"], review


def test_screening_cli_preserves_duplicate_disagreement(tmp_path, capsys):
    snapshot, digest, review = setup_snapshot(tmp_path)
    original = snapshot.read_bytes()
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review))
    assert main(["--json", "literature", "screen", "--snapshot-file", str(snapshot),
        "--expected-snapshot-sha256", digest, "--review-file", str(path), "--output", str(tmp_path / "screening")]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "review_required"
    assert result["duplicate_decision_conflicts"] == [["a", "b"]]
    assert result["scientific_evidence_eligible"] is False
    assert snapshot.read_bytes() == original
    with pytest.raises(ValidationError, match="already exists"):
        create_screening(snapshot, digest, review, tmp_path / "screening")


def test_screening_normalizes_source_and_criterion_references(tmp_path):
    snapshot, digest, review = setup_snapshot(tmp_path)
    review["decisions"][0]["source_id"] = " a "
    review["decisions"][0]["criterion_refs"] = [" inclusion:1 "]
    result = create_screening(snapshot, digest, review, tmp_path / "screening")
    included = result["decisions"][0]
    assert included["source_id"] == "a"
    assert included["criterion_refs"] == ["inclusion:1"]


@pytest.mark.parametrize("failure", ["hash", "missing", "duplicate", "padded_duplicate", "reason", "criterion", "duplicate_criterion", "no_criterion"])
def test_invalid_screening_never_publishes(tmp_path, failure):
    path, digest, review = setup_snapshot(tmp_path)
    if failure == "hash":
        digest = "0" * 64
    elif failure == "missing":
        review["decisions"].pop()
    elif failure == "duplicate":
        review["decisions"][1]["source_id"] = "a"
    elif failure == "padded_duplicate":
        review["decisions"][1]["source_id"] = " a "
    elif failure == "reason":
        review["decisions"][0]["reason"] = ""
    elif failure == "criterion":
        review["decisions"][0]["criterion_refs"] = ["inclusion:999"]
    elif failure == "duplicate_criterion":
        review["decisions"][0]["criterion_refs"] = ["inclusion:1", " inclusion:1 "]
    else:
        review["decisions"][0]["criterion_refs"] = []
    output = tmp_path / "screening"
    with pytest.raises(ValidationError):
        create_screening(path, digest, review, output)
    assert not output.exists()
