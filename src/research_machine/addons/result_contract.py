from __future__ import annotations

from typing import Any

from research_machine.addons.models import INFERENCE_LEVELS
from research_machine.domain.errors import ValidationError


RESULT_CONTRACT_FIELDS = frozenset({
    "result_contract_version",
    "analysis_id",
    "addon_id",
    "addon_version",
    "method",
    "purpose",
    "estimand",
    "contrast_definition",
    "contrast_groups",
    "claim_ceiling",
    "maximum_inference_level",
    "randomness_control",
    "randomness_binding",
    "declared_claim_ceiling",
    "claim_ceiling_status",
    "missing_data_policy",
    "missing_data_policy_scope",
    "result",
})
CLAIM_CEILING_STATUS = (
    "method_enforced_maximum; the researcher declaration is retained but cannot widen it"
)
MISSING_DATA_POLICY_SCOPE = (
    "Declared specification setting only; consult method results for actual exclusions or rejection rules."
)


def _require_text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValidationError(f"{field} must be text")
    return value


def validate_analysis_result_contract(result: dict[str, Any]) -> None:
    if set(result) != RESULT_CONTRACT_FIELDS:
        raise ValidationError("analysis result contract fields do not match version 2")
    if result.get("result_contract_version") != 2:
        raise ValidationError("analysis result contract version is unsupported")
    for field in ("analysis_id", "addon_id", "addon_version", "method"):
        _require_text(result.get(field), f"analysis result {field}")
    for field in ("purpose", "estimand", "contrast_definition"):
        _require_text(result.get(field), f"analysis result {field}", allow_empty=True)
    if not isinstance(result.get("contrast_groups"), list) or any(
        not isinstance(item, str) for item in result["contrast_groups"]
    ):
        raise ValidationError("analysis result contrast_groups must be an array of text")
    _require_text(result.get("claim_ceiling"), "analysis result claim_ceiling")
    _require_text(
        result.get("declared_claim_ceiling"),
        "analysis result declared_claim_ceiling",
    )
    if result.get("claim_ceiling_status") != CLAIM_CEILING_STATUS:
        raise ValidationError("analysis result claim_ceiling_status is invalid")
    if result.get("maximum_inference_level") not in INFERENCE_LEVELS:
        raise ValidationError("analysis result maximum_inference_level is unsupported")
    if result.get("missing_data_policy") not in (None, "complete_case"):
        raise ValidationError("analysis result missing_data_policy is unsupported")
    if result.get("missing_data_policy_scope") != MISSING_DATA_POLICY_SCOPE:
        raise ValidationError("analysis result missing_data_policy_scope is invalid")
