"""Write-once screening decisions; never promotes source content to evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.hashes import require_sha256
from research_machine.literature.snapshot import _text, validate_snapshot_boundary


_SCREENING_PROSE_OVERCLAIM = re.compile(
    r"\b(?:proved|confirmed|explained|validates?|validated)\b",
    re.IGNORECASE,
)


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def _bounded_screening_text(value: Any, field: str) -> str:
    text = _canonical_text(value, field)
    if _SCREENING_PROSE_OVERCLAIM.search(text):
        raise ValidationError(
            f"{field} uses screening-prohibited overclaiming language; "
            "describe the eligibility decision without claiming proof, "
            "confirmation, validation, or explanation"
        )
    return text


def validate_screening_boundary(screening: dict[str, Any]) -> None:
    """Replay screening non-authority, decision, and count boundaries."""
    if not isinstance(screening, dict) or screening.get("screening_version") != 2:
        raise ValidationError("unsupported screening record")
    require_sha256(screening.get("snapshot_sha256"), "screening snapshot_sha256")
    _canonical_text(screening.get("snapshot_id"), "screening snapshot_id")
    _canonical_text(screening.get("reviewer"), "screening reviewer")
    if screening.get("scientific_evidence_eligible") is not False:
        raise ValidationError("screening must remain scientifically ineligible")
    if screening.get("conclusion_authorized") is not False:
        raise ValidationError("screening must not authorize conclusions")
    if screening.get("publication_authorized") is not False:
        raise ValidationError("screening must not authorize publication claims")
    if screening.get("reviewer_identity_authenticated", False) is not False:
        raise ValidationError("screening must not authenticate reviewer identity")
    limitations = screening.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("screening requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _bounded_screening_text(
            limitation,
            f"screening limitation {index + 1}",
        )

    criteria = screening.get("criteria")
    if not isinstance(criteria, dict) or not criteria:
        raise ValidationError("screening criteria must be retained")
    for key, value in criteria.items():
        _canonical_text(key, "screening criterion key")
        _canonical_text(value, "screening criterion")

    decisions = screening.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ValidationError("screening decisions must be a non-empty array")
    seen: set[str] = set()
    counts = {"include": 0, "exclude": 0, "unresolved": 0}
    by_hash: dict[str, list[str]] = {}
    for item in decisions:
        if not isinstance(item, dict):
            raise ValidationError("screening decisions must be objects")
        source_id = _canonical_text(item.get("source_id"), "screening source_id")
        if source_id in seen:
            raise ValidationError("screening decisions contain duplicate source_id")
        seen.add(source_id)
        decision = item.get("decision")
        if decision not in counts:
            raise ValidationError("screening decision must be include, exclude, or unresolved")
        counts[decision] += 1
        _bounded_screening_text(item.get("reason"), "screening reason")
        source_hash = require_sha256(
            item.get("source_retained_file_sha256"),
            "screening source_retained_file_sha256",
        )
        refs = item.get("criterion_refs")
        if (not isinstance(refs, list)
                or any(not isinstance(ref, str) or not ref.strip() for ref in refs)):
            raise ValidationError("screening criterion_refs must reference retained criteria")
        normalized_refs = [
            _canonical_text(ref, "screening criterion_refs item")
            for ref in refs
        ]
        if len(normalized_refs) != len(set(normalized_refs)):
            raise ValidationError("duplicate screening criterion reference")
        if decision != "unresolved" and not normalized_refs:
            raise ValidationError("include/exclude decisions require at least one criterion reference")
        if any(ref not in criteria for ref in normalized_refs):
            raise ValidationError("screening criterion_refs must reference retained criteria")
        by_hash.setdefault(source_hash, []).append(source_id)

    if screening.get("source_record_counts") != counts:
        raise ValidationError("screening source_record_counts do not replay from decisions")
    conflicts = [
        sorted(ids) for _, ids in sorted(by_hash.items())
        if len({item["decision"] for item in decisions if item["source_id"] in ids}) > 1
    ]
    if screening.get("duplicate_decision_conflicts") != conflicts:
        raise ValidationError("screening duplicate decision conflicts do not replay from decisions")
    expected_status = "review_required" if conflicts or counts["unresolved"] else "screening_recorded"
    if screening.get("status") != expected_status:
        raise ValidationError("screening status does not replay from decisions")


def create_screening(snapshot_path: Path, expected_sha256: str, review: dict[str, Any], output: Path) -> dict[str, Any]:
    expected_sha256 = require_sha256(expected_sha256, "expected_snapshot_sha256")
    content = snapshot_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValidationError("screening snapshot does not match the expected SHA-256")
    try:
        snapshot = json.loads(content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("invalid literature snapshot JSON") from exc
    validate_snapshot_boundary(snapshot)
    sources = snapshot.get("sources")
    if not isinstance(sources, list) or not sources or any(not isinstance(item, dict) for item in sources):
        raise ValidationError("snapshot sources must be non-empty objects")
    source_ids = [
        _canonical_text(item.get("source_id"), "source_id") for item in sources
    ]
    if len(set(source_ids)) != len(source_ids):
        raise ValidationError("snapshot has duplicate source IDs")
    source_hashes: dict[str, str] = {}
    for source in sources:
        source_id = _canonical_text(source.get("source_id"), "source_id")
        source_hashes[source_id] = require_sha256(
            source.get("retained_file_sha256"), "retained_file_sha256"
        )
    if not isinstance(review, dict) or set(review) != {"reviewer", "decisions"}:
        raise ValidationError("screening review requires exactly reviewer and decisions")
    reviewer = _canonical_text(review["reviewer"], "reviewer")
    criteria = {}
    for kind in ("inclusion", "exclusion"):
        values = snapshot.get(f"{kind}_criteria", [])
        if not isinstance(values, list):
            raise ValidationError("snapshot criteria must be arrays")
        for index, value in enumerate(values, start=1):
            criteria[f"{kind}:{index}"] = _text(value, "screening criterion")
    decisions = review["decisions"]
    if not isinstance(decisions, list):
        raise ValidationError("screening decisions must be an array")
    by_id = {}
    for item in decisions:
        if not isinstance(item, dict) or set(item) != {"source_id", "decision", "reason", "criterion_refs"}:
            raise ValidationError("each screening decision requires exactly source_id, decision, reason, and criterion_refs")
        source_id = _canonical_text(item["source_id"], "screening source_id")
        if source_id in by_id:
            raise ValidationError("duplicate screening decision")
        if item["decision"] not in ("include", "exclude", "unresolved"):
            raise ValidationError("screening decision must be include, exclude, or unresolved")
        reason = _bounded_screening_text(item["reason"], "screening reason")
        refs = item["criterion_refs"]
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            raise ValidationError("screening criterion_refs must reference criteria in the pinned snapshot")
        refs = [
            _canonical_text(ref, "screening criterion_refs item")
            for ref in refs
        ]
        if source_id not in source_hashes:
            raise ValidationError("screening decisions must cover exactly the snapshot source IDs")
        if any(ref not in criteria for ref in refs):
            raise ValidationError("screening criterion_refs must reference criteria in the pinned snapshot")
        if len(refs) != len(set(refs)):
            raise ValidationError("duplicate screening criterion reference")
        if item["decision"] != "unresolved" and not refs:
            raise ValidationError("include/exclude decisions require at least one criterion reference")
        by_id[source_id] = {
            **item,
            "source_id": source_id,
            "source_retained_file_sha256": source_hashes[source_id],
            "reason": reason,
            "criterion_refs": refs,
        }
    if set(by_id) != set(source_ids):
        raise ValidationError("screening decisions must cover exactly the snapshot source IDs")
    groups: dict[str, list[str]] = {}
    for source in sources:
        digest = require_sha256(
            source.get("retained_file_sha256"), "retained_file_sha256"
        )
        groups.setdefault(digest, []).append(
            _canonical_text(source["source_id"], "source_id")
        )
    conflicts = [sorted(ids) for _, ids in sorted(groups.items())
                 if len({by_id[source_id]["decision"] for source_id in ids}) > 1]
    counts = {decision: sum(item["decision"] == decision for item in decisions)
              for decision in ("include", "exclude", "unresolved")}
    result = {
        "screening_version": 2, "snapshot_sha256": expected_sha256,
        "criteria": criteria,
        "snapshot_id": snapshot.get("snapshot_id"), "reviewer": reviewer,
        "decisions": [by_id[source_id] for source_id in sorted(by_id)],
        "source_record_counts": counts, "duplicate_decision_conflicts": conflicts,
        "status": "review_required" if conflicts or counts["unresolved"] else "screening_recorded",
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "reviewer_identity_authenticated": False,
        "limitations": [
            "Inclusion is not claim acceptance, evidence admission, or support for any extracted claim.",
            "Reviewer identity and correctness of screening are not authenticated.",
            "Counts describe source records, not independent studies, replications, or effect estimates.",
        ],
    }
    validate_screening_boundary(result)
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("screening output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".screening-", dir=root.parent) as temporary:
        staging = Path(temporary) / "screening"
        staging.mkdir()
        (staging / "screening.json").write_bytes(encoded)
        os.replace(staging, root)
    return {"path": str(root), "screening_sha256": hashlib.sha256(encoded).hexdigest(), **result}
