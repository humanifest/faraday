"""Immutable disclosure of departures from a frozen synthesis plan."""
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


_STAGES = {"extraction", "citation_verification", "bias_assessment", "study_reconciliation",
           "effect_preparation", "synthesis", "reporting"}
_TIMINGS = {"before_extraction", "before_synthesis", "after_results_seen", "unknown"}


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def create_synthesis_deviations(
    plan_path: Path,
    expected_sha256: str,
    disclosure: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    expected_sha256 = require_sha256(expected_sha256, "expected_plan_sha256")
    try:
        content = plan_path.read_bytes(); plan = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("could not read valid synthesis-plan JSON") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValidationError("synthesis deviations plan does not match the expected SHA-256")
    if (not isinstance(plan, dict) or plan.get("synthesis_plan_version") != 1
            or plan.get("status") != "synthesis_plan_frozen"):
        raise ValidationError("synthesis deviations require a frozen version 1 plan")
    synthesis_type = plan.get("synthesis_type")
    if synthesis_type not in {"qualitative", "quantitative"}:
        raise ValidationError("synthesis deviations require a plan with a supported synthesis_type")
    if not isinstance(disclosure, dict) or set(disclosure) != {"reviewer", "deviations"}:
        raise ValidationError("deviation disclosure requires exactly reviewer and deviations")
    reviewer = _canonical_text(disclosure["reviewer"], "deviation reviewer")
    deviations = disclosure["deviations"]
    if not isinstance(deviations, list):
        raise ValidationError("deviations must be an array")
    required = {"deviation_id", "stage", "frozen_commitment", "actual_method", "reason",
                "timing", "impact_assessment", "corrective_action", "evidence_location"}
    by_id: dict[str, dict[str, str]] = {}
    for item in deviations:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError("synthesis deviation fields do not match the documented contract")
        deviation_id = _canonical_text(item["deviation_id"], "deviation_id")
        if deviation_id in by_id:
            raise ValidationError("duplicate synthesis deviation_id")
        if item["stage"] not in _STAGES or item["timing"] not in _TIMINGS:
            raise ValidationError("invalid synthesis deviation stage or timing")
        if synthesis_type == "qualitative" and item["stage"] == "effect_preparation":
            raise ValidationError("qualitative synthesis deviations cannot use the effect_preparation stage")
        by_id[deviation_id] = {"deviation_id": deviation_id, "stage": item["stage"],
            "frozen_commitment": _canonical_text(item["frozen_commitment"], "frozen_commitment"),
            "actual_method": _canonical_text(item["actual_method"], "actual_method"),
            "reason": _canonical_text(item["reason"], "deviation reason"), "timing": item["timing"],
            "impact_assessment": _canonical_text(item["impact_assessment"], "impact_assessment"),
            "corrective_action": _canonical_text(item["corrective_action"], "corrective_action"),
            "evidence_location": _canonical_text(item["evidence_location"], "deviation evidence_location")}
    timing_counts = {timing: sum(item["timing"] == timing for item in by_id.values())
                     for timing in sorted(_TIMINGS)}
    elevated = bool(timing_counts["after_results_seen"] or timing_counts["unknown"])
    result = {"synthesis_deviations_version": 1, "synthesis_plan_sha256": digest,
        "plan_id": plan.get("plan_id"), "snapshot_id": plan.get("snapshot_id"),
        "frozen_plan_commitments": {
            "synthesis_type": synthesis_type,
            "research_question": plan.get("research_question"),
            "primary_outcome": plan.get("primary_outcome"),
            "effect_measure": plan.get("effect_measure"),
            "contrast_definition": plan.get("contrast_definition"),
            "statistical_model": plan.get("statistical_model"),
            "minimum_independent_studies": plan.get("minimum_independent_studies"),
            "included_source_ids_at_freeze": plan.get("included_source_ids_at_freeze"),
            "conclusion_rule": plan.get("conclusion_rule"),
            "deviation_policy": plan.get("deviation_policy"),
        },
        "reviewer": reviewer, "deviations": [by_id[item] for item in sorted(by_id)],
        "timing_counts": timing_counts,
        "status": ("no_deviations_declared" if not by_id else
                   "retrospective_or_uncertain_deviation_review_required" if elevated else
                   "prospective_deviations_recorded"),
        "claim_ceiling_effect": "cannot_raise",
        "scientific_evidence_eligible": False, "plan_amended": False,
        "limitations": [
            "This artifact discloses departures but never edits, supersedes, or retroactively preregisters the frozen plan.",
            "Reviewer identity, stated timing, reasons, and impact assessments are not authenticated by the machine.",
            "After-results or unknown-timing deviations require heightened interpretation and cannot raise a conclusion ceiling.",
        ]}
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("synthesis-deviation output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".synthesis-deviations-", dir=root.parent) as temporary:
        staging = Path(temporary) / "synthesis-deviations"; staging.mkdir()
        (staging / "synthesis-deviations.json").write_bytes(encoded); os.replace(staging, root)
    return {"path": str(root), "synthesis_deviations_sha256": hashlib.sha256(encoded).hexdigest(), **result}
