"""Freeze literature synthesis commitments before claim extraction."""
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


_TYPES = {"qualitative", "quantitative"}
_MODELS = {"not_applicable", "fixed_effect", "random_effects"}
_QUANTITATIVE_SENSITIVITIES = {
    "leave_one_study_out",
    "exclude_high_or_unclear_bias",
    "alternate_fixed_effect",
    "alternate_random_effects",
}


def _text_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if (not isinstance(value, list)
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))
            or (not allow_empty and not value)):
        raise ValidationError(f"synthesis plan {field} must be a unique array of non-empty text")
    return [item.strip() for item in value]


def create_synthesis_plan(
    screening_path: Path,
    expected_sha256: str,
    specification: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    expected_sha256 = require_sha256(expected_sha256, "expected_screening_sha256")
    try:
        content = screening_path.read_bytes()
        screening = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("could not read valid screening JSON") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValidationError("synthesis plan screening does not match the expected SHA-256")
    if (not isinstance(screening, dict) or screening.get("screening_version") != 2
            or screening.get("status") != "screening_recorded"):
        raise ValidationError("synthesis planning requires a completed version 2 screening")
    included = sorted(item.get("source_id") for item in screening.get("decisions", [])
                      if isinstance(item, dict) and item.get("decision") == "include")
    if not included or any(not isinstance(item, str) or not item.strip() for item in included):
        raise ValidationError("synthesis planning requires included source records")

    required = {
        "plan_id", "reviewer", "research_question", "primary_outcome",
        "synthesis_type", "effect_measure", "contrast_definition", "statistical_model",
        "minimum_independent_studies", "eligibility_policy", "missing_statistics_policy",
        "heterogeneity_policy", "multiplicity_policy", "subgroup_analyses",
        "sensitivity_analyses", "conclusion_rule", "deviation_policy",
    }
    if not isinstance(specification, dict) or set(specification) != required:
        raise ValidationError("synthesis plan fields do not match the documented contract")
    synthesis_type = specification["synthesis_type"]
    model = specification["statistical_model"]
    if synthesis_type not in _TYPES or model not in _MODELS:
        raise ValidationError("invalid synthesis_type or statistical_model")
    effect_measure = _text(specification["effect_measure"], "effect_measure").strip()
    contrast_definition = _text(specification["contrast_definition"], "contrast_definition").strip()
    if synthesis_type == "qualitative" and (effect_measure != "not_applicable" or model != "not_applicable"):
        raise ValidationError("qualitative synthesis requires not_applicable effect_measure and statistical_model")
    if synthesis_type == "qualitative" and contrast_definition != "not_applicable":
        raise ValidationError("qualitative synthesis requires not_applicable contrast_definition")
    if synthesis_type == "quantitative" and contrast_definition == "not_applicable":
        raise ValidationError("quantitative synthesis requires an explicit contrast_definition")
    if synthesis_type == "quantitative" and (effect_measure == "not_applicable" or model == "not_applicable"):
        raise ValidationError("quantitative synthesis requires a declared effect measure and statistical model")
    minimum = specification["minimum_independent_studies"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValidationError("minimum_independent_studies must be a positive integer")

    sensitivities = _text_list(specification["sensitivity_analyses"], "sensitivity_analyses", allow_empty=False)
    if synthesis_type == "quantitative":
        unknown = sorted(set(sensitivities) - _QUANTITATIVE_SENSITIVITIES)
        if unknown:
            raise ValidationError("unknown executable quantitative sensitivity analysis: " + ", ".join(unknown))
        incompatible = ((model == "fixed_effect" and "alternate_fixed_effect" in sensitivities)
                        or (model == "random_effects" and "alternate_random_effects" in sensitivities))
        if incompatible:
            raise ValidationError("alternate-model sensitivity must differ from the primary statistical model")
    plan = {
        "synthesis_plan_version": 1,
        "screening_sha256": digest,
        "snapshot_id": screening.get("snapshot_id"),
        "included_source_ids_at_freeze": included,
        "plan_id": _text(specification["plan_id"], "plan_id").strip(),
        "reviewer": _text(specification["reviewer"], "reviewer").strip(),
        "research_question": _text(specification["research_question"], "research_question").strip(),
        "primary_outcome": _text(specification["primary_outcome"], "primary_outcome").strip(),
        "synthesis_type": synthesis_type,
        "effect_measure": effect_measure,
        "contrast_definition": contrast_definition,
        "statistical_model": model,
        "minimum_independent_studies": minimum,
        "eligibility_policy": _text(specification["eligibility_policy"], "eligibility_policy").strip(),
        "missing_statistics_policy": _text(specification["missing_statistics_policy"], "missing_statistics_policy").strip(),
        "heterogeneity_policy": _text(specification["heterogeneity_policy"], "heterogeneity_policy").strip(),
        "multiplicity_policy": _text(specification["multiplicity_policy"], "multiplicity_policy").strip(),
        "subgroup_analyses": _text_list(specification["subgroup_analyses"], "subgroup_analyses"),
        "sensitivity_analyses": sensitivities,
        "conclusion_rule": _text(specification["conclusion_rule"], "conclusion_rule").strip(),
        "deviation_policy": _text(specification["deviation_policy"], "deviation_policy").strip(),
        "status": "synthesis_plan_frozen",
        "scientific_evidence_eligible": False,
        "limitations": [
            "The plan is hash-bound to screening but the machine does not authenticate the reviewer or prove that freezing preceded extraction outside this workflow.",
            "A frozen plan does not establish that its effect measure, statistical model, thresholds, or decision rules are scientifically appropriate.",
            "Departures require a separate declared deviation; this artifact never authorizes selective omission of null, adverse, or high-bias studies.",
        ],
    }
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("synthesis plan output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(plan, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".synthesis-plan-", dir=root.parent) as temporary:
        staging = Path(temporary) / "synthesis-plan"
        staging.mkdir()
        (staging / "synthesis-plan.json").write_bytes(encoded)
        os.replace(staging, root)
    return {"path": str(root), "synthesis_plan_sha256": hashlib.sha256(encoded).hexdigest(), **plan}
