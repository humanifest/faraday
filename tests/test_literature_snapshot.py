from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.literature.screening import create_screening
from research_machine.literature.snapshot import create_snapshot, validate_snapshot_boundary


def test_literature_snapshot_hashes_retained_source_and_preserves_boundary(
    tmp_path: Path
) -> None:
    source = tmp_path / "paper.txt"
    source.write_text("retained source", encoding="utf-8")
    result = create_snapshot({
        "snapshot_id": "sleep-search-v1", "query": "sleep concentration",
        "inclusion_criteria": ["Primary studies"], "exclusion_criteria": [],
        "sources": [{"source_id": "s1", "title": "Study", "locator": "doi:example", "source_class": "primary", "file": str(source)}],
    }, tmp_path / "snapshot")
    assert result["source_count"] == 1
    saved = json.loads((tmp_path / "snapshot" / "literature-snapshot.json").read_text())
    assert saved["sources"][0]["retained_file_sha256"]
    assert "not accepted claims" in saved["evidence_boundary"]
    validate_snapshot_boundary(saved)


def test_byte_duplicates_are_grouped_without_deleting_source_records(tmp_path):
    first = tmp_path / "first.txt"
    copy = tmp_path / "copy.txt"
    distinct = tmp_path / "distinct.txt"
    first.write_bytes(b"synthetic literature fixture")
    copy.write_bytes(first.read_bytes())
    distinct.write_bytes(b"different synthetic content")
    sources = [{"source_id": source_id, "title": "Fixture", "locator": "fixture:" + source_id,
                "source_class": source_class, "file": str(path)}
               for source_id, path, source_class in [("z", first, "primary"), ("a", copy, "secondary"), ("b", distinct, "primary")]]
    manifest = {"snapshot_id": "fixture", "query": "fixture query", "sources": sources}
    result = create_snapshot(manifest, tmp_path / "snapshot")
    saved = json.loads((tmp_path / "snapshot/literature-snapshot.json").read_text())
    assert result["source_count"] == 3
    assert result["unique_content_count"] == 2
    assert result["duplicate_group_count"] == 1
    assert len(saved["sources"]) == 3
    assert saved["deduplication"]["duplicate_groups"][0]["source_ids"] == ["a", "z"]
    assert saved["sources"][0]["source_class"] == "primary"
    assert saved["sources"][1]["source_class"] == "secondary"
    assert "not study identity" in saved["deduplication"]["limitations"]
    validate_snapshot_boundary(saved)
    create_snapshot({**manifest, "sources": list(reversed(sources))}, tmp_path / "reversed")
    reversed_snapshot = json.loads((tmp_path / "reversed/literature-snapshot.json").read_text())
    assert saved["deduplication"] == reversed_snapshot["deduplication"]


def test_snapshot_boundary_replays_deduplication_and_non_evidence_boundary(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    copy = tmp_path / "copy.txt"
    first.write_text("same retained source", encoding="utf-8")
    copy.write_text("same retained source", encoding="utf-8")
    create_snapshot({
        "snapshot_id": "fixture",
        "query": "fixture query",
        "sources": [
            {"source_id": "s1", "title": "Study 1", "locator": "doi:1", "source_class": "primary", "file": str(first)},
            {"source_id": "s2", "title": "Study 2", "locator": "doi:2", "source_class": "secondary", "file": str(copy)},
        ],
    }, tmp_path / "snapshot")
    saved = json.loads((tmp_path / "snapshot/literature-snapshot.json").read_text())

    for mutate, message in [
        (lambda candidate: candidate.update({"snapshot_version": 2}), "unsupported literature snapshot"),
        (lambda candidate: candidate.__setitem__("evidence_boundary", "Retrieved sources are accepted claims."), "non-evidence boundary"),
        (lambda candidate: candidate["deduplication"].update({"source_record_count": 1}), "deduplication does not replay"),
        (lambda candidate: candidate["deduplication"].update({"unique_content_count": 2}), "deduplication does not replay"),
        (lambda candidate: candidate["deduplication"].update({"duplicate_groups": []}), "deduplication does not replay"),
        (lambda candidate: candidate["sources"][0].update({"retained_file_sha256": "A" * 64}), "lowercase SHA-256"),
    ]:
        candidate = json.loads(json.dumps(saved))
        mutate(candidate)
        with pytest.raises(ValidationError, match=message):
            validate_snapshot_boundary(candidate)


def test_screening_replays_snapshot_boundary_before_trusting_sources(tmp_path: Path) -> None:
    source = tmp_path / "paper.txt"
    source.write_text("retained source", encoding="utf-8")
    create_snapshot({
        "snapshot_id": "fixture",
        "query": "fixture query",
        "inclusion_criteria": ["Eligible"],
        "sources": [{
            "source_id": "s1", "title": "Study", "locator": "doi:example",
            "source_class": "primary", "file": str(source),
        }],
    }, tmp_path / "snapshot")
    snapshot_path = tmp_path / "snapshot/literature-snapshot.json"
    tampered = json.loads(snapshot_path.read_text())
    tampered["deduplication"]["source_record_count"] = 2
    tampered_path = tmp_path / "tampered-snapshot.json"
    encoded = (json.dumps(tampered, indent=2, sort_keys=True) + "\n").encode()
    tampered_path.write_bytes(encoded)
    review = {
        "reviewer": "reviewer",
        "decisions": [{
            "source_id": "s1",
            "decision": "include",
            "reason": "Eligible",
            "criterion_refs": ["inclusion:1"],
        }],
    }

    with pytest.raises(ValidationError, match="deduplication does not replay"):
        create_screening(
            tampered_path,
            hashlib.sha256(encoded).hexdigest(),
            review,
            tmp_path / "screening",
        )
    assert not (tmp_path / "screening").exists()


@pytest.mark.parametrize("field", ["snapshot_id", "query"])
def test_literature_snapshot_rejects_padded_manifest_text(tmp_path: Path, field) -> None:
    source = tmp_path / "paper.txt"
    source.write_text("retained source", encoding="utf-8")
    manifest = {
        "snapshot_id": "fixture",
        "query": "fixture query",
        "sources": [{
            "source_id": "s1", "title": "Study", "locator": "doi:example",
            "source_class": "primary", "file": str(source),
        }],
    }
    manifest[field] = f" {manifest[field]} "
    output = tmp_path / "snapshot"
    with pytest.raises(ValidationError, match="canonical"):
        create_snapshot(manifest, output)
    assert not output.exists()


@pytest.mark.parametrize("field", ["inclusion_criteria", "exclusion_criteria"])
def test_literature_snapshot_rejects_padded_criteria(tmp_path: Path, field) -> None:
    source = tmp_path / "paper.txt"
    source.write_text("retained source", encoding="utf-8")
    manifest = {
        "snapshot_id": "fixture",
        "query": "fixture query",
        "inclusion_criteria": [" Eligible "] if field == "inclusion_criteria" else [],
        "exclusion_criteria": [" Ineligible "] if field == "exclusion_criteria" else [],
        "sources": [{
            "source_id": "s1", "title": "Study", "locator": "doi:example",
            "source_class": "primary", "file": str(source),
        }],
    }
    output = tmp_path / "snapshot"
    with pytest.raises(ValidationError, match="canonical"):
        create_snapshot(manifest, output)
    assert not output.exists()


@pytest.mark.parametrize("field", ["source_id", "title", "locator", "file"])
def test_literature_snapshot_rejects_padded_source_metadata(tmp_path: Path, field) -> None:
    source = tmp_path / "paper.txt"
    source.write_text("retained source", encoding="utf-8")
    record = {
        "source_id": "s1", "title": "Study", "locator": "doi:example",
        "source_class": "primary", "file": str(source),
    }
    record[field] = f" {record[field]} "
    output = tmp_path / "snapshot"
    with pytest.raises(ValidationError, match="canonical"):
        create_snapshot({
            "snapshot_id": "fixture", "query": "fixture query",
            "sources": [record],
        }, output)
    assert not output.exists()
