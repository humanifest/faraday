import hashlib
import json
import pytest

from research_machine.literature.snapshot import create_snapshot
from research_machine.literature.screening import create_screening, validate_screening_boundary
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
    assert result["conclusion_authorized"] is False
    assert result["publication_authorized"] is False
    assert isinstance(result["limitations"], list)
    assert snapshot.read_bytes() == original
    with pytest.raises(ValidationError, match="already exists"):
        create_screening(snapshot, digest, review, tmp_path / "screening")


def test_screening_preserves_canonical_source_and_criterion_references(tmp_path):
    snapshot, digest, review = setup_snapshot(tmp_path)
    result = create_screening(snapshot, digest, review, tmp_path / "screening")
    included = result["decisions"][0]
    retained_source_sha = json.loads(snapshot.read_text())["sources"][0][
        "retained_file_sha256"
    ]
    assert included["source_id"] == "a"
    assert included["source_retained_file_sha256"] == retained_source_sha
    assert included["criterion_refs"] == ["inclusion:1"]
    validate_screening_boundary(result)


@pytest.mark.parametrize("tamper", [
    "scientific_evidence_eligible", "conclusion_authorized", "publication_authorized",
    "limitations", "source_record_counts", "duplicate_decision_conflicts", "status",
])
def test_screening_boundary_replays_authority_counts_and_status(tmp_path, tamper):
    snapshot, digest, review = setup_snapshot(tmp_path)
    result = create_screening(snapshot, digest, review, tmp_path / "screening")
    if tamper == "scientific_evidence_eligible":
        result["scientific_evidence_eligible"] = True
    elif tamper == "conclusion_authorized":
        result["conclusion_authorized"] = True
    elif tamper == "publication_authorized":
        result["publication_authorized"] = True
    elif tamper == "limitations":
        result["limitations"] = []
    elif tamper == "source_record_counts":
        result["source_record_counts"] = {"include": 2, "exclude": 0, "unresolved": 0}
    elif tamper == "duplicate_decision_conflicts":
        result["duplicate_decision_conflicts"] = []
    else:
        result["status"] = "screening_recorded"
    with pytest.raises(ValidationError):
        validate_screening_boundary(result)


@pytest.mark.parametrize("failure", ["hash", "missing", "duplicate", "padded_source", "reason", "criterion", "padded_criterion", "duplicate_criterion", "no_criterion"])
def test_invalid_screening_never_publishes(tmp_path, failure):
    path, digest, review = setup_snapshot(tmp_path)
    if failure == "hash":
        digest = "0" * 64
    elif failure == "missing":
        review["decisions"].pop()
    elif failure == "duplicate":
        review["decisions"][1]["source_id"] = "a"
    elif failure == "padded_source":
        review["decisions"][0]["source_id"] = " a "
    elif failure == "reason":
        review["decisions"][0]["reason"] = ""
    elif failure == "criterion":
        review["decisions"][0]["criterion_refs"] = ["inclusion:999"]
    elif failure == "padded_criterion":
        review["decisions"][0]["criterion_refs"] = [" inclusion:1 "]
    elif failure == "duplicate_criterion":
        review["decisions"][0]["criterion_refs"] = ["inclusion:1", "inclusion:1"]
    else:
        review["decisions"][0]["criterion_refs"] = []
    output = tmp_path / "screening"
    with pytest.raises(ValidationError):
        create_screening(path, digest, review, output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reviewer", " Synthetic reviewer", "reviewer must be canonical"),
        ("source_id", " a", "screening source_id must be canonical"),
        ("reason", " Fixture criteria met", "screening reason must be canonical"),
        ("criterion_refs", ["inclusion:1 "], "criterion_refs item must be canonical"),
    ],
)
def test_screening_review_text_must_be_canonical(tmp_path, field, value, message):
    path, digest, review = setup_snapshot(tmp_path)
    if field == "reviewer":
        review[field] = value
    else:
        review["decisions"][0][field] = value
    output = tmp_path / "screening"
    with pytest.raises(ValidationError, match=message):
        create_screening(path, digest, review, output)
    assert not output.exists()


def test_screening_rejects_noncanonical_pinned_snapshot_source_id(tmp_path):
    path, digest, review = setup_snapshot(tmp_path)
    snapshot = json.loads(path.read_text())
    snapshot["sources"][0]["source_id"] = " a "
    path.write_text(json.dumps(snapshot, sort_keys=True) + "\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    review["decisions"][0]["source_id"] = " a "
    output = tmp_path / "screening"
    with pytest.raises(ValidationError, match="source_id must be canonical"):
        create_screening(path, digest, review, output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [" 0123", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_screening_rejects_malformed_expected_snapshot_hash(tmp_path, expected):
    path, _, review = setup_snapshot(tmp_path)
    output = tmp_path / "screening"
    with pytest.raises(ValidationError, match="expected_snapshot_sha256 must be a lowercase SHA-256 digest"):
        create_screening(path, expected, review, output)
    assert not output.exists()
