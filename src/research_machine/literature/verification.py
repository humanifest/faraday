"""Independent citation review without promoting literature claims to facts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.extraction import validate_extraction_boundary
from research_machine.literature.hashes import require_sha256
from research_machine.literature.snapshot import _text


_VERDICTS = {"supported", "partially_supported", "unsupported", "unclear"}
_EXTRACTION_RECORD_FIELDS = {
    "extraction_id",
    "study_id",
    "claim_text",
    "evidence_location",
    "epistemic_layer",
    "result_direction",
    "uncertainty",
    "notes",
}
_LEGACY_SOURCE_ANCHOR = "legacy_missing"


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def _source_anchor(value: Any, field: str) -> str:
    if value == _LEGACY_SOURCE_ANCHOR:
        return _LEGACY_SOURCE_ANCHOR
    return require_sha256(value, field)


def _extraction_claim_payload_sha256(
    source_id: str,
    record: dict[str, Any],
    source_retained_file_sha256: str = _LEGACY_SOURCE_ANCHOR,
) -> str:
    payload = {
        "source_id": source_id,
        "extraction_id": record["extraction_id"],
        "study_id": record["study_id"],
        "claim_text": record["claim_text"],
        "evidence_location": record["evidence_location"],
        "epistemic_layer": record["epistemic_layer"],
        "result_direction": record["result_direction"],
        "uncertainty": record["uncertainty"],
        "notes": record["notes"],
    }
    if source_retained_file_sha256 != _LEGACY_SOURCE_ANCHOR:
        payload["source_retained_file_sha256"] = source_retained_file_sha256
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_citation_verification_boundary(
    verification: dict[str, Any],
    assessments: list[dict[str, Any]],
    *,
    require_clean_verdicts: bool = False,
) -> None:
    """Replay citation-review authority, independence, status, and counts."""
    if verification.get("independent_review") is not True:
        raise ValidationError("citation verification must retain independent-review status")
    if verification.get("scientific_evidence_eligible") is not False:
        raise ValidationError("citation verification must remain scientifically ineligible")
    if verification.get("conclusion_authorized") is not False:
        raise ValidationError("citation verification must not authorize conclusions")
    if verification.get("publication_authorized") is not False:
        raise ValidationError("citation verification must not authorize publication claims")
    limitations = verification.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("citation verification requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _canonical_text(limitation, f"citation verification limitation {index + 1}")

    counts: dict[str, int] = {verdict: 0 for verdict in sorted(_VERDICTS)}
    for item in assessments:
        verdict = item.get("verdict") if isinstance(item, dict) else None
        if verdict not in _VERDICTS:
            raise ValidationError("citation assessment verdict is invalid")
        counts[verdict] += 1
    if verification.get("verdict_counts") != counts:
        raise ValidationError("citation verification verdict_counts do not replay from assessments")
    expected_status = (
        "review_required"
        if counts["unsupported"] or counts["unclear"]
        else "citation_review_recorded"
    )
    if verification.get("status") != expected_status:
        raise ValidationError("citation verification status does not replay from verdicts")
    if require_clean_verdicts and (counts["unsupported"] or counts["unclear"]):
        raise ValidationError("downstream review requires citation-reviewed claims without unsupported or unclear verdicts")


def create_citation_verification(
    extraction_path: Path,
    expected_sha256: str,
    review: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    """Record an independent, exhaustive review of extracted source claims."""
    expected_sha256 = require_sha256(expected_sha256, "expected_extraction_sha256")
    try:
        content = extraction_path.read_bytes()
        extraction = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("could not read valid extraction JSON") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValidationError("citation verification extraction does not match the expected SHA-256")
    if (not isinstance(extraction, dict) or extraction.get("extraction_version") != 1
            or extraction.get("status") != "extraction_recorded"):
        raise ValidationError("citation verification requires a completed version 1 extraction")

    extractor = _canonical_text(extraction.get("reviewer"), "extraction reviewer")
    records: dict[str, dict[str, str]] = {}
    source_reviews = extraction.get("source_reviews")
    if not isinstance(source_reviews, list):
        raise ValidationError("extraction source_reviews must be an array")
    for source_review in source_reviews:
        if not isinstance(source_review, dict):
            raise ValidationError("extraction source review must be an object")
        source_id = _canonical_text(source_review.get("source_id"), "extraction source_id")
        source_retained_file_sha256 = _source_anchor(
            source_review.get(
                "source_retained_file_sha256", _LEGACY_SOURCE_ANCHOR
            ),
            "extraction source_retained_file_sha256",
        )
        source_records = source_review.get("records")
        if not isinstance(source_records, list):
            raise ValidationError("extraction records must be an array")
        for record in source_records:
            if not isinstance(record, dict):
                raise ValidationError("extraction record must be an object")
            if set(record) != _EXTRACTION_RECORD_FIELDS:
                raise ValidationError("extraction record fields do not match the documented contract")
            extraction_id = _canonical_text(record.get("extraction_id"), "extraction_id")
            if extraction_id in records:
                raise ValidationError("extraction contains duplicate extraction_id")
            normalized_record = {
                field: _canonical_text(record.get(field), field)
                for field in _EXTRACTION_RECORD_FIELDS
            }
            records[extraction_id] = {
                "source_id": source_id,
                "source_retained_file_sha256": source_retained_file_sha256,
                "study_id": normalized_record["study_id"],
                "claim_text": normalized_record["claim_text"],
                "extracted_evidence_location": normalized_record["evidence_location"],
                "extraction_claim_sha256": _extraction_claim_payload_sha256(
                    source_id, normalized_record, source_retained_file_sha256
                ),
            }
    if not records:
        raise ValidationError("citation verification requires at least one extracted claim")
    validate_extraction_boundary(extraction, len(records))
    if not isinstance(review, dict) or set(review) != {"reviewer", "assessments"}:
        raise ValidationError("citation review requires exactly reviewer and assessments")
    reviewer = _canonical_text(review["reviewer"], "citation reviewer")
    if reviewer.casefold() == extractor.casefold():
        raise ValidationError("citation reviewer must be independent of the extraction reviewer")
    assessments = review["assessments"]
    if not isinstance(assessments, list):
        raise ValidationError("citation assessments must be an array")

    by_id: dict[str, dict[str, Any]] = {}
    required = {"extraction_id", "verdict", "checked_location", "rationale"}
    for assessment in assessments:
        if not isinstance(assessment, dict) or set(assessment) != required:
            raise ValidationError(
                "each citation assessment requires exactly extraction_id, verdict, checked_location, and rationale"
            )
        extraction_id = _canonical_text(assessment["extraction_id"], "citation extraction_id")
        if extraction_id not in records:
            raise ValidationError("citation assessment references an unknown extraction_id")
        if extraction_id in by_id:
            raise ValidationError("duplicate citation assessment")
        verdict = assessment["verdict"]
        if verdict not in _VERDICTS:
            raise ValidationError("invalid citation verification verdict")
        by_id[extraction_id] = {
            "extraction_id": extraction_id,
            **records[extraction_id],
            "verdict": verdict,
            "checked_location": _canonical_text(assessment["checked_location"], "checked_location"),
            "rationale": _canonical_text(assessment["rationale"], "citation rationale"),
        }
    if set(by_id) != set(records):
        raise ValidationError("citation assessments must cover exactly all extracted claims")

    counts = {verdict: sum(item["verdict"] == verdict for item in by_id.values())
              for verdict in sorted(_VERDICTS)}
    requires_review = bool(counts["unsupported"] or counts["unclear"])
    result = {
        "citation_verification_version": 1,
        "extraction_sha256": digest,
        "snapshot_id": extraction.get("snapshot_id"),
        "extraction_reviewer": extractor,
        "citation_reviewer": reviewer,
        "independent_review": True,
        "assessments": [by_id[item] for item in sorted(by_id)],
        "verdict_counts": counts,
        "status": "review_required" if requires_review else "citation_review_recorded",
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "The machine binds an independent review to extraction bytes but does not interpret source text or authenticate either reviewer.",
            "A supported verdict is a reviewer judgment, not proof that a claim is true, unbiased, reproducible, or applicable.",
            "Risk-of-bias assessment, study-identity reconciliation, and quantitative synthesis remain separate gates.",
        ],
    }
    validate_citation_verification_boundary(result, result["assessments"])
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("citation verification output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".citation-verification-", dir=root.parent) as temporary:
        staging = Path(temporary) / "citation-verification"
        staging.mkdir()
        (staging / "citation-verification.json").write_bytes(encoded)
        os.replace(staging, root)
    return {"path": str(root), "citation_verification_sha256": hashlib.sha256(encoded).hexdigest(), **result}
