"""Plan-bound effect-size records for later quantitative synthesis."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.snapshot import _text


def _load(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(f"could not read valid {label} JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value, hashlib.sha256(content).hexdigest()


def create_effect_records(
    plan_path: Path,
    expected_plan_sha256: str,
    extraction_path: Path,
    evidence_map_path: Path,
    expected_evidence_map_sha256: str,
    review: dict[str, Any],
    output: Path,
    *,
    derivation_scope: str = "reviewer_reported_effect_and_standard_error",
    contrast_definition: str | None = None,
    source_summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    plan, plan_sha = _load(plan_path, "synthesis plan")
    extraction, extraction_sha = _load(extraction_path, "extraction")
    evidence_map, map_sha = _load(evidence_map_path, "evidence map")
    if plan_sha != expected_plan_sha256 or map_sha != expected_evidence_map_sha256:
        raise ValidationError("effect-record input does not match an expected SHA-256")
    if (plan.get("synthesis_plan_version") != 1 or plan.get("status") != "synthesis_plan_frozen"
            or plan.get("synthesis_type") != "quantitative"):
        raise ValidationError("effect records require a frozen quantitative synthesis plan")
    if (extraction.get("extraction_version") != 1 or extraction.get("status") != "extraction_recorded"
            or extraction.get("screening_sha256") != plan.get("screening_sha256")):
        raise ValidationError("effect records require an extraction from the plan's pinned screening")
    inputs = evidence_map.get("inputs")
    if (evidence_map.get("evidence_map_version") != 1 or evidence_map.get("status") != "evidence_map_recorded"
            or not isinstance(inputs, dict) or inputs.get("extraction_sha256") != extraction_sha):
        raise ValidationError("effect records require an evidence map bound to the supplied extraction")
    if not (plan.get("snapshot_id") == extraction.get("snapshot_id") == evidence_map.get("snapshot_id")):
        raise ValidationError("effect-record artifacts do not share a snapshot_id")
    claims = evidence_map.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValidationError("effect records require mapped claims")
    studies = {item.get("study_id") for item in claims if isinstance(item, dict)}
    if None in studies or any(not isinstance(item, str) or not item.strip() for item in studies):
        raise ValidationError("evidence map contains invalid study IDs")
    study_biases: dict[str, str] = {}
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("risk_of_bias") not in {"low", "some_concerns", "high", "unclear"}:
            raise ValidationError("mapped claims require a valid study risk_of_bias")
        prior = study_biases.setdefault(claim["study_id"], claim["risk_of_bias"])
        if prior != claim["risk_of_bias"]:
            raise ValidationError("mapped claims disagree on study risk_of_bias")

    if not isinstance(review, dict) or set(review) != {"reviewer", "records"}:
        raise ValidationError("effect review requires exactly reviewer and records")
    reviewer = _text(review["reviewer"], "effect reviewer")
    records = review["records"]
    if not isinstance(records, list):
        raise ValidationError("effect records must be an array")
    required = {"study_id", "status", "reason", "effect_measure", "estimate",
                "standard_error", "sample_size", "evidence_location", "derivation"}
    by_study: dict[str, dict[str, Any]] = {}
    expected_measure = plan.get("effect_measure")
    for item in records:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError("effect record fields do not match the documented contract")
        study_id = _text(item["study_id"], "effect study_id")
        if study_id not in studies or study_id in by_study:
            raise ValidationError("effect study_id is unknown or duplicated")
        status = item["status"]
        if status not in {"available", "unavailable"}:
            raise ValidationError("effect status must be available or unavailable")
        if item["effect_measure"] != expected_measure:
            raise ValidationError("effect measure must exactly match the frozen synthesis plan")
        reason = _text(item["reason"], "effect reason").strip()
        location = _text(item["evidence_location"], "effect evidence_location").strip()
        derivation = _text(item["derivation"], "effect derivation").strip()
        estimate, standard_error, sample_size = item["estimate"], item["standard_error"], item["sample_size"]
        if status == "available":
            if (isinstance(estimate, bool) or not isinstance(estimate, (int, float))
                    or not math.isfinite(estimate)):
                raise ValidationError("available effect estimate must be finite numeric data")
            if (isinstance(standard_error, bool) or not isinstance(standard_error, (int, float))
                    or not math.isfinite(standard_error) or standard_error <= 0):
                raise ValidationError("available effect standard_error must be finite and positive")
            if isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size <= 0:
                raise ValidationError("available effect sample_size must be a positive integer")
        elif any(value is not None for value in (estimate, standard_error, sample_size)):
            raise ValidationError("unavailable effects require null estimate, standard_error, and sample_size")
        by_study[study_id] = {"study_id": study_id, "status": status, "reason": reason,
            "risk_of_bias": study_biases[study_id],
            "effect_measure": expected_measure, "estimate": estimate, "standard_error": standard_error,
            "variance": standard_error ** 2 if status == "available" else None,
            "sample_size": sample_size, "evidence_location": location, "derivation": derivation}
    if set(by_study) != studies:
        raise ValidationError("effect records must cover exactly all mapped studies")
    available = sum(item["status"] == "available" for item in by_study.values())
    minimum = plan.get("minimum_independent_studies")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValidationError("frozen minimum_independent_studies is invalid")
    result = {"effect_records_version": 1, "inputs": {"synthesis_plan_sha256": plan_sha,
        "extraction_sha256": extraction_sha, "evidence_map_sha256": map_sha},
        "plan_id": plan.get("plan_id"), "snapshot_id": plan.get("snapshot_id"),
        "reviewer": reviewer, "effect_measure": expected_measure,
        "derivation_scope": _text(derivation_scope, "effect derivation_scope").strip(),
        "contrast_definition": contrast_definition,
        "source_summaries": source_summaries,
        "records": [by_study[item] for item in sorted(by_study)], "study_count": len(studies),
        "available_effect_count": available, "unavailable_effect_count": len(studies) - available,
        "minimum_independent_studies": minimum,
        "status": "effects_ready" if available >= minimum else "insufficient_effects",
        "scientific_evidence_eligible": False,
        "limitations": [
            "Effect values and derivations are reviewer assertions; the machine validates shape and variance but does not reproduce calculations from source data.",
            "Unavailable statistics remain explicit and are not imputed or silently excluded.",
            "One planned effect per study avoids within-study double counting but does not establish outcome compatibility or authorize pooling.",
        ]}
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("effect-record output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".effect-records-", dir=root.parent) as temporary:
        staging = Path(temporary) / "effect-records"; staging.mkdir()
        (staging / "effect-records.json").write_bytes(encoded); os.replace(staging, root)
    return {"path": str(root), "effect_records_sha256": hashlib.sha256(encoded).hexdigest(), **result}
