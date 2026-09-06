from __future__ import annotations

import json
from pathlib import Path

from research_machine.literature.snapshot import create_snapshot


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
    create_snapshot({**manifest, "sources": list(reversed(sources))}, tmp_path / "reversed")
    reversed_snapshot = json.loads((tmp_path / "reversed/literature-snapshot.json").read_text())
    assert saved["deduplication"] == reversed_snapshot["deduplication"]
