"""Conservative inverse-variance meta-analysis for plan-bound effect records."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import NormalDist
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.deviations import (
    validate_retained_synthesis_deviations,
    validate_frozen_plan_commitments_boundary,
    validate_synthesis_deviations_boundary,
)
from research_machine.literature.effect_verification import validate_effect_verification_boundary
from research_machine.literature.effects import (
    retained_source_summary_sha256,
    validate_effect_records_boundary,
    validate_retained_source_summaries,
)
from research_machine.literature.hashes import require_sha256
from research_machine.literature.synthesis_plan import (
    QUANTITATIVE_SENSITIVITIES,
    validate_synthesis_plan_boundary,
)
from research_machine.literature.verification import _validate_passage_receipt

_LEGACY_SOURCE_ANCHOR = "legacy_missing"
_DEVIATION_STATUSES = {
    "no_deviations_declared",
    "prospective_deviations_recorded",
    "retrospective_or_uncertain_deviation_review_required",
}
_META_ANALYSIS_PROSE_OVERCLAIM = re.compile(
    r"\b(?:proved|confirmed|explained|validates?|validated)\b",
    re.IGNORECASE,
)


_T_CRITICAL_975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
    7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
    13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
    19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
    25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def _t_critical_95(degrees_of_freedom: int) -> float:
    """Conservative tabulated two-sided .975 critical value without dependencies."""
    if degrees_of_freedom <= 0:
        raise ValidationError("Student-t inference requires positive degrees of freedom")
    if degrees_of_freedom <= 30:
        return _T_CRITICAL_975[degrees_of_freedom]
    # Standard reference-table cut points; choosing the lower boundary is conservative.
    if degrees_of_freedom <= 40:
        return 2.042
    if degrees_of_freedom <= 60:
        return 2.021
    if degrees_of_freedom <= 120:
        return 2.000
    return 1.980


def _load(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        content = path.read_bytes(); value = json.loads(content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(f"could not read valid {label} JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value, hashlib.sha256(content).hexdigest()


def _canonical_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be non-empty text")
    if value != value.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return value


def _bounded_meta_text(value: Any, field: str) -> str:
    text = _canonical_text(value, field)
    if _META_ANALYSIS_PROSE_OVERCLAIM.search(text):
        raise ValidationError(
            f"{field} uses meta-analysis prohibited overclaiming language; "
            "describe availability, sensitivity, or diagnostics without claiming "
            "proof, confirmation, validation, or explanation"
        )
    return text


def _source_anchor(value: object, field: str) -> str:
    if value == _LEGACY_SOURCE_ANCHOR:
        return _LEGACY_SOURCE_ANCHOR
    return require_sha256(value, field)


def _claim_source_provenance(claims: list[object], field_prefix: str) -> list[dict[str, Any]]:
    retained = []
    seen_claims = set()
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValidationError(f"{field_prefix} claim source provenance is malformed")
        extraction_id = _canonical_text(
            claim.get("extraction_id"), f"{field_prefix} extraction_id"
        )
        if extraction_id in seen_claims:
            raise ValidationError(f"{field_prefix} claim source provenance requires unique extraction IDs")
        seen_claims.add(extraction_id)
        claim_summary = {
            "extraction_id": extraction_id,
            "extraction_claim_sha256": require_sha256(
                claim.get("extraction_claim_sha256"),
                f"{field_prefix} extraction_claim_sha256",
            ),
            "source_id": _canonical_text(claim.get("source_id"), f"{field_prefix} source_id"),
            "source_retained_file_sha256": _source_anchor(
                claim.get("source_retained_file_sha256", _LEGACY_SOURCE_ANCHOR),
                f"{field_prefix} source_retained_file_sha256",
            ),
            "citation_checked_location": _canonical_text(
                claim.get("citation_checked_location"),
                f"{field_prefix} citation_checked_location",
            ),
        }
        if "passage_verification" in claim:
            claim_summary["passage_verification"] = _validate_passage_receipt(
                claim.get("passage_verification"),
                f"{field_prefix} passage_verification",
            )
        retained.append(claim_summary)
    return sorted(retained, key=lambda claim: claim["extraction_id"])


def _finite_float(value: Any, field: str, *, positive: bool = False, non_negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValidationError(f"{field} must be finite numeric data")
    result = float(value)
    if positive and result <= 0:
        raise ValidationError(f"{field} must be positive")
    if non_negative and result < 0:
        raise ValidationError(f"{field} must be non-negative")
    return result


def _finite_interval(value: Any, field: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValidationError(f"{field} must be a two-value interval")
    lower = _finite_float(value[0], f"{field} lower")
    upper = _finite_float(value[1], f"{field} upper")
    if lower > upper:
        raise ValidationError(f"{field} bounds must be ordered")
    return [lower, upper]


def _assert_close(value: float, expected: float, field: str) -> None:
    if not math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-12):
        raise ValidationError(f"{field} does not replay from retained numeric fields")


def _weighted(records: list[dict[str, Any]], tau_squared: float = 0.0) -> tuple[float, float]:
    weights = [1.0 / (item["variance"] + tau_squared) for item in records]
    total = sum(weights)
    return sum(weight * item["estimate"] for weight, item in zip(weights, records)) / total, math.sqrt(1.0 / total)


def _egger_diagnostic(records: list[dict[str, Any]]) -> dict[str, Any]:
    if len(records) < 10:
        return {"status": "not_estimable", "reason": "fewer than 10 available effects",
                "study_count": len(records), "publication_bias_conclusion": False}
    precision = [1.0 / math.sqrt(item["variance"]) for item in records]
    standardized = [item["estimate"] / math.sqrt(item["variance"]) for item in records]
    x_mean, y_mean = sum(precision) / len(records), sum(standardized) / len(records)
    sxx = sum((value - x_mean) ** 2 for value in precision)
    if sxx <= 0:
        return {"status": "not_estimable", "reason": "effect precisions do not vary",
                "study_count": len(records), "publication_bias_conclusion": False}
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(precision, standardized)) / sxx
    intercept = y_mean - slope * x_mean
    residuals = [y - (intercept + slope * x) for x, y in zip(precision, standardized)]
    degrees_of_freedom = len(records) - 2
    residual_variance = sum(value ** 2 for value in residuals) / degrees_of_freedom
    standard_error = math.sqrt(residual_variance * (1.0 / len(records) + x_mean ** 2 / sxx))
    critical = _t_critical_95(degrees_of_freedom)
    return {"status": "estimated", "method": "egger_standardized_effect_on_precision_ols",
            "study_count": len(records), "intercept": intercept, "slope": slope,
            "intercept_standard_error": standard_error,
            "intercept_confidence_interval_95": [intercept - critical * standard_error,
                                                  intercept + critical * standard_error],
            "degrees_of_freedom": degrees_of_freedom, "critical_value_95": critical,
            "publication_bias_conclusion": False,
            "interpretation_boundary": "Funnel asymmetry can reflect heterogeneity, selection, measurement, or chance; this diagnostic does not establish publication bias."}


def validate_meta_analysis_boundary(
    meta_analysis: dict[str, Any],
    *,
    planned_sensitivity_analyses: list[str] | None = None,
) -> None:
    """Replay meta-analysis non-authority, study-count, and sensitivity boundaries."""
    if meta_analysis.get("meta_analysis_version") != 1:
        raise ValidationError("meta-analysis version is invalid")
    inputs = meta_analysis.get("inputs")
    required_inputs = {
        "synthesis_plan_sha256",
        "effect_records_sha256",
        "effect_verification_sha256",
        "synthesis_deviations_sha256",
    }
    if not isinstance(inputs, dict) or set(inputs) != required_inputs:
        raise ValidationError("meta-analysis inputs do not match the documented contract")
    for key in sorted(required_inputs):
        require_sha256(inputs.get(key), f"meta-analysis input {key}")
    _canonical_text(meta_analysis.get("plan_id"), "meta-analysis plan_id")
    _canonical_text(meta_analysis.get("snapshot_id"), "meta-analysis snapshot_id")
    contrast_definition = _canonical_text(
        meta_analysis.get("contrast_definition"), "meta-analysis contrast_definition"
    )
    if contrast_definition == "not_applicable":
        raise ValidationError("meta-analysis requires a frozen quantitative contrast_definition")
    if meta_analysis.get("scientific_evidence_eligible") is not False:
        raise ValidationError("meta-analysis must remain scientifically ineligible")
    if meta_analysis.get("conclusion_authorized") is not False:
        raise ValidationError("meta-analysis must not authorize conclusions")
    if meta_analysis.get("publication_authorized") is not False:
        raise ValidationError("meta-analysis must not authorize publication claims")
    if meta_analysis.get("reviewer_identity_authenticated", False) is not False:
        raise ValidationError("meta-analysis must not authenticate reviewer identity")
    limitations = meta_analysis.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise ValidationError("meta-analysis requires retained boundary limitations")
    for index, limitation in enumerate(limitations):
        _bounded_meta_text(limitation, f"meta-analysis limitation {index + 1}")

    deviation_status = meta_analysis.get("deviation_status")
    if deviation_status not in _DEVIATION_STATUSES:
        raise ValidationError("meta-analysis deviation_status is invalid")
    _retained_deviations, _timing_counts, retained_deviation_status = validate_retained_synthesis_deviations(
        meta_analysis.get("deviations"), synthesis_type="quantitative"
    )
    if retained_deviation_status != deviation_status:
        raise ValidationError("meta-analysis deviation_status does not replay from retained deviations")
    expected_status = (
        "meta_analysis_deviation_review_required"
        if deviation_status == "retrospective_or_uncertain_deviation_review_required"
        else "meta_analysis_recorded"
    )
    if meta_analysis.get("status") != expected_status:
        raise ValidationError("meta-analysis status does not replay from deviation status")
    commitments = meta_analysis.get("deviation_plan_commitments")
    validate_frozen_plan_commitments_boundary(commitments)
    if (commitments.get("synthesis_type") != "quantitative"
            or commitments.get("effect_measure") != meta_analysis.get("effect_measure")
            or commitments.get("contrast_definition") != contrast_definition
            or commitments.get("statistical_model") != meta_analysis.get("statistical_model")):
        raise ValidationError("meta-analysis deviation-plan commitments do not replay")

    study_provenance = meta_analysis.get("study_provenance")
    if not isinstance(study_provenance, list) or not study_provenance:
        raise ValidationError("meta-analysis requires retained study provenance")
    effect_statuses: dict[str, str] = {}
    available_ids: set[str] = set()
    unavailable_ids: set[str] = set()
    retained_effect_inputs: list[dict[str, Any]] = []
    for item in study_provenance:
        if not isinstance(item, dict):
            raise ValidationError("meta-analysis study provenance is malformed")
        study_id = _canonical_text(item.get("study_id"), "meta-analysis study_id")
        if study_id in effect_statuses:
            raise ValidationError("meta-analysis study provenance requires unique study IDs")
        effect_status = item.get("effect_status")
        if effect_status not in {"available", "unavailable"}:
            raise ValidationError("meta-analysis effect_status is invalid")
        effect_statuses[study_id] = effect_status
        if effect_status == "available":
            available_ids.add(study_id)
            effect_estimate = _finite_float(
                item.get("effect_estimate"),
                "meta-analysis retained effect_estimate",
            )
            effect_standard_error = _finite_float(
                item.get("effect_standard_error"),
                "meta-analysis retained effect_standard_error",
                positive=True,
            )
            effect_variance = _finite_float(
                item.get("effect_variance"),
                "meta-analysis retained effect_variance",
                positive=True,
            )
            _assert_close(
                effect_variance,
                effect_standard_error ** 2,
                "meta-analysis retained effect_variance",
            )
            retained_effect_inputs.append({
                "study_id": study_id,
                "estimate": effect_estimate,
                "variance": effect_variance,
            })
        else:
            unavailable_ids.add(study_id)
            if any(
                item.get(field) is not None
                for field in (
                    "effect_estimate",
                    "effect_standard_error",
                    "effect_variance",
                )
            ):
                raise ValidationError("meta-analysis unavailable studies require null retained effect inputs")
        if item.get("risk_of_bias") not in {"low", "some_concerns", "high", "unclear"}:
            raise ValidationError("meta-analysis study provenance requires retained risk_of_bias")
        mapped_claim_ids = item.get("mapped_claim_ids")
        if (not isinstance(mapped_claim_ids, list) or not mapped_claim_ids
                or any(not isinstance(claim_id, str) or not claim_id.strip()
                       or claim_id != claim_id.strip() for claim_id in mapped_claim_ids)
                or len(mapped_claim_ids) != len(set(mapped_claim_ids))):
            raise ValidationError("meta-analysis mapped_claim_ids must be unique canonical text")
        retained_digest = require_sha256(
            item.get("retained_source_summary_sha256"),
            "meta-analysis retained_source_summary_sha256",
        )
        mapped_claim_source_provenance = item.get("mapped_claim_source_provenance")
        if not isinstance(mapped_claim_source_provenance, list) or not mapped_claim_source_provenance:
            raise ValidationError("meta-analysis mapped claim source provenance is missing")
        mapped_claims = _claim_source_provenance(
            mapped_claim_source_provenance, "meta-analysis mapped claim"
        )
        if [claim["extraction_id"] for claim in mapped_claims] != mapped_claim_ids:
            raise ValidationError("meta-analysis mapped_claim_ids do not replay from claim provenance")
        verification = item.get("effect_verification")
        if not isinstance(verification, dict):
            raise ValidationError("meta-analysis effect verification provenance is malformed")
        if (_canonical_text(verification.get("study_id"), "meta-analysis verification study_id") != study_id
                or verification.get("effect_status") != effect_status):
            raise ValidationError("meta-analysis verification provenance does not match study status")
        if require_sha256(
            verification.get("retained_source_summary_sha256"),
            "meta-analysis verification retained_source_summary_sha256",
        ) != retained_digest:
            raise ValidationError("meta-analysis verification source-summary digest does not match study provenance")
        verification_claims = verification.get("claim_source_provenance")
        if not isinstance(verification_claims, list) or not verification_claims:
            raise ValidationError("meta-analysis verification claim source provenance is missing")
        if _claim_source_provenance(verification_claims, "meta-analysis verification claim") != mapped_claims:
            raise ValidationError("meta-analysis verification claim provenance does not match study provenance")
        _canonical_text(
            verification.get("checked_location"),
            "meta-analysis verification checked_location",
        )
        source_values_match = verification.get("source_values_match")
        calculation_matches = verification.get("calculation_matches")
        if effect_status == "available":
            if source_values_match is not True or calculation_matches is not True:
                raise ValidationError("meta-analysis available effects require clean verification checks")
        elif source_values_match is not None or calculation_matches is not None:
            raise ValidationError("meta-analysis unavailable effects require not-applicable verification checks")

    available_count = meta_analysis.get("available_study_count")
    if isinstance(available_count, bool) or available_count != len(available_ids):
        raise ValidationError("meta-analysis available_study_count does not replay from provenance")
    unavailable = meta_analysis.get("unavailable_studies")
    if not isinstance(unavailable, list):
        raise ValidationError("meta-analysis unavailable_studies must be an array")
    unavailable_seen = set()
    for item in unavailable:
        if not isinstance(item, dict) or set(item) != {"study_id", "reason"}:
            raise ValidationError("meta-analysis unavailable study fields do not match the documented contract")
        study_id = _canonical_text(item.get("study_id"), "meta-analysis unavailable study_id")
        if study_id in unavailable_seen:
            raise ValidationError("meta-analysis unavailable_studies requires unique study IDs")
        unavailable_seen.add(study_id)
        _bounded_meta_text(item.get("reason"), "meta-analysis unavailable reason")
    if unavailable_seen != unavailable_ids:
        raise ValidationError("meta-analysis unavailable_studies do not replay from provenance")

    model = meta_analysis.get("statistical_model")
    if model not in {"fixed_effect", "random_effects"}:
        raise ValidationError("meta-analysis statistical_model is invalid")
    pooled_estimate = _finite_float(meta_analysis.get("pooled_estimate"), "meta-analysis pooled_estimate")
    standard_error = _finite_float(
        meta_analysis.get("standard_error"), "meta-analysis standard_error", positive=True
    )
    conventional_standard_error = _finite_float(
        meta_analysis.get("conventional_standard_error"),
        "meta-analysis conventional_standard_error",
        positive=True,
    )
    critical_value = _finite_float(
        meta_analysis.get("critical_value_95"), "meta-analysis critical_value_95", positive=True
    )
    confidence_interval = _finite_interval(
        meta_analysis.get("confidence_interval_95"), "meta-analysis confidence_interval_95"
    )
    _assert_close(
        confidence_interval[0],
        pooled_estimate - critical_value * standard_error,
        "meta-analysis confidence_interval_95 lower",
    )
    _assert_close(
        confidence_interval[1],
        pooled_estimate + critical_value * standard_error,
        "meta-analysis confidence_interval_95 upper",
    )
    hartung_knapp = meta_analysis.get("hartung_knapp_standard_error")
    inference_method = meta_analysis.get("inference_method")
    if model == "fixed_effect":
        if hartung_knapp is not None or inference_method != "fixed_effect_normal_95":
            raise ValidationError("fixed-effect meta-analysis must retain the fixed-effect inference method")
        _assert_close(
            standard_error,
            conventional_standard_error,
            "fixed-effect meta-analysis standard_error",
        )
    else:
        _finite_float(hartung_knapp, "meta-analysis hartung_knapp_standard_error", positive=True)
        if inference_method != "modified_hartung_knapp_student_t_95":
            raise ValidationError("random-effects meta-analysis must retain the Hartung-Knapp inference method")

    retained_source_summaries = validate_retained_source_summaries(
        meta_analysis.get("retained_source_summaries"),
        expected_statuses=effect_statuses,
        effect_measure=_canonical_text(meta_analysis.get("effect_measure"), "meta-analysis effect_measure"),
    )
    summary_digests = {
        summary["study_id"]: retained_source_summary_sha256(summary)
        for summary in retained_source_summaries
    }
    for item in study_provenance:
        study_id = item["study_id"]
        if item["retained_source_summary_sha256"] != summary_digests[study_id]:
            raise ValidationError("meta-analysis retained source summaries do not match study provenance")

    heterogeneity = meta_analysis.get("heterogeneity")
    required_heterogeneity = {
        "q",
        "degrees_of_freedom",
        "i_squared_percent",
        "tau_squared_der_simonian_laird",
    }
    if not isinstance(heterogeneity, dict) or set(heterogeneity) != required_heterogeneity:
        raise ValidationError("meta-analysis heterogeneity fields do not match the documented contract")
    fixed_estimate, _fixed_se = _weighted(retained_effect_inputs)
    fixed_weights = [1.0 / item["variance"] for item in retained_effect_inputs]
    expected_q = sum(
        weight * (item["estimate"] - fixed_estimate) ** 2
        for weight, item in zip(fixed_weights, retained_effect_inputs)
    )
    expected_degrees_of_freedom = len(retained_effect_inputs) - 1
    denominator = (
        sum(fixed_weights)
        - sum(weight ** 2 for weight in fixed_weights) / sum(fixed_weights)
    )
    expected_tau_squared = (
        max(0.0, (expected_q - expected_degrees_of_freedom) / denominator)
        if denominator > 0
        else 0.0
    )
    expected_i_squared = (
        max(0.0, (expected_q - expected_degrees_of_freedom) / expected_q) * 100.0
        if expected_q > 0
        else 0.0
    )
    observed_q = _finite_float(
        heterogeneity.get("q"), "meta-analysis heterogeneity q", non_negative=True
    )
    _assert_close(observed_q, expected_q, "meta-analysis heterogeneity q")
    degrees_of_freedom = heterogeneity.get("degrees_of_freedom")
    if (isinstance(degrees_of_freedom, bool) or not isinstance(degrees_of_freedom, int)
            or degrees_of_freedom != expected_degrees_of_freedom):
        raise ValidationError("meta-analysis heterogeneity degrees_of_freedom does not replay from available studies")
    observed_i_squared = _finite_float(
        heterogeneity.get("i_squared_percent"),
        "meta-analysis heterogeneity i_squared_percent",
        non_negative=True,
    )
    _assert_close(
        observed_i_squared,
        expected_i_squared,
        "meta-analysis heterogeneity i_squared_percent",
    )
    observed_tau_squared = _finite_float(
        heterogeneity.get("tau_squared_der_simonian_laird"),
        "meta-analysis heterogeneity tau_squared_der_simonian_laird",
        non_negative=True,
    )
    _assert_close(
        observed_tau_squared,
        expected_tau_squared,
        "meta-analysis heterogeneity tau_squared_der_simonian_laird",
    )
    tau_for_model = expected_tau_squared if model == "random_effects" else 0.0
    expected_pooled_estimate, expected_conventional_se = _weighted(
        retained_effect_inputs, tau_for_model
    )
    _assert_close(
        pooled_estimate,
        expected_pooled_estimate,
        "meta-analysis pooled_estimate",
    )
    _assert_close(
        conventional_standard_error,
        expected_conventional_se,
        "meta-analysis conventional_standard_error",
    )
    if model == "random_effects":
        random_weights = [
            1.0 / (item["variance"] + expected_tau_squared)
            for item in retained_effect_inputs
        ]
        expected_hartung_knapp = math.sqrt(
            sum(
                weight * (item["estimate"] - expected_pooled_estimate) ** 2
                for weight, item in zip(random_weights, retained_effect_inputs)
            )
            / expected_degrees_of_freedom
            / sum(random_weights)
        )
        _assert_close(
            float(hartung_knapp),
            expected_hartung_knapp,
            "meta-analysis hartung_knapp_standard_error",
        )
        _assert_close(
            standard_error,
            max(expected_conventional_se, expected_hartung_knapp),
            "meta-analysis standard_error",
        )
        _assert_close(
            critical_value,
            _t_critical_95(expected_degrees_of_freedom),
            "meta-analysis critical_value_95",
        )
    else:
        _assert_close(
            critical_value,
            NormalDist().inv_cdf(0.975),
            "meta-analysis critical_value_95",
        )
    prediction_interval = meta_analysis.get("prediction_interval_95")
    if prediction_interval is None:
        if model == "random_effects" and len(available_ids) >= 3:
            raise ValidationError("random-effects meta-analysis requires a prediction interval for three or more studies")
    else:
        if model != "random_effects" or len(available_ids) < 3:
            raise ValidationError("meta-analysis prediction interval is not allowed for this model or study count")
        prediction_bounds = _finite_interval(
            prediction_interval, "meta-analysis prediction_interval_95"
        )
        expected_prediction_spread = math.sqrt(expected_tau_squared + standard_error ** 2)
        _assert_close(
            prediction_bounds[0],
            pooled_estimate - critical_value * expected_prediction_spread,
            "meta-analysis prediction_interval_95 lower",
        )
        _assert_close(
            prediction_bounds[1],
            pooled_estimate + critical_value * expected_prediction_spread,
            "meta-analysis prediction_interval_95 upper",
        )

    leave_one_out = meta_analysis.get("leave_one_study_out")
    if not isinstance(leave_one_out, list):
        raise ValidationError("meta-analysis leave_one_study_out must be an array")
    excluded_seen = set()
    normal_critical = NormalDist().inv_cdf(0.975)
    for item in leave_one_out:
        if not isinstance(item, dict) or set(item) != {
            "excluded_study_id",
            "estimate",
            "standard_error",
            "confidence_interval_95_normal_approximation",
        }:
            raise ValidationError("meta-analysis leave-one-out fields do not match the documented contract")
        excluded = _canonical_text(item.get("excluded_study_id"), "meta-analysis excluded_study_id")
        if excluded not in available_ids or excluded in excluded_seen:
            raise ValidationError("meta-analysis leave-one-out coverage does not match available studies")
        excluded_seen.add(excluded)
        remaining = [
            retained
            for retained in retained_effect_inputs
            if retained["study_id"] != excluded
        ]
        expected_loo_estimate, expected_loo_se = _weighted(remaining, tau_for_model)
        loo_estimate = _finite_float(item.get("estimate"), "meta-analysis leave-one-out estimate")
        loo_se = _finite_float(
            item.get("standard_error"), "meta-analysis leave-one-out standard_error", positive=True
        )
        _assert_close(
            loo_estimate,
            expected_loo_estimate,
            "meta-analysis leave-one-out estimate",
        )
        _assert_close(
            loo_se,
            expected_loo_se,
            "meta-analysis leave-one-out standard_error",
        )
        loo_interval = _finite_interval(
            item.get("confidence_interval_95_normal_approximation"),
            "meta-analysis leave-one-out confidence_interval_95_normal_approximation",
        )
        _assert_close(
            loo_interval[0],
            loo_estimate - normal_critical * loo_se,
            "meta-analysis leave-one-out confidence interval lower",
        )
        _assert_close(
            loo_interval[1],
            loo_estimate + normal_critical * loo_se,
            "meta-analysis leave-one-out confidence interval upper",
        )
    if excluded_seen != available_ids:
        raise ValidationError("meta-analysis leave-one-out results must cover every available study")

    sensitivity_results = meta_analysis.get("planned_sensitivity_results")
    if not isinstance(sensitivity_results, list) or not sensitivity_results:
        raise ValidationError("meta-analysis requires retained planned sensitivity results")
    retained_plan = meta_analysis.get("planned_sensitivity_analyses")
    if not isinstance(retained_plan, list) or not retained_plan:
        raise ValidationError("meta-analysis requires retained planned sensitivity analyses")
    retained_sensitivity_names = []
    for index, name in enumerate(retained_plan):
        retained_name = _canonical_text(
            name, f"meta-analysis planned sensitivity analysis {index + 1}"
        )
        if retained_name in retained_sensitivity_names:
            raise ValidationError("meta-analysis planned sensitivity analyses must be unique")
        if retained_name not in QUANTITATIVE_SENSITIVITIES:
            raise ValidationError(
                "meta-analysis retained an unknown executable quantitative sensitivity analysis"
            )
        retained_sensitivity_names.append(retained_name)
    sensitivity_names = []
    for item in sensitivity_results:
        if not isinstance(item, dict):
            raise ValidationError("meta-analysis sensitivity result is malformed")
        name = _canonical_text(item.get("analysis"), "meta-analysis sensitivity analysis")
        if name in sensitivity_names:
            raise ValidationError("meta-analysis sensitivity results require unique analysis names")
        sensitivity_names.append(name)
        if item.get("status") not in {"completed", "not_estimable"}:
            raise ValidationError("meta-analysis sensitivity status is invalid")
        status = item["status"]
        if name == "leave_one_study_out":
            if status != "completed" or item.get("results") != leave_one_out:
                raise ValidationError("meta-analysis leave-one-study-out sensitivity must replay from retained diagnostics")
        elif status == "completed":
            sensitivity_estimate = _finite_float(
                item.get("estimate"),
                f"meta-analysis sensitivity {name} estimate",
            )
            sensitivity_standard_error = _finite_float(
                item.get("standard_error_normal_approximation"),
                f"meta-analysis sensitivity {name} standard_error_normal_approximation",
                positive=True,
            )
            if "remaining_study_count" in item:
                remaining = item["remaining_study_count"]
                if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 2:
                    raise ValidationError("meta-analysis completed sensitivity remaining_study_count is invalid")
            if name == "exclude_high_or_unclear_bias":
                subset = [
                    {
                        "study_id": provenance["study_id"],
                        "estimate": provenance["effect_estimate"],
                        "variance": provenance["effect_variance"],
                    }
                    for provenance in study_provenance
                    if provenance["effect_status"] == "available"
                    and provenance["risk_of_bias"] not in {"high", "unclear"}
                ]
                if len(subset) < 2:
                    raise ValidationError("meta-analysis bias-exclusion sensitivity should be not-estimable")
                expected_sensitivity_estimate, expected_sensitivity_se = _weighted(
                    subset, tau_for_model
                )
                if item.get("remaining_study_count") != len(subset):
                    raise ValidationError("meta-analysis bias-exclusion sensitivity count does not replay")
            elif name == "alternate_fixed_effect":
                expected_sensitivity_estimate, expected_sensitivity_se = _weighted(
                    retained_effect_inputs, 0.0
                )
            elif name == "alternate_random_effects":
                expected_sensitivity_estimate, expected_sensitivity_se = _weighted(
                    retained_effect_inputs, expected_tau_squared
                )
            else:
                expected_sensitivity_estimate = expected_sensitivity_se = None
            if expected_sensitivity_estimate is not None:
                _assert_close(
                    sensitivity_estimate,
                    expected_sensitivity_estimate,
                    f"meta-analysis sensitivity {name} estimate",
                )
                _assert_close(
                    sensitivity_standard_error,
                    expected_sensitivity_se,
                    f"meta-analysis sensitivity {name} standard_error_normal_approximation",
                )
        else:
            _bounded_meta_text(
                item.get("reason"),
                f"meta-analysis sensitivity {name} reason",
            )
            remaining = item.get("remaining_study_count")
            if (remaining is not None
                    and (isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 0)):
                raise ValidationError("meta-analysis not-estimable sensitivity remaining_study_count is invalid")
            if name == "exclude_high_or_unclear_bias":
                subset_count = sum(
                    1
                    for provenance in study_provenance
                    if provenance["effect_status"] == "available"
                    and provenance["risk_of_bias"] not in {"high", "unclear"}
                )
                if remaining != subset_count or subset_count >= 2:
                    raise ValidationError("meta-analysis bias-exclusion sensitivity status does not replay")
    if sensitivity_names != retained_sensitivity_names:
        raise ValidationError("meta-analysis sensitivity results do not replay from retained planned analyses")
    if planned_sensitivity_analyses is not None and retained_sensitivity_names != planned_sensitivity_analyses:
        raise ValidationError("meta-analysis sensitivity results do not cover the frozen plan exactly")

    small_study_effects = meta_analysis.get("small_study_effects")
    if not isinstance(small_study_effects, dict):
        raise ValidationError("meta-analysis small-study diagnostic is missing")
    if small_study_effects.get("status") not in {"estimated", "not_estimable"}:
        raise ValidationError("meta-analysis small-study diagnostic status is invalid")
    if small_study_effects.get("publication_bias_conclusion") is not False:
        raise ValidationError("meta-analysis small-study diagnostic must not authorize publication-bias conclusions")
    expected_small_study_effects = _egger_diagnostic(retained_effect_inputs)
    if small_study_effects.get("status") == "estimated":
        required_egger = {
            "status",
            "method",
            "study_count",
            "intercept",
            "slope",
            "intercept_standard_error",
            "intercept_confidence_interval_95",
            "degrees_of_freedom",
            "critical_value_95",
            "publication_bias_conclusion",
            "interpretation_boundary",
        }
        if set(small_study_effects) != required_egger:
            raise ValidationError("estimated small-study diagnostic fields do not match the documented contract")
        if small_study_effects.get("method") != "egger_standardized_effect_on_precision_ols":
            raise ValidationError("estimated small-study diagnostic method is invalid")
        if small_study_effects.get("study_count") != len(available_ids):
            raise ValidationError("small-study diagnostic count does not replay from available studies")
        intercept = _finite_float(small_study_effects.get("intercept"), "small-study intercept")
        slope = _finite_float(small_study_effects.get("slope"), "small-study slope")
        egger_se = _finite_float(
            small_study_effects.get("intercept_standard_error"),
            "small-study intercept_standard_error",
            positive=True,
        )
        egger_critical = _finite_float(
            small_study_effects.get("critical_value_95"),
            "small-study critical_value_95",
            positive=True,
        )
        egger_interval = _finite_interval(
            small_study_effects.get("intercept_confidence_interval_95"),
            "small-study intercept_confidence_interval_95",
        )
        _assert_close(
            egger_interval[0],
            intercept - egger_critical * egger_se,
            "small-study confidence interval lower",
        )
        _assert_close(
            egger_interval[1],
            intercept + egger_critical * egger_se,
            "small-study confidence interval upper",
        )
        if small_study_effects.get("degrees_of_freedom") != len(available_ids) - 2:
            raise ValidationError("small-study diagnostic degrees_of_freedom does not replay from available studies")
        if expected_small_study_effects["status"] != "estimated":
            raise ValidationError("small-study diagnostic status does not replay from retained effects")
        _assert_close(
            intercept,
            expected_small_study_effects["intercept"],
            "small-study intercept",
        )
        _assert_close(
            slope,
            expected_small_study_effects["slope"],
            "small-study slope",
        )
        _assert_close(
            egger_se,
            expected_small_study_effects["intercept_standard_error"],
            "small-study intercept_standard_error",
        )
        _assert_close(
            egger_critical,
            expected_small_study_effects["critical_value_95"],
            "small-study critical_value_95",
        )
        boundary = _bounded_meta_text(
            small_study_effects.get("interpretation_boundary"),
            "meta-analysis small-study interpretation boundary",
        )
        if boundary != expected_small_study_effects["interpretation_boundary"]:
            raise ValidationError("small-study diagnostic interpretation boundary does not replay")
    else:
        required_not_estimable = {"status", "reason", "study_count", "publication_bias_conclusion"}
        if set(small_study_effects) != required_not_estimable:
            raise ValidationError("not-estimable small-study diagnostic fields do not match the documented contract")
        _bounded_meta_text(small_study_effects.get("reason"), "small-study not-estimable reason")
        if small_study_effects.get("study_count") != len(available_ids):
            raise ValidationError("small-study diagnostic count does not replay from available studies")
        if (expected_small_study_effects["status"] != "not_estimable"
                or small_study_effects.get("reason") != expected_small_study_effects["reason"]):
            raise ValidationError("small-study diagnostic status does not replay from retained effects")


def execute_meta_analysis(
    plan_path: Path,
    expected_plan_sha256: str,
    effects_path: Path,
    expected_effects_sha256: str,
    effect_verification_path: Path,
    expected_effect_verification_sha256: str,
    deviations_path: Path,
    expected_deviations_sha256: str,
    output: Path,
) -> dict[str, Any]:
    expected_plan_sha256 = require_sha256(expected_plan_sha256, "expected_plan_sha256")
    expected_effects_sha256 = require_sha256(expected_effects_sha256, "expected_effects_sha256")
    expected_effect_verification_sha256 = require_sha256(
        expected_effect_verification_sha256, "expected_effect_verification_sha256"
    )
    expected_deviations_sha256 = require_sha256(
        expected_deviations_sha256, "expected_deviations_sha256"
    )
    plan, plan_sha = _load(plan_path, "synthesis plan")
    effects, effects_sha = _load(effects_path, "effect records")
    effect_verification, effect_verification_sha = _load(effect_verification_path, "effect verification")
    deviations, deviations_sha = _load(deviations_path, "synthesis deviations")
    if (plan_sha != expected_plan_sha256 or effects_sha != expected_effects_sha256
            or effect_verification_sha != expected_effect_verification_sha256
            or deviations_sha != expected_deviations_sha256):
        raise ValidationError("meta-analysis input does not match an expected SHA-256")
    if (plan.get("synthesis_plan_version") != 1 or plan.get("status") != "synthesis_plan_frozen"
            or plan.get("synthesis_type") != "quantitative"):
        raise ValidationError("meta-analysis requires a frozen quantitative synthesis plan")
    validate_synthesis_plan_boundary(plan)
    if (effects.get("effect_records_version") != 1 or effects.get("status") != "effects_ready"
            or not isinstance(effects.get("inputs"), dict)
            or effects["inputs"].get("synthesis_plan_sha256") != plan_sha):
        raise ValidationError("meta-analysis requires ready effect records bound to the supplied plan")
    validate_effect_records_boundary(effects)
    if effects.get("effect_measure") != plan.get("effect_measure"):
        raise ValidationError("effect records do not match the frozen effect measure")
    plan_contrast = _canonical_text(
        plan.get("contrast_definition"), "meta-analysis plan contrast_definition"
    )
    if plan_contrast == "not_applicable":
        raise ValidationError("meta-analysis requires a frozen quantitative contrast_definition")
    if effects.get("contrast_definition") != plan_contrast:
        raise ValidationError("effect records do not match the frozen contrast_definition")
    if effects.get("derivation_scope") != "recomputed_from_source_reported_arm_summaries":
        raise ValidationError(
            "meta-analysis requires reproducibly derived effect records with retained source summaries"
        )
    if (effect_verification.get("effect_verification_version") != 1
            or effect_verification.get("status") != "effect_verification_recorded"
            or effect_verification.get("effect_records_sha256") != effects_sha):
        raise ValidationError("meta-analysis requires clean independent verification of the supplied effects")
    validate_effect_verification_boundary(effect_verification)
    if effect_verification.get("contrast_definition") != plan_contrast:
        raise ValidationError("effect verification does not match the frozen contrast_definition")
    verification_assessments = effect_verification.get("assessments")
    if not isinstance(verification_assessments, list) or not verification_assessments:
        raise ValidationError("meta-analysis requires retained effect-verification assessments")
    verification_by_study = {}
    for assessment in verification_assessments:
        if not isinstance(assessment, dict):
            raise ValidationError("effect-verification assessment is malformed")
        study_id = _canonical_text(
            assessment.get("study_id"), "effect-verification assessment study_id"
        )
        if study_id in verification_by_study:
            raise ValidationError("effect-verification assessments require unique study IDs")
        source_values_match = assessment.get("source_values_match")
        calculation_matches = assessment.get("calculation_matches")
        if not (isinstance(source_values_match, bool) and isinstance(calculation_matches, bool)
                or source_values_match is None and calculation_matches is None):
            raise ValidationError("effect-verification assessment statuses are invalid")
        effect_status = assessment.get("effect_status")
        if effect_status not in {"available", "unavailable"}:
            raise ValidationError("effect-verification assessment must retain effect status")
        retained_source_summary_digest = require_sha256(
            assessment.get("retained_source_summary_sha256"),
            "effect-verification retained_source_summary_sha256",
        )
        checked_location = _canonical_text(
            assessment.get("checked_location"),
            "effect-verification assessment checked_location",
        )
        assessment_claims = assessment.get("claim_source_provenance")
        if not isinstance(assessment_claims, list) or not assessment_claims:
            raise ValidationError("effect-verification assessment must retain claim source provenance")
        verification_by_study[study_id] = {
            "study_id": study_id,
            "effect_status": effect_status,
            "source_values_match": source_values_match,
            "calculation_matches": calculation_matches,
            "retained_source_summary_sha256": retained_source_summary_digest,
            "claim_source_provenance": _claim_source_provenance(
                assessment_claims, "effect-verification claim"
            ),
            "checked_location": checked_location,
        }
    deviation_status = deviations.get("status")
    if (deviations.get("synthesis_deviations_version") != 1
            or deviations.get("synthesis_plan_sha256") != plan_sha
            or deviation_status not in {"no_deviations_declared", "prospective_deviations_recorded",
                                        "retrospective_or_uncertain_deviation_review_required"}):
        raise ValidationError("meta-analysis requires a valid deviation declaration bound to the plan")
    validate_synthesis_deviations_boundary(deviations, synthesis_type="quantitative")
    frozen_deviation_plan = deviations.get("frozen_plan_commitments")
    if not isinstance(frozen_deviation_plan, dict):
        raise ValidationError("meta-analysis requires deviation-bound frozen plan commitments")
    if (frozen_deviation_plan.get("synthesis_type") != "quantitative"
            or frozen_deviation_plan.get("effect_measure") != plan.get("effect_measure")
            or frozen_deviation_plan.get("contrast_definition") != plan_contrast
            or frozen_deviation_plan.get("statistical_model") != plan.get("statistical_model")
            or frozen_deviation_plan.get("minimum_independent_studies") != plan.get("minimum_independent_studies")):
        raise ValidationError("deviation-bound frozen plan commitments do not match the supplied plan")
    model = plan.get("statistical_model")
    if model not in {"fixed_effect", "random_effects"}:
        raise ValidationError("meta-analysis requires a supported frozen statistical model")
    raw_records = effects.get("records")
    if not isinstance(raw_records, list):
        raise ValidationError("effect records must be an array")
    available, unavailable = [], []
    study_provenance = []
    seen = set()
    effect_statuses: dict[str, str] = {}
    for item in raw_records:
        if not isinstance(item, dict):
            raise ValidationError("effect records contain invalid or duplicate study IDs")
        study_id = _canonical_text(item.get("study_id"), "effect record study_id")
        if study_id in seen:
            raise ValidationError("effect records contain invalid or duplicate study IDs")
        seen.add(study_id)
        status = item.get("status")
        if status not in {"available", "unavailable"}:
            raise ValidationError("effect record status is invalid")
        effect_statuses[study_id] = status
        verification = verification_by_study.get(study_id)
        if verification is None:
            raise ValidationError("effect verification must cover every pooled effect record")
        if verification["effect_status"] != status:
            raise ValidationError("effect-verification status does not match the effect record")
        mapped_claims = item.get("mapped_claims")
        if not isinstance(mapped_claims, list) or not mapped_claims:
            raise ValidationError("effect records must retain mapped claim provenance")
        claim_ids = []
        claim_source_provenance = _claim_source_provenance(mapped_claims, "mapped claim")
        for claim in claim_source_provenance:
            claim_ids.append(claim["extraction_id"])
        if verification["claim_source_provenance"] != claim_source_provenance:
            raise ValidationError("effect-verification claim source provenance does not match effect records")
        risk = item.get("risk_of_bias")
        if risk not in {"low", "some_concerns", "high", "unclear"}:
            raise ValidationError("effect records require a valid risk_of_bias")
        study_provenance.append({
            "study_id": study_id,
            "effect_status": status,
            "risk_of_bias": risk,
            "mapped_claim_ids": claim_ids,
            "mapped_claim_source_provenance": claim_source_provenance,
            "effect_verification": verification,
        })
        if status == "unavailable":
            if verification["source_values_match"] is not None or verification["calculation_matches"] is not None:
                raise ValidationError("unavailable effects require not-applicable verification checks")
            unavailable.append({
                "study_id": study_id,
                "reason": _bounded_meta_text(item.get("reason"), "meta-analysis unavailable reason"),
            })
            continue
        if verification["source_values_match"] is not True or verification["calculation_matches"] is not True:
            raise ValidationError("available effects require clean source and calculation verification")
        estimate, variance = item.get("estimate"), item.get("variance")
        if (isinstance(estimate, bool) or not isinstance(estimate, (int, float)) or not math.isfinite(estimate)
                or isinstance(variance, bool) or not isinstance(variance, (int, float))
                or not math.isfinite(variance) or variance <= 0):
            raise ValidationError("available effects require finite estimates and positive variances")
        available.append({"study_id": study_id, "estimate": float(estimate),
                          "variance": float(variance), "risk_of_bias": risk,
                          "mapped_claim_ids": claim_ids,
                          "mapped_claim_source_provenance": claim_source_provenance})
        study_provenance[-1]["effect_estimate"] = float(estimate)
        study_provenance[-1]["effect_standard_error"] = math.sqrt(float(variance))
        study_provenance[-1]["effect_variance"] = float(variance)
    minimum = plan.get("minimum_independent_studies")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValidationError("frozen minimum_independent_studies is invalid")
    if len(available) < max(2, minimum):
        raise ValidationError("meta-analysis requires at least two available effects and the frozen minimum study count")
    if set(verification_by_study) != seen:
        raise ValidationError("effect verification must cover exactly the effect records")
    retained_source_summaries = validate_retained_source_summaries(
        effects.get("source_summaries"),
        expected_statuses=effect_statuses,
        effect_measure=plan.get("effect_measure"),
    )
    summary_digests = {
        summary["study_id"]: retained_source_summary_sha256(summary)
        for summary in retained_source_summaries
    }
    for provenance in study_provenance:
        study_id = provenance["study_id"]
        retained_digest = summary_digests[study_id]
        if provenance["effect_verification"]["retained_source_summary_sha256"] != retained_digest:
            raise ValidationError(
                "effect-verification retained source-summary digest does not match effect records"
            )
        provenance["retained_source_summary_sha256"] = retained_digest

    fixed_estimate, fixed_se = _weighted(available)
    fixed_weights = [1.0 / item["variance"] for item in available]
    q = sum(weight * (item["estimate"] - fixed_estimate) ** 2
            for weight, item in zip(fixed_weights, available))
    df = len(available) - 1
    denominator = sum(fixed_weights) - sum(weight ** 2 for weight in fixed_weights) / sum(fixed_weights)
    tau_squared = max(0.0, (q - df) / denominator) if denominator > 0 else 0.0
    i_squared = max(0.0, (q - df) / q) * 100.0 if q > 0 else 0.0
    estimate, conventional_se = _weighted(available, tau_squared if model == "random_effects" else 0.0)
    normal_critical = NormalDist().inv_cdf(0.975)
    if model == "random_effects":
        random_weights = [1.0 / (item["variance"] + tau_squared) for item in available]
        hk_scale = sum(weight * (item["estimate"] - estimate) ** 2
                       for weight, item in zip(random_weights, available)) / df
        hartung_knapp_se = math.sqrt(hk_scale / sum(random_weights))
        standard_error = max(conventional_se, hartung_knapp_se)
        critical = _t_critical_95(df)
        inference_method = "modified_hartung_knapp_student_t_95"
    else:
        hartung_knapp_se = None
        standard_error = conventional_se
        critical = normal_critical
        inference_method = "fixed_effect_normal_95"
    confidence_interval = [estimate - critical * standard_error, estimate + critical * standard_error]
    prediction_interval = None
    if model == "random_effects" and len(available) >= 3:
        spread = math.sqrt(tau_squared + standard_error ** 2)
        prediction_interval = [estimate - critical * spread, estimate + critical * spread]
    leave_one_out = []
    for excluded in available:
        remaining = [item for item in available if item["study_id"] != excluded["study_id"]]
        loo_estimate, loo_se = _weighted(remaining, tau_squared if model == "random_effects" else 0.0)
        leave_one_out.append({"excluded_study_id": excluded["study_id"], "estimate": loo_estimate,
                              "standard_error": loo_se,
                              "confidence_interval_95_normal_approximation": [loo_estimate - normal_critical * loo_se, loo_estimate + normal_critical * loo_se]})
    planned = plan.get("sensitivity_analyses")
    if not isinstance(planned, list) or not planned:
        raise ValidationError("quantitative meta-analysis requires executable planned sensitivity analyses")
    sensitivity_results = []
    for sensitivity in planned:
        if sensitivity == "leave_one_study_out":
            sensitivity_results.append({"analysis": sensitivity, "status": "completed",
                                        "results": leave_one_out})
        elif sensitivity == "exclude_high_or_unclear_bias":
            subset = [item for item in available if item["risk_of_bias"] not in {"high", "unclear"}]
            if len(subset) < 2:
                sensitivity_results.append({"analysis": sensitivity, "status": "not_estimable",
                    "reason": "fewer than two low-or-some-concerns studies remain", "remaining_study_count": len(subset)})
            else:
                subset_estimate, subset_se = _weighted(subset, tau_squared if model == "random_effects" else 0.0)
                sensitivity_results.append({"analysis": sensitivity, "status": "completed",
                    "remaining_study_count": len(subset), "estimate": subset_estimate,
                    "standard_error_normal_approximation": subset_se})
        elif sensitivity in {"alternate_fixed_effect", "alternate_random_effects"}:
            alternate_tau = 0.0 if sensitivity == "alternate_fixed_effect" else tau_squared
            alternate_estimate, alternate_se = _weighted(available, alternate_tau)
            sensitivity_results.append({"analysis": sensitivity, "status": "completed",
                "estimate": alternate_estimate, "standard_error_normal_approximation": alternate_se})
        else:
            raise ValidationError("meta-analysis cannot execute an unknown planned sensitivity analysis")
    result = {
        "meta_analysis_version": 1,
        "inputs": {"synthesis_plan_sha256": plan_sha, "effect_records_sha256": effects_sha,
                   "effect_verification_sha256": effect_verification_sha,
                   "synthesis_deviations_sha256": deviations_sha},
        "deviation_status": deviation_status,
        "deviation_plan_commitments": frozen_deviation_plan,
        "deviations": deviations.get("deviations"),
        "plan_id": plan.get("plan_id"), "snapshot_id": plan.get("snapshot_id"),
        "contrast_definition": plan_contrast,
        "effect_measure": plan.get("effect_measure"), "statistical_model": model,
        "available_study_count": len(available), "unavailable_studies": unavailable,
        "retained_source_summaries": retained_source_summaries,
        "study_provenance": study_provenance,
        "pooled_estimate": estimate, "standard_error": standard_error,
        "conventional_standard_error": conventional_se,
        "hartung_knapp_standard_error": hartung_knapp_se,
        "inference_method": inference_method,
        "critical_value_95": critical,
        "confidence_interval_95": confidence_interval,
        "heterogeneity": {"q": q, "degrees_of_freedom": df, "i_squared_percent": i_squared,
                          "tau_squared_der_simonian_laird": tau_squared},
        "prediction_interval_95": prediction_interval,
        "leave_one_study_out": leave_one_out,
        "planned_sensitivity_analyses": planned,
        "planned_sensitivity_results": sensitivity_results,
        "small_study_effects": _egger_diagnostic(available),
        "status": ("meta_analysis_deviation_review_required"
                   if deviation_status == "retrospective_or_uncertain_deviation_review_required"
                   else "meta_analysis_recorded"), "scientific_evidence_eligible": False,
        "conclusion_authorized": False, "publication_authorized": False,
        "reviewer_identity_authenticated": False,
        "limitations": [
            "Inverse-variance pooling assumes the supplied estimates and variances are comparable and correctly derived; Faraday has not reproduced them from participant-level data.",
            "DerSimonian-Laird heterogeneity can be unreliable with few studies. Random-effects confidence and prediction intervals use a conservative modified Hartung-Knapp standard error and tabulated Student-t critical value; prediction intervals are withheld below three effects.",
            "Leave-one-study-out intervals are labeled normal approximations and retain the full-analysis tau-squared; they are influence diagnostics, not replacement meta-analyses.",
            "Planned sensitivity analyses are always reported, including not-estimable results. Alternate-model and bias-exclusion standard errors are labeled normal approximations.",
            "Egger regression is withheld below ten effects or without precision variation. An estimated asymmetry diagnostic never establishes publication bias.",
            "The machine does not authenticate reviewer identity or expertise for extraction, effect preparation, verification, deviation, or pooling judgments.",
            "Execution requires an explicit plan-bound deviation declaration; retrospective or unknown-timing departures force review status.",
            "Unavailable studies remain disclosed. The pooled sign is not interpreted, and no causal, clinical, practical, or publication conclusion is authorized.",
        ],
    }
    validate_meta_analysis_boundary(result, planned_sensitivity_analyses=planned)
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("meta-analysis output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".meta-analysis-", dir=root.parent) as temporary:
        staging = Path(temporary) / "meta-analysis"; staging.mkdir()
        (staging / "meta-analysis.json").write_bytes(encoded); os.replace(staging, root)
    return {"path": str(root), "meta_analysis_sha256": hashlib.sha256(encoded).hexdigest(), **result}
