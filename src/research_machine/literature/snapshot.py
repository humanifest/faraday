from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_machine.domain.errors import ValidationError


_SOURCE_CLASSES = {"primary", "secondary", "registry", "preprint", "other"}


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"literature snapshot {field} must be non-empty text")
    if value != value.strip():
        raise ValidationError(f"literature snapshot {field} must be canonical without surrounding whitespace")
    return value


def create_snapshot(manifest: dict[str, Any], output: Path) -> dict[str, Any]:
    """Create a write-once source snapshot from files the researcher retained."""
    allowed = {"snapshot_id", "query", "inclusion_criteria", "exclusion_criteria", "sources"}
    unknown = sorted(set(manifest) - allowed)
    if unknown:
        raise ValidationError("unknown literature snapshot fields: " + ", ".join(unknown))
    snapshot_id = _text(manifest.get("snapshot_id"), "snapshot_id")
    query = _text(manifest.get("query"), "query")
    criteria: dict[str, list[str]] = {}
    for field in ("inclusion_criteria", "exclusion_criteria"):
        value = manifest.get(field, [])
        if (not isinstance(value, list)
                or any(not isinstance(item, str) or not item.strip() for item in value)
                or any(isinstance(item, str) and item != item.strip() for item in value)):
            raise ValidationError(f"literature snapshot {field} must be an array of canonical non-empty strings")
        criteria[field] = value
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValidationError("literature snapshot sources must be a non-empty array")
    seen_ids: set[str] = set()
    records: list[dict[str, Any]] = []
    for item in sources:
        if not isinstance(item, dict):
            raise ValidationError("each literature source must be an object")
        allowed_source = {"source_id", "title", "locator", "source_class", "file"}
        extra = sorted(set(item) - allowed_source)
        if extra:
            raise ValidationError("unknown literature source fields: " + ", ".join(extra))
        source_id = _text(item.get("source_id"), "source_id")
        if source_id in seen_ids:
            raise ValidationError(f"duplicate literature source_id: {source_id}")
        seen_ids.add(source_id)
        source_class = item.get("source_class")
        if source_class not in _SOURCE_CLASSES:
            raise ValidationError("source_class must be one of: " + ", ".join(sorted(_SOURCE_CLASSES)))
        path = Path(_text(item.get("file"), "source file")).expanduser().resolve()
        if not path.is_file():
            raise ValidationError(f"literature source file is not a file: {path}")
        digest, size = _hash(path)
        records.append({
            "source_id": source_id,
            "title": _text(item.get("title"), "source title"),
            "locator": _text(item.get("locator"), "source locator"),
            "source_class": source_class,
            "retained_file_sha256": digest,
            "retained_file_size_bytes": size,
        })
    content_groups: dict[str, list[str]] = {}
    for record in records:
        content_groups.setdefault(record["retained_file_sha256"], []).append(record["source_id"])
    duplicates = [{"retained_file_sha256": digest, "source_ids": sorted(ids)}
                  for digest, ids in sorted(content_groups.items()) if len(ids) > 1]
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError(f"literature snapshot output path already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "snapshot_version": 1,
        "snapshot_id": snapshot_id,
        "query": query,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **criteria,
        "sources": records,
        "deduplication": {
            "method": "exact_retained_file_sha256", "source_record_count": len(records),
            "unique_content_count": len(content_groups), "duplicate_groups": duplicates,
            "limitations": "Byte identity is not study identity. Distinct files may describe the same study; metadata and screening conflicts remain unresolved. No source records were removed.",
        },
        "evidence_boundary": "Retrieved sources are not accepted claims. Screen, extract, assess bias, and cite each claim separately.",
    }
    content = (json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-", dir=root.parent) as temporary:
        staging = Path(temporary) / root.name
        staging.mkdir()
        (staging / "literature-snapshot.json").write_bytes(content)
        try:
            os.replace(staging, root)
        except OSError as exc:
            raise ValidationError(f"could not publish literature snapshot atomically: {exc}") from exc
    return {
        "path": str(root),
        "snapshot_id": snapshot_id,
        "source_count": len(records),
        "unique_content_count": len(content_groups),
        "duplicate_group_count": len(duplicates),
        "snapshot_sha256": hashlib.sha256(content).hexdigest(),
    }
