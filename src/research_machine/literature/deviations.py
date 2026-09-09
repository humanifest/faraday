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
from research_machine.literature.synthesis_plan import validate_synthesis_plan_boundary


_STAGES = {"extraction", "citation_verification", "bias_assessment", "study_reconciliation",
           "effect_preparation", "synthesis", "reporting"}
_TIMINGS = {"before_extraction", "before_synthesis", "after_results_seen", "unknown"}


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def _optional_canonical_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _canonical_text(value, field)


def _validate_frozen_plan_commitments(value: Any) -> None:
    required = {
        "synthesis_type",
        "research_question",
        "primary_outcome",
        "effect_measure",
        "contrast_definition",
        "statistical_model",
        "minimum_independent_studies",
        "included_source_ids_at_freeze",
        "conclusion_rule",
        "deviation_policy",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValidationError("synthesis deviations require exact frozen plan commitments")
    synthesis_type = value.get("synthesis_type")
    if synthesis_type not in {"qualitative", "quantitative"}:
        raise ValidationError("frozen plan synthesis_type is invalid")
    for field in (
        "research_question",
        "primary_outcome",
        "effect_measure",
        "contrast_definition",
        "statistical_model",
        "conclusion_rule",
        "deviation_policy",
    ):
        _optional_canonical_text(value.get(field), f"frozen plan {field}")
    minimum = value.get("minimum_independent_studies")
    if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, int) or minimum <= 0):
        raise ValidationError("frozen plan minimum_independent_studies must be a positive integer")
    source_ids = value.get("included_source_ids_at_freeze")
    if source_ids is not None:
        if (not isinstance(source_ids, list)
                or any(not isinstance(item, str) or not item.strip()
                       or item != item.strip() for item in source_ids)
                or len(source_ids) != len(set(source_ids))):
            raise ValidationError("frozen plan included_source_ids_at_freeze must be unique canonical text")


def _replay_deviations(value: Any, *, synthesis_type: str | None = None) -> tuple[list[dict[str, str]], dict[str, int], str]:
    if not isinstance(value, list):
        raise ValidationError("retained synthesis deviations must be an array")
    required = {"deviation_id", "stage", "frozen_commitment", "actual_method", "reason",
                "timing", "impact_assessment", "corrective_action", "evidence_location"}
    by_id: dict[str, dict[str, str]] = {}
    for item in value:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError("retained synthesis deviation fields do not match the documented contract")
        deviation_id = _canonical_text(item["deviation_id"], "retained deviation_id")
        if deviation_id in by_id:
            raise ValidationError("retained synthesis deviations contain duplicate deviation_id")
        stage = item["stage"]
        timing = item["timing"]
        if stage not in _STAGES or timing not in _TIMINGS:
            raise ValidationError("retained synthesis deviation stage or timing is invalid")
        if synthesis_type == "qualitative" and stage == "effect_preparation":
            raise ValidationError("qualitative synthesis deviations cannot use the effect_preparation stage")
        by_id[deviation_id] = {
            "deviation_id": deviation_id,
            "stage": stage,
            "frozen_commitment": _canonical_text(
                item["frozen_commitment"], "retained frozen_commitment"
            ),
            "actual_method": _canonical_text(item["actual_method"], "retained actual_method"),
            "reason": _canonical_text(item["reason"], "retained deviation reason"),
            "timing": timing,
            "impact_assessment": _canonical_text(
                item["impact_assessment"], "retained impact_assessment"
            ),
            "corrective_action": _canonical_text(
                item["corrective_action"], "retained corrective_action"
            ),
            "evidence_location": _canonical_text(
                item["evidence_location"], "retained deviation evidence_location"
            ),
        }
    timing_counts = {timing: sum(item["timing"] == timing for item in by_id.values())
                     for timing in sorted(_TIMINGS)}
    elevated = bool(timing_counts["after_results_seen"] or timing_counts["unknown"])
    status = ("no_deviations_declared" if not by_id else
              "retrospective_or_uncertain_deviation_review_required" if elevated else
              "prospective_deviations_recorded")
    return [by_id[item] for item in sorted(by_id)], timing_counts, status


def validate_synthesis_deviations_boundary(
    deviations: dict[str, Any], *, synthesis_type: str | None = None
) -> None:
    """Replay deviation-disclosure non-authority and status from retained rows."""
    if deviations.get("synthesis_deviations_version") != 1:
        raise ValidationError("synthesis deviations version is invalid")
    require_sha256(
        deviations.get("synthesis_plan_sha256"),
        "synthesis deviations synthesis_plan_sha256",
    )
    _canonical_text(deviations.get("plan_id"), "synthesis deviations plan_id")
    _canonical_text(deviations.get("snapshot_id"), "synthesis deviations snapshot_id")
    _canonical_text(deviations.get("reviewer"), "synthesis deviations reviewer")
    _validate_frozen_plan_commitments(deviations.get("frozen_plan_commitments"))
    if deviations.get("scientific_evidence_eligible") is not False:
        raise ValidationError("synthesis deviations must remain scientifically ineligible")
    if deviations.get("conclusion_authorized") is not False:
        raise ValidationError("synthesis deviations must not authorize conclusions")
    if deviations.get("publication_authorized") is not False:
        raise ValidationError("synthesis deviations must not authorize publication claims")
    if deviations.get("plan_amended") is not False:
        raise ValidationError("synthesis deviations must not amend the frozen plan")
    if deviations.get("claim_ceiling_effect") != "cannot_raise":
        raise ValidationError("synthesis deviations must retain cannot_raise claim ceiling effect")
    limitations = deviations.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("synthesis deviations require retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _canonical_text(limitation, f"synthesis-deviation limitation {index + 1}")
    retained, timing_counts, status = _replay_deviations(
        deviations.get("deviations"), synthesis_type=synthesis_type
    )
    if deviations.get("deviations") != retained:
        raise ValidationError("synthesis deviations must retain canonical deviation rows")
    if deviations.get("timing_counts") != timing_counts:
        raise ValidationError("synthesis-deviation timing_counts do not replay from deviations")
    if deviations.get("status") != status:
        raise ValidationError("synthesis-deviation status does not replay from deviations")


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
    validate_synthesis_plan_boundary(plan)
    synthesis_type = plan.get("synthesis_type")
    if synthesis_type not in {"qualitative", "quantitative"}:
        raise ValidationError("synthesis deviations require a plan with a supported synthesis_type")
    if not isinstance(disclosure, dict) or set(disclosure) != {"reviewer", "deviations"}:
        raise ValidationError("deviation disclosure requires exactly reviewer and deviations")
    reviewer = _canonical_text(disclosure["reviewer"], "deviation reviewer")
    deviations = disclosure["deviations"]
    if not isinstance(deviations, list):
        raise ValidationError("deviations must be an array")
    retained_deviations, timing_counts, status = _replay_deviations(
        deviations, synthesis_type=synthesis_type
    )
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
        "reviewer": reviewer, "deviations": retained_deviations,
        "timing_counts": timing_counts,
        "status": status,
        "claim_ceiling_effect": "cannot_raise",
        "scientific_evidence_eligible": False, "plan_amended": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "This artifact discloses departures but never edits, supersedes, or retroactively preregisters the frozen plan.",
            "Reviewer identity, stated timing, reasons, and impact assessments are not authenticated by the machine.",
            "After-results or unknown-timing deviations require heightened interpretation and cannot raise a conclusion ceiling.",
        ]}
    validate_synthesis_deviations_boundary(result, synthesis_type=synthesis_type)
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("synthesis-deviation output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".synthesis-deviations-", dir=root.parent) as temporary:
        staging = Path(temporary) / "synthesis-deviations"; staging.mkdir()
        (staging / "synthesis-deviations.json").write_bytes(encoded); os.replace(staging, root)
    return {"path": str(root), "synthesis_deviations_sha256": hashlib.sha256(encoded).hexdigest(), **result}
