"""Independent review of retained arm summaries and derived effects."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.effects import (
    retained_source_summary_sha256,
    validate_effect_records_boundary,
    validate_retained_source_summaries,
)
from research_machine.literature.hashes import require_sha256
from research_machine.literature.snapshot import _text

_LEGACY_SOURCE_ANCHOR = "legacy_missing"


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def _source_anchor(value: object, field: str) -> str:
    if value == _LEGACY_SOURCE_ANCHOR:
        return _LEGACY_SOURCE_ANCHOR
    return require_sha256(value, field)


def validate_effect_verification_boundary(effect_verification: dict[str, Any]) -> None:
    """Replay effect-verification non-authority, independence, and mismatch status."""
    if effect_verification.get("scientific_evidence_eligible") is not False:
        raise ValidationError("effect verification must remain scientifically ineligible")
    if effect_verification.get("conclusion_authorized") is not False:
        raise ValidationError("effect verification must not authorize conclusions")
    if effect_verification.get("publication_authorized") is not False:
        raise ValidationError("effect verification must not authorize publication claims")
    limitations = effect_verification.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("effect verification requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _canonical_text(limitation, f"effect-verification limitation {index + 1}")

    if effect_verification.get("independent_review") is not True:
        raise ValidationError("effect verification must retain independent_review true")
    effect_reviewer = _canonical_text(
        effect_verification.get("effect_reviewer"),
        "effect verification effect_reviewer",
    )
    verification_reviewer = _canonical_text(
        effect_verification.get("verification_reviewer"),
        "effect verification verification_reviewer",
    )
    if effect_reviewer.casefold() == verification_reviewer.casefold():
        raise ValidationError("effect verification reviewers must remain distinct")
    assessments = effect_verification.get("assessments")
    if not isinstance(assessments, list) or not assessments:
        raise ValidationError("effect verification requires retained assessments")
    seen = set()
    mismatches = []
    for assessment in assessments:
        if not isinstance(assessment, dict):
            raise ValidationError("effect-verification assessment is malformed")
        study_id = _canonical_text(
            assessment.get("study_id"), "effect-verification assessment study_id"
        )
        if study_id in seen:
            raise ValidationError("effect-verification assessments require unique study IDs")
        seen.add(study_id)
        effect_status = assessment.get("effect_status")
        if effect_status not in {"available", "unavailable"}:
            raise ValidationError("effect-verification assessment must retain effect status")
        source_values_match = assessment.get("source_values_match")
        calculation_matches = assessment.get("calculation_matches")
        if effect_status == "available":
            if not isinstance(source_values_match, bool) or not isinstance(calculation_matches, bool):
                raise ValidationError("available effects require boolean verification checks")
            if not source_values_match or not calculation_matches:
                mismatches.append(study_id)
        elif source_values_match is not None or calculation_matches is not None:
            raise ValidationError("unavailable effects require not-applicable verification checks")
    mismatch_study_ids = effect_verification.get("mismatch_study_ids")
    if mismatch_study_ids != sorted(mismatches):
        raise ValidationError("effect-verification mismatch_study_ids do not replay from assessments")
    expected_status = "review_required" if mismatches else "effect_verification_recorded"
    if effect_verification.get("status") != expected_status:
        raise ValidationError("effect-verification status does not replay from assessments")


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
    validate_effect_records_boundary(effects)
    effect_reviewer = _canonical_text(effects.get("reviewer"), "effect reviewer")
    records = effects.get("records")
    if not isinstance(records, list) or not records:
        raise ValidationError("effect verification requires effect records")
    statuses = {}
    claim_provenance: dict[str, list[dict[str, str]]] = {}
    for item in records:
        if not isinstance(item, dict):
            raise ValidationError("effect record is malformed")
        study_id = _canonical_text(item.get("study_id"), "effect record study_id")
        if study_id in statuses or item.get("status") not in {"available", "unavailable"}:
            raise ValidationError("effect record study IDs or statuses are invalid")
        statuses[study_id] = item["status"]
        mapped_claims = item.get("mapped_claims")
        if not isinstance(mapped_claims, list) or not mapped_claims:
            raise ValidationError("effect records must retain mapped claim source provenance")
        seen_claims = set()
        retained = []
        for claim in mapped_claims:
            if not isinstance(claim, dict):
                raise ValidationError("effect mapped claim source provenance is malformed")
            extraction_id = _canonical_text(
                claim.get("extraction_id"), "effect mapped claim extraction_id"
            )
            if extraction_id in seen_claims:
                raise ValidationError("effect mapped claim source provenance has duplicate extraction IDs")
            seen_claims.add(extraction_id)
            retained.append({
                "extraction_id": extraction_id,
                "extraction_claim_sha256": require_sha256(
                    claim.get("extraction_claim_sha256"),
                    "effect mapped claim extraction_claim_sha256",
                ),
                "source_id": _canonical_text(
                    claim.get("source_id"), "effect mapped claim source_id"
                ),
                "source_retained_file_sha256": _source_anchor(
                    claim.get("source_retained_file_sha256", _LEGACY_SOURCE_ANCHOR),
                    "effect mapped claim source_retained_file_sha256",
                ),
                "citation_checked_location": _canonical_text(
                    claim.get("citation_checked_location"),
                    "effect mapped claim citation_checked_location",
                ),
            })
        claim_provenance[study_id] = sorted(retained, key=lambda claim: claim["extraction_id"])
    retained_source_summaries = validate_retained_source_summaries(
        effects.get("source_summaries"),
        expected_statuses=statuses,
        effect_measure=_canonical_text(effects.get("effect_measure"), "effect_measure"),
    )
    source_summary_digests = {
        summary["study_id"]: retained_source_summary_sha256(summary)
        for summary in retained_source_summaries
    }
    if not isinstance(review, dict) or set(review) != {"reviewer", "assessments"}:
        raise ValidationError("effect verification requires exactly reviewer and assessments")
    reviewer = _canonical_text(review["reviewer"], "effect verification reviewer")
    if reviewer.casefold() == effect_reviewer.casefold():
        raise ValidationError("effect verification reviewer must differ from the effect reviewer")
    assessments = review["assessments"]
    if not isinstance(assessments, list):
        raise ValidationError("effect verification assessments must be an array")
    required = {"study_id", "source_values_match", "calculation_matches", "checked_location", "rationale"}
    by_study = {}
    for item in assessments:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError("effect verification assessment fields do not match the documented contract")
        study_id = _canonical_text(item["study_id"], "effect verification study_id")
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
            "retained_source_summary_sha256": source_summary_digests[study_id],
            "claim_source_provenance": claim_provenance[study_id],
            "checked_location": _canonical_text(item["checked_location"], "effect checked_location"),
            "rationale": _canonical_text(item["rationale"], "effect verification rationale")}
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
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "The machine records an independent check but does not read the cited source or authenticate reviewers.",
            "A matching calculation verifies arithmetic from retained summaries, not source truth, outcome compatibility, or participant-level analysis.",
            "Each assessment carries the exact retained source-summary digest that was independently checked, so later pooling can detect substitution of source-reported values.",
            "Retained claim source anchors bind verification to the prepared-effect artifact; they do not prove that the cited source supports the claim.",
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
