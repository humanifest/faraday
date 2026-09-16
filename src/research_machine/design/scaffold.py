from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any
from research_machine.domain.models import (
    ClaimLevel, ControlDefinition, CONTROL_FAMILIES, MEASUREMENT_TEMPORAL_ROLES,
)
from research_machine.design.causal import audit_causal_identification
from research_machine.design.precision import build_sample_size_planning_receipt
from research_machine.domain.errors import ValidationError


_REQUIRED = {"title", "question", "decision", "outcome", "unit_of_observation"}
_STUDY_TYPES = {"causal", "correlational", "exploratory", "descriptive"}
_MEASUREMENT_SCALES = {
    "binary", "nominal", "ordinal", "interval", "ratio", "count",
    "time_to_event",
}
_ANALYSIS_FAMILIES = {
    "mean_difference", "paired_mean_difference", "adjusted_linear_effect",
    "descriptive", "custom_reviewed",
}
_SECONDARY_MEASUREMENT_FIELDS = {
    "outcome", "observable", "input_condition", "parameter_values",
    "evaluation_point", "convention", "aggregation", "tolerance",
    "expected_behavior", "data_column", "temporal_role", "scale_type", "unit",
    "admissible_values", "valid_min", "valid_max", "missing_value_codes",
}
_CONTROL_MEASUREMENT_FIELDS = (
    _SECONDARY_MEASUREMENT_FIELDS - {"outcome"}
) | {"control"}
_CAUSAL_MEASUREMENT_FIELDS = (
    _SECONDARY_MEASUREMENT_FIELDS - {"outcome"}
) | {"variable", "role"}
_CLAIM_BOUNDARY_FIELDS = {"statement", "level", "scope"}
_VALIDITY_CHECK_FIELDS = {
    "check_id", "evidence_type", "validity_claim", "assessment_plan",
    "acceptance_criterion", "failure_response", "assessment_gate_id",
}
_VALIDITY_EVIDENCE_TYPES = {
    "criterion", "convergent", "discriminant", "known_groups", "test_retest",
    "inter_rater", "content", "calibration", "other",
}
_ALIAS_PROXY_COMMITMENT_FIELDS = {
    "commitment_id",
    "concealment_scope",
    "public_label",
    "private_mapping_sha256",
    "construct_validity_rationale",
    "limitations",
    "reveal_conditions",
    "proxy_construct",
}
_ALIAS_PROXY_SCOPES = {
    "registered_target_alias",
    "observable_alias",
    "input_condition_alias",
    "data_column_alias",
    "value_domain_alias",
    "proxy_measurement",
}
_CLAIM_LEVELS = {level.value for level in ClaimLevel}
_CANARY_TARGET_PLAN_FIELDS = {
    "plan_id",
    "candidate_target_ids",
    "seed_commitment_sha256",
    "assignment_artifact_sha256",
    "masking_plan",
    "ethical_disclosure",
    "assessment_gate_id",
}
_CONTROLLED_ACCEPTANCE_SCENARIO_FIELDS = {
    "scenario_id",
    "purpose",
    "expected_observation",
    "distinguishes_from",
    "failure_response",
    "claim_ceiling",
}
_FALSIFYING_CONTROL_FAMILIES = {
    "negative", "sham", "replay", "random_time", "adversarial",
    "apparatus_only",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPORT_OVERCLAIM = re.compile(
    r"\b(?:proved|confirmed|explained|validates?|validated)\b",
    re.IGNORECASE,
)
DESIGN_BRIEF_FIELDS = {
    "title", "question", "decision", "minimum_evidence",
    "decision_change_criteria", "decision_owner", "ambiguity_questions",
    "study_type", "population", "setting",
    "available_data_sources", "unavailable_data", "data_access_constraints",
    "data_access_owner", "data_provenance_plan",
    "ethical_constraints", "ethical_safeguards_plan",
    "intervention", "exposure_definition", "assignment_type",
    "manipulated_factors", "factorial_or_crossover_design",
    "factor_interpretability_plan",
    "outcome", "outcome_unit", "outcome_scale",
    "outcome_admissible_values", "outcome_valid_min", "outcome_valid_max",
    "outcome_missing_value_codes", "primary_analysis_family",
    "primary_estimand", "contrast_definition", "expected_effect_direction",
    "contrast_groups", "group_data_column",
    "null_value", "support_rule", "confidence_level",
    "measurement_observable", "measurement_input_condition", "measurement_parameter_values",
    "measurement_evaluation_point", "measurement_convention",
    "measurement_aggregation", "measurement_tolerance",
    "measurement_expected_behavior", "measurement_temporal_role",
    "outcome_data_column",
    "preprocessing_pipeline", "preprocessing_conformance_gate_id",
    "sensor_requirements", "clock_accuracy_requirement", "control_windows",
    "measurement_validity_checks", "alias_proxy_commitment",
    "secondary_measurements",
    "control_measurements",
    "causal_measurements",
    "sample_size_plan",
    "unit_of_observation",
    "comparison", "sampling_plan", "randomization_plan", "blinding_plan",
    "controls", "confounds", "calibration_plan", "measurement_validity",
    "analysis_commitment", "stopping_rule", "human_participants", "consent_plan",
    "privacy_plan", "withdrawal_plan", "retention_deletion_plan",
    "independent_review", "independent_review_receipt",
    "independent_review_decision", "independent_reviewer_role",
    "independent_reviewed_at", "independent_review_scope",
    "independent_review_artifact_locator",
    "independent_review_artifact_sha256", "independent_review_conditions",
    "risk_description",
    "vulnerable_population_plan", "data_security_plan", "incidental_findings_plan",
    "exclusions",
    "independent_unit", "repeated_measures", "analysis_design", "unit_analysis_plan", "unit_id_column",
    "observable_prediction", "null_model", "falsification_conditions",
    "control_definitions", "sample_size_justification", "secondary_outcomes",
    "confirmatory_outcomes", "exploratory_outcomes", "multiplicity_method",
    "multiplicity_alpha", "multiple_testing_policy", "minimum_analyzable_units", "maximum_excluded_fraction",
    "maximum_group_excluded_fraction_difference",
    "missingness_assumption", "missingness_assessment_plan",
    "missingness_failure_response", "missingness_assessment_kind",
    "missingness_assessment_gate_id",
    "smallest_effect_size_of_interest", "effect_scale",
    "conclusion_time_window", "non_supporting_direction",
    "higher_level_conclusions_unsupported",
    "claim_boundaries", "causal_identification", "canary_target_plan",
    "hypothesis_reactivity_plan",
    "controlled_acceptance_scenarios",
}


@dataclass(frozen=True)
class DesignFinding:
    code: str
    severity: str
    message: str
    remediation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "remediation": self.remediation,
        }


def _text_list(brief: dict[str, Any], key: str) -> list[str]:
    value = brief.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"design brief field {key} must be an array of non-blank strings")
    return value


def _decision_change_criteria(brief: dict[str, Any]) -> list[str]:
    criteria = _text_list(brief, "decision_change_criteria")
    seen: set[str] = set()
    for index, criterion in enumerate(criteria, start=1):
        criterion_key = criterion.strip().casefold()
        if criterion_key in seen:
            raise ValueError(
                f"decision_change_criteria[{index}] duplicates an earlier criterion"
            )
        seen.add(criterion_key)
    return criteria


def _ambiguity_questions(brief: dict[str, Any]) -> list[str]:
    questions = _text_list(brief, "ambiguity_questions")
    seen: set[str] = set()
    for index, question in enumerate(questions, start=1):
        question_key = question.strip().casefold()
        if question_key in seen:
            raise ValueError(
                f"ambiguity_questions[{index}] duplicates an earlier ambiguity question"
            )
        seen.add(question_key)
    return questions


def _data_availability_boundary(
    brief: dict[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    available = _text_list(brief, "available_data_sources")
    unavailable = _text_list(brief, "unavailable_data")
    constraints = _text_list(brief, "data_access_constraints")
    available_keys: set[str] = set()
    for index, source in enumerate(available, start=1):
        source_key = source.strip().casefold()
        if source_key in available_keys:
            raise ValueError(
                f"available_data_sources[{index}] duplicates an earlier available data source"
            )
        available_keys.add(source_key)
    unavailable_keys: set[str] = set()
    for index, source in enumerate(unavailable, start=1):
        source_key = source.strip().casefold()
        if source_key in unavailable_keys:
            raise ValueError(
                f"unavailable_data[{index}] duplicates an earlier unavailable data item"
            )
        if source_key in available_keys:
            raise ValueError(
                f"unavailable_data[{index}] conflicts with an available data source"
            )
        unavailable_keys.add(source_key)
    return available, unavailable, constraints


def _independent_review_conditions(brief: dict[str, Any]) -> list[str]:
    conditions = _text_list(brief, "independent_review_conditions")
    seen: set[str] = set()
    for index, condition in enumerate(conditions, start=1):
        condition_key = condition.strip().casefold()
        if condition_key in seen:
            raise ValueError(
                f"independent_review_conditions[{index}] duplicates an earlier review condition"
            )
        seen.add(condition_key)
    return conditions


def _claim_boundaries(brief: dict[str, Any]) -> list[dict[str, str]]:
    value = brief.get("claim_boundaries", [])
    if not isinstance(value, list):
        raise ValueError("claim_boundaries must be an array")
    claims: list[dict[str, str]] = []
    statements: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict) or set(item) != _CLAIM_BOUNDARY_FIELDS:
            raise ValueError(
                f"claim_boundaries[{index}] must contain exactly statement, level, and scope"
            )
        for field in _CLAIM_BOUNDARY_FIELDS:
            if not isinstance(item[field], str) or not item[field].strip():
                raise ValueError(
                    f"claim_boundaries[{index}].{field} must be non-blank text"
                )
        if item["level"] not in _CLAIM_LEVELS:
            raise ValueError(
                f"claim_boundaries[{index}].level must be a supported claim level"
            )
        statement_key = item["statement"].strip().casefold()
        if statement_key in statements:
            raise ValueError(
                f"claim_boundaries[{index}].statement duplicates an earlier claim boundary"
            )
        statements.append(statement_key)
        claims.append(
            {
                "statement": item["statement"],
                "level": item["level"],
                "scope": item["scope"],
            }
        )
    return claims


def _bounded_review_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-blank text")
    if _REPORT_OVERCLAIM.search(value):
        raise ValueError(
            f"{field} uses report-prohibited overclaiming language"
        )
    return value


def _controlled_acceptance_scenarios(
    brief: dict[str, Any],
) -> list[dict[str, Any]]:
    value = brief.get("controlled_acceptance_scenarios", [])
    if not isinstance(value, list):
        raise ValueError("controlled_acceptance_scenarios must be an array")
    scenarios: list[dict[str, Any]] = []
    scenario_ids: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict) or set(item) != _CONTROLLED_ACCEPTANCE_SCENARIO_FIELDS:
            raise ValueError(
                "controlled_acceptance_scenarios["
                + str(index)
                + "] must contain exactly scenario_id, purpose, expected_observation, "
                "distinguishes_from, failure_response, and claim_ceiling"
            )
        scenario_id = _bounded_review_text(
            item["scenario_id"],
            f"controlled_acceptance_scenarios[{index}].scenario_id",
        )
        normalized_id = scenario_id.strip().casefold()
        if normalized_id in scenario_ids:
            raise ValueError(
                f"controlled_acceptance_scenarios[{index}].scenario_id duplicates an earlier scenario"
            )
        scenario_ids.add(normalized_id)
        distinguishes_from = item["distinguishes_from"]
        if (
            not isinstance(distinguishes_from, list)
            or not distinguishes_from
            or any(
                not isinstance(entry, str) or not entry.strip()
                for entry in distinguishes_from
            )
        ):
            raise ValueError(
                f"controlled_acceptance_scenarios[{index}].distinguishes_from must be a non-empty array of non-blank text"
            )
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "purpose": _bounded_review_text(
                    item["purpose"],
                    f"controlled_acceptance_scenarios[{index}].purpose",
                ),
                "expected_observation": _bounded_review_text(
                    item["expected_observation"],
                    f"controlled_acceptance_scenarios[{index}].expected_observation",
                ),
                "distinguishes_from": [
                    _bounded_review_text(
                        entry,
                        f"controlled_acceptance_scenarios[{index}].distinguishes_from[{entry_index}]",
                    )
                    for entry_index, entry in enumerate(distinguishes_from)
                ],
                "failure_response": _bounded_review_text(
                    item["failure_response"],
                    f"controlled_acceptance_scenarios[{index}].failure_response",
                ),
                "claim_ceiling": _bounded_review_text(
                    item["claim_ceiling"],
                    f"controlled_acceptance_scenarios[{index}].claim_ceiling",
                ),
            }
        )
    return scenarios


def _is_canonical_sha256(value: str) -> bool:
    return bool(_SHA256.fullmatch(value))


def _optional_alias_proxy_commitment(
    value: Any,
    *,
    field: str,
    expected_labels: dict[str, set[str]],
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    if set(value) != _ALIAS_PROXY_COMMITMENT_FIELDS:
        raise ValueError(
            f"{field} must contain exactly the documented alias/proxy commitment fields"
        )
    for text_field in (
        "commitment_id",
        "concealment_scope",
        "public_label",
        "private_mapping_sha256",
        "construct_validity_rationale",
        "reveal_conditions",
        "proxy_construct",
    ):
        if not isinstance(value[text_field], str):
            raise ValueError(f"{field}.{text_field} must be text")
    if any(
        not value[text_field].strip()
        for text_field in (
            "commitment_id",
            "concealment_scope",
            "public_label",
            "private_mapping_sha256",
            "construct_validity_rationale",
            "reveal_conditions",
        )
    ):
        raise ValueError(f"{field} required text fields must be non-blank")
    if any(
        value[text_field] != value[text_field].strip()
        for text_field in (
            "commitment_id",
            "concealment_scope",
            "public_label",
            "private_mapping_sha256",
            "construct_validity_rationale",
            "reveal_conditions",
            "proxy_construct",
        )
    ):
        raise ValueError(f"{field} text fields must not contain surrounding whitespace")
    if value["concealment_scope"] not in _ALIAS_PROXY_SCOPES:
        raise ValueError(f"{field}.concealment_scope is unsupported")
    if not _is_canonical_sha256(value["private_mapping_sha256"]):
        raise ValueError(f"{field}.private_mapping_sha256 must be a lowercase SHA-256")
    for text_field in (
        "construct_validity_rationale",
        "reveal_conditions",
        "proxy_construct",
    ):
        if value[text_field] and _REPORT_OVERCLAIM.search(value[text_field]):
            raise ValueError(
                f"{field}.{text_field} uses report-prohibited overclaiming language"
            )
    limitations = value["limitations"]
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(not isinstance(item, str) or not item.strip() for item in limitations)
    ):
        raise ValueError(f"{field}.limitations must be a non-empty array of non-blank text")
    if any(item != item.strip() for item in limitations):
        raise ValueError(f"{field}.limitations must not contain surrounding whitespace")
    normalized_limitations = [item.casefold() for item in limitations]
    if len(set(normalized_limitations)) != len(normalized_limitations):
        raise ValueError(f"{field}.limitations must be unique")
    scope = value["concealment_scope"]
    if value["public_label"] not in expected_labels[scope]:
        raise ValueError(
            f"{field}.public_label must match the declared public measurement field"
        )
    if scope == "data_column_alias" and not expected_labels[scope]:
        raise ValueError(f"{field}.data_column_alias requires an executable data column")
    if scope == "value_domain_alias" and not expected_labels[scope]:
        raise ValueError(f"{field}.value_domain_alias requires an observed value domain")
    if scope == "proxy_measurement" and not value["proxy_construct"]:
        raise ValueError(
            f"{field}.proxy_construct must identify the hidden construct for proxy_measurement"
        )
    if scope != "proxy_measurement" and value["proxy_construct"]:
        raise ValueError(f"{field}.proxy_construct is reserved for proxy_measurement")
    return dict(value)


def _measurement_alias_expected_labels(
    measurement: dict[str, Any],
    target_key: str,
) -> dict[str, set[str]]:
    data_column = measurement.get("data_column", "")
    return {
        "registered_target_alias": {measurement[target_key]},
        "observable_alias": {measurement["observable"]},
        "input_condition_alias": {measurement["input_condition"]},
        "data_column_alias": {data_column} if data_column else set(),
        "value_domain_alias": set(measurement["admissible_values"]),
        "proxy_measurement": {measurement["observable"]},
    }


def _primary_alias_expected_labels(brief: dict[str, Any]) -> dict[str, set[str]]:
    outcome_data_column = brief.get("outcome_data_column", "")
    measurement_observable = brief.get("measurement_observable", "")
    return {
        "registered_target_alias": {brief["outcome"]},
        "observable_alias": {measurement_observable} if measurement_observable else set(),
        "input_condition_alias": (
            {brief["measurement_input_condition"]}
            if brief.get("measurement_input_condition")
            else set()
        ),
        "data_column_alias": {outcome_data_column} if outcome_data_column else set(),
        "value_domain_alias": set(_text_list(brief, "outcome_admissible_values")),
        "proxy_measurement": {measurement_observable} if measurement_observable else set(),
    }


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _content_sha256(value: Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = _canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def _rendered_artifact_sha256(value: Any) -> str:
    if isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = (
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _scaffold_provenance(brief: dict[str, Any], findings: list[DesignFinding]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "guided_experiment_scaffold",
        "authority": "review_only",
        "brief_content_sha256": _content_sha256(brief),
        "design_findings_sha256": _content_sha256(
            [item.to_dict() for item in findings]
        ),
        "scientific_evidence_eligible": False,
    }


def _stamp_scaffold_provenance(
    artifacts: dict[str, Any], provenance: dict[str, Any]
) -> None:
    for value in artifacts.values():
        if isinstance(value, dict):
            value["scaffold_provenance"] = dict(provenance)


def _scaffold_manifest(
    status: str, artifacts: dict[str, Any], provenance: dict[str, Any]
) -> dict[str, Any]:
    entries = [
        {
            "name": name,
            "media_type": "text/markdown" if isinstance(content, str) else "application/json",
            "content_sha256": _rendered_artifact_sha256(content),
        }
        for name, content in sorted(artifacts.items())
    ]
    return {
        **provenance,
        "status": status,
        "artifact_manifest": entries,
        "artifact_manifest_sha256": _content_sha256(entries),
        "notice": (
            "This manifest binds review-only scaffold artifacts to the exact "
            "canonical design brief content and deterministic findings that "
            "produced them. It is not approval, protocol freeze, evidence, or "
            "authentication of reviewer identity."
        ),
    }


def inquiry_decision_commitments(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_to_support": brief["decision"],
        "minimum_evidence": brief.get(
            "minimum_evidence",
            "[REVIEW REQUIRED] Define the minimum decision-relevant evidence.",
        ),
        "decision_change_criteria": _decision_change_criteria(brief)
        or ["[REVIEW REQUIRED] Define what result changes the decision."],
        "decision_owner": brief.get("decision_owner", "[REVIEW REQUIRED]"),
    }


def _analysis_contract_method(family: str) -> str:
    return {
        "mean_difference": "independent_mean_difference_ci",
        "paired_mean_difference": "paired_mean_difference_ci",
        "adjusted_linear_effect": "adjusted_linear_effect",
        "descriptive": "descriptive_summary",
        "custom_reviewed": "[REVIEW REQUIRED] method from the reviewed add-on manifest",
    }.get(family, "[REVIEW REQUIRED] choose an executable reviewed method")


def _analysis_contract_assignment_type(
    *, study_type: str, assignment_type: str
) -> str:
    if study_type == "causal" and assignment_type == "randomized":
        return "randomized_between_units"
    if assignment_type == "observational" or study_type == "correlational":
        return "observational"
    if assignment_type == "randomized":
        return "randomized_between_units"
    return "[REVIEW REQUIRED] observational, randomized_between_units, nonrandomized, or not_applicable"


def _analysis_contract_selectors(method: str) -> tuple[str, str]:
    if method == "adjusted_linear_effect":
        return (
            "/result/adjusted_mean_difference_first_minus_second",
            "/result/robust_confidence_interval",
        )
    if method in {"independent_mean_difference_ci", "paired_mean_difference_ci"}:
        return (
            "/result/mean_difference_first_minus_second",
            "/result/confidence_interval",
        )
    return (
        "[REVIEW REQUIRED] absolute JSON Pointer to the registered effect estimate",
        "[REVIEW REQUIRED] absolute JSON Pointer to the registered uncertainty object",
    )


def _analysis_contract_draft(
    brief: dict[str, Any],
    *,
    study_type: str,
    assignment_type: str,
) -> dict[str, Any]:
    method = _analysis_contract_method(brief.get("primary_analysis_family", ""))
    contract_assignment_type = _analysis_contract_assignment_type(
        study_type=study_type, assignment_type=assignment_type
    )
    effect_path, uncertainty_path = _analysis_contract_selectors(method)
    adjustment_columns: list[str] = []
    if (
        method == "adjusted_linear_effect"
        and isinstance(brief.get("causal_identification"), dict)
    ):
        adjustment_columns = list(
            brief["causal_identification"].get("proposed_adjustment_set", [])
        )
    return {
        "primary_hypothesis_id": "[REVIEW REQUIRED] bind the reviewed primary hypothesis ID",
        "primary_measurement_id": "[REVIEW REQUIRED] bind the reviewed primary measurement ID",
        "method": method,
        "outcome_column": brief.get(
            "outcome_data_column",
            "[REVIEW REQUIRED] exact primary outcome column",
        ),
        "group_column": brief.get(
            "group_data_column",
            "[REVIEW REQUIRED] exact comparison or exposure column",
        ),
        "groups": _text_list(brief, "contrast_groups") or [
            "[REVIEW REQUIRED] first contrast level",
            "[REVIEW REQUIRED] second contrast level",
        ],
        "adjustment_columns": adjustment_columns,
        "estimand": brief.get(
            "primary_estimand", "[REVIEW REQUIRED] primary estimand"
        ),
        "contrast_definition": brief.get(
            "contrast_definition", "[REVIEW REQUIRED] signed contrast"
        ),
        "contrast_groups": _text_list(brief, "contrast_groups") or [
            "[REVIEW REQUIRED] first contrast level",
            "[REVIEW REQUIRED] second contrast level",
        ],
        "missing_data_policy": "complete_case",
        "assignment_type": contract_assignment_type,
        "effect_estimate_path": effect_path,
        "uncertainty_path": uncertainty_path,
        "null_value": brief.get("null_value", "[REVIEW REQUIRED] numeric null"),
        "support_rule": brief.get("support_rule", "[REVIEW REQUIRED] support rule"),
        "confidence_level": brief.get(
            "confidence_level", "[REVIEW REQUIRED] confidence level"
        ),
        "minimum_analyzable_units": brief.get(
            "minimum_analyzable_units",
            "[REVIEW REQUIRED] minimum analyzable independent units",
        ),
        "maximum_excluded_fraction": brief.get(
            "maximum_excluded_fraction",
            "[REVIEW REQUIRED] maximum excluded fraction",
        ),
        "maximum_group_excluded_fraction_difference": brief.get(
            "maximum_group_excluded_fraction_difference",
            "[REVIEW REQUIRED] maximum group exclusion-fraction difference",
        ),
        "allocation_sha256": "[REVIEW REQUIRED] design randomize allocation_sha256"
        if contract_assignment_type == "randomized_between_units"
        else "",
        "missingness_assumption": brief.get(
            "missingness_assumption", "[REVIEW REQUIRED] missingness assumption"
        ),
        "missingness_assessment_plan": brief.get(
            "missingness_assessment_plan",
            "[REVIEW REQUIRED] missingness assessment plan",
        ),
        "missingness_failure_response": brief.get(
            "missingness_failure_response",
            "[REVIEW REQUIRED] missingness failure response",
        ),
        "missingness_assessment_kind": brief.get(
            "missingness_assessment_kind",
            "[REVIEW REQUIRED] empirical_diagnostic, design_record_review, external_validation, or substantive_judgment",
        ),
        "missingness_assessment_gate_id": brief.get(
            "missingness_assessment_gate_id",
            "[REVIEW REQUIRED] dedicated missingness gate ID",
        ),
    }


def validate_brief(brief: dict[str, Any]) -> None:
    if not isinstance(brief, dict):
        raise ValueError("design brief must be an object")
    unknown = set(brief) - DESIGN_BRIEF_FIELDS
    if unknown:
        raise ValueError("unknown design brief fields: " + ", ".join(sorted(unknown)))
    non_text_fields = {"controls", "confounds", "exclusions", "falsification_conditions", "decision_change_criteria", "ambiguity_questions", "available_data_sources", "unavailable_data", "data_access_constraints", "ethical_constraints", "secondary_outcomes", "confirmatory_outcomes", "exploratory_outcomes", "multiplicity_alpha", "independent_review_conditions", "human_participants", "independent_review", "repeated_measures", "factorial_or_crossover_design", "control_definitions", "minimum_analyzable_units", "maximum_excluded_fraction", "maximum_group_excluded_fraction_difference", "smallest_effect_size_of_interest", "higher_level_conclusions_unsupported", "claim_boundaries", "causal_identification", "canary_target_plan", "hypothesis_reactivity_plan", "controlled_acceptance_scenarios", "outcome_admissible_values", "outcome_missing_value_codes", "outcome_valid_min", "outcome_valid_max", "null_value", "confidence_level", "contrast_groups", "manipulated_factors", "sensor_requirements", "control_windows", "measurement_parameter_values", "measurement_validity_checks", "alias_proxy_commitment", "secondary_measurements", "control_measurements", "causal_measurements", "sample_size_plan"}
    for key, value in brief.items():
        if key not in non_text_fields and not isinstance(value, str):
            raise ValueError(f"design brief field {key} must be a string")
    missing = sorted(key for key in _REQUIRED if not brief.get(key, "").strip())
    if missing:
        raise ValueError("design brief is missing required fields: " + ", ".join(missing))
    definitions = brief.get("control_definitions", [])
    if not isinstance(definitions, list):
        raise ValueError("control_definitions must be an array")
    for item in definitions:
        try:
            definition = ControlDefinition(**item)
        except TypeError as exc:
            raise ValueError("control definition requires exactly the documented fields") from exc
        if any(not isinstance(value, str) for value in definition.to_dict().values()):
            raise ValueError("control definition fields must be strings")
    _independent_review_conditions(brief)
    study_type = brief.get("study_type", "exploratory")
    if study_type not in _STUDY_TYPES:
        raise ValueError("study_type must be one of: " + ", ".join(sorted(_STUDY_TYPES)))
    if brief.get("assignment_type", "") not in {"", "randomized", "observational"}:
        raise ValueError("assignment_type must be randomized or observational")
    for key in {"controls", "confounds", "exclusions", "falsification_conditions", "ambiguity_questions", "available_data_sources", "unavailable_data", "data_access_constraints", "ethical_constraints", "secondary_outcomes", "confirmatory_outcomes", "exploratory_outcomes", "higher_level_conclusions_unsupported", "outcome_admissible_values", "outcome_missing_value_codes", "contrast_groups", "manipulated_factors", "sensor_requirements", "control_windows"}:
        _text_list(brief, key)
    _decision_change_criteria(brief)
    _ambiguity_questions(brief)
    _data_availability_boundary(brief)
    _claim_boundaries(brief)
    _controlled_acceptance_scenarios(brief)
    if brief.get("outcome_scale", "") not in {"", *_MEASUREMENT_SCALES}:
        raise ValueError("outcome_scale is unsupported")
    if brief.get("primary_analysis_family", "") not in {"", *_ANALYSIS_FAMILIES}:
        raise ValueError("primary_analysis_family is unsupported")
    if brief.get("expected_effect_direction", "") not in {
        "", "positive", "negative", "two_sided", "equivalence",
    }:
        raise ValueError("expected_effect_direction is unsupported")
    if brief.get("support_rule", "") not in {
        "", "point_direction", "interval_excludes_null",
        "interval_within_equivalence_margin",
    }:
        raise ValueError("support_rule is unsupported")
    if brief.get("measurement_temporal_role", "") not in {
        "", *MEASUREMENT_TEMPORAL_ROLES,
    }:
        raise ValueError("measurement_temporal_role is unsupported")
    parameters = brief.get("measurement_parameter_values", {})
    if not isinstance(parameters, dict) or any(
        not isinstance(key, str) or not key.strip()
        or not isinstance(value, str) or not value.strip()
        for key, value in parameters.items()
    ):
        raise ValueError("measurement_parameter_values must be an object of non-blank string bindings")
    validity_checks = brief.get("measurement_validity_checks", [])
    if not isinstance(validity_checks, list):
        raise ValueError("measurement_validity_checks must be an array")
    for index, check in enumerate(validity_checks):
        if not isinstance(check, dict) or set(check) != _VALIDITY_CHECK_FIELDS:
            raise ValueError(
                f"measurement_validity_checks[{index}] must contain exactly the documented fields"
            )
        if any(not isinstance(value, str) or not value.strip() for value in check.values()):
            raise ValueError(f"measurement_validity_checks[{index}] fields must be non-blank text")
        if check["evidence_type"] not in _VALIDITY_EVIDENCE_TYPES:
            raise ValueError(f"measurement_validity_checks[{index}].evidence_type is unsupported")
    _optional_alias_proxy_commitment(
        brief.get("alias_proxy_commitment"),
        field="alias_proxy_commitment",
        expected_labels=_primary_alias_expected_labels(brief),
    )
    secondary_measurements = brief.get("secondary_measurements", [])
    if not isinstance(secondary_measurements, list):
        raise ValueError("secondary_measurements must be an array")
    for index, measurement in enumerate(secondary_measurements):
        if not isinstance(measurement, dict) or not (
            set(measurement) == _SECONDARY_MEASUREMENT_FIELDS
            or set(measurement) == _SECONDARY_MEASUREMENT_FIELDS | {"alias_proxy_commitment"}
        ):
            raise ValueError(
                f"secondary_measurements[{index}] must contain exactly the documented measurement fields"
            )
        for field in _SECONDARY_MEASUREMENT_FIELDS - {
            "parameter_values", "admissible_values", "valid_min", "valid_max",
            "missing_value_codes",
        }:
            if not isinstance(measurement[field], str) or not measurement[field].strip():
                raise ValueError(f"secondary_measurements[{index}].{field} must be non-blank text")
        values = measurement["parameter_values"]
        if not isinstance(values, dict) or not values or any(
            not isinstance(key, str) or not key.strip()
            or not isinstance(value, str) or not value.strip()
            for key, value in values.items()
        ):
            raise ValueError(f"secondary_measurements[{index}].parameter_values must contain non-blank string bindings")
        for field in ("admissible_values", "missing_value_codes"):
            values = measurement[field]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"secondary_measurements[{index}].{field} must be an array of non-blank text")
        for field in ("valid_min", "valid_max"):
            value = measurement[field]
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"secondary_measurements[{index}].{field} must be finite or null")
        _optional_alias_proxy_commitment(
            measurement.get("alias_proxy_commitment"),
            field=f"secondary_measurements[{index}].alias_proxy_commitment",
            expected_labels=_measurement_alias_expected_labels(measurement, "outcome"),
        )
    control_measurements = brief.get("control_measurements", [])
    if not isinstance(control_measurements, list):
        raise ValueError("control_measurements must be an array")
    for index, measurement in enumerate(control_measurements):
        if not isinstance(measurement, dict) or not (
            set(measurement) == _CONTROL_MEASUREMENT_FIELDS
            or set(measurement) == _CONTROL_MEASUREMENT_FIELDS | {"alias_proxy_commitment"}
        ):
            raise ValueError(
                f"control_measurements[{index}] must contain exactly the documented measurement fields"
            )
        for field in _CONTROL_MEASUREMENT_FIELDS - {
            "parameter_values", "admissible_values", "valid_min", "valid_max",
            "missing_value_codes", "data_column", "scale_type", "unit",
        }:
            if not isinstance(measurement[field], str) or not measurement[field].strip():
                raise ValueError(f"control_measurements[{index}].{field} must be non-blank text")
        for field in ("data_column", "scale_type", "unit"):
            if not isinstance(measurement[field], str):
                raise ValueError(f"control_measurements[{index}].{field} must be text")
        values = measurement["parameter_values"]
        if not isinstance(values, dict) or not values or any(
            not isinstance(key, str) or not key.strip()
            or not isinstance(value, str) or not value.strip()
            for key, value in values.items()
        ):
            raise ValueError(f"control_measurements[{index}].parameter_values must contain non-blank string bindings")
        for field in ("admissible_values", "missing_value_codes"):
            values = measurement[field]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"control_measurements[{index}].{field} must be an array of non-blank text")
        for field in ("valid_min", "valid_max"):
            value = measurement[field]
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"control_measurements[{index}].{field} must be finite or null")
        _optional_alias_proxy_commitment(
            measurement.get("alias_proxy_commitment"),
            field=f"control_measurements[{index}].alias_proxy_commitment",
            expected_labels=_measurement_alias_expected_labels(measurement, "control"),
        )
    causal_measurements = brief.get("causal_measurements", [])
    if not isinstance(causal_measurements, list):
        raise ValueError("causal_measurements must be an array")
    for index, measurement in enumerate(causal_measurements):
        if not isinstance(measurement, dict) or not (
            set(measurement) == _CAUSAL_MEASUREMENT_FIELDS
            or set(measurement) == _CAUSAL_MEASUREMENT_FIELDS | {"alias_proxy_commitment"}
        ):
            raise ValueError(
                f"causal_measurements[{index}] must contain exactly the documented measurement fields"
            )
        for field in _CAUSAL_MEASUREMENT_FIELDS - {
            "parameter_values", "admissible_values", "valid_min", "valid_max",
            "missing_value_codes",
        }:
            if not isinstance(measurement[field], str) or not measurement[field].strip():
                raise ValueError(f"causal_measurements[{index}].{field} must be non-blank text")
        values = measurement["parameter_values"]
        if not isinstance(values, dict) or not values or any(
            not isinstance(key, str) or not key.strip()
            or not isinstance(value, str) or not value.strip()
            for key, value in values.items()
        ):
            raise ValueError(f"causal_measurements[{index}].parameter_values must contain non-blank string bindings")
        for field in ("admissible_values", "missing_value_codes"):
            values = measurement[field]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"causal_measurements[{index}].{field} must be an array of non-blank text")
        for field in ("valid_min", "valid_max"):
            value = measurement[field]
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"causal_measurements[{index}].{field} must be finite or null")
        _optional_alias_proxy_commitment(
            measurement.get("alias_proxy_commitment"),
            field=f"causal_measurements[{index}].alias_proxy_commitment",
            expected_labels=_measurement_alias_expected_labels(measurement, "variable"),
        )
    for key in ("outcome_valid_min", "outcome_valid_max"):
        if key in brief and brief[key] is not None and (
            isinstance(brief[key], bool)
            or not isinstance(brief[key], (int, float))
            or not math.isfinite(float(brief[key]))
        ):
            raise ValueError(f"{key} must be a finite number or null")
    if "null_value" in brief and (
        isinstance(brief["null_value"], bool)
        or not isinstance(brief["null_value"], (int, float))
        or not math.isfinite(float(brief["null_value"]))
    ):
        raise ValueError("null_value must be a finite number")
    if "confidence_level" in brief and (
        isinstance(brief["confidence_level"], bool)
        or not isinstance(brief["confidence_level"], (int, float))
        or not math.isfinite(float(brief["confidence_level"]))
        or not 0.8 <= float(brief["confidence_level"]) < 1
    ):
        raise ValueError("confidence_level must be finite and in [0.8, 1)")
    if "multiplicity_alpha" in brief and brief["multiplicity_alpha"] is not None and (
        isinstance(brief["multiplicity_alpha"], bool)
        or not isinstance(brief["multiplicity_alpha"], (int, float))
        or not math.isfinite(float(brief["multiplicity_alpha"]))
        or not 0 < float(brief["multiplicity_alpha"]) < 1
    ):
        raise ValueError("multiplicity_alpha must be finite and strictly between zero and one")
    if brief.get("multiplicity_method", "") not in {"", "single_test", "holm", "exploratory_only"}:
        raise ValueError("multiplicity_method must be single_test, holm, or exploratory_only")
    if "smallest_effect_size_of_interest" in brief and (
        isinstance(brief["smallest_effect_size_of_interest"], bool)
        or not isinstance(brief["smallest_effect_size_of_interest"], (int, float))
        or not math.isfinite(float(brief["smallest_effect_size_of_interest"]))
        or float(brief["smallest_effect_size_of_interest"]) < 0
    ):
        raise ValueError("smallest_effect_size_of_interest must be finite and non-negative")
    if brief.get("non_supporting_direction", "") not in {"", "inconclusive", "weakens"}:
        raise ValueError("non_supporting_direction must be inconclusive or weakens")
    for key in {"human_participants", "independent_review", "repeated_measures", "factorial_or_crossover_design"}:
        if key in brief and not isinstance(brief[key], bool):
            raise ValueError(f"design brief field {key} must be a boolean")
    if "independent_unit" in brief and (not isinstance(brief["independent_unit"], str) or not brief["independent_unit"].strip()):
        raise ValueError("independent_unit must be a non-blank string")
    if "analysis_design" in brief and brief["analysis_design"] not in ("independent_groups", "paired", "clustered", "repeated_measures", "descriptive"):
        raise ValueError("analysis_design must be independent_groups, paired, clustered, repeated_measures, or descriptive")
    if "minimum_analyzable_units" in brief and (
        type(brief["minimum_analyzable_units"]) is not int or brief["minimum_analyzable_units"] < 2
    ):
        raise ValueError("minimum_analyzable_units must be an integer of at least two")
    if "maximum_excluded_fraction" in brief and (
        isinstance(brief["maximum_excluded_fraction"], bool)
        or not isinstance(brief["maximum_excluded_fraction"], (int, float))
        or not 0 <= float(brief["maximum_excluded_fraction"]) < 1
    ):
        raise ValueError("maximum_excluded_fraction must be in [0, 1)")
    if "maximum_group_excluded_fraction_difference" in brief and (
        isinstance(brief["maximum_group_excluded_fraction_difference"], bool)
        or not isinstance(
            brief["maximum_group_excluded_fraction_difference"], (int, float)
        )
        or not 0 <= float(
            brief["maximum_group_excluded_fraction_difference"]
        ) <= 1
    ):
        raise ValueError(
            "maximum_group_excluded_fraction_difference must be in [0, 1]"
        )
    if "causal_identification" in brief and not isinstance(brief["causal_identification"], dict):
        raise ValueError("causal_identification must be an object")
    canary_plan = brief.get("canary_target_plan")
    if canary_plan is not None:
        if not isinstance(canary_plan, dict):
            raise ValueError("canary_target_plan must be an object")
        if set(canary_plan) != _CANARY_TARGET_PLAN_FIELDS:
            raise ValueError("canary_target_plan must contain exactly the documented fields")
        for field in _CANARY_TARGET_PLAN_FIELDS - {"candidate_target_ids"}:
            if not isinstance(canary_plan[field], str) or not canary_plan[field].strip():
                raise ValueError(f"canary_target_plan.{field} must be non-blank text")
        targets = canary_plan["candidate_target_ids"]
        if (
            not isinstance(targets, list)
            or any(not isinstance(item, str) or not item.strip() for item in targets)
        ):
            raise ValueError("canary_target_plan.candidate_target_ids must be an array of non-blank text")
    reactivity_plan = brief.get("hypothesis_reactivity_plan")
    if reactivity_plan is not None:
        from research_machine.application.hypothesis_reactivity import (
            parse_hypothesis_reactivity_plan,
        )

        try:
            parse_hypothesis_reactivity_plan(reactivity_plan)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
    if "sample_size_plan" in brief and not isinstance(brief["sample_size_plan"], dict):
        raise ValueError("sample_size_plan must be an object")
    if brief.get("missingness_assessment_kind", "") not in {
        "", "empirical_diagnostic", "design_record_review", "external_validation",
        "substantive_judgment",
    }:
        raise ValueError("missingness_assessment_kind is unsupported")


def audit_design(brief: dict[str, Any]) -> list[DesignFinding]:
    validate_brief(brief)
    findings: list[DesignFinding] = []
    study_type = brief.get("study_type", "exploratory")

    def add(code: str, severity: str, message: str, remediation: str) -> None:
        findings.append(DesignFinding(code, severity, message, remediation))

    def require_canonical_list_items(key: str, code: str, label: str) -> None:
        values = _text_list(brief, key)
        if any(item != item.strip() for item in values):
            add(
                code,
                "error",
                f"{label} contain labels with surrounding whitespace.",
                "Use exact stable labels without padding so review artifacts, coverage checks, gates, and execution handles bind the same scientific roles.",
            )

    def has_noncanonical_parameter_values(values: dict[str, str]) -> bool:
        return any(
            key != key.strip() or value != value.strip()
            for key, value in values.items()
        )

    def has_noncanonical_text_items(values: list[str]) -> bool:
        return any(value != value.strip() for value in values)

    if any(brief[field] != brief[field].strip() for field in _REQUIRED):
        add(
            "CORE_BRIEF_FIELD_NONCANONICAL", "error",
            "A required design brief field contains surrounding whitespace.",
            "Use exact unpadded title, question, decision, outcome, and unit-of-observation text before review drafts preserve them as inquiry, hypothesis, protocol, and collection commitments.",
        )
    decision_change_criteria = _decision_change_criteria(brief)
    if (
        not str(brief.get("minimum_evidence", "")).strip()
        or not decision_change_criteria
        or not str(brief.get("decision_owner", "")).strip()
    ):
        add(
            "INQUIRY_DECISION_BOUNDARY_INCOMPLETE",
            "warning",
            "The guided inquiry lacks a complete minimum-evidence threshold, decision-change criterion, or decision owner.",
            "Before treating the study as decision-ready, state who owns the decision, what minimum evidence is enough, and what observation would change the decision.",
        )
    if (
        (
            isinstance(brief.get("minimum_evidence"), str)
            and brief["minimum_evidence"] != brief["minimum_evidence"].strip()
        )
        or (
            isinstance(brief.get("decision_owner"), str)
            and brief["decision_owner"] != brief["decision_owner"].strip()
        )
        or has_noncanonical_text_items(decision_change_criteria)
    ):
        add(
            "INQUIRY_DECISION_BOUNDARY_NONCANONICAL",
            "error",
            "The inquiry decision boundary contains text with surrounding whitespace.",
            "Use exact unpadded minimum-evidence, decision-change, and decision-owner commitments before review artifacts preserve them.",
        )
    ambiguity_questions = _ambiguity_questions(brief)
    if not ambiguity_questions:
        add(
            "AMBIGUITY_QUESTIONS_UNRESOLVED",
            "warning",
            "The guided design records no explicit unresolved ambiguity questions.",
            "Before design review, state the important unknowns, ambiguities, or discriminator questions that should remain open rather than being answered by the scaffold.",
        )
    if has_noncanonical_text_items(ambiguity_questions):
        add(
            "AMBIGUITY_QUESTION_NONCANONICAL",
            "error",
            "A guided ambiguity question contains surrounding whitespace.",
            "Use exact unpadded ambiguity questions before review artifacts and canonical open questions preserve them.",
        )
    claim_boundaries = _claim_boundaries(brief)
    if not claim_boundaries:
        add(
            "CLAIM_BOUNDARIES_UNRESOLVED",
            "warning",
            "The guided design has no explicit claim-level boundary proposals.",
            "Separate observation, measurement-validity, association, causal-direction, mechanism, adaptation, attribution/intent, legal characterization, robustness, and other claims before review.",
        )
    if any(
        item["statement"] != item["statement"].strip()
        or item["scope"] != item["scope"].strip()
        or item["level"] != item["level"].strip()
        for item in claim_boundaries
    ):
        add(
            "CLAIM_BOUNDARY_NONCANONICAL",
            "error",
            "A guided claim boundary contains text with surrounding whitespace.",
            "Use exact unpadded claim statements, levels, and scopes before review artifacts and canonical unresolved claims preserve them.",
        )
    controlled_acceptance_scenarios = _controlled_acceptance_scenarios(brief)
    if not controlled_acceptance_scenarios:
        add(
            "CONTROLLED_ACCEPTANCE_SCENARIOS_UNRESOLVED",
            "warning",
            "The guided design has no controlled acceptance scenarios for discriminating machine behavior.",
            "Before treating the scaffold as an end-to-end readiness target, name synthetic or controlled scenarios that should recover planted signals, return nulls, expose confounds, reject tampering, and preserve claim boundaries.",
        )
    if any(
        scenario["scenario_id"] != scenario["scenario_id"].strip()
        or scenario["purpose"] != scenario["purpose"].strip()
        or scenario["expected_observation"]
        != scenario["expected_observation"].strip()
        or scenario["failure_response"] != scenario["failure_response"].strip()
        or scenario["claim_ceiling"] != scenario["claim_ceiling"].strip()
        or has_noncanonical_text_items(scenario["distinguishes_from"])
        for scenario in controlled_acceptance_scenarios
    ):
        add(
            "CONTROLLED_ACCEPTANCE_SCENARIO_NONCANONICAL",
            "error",
            "A controlled acceptance scenario contains text with surrounding whitespace.",
            "Use exact unpadded scenario IDs, expectations, alternatives, failure responses, and claim ceilings before review artifacts preserve them.",
        )
    available_data_sources, unavailable_data, data_access_constraints = (
        _data_availability_boundary(brief)
    )
    if not available_data_sources:
        add(
            "DATA_AVAILABILITY_UNRESOLVED",
            "warning",
            "The guided design has no declared available data source.",
            "Identify existing records, instruments, field collection, simulations, or unavailable data before choosing a discriminating test.",
        )
    if not str(brief.get("data_provenance_plan", "")).strip():
        add(
            "DATA_PROVENANCE_PLAN_MISSING",
            "warning",
            "The guided design has no plan for binding source data to provenance.",
            "State how source bytes, collection context, custody, and access limitations will be retained before collection or analysis.",
        )
    if not str(brief.get("data_access_owner", "")).strip():
        add(
            "DATA_ACCESS_OWNER_UNRESOLVED",
            "warning",
            "The guided design has no declared data access owner.",
            "Name who controls access to the needed data so custody, consent, licensing, and operational limits remain accountable before collection or analysis.",
        )
    if (
        has_noncanonical_text_items(available_data_sources)
        or has_noncanonical_text_items(unavailable_data)
        or has_noncanonical_text_items(data_access_constraints)
        or (
            isinstance(brief.get("data_access_owner"), str)
            and brief["data_access_owner"] != brief["data_access_owner"].strip()
        )
        or (
            isinstance(brief.get("data_provenance_plan"), str)
            and brief["data_provenance_plan"]
            and brief["data_provenance_plan"] != brief["data_provenance_plan"].strip()
        )
    ):
        add(
            "DATA_AVAILABILITY_NONCANONICAL",
            "error",
            "The guided data-availability record contains text with surrounding whitespace.",
            "Use exact unpadded source, unavailable-data, access-owner, constraint, and provenance-plan text before review artifacts preserve it.",
        )
    if not _text_list(brief, "ethical_constraints"):
        add(
            "ETHICAL_CONSTRAINTS_UNRESOLVED",
            "warning",
            "The guided design has no declared ethical or safety constraint boundary.",
            "Name applicable consent, safety, community, environmental, dual-use, resource, animal-welfare, or other ethical constraints before collection or analysis.",
        )
    if not str(brief.get("ethical_safeguards_plan", "")).strip():
        add(
            "ETHICAL_SAFEGUARDS_PLAN_MISSING",
            "warning",
            "The guided design has no plan for handling its declared ethical constraints.",
            "State how constraints will be reviewed, monitored, and turned into stop conditions or qualified-review requirements before collection or analysis.",
        )
    if (
        has_noncanonical_text_items(_text_list(brief, "ethical_constraints"))
        or (
            isinstance(brief.get("ethical_safeguards_plan"), str)
            and brief["ethical_safeguards_plan"]
            and brief["ethical_safeguards_plan"] != brief["ethical_safeguards_plan"].strip()
        )
    ):
        add(
            "ETHICAL_SAFEGUARDS_NONCANONICAL",
            "error",
            "The guided ethical-safeguards record contains text with surrounding whitespace.",
            "Use exact unpadded ethical constraints and safeguards text before review artifacts preserve them.",
        )
    require_canonical_list_items("secondary_outcomes", "SECONDARY_OUTCOME_LABEL_NONCANONICAL", "Secondary outcomes")
    require_canonical_list_items("confirmatory_outcomes", "CONFIRMATORY_OUTCOME_LABEL_NONCANONICAL", "Confirmatory outcomes")
    require_canonical_list_items("exploratory_outcomes", "EXPLORATORY_OUTCOME_LABEL_NONCANONICAL", "Exploratory outcomes")
    require_canonical_list_items("contrast_groups", "CONTRAST_GROUP_LABEL_NONCANONICAL", "Contrast groups")
    require_canonical_list_items("manipulated_factors", "MANIPULATED_FACTOR_NONCANONICAL", "Manipulated factors")
    require_canonical_list_items("sensor_requirements", "SENSOR_REQUIREMENT_NONCANONICAL", "Sensor requirements")
    require_canonical_list_items("control_windows", "CONTROL_WINDOW_NONCANONICAL", "Control windows")
    require_canonical_list_items("controls", "CONTROL_LABEL_NONCANONICAL", "Controls")
    require_canonical_list_items("confounds", "CONFOUND_LABEL_NONCANONICAL", "Confounds")
    require_canonical_list_items("exclusions", "EXCLUSION_RULE_NONCANONICAL", "Exclusion rules")
    require_canonical_list_items(
        "falsification_conditions",
        "FALSIFICATION_CONDITION_NONCANONICAL",
        "Falsification conditions",
    )
    require_canonical_list_items(
        "higher_level_conclusions_unsupported",
        "UNSUPPORTED_CONCLUSION_NONCANONICAL",
        "Unsupported-conclusion ceilings",
    )

    def measurement_contract_is_noncanonical(
        measurement: dict[str, Any],
        *,
        optional_text_fields: set[str] | None = None,
    ) -> bool:
        optional_text_fields = optional_text_fields or set()
        for key, value in measurement.items():
            if key in {
                "parameter_values", "admissible_values", "missing_value_codes",
                "valid_min", "valid_max",
            }:
                continue
            if key in optional_text_fields and value == "":
                continue
            if isinstance(value, str) and value != value.strip():
                return True
        return (
            has_noncanonical_parameter_values(measurement["parameter_values"])
            or has_noncanonical_text_items(measurement["admissible_values"])
            or has_noncanonical_text_items(measurement["missing_value_codes"])
        )

    primary_measurement_fields = (
        "outcome_data_column", "outcome_unit", "measurement_observable",
        "measurement_input_condition", "measurement_evaluation_point",
        "measurement_convention", "measurement_aggregation",
        "measurement_tolerance", "measurement_expected_behavior",
    )
    if any(
        isinstance(brief.get(field), str)
        and brief[field]
        and brief[field] != brief[field].strip()
        for field in primary_measurement_fields
    ) or has_noncanonical_parameter_values(
        brief.get("measurement_parameter_values", {})
    ):
        add(
            "MEASUREMENT_CONTRACT_NONCANONICAL",
            "error",
            "The primary measurement contract contains text or parameter bindings with surrounding whitespace.",
            "Use exact unpadded measurement handles and scientific semantics before generating review artifacts or freezing a protocol.",
        )
    if (
        has_noncanonical_text_items(_text_list(brief, "outcome_admissible_values"))
        or has_noncanonical_text_items(_text_list(brief, "outcome_missing_value_codes"))
    ):
        add(
            "MEASUREMENT_DOMAIN_NONCANONICAL",
            "error",
            "The primary measurement value domain contains encodings with surrounding whitespace.",
            "Record observed-value and missing-value encodings exactly as they appear in source data, without padding.",
        )
    primary_alias_proxy_commitment = _optional_alias_proxy_commitment(
        brief.get("alias_proxy_commitment"),
        field="alias_proxy_commitment",
        expected_labels=_primary_alias_expected_labels(brief),
    )
    if (
        primary_alias_proxy_commitment is not None
        and primary_alias_proxy_commitment["concealment_scope"] == "proxy_measurement"
        and not brief.get("measurement_validity_checks")
    ):
        add(
            "ALIAS_PROXY_VALIDITY_PLAN_MISSING",
            "error",
            "The primary measurement is a proxy for a hidden construct without a prospective validity-check plan.",
            "Declare at least one measurement_validity_checks entry that states how the proxy-to-construct claim will be assessed before analysis.",
        )

    secondary_outcomes = _text_list(brief, "secondary_outcomes")
    manipulated_factors = _text_list(brief, "manipulated_factors")
    sensor_requirements = _text_list(brief, "sensor_requirements")
    control_windows = _text_list(brief, "control_windows")
    normalized_factors = [item.strip().casefold() for item in manipulated_factors]
    factorial_or_crossover = brief.get("factorial_or_crossover_design", False)
    factor_plan = brief.get("factor_interpretability_plan", "")
    if len(set(normalized_factors)) != len(normalized_factors):
        add(
            "MANIPULATED_FACTOR_DUPLICATE",
            "error",
            "Manipulated factors contain duplicate labels.",
            "Give each changed person, setting, apparatus, operator, condition, or analysis-label factor one stable name before review.",
        )
    if len({item.strip().casefold() for item in sensor_requirements}) != len(sensor_requirements):
        add(
            "SENSOR_REQUIREMENT_DUPLICATE",
            "error",
            "Sensor requirements contain duplicate labels.",
            "Give each required instrument, stream, or channel one stable name so custody, calibration, and missing-channel checks cannot double-count it.",
        )
    if len({item.strip().casefold() for item in control_windows}) != len(control_windows):
        add(
            "CONTROL_WINDOW_DUPLICATE",
            "error",
            "Control windows contain duplicate labels.",
            "Give each baseline, sham, replay, random-time, apparatus-only, or negative-control window one stable name before review.",
        )
    if factor_plan and factor_plan != factor_plan.strip():
        add(
            "FACTOR_INTERPRETABILITY_PLAN_NONCANONICAL",
            "error",
            "The factor-interpretability plan contains surrounding whitespace.",
            "Use exact unpadded plan text before review artifacts preserve how simultaneous factor changes will be separated.",
        )
    if factorial_or_crossover and not manipulated_factors:
        add(
            "FACTOR_INTERPRETABILITY_INCOMPLETE",
            "error",
            "A factorial or crossover design is declared without naming the manipulated factors.",
            "Name each manipulated factor so reviewers can tell what the design is supposed to separate.",
        )
    if factorial_or_crossover and not factor_plan.strip():
        add(
            "FACTOR_INTERPRETABILITY_INCOMPLETE",
            "error",
            "A factorial or crossover design is declared without a factor-interpretability plan.",
            "State how the design estimates or otherwise separates the effect of each changed factor before review.",
        )
    if len(manipulated_factors) > 1 and (
        not factorial_or_crossover or not factor_plan.strip()
    ):
        add(
            "MULTI_FACTOR_INTERVENTION_UNINTERPRETABLE",
            "error",
            "The guided design changes multiple factors without a declared factorial or crossover plan.",
            "Change one factor at a time, or declare a factorial/crossover design and explain how the changed factors will be interpreted separately.",
        )
    canary_plan = brief.get("canary_target_plan")
    if canary_plan is not None:
        candidate_targets = canary_plan["candidate_target_ids"]
        normalized_targets = [item.strip().casefold() for item in candidate_targets]
        if (
            len(candidate_targets) < 2
            or len(set(normalized_targets)) != len(normalized_targets)
        ):
            add(
                "CANARY_TARGET_PLAN_INCOMPLETE",
                "error",
                "The canary target plan does not name at least two distinct candidate targets.",
                "Name the real target plus at least one decoy, replay, sham, or no-target comparator before review.",
            )
        if any(
            isinstance(canary_plan.get(field), str)
            and canary_plan[field] != canary_plan[field].strip()
            for field in _CANARY_TARGET_PLAN_FIELDS - {"candidate_target_ids"}
        ) or any(target != target.strip() for target in candidate_targets):
            add(
                "CANARY_TARGET_PLAN_NONCANONICAL",
                "error",
                "The canary target plan contains target IDs, hashes, masking text, ethics text, or a gate ID with surrounding whitespace.",
                "Use exact unpadded canary target handles and commitments so masked assignment cannot be rewritten after review.",
            )
        for field in ("seed_commitment_sha256", "assignment_artifact_sha256"):
            if not _is_canonical_sha256(canary_plan[field]):
                add(
                    "CANARY_TARGET_PLAN_HASH_INVALID",
                    "error",
                    "The canary target plan uses a noncanonical SHA-256 commitment.",
                    "Record lowercase 64-character SHA-256 digests for both the committed random seed and hidden assignment artifact.",
                )
                break
    normalized_outcomes = [item.strip().casefold() for item in secondary_outcomes]
    if len(set(normalized_outcomes)) != len(normalized_outcomes):
        add("SECONDARY_OUTCOME_DUPLICATE", "error", "Secondary outcomes contain duplicate labels.", "Give each outcome one stable, unique name before review.")
    if brief["outcome"].strip().casefold() in normalized_outcomes:
        add("OUTCOME_ROLE_CONFLICT", "error", "The primary outcome is also listed as secondary.", "Assign each outcome exactly one role; do not relabel it after seeing results.")
    secondary_measurements = brief.get("secondary_measurements", [])
    measurement_targets = [item["outcome"].strip().casefold() for item in secondary_measurements]
    if (
        len(set(measurement_targets)) != len(measurement_targets)
        or [item["outcome"] for item in secondary_measurements] != secondary_outcomes
    ):
        add(
            "SECONDARY_MEASUREMENT_COVERAGE_INVALID", "error",
            "Typed secondary measurements do not uniquely and exactly cover every registered secondary outcome.",
            "Provide one complete measurement contract for each secondary outcome using its exact registered name; do not add surrogate or unregistered outcomes.",
        )
    for item in secondary_measurements:
        if measurement_contract_is_noncanonical(item):
            add(
                "SECONDARY_MEASUREMENT_CONTRACT_NONCANONICAL",
                "error",
                f"Secondary outcome {item['outcome']} has padded measurement text, parameter bindings, or value-domain encodings.",
                "Use exact unpadded measurement semantics and source-data encodings before review.",
            )
        scale = item["scale_type"]
        admissible = item["admissible_values"]
        missing = item["missing_value_codes"]
        bounds = (item["valid_min"], item["valid_max"])
        if scale not in _MEASUREMENT_SCALES or item["temporal_role"] not in MEASUREMENT_TEMPORAL_ROLES:
            add("SECONDARY_MEASUREMENT_TYPE_INVALID", "error", f"Secondary outcome {item['outcome']} has an unsupported scale or temporal role.", "Use the canonical scale and temporal-role vocabulary.")
            continue
        normalized_admissible = {value.casefold() for value in admissible}
        normalized_missing = {value.casefold() for value in missing}
        if len(normalized_admissible) != len(admissible) or len(normalized_missing) != len(missing) or normalized_admissible & normalized_missing:
            add("SECONDARY_MEASUREMENT_DOMAIN_INVALID", "error", f"Secondary outcome {item['outcome']} has duplicate or overlapping observed and missing encodings.", "Make observed and missing domains unique and disjoint.")
        categorical = scale in {"binary", "nominal", "ordinal"}
        if categorical and (not admissible or any(value is not None for value in bounds)):
            add("SECONDARY_MEASUREMENT_DOMAIN_INVALID", "error", f"Categorical secondary outcome {item['outcome']} lacks a valid enumerated domain.", "Enumerate every observed category and omit numeric bounds.")
        if scale == "binary" and len(admissible) != 2:
            add("SECONDARY_MEASUREMENT_DOMAIN_INVALID", "error", f"Binary secondary outcome {item['outcome']} does not have exactly two values.", "Register exactly two admissible observed values.")
        if not categorical and admissible:
            add("SECONDARY_MEASUREMENT_DOMAIN_INVALID", "error", f"Numeric secondary outcome {item['outcome']} uses categorical admissible values.", "Use numeric validity bounds and leave admissible_values empty.")
        if bounds[0] is not None and bounds[1] is not None and bounds[0] >= bounds[1]:
            add("SECONDARY_MEASUREMENT_DOMAIN_INVALID", "error", f"Secondary outcome {item['outcome']} has invalid numeric bounds.", "Set valid_min strictly below valid_max.")
        if scale in {"ratio", "count", "time_to_event"} and bounds[0] is not None and bounds[0] < 0:
            add("SECONDARY_MEASUREMENT_DOMAIN_INVALID", "error", f"Secondary outcome {item['outcome']} permits a negative {scale} value.", "Use a non-negative lower bound for ratio, count, and time-to-event measurements.")
        if scale == "count" and any(
            value is not None and not float(value).is_integer() for value in bounds
        ):
            add("SECONDARY_MEASUREMENT_DOMAIN_INVALID", "error", f"Count secondary outcome {item['outcome']} has a fractional validity bound.", "Use integer count bounds.")
    if secondary_outcomes and not brief.get("multiple_testing_policy", "").strip():
        add("MULTIPLICITY_POLICY_MISSING", "warning", "Multiple outcomes are declared without a multiplicity policy.", "State the confirmatory family, adjustment or hierarchical rule, and how secondary outcomes will be interpreted before inspecting results.")
    if secondary_outcomes:
        registered = [brief["outcome"], *secondary_outcomes]
        confirmatory = _text_list(brief, "confirmatory_outcomes")
        exploratory = _text_list(brief, "exploratory_outcomes")
        method = brief.get("multiplicity_method", "")
        alpha = brief.get("multiplicity_alpha")
        normalized_registered = [item.strip().casefold() for item in registered]
        normalized_confirmatory = [item.strip().casefold() for item in confirmatory]
        normalized_exploratory = [item.strip().casefold() for item in exploratory]
        if not confirmatory and not exploratory:
            add("MULTIPLICITY_PLAN_INCOMPLETE", "error", "Multiple outcomes lack an exact confirmatory/exploratory classification.", "Classify every registered outcome exactly once before review.")
        elif (len(set(normalized_confirmatory)) != len(normalized_confirmatory)
              or len(set(normalized_exploratory)) != len(normalized_exploratory)
              or set(normalized_confirmatory) & set(normalized_exploratory)
              or set(normalized_confirmatory + normalized_exploratory) != set(normalized_registered)):
            add("MULTIPLICITY_OUTCOME_PARTITION_INVALID", "error", "Outcome roles do not form an exact, disjoint partition of the registered outcomes.", "Remove duplicates and inventions, and classify every primary and secondary outcome exactly once.")
        if study_type in {"exploratory", "descriptive"}:
            if confirmatory or normalized_exploratory != normalized_registered:
                add("MULTIPLICITY_ROLE_CONFLICT", "error", "An exploratory protocol must classify every registered outcome as exploratory in registered order.", "Move all outcomes to the exploratory family; a later confirmatory study requires a new frozen protocol.")
            if method != "exploratory_only" or alpha is not None:
                add("MULTIPLICITY_METHOD_CONFLICT", "error", "An exploratory protocol must use exploratory_only without a confirmatory alpha.", "Use multiplicity_method exploratory_only and omit multiplicity_alpha.")
        else:
            if brief["outcome"].strip().casefold() not in normalized_confirmatory:
                add("MULTIPLICITY_ROLE_CONFLICT", "error", "The primary outcome is not in the confirmatory family.", "Keep the primary outcome confirmatory or explicitly redesign and re-review the protocol before collection.")
            expected_method = "single_test" if len(confirmatory) == 1 else "holm"
            if method != expected_method or alpha is None:
                add("MULTIPLICITY_METHOD_CONFLICT", "error", f"The confirmatory family requires {expected_method} with a prespecified alpha.", "Set the method from the exact confirmatory family size and record a finite alpha strictly between zero and one.")

    if study_type in {"causal", "correlational"}:
        required_conclusion_fields = {
            "population": brief.get("population"),
            "setting": brief.get("setting"),
            "outcome_unit": brief.get("outcome_unit"),
            "effect_scale": brief.get("effect_scale"),
            "conclusion_time_window": brief.get("conclusion_time_window"),
            "smallest_effect_size_of_interest": brief.get("smallest_effect_size_of_interest"),
            "non_supporting_direction": brief.get("non_supporting_direction"),
            "higher_level_conclusions_unsupported": brief.get("higher_level_conclusions_unsupported"),
        }
        missing_conclusion = [
            key for key, value in required_conclusion_fields.items()
            if value is None or value == "" or value == []
        ]
        if missing_conclusion:
            add(
                "CONCLUSION_CONTRACT_INCOMPLETE", "error",
                "The confirmatory study lacks a complete prospective conclusion contract.",
                "Before review, specify population, setting, endpoint, effect scale and unit, smallest effect of interest, non-supporting disposition, and unsupported higher-level claims.",
            )
        if any(
            isinstance(value, str) and value and value != value.strip()
            for value in required_conclusion_fields.values()
        ):
            add(
                "CONCLUSION_CONTRACT_NONCANONICAL", "error",
                "The prospective conclusion contract contains text with surrounding whitespace.",
                "Use exact unpadded population, setting, endpoint unit, effect scale, and time-window text before freezing bounded conclusion scope.",
            )
        inference_fields = {
            "primary_estimand": brief.get("primary_estimand"),
            "contrast_definition": brief.get("contrast_definition"),
            "contrast_groups": brief.get("contrast_groups"),
            "expected_effect_direction": brief.get("expected_effect_direction"),
            "null_value": brief.get("null_value"),
            "support_rule": brief.get("support_rule"),
            "confidence_level": brief.get("confidence_level"),
        }
        missing_inference = [
            key for key, value in inference_fields.items()
            if value is None or value == "" or value == []
        ]
        if missing_inference:
            add(
                "INFERENCE_COMMITMENT_INCOMPLETE", "error",
                "The confirmatory design lacks a complete estimand, contrast, direction, null, support rule, or interval level.",
                "Freeze what quantity is estimated, the signed contrast order, expected direction, numeric null, support rule, and confidence level before collection.",
            )
        if any(
            isinstance(value, str) and value and value != value.strip()
            for value in inference_fields.values()
        ):
            add(
                "INFERENCE_COMMITMENT_NONCANONICAL", "error",
                "The prospective inference commitment contains text with surrounding whitespace.",
                "Use exact unpadded estimand and signed contrast text before review artifacts preserve the hypothesis and analysis commitment.",
            )
        groups = _text_list(brief, "contrast_groups")
        if groups and (len(groups) != 2 or len({item.casefold() for item in groups}) != 2):
            add("CONTRAST_GROUPS_INVALID", "error", "The confirmatory contrast does not name exactly two distinct ordered levels.", "List the first-minus-second comparison levels exactly once and preserve that order in the executable analysis.")
    groups = _text_list(brief, "contrast_groups")
    group_data_column_value = brief.get("group_data_column", "")
    group_data_column = group_data_column_value if isinstance(group_data_column_value, str) else ""
    if group_data_column and group_data_column != group_data_column.strip():
        add(
            "GROUP_DATA_COLUMN_NONCANONICAL",
            "error",
            "The guided comparison column has surrounding whitespace.",
            "Name the exact comparison or exposure column without padding so audit, protocol, dictionary, and analysis artifacts bind the same handle.",
        )
    if len(groups) == 2 and not group_data_column:
        add(
            "GROUP_DATA_COLUMN_UNRESOLVED",
            "error" if study_type in {"causal", "correlational"} else "warning",
            "The signed two-level contrast has no explicit dataset comparison column.",
            "Name the exact group or exposure column whose values use the two registered contrast levels.",
        )
    if group_data_column and len(groups) != 2:
        add(
            "GROUP_COLUMN_WITHOUT_CONTRAST",
            "error",
            "A comparison column is declared without exactly two distinct ordered contrast levels.",
            "Freeze the exact first-minus-second levels together with the executable comparison column.",
        )
    direction = brief.get("expected_effect_direction", "")
    support_rule = brief.get("support_rule", "")
    if direction == "equivalence" and support_rule not in {"", "interval_within_equivalence_margin"}:
        add("EQUIVALENCE_RULE_CONFLICT", "error", "Equivalence intent uses a difference-support rule.", "Use the dedicated interval-within-margin rule and define the frozen equivalence margin; nonsignificance is not equivalence.")
    if direction and direction != "equivalence" and support_rule == "interval_within_equivalence_margin":
        add("DIRECTION_SUPPORT_RULE_CONFLICT", "error", "A directional difference hypothesis uses an equivalence support rule.", "Align the registered direction and decision event before collection.")
    if study_type in {"causal", "correlational"} and support_rule == "point_direction":
        add("CONFIRMATORY_POINT_RULE_TOO_WEAK", "error", "The confirmatory conclusion would rely on point direction without uncertainty separation.", "Use a prespecified confidence-interval decision rule; a point estimate alone cannot support the bounded conclusion contract.")

    controls = _text_list(brief, "controls")
    definitions = brief.get("control_definitions", [])
    if controls and not definitions:
        add(
            "CONTROL_DEFINITION_MISSING",
            "error",
            "Registered controls lack structured control definitions.",
            "For every named control, declare its stable ID, family, purpose, expected behavior, and dedicated evaluation gate before protocol review.",
        )
    if definitions:
        targets = [item["registered_control"] for item in definitions]
        ids = [item["control_id"] for item in definitions]
        if any(
            value != value.strip()
            for item in definitions
            for value in item.values()
        ):
            add(
                "CONTROL_DEFINITION_NONCANONICAL",
                "error",
                "Structured controls contain text, IDs, targets, families, expectations, or gate handles with surrounding whitespace.",
                "Use exact unpadded control definition fields before review so protocol gates and evidence partitions bind the same controls.",
            )
        if (
            targets != controls
            or len(set(targets)) != len(targets)
            or len(set(ids)) != len(ids)
        ):
            add(
                "CONTROL_COVERAGE_INVALID",
                "error",
                "Structured controls do not uniquely cover the named controls in order.",
                "Provide one uniquely identified definition for each named control in the exact registered order.",
            )
        for item in definitions:
            if any(not value.strip() for value in item.values()) or item["family"] not in CONTROL_FAMILIES:
                add("CONTROL_DEFINITION_INCOMPLETE", "error", "A control has unresolved family, purpose, expectation, or evaluation linkage.", "Complete the control definition before protocol review.")
        supported_families = {
            item["family"] for item in definitions
            if item["family"] in CONTROL_FAMILIES
        }
        if "positive" not in supported_families:
            add(
                "CONTROL_POSITIVE_FAMILY_MISSING",
                "warning",
                "Structured controls include no positive-control family.",
                "Add a positive control or document why this design cannot demonstrate that the measurement pipeline detects a known effect.",
            )
        if not supported_families.intersection(_FALSIFYING_CONTROL_FAMILIES):
            add(
                "CONTROL_FALSIFYING_FAMILY_MISSING",
                "warning",
                "Structured controls include no negative, sham, replay, random-time, adversarial, or apparatus-only family.",
                "Add a falsifying control family that can reveal contamination, leakage, timing artifacts, or misleading procedure success.",
            )
    control_measurements = brief.get("control_measurements", [])
    control_targets = [item["control"] for item in control_measurements]
    if control_targets != brief.get("controls", []) or len({item.casefold() for item in control_targets}) != len(control_targets):
        add(
            "CONTROL_MEASUREMENT_COVERAGE_INVALID", "error",
            "Typed control measurements do not uniquely and exactly cover every registered control in order.",
            "Provide one reproducible measurement definition for each control using its exact registered name; artifact-evaluated controls may leave data_column and value typing empty.",
        )
    for item in control_measurements:
        if measurement_contract_is_noncanonical(
            item,
            optional_text_fields={"data_column", "scale_type", "unit"},
        ):
            add(
                "CONTROL_MEASUREMENT_CONTRACT_NONCANONICAL",
                "error",
                f"Control {item['control']} has padded measurement text, parameter bindings, or value-domain encodings.",
                "Use exact unpadded control measurement semantics and source-data encodings before review.",
            )
        scale = item["scale_type"]
        column = item["data_column"]
        admissible = item["admissible_values"]
        missing = item["missing_value_codes"]
        bounds = (item["valid_min"], item["valid_max"])
        if item["temporal_role"] not in MEASUREMENT_TEMPORAL_ROLES:
            add("CONTROL_MEASUREMENT_TYPE_INVALID", "error", f"Control {item['control']} has an unsupported temporal role.", "Use the canonical temporal-role vocabulary.")
        if not column:
            if scale or item["unit"] or admissible or missing or any(value is not None for value in bounds):
                add("CONTROL_MEASUREMENT_DOMAIN_INVALID", "error", f"Artifact-evaluated control {item['control']} declares a partial dataset-column value contract.", "Either name a data column and complete its typed domain, or leave all column-specific fields empty.")
            continue
        if scale not in _MEASUREMENT_SCALES or not item["unit"]:
            add("CONTROL_MEASUREMENT_TYPE_INVALID", "error", f"Dataset control {item['control']} lacks a supported scale or unit.", "Type every control data column before collection.")
            continue
        normalized_admissible = {value.casefold() for value in admissible}
        normalized_missing = {value.casefold() for value in missing}
        if len(normalized_admissible) != len(admissible) or len(normalized_missing) != len(missing) or normalized_admissible & normalized_missing:
            add("CONTROL_MEASUREMENT_DOMAIN_INVALID", "error", f"Control {item['control']} has duplicate or overlapping observed and missing encodings.", "Make observed and missing domains unique and disjoint.")
        categorical = scale in {"binary", "nominal", "ordinal"}
        if categorical and (not admissible or any(value is not None for value in bounds)):
            add("CONTROL_MEASUREMENT_DOMAIN_INVALID", "error", f"Categorical control {item['control']} lacks a valid enumerated domain.", "Enumerate every observed category and omit numeric bounds.")
        if scale == "binary" and len(admissible) != 2:
            add("CONTROL_MEASUREMENT_DOMAIN_INVALID", "error", f"Binary control {item['control']} does not have exactly two values.", "Register exactly two admissible observed values.")
        if not categorical and admissible:
            add("CONTROL_MEASUREMENT_DOMAIN_INVALID", "error", f"Numeric control {item['control']} uses categorical admissible values.", "Use numeric validity bounds and leave admissible_values empty.")
        if bounds[0] is not None and bounds[1] is not None and bounds[0] >= bounds[1]:
            add("CONTROL_MEASUREMENT_DOMAIN_INVALID", "error", f"Control {item['control']} has invalid numeric bounds.", "Set valid_min strictly below valid_max.")

    causal_measurements = brief.get("causal_measurements", [])
    if causal_measurements and study_type != "causal":
        add(
            "CAUSAL_MEASUREMENT_SCOPE_INVALID", "error",
            "Causal exposure or adjustment measurements are attached to a non-causal design.",
            "Use ordinary outcome or control measurements, or explicitly redesign and review the study as causal.",
        )
    if study_type == "causal" and isinstance(brief.get("causal_identification"), dict):
        identification = brief["causal_identification"]
        expected_causal_targets = [
            ("exposure", identification["exposure"]),
            *[("covariate", item) for item in identification["proposed_adjustment_set"]],
        ]
        actual_causal_targets = [
            (item["role"], item["variable"]) for item in causal_measurements
        ]
        if actual_causal_targets != expected_causal_targets:
            add(
                "CAUSAL_MEASUREMENT_COVERAGE_INVALID", "error",
                "Causal measurements do not exactly cover the exposure followed by every adjustment covariate in registered order.",
                "Define one exposure measurement and one measurement for each proposed adjustment variable; do not omit, rename, duplicate, or add variables.",
            )
    for item in causal_measurements:
        if measurement_contract_is_noncanonical(item):
            add(
                "CAUSAL_MEASUREMENT_CONTRACT_NONCANONICAL",
                "error",
                f"Causal variable {item['variable']} has padded measurement text, parameter bindings, or value-domain encodings.",
                "Use exact unpadded causal measurement semantics and source-data encodings before review.",
            )
        variable = item["variable"]
        role = item["role"]
        scale = item["scale_type"]
        admissible = item["admissible_values"]
        missing = item["missing_value_codes"]
        bounds = (item["valid_min"], item["valid_max"])
        if role not in {"exposure", "covariate"}:
            add("CAUSAL_MEASUREMENT_ROLE_INVALID", "error", f"Causal variable {variable} has an unsupported measurement role.", "Use exposure for the audited exposure and covariate for adjustment variables.")
        if scale not in _MEASUREMENT_SCALES or item["temporal_role"] not in MEASUREMENT_TEMPORAL_ROLES:
            add("CAUSAL_MEASUREMENT_TYPE_INVALID", "error", f"Causal variable {variable} has an unsupported scale or temporal role.", "Use the canonical scale and temporal-role vocabularies.")
            continue
        normalized_admissible = [value.casefold() for value in admissible]
        normalized_missing = [value.casefold() for value in missing]
        if (len(set(normalized_admissible)) != len(admissible)
                or len(set(normalized_missing)) != len(missing)
                or set(normalized_admissible) & set(normalized_missing)):
            add("CAUSAL_MEASUREMENT_DOMAIN_INVALID", "error", f"Causal variable {variable} has duplicate or overlapping observed and missing encodings.", "Make observed and missing domains unique and disjoint.")
        categorical = scale in {"binary", "nominal", "ordinal"}
        if categorical and (not admissible or any(value is not None for value in bounds)):
            add("CAUSAL_MEASUREMENT_DOMAIN_INVALID", "error", f"Categorical causal variable {variable} lacks a valid enumerated domain.", "Enumerate observed categories and omit numeric bounds.")
        if scale == "binary" and len(admissible) != 2:
            add("CAUSAL_MEASUREMENT_DOMAIN_INVALID", "error", f"Binary causal variable {variable} does not have exactly two values.", "Register exactly two admissible observed values.")
        if not categorical and admissible:
            add("CAUSAL_MEASUREMENT_DOMAIN_INVALID", "error", f"Numeric causal variable {variable} uses categorical admissible values.", "Use numeric validity bounds and leave admissible_values empty.")
        if bounds[0] is not None and bounds[1] is not None and bounds[0] >= bounds[1]:
            add("CAUSAL_MEASUREMENT_DOMAIN_INVALID", "error", f"Causal variable {variable} has invalid numeric bounds.", "Set valid_min strictly below valid_max.")
        if scale in {"ratio", "count", "time_to_event"} and bounds[0] is not None and bounds[0] < 0:
            add("CAUSAL_MEASUREMENT_DOMAIN_INVALID", "error", f"Causal variable {variable} permits a negative {scale} value.", "Use a non-negative lower bound.")
        if role == "exposure":
            if item["temporal_role"] != "at_exposure":
                add("CAUSAL_MEASUREMENT_TIMING_INVALID", "error", f"Exposure {variable} is not measured at exposure.", "Use at_exposure and define pre-exposure covariates separately.")
            if scale not in {"binary", "nominal"}:
                add("CAUSAL_EXPOSURE_SCALE_INVALID", "error", f"Grouped exposure {variable} is not binary or nominal.", "Use a categorical exposure whose exact values are the registered contrast groups.")
            if admissible != groups:
                add("CAUSAL_EXPOSURE_LEVELS_MISMATCH", "error", f"Exposure {variable} values do not exactly match the ordered contrast levels.", "Preserve the same first-minus-second exposure levels in measurement and analysis.")
            if item["data_column"] != group_data_column:
                add("CAUSAL_EXPOSURE_COLUMN_MISMATCH", "error", f"Exposure measurement {variable} does not use the guided comparison column.", "Use one exact exposure column throughout measurement, graph, and analysis.")
        if role == "covariate":
            if item["temporal_role"] != "pre_exposure":
                add("CAUSAL_MEASUREMENT_TIMING_INVALID", "error", f"Adjustment covariate {variable} is not measured before exposure.", "Do not adjust for post-exposure variables in this causal contract.")
            if scale not in {"binary", "interval", "ratio", "count"}:
                add("CAUSAL_COVARIATE_SCALE_INVALID", "error", f"Adjustment covariate {variable} is incompatible with the bundled adjusted linear estimator.", "Use a supported typed covariate or obtain a reviewed method that implements its scale.")
            if item["data_column"] != variable:
                add("CAUSAL_COVARIATE_COLUMN_MISMATCH", "error", f"Adjustment covariate {variable} does not bind its audited DAG column exactly.", "Use the same exact name for the DAG adjustment target, measurement data column, and executable adjustment column.")

    causal_audit = None
    if "causal_identification" in brief:
        causal_audit = audit_causal_identification(brief["causal_identification"])
        severity = "error" if study_type == "causal" else "warning"
        for violation in causal_audit["violations"]:
            add("CAUSAL_" + violation["code"], severity, violation["message"], "Revise the graph, assignment claim, measurement plan, or adjustment strategy before treating the causal effect as identified.")
        graph_nodes = {item["id"].strip().casefold() for item in brief["causal_identification"]["nodes"]}
        absent_confounds = sorted(item for item in _text_list(brief, "confounds") if item.strip().casefold() not in graph_nodes)
        if absent_confounds:
            add("CAUSAL_CONFOUND_NOT_IN_GRAPH", severity, "Declared confounders are absent from the causal graph: " + ", ".join(absent_confounds), "Represent every declared alternative in the DAG or explain why it is outside the causal identification claim.")
        if group_data_column and group_data_column != brief["causal_identification"]["exposure"]:
            add(
                "CAUSAL_EXPOSURE_COLUMN_MISMATCH", severity,
                "The guided comparison column does not exactly match the audited causal exposure node.",
                "Use one exact exposure column across the causal graph, measurement definition, and executable analysis contract.",
            )
    elif study_type == "causal":
        add("CAUSAL_GRAPH_UNRESOLVED", "warning", "The causal design has no explicit DAG or adjustment-set audit.", "Declare exposure, outcome, observed and unobserved variables, directed edges, assignment type, and the proposed adjustment set; then review every graph assumption.")
    for field, code, prompt in (
        ("blinding_plan", "BLINDING_UNRESOLVED", "State who can see condition labels during collection, outcome assessment, and analysis; explain infeasible masking and the safeguards used instead. Random assignment alone does not answer this question."),
        ("observable_prediction", "PREDICTION_UNRESOLVED", "State an observable prediction, including its direction, setting, and time window."),
        ("null_model", "ALTERNATIVE_UNRESOLVED", "Describe the no-effect or competing explanation and what it predicts."),
        ("falsification_conditions", "FALSIFIER_UNRESOLVED", "State an observation that would weaken the proposed explanation, not merely a software failure."),
    ):
        value = brief.get(field)
        if not value or (isinstance(value, str) and not value.strip()):
            add(code, "warning", "The hypothesis is not yet ready for review: " + field.replace("_", " ") + " is missing.", prompt)
    prospective_commitment_fields = (
        "intervention", "exposure_definition", "comparison",
        "sampling_plan", "randomization_plan", "blinding_plan",
        "calibration_plan", "measurement_validity", "analysis_commitment",
        "stopping_rule", "observable_prediction", "null_model",
        "clock_accuracy_requirement",
    )
    if any(
        isinstance(brief.get(field), str)
        and brief[field]
        and brief[field] != brief[field].strip()
        for field in prospective_commitment_fields
    ):
        add(
            "PROSPECTIVE_COMMITMENT_NONCANONICAL", "error",
            "A prospective design commitment contains surrounding whitespace.",
            "Use exact unpadded intervention, exposure, comparison, sampling, blinding, calibration, clock-accuracy, analysis, stopping, prediction, and alternative-model text before review artifacts preserve those commitments.",
        )
    if control_windows and not str(brief.get("clock_accuracy_requirement", "")).strip():
        add(
            "CLOCK_ACCURACY_UNRESOLVED",
            "error",
            "Control windows are declared without a clock-accuracy requirement.",
            "State the maximum tolerable timing uncertainty or synchronization rule before timing windows can be interpreted.",
        )
    preprocessing_pipeline = brief.get("preprocessing_pipeline", "")
    preprocessing_gate_id = brief.get("preprocessing_conformance_gate_id", "")
    if preprocessing_pipeline:
        if preprocessing_pipeline != preprocessing_pipeline.strip():
            add(
                "PREPROCESSING_PIPELINE_HASH_NONCANONICAL",
                "error",
                "The guided preprocessing-pipeline commitment contains surrounding whitespace.",
                "Use the exact lowercase SHA-256 digest of the reviewed registered pipeline declaration without padding.",
            )
        elif not _is_canonical_sha256(preprocessing_pipeline):
            add(
                "PREPROCESSING_PIPELINE_HASH_INVALID",
                "error",
                "The guided preprocessing-pipeline commitment is not a canonical SHA-256 digest.",
                "Bind preprocessing to a reviewed registered-pipeline JSON artifact by recording its lowercase 64-character SHA-256 digest.",
            )
        if not preprocessing_gate_id:
            add(
                "PREPROCESSING_CONFORMANCE_GATE_MISSING",
                "error",
                "A hash-bound preprocessing pipeline lacks a dedicated conformance gate.",
                "Name the exact required quality gate that will cite a byte-verified preprocessing-conformance record before analysis can become evidence.",
            )
    if preprocessing_gate_id and preprocessing_gate_id != preprocessing_gate_id.strip():
        add(
            "PREPROCESSING_CONFORMANCE_GATE_NONCANONICAL",
            "error",
            "The preprocessing-conformance gate ID contains surrounding whitespace.",
            "Use an exact unpadded gate ID so run intake can bind preprocessing adherence to one required quality gate.",
        )
    if not brief.get("independent_unit") or "repeated_measures" not in brief:
        add("INDEPENDENCE_UNRESOLVED", "warning", "The independent sampling unit and repeated-observation structure are not fully declared.", "Name the independently sampled participant, pot, site, or other unit; state whether each contributes repeated observations. Count independent units separately from rows.")
    if any(
        isinstance(brief.get(field), str)
        and brief[field]
        and brief[field] != brief[field].strip()
        for field in ("independent_unit", "unit_analysis_plan")
    ):
        add(
            "DEPENDENCE_COMMITMENT_NONCANONICAL", "error",
            "The dependence or unit-analysis commitment contains surrounding whitespace.",
            "Use exact unpadded independent-unit and unit-analysis-plan text before protocol and data-dictionary drafts preserve row-to-unit semantics.",
        )
    if not brief.get("analysis_design"):
        add("ANALYSIS_DESIGN_UNRESOLVED", "warning", "The analysis does not declare how observations depend on one another.", "Choose an independent, paired, clustered, repeated-measure, or descriptive design before selecting an estimator.")
    if brief.get("repeated_measures") and brief.get("analysis_design") == "independent_groups":
        add("PSEUDOREPLICATION_RISK", "error", "Repeated observations from the same unit are assigned an independent-groups analysis.", "Use a justified paired, repeated-measure, or hierarchical analysis, or preregister unit-level aggregation. Do not count repeated rows as independent samples.")
    if (brief.get("repeated_measures") or brief.get("analysis_design") in {"paired", "clustered", "repeated_measures"}) and not brief.get("unit_analysis_plan"):
        add("UNIT_ANALYSIS_PLAN_MISSING", "error", "Dependent observations lack a frozen row-to-unit estimand rule.", "Define pairing, cluster handling, within-unit aggregation, time structure, and which unit contributes one independent estimate.")
    if brief.get("analysis_design") in {"clustered", "repeated_measures"}:
        add("DEPENDENCE_METHOD_REVIEW", "warning", "The bundled two-group estimators do not implement this dependence structure.", "Obtain a reviewed add-on or specify and review an appropriate unit-level analysis; do not substitute an independent-groups estimator.")
    graph_assignment = (
        brief.get("causal_identification", {}).get("assignment_type")
        if isinstance(brief.get("causal_identification"), dict) else ""
    )
    assignment_type = brief.get("assignment_type", "") or graph_assignment
    if brief.get("assignment_type") and graph_assignment and brief["assignment_type"] != graph_assignment:
        add("CAUSAL_ASSIGNMENT_CONFLICT", "error", "The design brief and causal-identification record disagree about assignment.", "Use one explicit assignment classification throughout the design; do not describe observational exposure as randomized.")
    if study_type == "causal":
        if not assignment_type:
            add("CAUSAL_ASSIGNMENT_TYPE_UNRESOLVED", "warning", "Causal intent is declared without classifying exposure assignment as randomized or observational.", "State the actual assignment mechanism; causal intent alone does not make a study experimental.")
        if assignment_type == "randomized" and not str(brief.get("intervention", "")).strip():
            add("CAUSAL_INTERVENTION_MISSING", "error", "A randomized causal study does not specify its intervention.", "Define what is assigned, by whom, and when.")
        if assignment_type == "observational" and not str(brief.get("exposure_definition") or brief.get("intervention", "")).strip():
            add("CAUSAL_EXPOSURE_MISSING", "error", "An observational causal study does not define the observed exposure.", "Define how exposure is observed and temporally ordered; do not describe observation as intervention assignment.")
        if not str(brief.get("comparison", "")).strip():
            add("CAUSAL_COMPARISON_MISSING", "error", "A causal study has no comparison condition.", "Add a control, crossover, or justified comparison group.")
        if assignment_type == "randomized" and not str(brief.get("randomization_plan", "")).strip():
            add("CAUSAL_ASSIGNMENT_UNRESOLVED", "warning", "Assignment is not randomized or otherwise justified.", "Specify randomization, matching, or the identification assumptions and likely confounders.")
    if not str(brief.get("outcome_unit", "")).strip():
        add("MEASUREMENT_UNIT_MISSING", "error", "The outcome has no stated unit or scale.", "Name the instrument, scale, units, and direction of better/worse values.")
    scale = brief.get("outcome_scale", "")
    admissible = _text_list(brief, "outcome_admissible_values")
    missing_codes = _text_list(brief, "outcome_missing_value_codes")
    valid_min = brief.get("outcome_valid_min")
    valid_max = brief.get("outcome_valid_max")
    if len({item.casefold() for item in missing_codes}) != len(missing_codes):
        add("MISSING_VALUE_CODE_DUPLICATE", "error", "The primary outcome repeats a missing-value code.", "Give each missing state one unique code and keep missingness distinct from observed outcome values.")
    if {item.casefold() for item in admissible} & {item.casefold() for item in missing_codes}:
        add("MISSING_VALUE_DOMAIN_COLLISION", "error", "A missing-value code is also declared as an observed outcome value.", "Use disjoint encodings so missing observations cannot be analyzed as measurements.")
    if not scale:
        add("MEASUREMENT_SCALE_MISSING", "warning", "The primary outcome has no typed measurement scale.", "Classify it as binary, nominal, ordinal, interval, ratio, count, or time_to_event before selecting an estimator.")
    elif scale in {"binary", "nominal", "ordinal"}:
        if len(admissible) < 2 or len({item.casefold() for item in admissible}) != len(admissible):
            add("MEASUREMENT_DOMAIN_INCOMPLETE", "error", "The categorical outcome lacks a unique, explicit admissible-value domain.", "List every permitted category exactly once; a binary outcome must have exactly two values.")
        elif scale == "binary" and len(admissible) != 2:
            add("BINARY_DOMAIN_INVALID", "error", "A binary outcome does not have exactly two admissible values.", "Name the two possible recorded values explicitly.")
        if valid_min is not None or valid_max is not None:
            add("MEASUREMENT_DOMAIN_CONFLICT", "error", "A categorical outcome declares numeric range bounds.", "Use admissible values for categorical scales; do not imply numeric distance with range bounds.")
    elif admissible:
        add("MEASUREMENT_DOMAIN_CONFLICT", "error", "A numeric outcome declares categorical admissible values.", "Use valid numeric bounds for numeric scales, or choose a categorical scale.")
    if valid_min is not None and valid_max is not None and float(valid_min) >= float(valid_max):
        add("MEASUREMENT_RANGE_INVALID", "error", "The primary outcome's valid minimum is not below its valid maximum.", "Record scientifically justified bounds with minimum strictly below maximum.")
    if scale in {"ratio", "count", "time_to_event"} and valid_min is not None and float(valid_min) < 0:
        add(
            "MEASUREMENT_RANGE_INVALID",
            "error",
            f"A {scale} outcome permits negative values.",
            "Use a non-negative lower bound for ratio, count, and time-to-event measurements.",
        )
    if scale == "count" and any(
        value is not None and not float(value).is_integer()
        for value in (valid_min, valid_max)
    ):
        add(
            "COUNT_RANGE_INVALID",
            "error",
            "A count outcome declares fractional validity bounds.",
            "Use integer bounds for count data so continuous quantities are not analyzed as event counts.",
        )
    family = brief.get("primary_analysis_family", "")
    if not family:
        add("ANALYSIS_FAMILY_UNRESOLVED", "warning", "No structured primary analysis family is selected.", "Choose a design- and scale-compatible analysis family; free-text analysis prose alone is not executable.")
    elif family in {"mean_difference", "paired_mean_difference", "adjusted_linear_effect"} and scale not in {"binary", "interval", "ratio", "count"}:
        add("ANALYSIS_SCALE_INCOMPATIBLE", "error", "The selected mean or linear analysis is incompatible with the declared primary-outcome scale.", "Choose a scale-compatible estimator or obtain review for a typed custom method; do not encode categories as arbitrary numbers.")
    if family == "mean_difference" and brief.get("analysis_design") not in {"", "independent_groups"}:
        add("ANALYSIS_DESIGN_FAMILY_CONFLICT", "error", "An independent mean-difference family conflicts with the declared dependence design.", "Select an analysis family that preserves pairing, clustering, or repeated observations.")
    if family == "paired_mean_difference" and brief.get("analysis_design") != "paired":
        add("ANALYSIS_DESIGN_FAMILY_CONFLICT", "error", "A paired mean-difference family requires a paired analysis design.", "Declare paired observations and their pairing rule, or choose another estimator family.")
    if not str(brief.get("measurement_validity", "")).strip():
        add("MEASUREMENT_VALIDITY_UNRESOLVED", "warning", "No validity evidence is named for the outcome measurement.", "State how the measurement can be checked against a reference, blind sample, or known result.")
    validity_checks = brief.get("measurement_validity_checks", [])
    if not validity_checks:
        add(
            "MEASUREMENT_VALIDITY_PLAN_INCOMPLETE",
            "error" if study_type in {"causal", "correlational"} else "warning",
            "The primary measurement has no structured prospective validity check.",
            "Define at least one validity claim, evidence type, assessment procedure, acceptance criterion, failure response, and dedicated required gate before collection.",
        )
    else:
        check_ids = [item["check_id"] for item in validity_checks]
        gate_ids = [item["assessment_gate_id"] for item in validity_checks]
        if any(
            item[field] != item[field].strip()
            for item in validity_checks
            for field in _VALIDITY_CHECK_FIELDS
        ):
            add(
                "MEASUREMENT_VALIDITY_CHECK_NONCANONICAL",
                "error",
                "Primary measurement validity checks contain text or gate handles with surrounding whitespace.",
                "Use exact unpadded check IDs, evidence types, validity claims, assessment procedures, acceptance criteria, failure responses, and gate IDs before review.",
            )
        if len(set(check_ids)) != len(check_ids):
            add("MEASUREMENT_VALIDITY_CHECK_DUPLICATE", "error", "Primary measurement validity check IDs are not unique.", "Give each prospective validity check one stable unique ID.")
        if len(set(gate_ids)) != len(gate_ids):
            add("MEASUREMENT_VALIDITY_GATE_DUPLICATE", "error", "Primary measurement validity checks reuse an assessment gate.", "Use one dedicated gate for each distinct validity assessment so evidence cannot satisfy multiple checks ambiguously.")
    measurement_commitment_fields = (
        "outcome_data_column",
        "measurement_observable",
        "measurement_input_condition", "measurement_parameter_values",
        "measurement_evaluation_point", "measurement_convention",
        "measurement_aggregation", "measurement_tolerance",
        "measurement_expected_behavior", "measurement_temporal_role",
    )
    missing_measurement_commitments = [
        field for field in measurement_commitment_fields
        if brief.get(field) in (None, "", {})
    ]
    if missing_measurement_commitments:
        add(
            "MEASUREMENT_CONTRACT_INCOMPLETE",
            "error" if study_type in {"causal", "correlational"} else "warning",
            "The primary measurement lacks a complete reproducible measurement contract.",
            "Separately specify the exact observable, input condition, fixed parameter bindings, evaluation point, coding convention, aggregation, tolerance, expected behavior, and temporal role before collection.",
        )
    unit_id_column_value = brief.get("unit_id_column", "")
    unit_id_column = unit_id_column_value if isinstance(unit_id_column_value, str) else ""
    if unit_id_column and unit_id_column != unit_id_column.strip():
        add(
            "UNIT_ID_COLUMN_NONCANONICAL",
            "error",
            "The guided unit-identity column has surrounding whitespace.",
            "Name the exact stable unit identifier column without padding so collection, protocol, and executable analysis share the same handle.",
        )
    if brief.get("independent_unit") and not unit_id_column:
        add(
            "UNIT_ID_COLUMN_UNRESOLVED",
            "error" if study_type in {"causal", "correlational"} else "warning",
            "The independently sampled unit has no explicit dataset identifier column.",
            "Name the exact stable unit-identity column so collection, dependence handling, and executable analysis can bind the same independent units.",
        )
    if study_type == "causal" and brief.get("measurement_temporal_role") not in {"", "post_exposure"}:
        add("CAUSAL_OUTCOME_TIMING_INVALID", "error", "The causal primary outcome is not declared post-exposure.", "Use post_exposure for the outcome and separately define pre-exposure covariates and the at-exposure assignment or exposure measurement.")
    executable_columns = [
        value for value in [
            brief.get("outcome_data_column", ""),
            *[item["data_column"] for item in brief.get("secondary_measurements", [])],
            *[item["data_column"] for item in brief.get("control_measurements", [])],
            *[
                item["data_column"] for item in brief.get("causal_measurements", [])
                if item["role"] == "covariate"
            ],
        ] if value
    ]
    normalized_columns = [value.casefold() for value in executable_columns]
    if len(set(normalized_columns)) != len(normalized_columns):
        add("MEASUREMENT_COLUMN_COLLISION", "error", "Two executable measurements use the same dataset column.", "Give the primary outcome, every secondary outcome, and every column-backed control a distinct exact data column.")
    reserved_columns = {"observation_id", "unit_id", "condition", "captured_at"}
    if unit_id_column:
        reserved_columns.add(unit_id_column.casefold())
    if group_data_column:
        reserved_columns.add(group_data_column.casefold())
    collisions = sorted(
        value for value in executable_columns if value.casefold() in reserved_columns
    )
    if collisions:
        add("MEASUREMENT_COLUMN_RESERVED", "error", "Measurement columns collide with proposed identity, assignment, or acquisition fields: " + ", ".join(collisions), "Use distinct measurement columns so outcome values cannot overwrite row identity, unit identity, condition, or capture time.")
    structural_columns = [
        value for value in ["observation_id", unit_id_column, group_data_column, "captured_at"]
        if value
    ]
    if len({value.casefold() for value in structural_columns}) != len(structural_columns):
        add(
            "STRUCTURAL_COLUMN_COLLISION", "error",
            "Identity, comparison, and acquisition roles do not use distinct dataset columns.",
            "Give row identity, independent-unit identity, comparison or exposure, and acquisition time separate exact columns.",
        )
    if not str(brief.get("calibration_plan", "")).strip():
        add("CALIBRATION_UNRESOLVED", "warning", "No calibration or measurement-quality plan is recorded.", "Specify calibration, synchronization, missing-channel, or data-quality checks before collection.")
    if not _text_list(brief, "controls"):
        add("CONTROL_FAMILY_MISSING", "warning", "No positive, negative, sham, replay, apparatus-only, or other control is planned.", "Choose the control family that could reveal a misleading measurement or procedure.")
    controls = _text_list(brief, "controls")
    normalized_controls = [item.strip().casefold() for item in controls]
    if len(set(normalized_controls)) != len(normalized_controls):
        add("CONTROL_DUPLICATE", "error", "Controls contain duplicate labels.", "Give each control one stable, unique name before assigning definitions, measurements, or gates.")
    if not _text_list(brief, "confounds"):
        add("CONFOUNDS_UNASSESSED", "warning", "No plausible confounders are recorded.", "List competing explanations and how each will be measured, blocked, or bounded.")
    confounds = _text_list(brief, "confounds")
    normalized_confounds = [item.strip().casefold() for item in confounds]
    if len(set(normalized_confounds)) != len(normalized_confounds):
        add("CONFOUND_DUPLICATE", "error", "Confounds contain duplicate labels.", "Give each competing explanation one stable, unique name so it can be measured, blocked, bounded, or represented in the causal graph.")
    if not str(brief.get("analysis_commitment", "")).strip():
        add("ANALYSIS_COMMITMENT_MISSING", "warning", "The analysis and estimand are not committed before collection.", "Specify the primary comparison, uncertainty method, exclusions, and multiplicity handling.")
    if not str(brief.get("stopping_rule", "")).strip():
        add("STOPPING_RULE_MISSING", "warning", "No sample-size, precision, or stopping rule is declared.", "Set a sample-size, precision target, or fixed stopping condition before inspecting results.")
    if not brief.get("sample_size_justification", "").strip():
        add("SAMPLE_SIZE_JUSTIFICATION_MISSING", "warning", "The planned information amount has no separate justification.", "State the precision or power target and assumptions, or explain the feasibility limit and resulting inferential limitations. Count independent units, not repeated rows; a stopping count alone is not a justification.")
    elif brief["sample_size_justification"] != brief["sample_size_justification"].strip():
        add(
            "SAMPLE_SIZE_JUSTIFICATION_NONCANONICAL", "error",
            "The sample-size justification contains surrounding whitespace.",
            "Use exact unpadded planning rationale before it enters review artifacts or the protocol planning commitment.",
        )
    planning_receipt = None
    if brief.get("sample_size_plan"):
        try:
            planning_receipt = build_sample_size_planning_receipt(
                brief["sample_size_plan"]
            )
        except ValidationError as exc:
            add(
                "SAMPLE_SIZE_PLAN_INVALID", "error",
                "The supplied sample-size plan cannot be deterministically reproduced: " + str(exc),
                "Correct the explicit planning assumptions and regenerate the receipt; do not transcribe or hand-edit a favorable sample size.",
            )
        if planning_receipt is not None:
            strategy = planning_receipt["strategy"]
            calculation = planning_receipt["calculation"]
            if planning_receipt.get("target_hypothesis_id"):
                add(
                    "SAMPLE_SIZE_TARGET_PREMATURE", "error",
                    "A guided review plan claims canonical target IDs before this scaffold creates and reviews them.",
                    "Use an untargeted planning receipt during guided review; bind the actual canonical hypothesis, measurement, and unit only when constructing the executable protocol.",
                )
            if study_type in {"causal", "correlational"} and strategy == "power":
                add(
                    "SAMPLE_SIZE_DECISION_MISMATCH", "error",
                    "Conventional difference-test power does not power the scaffold's confidence-bound practical-significance conclusion.",
                    "Use practical_power for a directional practical-significance decision, equivalence_power for equivalence, or a precision target whose interpretation is explicit.",
                )
            if strategy == "equivalence_power" and brief.get("expected_effect_direction") != "equivalence":
                add("SAMPLE_SIZE_DECISION_MISMATCH", "error", "An equivalence-power plan is attached to a non-equivalence hypothesis.", "Align the hypothesis, interval-within-margin rule, and equivalence-power strategy prospectively.")
            if strategy == "practical_power" and brief.get("expected_effect_direction") in {"", "equivalence"}:
                add("SAMPLE_SIZE_DECISION_MISMATCH", "error", "A practical-significance power plan lacks a compatible directional hypothesis.", "Register positive, negative, or two_sided direction and preserve the same alternative in the plan.")
            if strategy == "practical_power" and brief.get("expected_effect_direction") not in {"", "equivalence"} and planning_receipt["calculation"]["alternative"] != brief.get("expected_effect_direction"):
                add("SAMPLE_SIZE_DECISION_MISMATCH", "error", "The practical-power alternative does not match the registered hypothesis direction.", "Use the same signed direction in the hypothesis, contrast, and planning calculation.")
            if brief.get("analysis_design") and brief["analysis_design"] != calculation["study_design"]:
                add("SAMPLE_SIZE_DESIGN_MISMATCH", "error", "The sample-size calculation uses a different dependence design from the guided analysis.", "Use a planner that implements the declared analysis design; do not apply independent-group counts to paired, clustered, or repeated observations.")
            if (
                brief.get("minimum_analyzable_units") is not None
                and int(brief["minimum_analyzable_units"])
                != calculation["analyzable_n_per_group"]
            ):
                add("SAMPLE_SIZE_INFORMATION_MISMATCH", "error", "The frozen minimum analyzable count does not equal the recomputed per-group planning target.", "Use the plan's analyzable count for the smaller arm, or revise and justify the planning assumptions before collection.")
            if (
                brief.get("maximum_excluded_fraction") is not None
                and calculation["anticipated_attrition_fraction"]
                > float(brief["maximum_excluded_fraction"])
            ):
                add("SAMPLE_SIZE_ATTRITION_MISMATCH", "error", "The plan assumes more attrition than the analysis contract would permit.", "Align anticipated attrition with the frozen exclusion ceiling; do not plan to continue after the analysis must stop.")
            if "alpha" in calculation and brief.get("multiplicity_alpha") is not None and calculation["alpha"] != float(brief["multiplicity_alpha"]):
                add("SAMPLE_SIZE_ALPHA_MISMATCH", "error", "The planning alpha differs from the confirmatory family alpha.", "Use the exact frozen decision threshold in the planning calculation.")
            if "confidence_level" in calculation and brief.get("confidence_level") is not None and calculation["confidence_level"] != float(brief["confidence_level"]):
                add("SAMPLE_SIZE_CONFIDENCE_MISMATCH", "error", "The planning interval level differs from the registered analysis interval level.", "Power or size the exact interval used by the conclusion rule.")
            threshold = brief.get("smallest_effect_size_of_interest")
            planned_threshold = (
                calculation.get("equivalence_margin")
                if strategy == "equivalence_power"
                else calculation.get("smallest_effect_size_of_interest")
            )
            if threshold is not None and planned_threshold is not None and float(threshold) != planned_threshold:
                add("SAMPLE_SIZE_EFFECT_THRESHOLD_MISMATCH", "error", "The planning effect threshold differs from the conclusion contract.", "Use one frozen practical threshold or equivalence margin throughout planning and adjudication.")
            if strategy in {"practical_power", "equivalence_power"} and brief.get("multiplicity_method") not in {"", "single_test"}:
                add("SAMPLE_SIZE_MULTIPLICITY_MISMATCH", "error", "The direct power calculation does not power the declared multiplicity-adjusted family decision.", "Use single_test for this direct planner or obtain a reviewed family-wise planning method.")
    if "minimum_analyzable_units" not in brief:
        add("MINIMUM_ANALYZABLE_UNITS_MISSING", "warning", "No minimum analyzable independent-unit count is declared.", "Set the smallest arm count or complete-pair count below which the frozen analysis must stop rather than silently continue.")
    if "maximum_excluded_fraction" not in brief:
        add("MAXIMUM_EXCLUDED_FRACTION_MISSING", "warning", "No maximum tolerable exclusion fraction is declared.", "Set the largest preregistered fraction of submitted records that may be excluded before analysis must stop for review.")
    if "maximum_group_excluded_fraction_difference" not in brief:
        add(
            "MAXIMUM_GROUP_EXCLUSION_DIFFERENCE_MISSING", "warning",
            "No maximum tolerable between-group difference in exclusion fractions is declared.",
            "Set the largest preregistered absolute difference in group-specific exclusion rates before differential attrition must stop the analysis for review.",
        )
    missingness_fields = (
        "missingness_assumption", "missingness_assessment_plan",
        "missingness_failure_response", "missingness_assessment_kind",
        "missingness_assessment_gate_id",
    )
    if any(not str(brief.get(field, "")).strip() for field in missingness_fields):
        add(
            "MISSINGNESS_ASSESSMENT_INCOMPLETE", "warning",
            "The complete-case analysis has no complete prospective missingness assessment contract.",
            "State the missingness assumption, assessment plan and kind, failure response, and a dedicated required gate before freezing analysis.",
        )
    elif any(
        brief[field] != brief[field].strip()
        for field in missingness_fields
    ):
        add(
            "MISSINGNESS_ASSESSMENT_NONCANONICAL", "error",
            "The missingness assessment contract contains text or a gate handle with surrounding whitespace.",
            "Use exact unpadded missingness assumptions, assessment plans, failure responses, kind labels, and gate IDs before review.",
        )
    if "human_participants" not in brief:
        add("HUMAN_SCOPE_UNRESOLVED", "error", "It is unknown whether this study involves people or data about people.", "Explicitly assess human-participant and human-data involvement; an omitted answer is not clearance.")
    if brief.get("human_participants"):
        human_plan_fields = (
            ("consent_plan", "HUMAN_CONSENT_MISSING", "consent and withdrawal"),
            ("privacy_plan", "HUMAN_PRIVACY_MISSING", "privacy and access"),
            ("withdrawal_plan", "HUMAN_WITHDRAWAL_MISSING", "withdrawal handling"),
            ("retention_deletion_plan", "HUMAN_RETENTION_MISSING", "retention and deletion"),
            ("risk_description", "HUMAN_RISK_UNASSESSED", "physical and psychological risks"),
            ("vulnerable_population_plan", "HUMAN_VULNERABILITY_PLAN_MISSING", "vulnerable-population eligibility and protections"),
            ("data_security_plan", "HUMAN_DATA_SECURITY_MISSING", "encryption, access control, and security response"),
            ("incidental_findings_plan", "HUMAN_INCIDENTAL_FINDINGS_MISSING", "incidental and safety-relevant findings"),
        )
        for field, code, label in human_plan_fields:
            if not str(brief.get(field, "")).strip():
                add(code, "error", f"Human-participant work lacks a {label} plan.", f"Document {label} before the study can proceed.")
        if any(
            isinstance(brief.get(field), str)
            and brief[field]
            and brief[field] != brief[field].strip()
            for field, _, _ in human_plan_fields
        ):
            add(
                "HUMAN_SAFEGUARD_NONCANONICAL", "error",
                "Human-participant safeguard plans contain text with surrounding whitespace.",
                "Use exact unpadded consent, withdrawal, privacy, retention, risk, vulnerability, security, and incidental-finding plans before review.",
            )
        if not brief.get("independent_review", False):
            add("HUMAN_REVIEW_REQUIRED", "error", "Human-participant work is blocked pending qualified independent review.", "Obtain and record the applicable ethics, institutional, or qualified professional review.")
        elif not str(brief.get("independent_review_receipt", "")).strip():
            add("HUMAN_REVIEW_RECEIPT_MISSING", "error", "Qualified independent review is asserted without a review receipt.", "Record the review body's stable receipt or approval identifier before the study can proceed.")
        else:
            review_fields = (
                ("independent_review_decision", "HUMAN_REVIEW_DECISION_MISSING", "decision status"),
                ("independent_reviewer_role", "HUMAN_REVIEWER_ROLE_MISSING", "reviewer role"),
                ("independent_reviewed_at", "HUMAN_REVIEW_TIME_MISSING", "decision timestamp"),
                ("independent_review_scope", "HUMAN_REVIEW_SCOPE_MISSING", "review scope"),
                ("independent_review_artifact_locator", "HUMAN_REVIEW_ARTIFACT_LOCATOR_MISSING", "review artifact locator"),
                ("independent_review_artifact_sha256", "HUMAN_REVIEW_DIGEST_MISSING", "review artifact SHA-256"),
            )
            for field, code, label in review_fields:
                if not str(brief.get(field, "")).strip():
                    add(code, "error", f"Independent review lacks a {label}.", f"Record the {label} from the review artifact before the study can proceed.")
            if (
                brief["independent_review_receipt"] != brief["independent_review_receipt"].strip()
                or any(
                    isinstance(brief.get(field), str)
                    and brief[field]
                    and brief[field] != brief[field].strip()
                    for field, _, _ in review_fields
                )
                or has_noncanonical_text_items(
                    _independent_review_conditions(brief)
                )
            ):
                add(
                    "HUMAN_REVIEW_NONCANONICAL", "error",
                    "Independent-review receipt, decision, reviewer, timestamp, scope, artifact handle, digest, or conditions contain surrounding whitespace.",
                    "Use exact unpadded human-review fields before they can enter the protocol commitment or local artifact verification flow.",
                )
            decision = brief.get("independent_review_decision", "")
            if decision and decision not in {"approved", "approved_with_conditions"}:
                add("HUMAN_REVIEW_NOT_APPROVED", "error", "Independent review does not record an approval decision.", "Do not proceed until qualified review records approval or approval with explicit conditions.")
            digest = brief.get("independent_review_artifact_sha256", "")
            if digest and not _is_canonical_sha256(digest):
                add(
                    "HUMAN_REVIEW_DIGEST_INVALID", "error",
                    "Independent review artifact SHA-256 is not a canonical lowercase digest.",
                    "Record the exact 64-character lowercase hexadecimal SHA-256 of the review artifact before staging local-byte verification.",
                )
            if decision == "approved_with_conditions" and not _independent_review_conditions(brief):
                add("HUMAN_REVIEW_CONDITIONS_MISSING", "error", "Conditional approval does not record its conditions.", "Record every condition so the frozen protocol preserves the obligations.")
    dedicated_gate_ids = [
        *[item["evaluation_gate_id"] for item in brief.get("control_definitions", [])],
        *[item["assessment_gate_id"] for item in validity_checks],
    ]
    if isinstance(brief.get("causal_identification"), dict):
        dedicated_gate_ids.extend(
            item["assessment_gate_id"]
            for item in brief.get("causal_identification", {}).get("assumptions", [])
        )
    if str(brief.get("missingness_assessment_gate_id", "")).strip():
        dedicated_gate_ids.append(brief["missingness_assessment_gate_id"])
    if isinstance(brief.get("canary_target_plan"), dict):
        dedicated_gate_ids.append(brief["canary_target_plan"]["assessment_gate_id"])
    if isinstance(brief.get("hypothesis_reactivity_plan"), dict):
        dedicated_gate_ids.append(
            brief["hypothesis_reactivity_plan"]["assessment_gate_id"]
        )
    if str(brief.get("preprocessing_conformance_gate_id", "")).strip():
        dedicated_gate_ids.append(brief["preprocessing_conformance_gate_id"])
    if len(set(dedicated_gate_ids)) != len(dedicated_gate_ids):
        add(
            "QUALITY_GATE_PURPOSE_COLLISION", "error",
            "A quality gate is reused across control, measurement-validity, causal-assumption, missingness, canary-target, or preprocessing-conformance purposes.",
            "Use dedicated gate IDs so one artifact-bound assessment cannot silently satisfy scientifically different obligations.",
        )
    return findings


def scaffold_design(brief: dict[str, Any]) -> dict[str, Any]:
    findings = audit_design(brief)
    blockers = [item for item in findings if item.severity == "error"]
    planning_receipt = None
    if brief.get("sample_size_plan"):
        try:
            planning_receipt = build_sample_size_planning_receipt(
                brief["sample_size_plan"]
            )
        except ValidationError:
            pass
    study_type = brief.get("study_type", "exploratory")
    controls = _text_list(brief, "controls")
    confounds = _text_list(brief, "confounds")
    manipulated_factors = _text_list(brief, "manipulated_factors")
    sensor_requirements = _text_list(brief, "sensor_requirements")
    control_windows = _text_list(brief, "control_windows")
    secondary_outcomes = _text_list(brief, "secondary_outcomes")
    ambiguity_questions = _ambiguity_questions(brief)
    claim_boundaries = _claim_boundaries(brief)
    controlled_acceptance_scenarios = _controlled_acceptance_scenarios(brief)
    available_data_sources, unavailable_data, data_access_constraints = (
        _data_availability_boundary(brief)
    )
    data_access_owner = brief.get("data_access_owner") or "[REVIEW REQUIRED]"
    data_provenance_plan = brief.get(
        "data_provenance_plan"
    ) or "[REVIEW REQUIRED] bind source bytes, custody, and collection context"
    ethical_constraints = _text_list(brief, "ethical_constraints")
    ethical_safeguards_plan = brief.get(
        "ethical_safeguards_plan"
    ) or "[REVIEW REQUIRED] define review, monitoring, and stop-condition safeguards"
    canary_target_plan = (
        dict(brief["canary_target_plan"])
        if isinstance(brief.get("canary_target_plan"), dict)
        else None
    )
    hypothesis_reactivity_plan = (
        dict(brief["hypothesis_reactivity_plan"])
        if isinstance(brief.get("hypothesis_reactivity_plan"), dict)
        else None
    )
    primary_alias_proxy_commitment = _optional_alias_proxy_commitment(
        brief.get("alias_proxy_commitment"),
        field="alias_proxy_commitment",
        expected_labels=_primary_alias_expected_labels(brief),
    )
    alias_proxy_commitments: list[dict[str, Any]] = []
    if primary_alias_proxy_commitment is not None:
        alias_proxy_commitments.append(
            {
                "measurement_id": "[REVIEW REQUIRED] stable primary measurement ID",
                "role": "primary",
                "registered_target": brief["outcome"],
                "commitment": primary_alias_proxy_commitment,
            }
        )
    for role, target_key, measurements in (
        ("secondary", "outcome", brief.get("secondary_measurements", [])),
        ("control", "control", brief.get("control_measurements", [])),
        ("causal", "variable", brief.get("causal_measurements", [])),
    ):
        for index, item in enumerate(measurements, start=1):
            commitment = item.get("alias_proxy_commitment")
            if commitment is None:
                continue
            alias_proxy_commitments.append(
                {
                    "measurement_id": f"[REVIEW REQUIRED] stable {role} measurement ID {index}",
                    "role": role,
                    "registered_target": item[target_key],
                    "commitment": dict(commitment),
                }
            )
    causal_audit = (
        audit_causal_identification(brief["causal_identification"])
        if isinstance(brief.get("causal_identification"), dict) else None
    )
    hypothesis = {
        "statement": f"[REVIEW REQUIRED] {brief['question']}",
        "generated_by": "guided_experiment_scaffold",
        "scope": f"Population: {brief.get('population', 'unresolved')}; setting: {brief.get('setting', 'unresolved')}",
        "observable_prediction": brief.get("observable_prediction") or "[REVIEW REQUIRED] State the observation that would discriminate this hypothesis from alternatives.",
        "null_model": brief.get("null_model") or "[REVIEW REQUIRED] State the no-effect or competing explanation.",
        "competing_models": confounds or ["[REVIEW REQUIRED] Add measurement, selection, and confounding alternatives."],
        "falsification_conditions": _text_list(brief, "falsification_conditions") or ["[REVIEW REQUIRED] Define a result that would weaken this hypothesis."],
        "primary_estimand": brief.get("primary_estimand") or "[REVIEW REQUIRED] define the primary estimand",
        "expected_effect_direction": brief.get("expected_effect_direction") or "[REVIEW REQUIRED] define positive, negative, two_sided, or equivalence",
        "contrast_definition": brief.get("contrast_definition") or "[REVIEW REQUIRED] define the signed comparison order",
        "contrast_groups": _text_list(brief, "contrast_groups") or [
            "[REVIEW REQUIRED] first contrast level",
            "[REVIEW REQUIRED] second contrast level",
        ],
    }
    inquiry = {
        "status": "review_required",
        "title": brief["title"],
        "initial_statement": brief["question"],
        **inquiry_decision_commitments(brief),
        "notice": (
            "This inquiry draft records the practical decision boundary for "
            "review. It is not evidence, approval, or a claim that the listed "
            "threshold is scientifically adequate."
        ),
    }
    planned_outcomes = [brief["outcome"], *secondary_outcomes]
    planned_confirmatory = _text_list(brief, "confirmatory_outcomes")
    analysis_steps = []
    source_steps = []
    if secondary_outcomes:
        analysis_steps.append({
            "step_id": "primary-estimate",
            "role": "primary_estimate",
            "method": "[REVIEW REQUIRED] choose a design-compatible estimator",
            "specification_sha256": "[REVIEW REQUIRED] hash the exact estimation specification",
            "implementation_sha256": "[REVIEW REQUIRED] hash the exact implementation",
            "depends_on": [],
            "hypothesis_id": "[REVIEW REQUIRED] bind a reviewed hypothesis",
            "outcome": brief["outcome"],
            "measurement_id": "[REVIEW REQUIRED] bind the typed primary measurement",
            "p_value_path": "",
            "family_id": "",
            "family_members": [],
            "alpha": None,
        })
        for index, outcome in enumerate(planned_outcomes, start=1):
            step_id = f"outcome-test-{index}"
            confirmatory_test = outcome in planned_confirmatory
            if confirmatory_test:
                source_steps.append((step_id, outcome))
            analysis_steps.append({
                "step_id": step_id,
                "role": "confirmatory_test" if confirmatory_test else "exploratory_analysis",
                "method": "[REVIEW REQUIRED] choose a design-compatible test or analysis",
                "specification_sha256": "[REVIEW REQUIRED] hash the exact step specification",
                "implementation_sha256": "[REVIEW REQUIRED] hash the exact implementation",
                "depends_on": [],
                "hypothesis_id": "[REVIEW REQUIRED] bind a reviewed hypothesis",
                "outcome": outcome,
                "measurement_id": "[REVIEW REQUIRED] bind the typed measurement",
                "p_value_path": "[REVIEW REQUIRED] absolute JSON Pointer to the raw p-value" if confirmatory_test else "",
                "family_id": "",
                "family_members": [],
                "alpha": None,
            })
        if brief.get("multiplicity_method") == "holm":
            confirmatory_sources = [
                (step_id, outcome) for step_id, outcome in source_steps
                if outcome in planned_confirmatory
            ]
            analysis_steps.append({
                "step_id": "confirmatory-holm",
                "role": "multiplicity",
                "method": "holm_adjustment",
                "specification_sha256": "[REVIEW REQUIRED] hash the exact Holm specification",
                "implementation_sha256": "[REVIEW REQUIRED] hash the Holm implementation",
                "depends_on": [step_id for step_id, _ in confirmatory_sources],
                "hypothesis_id": "",
                "outcome": "",
                "measurement_id": "",
                "p_value_path": "",
                "family_id": "[REVIEW REQUIRED] stable confirmatory family ID",
                "family_members": [{
                    "member_id": f"{step_id}-p",
                    "source_step_id": step_id,
                    "hypothesis_id": "[REVIEW REQUIRED] bind a reviewed hypothesis",
                    "outcome": outcome,
                    "measurement_id": "[REVIEW REQUIRED] bind the typed measurement",
                } for step_id, outcome in confirmatory_sources],
                "alpha": brief.get("multiplicity_alpha"),
            })
    graph_assignment = (
        brief.get("causal_identification", {}).get("assignment_type")
        if isinstance(brief.get("causal_identification"), dict) else ""
    )
    assignment_conflict = bool(
        brief.get("assignment_type") and graph_assignment
        and brief["assignment_type"] != graph_assignment
    )
    assignment_type = brief.get("assignment_type", "") or graph_assignment
    analysis_contract = (
        _analysis_contract_draft(
            brief,
            study_type=study_type,
            assignment_type=assignment_type,
        )
        if study_type in {"causal", "correlational"}
        else None
    )
    protocol_kind = (
        "[REVIEW REQUIRED] resolve conflicting assignment classifications"
        if assignment_conflict
        else "experimental" if study_type == "causal" and assignment_type == "randomized"
        else "observational" if study_type != "causal" or assignment_type == "observational"
        else "[REVIEW REQUIRED] classify assignment before choosing protocol kind"
    )
    exposure_label = (
        brief.get("intervention") if assignment_type == "randomized"
        else brief.get("exposure_definition") or brief.get("intervention")
    )
    protocol = {
        "experiment_id": "[REVIEW REQUIRED] stable experiment ID",
        "title": brief["title"],
        "analysis_mode": "confirmatory" if study_type in {"causal", "correlational"} else "exploratory",
        "hypotheses_tested": ["[REVIEW REQUIRED] create and review hypothesis first"],
        "primary_outcome": brief["outcome"],
        "secondary_outcomes": secondary_outcomes,
        "confirmatory_outcomes": _text_list(brief, "confirmatory_outcomes"),
        "exploratory_outcomes": _text_list(brief, "exploratory_outcomes"),
        "multiplicity_method": brief.get("multiplicity_method", ""),
        "multiplicity_alpha": brief.get("multiplicity_alpha"),
        "analysis_steps": analysis_steps,
        "analysis_contract": analysis_contract,
        "conclusion_contract": ({
            "primary_hypothesis_id": "[REVIEW REQUIRED] bind the primary reviewed hypothesis",
            "decision_rule": (
                "adjusted_primary_rejection_and_interval_and_practical_significance"
                if brief.get("multiplicity_method") == "holm"
                else "interval_and_practical_significance"
            ),
            "smallest_effect_size_of_interest": brief.get(
                "smallest_effect_size_of_interest", 0.0
            ),
            "effect_scale": brief.get("effect_scale", "[REVIEW REQUIRED] effect scale"),
            "effect_unit": brief.get("outcome_unit", "[REVIEW REQUIRED] effect unit"),
            "population": brief.get("population", "[REVIEW REQUIRED] target population"),
            "setting": brief.get("setting", "[REVIEW REQUIRED] target setting"),
            "time_window": brief.get(
                "conclusion_time_window", "[REVIEW REQUIRED] outcome time window"
            ),
            "non_supporting_direction": brief.get(
                "non_supporting_direction", "inconclusive"
            ),
            "permitted_claim_level": (
                "causal_direction" if study_type == "causal"
                else "statistical_association"
            ),
            "higher_level_conclusions_unsupported": brief.get(
                "higher_level_conclusions_unsupported",
                ["[REVIEW REQUIRED] state conclusions this study cannot support"],
            ),
        } if study_type in {"causal", "correlational"} else None),
        "protocol_kind": protocol_kind,
        "causal_claim": study_type == "causal",
        "methodology": f"{study_type} study; assignment: {assignment_type or 'unresolved'}; {'intervention' if assignment_type == 'randomized' else 'exposure'}: {exposure_label or 'unresolved'}; comparison: {brief.get('comparison', 'unresolved')}",
        "manipulated_factors": manipulated_factors,
        "factorial_or_crossover_design": brief.get("factorial_or_crossover_design", False),
        "factor_interpretability_plan": brief.get("factor_interpretability_plan", ""),
        "canary_target_plan": canary_target_plan,
        "hypothesis_reactivity_plan": hypothesis_reactivity_plan,
        "group_data_column": brief.get("group_data_column", "[REVIEW REQUIRED] exact comparison or exposure column"),
        "controls": controls or ["[REVIEW REQUIRED] add a control family"],
        "sampling_unit": brief["unit_of_observation"],
        "sample_size_or_stopping_rule": brief.get("stopping_rule", "[REVIEW REQUIRED]"),
        "sample_size_plan": planning_receipt or {},
        "randomization_plan": brief.get("randomization_plan", "[REVIEW REQUIRED]"),
        "blinding_plan": brief.get("blinding_plan", "[REVIEW REQUIRED]"),
        "calibration_requirements": [brief.get("calibration_plan", "[REVIEW REQUIRED]")],
        "calibration_acceptance_criteria": [{
            "criterion_id": "[REVIEW REQUIRED] stable criterion ID",
            "calibration_id": "[REVIEW REQUIRED] matching custody calibration ID",
            "quantity": "[REVIEW REQUIRED] measured calibration quantity",
            "unit": brief.get("outcome_unit") or "[REVIEW REQUIRED] calibration unit",
            "rationale": "[REVIEW REQUIRED] justify the bound before collection",
            "lower_bound": None,
            "upper_bound": None,
            "component_bounds": [],
            "multivariate_policy": {},
        }],
        "measurement_custody_requirements": ["[REVIEW REQUIRED] name the custody gate that demonstrates the calibration requirement was met"],
        "preprocessing_pipeline": brief.get("preprocessing_pipeline", ""),
        "statistical_model": brief.get("analysis_commitment", "[REVIEW REQUIRED]"),
        "multiple_testing_policy": brief.get("multiple_testing_policy", "[REVIEW REQUIRED]"),
        "inclusion_rules": [brief.get("sampling_plan", "[REVIEW REQUIRED]")],
        "exclusion_rules": _text_list(brief, "exclusions"),
        "sensor_requirements": sensor_requirements or [
            "[REVIEW REQUIRED] specify required instruments, streams, or channels"
        ],
        "clock_accuracy_requirement": brief.get(
            "clock_accuracy_requirement",
            "[REVIEW REQUIRED] maximum tolerable timing uncertainty or synchronization rule",
        ),
        "control_windows": control_windows,
        "safety_constraints": (
            (["Human-participant review required before collection."] if brief.get("human_participants") else [])
            + (
                ethical_constraints
                if ethical_constraints
                else ["[REVIEW REQUIRED] assess applicable ethical and safety constraints."]
            )
        ),
        "human_subjects": brief.get("human_participants"),
        "consent_plan": brief.get("consent_plan", ""),
        "withdrawal_plan": brief.get("withdrawal_plan", ""),
        "privacy_plan": brief.get("privacy_plan", ""),
        "retention_deletion_plan": brief.get("retention_deletion_plan", ""),
        "risk_assessment": brief.get("risk_description", ""),
        "vulnerable_population_plan": brief.get("vulnerable_population_plan", ""),
        "data_security_plan": brief.get("data_security_plan", ""),
        "incidental_findings_plan": brief.get("incidental_findings_plan", ""),
        "independent_review_receipt": brief.get("independent_review_receipt", ""),
        "independent_review_decision": brief.get("independent_review_decision", ""),
        "independent_reviewer_role": brief.get("independent_reviewer_role", ""),
        "independent_reviewed_at": brief.get("independent_reviewed_at", ""),
        "independent_review_scope": brief.get("independent_review_scope", ""),
        "independent_review_artifact_locator": brief.get("independent_review_artifact_locator", ""),
        "independent_review_artifact_sha256": brief.get("independent_review_artifact_sha256", ""),
        "independent_review_conditions": _independent_review_conditions(brief),
    }

    def add_quality_requirements(gate_ids: list[str]) -> None:
        protocol["quality_requirements"] = list(dict.fromkeys(
            protocol.get("quality_requirements", []) + gate_ids
        ))

    if brief.get("independent_unit"):
        protocol["unit_id_column"] = brief.get(
            "unit_id_column", "[REVIEW REQUIRED] exact independent-unit ID column"
        )
    if brief.get("measurement_validity_checks"):
        protocol["measurement_validity_checks"] = [
            {
                **item,
                "measurement_id": "[REVIEW REQUIRED] bind the reviewed primary measurement ID",
            }
            for item in brief["measurement_validity_checks"]
        ]
        add_quality_requirements([
            item["assessment_gate_id"]
            for item in brief["measurement_validity_checks"]
        ])
    if isinstance(brief.get("causal_identification"), dict):
        protocol["causal_identification"] = dict(brief["causal_identification"])
        add_quality_requirements([
            item["assessment_gate_id"]
            for item in brief["causal_identification"].get("assumptions", [])
        ])
    for field in ("independent_unit", "repeated_measures", "analysis_design", "unit_analysis_plan"):
        if field in brief:
            protocol[field] = brief[field]
    if brief.get("control_definitions"):
        protocol["control_definitions"] = [dict(item) for item in brief["control_definitions"]]
        add_quality_requirements([
            item["evaluation_gate_id"] for item in brief["control_definitions"]
        ])
    if canary_target_plan is not None:
        add_quality_requirements([canary_target_plan["assessment_gate_id"]])
    if hypothesis_reactivity_plan is not None:
        add_quality_requirements([hypothesis_reactivity_plan["assessment_gate_id"]])
    if brief.get("preprocessing_pipeline") and brief.get("preprocessing_conformance_gate_id"):
        add_quality_requirements([brief["preprocessing_conformance_gate_id"]])
    if all(str(brief.get(field, "")).strip() for field in (
        "missingness_assumption", "missingness_assessment_plan",
        "missingness_failure_response", "missingness_assessment_kind",
        "missingness_assessment_gate_id",
    )):
        protocol["missingness_assessment"] = {
            field: brief[field] for field in (
                "missingness_assumption", "missingness_assessment_plan",
                "missingness_failure_response", "missingness_assessment_kind",
                "missingness_assessment_gate_id",
            )
        }
        add_quality_requirements([brief["missingness_assessment_gate_id"]])
    status = "blocked" if blockers else "review_required"
    provenance = _scaffold_provenance(brief, findings)
    inquiry_commitments = inquiry_decision_commitments(brief)
    artifacts = {
            "inquiry-draft.json": inquiry,
            "hypothesis-proposal.json": hypothesis,
            "protocol-draft.json": protocol,
            "analysis-workflow-draft.json": {
                "status": "review_required",
                "steps": analysis_steps,
                "notice": "Freeze exact methods, specifications, implementations, dependencies, hypotheses, outcomes, and measurements before execution. Generated placeholders are not registrations.",
            },
            "ambiguity-questions-draft.json": {
                "status": "review_required",
                "ambiguity_questions": ambiguity_questions,
                "notice": "These are unresolved review questions. They are not evidence, answers, protocol commitments, or authorization to choose a preferred explanation.",
            },
            "claim-boundaries-draft.json": {
                "status": "review_required",
                "claims": claim_boundaries,
                "notice": "These are unresolved claim-level proposals. They separate inference levels for review but do not accept, prove, or prioritize any claim.",
            },
            "controlled-acceptance-scenarios-draft.json": {
                "status": (
                    "review_required"
                    if controlled_acceptance_scenarios
                    else "unresolved"
                ),
                "scenarios": controlled_acceptance_scenarios,
                "scenario_count": len(controlled_acceptance_scenarios),
                "scientific_evidence_eligible": False,
                "notice": "These are review-only controlled readiness scenarios. They do not report observed results, pass criteria, protocol approval, evidence, or support for any scientific claim.",
            },
            "data-availability-draft.json": {
                "status": "review_required",
                "available_data_sources": available_data_sources,
                "unavailable_data": unavailable_data,
                "data_access_owner": data_access_owner,
                "data_access_constraints": data_access_constraints,
                "data_provenance_plan": data_provenance_plan,
                "notice": "This is a review-only data availability record. It does not verify access, custody, consent, source authenticity, or suitability for evidence.",
            },
            "ethical-safeguards-draft.json": {
                "status": "review_required",
                "ethical_constraints": ethical_constraints,
                "ethical_safeguards_plan": ethical_safeguards_plan,
                "notice": "This is a review-only ethical-safeguards record. It does not grant approval, authenticate reviewers, satisfy human-subject review, or prove substantive ethical adequacy.",
            },
            "data-dictionary-draft.json": {
                "outcome": brief["outcome"], "unit_or_scale": brief.get("outcome_unit", "[REVIEW REQUIRED]"), "scale_type": brief.get("outcome_scale", "[REVIEW REQUIRED]"), "admissible_values": _text_list(brief, "outcome_admissible_values"), "valid_min": brief.get("outcome_valid_min"), "valid_max": brief.get("outcome_valid_max"), "missing_value_codes": _text_list(brief, "outcome_missing_value_codes"), "primary_analysis_family": brief.get("primary_analysis_family", "[REVIEW REQUIRED]"), "unit_of_observation": brief["unit_of_observation"], "measurement_validity": brief.get("measurement_validity", "[REVIEW REQUIRED]"),
                "independent_unit": brief.get("independent_unit", "[REVIEW REQUIRED]"),
                "repeated_measures": brief.get("repeated_measures"),
                "analysis_design": brief.get("analysis_design", "[REVIEW REQUIRED]"),
                "proposed_columns": [
                    {"name": "observation_id", "role": "row_identity", "type": "string",
                     "constraint": "Unique per recorded observation; never recycle an identifier after exclusion."},
                    {"name": brief.get("unit_id_column", "[REVIEW REQUIRED]"), "role": "independent_unit_identity", "type": "string",
                     "constraint": "Stable pseudonymous identifier for the independently sampled unit, not a new identifier for each repeated row."},
                    {"name": brief.get("group_data_column", "[REVIEW REQUIRED]"), "role": "comparison_label", "type": "string",
                     "constraint": "Use only the reviewed ordered contrast levels; preserve the masking key separately when applicable."},
                    {"name": brief.get("outcome_data_column", "[REVIEW REQUIRED]"), "role": "primary_outcome", "type": "review_required",
                     "constraint": "Specify the measurement scale, units, valid range, and missing-value encoding before collection."},
                    *[
                        {"name": item["data_column"], "role": "secondary_outcome", "type": item["scale_type"],
                         "constraint": f"Registered measurement for secondary outcome: {item['outcome']}."}
                        for item in brief.get("secondary_measurements", [])
                        if item.get("data_column")
                    ],
                    *[
                        {"name": item["data_column"], "role": "control_measurement", "type": item["scale_type"],
                         "constraint": f"Registered measurement for control: {item['control']}."}
                        for item in brief.get("control_measurements", [])
                        if item.get("data_column")
                    ],
                    *[
                        {"name": item["data_column"], "role": "causal_covariate", "type": item["scale_type"],
                         "constraint": f"Pre-exposure measurement for audited adjustment variable: {item['variable']}."}
                        for item in brief.get("causal_measurements", [])
                        if item.get("role") == "covariate" and item.get("data_column")
                    ],
                    {"name": "captured_at", "role": "acquisition_time", "type": "timestamp_with_offset",
                     "constraint": "Record acquisition time with timezone and retain instrument clock/calibration provenance."},
                ],
                "column_status": "Review-only proposal, not a validated dataset schema or a frozen analysis specification.",
                "sample_size_justification": brief.get("sample_size_justification", "[REVIEW REQUIRED]"),
                "minimum_analyzable_units": brief.get("minimum_analyzable_units", "[REVIEW REQUIRED]"),
                "maximum_excluded_fraction": brief.get("maximum_excluded_fraction", "[REVIEW REQUIRED]"),
                "maximum_group_excluded_fraction_difference": brief.get(
                    "maximum_group_excluded_fraction_difference", "[REVIEW REQUIRED]"
                ),
                "missingness_assessment": {
                    field: brief.get(field, "[REVIEW REQUIRED]")
                    for field in (
                        "missingness_assumption", "missingness_assessment_plan",
                        "missingness_failure_response", "missingness_assessment_kind",
                        "missingness_assessment_gate_id",
                    )
                },
                "primary_outcome": brief["outcome"],
                "sensor_requirements": sensor_requirements,
                "clock_accuracy_requirement": brief.get("clock_accuracy_requirement", ""),
                "control_windows": control_windows,
                "manipulated_factors": manipulated_factors,
                "factorial_or_crossover_design": brief.get("factorial_or_crossover_design", False),
                "factor_interpretability_plan": brief.get("factor_interpretability_plan", ""),
                "secondary_outcomes": secondary_outcomes,
                "confirmatory_outcomes": _text_list(brief, "confirmatory_outcomes"),
                "exploratory_outcomes": _text_list(brief, "exploratory_outcomes"),
                "multiplicity_method": brief.get("multiplicity_method", ""),
                "multiplicity_alpha": brief.get("multiplicity_alpha"),
                "multiple_testing_policy": brief.get("multiple_testing_policy", "[REVIEW REQUIRED]"),
                "preprocessing_pipeline": brief.get("preprocessing_pipeline", ""),
                "preprocessing_conformance_gate_id": brief.get(
                    "preprocessing_conformance_gate_id", "[REVIEW REQUIRED]"
                ) if brief.get("preprocessing_pipeline") else "",
                "causal_variable_measurement_requirements": ([
                    {
                        "variable": node["id"],
                        "role": (
                            "exposure" if node["id"] == brief["causal_identification"]["exposure"]
                            else "primary" if node["id"] == brief["causal_identification"]["outcome"]
                            else "covariate" if node["id"] in brief["causal_identification"]["proposed_adjustment_set"]
                            else "causal_graph_variable"
                        ),
                        "observed": node["observed"],
                        "required_definition_fields": [
                            "observable", "input_condition", "parameter_values",
                            "evaluation_point", "convention", "aggregation",
                            "tolerance", "expected_behavior", "data_column",
                            "temporal_role",
                        ] if node["observed"] else [],
                        "status": (
                            "[REVIEW REQUIRED] create a typed measurement definition before causal analysis freeze"
                            if node["observed"] else
                            "unobserved variable; retain as an explicit identification limitation"
                        ),
                    }
                    for node in brief["causal_identification"]["nodes"]
                ] if isinstance(brief.get("causal_identification"), dict) else []),
            },
            "measurement-definition-draft.json": {
                "status": "review_required",
                "measurement_id": "[REVIEW REQUIRED] stable primary measurement ID",
                "role": "primary",
                "registered_target": brief["outcome"],
                "observable": brief.get("measurement_observable", "[REVIEW REQUIRED] define the exact recorded observable"),
                "input_condition": brief.get("measurement_input_condition", "[REVIEW REQUIRED]"),
                "parameter_values": brief.get("measurement_parameter_values", {}),
                "evaluation_point": brief.get("measurement_evaluation_point", "[REVIEW REQUIRED]"),
                "convention": brief.get("measurement_convention", "[REVIEW REQUIRED]"),
                "aggregation": brief.get("measurement_aggregation", "[REVIEW REQUIRED]"),
                "tolerance": brief.get("measurement_tolerance", "[REVIEW REQUIRED]"),
                "expected_behavior": brief.get("measurement_expected_behavior", "[REVIEW REQUIRED]"),
                "data_column": brief.get("outcome_data_column", "[REVIEW REQUIRED]"),
                "temporal_role": brief.get("measurement_temporal_role", "[REVIEW REQUIRED]"),
                "scale_type": brief.get("outcome_scale", "[REVIEW REQUIRED]"),
                "unit": brief.get("outcome_unit", "[REVIEW REQUIRED]"),
                "admissible_values": _text_list(brief, "outcome_admissible_values"),
                "valid_min": brief.get("outcome_valid_min"),
                "valid_max": brief.get("outcome_valid_max"),
                "missing_value_codes": _text_list(brief, "outcome_missing_value_codes"),
                "analysis_family": brief.get("primary_analysis_family", "[REVIEW REQUIRED]"),
                "alias_proxy_commitment": primary_alias_proxy_commitment,
                "notice": "Review and complete the full measurement contract before protocol freeze; this draft does not establish validity or authorize numeric coding of categories.",
            },
            "alias-proxy-commitments-draft.json": {
                "status": (
                    "review_required"
                    if alias_proxy_commitments
                    else "unresolved"
                ),
                "commitments": alias_proxy_commitments,
                "commitment_count": len(alias_proxy_commitments),
                "required_follow_up": (
                    "Before collection, copy each commitment into the frozen measurement definition and later record private mapping custody with research measurement record-alias-mapping."
                    if alias_proxy_commitments
                    else "No alias/proxy commitment was supplied in the guided design brief."
                ),
                "scientific_evidence_eligible": False,
                "notice": "These are review-only alias/proxy commitments. They bind public labels to private mapping hashes and reveal rules, but do not reveal hidden entities, prove proxy validity, authenticate private custody, satisfy ethics review, or authorize evidence.",
            },
            "measurement-validity-plan-draft.json": {
                "status": "review_required",
                "target": brief["outcome"],
                "measurement_column": brief.get("outcome_data_column", "[REVIEW REQUIRED]"),
                "checks": [dict(item) for item in brief.get("measurement_validity_checks", [])],
                "notice": "These are prospective validity claims and decision rules. A future artifact-bound gate disposition is required; this draft does not establish construct validity.",
            },
            "secondary-measurement-definitions-draft.json": {
                "status": "review_required",
                "measurements": [
                    {
                        "measurement_id": f"[REVIEW REQUIRED] stable secondary measurement ID {index}",
                        "role": "secondary",
                        "registered_target": item["outcome"],
                        **{key: value for key, value in item.items() if key != "outcome"},
                    }
                    for index, item in enumerate(
                        brief.get("secondary_measurements", []), start=1
                    )
                ],
                "notice": "The ordered list must exactly cover secondary_outcomes. Review IDs and all scientific semantics before copying these definitions into a protocol.",
            },
            "control-measurement-definitions-draft.json": {
                "status": "review_required",
                "measurements": [
                    {
                        "measurement_id": f"[REVIEW REQUIRED] stable control measurement ID {index}",
                        "role": "control",
                        "registered_target": item["control"],
                        **{key: value for key, value in item.items() if key != "control"},
                    }
                    for index, item in enumerate(
                        brief.get("control_measurements", []), start=1
                    )
                ],
                "notice": "The ordered list must exactly cover controls. Review IDs and scientific adequacy before copying these definitions into a protocol; an artifact-evaluated control need not be a dataset column.",
            },
            "causal-measurement-definitions-draft.json": {
                "status": "review_required",
                "measurements": [
                    {
                        "measurement_id": f"[REVIEW REQUIRED] stable {item['role']} measurement ID {index}",
                        "registered_target": item["variable"],
                        **{key: value for key, value in item.items() if key != "variable"},
                    }
                    for index, item in enumerate(
                        brief.get("causal_measurements", []), start=1
                    )
                ],
                "notice": "The ordered list must exactly cover the audited exposure followed by adjustment covariates. Timing and column agreement are prospective assertions, not proof that causal assumptions hold.",
            },
            "analysis-commitment-draft.json": {
                "status": "review_required",
                "primary_estimand": brief.get("primary_estimand", "[REVIEW REQUIRED]"),
                "contrast_definition": brief.get("contrast_definition", "[REVIEW REQUIRED]"),
                "contrast_groups": _text_list(brief, "contrast_groups"),
                "group_column": brief.get("group_data_column", "[REVIEW REQUIRED]"),
                "expected_effect_direction": brief.get("expected_effect_direction", "[REVIEW REQUIRED]"),
                "null_value": brief.get("null_value", "[REVIEW REQUIRED]"),
                "support_rule": brief.get("support_rule", "[REVIEW REQUIRED]"),
                "confidence_level": brief.get("confidence_level", "[REVIEW REQUIRED]"),
                "analysis_family": brief.get("primary_analysis_family", "[REVIEW REQUIRED]"),
                "measurement_scale": brief.get("outcome_scale", "[REVIEW REQUIRED]"),
                "analysis_contract": analysis_contract or {
                    "status": "unresolved",
                    "notice": "Exploratory or descriptive scaffolds may retain prose analysis review; protected confirmatory protocols must freeze a structured contract before execution.",
                },
                "notice": "This is a prospective review aid, not a frozen analysis contract. Bind stable hypothesis and measurement IDs plus exact executable specifications before collection.",
            },
            "sample-size-plan-draft.json": (
                {
                    **planning_receipt,
                    "guided_review_notice": "Deterministically recomputed review artifact. Before executable protocol freeze, bind the reviewed hypothesis ID, primary measurement ID, and unit; this draft is not preregistration or evidence.",
                }
                if planning_receipt is not None else {
                    "status": "unresolved",
                    "scientific_interpretation_verified": False,
                    "notice": "No reproducible sample-size plan is available. Supply a supported strategy and explicit assumptions or document a feasibility-limited design and its inferential limits.",
                }
            ),
            "preprocessing-conformance-plan-draft.json": {
                "status": (
                    "review_required"
                    if brief.get("preprocessing_pipeline")
                    else "unresolved"
                ),
                "registered_pipeline_sha256": brief.get(
                    "preprocessing_pipeline", ""
                ) or "[REVIEW REQUIRED] lowercase SHA-256 of the registered preprocessing-pipeline declaration",
                "required_gate_id": brief.get(
                    "preprocessing_conformance_gate_id", ""
                ) or "[REVIEW REQUIRED] dedicated preprocessing conformance gate",
                "required_run_assessment": {
                    "details_key": "preprocessing_conformance",
                    "result_shape": {
                        "locator": "[REVIEW REQUIRED] run output locator for preprocessing-conformance.json",
                        "sha256": "[REVIEW REQUIRED] preprocessing conformance record SHA-256",
                        "status": "preprocessing_conformance_passed | preprocessing_conformance_failed",
                        "registered_pipeline_sha256": brief.get(
                            "preprocessing_pipeline", ""
                        ) or "[REVIEW REQUIRED] match the frozen protocol preprocessing_pipeline",
                        "observed_pipeline_sha256": "[REVIEW REQUIRED] observed preprocessing-pipeline declaration SHA-256",
                    },
                },
                "notice": "This is a review-only preprocessing adherence plan. A future run must cite a byte-verified conformance record; matching declarations do not prove implementation correctness or scientific validity.",
            },
            "causal-identification-audit.json": causal_audit or {
                "status": "unresolved",
                "claim_ceiling": "No causal graph was supplied or audited.",
                "scientific_evidence_eligible": False,
            },
            "canary-target-plan-draft.json": {
                "status": "review_required" if canary_target_plan is not None else "unresolved",
                "canary_target_plan": canary_target_plan or {
                    "notice": "No masked canary-target plan was supplied.",
                },
                "required_run_assessment": {
                    "gate_id": (
                        canary_target_plan["assessment_gate_id"]
                        if canary_target_plan is not None
                        else "[REVIEW REQUIRED] dedicated canary assessment gate"
                    ),
                    "result_shape": {
                        "plan_id": (
                            canary_target_plan["plan_id"]
                            if canary_target_plan is not None
                            else "[REVIEW REQUIRED] canary plan ID"
                        ),
                        "assignment_artifact_sha256": (
                            canary_target_plan["assignment_artifact_sha256"]
                            if canary_target_plan is not None
                            else "[REVIEW REQUIRED] hidden assignment artifact SHA-256"
                        ),
                        "revealed_target_id": "[REVIEW REQUIRED] reveal only from the frozen assignment artifact",
                        "comparator_target_ids": [
                            "[REVIEW REQUIRED] frozen candidate target used as decoy, replay, sham, or no-target comparator"
                        ],
                        "assessment_status": "consistent_with_revealed_target | follows_comparator_or_decoy | follows_no_target | mixed | inconclusive",
                        "observed_pattern": "[REVIEW REQUIRED] bounded observation",
                        "interpretation": "[REVIEW REQUIRED] disclose without claiming mechanism, adaptation, attribution, or intent",
                        "evidence_sha256": "[REVIEW REQUIRED] run output artifact SHA-256",
                        "evidence_location": "[REVIEW REQUIRED] exact location, absolute JSON Pointer for verified JSON outputs",
                    },
                },
                "notice": "This is a prospective masked-target design aid. It is not evidence of adaptation, mechanism, attribution, or intent, and it does not authenticate the hidden assignment.",
            },
            "hypothesis-reactivity-plan-draft.json": {
                "status": (
                    "review_required"
                    if hypothesis_reactivity_plan is not None
                    else "unresolved"
                ),
                "hypothesis_reactivity_plan": hypothesis_reactivity_plan or {
                    "notice": "No hypothesis-reactivity plan was supplied.",
                },
                "required_run_assessment": {
                    "gate_id": (
                        hypothesis_reactivity_plan["assessment_gate_id"]
                        if hypothesis_reactivity_plan is not None
                        else "[REVIEW REQUIRED] dedicated reactivity assessment gate"
                    ),
                    "result_shape": {
                        "plan_id": (
                            hypothesis_reactivity_plan["plan_id"]
                            if hypothesis_reactivity_plan is not None
                            else "[REVIEW REQUIRED] reactivity plan ID"
                        ),
                        "assessment_status": (
                            "models_discriminated | compatible_with_multiple | "
                            "not_distinguishable_by_design | inconclusive"
                        ),
                        "supported_model_ids": [
                            "[REVIEW REQUIRED] frozen distinguishable model IDs only"
                        ],
                        "not_distinguishable_model_ids": [
                            "[REVIEW REQUIRED] exact frozen non-distinguishable model IDs"
                        ],
                        "likelihood_comparison": (
                            "[REVIEW REQUIRED] cite frozen likelihood_comparison_rule or plan_id"
                        ),
                        "observed_pattern": "[REVIEW REQUIRED] bounded observation",
                        "interpretation": (
                            "[REVIEW REQUIRED] disclose without claiming detection, adaptation, or intent"
                        ),
                        "decision_rationale": (
                            "[OPTIONAL] requires frozen decision_loss_assumptions; not a finding"
                        ),
                        "evidence_sha256": "[REVIEW REQUIRED] run output artifact SHA-256",
                        "evidence_location": (
                            "[REVIEW REQUIRED] exact location, absolute JSON Pointer for verified JSON outputs"
                        ),
                    },
                },
                "notice": (
                    "Prospective disclosure and process-model design aid. Observation, "
                    "model compatibility, and decision loss remain separate. "
                    "Non-distinguishable models are design limits, not independently "
                    "supported explanations."
                ),
            },
            "collection-plan.md": (
                f"# {brief['title']}\n\nQuestion: {brief['question']}\n\nDecision: {brief['decision']}\n\n"
                f"Minimum decision-relevant evidence: {inquiry_commitments['minimum_evidence']}\n\n"
                "Decision-change observations: "
                + "; ".join(inquiry_commitments["decision_change_criteria"])
                + "\n\n"
                f"Decision owner: {inquiry_commitments['decision_owner']}\n\n"
                "Unresolved ambiguity questions: "
                + (
                    "; ".join(ambiguity_questions)
                    if ambiguity_questions else "[REVIEW REQUIRED]"
                )
                + "\n\n"
                "Claim-level boundaries: "
                + (
                    "; ".join(
                        f"{item['level']}: {item['statement']}"
                        for item in claim_boundaries
                    )
                    if claim_boundaries else "[REVIEW REQUIRED]"
                )
                + "\n\n"
                "Controlled acceptance scenarios: "
                + (
                    "; ".join(
                        f"{item['scenario_id']} distinguishes "
                        + ", ".join(item["distinguishes_from"])
                        for item in controlled_acceptance_scenarios
                    )
                    if controlled_acceptance_scenarios else "[REVIEW REQUIRED]"
                )
                + "\n\n"
                "Available data sources: "
                + (
                    "; ".join(available_data_sources)
                    if available_data_sources else "[REVIEW REQUIRED]"
                )
                + "\n\n"
                "Unavailable or out-of-reach data: "
                + (
                    "; ".join(unavailable_data)
                    if unavailable_data else "[none declared]"
                )
                + "\n\n"
                f"Data access owner: {brief.get('data_access_owner') or '[REVIEW REQUIRED]'}\n\n"
                "Data access constraints: "
                + (
                    "; ".join(data_access_constraints)
                    if data_access_constraints else "[none declared]"
                )
                + "\n\n"
                f"Data provenance plan: {brief.get('data_provenance_plan') or '[REVIEW REQUIRED]'}\n\n"
                "Ethical and safety constraints: "
                + (
                    "; ".join(ethical_constraints)
                    if ethical_constraints else "[REVIEW REQUIRED]"
                )
                + "\n\n"
                f"Ethical safeguards plan: {brief.get('ethical_safeguards_plan') or '[REVIEW REQUIRED]'}\n\n"
                "Collect only after blocking findings are resolved and the applicable protocol is reviewed and frozen.\n\n"
                "Keep observation identity separate from independent-unit identity. Repeated observations retain the same unit ID; do not manufacture independence by assigning each row a new unit ID. "
                "Use pseudonymous IDs and keep identifying lookup tables under the approved privacy controls.\n\n"
                "Preserve raw captures unchanged. Record missing measurements and reasons without replacing them with zero or deleting unfavorable observations. "
                "Any exclusions or unit-level aggregation belong in a versioned, reviewed transformation with raw-source lineage.\n\n"
                "Freeze the minimum analyzable independent-unit count, total and differential exclusion thresholds, and the missingness assessment contract before protected outcomes are inspected. Crossing a threshold or contradicting the registered missingness assumption requires the frozen failure response, not silent continuation.\n\n"
                "The proposed data dictionary needs review for scale, valid ranges, missing-value encoding, condition labels, masking, and collection timing. "
                f"It is not an executable collection validator. Analysis should commit {brief.get('unit_id_column', '[REVIEW REQUIRED: unit ID column]')} as its unit column only after the unit definition is reviewed.\n"
                "\n"
                f"Manipulated factors: {', '.join(manipulated_factors) if manipulated_factors else '[REVIEW REQUIRED: none declared]'}. "
                f"Factorial or crossover design declared: {brief.get('factorial_or_crossover_design', False)}. "
                f"Interpretability plan: {brief.get('factor_interpretability_plan') or '[REVIEW REQUIRED if more than one factor changes]'}.\n"
                "\n"
                f"Required sensors or streams: {', '.join(sensor_requirements) if sensor_requirements else '[REVIEW REQUIRED: none declared]'}. "
                f"Clock accuracy or synchronization: {brief.get('clock_accuracy_requirement') or '[REVIEW REQUIRED]'}. "
                f"Control windows: {', '.join(control_windows) if control_windows else '[none declared]'}.\n"
                "\n"
                f"Canary target plan: {canary_target_plan['plan_id'] if canary_target_plan else '[not supplied]'}. "
                "If used, keep the hidden assignment artifact sealed until the protocol-specified reveal point and report comparator, decoy, no-target, mixed, or inconclusive outcomes without upgrading them into source or intent claims.\n"
                "\n"
                f"Registered preprocessing pipeline SHA-256: {brief.get('preprocessing_pipeline') or '[not supplied]'}. "
                f"Preprocessing conformance gate: {brief.get('preprocessing_conformance_gate_id') or '[not supplied]'}. "
                "A matching declaration proves only conformance of the observed preprocessing declaration to the registered declaration, not implementation correctness or scientific adequacy.\n"
            ),
    }
    _stamp_scaffold_provenance(artifacts, provenance)
    manifest = _scaffold_manifest(status, artifacts, provenance)
    artifacts["design-scaffold-provenance.json"] = manifest
    return {
        "status": status,
        "plain_language_summary": "This scaffold is a draft. It does not register, approve, or freeze a study.",
        "findings": [item.to_dict() for item in findings],
        "provenance": {
            **provenance,
            "artifact_manifest_sha256": manifest["artifact_manifest_sha256"],
        },
        "artifacts": artifacts,
    }
