"""Write-once screening decisions; never promotes source content to evidence."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.hashes import require_sha256
from research_machine.literature.snapshot import _text


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def create_screening(snapshot_path: Path, expected_sha256: str, review: dict[str, Any], output: Path) -> dict[str, Any]:
    expected_sha256 = require_sha256(expected_sha256, "expected_snapshot_sha256")
    content = snapshot_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValidationError("screening snapshot does not match the expected SHA-256")
    try:
        snapshot = json.loads(content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("invalid literature snapshot JSON") from exc
    if not isinstance(snapshot, dict) or snapshot.get("snapshot_version") != 1:
        raise ValidationError("unsupported literature snapshot")
    sources = snapshot.get("sources")
    if not isinstance(sources, list) or not sources or any(not isinstance(item, dict) for item in sources):
        raise ValidationError("snapshot sources must be non-empty objects")
    source_ids = [
        _canonical_text(item.get("source_id"), "source_id") for item in sources
    ]
    if len(set(source_ids)) != len(source_ids):
        raise ValidationError("snapshot has duplicate source IDs")
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
        reason = _canonical_text(item["reason"], "screening reason")
        refs = item["criterion_refs"]
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            raise ValidationError("screening criterion_refs must reference criteria in the pinned snapshot")
        refs = [
            _canonical_text(ref, "screening criterion_refs item")
            for ref in refs
        ]
        if any(ref not in criteria for ref in refs):
            raise ValidationError("screening criterion_refs must reference criteria in the pinned snapshot")
        if len(refs) != len(set(refs)):
            raise ValidationError("duplicate screening criterion reference")
        if item["decision"] != "unresolved" and not refs:
            raise ValidationError("include/exclude decisions require at least one criterion reference")
        by_id[source_id] = {
            **item, "source_id": source_id, "reason": reason, "criterion_refs": refs
        }
    if set(by_id) != set(source_ids):
        raise ValidationError("screening decisions must cover exactly the snapshot source IDs")
    groups: dict[str, list[str]] = {}
    for source in sources:
        digest = _text(source.get("retained_file_sha256"), "retained_file_sha256")
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
        "limitations": "Inclusion is not claim acceptance. Reviewer identity and correctness of screening are not authenticated. Counts describe records, not independent studies.",
    }
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
