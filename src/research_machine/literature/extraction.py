"""Write-once source-bound extraction; extracted claims remain review assertions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.hashes import require_sha256
from research_machine.literature.json_loading import load_json_object
from research_machine.literature.screening import validate_screening_boundary
from research_machine.literature.snapshot import _text

_LAYERS = {"observed", "derived", "model-dependent", "inferred", "hypothesized", "speculative"}
_DIRECTIONS = {"supports", "weakens", "mixed", "null", "not_applicable"}
_LEGACY_SOURCE_ANCHOR = "legacy_missing"
_EXTRACTION_PROSE_OVERCLAIM = re.compile(
    r"\b(?:proved|confirmed|explained|validates?|validated)\b",
    re.IGNORECASE,
)


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def _bounded_extraction_text(value: Any, field: str) -> str:
    text = _canonical_text(value, field)
    if _EXTRACTION_PROSE_OVERCLAIM.search(text):
        raise ValidationError(
            f"{field} uses extraction-prohibited overclaiming language; "
            "describe the extraction judgment without claiming proof, "
            "confirmation, validation, or explanation"
        )
    return text


def validate_extraction_boundary(
    extraction: dict[str, Any],
    extracted_record_count: int | None = None,
    *,
    require_source_review_contract: bool = False,
) -> None:
    """Replay extraction non-authority and retained record-count boundaries."""
    if extraction.get("extraction_version") != 1:
        raise ValidationError("extraction version is invalid")
    require_sha256(extraction.get("screening_sha256"), "extraction screening_sha256")
    _canonical_text(extraction.get("snapshot_id"), "extraction snapshot_id")
    if extraction.get("status") != "extraction_recorded":
        raise ValidationError("extraction status is invalid")
    if extraction.get("scientific_evidence_eligible") is not False:
        raise ValidationError("extraction record must remain scientifically ineligible")
    if extraction.get("conclusion_authorized") is not False:
        raise ValidationError("extraction record must not authorize conclusions")
    if extraction.get("publication_authorized") is not False:
        raise ValidationError("extraction record must not authorize publication claims")
    if extraction.get("reviewer_identity_authenticated", False) is not False:
        raise ValidationError("extraction record must not authenticate reviewer identity")
    limitations = extraction.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("extraction record requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _bounded_extraction_text(
            limitation,
            f"extraction limitation {index + 1}",
        )
    if (
        extracted_record_count is not None
        and extraction.get("record_count") != extracted_record_count
    ):
        raise ValidationError("extraction record_count does not replay from extracted claims")
    if require_source_review_contract:
        source_reviews = extraction.get("source_reviews")
        if not isinstance(source_reviews, list):
            raise ValidationError("extraction source_reviews must be an array")
        source_ids: set[str] = set()
        replayed_record_count = 0
        allowed_keys = {
            "source_id",
            "source_retained_file_sha256",
            "status",
            "reason",
            "records",
        }
        required_keys = {"source_id", "status", "reason", "records"}
        for source_review in source_reviews:
            if not isinstance(source_review, dict):
                raise ValidationError("extraction source review must be an object")
            keys = set(source_review)
            if not required_keys <= keys <= allowed_keys:
                raise ValidationError(
                    "extraction source review fields do not match the documented contract"
                )
            source_id = _canonical_text(
                source_review.get("source_id"), "extraction source_id"
            )
            if source_id in source_ids:
                raise ValidationError("extraction source_reviews contain duplicate source_id")
            source_ids.add(source_id)
            if "source_retained_file_sha256" in source_review:
                source_anchor = source_review.get("source_retained_file_sha256")
                if source_anchor != _LEGACY_SOURCE_ANCHOR:
                    require_sha256(
                        source_anchor,
                        "extraction source_retained_file_sha256",
                    )
            status = source_review.get("status")
            records = source_review.get("records")
            if status not in {"extracted", "no_extractable_claim"} or not isinstance(
                records, list
            ):
                raise ValidationError("source extraction status or records are invalid")
            _bounded_extraction_text(
                source_review.get("reason"), "source extraction reason"
            )
            if (status == "extracted") != bool(records):
                raise ValidationError(
                    "extracted sources require records; no_extractable_claim sources require none"
                )
            required_record_fields = {
                "extraction_id",
                "study_id",
                "claim_text",
                "evidence_location",
                "epistemic_layer",
                "result_direction",
                "uncertainty",
                "notes",
            }
            seen_records: set[str] = set()
            for record in records:
                if not isinstance(record, dict) or set(record) != required_record_fields:
                    raise ValidationError(
                        "extraction record fields do not match the documented contract"
                    )
                extraction_id = _canonical_text(
                    record.get("extraction_id"), "extraction extraction_id"
                )
                if extraction_id in seen_records:
                    raise ValidationError("extraction records contain duplicate extraction_id")
                seen_records.add(extraction_id)
                _canonical_text(record.get("study_id"), "extraction study_id")
                _canonical_text(record.get("claim_text"), "extraction claim_text")
                _canonical_text(
                    record.get("evidence_location"), "extraction evidence_location"
                )
                epistemic_layer = _canonical_text(
                    record.get("epistemic_layer"), "extraction epistemic_layer"
                )
                if epistemic_layer not in _LAYERS:
                    raise ValidationError("invalid extraction epistemic_layer")
                result_direction = _canonical_text(
                    record.get("result_direction"), "extraction result_direction"
                )
                if result_direction not in _DIRECTIONS:
                    raise ValidationError("invalid extraction result_direction")
                _bounded_extraction_text(
                    record.get("uncertainty"), "extraction uncertainty"
                )
                _bounded_extraction_text(record.get("notes"), "extraction notes")
            replayed_record_count += len(records)
        if (
            extracted_record_count is not None
            and replayed_record_count != extracted_record_count
        ):
            raise ValidationError(
                "extraction source_reviews record count does not replay from extracted claims"
            )


def create_extraction(screening_path: Path, expected_sha256: str,
                      review: dict[str, Any], output: Path) -> dict[str, Any]:
    expected_sha256 = require_sha256(expected_sha256, "expected_screening_sha256")
    screening, digest = load_json_object(screening_path, "screening")
    if digest != expected_sha256:
        raise ValidationError("extraction screening does not match the expected SHA-256")
    if (not isinstance(screening, dict) or screening.get("screening_version") != 2
            or screening.get("status") != "screening_recorded"):
        raise ValidationError("extraction requires a completed version 2 screening record")
    validate_screening_boundary(screening)
    decisions = screening.get("decisions")
    if not isinstance(decisions, list):
        raise ValidationError("screening decisions must be an array")
    included: dict[str, str] = {}
    screening_source_ids: set[str] = set()
    for item in decisions:
        if not isinstance(item, dict):
            raise ValidationError("screening decisions must be objects")
        source_id = _canonical_text(item.get("source_id"), "screening source_id")
        if source_id in screening_source_ids:
            raise ValidationError("screening decisions contain duplicate source_id")
        screening_source_ids.add(source_id)
        if item.get("decision") == "include":
            if "source_retained_file_sha256" in item:
                source_hash = require_sha256(
                    item.get("source_retained_file_sha256"),
                    "screening source_retained_file_sha256",
                )
            else:
                source_hash = "legacy_missing"
            included[source_id] = source_hash
    if not included:
        raise ValidationError("extraction requires at least one included source")
    if not isinstance(review, dict) or set(review) != {"reviewer", "source_reviews"}:
        raise ValidationError("extraction review requires exactly reviewer and source_reviews")
    reviewer = _canonical_text(review["reviewer"], "extraction reviewer")
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
        source_id = _canonical_text(source_review["source_id"], "extraction source_id")
        if source_id in by_source:
            raise ValidationError("duplicate extraction source review")
        if source_id not in included:
            raise ValidationError("extraction may reference only included sources")
        status, records = source_review["status"], source_review["records"]
        if status not in {"extracted", "no_extractable_claim"} or not isinstance(records, list):
            raise ValidationError("source extraction status or records are invalid")
        reason = _bounded_extraction_text(
            source_review["reason"], "source extraction reason"
        )
        if (status == "extracted") != bool(records):
            raise ValidationError("extracted sources require records; no_extractable_claim sources require none")
        normalized_records = []
        for record in records:
            required = {"extraction_id", "study_id", "claim_text", "evidence_location",
                        "epistemic_layer", "result_direction", "uncertainty", "notes"}
            if not isinstance(record, dict) or set(record) != required:
                raise ValidationError("extraction record fields do not match the documented contract")
            normalized = {
                key: _canonical_text(record[key], f"extraction {key}")
                for key in required
            }
            normalized["uncertainty"] = _bounded_extraction_text(
                record["uncertainty"], "extraction uncertainty"
            )
            normalized["notes"] = _bounded_extraction_text(
                record["notes"], "extraction notes"
            )
            identifier = normalized["extraction_id"]
            if identifier in extraction_ids:
                raise ValidationError("duplicate extraction_id")
            extraction_ids.add(identifier)
            if normalized["epistemic_layer"] not in _LAYERS:
                raise ValidationError("invalid extraction epistemic_layer")
            if normalized["result_direction"] not in _DIRECTIONS:
                raise ValidationError("invalid extraction result_direction")
            normalized_records.append(normalized)
        by_source[source_id] = {
            "source_id": source_id,
            "source_retained_file_sha256": included[source_id],
            "status": status,
            "reason": reason,
            "records": sorted(normalized_records, key=lambda item: item["extraction_id"]),
        }
    if set(by_source) != set(included):
        raise ValidationError("source reviews must cover exactly all included sources")
    result = {
        "extraction_version": 1, "screening_sha256": digest,
        "snapshot_id": screening.get("snapshot_id"), "reviewer": reviewer,
        "source_reviews": [by_source[source_id] for source_id in sorted(by_source)],
        "record_count": len(extraction_ids), "status": "extraction_recorded",
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "reviewer_identity_authenticated": False,
        "limitations": [
            "Records are reviewer assertions bound to source IDs and locations; the machine has not verified that source text supports them.",
            "Shared study_id values group reports only by reviewer declaration and do not establish independent studies.",
            "Extraction does not perform risk-of-bias assessment, resolve disagreements, accept claims as facts, or conduct synthesis.",
        ],
    }
    validate_extraction_boundary(
        result,
        len(extraction_ids),
        require_source_review_contract=True,
    )
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
