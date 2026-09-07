"""Independent review of retained arm summaries and derived effects."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.hashes import require_sha256
from research_machine.literature.snapshot import _text


def create_effect_verification(effects_path: Path, expected_sha256: str,
                               review: dict[str, Any], output: Path) -> dict[str, Any]:
    expected_sha256 = require_sha256(expected_sha256, "expected_effects_sha256")
    try:
        content = effects_path.read_bytes(); effects = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("could not read valid effect-record JSON") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValidationError("effect verification does not match the expected SHA-256")
    if (not isinstance(effects, dict) or effects.get("effect_records_version") != 1
            or effects.get("derivation_scope") != "recomputed_from_source_reported_arm_summaries"):
        raise ValidationError("effect verification requires reproducibly derived effect records")
    effect_reviewer = _text(effects.get("reviewer"), "effect reviewer")
    records = effects.get("records")
    if not isinstance(records, list) or not records:
        raise ValidationError("effect verification requires effect records")
    statuses = {}
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get("study_id"), str) or not item["study_id"].strip():
            raise ValidationError("effect record is malformed")
        study_id = item["study_id"].strip()
        if study_id in statuses or item.get("status") not in {"available", "unavailable"}:
            raise ValidationError("effect record study IDs or statuses are invalid")
        statuses[study_id] = item["status"]
    summaries = effects.get("source_summaries")
    if not isinstance(summaries, list) or len(summaries) != len(records):
        raise ValidationError("effect artifact does not retain complete source summaries")
    summary_statuses = {}
    for item in summaries:
        if (not isinstance(item, dict) or not isinstance(item.get("study_id"), str)
                or not item["study_id"].strip()
                or item.get("status") not in {"available", "unavailable"}):
            raise ValidationError("retained source summaries contain invalid or duplicate study IDs")
        study_id = item["study_id"].strip()
        if study_id in summary_statuses:
            raise ValidationError("retained source summaries contain invalid or duplicate study IDs")
        summary_statuses[study_id] = item["status"]
    if summary_statuses != statuses:
        raise ValidationError("retained source summaries must exactly match effect studies and statuses")
    if not isinstance(review, dict) or set(review) != {"reviewer", "assessments"}:
        raise ValidationError("effect verification requires exactly reviewer and assessments")
    reviewer = _text(review["reviewer"], "effect verification reviewer")
    if reviewer.strip().casefold() == effect_reviewer.strip().casefold():
        raise ValidationError("effect verification reviewer must differ from the effect reviewer")
    assessments = review["assessments"]
    if not isinstance(assessments, list):
        raise ValidationError("effect verification assessments must be an array")
    required = {"study_id", "source_values_match", "calculation_matches", "checked_location", "rationale"}
    by_study = {}
    for item in assessments:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError("effect verification assessment fields do not match the documented contract")
        study_id = _text(item["study_id"], "effect verification study_id").strip()
        if study_id not in statuses or study_id in by_study:
            raise ValidationError("effect verification study_id is unknown or duplicated")
        values_match, calculation_matches = item["source_values_match"], item["calculation_matches"]
        if statuses[study_id] == "available":
            if not isinstance(values_match, bool) or not isinstance(calculation_matches, bool):
                raise ValidationError("available effects require boolean transcription and calculation checks")
        elif values_match is not None or calculation_matches is not None:
            raise ValidationError("unavailable effects require null transcription and calculation checks")
        by_study[study_id] = {"study_id": study_id, "effect_status": statuses[study_id],
            "source_values_match": values_match, "calculation_matches": calculation_matches,
            "checked_location": _text(item["checked_location"], "effect checked_location").strip(),
            "rationale": _text(item["rationale"], "effect verification rationale").strip()}
    if set(by_study) != set(statuses):
        raise ValidationError("effect verification must cover exactly all effect records")
    mismatches = [item["study_id"] for item in by_study.values()
                  if item["effect_status"] == "available"
                  and (not item["source_values_match"] or not item["calculation_matches"])]
    result = {"effect_verification_version": 1, "effect_records_sha256": digest,
        "plan_id": effects.get("plan_id"), "snapshot_id": effects.get("snapshot_id"),
        "effect_reviewer": effect_reviewer, "verification_reviewer": reviewer,
        "independent_review": True, "assessments": [by_study[item] for item in sorted(by_study)],
        "mismatch_study_ids": sorted(mismatches),
        "status": "review_required" if mismatches else "effect_verification_recorded",
        "scientific_evidence_eligible": False,
        "limitations": [
            "The machine records an independent check but does not read the cited source or authenticate reviewers.",
            "A matching calculation verifies arithmetic from retained summaries, not source truth, outcome compatibility, or participant-level analysis.",
            "Mismatches remain visible and prevent quantitative pooling through the verified workflow.",
        ]}
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("effect-verification output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".effect-verification-", dir=root.parent) as temporary:
        staging = Path(temporary) / "effect-verification"; staging.mkdir()
        (staging / "effect-verification.json").write_bytes(encoded); os.replace(staging, root)
    return {"path": str(root), "effect_verification_sha256": hashlib.sha256(encoded).hexdigest(), **result}
