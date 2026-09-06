"""Synthetic meta-analysis validates deterministic mechanics, not conclusions."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.meta_analysis import execute_meta_analysis


def write_json(path, value):
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode(); path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def artifacts(tmp_path, model="fixed_effect", minimum=2, count=3,
              sensitivities=None):
    if sensitivities is None:
        sensitivities = ["leave_one_study_out", "exclude_high_or_unclear_bias",
                         "alternate_random_effects" if model == "fixed_effect" else "alternate_fixed_effect"]
    plan = tmp_path / "plan.json"
    plan_sha = write_json(plan, {"synthesis_plan_version": 1, "status": "synthesis_plan_frozen",
        "synthesis_type": "quantitative", "statistical_model": model, "effect_measure": "mean_difference",
        "minimum_independent_studies": minimum, "plan_id": "p1", "snapshot_id": "snap",
        "sensitivity_analyses": sensitivities})
    records = [{"study_id": f"s{i}", "status": "available", "estimate": value, "variance": 1.0,
                "risk_of_bias": "high" if i == 3 else "low"}
               for i, value in enumerate([1.0, 2.0, 6.0][:count], start=1)]
    records.append({"study_id": "missing", "status": "unavailable", "reason": "Not reported"})
    effects = tmp_path / "effects.json"
    effects_sha = write_json(effects, {"effect_records_version": 1, "status": "effects_ready",
        "inputs": {"synthesis_plan_sha256": plan_sha}, "effect_measure": "mean_difference", "records": records})
    verification = tmp_path / "effect-verification.json"
    verification_sha = write_json(verification, {"effect_verification_version": 1,
        "status": "effect_verification_recorded", "effect_records_sha256": effects_sha})
    deviations = tmp_path / "deviations.json"
    deviations_sha = write_json(deviations, {"synthesis_deviations_version": 1,
        "synthesis_plan_sha256": plan_sha, "status": "no_deviations_declared", "deviations": []})
    return plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha


def test_fixed_effect_cli_pools_and_preserves_unavailable(tmp_path, capsys):
    plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha = artifacts(tmp_path, count=2)
    output = tmp_path / "meta"
    assert main(["--json", "literature", "pool-effects", "--plan-file", str(plan),
        "--expected-plan-sha256", plan_sha, "--effects-file", str(effects),
        "--expected-effects-sha256", effects_sha, "--deviations-file", str(deviations),
        "--effect-verification-file", str(verification),
        "--expected-effect-verification-sha256", verification_sha,
        "--expected-deviations-sha256", deviations_sha, "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["pooled_estimate"] == pytest.approx(1.5)
    assert result["standard_error"] == pytest.approx(2 ** -0.5)
    assert result["prediction_interval_95"] is None
    assert result["unavailable_studies"] == [{"reason": "Not reported", "study_id": "missing"}]
    assert result["conclusion_authorized"] is False
    assert result["small_study_effects"]["status"] == "not_estimable"
    assert result["small_study_effects"]["publication_bias_conclusion"] is False
    assert [item["analysis"] for item in result["planned_sensitivity_results"]] == [
        "leave_one_study_out", "exclude_high_or_unclear_bias", "alternate_random_effects"]
    with pytest.raises(ValidationError, match="already exists"):
        execute_meta_analysis(plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha, output)


def test_random_effects_reports_heterogeneity_prediction_and_influence(tmp_path):
    plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha = artifacts(tmp_path, model="random_effects")
    result = execute_meta_analysis(plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha, tmp_path / "meta")
    assert result["heterogeneity"]["q"] > result["heterogeneity"]["degrees_of_freedom"]
    assert result["heterogeneity"]["tau_squared_der_simonian_laird"] > 0
    assert len(result["prediction_interval_95"]) == 2
    assert len(result["leave_one_study_out"]) == 3
    assert result["inference_method"] == "modified_hartung_knapp_student_t_95"
    assert result["standard_error"] >= result["conventional_standard_error"]
    assert result["critical_value_95"] == pytest.approx(4.303)
    assert result["hartung_knapp_standard_error"] is not None
    assert "confidence_interval_95_normal_approximation" in result["leave_one_study_out"][0]
    excluded = next(item for item in result["planned_sensitivity_results"]
                    if item["analysis"] == "exclude_high_or_unclear_bias")
    assert excluded["status"] == "completed" and excluded["remaining_study_count"] == 2


def test_egger_diagnostic_requires_ten_varying_precisions_and_never_declares_bias(tmp_path):
    plan, plan_sha, effects, _, verification, _, deviations, deviations_sha = artifacts(tmp_path, sensitivities=["leave_one_study_out"])
    value = json.loads(effects.read_text())
    value["records"] = [
        {"study_id": f"s{i}", "status": "available", "estimate": 0.1 + i * 0.02,
         "variance": 0.05 + i * 0.01, "risk_of_bias": "low"}
        for i in range(10)
    ]
    effects_sha = write_json(effects, value)
    verification_sha = write_json(verification, {"effect_verification_version": 1,
        "status": "effect_verification_recorded", "effect_records_sha256": effects_sha})
    result = execute_meta_analysis(plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha, tmp_path / "meta")
    diagnostic = result["small_study_effects"]
    assert diagnostic["status"] == "estimated"
    assert diagnostic["study_count"] == 10
    assert len(diagnostic["intercept_confidence_interval_95"]) == 2
    assert diagnostic["publication_bias_conclusion"] is False


def test_egger_diagnostic_with_constant_precision_is_not_estimable(tmp_path):
    plan, plan_sha, effects, _, verification, _, deviations, deviations_sha = artifacts(tmp_path, sensitivities=["leave_one_study_out"])
    value = json.loads(effects.read_text())
    value["records"] = [
        {"study_id": f"s{i}", "status": "available", "estimate": float(i),
         "variance": 1.0, "risk_of_bias": "low"} for i in range(10)
    ]
    effects_sha = write_json(effects, value)
    verification_sha = write_json(verification, {"effect_verification_version": 1,
        "status": "effect_verification_recorded", "effect_records_sha256": effects_sha})
    result = execute_meta_analysis(plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha, tmp_path / "meta")
    assert result["small_study_effects"]["status"] == "not_estimable"
    assert "precisions do not vary" in result["small_study_effects"]["reason"]


def test_retrospective_deviation_forces_meta_analysis_review_status(tmp_path):
    plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, _ = artifacts(tmp_path)
    value = json.loads(deviations.read_text())
    value["status"] = "retrospective_or_uncertain_deviation_review_required"
    value["deviations"] = [{"deviation_id": "d1", "timing": "unknown"}]
    deviations_sha = write_json(deviations, value)
    result = execute_meta_analysis(
        plan, plan_sha, effects, effects_sha, verification, verification_sha,
        deviations, deviations_sha, tmp_path / "meta"
    )
    assert result["status"] == "meta_analysis_deviation_review_required"
    assert result["deviations"] == value["deviations"]


@pytest.mark.parametrize("failure", ["plan-hash", "effects-hash", "model", "link", "measure", "one-study", "variance", "duplicate", "bias", "unknown-sensitivity"])
def test_invalid_meta_analysis_never_publishes(tmp_path, failure):
    plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha = artifacts(tmp_path)
    if failure == "plan-hash": plan_sha = "0" * 64
    elif failure == "effects-hash": effects_sha = "0" * 64
    elif failure == "model":
        value = json.loads(plan.read_text()); value["statistical_model"] = "not_applicable"; plan_sha = write_json(plan, value)
    elif failure == "link":
        value = json.loads(effects.read_text()); value["inputs"]["synthesis_plan_sha256"] = "0" * 64; effects_sha = write_json(effects, value)
    elif failure == "measure":
        value = json.loads(effects.read_text()); value["effect_measure"] = "other"; effects_sha = write_json(effects, value)
    elif failure == "one-study":
        value = json.loads(effects.read_text()); value["records"] = value["records"][:1]; effects_sha = write_json(effects, value)
    elif failure == "variance":
        value = json.loads(effects.read_text()); value["records"][0]["variance"] = 0; effects_sha = write_json(effects, value)
    elif failure == "duplicate":
        value = json.loads(effects.read_text()); value["records"][1]["study_id"] = "s1"; effects_sha = write_json(effects, value)
    elif failure == "bias":
        value = json.loads(effects.read_text()); value["records"][0]["risk_of_bias"] = "safe"; effects_sha = write_json(effects, value)
    elif failure == "unknown-sensitivity":
        value = json.loads(plan.read_text()); value["sensitivity_analyses"] = ["unknown"]; plan_sha = write_json(plan, value)
        value = json.loads(effects.read_text()); value["inputs"]["synthesis_plan_sha256"] = plan_sha; effects_sha = write_json(effects, value)
    output = tmp_path / "meta"
    with pytest.raises(ValidationError):
        execute_meta_analysis(plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha, output)
    assert not output.exists()
