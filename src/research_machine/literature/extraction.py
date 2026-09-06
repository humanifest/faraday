"""Write-once source-bound extraction; extracted claims remain review assertions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.snapshot import _text

_LAYERS = {"observed", "derived", "model-dependent", "inferred", "hypothesized", "speculative"}
_DIRECTIONS = {"supports", "weakens", "mixed", "null", "not_applicable"}


def create_extraction(screening_path: Path, expected_sha256: str,
                      review: dict[str, Any], output: Path) -> dict[str, Any]:
    try:
        content = screening_path.read_bytes()
        screening = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("could not read valid screening JSON") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValidationError("extraction screening does not match the expected SHA-256")
    if (not isinstance(screening, dict) or screening.get("screening_version") != 2
            or screening.get("status") != "screening_recorded"):
        raise ValidationError("extraction requires a completed version 2 screening record")
    decisions = screening.get("decisions")
    if not isinstance(decisions, list):
        raise ValidationError("screening decisions must be an array")
    included = {item.get("source_id") for item in decisions
                if isinstance(item, dict) and item.get("decision") == "include"}
    if not included:
        raise ValidationError("extraction requires at least one included source")
    if not isinstance(review, dict) or set(review) != {"reviewer", "source_reviews"}:
        raise ValidationError("extraction review requires exactly reviewer and source_reviews")
    reviewer = _text(review["reviewer"], "extraction reviewer")
    source_reviews = review["source_reviews"]
    if not isinstance(source_reviews, list):
        raise ValidationError("source_reviews must be an array")
    by_source: dict[str, dict[str, Any]] = {}
    extraction_ids: set[str] = set()
    for source_review in source_reviews:
        if not isinstance(source_review, dict) or set(source_review) != {
            "source_id", "status", "reason", "records"
        }:
            raise ValidationError("each source review requires exactly source_id, status, reason, and records")
        source_id = _text(source_review["source_id"], "extraction source_id")
        if source_id in by_source:
            raise ValidationError("duplicate extraction source review")
        if source_id not in included:
            raise ValidationError("extraction may reference only included sources")
        status, records = source_review["status"], source_review["records"]
        if status not in {"extracted", "no_extractable_claim"} or not isinstance(records, list):
            raise ValidationError("source extraction status or records are invalid")
        _text(source_review["reason"], "source extraction reason")
        if (status == "extracted") != bool(records):
            raise ValidationError("extracted sources require records; no_extractable_claim sources require none")
        normalized_records = []
        for record in records:
            required = {"extraction_id", "study_id", "claim_text", "evidence_location",
                        "epistemic_layer", "result_direction", "uncertainty", "notes"}
            if not isinstance(record, dict) or set(record) != required:
                raise ValidationError("extraction record fields do not match the documented contract")
            normalized = {key: _text(record[key], f"extraction {key}") for key in required}
            identifier = normalized["extraction_id"]
            if identifier in extraction_ids:
                raise ValidationError("duplicate extraction_id")
            extraction_ids.add(identifier)
            if normalized["epistemic_layer"] not in _LAYERS:
                raise ValidationError("invalid extraction epistemic_layer")
            if normalized["result_direction"] not in _DIRECTIONS:
                raise ValidationError("invalid extraction result_direction")
            normalized_records.append(normalized)
        by_source[source_id] = {"source_id": source_id, "status": status,
                                "reason": source_review["reason"].strip(),
                                "records": sorted(normalized_records, key=lambda item: item["extraction_id"])}
    if set(by_source) != included:
        raise ValidationError("source reviews must cover exactly all included sources")
    result = {
        "extraction_version": 1, "screening_sha256": digest,
        "snapshot_id": screening.get("snapshot_id"), "reviewer": reviewer,
        "source_reviews": [by_source[source_id] for source_id in sorted(by_source)],
        "record_count": len(extraction_ids), "status": "extraction_recorded",
        "scientific_evidence_eligible": False,
        "limitations": [
            "Records are reviewer assertions bound to source IDs and locations; the machine has not verified that source text supports them.",
            "Shared study_id values group reports only by reviewer declaration and do not establish independent studies.",
            "Extraction does not perform risk-of-bias assessment, resolve disagreements, accept claims as facts, or conduct synthesis.",
        ],
    }
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("extraction output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".extraction-", dir=root.parent) as temporary:
        staging = Path(temporary) / "extraction"
        staging.mkdir()
        (staging / "extraction.json").write_bytes(encoded)
        os.replace(staging, root)
    return {"path": str(root), "extraction_sha256": hashlib.sha256(encoded).hexdigest(), **result}
