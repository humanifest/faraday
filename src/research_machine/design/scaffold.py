from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any
from research_machine.domain.models import (
    ControlDefinition, CONTROL_FAMILIES, MEASUREMENT_TEMPORAL_ROLES,
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
_VALIDITY_CHECK_FIELDS = {
    "check_id", "evidence_type", "validity_claim", "assessment_plan",
    "acceptance_criterion", "failure_response", "assessment_gate_id",
}
_VALIDITY_EVIDENCE_TYPES = {
    "criterion", "convergent", "discriminant", "known_groups", "test_retest",
    "inter_rater", "content", "calibration", "other",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def _is_canonical_sha256(value: str) -> bool:
    return bool(_SHA256.fullmatch(value))


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


def validate_brief(brief: dict[str, Any]) -> None:
    if not isinstance(brief, dict):
        raise ValueError("design brief must be an object")
    unknown = set(brief) - {
        "title", "question", "decision", "study_type", "population", "setting",
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
        "measurement_validity_checks",
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
        "causal_identification",
    }
    if unknown:
        raise ValueError("unknown design brief fields: " + ", ".join(sorted(unknown)))
    non_text_fields = {"controls", "confounds", "exclusions", "falsification_conditions", "secondary_outcomes", "confirmatory_outcomes", "exploratory_outcomes", "multiplicity_alpha", "independent_review_conditions", "human_participants", "independent_review", "repeated_measures", "factorial_or_crossover_design", "control_definitions", "minimum_analyzable_units", "maximum_excluded_fraction", "maximum_group_excluded_fraction_difference", "smallest_effect_size_of_interest", "higher_level_conclusions_unsupported", "causal_identification", "outcome_admissible_values", "outcome_missing_value_codes", "outcome_valid_min", "outcome_valid_max", "null_value", "confidence_level", "contrast_groups", "manipulated_factors", "measurement_parameter_values", "measurement_validity_checks", "secondary_measurements", "control_measurements", "causal_measurements", "sample_size_plan"}
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
    _text_list(brief, "independent_review_conditions")
    study_type = brief.get("study_type", "exploratory")
    if study_type not in _STUDY_TYPES:
        raise ValueError("study_type must be one of: " + ", ".join(sorted(_STUDY_TYPES)))
    if brief.get("assignment_type", "") not in {"", "randomized", "observational"}:
        raise ValueError("assignment_type must be randomized or observational")
    for key in {"controls", "confounds", "exclusions", "falsification_conditions", "secondary_outcomes", "confirmatory_outcomes", "exploratory_outcomes", "higher_level_conclusions_unsupported", "outcome_admissible_values", "outcome_missing_value_codes", "contrast_groups", "manipulated_factors"}:
        _text_list(brief, key)
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
    secondary_measurements = brief.get("secondary_measurements", [])
    if not isinstance(secondary_measurements, list):
        raise ValueError("secondary_measurements must be an array")
    for index, measurement in enumerate(secondary_measurements):
        if not isinstance(measurement, dict) or set(measurement) != _SECONDARY_MEASUREMENT_FIELDS:
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
    control_measurements = brief.get("control_measurements", [])
    if not isinstance(control_measurements, list):
        raise ValueError("control_measurements must be an array")
    for index, measurement in enumerate(control_measurements):
        if not isinstance(measurement, dict) or set(measurement) != _CONTROL_MEASUREMENT_FIELDS:
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
    causal_measurements = brief.get("causal_measurements", [])
    if not isinstance(causal_measurements, list):
        raise ValueError("causal_measurements must be an array")
    for index, measurement in enumerate(causal_measurements):
        if not isinstance(measurement, dict) or set(measurement) != _CAUSAL_MEASUREMENT_FIELDS:
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

    if any(brief[field] != brief[field].strip() for field in _REQUIRED):
        add(
            "CORE_BRIEF_FIELD_NONCANONICAL", "error",
            "A required design brief field contains surrounding whitespace.",
            "Use exact unpadded title, question, decision, outcome, and unit-of-observation text before review drafts preserve them as inquiry, hypothesis, protocol, and collection commitments.",
        )
    require_canonical_list_items("secondary_outcomes", "SECONDARY_OUTCOME_LABEL_NONCANONICAL", "Secondary outcomes")
    require_canonical_list_items("confirmatory_outcomes", "CONFIRMATORY_OUTCOME_LABEL_NONCANONICAL", "Confirmatory outcomes")
    require_canonical_list_items("exploratory_outcomes", "EXPLORATORY_OUTCOME_LABEL_NONCANONICAL", "Exploratory outcomes")
    require_canonical_list_items("contrast_groups", "CONTRAST_GROUP_LABEL_NONCANONICAL", "Contrast groups")
    require_canonical_list_items("manipulated_factors", "MANIPULATED_FACTOR_NONCANONICAL", "Manipulated factors")
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

    def has_noncanonical_parameter_values(values: dict[str, str]) -> bool:
        return any(
            key != key.strip() or value != value.strip()
            for key, value in values.items()
        )

    def has_noncanonical_text_items(values: list[str]) -> bool:
        return any(value != value.strip() for value in values)

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

    secondary_outcomes = _text_list(brief, "secondary_outcomes")
    manipulated_factors = _text_list(brief, "manipulated_factors")
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
        if set(targets) != set(brief.get("controls", [])) or len(set(targets)) != len(targets) or len(set(ids)) != len(ids):
            add("CONTROL_COVERAGE_INVALID", "error", "Structured controls do not uniquely cover the named controls.", "Provide one uniquely identified definition for each named control.")
        for item in definitions:
            if any(not value.strip() for value in item.values()) or item["family"] not in CONTROL_FAMILIES:
                add("CONTROL_DEFINITION_INCOMPLETE", "error", "A control has unresolved family, purpose, expectation, or evaluation linkage.", "Complete the control definition before protocol review.")
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
            "Use exact unpadded intervention, exposure, comparison, sampling, blinding, calibration, analysis, stopping, prediction, and alternative-model text before review artifacts preserve those commitments.",
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
        add("CONTROL_FAMILY_MISSING", "warning", "No positive, negative, sham, replay, or other control is planned.", "Choose the control family that could reveal a misleading measurement or procedure.")
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
                    _text_list(brief, "independent_review_conditions")
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
            if decision == "approved_with_conditions" and not _text_list(brief, "independent_review_conditions"):
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
    if len(set(dedicated_gate_ids)) != len(dedicated_gate_ids):
        add(
            "QUALITY_GATE_PURPOSE_COLLISION", "error",
            "A quality gate is reused across control, measurement-validity, causal-assumption, or missingness purposes.",
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
    secondary_outcomes = _text_list(brief, "secondary_outcomes")
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
        }],
        "measurement_custody_requirements": ["[REVIEW REQUIRED] name the custody gate that demonstrates the calibration requirement was met"],
        "statistical_model": brief.get("analysis_commitment", "[REVIEW REQUIRED]"),
        "multiple_testing_policy": brief.get("multiple_testing_policy", "[REVIEW REQUIRED]"),
        "inclusion_rules": [brief.get("sampling_plan", "[REVIEW REQUIRED]")],
        "exclusion_rules": _text_list(brief, "exclusions"),
        "safety_constraints": ["Human-participant review required before collection."] if brief.get("human_participants") else ["[REVIEW REQUIRED] assess applicable safety constraints."],
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
        "independent_review_conditions": _text_list(brief, "independent_review_conditions"),
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
    artifacts = {
            "hypothesis-proposal.json": hypothesis,
            "protocol-draft.json": protocol,
            "analysis-workflow-draft.json": {
                "status": "review_required",
                "steps": analysis_steps,
                "notice": "Freeze exact methods, specifications, implementations, dependencies, hypotheses, outcomes, and measurements before execution. Generated placeholders are not registrations.",
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
                "manipulated_factors": manipulated_factors,
                "factorial_or_crossover_design": brief.get("factorial_or_crossover_design", False),
                "factor_interpretability_plan": brief.get("factor_interpretability_plan", ""),
                "secondary_outcomes": secondary_outcomes,
                "confirmatory_outcomes": _text_list(brief, "confirmatory_outcomes"),
                "exploratory_outcomes": _text_list(brief, "exploratory_outcomes"),
                "multiplicity_method": brief.get("multiplicity_method", ""),
                "multiplicity_alpha": brief.get("multiplicity_alpha"),
                "multiple_testing_policy": brief.get("multiple_testing_policy", "[REVIEW REQUIRED]"),
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
                "notice": "Review and complete the full measurement contract before protocol freeze; this draft does not establish validity or authorize numeric coding of categories.",
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
            "causal-identification-audit.json": causal_audit or {
                "status": "unresolved",
                "claim_ceiling": "No causal graph was supplied or audited.",
                "scientific_evidence_eligible": False,
            },
            "collection-plan.md": (
                f"# {brief['title']}\n\nQuestion: {brief['question']}\n\nDecision: {brief['decision']}\n\n"
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
