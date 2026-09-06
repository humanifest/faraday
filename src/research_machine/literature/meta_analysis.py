"""Conservative inverse-variance meta-analysis for plan-bound effect records."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from statistics import NormalDist
import tempfile
from typing import Any

from research_machine.domain.errors import ValidationError


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
    if (effects.get("effect_records_version") != 1 or effects.get("status") != "effects_ready"
            or not isinstance(effects.get("inputs"), dict)
            or effects["inputs"].get("synthesis_plan_sha256") != plan_sha):
        raise ValidationError("meta-analysis requires ready effect records bound to the supplied plan")
    if effects.get("effect_measure") != plan.get("effect_measure"):
        raise ValidationError("effect records do not match the frozen effect measure")
    if (effect_verification.get("effect_verification_version") != 1
            or effect_verification.get("status") != "effect_verification_recorded"
            or effect_verification.get("effect_records_sha256") != effects_sha):
        raise ValidationError("meta-analysis requires clean independent verification of the supplied effects")
    verification_assessments = effect_verification.get("assessments")
    if not isinstance(verification_assessments, list) or not verification_assessments:
        raise ValidationError("meta-analysis requires retained effect-verification assessments")
    verification_by_study = {}
    for assessment in verification_assessments:
        if not isinstance(assessment, dict):
            raise ValidationError("effect-verification assessment is malformed")
        study_id = assessment.get("study_id")
        if not isinstance(study_id, str) or not study_id.strip() or study_id in verification_by_study:
            raise ValidationError("effect-verification assessments require unique study IDs")
        source_values_match = assessment.get("source_values_match")
        calculation_matches = assessment.get("calculation_matches")
        if not (isinstance(source_values_match, bool) and isinstance(calculation_matches, bool)
                or source_values_match is None and calculation_matches is None):
            raise ValidationError("effect-verification assessment statuses are invalid")
        effect_status = assessment.get("effect_status")
        if effect_status not in {"available", "unavailable"}:
            raise ValidationError("effect-verification assessment must retain effect status")
        checked_location = assessment.get("checked_location")
        if not isinstance(checked_location, str) or not checked_location.strip():
            raise ValidationError("effect-verification assessment requires an inspectable location")
        verification_by_study[study_id] = {
            "study_id": study_id,
            "effect_status": effect_status,
            "source_values_match": source_values_match,
            "calculation_matches": calculation_matches,
            "checked_location": checked_location.strip(),
        }
    deviation_status = deviations.get("status")
    if (deviations.get("synthesis_deviations_version") != 1
            or deviations.get("synthesis_plan_sha256") != plan_sha
            or deviation_status not in {"no_deviations_declared", "prospective_deviations_recorded",
                                        "retrospective_or_uncertain_deviation_review_required"}):
        raise ValidationError("meta-analysis requires a valid deviation declaration bound to the plan")
    frozen_deviation_plan = deviations.get("frozen_plan_commitments")
    if not isinstance(frozen_deviation_plan, dict):
        raise ValidationError("meta-analysis requires deviation-bound frozen plan commitments")
    if (frozen_deviation_plan.get("synthesis_type") != "quantitative"
            or frozen_deviation_plan.get("effect_measure") != plan.get("effect_measure")
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
    for item in raw_records:
        if not isinstance(item, dict) or not isinstance(item.get("study_id"), str) or item["study_id"] in seen:
            raise ValidationError("effect records contain invalid or duplicate study IDs")
        seen.add(item["study_id"])
        verification = verification_by_study.get(item["study_id"])
        if verification is None:
            raise ValidationError("effect verification must cover every pooled effect record")
        if verification["effect_status"] != item.get("status"):
            raise ValidationError("effect-verification status does not match the effect record")
        mapped_claims = item.get("mapped_claims")
        if not isinstance(mapped_claims, list) or not mapped_claims:
            raise ValidationError("effect records must retain mapped claim provenance")
        claim_ids = []
        for claim in mapped_claims:
            if not isinstance(claim, dict):
                raise ValidationError("mapped claim provenance is malformed")
            extraction_id = claim.get("extraction_id")
            if not isinstance(extraction_id, str) or not extraction_id.strip() or extraction_id in claim_ids:
                raise ValidationError("mapped claim provenance requires unique extraction IDs")
            claim_ids.append(extraction_id)
        risk = item.get("risk_of_bias")
        if risk not in {"low", "some_concerns", "high", "unclear"}:
            raise ValidationError("effect records require a valid risk_of_bias")
        study_provenance.append({
            "study_id": item["study_id"],
            "effect_status": item.get("status"),
            "risk_of_bias": risk,
            "mapped_claim_ids": claim_ids,
            "effect_verification": verification,
        })
        if item.get("status") == "unavailable":
            if verification["source_values_match"] is not None or verification["calculation_matches"] is not None:
                raise ValidationError("unavailable effects require not-applicable verification checks")
            unavailable.append({"study_id": item["study_id"], "reason": item.get("reason")})
            continue
        if item.get("status") != "available":
            raise ValidationError("effect record status is invalid")
        if verification["source_values_match"] is not True or verification["calculation_matches"] is not True:
            raise ValidationError("available effects require clean source and calculation verification")
        estimate, variance = item.get("estimate"), item.get("variance")
        if (isinstance(estimate, bool) or not isinstance(estimate, (int, float)) or not math.isfinite(estimate)
                or isinstance(variance, bool) or not isinstance(variance, (int, float))
                or not math.isfinite(variance) or variance <= 0):
            raise ValidationError("available effects require finite estimates and positive variances")
        available.append({"study_id": item["study_id"], "estimate": float(estimate),
                          "variance": float(variance), "risk_of_bias": risk,
                          "mapped_claim_ids": claim_ids})
    minimum = plan.get("minimum_independent_studies")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValidationError("frozen minimum_independent_studies is invalid")
    if len(available) < max(2, minimum):
        raise ValidationError("meta-analysis requires at least two available effects and the frozen minimum study count")
    if set(verification_by_study) != seen:
        raise ValidationError("effect verification must cover exactly the effect records")

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
        "effect_measure": plan.get("effect_measure"), "statistical_model": model,
        "available_study_count": len(available), "unavailable_studies": unavailable,
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
        "planned_sensitivity_results": sensitivity_results,
        "small_study_effects": _egger_diagnostic(available),
        "status": ("meta_analysis_deviation_review_required"
                   if deviation_status == "retrospective_or_uncertain_deviation_review_required"
                   else "meta_analysis_recorded"), "scientific_evidence_eligible": False,
        "conclusion_authorized": False, "publication_authorized": False,
        "limitations": [
            "Inverse-variance pooling assumes the supplied estimates and variances are comparable and correctly derived; Faraday has not reproduced them from participant-level data.",
            "DerSimonian-Laird heterogeneity can be unreliable with few studies. Random-effects confidence and prediction intervals use a conservative modified Hartung-Knapp standard error and tabulated Student-t critical value; prediction intervals are withheld below three effects.",
            "Leave-one-study-out intervals are labeled normal approximations and retain the full-analysis tau-squared; they are influence diagnostics, not replacement meta-analyses.",
            "Planned sensitivity analyses are always reported, including not-estimable results. Alternate-model and bias-exclusion standard errors are labeled normal approximations.",
            "Egger regression is withheld below ten effects or without precision variation. An estimated asymmetry diagnostic never establishes publication bias.",
            "Execution requires an explicit plan-bound deviation declaration; retrospective or unknown-timing departures force review status.",
            "Unavailable studies remain disclosed. The pooled sign is not interpreted, and no causal, clinical, practical, or publication conclusion is authorized.",
        ],
    }
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError("meta-analysis output already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix=".meta-analysis-", dir=root.parent) as temporary:
        staging = Path(temporary) / "meta-analysis"; staging.mkdir()
        (staging / "meta-analysis.json").write_bytes(encoded); os.replace(staging, root)
    return {"path": str(root), "meta_analysis_sha256": hashlib.sha256(encoded).hexdigest(), **result}
