from __future__ import annotations

import math
import hashlib
import json
from statistics import NormalDist
from typing import Any

from research_machine.domain.errors import ValidationError


def _canonical_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"sample_size_plan {field} must be non-empty text")
    if value != value.strip():
        raise ValidationError(f"sample_size_plan {field} must be canonical without surrounding whitespace")
    return value


def _registered_variance_ratio(spec: dict[str, Any]) -> float | None:
    value = spec.get("maximum_observed_to_assumed_sd_ratio")
    if value is None:
        return None
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(float(value)) or float(value) < 1
    ):
        raise ValidationError(
            "maximum_observed_to_assumed_sd_ratio must be a finite number of at least one"
        )
    return float(value)


def build_sample_size_planning_receipt(value: dict[str, Any]) -> dict[str, Any]:
    """Recompute a protocol-bindable precision or power planning receipt."""
    if not isinstance(value, dict):
        raise ValidationError("sample_size_plan must be an object")
    base_input_fields = {"strategy", "specification", "justification"}
    targeted_input_fields = base_input_fields | {
        "target_hypothesis_id", "target_measurement_id", "measurement_unit",
    }
    receipt_fields = base_input_fields | {
        "planning_version",
        "specification_sha256",
        "calculation",
        "scope",
        "scientific_interpretation_verified",
    }
    targeted_receipt_fields = receipt_fields | {
        "target_hypothesis_id", "target_measurement_id", "measurement_unit",
        "planning_target_sha256",
    }
    supplied_fields = frozenset(value)
    allowed_shapes = {
        frozenset(base_input_fields), frozenset(targeted_input_fields),
        frozenset(receipt_fields), frozenset(targeted_receipt_fields),
    }
    if supplied_fields not in allowed_shapes:
        unknown = sorted(set(value) - targeted_receipt_fields)
        missing = sorted(base_input_fields - set(value))
        details = []
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        if missing:
            details.append("missing: " + ", ".join(missing))
        if not details:
            details.append("partial service-generated receipt fields are not allowed")
        raise ValidationError("invalid sample_size_plan fields; " + "; ".join(details))
    strategy = value.get("strategy")
    if strategy not in {
        "power", "practical_power", "precision", "equivalence_power",
    }:
        raise ValidationError(
            "sample_size_plan strategy must be power, practical_power, precision, or equivalence_power"
        )
    specification = value.get("specification")
    if not isinstance(specification, dict):
        raise ValidationError("sample_size_plan specification must be an object")
    justification = _canonical_text(value.get("justification"), "justification")
    targeted = "target_hypothesis_id" in value
    if targeted:
        for field in (
            "target_hypothesis_id", "target_measurement_id", "measurement_unit",
        ):
            _canonical_text(value[field], field)
    calculation = (
        plan_two_group_power(specification) if strategy == "power"
        else plan_two_group_practical_power(specification)
        if strategy == "practical_power"
        else plan_two_group_equivalence_power(specification)
        if strategy == "equivalence_power"
        else plan_two_group_precision(specification)
    )
    canonical_specification = json.dumps(
        specification, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    expected = {
        "planning_version": 1,
        "strategy": strategy,
        "specification": specification,
        "specification_sha256": hashlib.sha256(canonical_specification).hexdigest(),
        "justification": justification,
        "calculation": calculation,
        "scope": "prospective sample-size assumptions and deterministic calculation",
        "scientific_interpretation_verified": False,
    }
    if targeted:
        target = {
            field: value[field] for field in (
                "target_hypothesis_id", "target_measurement_id", "measurement_unit",
            )
        }
        expected.update(target)
        expected["planning_version"] = 2
        expected["planning_target_sha256"] = hashlib.sha256(json.dumps(
            target, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
    if supplied_fields in {
        frozenset(receipt_fields), frozenset(targeted_receipt_fields),
    } and value != expected:
        raise ValidationError(
            "sample_size_plan service receipt does not reproduce exactly"
        )
    return expected


def plan_two_group_precision(spec: dict[str, Any]) -> dict[str, Any]:
    """Plan equal independent groups for a target normal-approximation CI width."""
    allowed = {
        "study_design",
        "target_half_width",
        "assumed_standard_deviation",
        "confidence_level",
        "anticipated_attrition_fraction",
        "maximum_observed_to_assumed_sd_ratio",
        "sensitivity_standard_deviations",
    }
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValidationError("unknown precision-plan fields: " + ", ".join(unknown))
    if spec.get("study_design") != "independent_groups":
        raise ValidationError("two-group precision planning requires study_design independent_groups")
    values: dict[str, float] = {}
    for field in ("target_half_width", "assumed_standard_deviation"):
        value = spec.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValidationError(f"{field} must be a positive finite number")
        try:
            converted = float(value)
        except (ValueError, OverflowError) as exc:
            raise ValidationError(f"{field} must be a representable positive finite number") from exc
        if not math.isfinite(converted) or converted <= 0:
            raise ValidationError(f"{field} must be a positive finite number")
        values[field] = converted
    confidence = spec.get("confidence_level", 0.95)
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0.8 <= confidence < 1:
        raise ValidationError("confidence_level must be in [0.8, 1)")
    attrition = spec.get("anticipated_attrition_fraction", 0)
    if not isinstance(attrition, (int, float)) or isinstance(attrition, bool) or not 0 <= attrition < 0.9:
        raise ValidationError("anticipated_attrition_fraction must be in [0, 0.9)")
    variance_ratio = _registered_variance_ratio(spec)
    # Lower-tail form avoids rounding (1 + confidence) / 2 to exactly one.
    z = -NormalDist().inv_cdf((1 - float(confidence)) / 2)
    try:
        raw_n = 2 * (z * (values["assumed_standard_deviation"] / values["target_half_width"])) ** 2
        if not math.isfinite(raw_n) or raw_n == 0:
            raise OverflowError("unrepresentable precision target")
        analyzable_per_group = max(2, math.ceil(raw_n))
        enroll_per_group = math.ceil(analyzable_per_group / (1 - float(attrition)))
    except (OverflowError, ValueError) as exc:
        raise ValidationError("precision target exceeds numerical range; rescale units or review the inputs") from exc
    result = {
        "study_design": "independent_groups",
        "confidence_level": float(confidence),
        "target_half_width": values["target_half_width"],
        "assumed_standard_deviation": values["assumed_standard_deviation"],
        "normal_quantile": z,
        "minimum_two_per_group_applied": raw_n < 2,
        "analyzable_n_per_group": analyzable_per_group,
        "analyzable_total_n": analyzable_per_group * 2,
        "anticipated_attrition_fraction": float(attrition),
        "enrollment_n_per_group": enroll_per_group,
        "enrollment_total_n": enroll_per_group * 2,
        "assumptions": [
            "Equal independent group sizes.",
            "A floor of two observations per group supports variance computation, not adequacy of the normal approximation; small studies need method review.",
            "The assumed standard deviation is appropriate for the registered outcome and population.",
            "This is a precision target, not a power calculation or a guarantee of causal identification.",
        ],
    }
    if variance_ratio is not None:
        result["maximum_observed_to_assumed_sd_ratio"] = variance_ratio
    if "sensitivity_standard_deviations" in spec:
        scenarios = spec["sensitivity_standard_deviations"]
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 100:
            raise ValidationError("sensitivity_standard_deviations must contain 1 to 100 researcher-supplied assumptions")
        base = {key: value for key, value in spec.items() if key != "sensitivity_standard_deviations"}
        plans = [plan_two_group_precision({**base, "assumed_standard_deviation": value}) for value in scenarios]
        deviations = [plan["assumed_standard_deviation"] for plan in plans]
        if len(set(deviations)) != len(deviations):
            raise ValidationError("sensitivity_standard_deviations must be distinct")
        result["sensitivity"] = {
            "varied_assumption": "assumed_standard_deviation",
            "scenarios": [{key: plan[key] for key in (
                "assumed_standard_deviation", "analyzable_n_per_group", "enrollment_n_per_group",
                "minimum_two_per_group_applied",
            )} for plan in plans],
            "notice": "Researcher-supplied hypothetical scenarios, not estimated uncertainty bounds or an automatically selected enrollment recommendation. Other assumptions are held fixed.",
        }
    return result


def plan_two_group_power(spec: dict[str, Any]) -> dict[str, Any]:
    """Plan equal independent groups with a bounded normal-approximation power model."""
    allowed = {
        "study_design",
        "smallest_effect_size_of_interest",
        "assumed_standard_deviation",
        "alpha",
        "target_power",
        "alternative",
        "anticipated_attrition_fraction",
        "maximum_observed_to_assumed_sd_ratio",
        "sensitivity_effect_sizes",
        "sensitivity_standard_deviations",
    }
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValidationError("unknown power-plan fields: " + ", ".join(unknown))
    if spec.get("study_design") != "independent_groups":
        raise ValidationError(
            "two-group power planning requires study_design independent_groups"
        )

    def positive(field: str) -> float:
        value = spec.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValidationError(f"{field} must be a positive finite number")
        try:
            converted = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValidationError(f"{field} must be a positive finite number") from exc
        if not math.isfinite(converted) or converted <= 0:
            raise ValidationError(f"{field} must be a positive finite number")
        return converted

    effect = positive("smallest_effect_size_of_interest")
    standard_deviation = positive("assumed_standard_deviation")
    alpha = spec.get("alpha", 0.05)
    if (
        not isinstance(alpha, (int, float))
        or isinstance(alpha, bool)
        or not math.isfinite(float(alpha))
        or not 0 < float(alpha) <= 0.2
    ):
        raise ValidationError("alpha must be a finite number in (0, 0.2]")
    target_power = spec.get("target_power", 0.8)
    if (
        not isinstance(target_power, (int, float))
        or isinstance(target_power, bool)
        or not math.isfinite(float(target_power))
        or not 0.5 < float(target_power) < 1
    ):
        raise ValidationError("target_power must be a finite number in (0.5, 1)")
    alternative = spec.get("alternative", "two_sided")
    if alternative not in {"two_sided", "greater", "less"}:
        raise ValidationError("alternative must be two_sided, greater, or less")
    attrition = spec.get("anticipated_attrition_fraction", 0)
    if (
        not isinstance(attrition, (int, float))
        or isinstance(attrition, bool)
        or not math.isfinite(float(attrition))
        or not 0 <= float(attrition) < 0.9
    ):
        raise ValidationError(
            "anticipated_attrition_fraction must be a finite number in [0, 0.9)"
        )
    variance_ratio = _registered_variance_ratio(spec)
    tail_alpha = float(alpha) / 2 if alternative == "two_sided" else float(alpha)
    z_alpha = -NormalDist().inv_cdf(tail_alpha)
    z_power = NormalDist().inv_cdf(float(target_power))
    try:
        raw_n = 2 * ((z_alpha + z_power) * standard_deviation / effect) ** 2
        if not math.isfinite(raw_n) or raw_n == 0:
            raise OverflowError("unrepresentable power target")
        analyzable_per_group = max(2, math.ceil(raw_n))
        enrollment_per_group = math.ceil(
            analyzable_per_group / (1 - float(attrition))
        )
    except (OverflowError, ValueError) as exc:
        raise ValidationError(
            "power target exceeds numerical range; rescale units or review the inputs"
        ) from exc
    result: dict[str, Any] = {
        "planning_method": "normal_approximation_equal_independent_groups",
        "study_design": "independent_groups",
        "smallest_effect_size_of_interest": effect,
        "assumed_standard_deviation": standard_deviation,
        "standardized_effect_size": effect / standard_deviation,
        "alpha": float(alpha),
        "target_power": float(target_power),
        "alternative": alternative,
        "alpha_quantile": z_alpha,
        "power_quantile": z_power,
        "minimum_two_per_group_applied": raw_n < 2,
        "analyzable_n_per_group": analyzable_per_group,
        "analyzable_total_n": analyzable_per_group * 2,
        "anticipated_attrition_fraction": float(attrition),
        "enrollment_n_per_group": enrollment_per_group,
        "enrollment_total_n": enrollment_per_group * 2,
        "assumptions": [
            "Equal independent group sizes and a continuous outcome.",
            "A common, correctly specified standard deviation applies in the registered population.",
            "The normal-approximation known-variance formula is adequate; small samples require method review or exact/software-specific planning.",
            "The stated alpha is for one primary comparison and does not include multiplicity adjustment.",
            "Attrition inflation does not correct selection bias or informative missingness.",
            "Power is conditional on the supplied effect and variance assumptions; it does not establish causal identification, measurement validity, or scientific importance.",
        ],
        "scientific_interpretation_verified": False,
    }
    if variance_ratio is not None:
        result["maximum_observed_to_assumed_sd_ratio"] = variance_ratio

    sensitivity: dict[str, Any] = {}
    for field, varied in (
        ("sensitivity_effect_sizes", "smallest_effect_size_of_interest"),
        ("sensitivity_standard_deviations", "assumed_standard_deviation"),
    ):
        if field not in spec:
            continue
        scenarios = spec[field]
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 100:
            raise ValidationError(f"{field} must contain 1 to 100 assumptions")
        base = {
            key: value
            for key, value in spec.items()
            if key not in {"sensitivity_effect_sizes", "sensitivity_standard_deviations"}
        }
        plans = [plan_two_group_power({**base, varied: value}) for value in scenarios]
        values = [plan[varied] for plan in plans]
        if len(set(values)) != len(values):
            raise ValidationError(f"{field} must contain distinct positive assumptions")
        sensitivity[varied] = [
            {
                varied: plan[varied],
                "standardized_effect_size": plan["standardized_effect_size"],
                "analyzable_n_per_group": plan["analyzable_n_per_group"],
                "enrollment_n_per_group": plan["enrollment_n_per_group"],
                "minimum_two_per_group_applied": plan[
                    "minimum_two_per_group_applied"
                ],
            }
            for plan in plans
        ]
    if sensitivity:
        result["sensitivity"] = {
            **sensitivity,
            "notice": "Researcher-supplied hypothetical scenarios; no parameter is estimated or selected automatically, and all unvaried assumptions are held fixed.",
        }
    return result


def plan_two_group_equivalence_power(spec: dict[str, Any]) -> dict[str, Any]:
    """Plan a direct two-group equivalence decision under a known-variance normal model."""
    allowed = {
        "study_design", "equivalence_margin", "assumed_true_difference",
        "assumed_standard_deviation", "alpha", "target_power",
        "anticipated_attrition_fraction", "maximum_observed_to_assumed_sd_ratio",
        "sensitivity_true_differences", "sensitivity_standard_deviations",
    }
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValidationError(
            "unknown equivalence-power fields: " + ", ".join(unknown)
        )
    if spec.get("study_design") != "independent_groups":
        raise ValidationError(
            "two-group equivalence power planning requires study_design independent_groups"
        )

    def finite(field: str) -> float:
        value = spec.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"{field} must be a finite number")
        converted = float(value)
        if not math.isfinite(converted):
            raise ValidationError(f"{field} must be a finite number")
        return converted

    margin = finite("equivalence_margin")
    standard_deviation = finite("assumed_standard_deviation")
    true_difference = finite("assumed_true_difference")
    if margin <= 0 or standard_deviation <= 0:
        raise ValidationError(
            "equivalence_margin and assumed_standard_deviation must be positive"
        )
    if abs(true_difference) >= margin:
        raise ValidationError(
            "assumed_true_difference must lie strictly inside the equivalence margin"
        )
    alpha = spec.get("alpha", 0.05)
    target_power = spec.get("target_power", 0.8)
    attrition = spec.get("anticipated_attrition_fraction", 0)
    if (
        isinstance(alpha, bool) or not isinstance(alpha, (int, float))
        or not math.isfinite(float(alpha)) or not 0 < float(alpha) <= 0.2
    ):
        raise ValidationError("alpha must be a finite number in (0, 0.2]")
    if (
        isinstance(target_power, bool) or not isinstance(target_power, (int, float))
        or not math.isfinite(float(target_power)) or not 0.5 < float(target_power) < 1
    ):
        raise ValidationError("target_power must be a finite number in (0.5, 1)")
    if (
        isinstance(attrition, bool) or not isinstance(attrition, (int, float))
        or not math.isfinite(float(attrition)) or not 0 <= float(attrition) < 0.9
    ):
        raise ValidationError(
            "anticipated_attrition_fraction must be a finite number in [0, 0.9)"
        )
    variance_ratio = _registered_variance_ratio(spec)
    normal = NormalDist()
    critical = -normal.inv_cdf(float(alpha))

    def decision_power(n_per_group: int) -> float:
        standard_error = standard_deviation * math.sqrt(2 / n_per_group)
        lower_acceptance = -margin + critical * standard_error
        upper_acceptance = margin - critical * standard_error
        if lower_acceptance >= upper_acceptance:
            return 0.0
        return max(0.0, normal.cdf(
            (upper_acceptance - true_difference) / standard_error
        ) - normal.cdf(
            (lower_acceptance - true_difference) / standard_error
        ))

    upper_n = 2
    while decision_power(upper_n) < float(target_power):
        upper_n *= 2
        if upper_n > 1_000_000_000:
            raise ValidationError(
                "equivalence power target exceeds supported numerical range"
            )
    lower_n = 2
    while lower_n < upper_n:
        middle = (lower_n + upper_n) // 2
        if decision_power(middle) >= float(target_power):
            upper_n = middle
        else:
            lower_n = middle + 1
    analyzable = lower_n
    enrollment = math.ceil(analyzable / (1 - float(attrition)))
    result: dict[str, Any] = {
        "planning_method": "normal_known_variance_direct_two_group_equivalence",
        "study_design": "independent_groups",
        "equivalence_margin": margin,
        "assumed_true_difference": true_difference,
        "assumed_standard_deviation": standard_deviation,
        "alpha": float(alpha),
        "confidence_level": 1 - 2 * float(alpha),
        "target_power": float(target_power),
        "achieved_model_power_at_integer_n": decision_power(analyzable),
        "analyzable_n_per_group": analyzable,
        "analyzable_total_n": analyzable * 2,
        "anticipated_attrition_fraction": float(attrition),
        "enrollment_n_per_group": enrollment,
        "enrollment_total_n": enrollment * 2,
        "assumptions": [
            "Equal independent group sizes and a continuous outcome.",
            "A common known standard deviation applies in the registered population.",
            "The estimator is normally distributed and equivalence requires the full 1-2alpha interval strictly within the symmetric margin.",
            "Power is conditional on the supplied true difference and variance; it is not observed power or evidence of equivalence.",
            "Attrition inflation does not correct selection bias or informative missingness.",
        ],
        "scientific_interpretation_verified": False,
    }
    if variance_ratio is not None:
        result["maximum_observed_to_assumed_sd_ratio"] = variance_ratio
    sensitivity: dict[str, Any] = {}
    for field, varied in (
        ("sensitivity_true_differences", "assumed_true_difference"),
        ("sensitivity_standard_deviations", "assumed_standard_deviation"),
    ):
        if field not in spec:
            continue
        scenarios = spec[field]
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 100:
            raise ValidationError(f"{field} must contain 1 to 100 assumptions")
        base = {
            key: value for key, value in spec.items()
            if key not in {"sensitivity_true_differences", "sensitivity_standard_deviations"}
        }
        plans = [
            plan_two_group_equivalence_power({**base, varied: value})
            for value in scenarios
        ]
        values = [plan[varied] for plan in plans]
        if len(set(values)) != len(values):
            raise ValidationError(f"{field} must contain distinct finite assumptions")
        sensitivity[varied] = [{
            varied: plan[varied],
            "analyzable_n_per_group": plan["analyzable_n_per_group"],
            "enrollment_n_per_group": plan["enrollment_n_per_group"],
            "achieved_model_power_at_integer_n": plan[
                "achieved_model_power_at_integer_n"
            ],
        } for plan in plans]
    if sensitivity:
        result["sensitivity"] = {
            **sensitivity,
            "notice": "Researcher-supplied hypothetical scenarios; no scenario is automatically selected and all other assumptions are held fixed.",
        }
    return result


def plan_two_group_practical_power(spec: dict[str, Any]) -> dict[str, Any]:
    """Power a confidence bound clearing a frozen practical-effect threshold."""
    allowed = {
        "study_design", "smallest_effect_size_of_interest", "assumed_true_effect",
        "assumed_standard_deviation", "alpha", "confidence_level", "target_power",
        "alternative", "anticipated_attrition_fraction",
        "maximum_observed_to_assumed_sd_ratio",
        "sensitivity_true_effects", "sensitivity_standard_deviations",
    }
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValidationError(
            "unknown practical-power fields: " + ", ".join(unknown)
        )
    if spec.get("study_design") != "independent_groups":
        raise ValidationError(
            "two-group practical power planning requires study_design independent_groups"
        )

    def finite(field: str) -> float:
        value = spec.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(f"{field} must be a finite number")
        converted = float(value)
        if not math.isfinite(converted):
            raise ValidationError(f"{field} must be a finite number")
        return converted

    threshold = finite("smallest_effect_size_of_interest")
    true_effect = finite("assumed_true_effect")
    standard_deviation = finite("assumed_standard_deviation")
    if threshold < 0 or standard_deviation <= 0:
        raise ValidationError(
            "smallest_effect_size_of_interest must be non-negative and assumed_standard_deviation positive"
        )
    alternative = spec.get("alternative")
    if alternative not in {"positive", "negative", "two_sided"}:
        raise ValidationError(
            "practical-power alternative must be positive, negative, or two_sided"
        )
    if (
        alternative == "positive" and true_effect <= threshold
        or alternative == "negative" and true_effect >= -threshold
        or alternative == "two_sided" and abs(true_effect) <= threshold
    ):
        raise ValidationError(
            "assumed_true_effect must lie beyond the practical-effect threshold in the registered direction"
        )
    alpha = spec.get("alpha", 0.05)
    confidence = spec.get("confidence_level", 0.95)
    target_power = spec.get("target_power", 0.8)
    attrition = spec.get("anticipated_attrition_fraction", 0)
    if (
        isinstance(alpha, bool) or not isinstance(alpha, (int, float))
        or not math.isfinite(float(alpha)) or not 0 < float(alpha) <= 0.2
    ):
        raise ValidationError("alpha must be a finite number in (0, 0.2]")
    if (
        isinstance(confidence, bool) or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence)) or not 0.8 <= float(confidence) < 1
        or not math.isclose(float(confidence), 1 - float(alpha), rel_tol=0, abs_tol=1e-12)
    ):
        raise ValidationError(
            "practical-power confidence_level must equal one minus alpha"
        )
    if (
        isinstance(target_power, bool) or not isinstance(target_power, (int, float))
        or not math.isfinite(float(target_power)) or not 0.5 < float(target_power) < 1
    ):
        raise ValidationError("target_power must be a finite number in (0.5, 1)")
    if (
        isinstance(attrition, bool) or not isinstance(attrition, (int, float))
        or not math.isfinite(float(attrition)) or not 0 <= float(attrition) < 0.9
    ):
        raise ValidationError(
            "anticipated_attrition_fraction must be a finite number in [0, 0.9)"
        )
    variance_ratio = _registered_variance_ratio(spec)
    normal = NormalDist()
    critical = -normal.inv_cdf((1 - float(confidence)) / 2)

    def decision_power(n_per_group: int) -> float:
        standard_error = standard_deviation * math.sqrt(2 / n_per_group)
        positive = 1 - normal.cdf(
            (threshold + critical * standard_error - true_effect) / standard_error
        )
        negative = normal.cdf(
            (-threshold - critical * standard_error - true_effect) / standard_error
        )
        return (
            positive if alternative == "positive" else
            negative if alternative == "negative" else positive + negative
        )

    upper_n = 2
    while decision_power(upper_n) < float(target_power):
        upper_n *= 2
        if upper_n > 1_000_000_000:
            raise ValidationError(
                "practical power target exceeds supported numerical range"
            )
    lower_n = 2
    while lower_n < upper_n:
        middle = (lower_n + upper_n) // 2
        if decision_power(middle) >= float(target_power):
            upper_n = middle
        else:
            lower_n = middle + 1
    analyzable = lower_n
    enrollment = math.ceil(analyzable / (1 - float(attrition)))
    result: dict[str, Any] = {
        "planning_method": "normal_known_variance_confidence_bound_beyond_practical_threshold",
        "study_design": "independent_groups",
        "smallest_effect_size_of_interest": threshold,
        "assumed_true_effect": true_effect,
        "assumed_standard_deviation": standard_deviation,
        "alpha": float(alpha), "confidence_level": float(confidence),
        "target_power": float(target_power), "alternative": alternative,
        "achieved_model_power_at_integer_n": decision_power(analyzable),
        "analyzable_n_per_group": analyzable,
        "analyzable_total_n": analyzable * 2,
        "anticipated_attrition_fraction": float(attrition),
        "enrollment_n_per_group": enrollment,
        "enrollment_total_n": enrollment * 2,
        "assumptions": [
            "Equal independent group sizes and a continuous outcome.",
            "A common known standard deviation applies in the registered population.",
            "The estimator is normally distributed and the full two-sided confidence bound must clear the practical threshold in the registered direction.",
            "Power is conditional on a supplied true effect beyond the threshold; it is not observed power or proof of practical importance.",
            "This direct single-test calculation does not power a multiplicity-adjusted family decision.",
        ],
        "scientific_interpretation_verified": False,
    }
    if variance_ratio is not None:
        result["maximum_observed_to_assumed_sd_ratio"] = variance_ratio
    sensitivity: dict[str, Any] = {}
    for field, varied in (
        ("sensitivity_true_effects", "assumed_true_effect"),
        ("sensitivity_standard_deviations", "assumed_standard_deviation"),
    ):
        if field not in spec:
            continue
        scenarios = spec[field]
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 100:
            raise ValidationError(f"{field} must contain 1 to 100 assumptions")
        base = {key: value for key, value in spec.items() if key not in {
            "sensitivity_true_effects", "sensitivity_standard_deviations",
        }}
        plans = [plan_two_group_practical_power({**base, varied: value}) for value in scenarios]
        values = [plan[varied] for plan in plans]
        if len(set(values)) != len(values):
            raise ValidationError(f"{field} must contain distinct finite assumptions")
        sensitivity[varied] = [{
            varied: plan[varied],
            "analyzable_n_per_group": plan["analyzable_n_per_group"],
            "enrollment_n_per_group": plan["enrollment_n_per_group"],
            "achieved_model_power_at_integer_n": plan["achieved_model_power_at_integer_n"],
        } for plan in plans]
    if sensitivity:
        result["sensitivity"] = {
            **sensitivity,
            "notice": "Researcher-supplied hypothetical scenarios; no scenario is automatically selected and all other assumptions are held fixed.",
        }
    return result
