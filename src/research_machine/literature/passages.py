"""Machine-check exact literature passage quotes without promoting claims."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.extraction import (
    _LEGACY_SOURCE_ANCHOR,
    validate_extraction_boundary,
)
from research_machine.literature.hashes import require_sha256
from research_machine.literature.json_loading import load_json_object
from research_machine.literature.snapshot import _text


_MACHINE_VERIFICATION = "exact_utf8_quote_found_in_retained_source_bytes"
_PASSAGE_PROSE_OVERCLAIM = re.compile(
    r"\b(?:proved|confirmed|explained|validates?|validated)\b",
    re.IGNORECASE,
)
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


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def _bounded_passage_text(value: Any, field: str) -> str:
    text = _canonical_text(value, field)
    if _PASSAGE_PROSE_OVERCLAIM.search(text):
        raise ValidationError(
            f"{field} uses passage-verification prohibited overclaiming language; "
            "describe byte-level passage checking without claiming proof, "
            "confirmation, validation, or explanation"
        )
    return text


def _hash_file(path: Path) -> tuple[str, int, bytes]:
    digest = hashlib.sha256()
    size = 0
    content = bytearray()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
            content.extend(chunk)
    return digest.hexdigest(), size, bytes(content)


def _extraction_claim_payload_sha256(
    source_id: str,
    record: dict[str, str],
    source_retained_file_sha256: str,
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
        "source_retained_file_sha256": source_retained_file_sha256,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_passage_verification_boundary(
    verification: dict[str, Any],
    claims: list[dict[str, Any]] | None = None,
) -> None:
    """Replay passage-verification authority, counts, and retained boundaries."""
    if (
        not isinstance(verification, dict)
        or verification.get("passage_verification_version") != 1
    ):
        raise ValidationError("passage verification version is invalid")
    require_sha256(
        verification.get("extraction_sha256"),
        "passage verification extraction_sha256",
    )
    _canonical_text(verification.get("snapshot_id"), "passage verification snapshot_id")
    _canonical_text(
        verification.get("extraction_reviewer"),
        "passage verification extraction_reviewer",
    )
    _canonical_text(
        verification.get("passage_reviewer"),
        "passage verification passage_reviewer",
    )
    if verification.get("scientific_evidence_eligible") is not False:
        raise ValidationError("passage verification must remain scientifically ineligible")
    if verification.get("conclusion_authorized") is not False:
        raise ValidationError("passage verification must not authorize conclusions")
    if verification.get("publication_authorized") is not False:
        raise ValidationError("passage verification must not authorize publication claims")
    if verification.get("reviewer_identity_authenticated", False) is not False:
        raise ValidationError("passage verification must not authenticate reviewer identity")
    if verification.get("status") != "passage_verification_recorded":
        raise ValidationError("passage verification status is invalid")
    limitations = verification.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("passage verification requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _bounded_passage_text(
            limitation,
            f"passage verification limitation {index + 1}",
        )

    retained_claims = verification.get("claims")
    if claims is None:
        claims = retained_claims
    if (
        not isinstance(claims, list)
        or not claims
        or retained_claims != claims
        or verification.get("claim_count") != len(claims)
    ):
        raise ValidationError("passage verification claims do not replay")
    seen: set[str] = set()
    required = {
        "extraction_id",
        "source_id",
        "source_retained_file_sha256",
        "study_id",
        "claim_text",
        "extracted_evidence_location",
        "extraction_claim_sha256",
        "evidence_quote",
        "evidence_quote_sha256",
        "quote_utf8_byte_count",
        "quote_occurrence_count",
        "machine_verification",
    }
    for item in claims:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError("passage verification claim fields are invalid")
        extraction_id = _canonical_text(
            item.get("extraction_id"),
            "passage verification extraction_id",
        )
        if extraction_id in seen:
            raise ValidationError("passage verification contains duplicate extraction_id")
        seen.add(extraction_id)
        _canonical_text(item.get("source_id"), "passage verification source_id")
        require_sha256(
            item.get("source_retained_file_sha256"),
            "passage verification source_retained_file_sha256",
        )
        _canonical_text(item.get("study_id"), "passage verification study_id")
        _canonical_text(item.get("claim_text"), "passage verification claim_text")
        _canonical_text(
            item.get("extracted_evidence_location"),
            "passage verification extracted_evidence_location",
        )
        require_sha256(
            item.get("extraction_claim_sha256"),
            "passage verification extraction_claim_sha256",
        )
        quote = _canonical_text(
            item.get("evidence_quote"),
            "passage verification evidence_quote",
        )
        quote_bytes = quote.encode("utf-8")
        expected_quote_hash = hashlib.sha256(quote_bytes).hexdigest()
        if item.get("evidence_quote_sha256") != expected_quote_hash:
            raise ValidationError("passage verification evidence_quote_sha256 does not replay")
        if item.get("quote_utf8_byte_count") != len(quote_bytes):
            raise ValidationError("passage verification quote byte count does not replay")
        occurrence_count = item.get("quote_occurrence_count")
        if (
            isinstance(occurrence_count, bool)
            or not isinstance(occurrence_count, int)
            or occurrence_count < 1
        ):
            raise ValidationError("passage verification quote_occurrence_count is invalid")
        if item.get("machine_verification") != _MACHINE_VERIFICATION:
            raise ValidationError("passage verification machine_verification is invalid")


def create_passage_verification(
    extraction_path: Path,
    expected_sha256: str,
    source_root: Path,
    review: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    """Verify reviewer-supplied exact quotes against retained source bytes."""
    expected_sha256 = require_sha256(expected_sha256, "expected_extraction_sha256")
    extraction, digest = load_json_object(extraction_path, "extraction")
    if digest != expected_sha256:
        raise ValidationError("passage verification extraction does not match the expected SHA-256")
    if (
        not isinstance(extraction, dict)
        or extraction.get("extraction_version") != 1
        or extraction.get("status") != "extraction_recorded"
    ):
        raise ValidationError("passage verification requires a completed version 1 extraction")

    claims: dict[str, dict[str, str]] = {}
    source_reviews = extraction.get("source_reviews")
    if not isinstance(source_reviews, list):
        raise ValidationError("extraction source_reviews must be an array")
    for source_review in source_reviews:
        if not isinstance(source_review, dict):
            raise ValidationError("extraction source review must be an object")
        source_id = _canonical_text(
            source_review.get("source_id"),
            "extraction source_id",
        )
        source_sha = source_review.get(
            "source_retained_file_sha256",
            _LEGACY_SOURCE_ANCHOR,
        )
        if source_sha == _LEGACY_SOURCE_ANCHOR:
            raise ValidationError(
                "passage verification requires hash-anchored retained source bytes"
            )
        source_sha = require_sha256(
            source_sha,
            "extraction source_retained_file_sha256",
        )
        records = source_review.get("records")
        if not isinstance(records, list):
            raise ValidationError("extraction records must be an array")
        for record in records:
            if not isinstance(record, dict) or set(record) != _EXTRACTION_RECORD_FIELDS:
                raise ValidationError(
                    "extraction record fields do not match the documented contract"
                )
            normalized = {
                field: _canonical_text(record.get(field), f"extraction {field}")
                for field in _EXTRACTION_RECORD_FIELDS
            }
            extraction_id = normalized["extraction_id"]
            if extraction_id in claims:
                raise ValidationError("extraction contains duplicate extraction_id")
            claims[extraction_id] = {
                "source_id": source_id,
                "source_retained_file_sha256": source_sha,
                "study_id": normalized["study_id"],
                "claim_text": normalized["claim_text"],
                "extracted_evidence_location": normalized["evidence_location"],
                "extraction_claim_sha256": _extraction_claim_payload_sha256(
                    source_id,
                    normalized,
                    source_sha,
                ),
            }
    if not claims:
        raise ValidationError("passage verification requires at least one extracted claim")
    validate_extraction_boundary(
        extraction,
        len(claims),
        require_source_review_contract=True,
    )

    root = source_root.expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValidationError("retained source root must be a real directory")
    if not isinstance(review, dict) or set(review) != {"reviewer", "passages"}:
        raise ValidationError("passage review requires exactly reviewer and passages")
    reviewer = _canonical_text(review["reviewer"], "passage reviewer")
    passages = review["passages"]
    if not isinstance(passages, list):
        raise ValidationError("passage review passages must be an array")

    retained_sources: dict[str, bytes] = {}
    by_id: dict[str, dict[str, Any]] = {}
    required = {"extraction_id", "evidence_quote"}
    for passage in passages:
        if not isinstance(passage, dict) or set(passage) != required:
            raise ValidationError(
                "each passage review requires exactly extraction_id and evidence_quote"
            )
        extraction_id = _canonical_text(
            passage.get("extraction_id"),
            "passage verification extraction_id",
        )
        if extraction_id not in claims:
            raise ValidationError("passage review references an unknown extraction_id")
        if extraction_id in by_id:
            raise ValidationError("duplicate passage verification")
        quote = _canonical_text(
            passage.get("evidence_quote"),
            "passage verification evidence_quote",
        )
        claim = claims[extraction_id]
        source_sha = claim["source_retained_file_sha256"]
        if source_sha not in retained_sources:
            source_path = root / source_sha
            if not source_path.is_file() or source_path.is_symlink():
                raise ValidationError(
                    f"retained source bytes are missing for {source_sha}"
                )
            actual_sha, _, source_bytes = _hash_file(source_path)
            if actual_sha != source_sha:
                raise ValidationError(
                    f"retained source bytes do not match {source_sha}"
                )
            retained_sources[source_sha] = source_bytes
        quote_bytes = quote.encode("utf-8")
        occurrence_count = retained_sources[source_sha].count(quote_bytes)
        if occurrence_count < 1:
            raise ValidationError(
                "passage evidence_quote does not occur in the retained source bytes"
            )
        by_id[extraction_id] = {
            "extraction_id": extraction_id,
            **claim,
            "evidence_quote": quote,
            "evidence_quote_sha256": hashlib.sha256(quote_bytes).hexdigest(),
            "quote_utf8_byte_count": len(quote_bytes),
            "quote_occurrence_count": occurrence_count,
            "machine_verification": _MACHINE_VERIFICATION,
        }
    if set(by_id) != set(claims):
        raise ValidationError("passage reviews must cover exactly all extracted claims")

    result = {
        "passage_verification_version": 1,
        "extraction_sha256": digest,
        "snapshot_id": extraction.get("snapshot_id"),
        "extraction_reviewer": _canonical_text(
            extraction.get("reviewer"),
            "extraction reviewer",
        ),
        "passage_reviewer": reviewer,
        "claims": [by_id[extraction_id] for extraction_id in sorted(by_id)],
        "claim_count": len(by_id),
        "status": "passage_verification_recorded",
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "reviewer_identity_authenticated": False,
        "limitations": [
            "Exact quote matching proves only that supplied UTF-8 quote bytes occur in the retained source bytes; it does not interpret the passage or prove the extracted claim.",
            "Reviewer identity, source semantics, risk of bias, and applicability remain unauthenticated and require later review gates.",
            "Passage verification is not scientific evidence, conclusion authorization, or publication authorization.",
        ],
    }
    validate_passage_verification_boundary(result, result["claims"])

    out = output.expanduser().resolve()
    if out.exists():
        raise ValidationError("passage verification output already exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode()
    with tempfile.TemporaryDirectory(prefix=".passage-verification-", dir=out.parent) as temporary:
        staging = Path(temporary) / "passage-verification"
        staging.mkdir()
        (staging / "passage-verification.json").write_bytes(encoded)
        os.replace(staging, out)
    return {
        "path": str(out),
        "passage_verification_sha256": hashlib.sha256(encoded).hexdigest(),
        **result,
    }
