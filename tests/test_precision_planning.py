from __future__ import annotations

import hashlib
import pytest

from research_machine.design.precision import (
    build_sample_size_planning_receipt,
    plan_two_group_equivalence_power,
    plan_two_group_practical_power,
    plan_two_group_power,
    plan_two_group_precision,
)
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import AnalysisContract
from research_machine.application.policies import (
    assess_attrition_achievement, assess_precision_achievement,
    assess_variance_assumption, validate_planning_inference_coherence,
)


def _planning_contract(confidence_level=0.95) -> AnalysisContract:
    return AnalysisContract(
        primary_hypothesis_id="h1", primary_measurement_id="m1",
        method="independent_mean_difference_ci",
        outcome_column="outcome", group_column="group", groups=["a", "b"],
        estimand="Mean difference.", missing_data_policy="complete_case",
        assignment_type="randomized", effect_estimate_path="/result/effect",
        uncertainty_path="/result/interval", null_value=0.0,
        support_rule="interval_excludes_null", confidence_level=confidence_level,
    )


def test_precision_plan_must_match_registered_interval_level() -> None:
    plan = build_sample_size_planning_receipt({
        "strategy": "precision",
        "target_hypothesis_id": "h1", "target_measurement_id": "m1",
        "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups", "target_half_width": 1.0,
            "assumed_standard_deviation": 2.0, "confidence_level": 0.95,
        },
        "justification": "Target the registered interval precision.",
    })
    validate_planning_inference_coherence(
        sample_size_plan=plan, analysis_contract=_planning_contract(),
        expected_direction="two_sided", multiplicity_alpha=0.05,
        measurement_unit="fixture units", smallest_effect_size_of_interest=None,
        maximum_excluded_fraction=0.25,
    )
    with pytest.raises(ValidationError, match="confidence level must match"):
        validate_planning_inference_coherence(
            sample_size_plan=plan, analysis_contract=_planning_contract(0.90),
            expected_direction="two_sided", multiplicity_alpha=0.05,
            measurement_unit="fixture units", smallest_effect_size_of_interest=None,
            maximum_excluded_fraction=0.25,
        )


@pytest.mark.parametrize(
    ("direction", "alpha", "message"),
    [("positive", 0.05, "alternative"), ("two_sided", 0.01, "alpha")],
)
def test_practical_power_plan_must_match_hypothesis_direction_and_protocol_alpha(
    direction, alpha, message,
) -> None:
    plan = build_sample_size_planning_receipt({
        "strategy": "practical_power",
        "target_hypothesis_id": "h1", "target_measurement_id": "m1",
        "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups",
            "smallest_effect_size_of_interest": 0.5,
            "assumed_true_effect": 1.0, "assumed_standard_deviation": 1.0,
            "alpha": 0.05, "confidence_level": 0.95,
            "target_power": 0.8, "alternative": "two_sided",
        },
        "justification": "Power the registered primary comparison.",
    })
    with pytest.raises(ValidationError, match=message):
        validate_planning_inference_coherence(
            sample_size_plan=plan, analysis_contract=_planning_contract(),
            expected_direction=direction, multiplicity_alpha=alpha,
            measurement_unit="fixture units", smallest_effect_size_of_interest=0.5,
            maximum_excluded_fraction=0.25,
        )


def test_execution_bound_plan_must_name_the_registered_scientific_target() -> None:
    plan = build_sample_size_planning_receipt({
        "strategy": "precision", "target_hypothesis_id": "other",
        "target_measurement_id": "m1", "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups", "target_half_width": 1.0,
            "assumed_standard_deviation": 2.0, "confidence_level": 0.95,
        },
        "justification": "Target an explicitly identified outcome.",
    })
    with pytest.raises(ValidationError, match="target_hypothesis_id"):
        validate_planning_inference_coherence(
            sample_size_plan=plan, analysis_contract=_planning_contract(),
            expected_direction="two_sided", multiplicity_alpha=0.05,
            measurement_unit="fixture units", smallest_effect_size_of_interest=None,
            maximum_excluded_fraction=0.25,
        )
    with pytest.raises(ValidationError, match="measurement_unit"):
        validate_planning_inference_coherence(
            sample_size_plan={**plan, "target_hypothesis_id": "h1"},
            analysis_contract=_planning_contract(), expected_direction="two_sided",
            multiplicity_alpha=0.05, measurement_unit="milliseconds",
            smallest_effect_size_of_interest=None, maximum_excluded_fraction=0.25,
        )


def test_practical_power_plan_smallest_effect_must_match_conclusion_threshold() -> None:
    plan = build_sample_size_planning_receipt({
        "strategy": "practical_power", "target_hypothesis_id": "h1",
        "target_measurement_id": "m1", "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups",
            "smallest_effect_size_of_interest": 0.5,
            "assumed_true_effect": 1.0, "assumed_standard_deviation": 1.0,
            "alpha": 0.05, "confidence_level": 0.95,
            "target_power": 0.8, "alternative": "two_sided",
        },
        "justification": "Power the smallest practically important effect.",
    })
    with pytest.raises(ValidationError, match="smallest effect"):
        validate_planning_inference_coherence(
            sample_size_plan=plan, analysis_contract=_planning_contract(),
            expected_direction="two_sided", multiplicity_alpha=0.05,
            measurement_unit="fixture units", smallest_effect_size_of_interest=0.25,
            maximum_excluded_fraction=0.25,
        )


def test_ordinary_power_cannot_bind_a_practical_significance_conclusion() -> None:
    plan = build_sample_size_planning_receipt({
        "strategy": "power", "target_hypothesis_id": "h1",
        "target_measurement_id": "m1", "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups",
            "smallest_effect_size_of_interest": 0.5,
            "assumed_standard_deviation": 1.0, "alpha": 0.05,
            "target_power": 0.8, "alternative": "two_sided",
        },
        "justification": "Review conventional difference-detection power.",
    })
    with pytest.raises(ValidationError, match="use practical_power"):
        validate_planning_inference_coherence(
            sample_size_plan=plan, analysis_contract=_planning_contract(),
            expected_direction="two_sided", multiplicity_alpha=0.05,
            measurement_unit="fixture units",
            smallest_effect_size_of_interest=0.5,
            maximum_excluded_fraction=0.25,
        )


def test_practical_power_powers_the_registered_confidence_bound_decision() -> None:
    result = plan_two_group_practical_power({
        "study_design": "independent_groups",
        "smallest_effect_size_of_interest": 0.5,
        "assumed_true_effect": 1.0,
        "assumed_standard_deviation": 1.0,
        "alpha": 0.05, "confidence_level": 0.95,
        "target_power": 0.8, "alternative": "positive",
        "sensitivity_true_effects": [0.75, 1.0, 1.5],
    })
    assert result["analyzable_n_per_group"] == 63
    sizes = [item["analyzable_n_per_group"] for item in result["sensitivity"]["assumed_true_effect"]]
    assert sizes[0] > sizes[1] > sizes[2]
    with pytest.raises(ValidationError, match="beyond the practical-effect threshold"):
        plan_two_group_practical_power({
            "study_design": "independent_groups",
            "smallest_effect_size_of_interest": 0.5,
            "assumed_true_effect": 0.5,
            "assumed_standard_deviation": 1.0,
            "alternative": "positive",
        })


def test_plan_cannot_assume_more_attrition_than_the_analysis_allows() -> None:
    plan = build_sample_size_planning_receipt({
        "strategy": "precision", "target_hypothesis_id": "h1",
        "target_measurement_id": "m1", "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups", "target_half_width": 1.0,
            "assumed_standard_deviation": 2.0, "confidence_level": 0.95,
            "anticipated_attrition_fraction": 0.3,
        },
        "justification": "Inflate enrollment for anticipated attrition.",
    })
    with pytest.raises(ValidationError, match="anticipated attrition exceeds"):
        validate_planning_inference_coherence(
            sample_size_plan=plan, analysis_contract=_planning_contract(),
            expected_direction="two_sided", multiplicity_alpha=0.05,
            measurement_unit="fixture units", smallest_effect_size_of_interest=None,
            maximum_excluded_fraction=0.2,
        )


def test_precision_achievement_is_observed_without_suppressing_evidence() -> None:
    plan = build_sample_size_planning_receipt({
        "strategy": "precision", "target_hypothesis_id": "h1",
        "target_measurement_id": "m1", "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups", "target_half_width": 1.0,
            "assumed_standard_deviation": 2.0, "confidence_level": 0.95,
        },
        "justification": "Target a one-unit confidence-interval half-width.",
    })
    assert assess_precision_achievement(
        plan, {"lower": -0.75, "upper": 0.75, "level": 0.95},
    )["status"] == "met"
    missed = assess_precision_achievement(
        plan, {"lower": -1.5, "upper": 1.5, "level": 0.95},
    )
    assert missed == {
        "status": "not_met", "target_half_width": 1.0,
        "observed_half_width": 1.5, "measurement_unit": "fixture units",
        "scientific_interpretation_verified": False,
    }


def test_attrition_assumption_miss_is_observed_not_suppressed() -> None:
    plan = build_sample_size_planning_receipt({
        "strategy": "precision", "target_hypothesis_id": "h1",
        "target_measurement_id": "m1", "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups", "target_half_width": 1.0,
            "assumed_standard_deviation": 2.0, "confidence_level": 0.95,
            "anticipated_attrition_fraction": 0.1,
        },
        "justification": "Inflate enrollment for ten percent attrition.",
    })
    assessment = assess_attrition_achievement(plan, {
        "status": "passed", "observed_excluded_fraction": 0.15,
        "registered_maximum_excluded_fraction": 0.2,
        "observed_excluded_fraction_by_group": {"a": 0.1, "b": 0.2},
        "observed_group_excluded_fraction_difference": 0.1,
        "registered_maximum_group_excluded_fraction_difference": 0.15,
    })
    assert assessment["status"] == "exceeded_assumption"
    assert assessment["observed_excluded_fraction_by_group"] == {"a": 0.1, "b": 0.2}


def test_observed_variance_is_compared_without_post_hoc_threshold() -> None:
    plan = build_sample_size_planning_receipt({
        "strategy": "power", "target_hypothesis_id": "h1",
        "target_measurement_id": "m1", "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups",
            "smallest_effect_size_of_interest": 0.5,
            "assumed_standard_deviation": 2.0, "alpha": 0.05,
            "target_power": 0.8, "alternative": "two_sided",
        },
        "justification": "Use a prospective two-unit variability assumption.",
    })
    assessment = assess_variance_assumption(plan, 3.0)
    assert assessment["observed_to_assumed_ratio"] == 1.5
    assert assessment["adequacy_threshold_registered"] is False
    assert assessment["scientific_interpretation_verified"] is False
    threshold_plan = build_sample_size_planning_receipt({
        "strategy": "power", "target_hypothesis_id": "h1",
        "target_measurement_id": "m1", "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups",
            "smallest_effect_size_of_interest": 0.5,
            "assumed_standard_deviation": 2.0, "alpha": 0.05,
            "target_power": 0.8, "alternative": "two_sided",
            "maximum_observed_to_assumed_sd_ratio": 1.25,
        },
        "justification": "Register a variance-assumption diagnostic tolerance.",
    })
    exceeded = assess_variance_assumption(threshold_plan, 3.0)
    assert exceeded["status"] == "exceeded_registered_tolerance"
    assert exceeded["maximum_registered_ratio"] == 1.25


@pytest.mark.parametrize("value", [True, 0.99, float("inf")])
def test_variance_ratio_tolerance_must_be_finite_and_at_least_one(value) -> None:
    with pytest.raises(ValidationError, match="maximum_observed"):
        plan_two_group_precision({
            "study_design": "independent_groups", "target_half_width": 1.0,
            "assumed_standard_deviation": 2.0,
            "maximum_observed_to_assumed_sd_ratio": value,
        })


def test_equivalence_power_uses_the_interval_within_margin_decision_event() -> None:
    spec = {
        "study_design": "independent_groups", "equivalence_margin": 0.5,
        "assumed_true_difference": 0.0, "assumed_standard_deviation": 1.0,
        "alpha": 0.05, "target_power": 0.8,
        "anticipated_attrition_fraction": 0.1,
        "sensitivity_true_differences": [0.0, 0.2],
    }
    result = plan_two_group_equivalence_power(spec)
    assert result["confidence_level"] == 0.9
    assert result["analyzable_n_per_group"] == 69
    assert result["enrollment_n_per_group"] == 77
    assert result["achieved_model_power_at_integer_n"] >= 0.8
    scenarios = result["sensitivity"]["assumed_true_difference"]
    assert scenarios[1]["analyzable_n_per_group"] > scenarios[0]["analyzable_n_per_group"]
    assert "not observed power" in result["assumptions"][3]


@pytest.mark.parametrize("true_difference", [-0.5, 0.5, 0.6])
def test_equivalence_power_requires_assumed_truth_inside_margin(true_difference) -> None:
    with pytest.raises(ValidationError, match="strictly inside"):
        plan_two_group_equivalence_power({
            "study_design": "independent_groups", "equivalence_margin": 0.5,
            "assumed_true_difference": true_difference,
            "assumed_standard_deviation": 1.0, "alpha": 0.05,
            "target_power": 0.8,
        })


def test_equivalence_power_cli_preserves_input_provenance(tmp_path, capsys) -> None:
    import json
    from research_machine.interfaces.cli import main

    spec = {
        "study_design": "independent_groups", "equivalence_margin": 0.5,
        "assumed_true_difference": 0.0, "assumed_standard_deviation": 1.0,
        "alpha": 0.05, "target_power": 0.8,
    }
    path = tmp_path / "equivalence-power.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    assert main([
        "--json", "design", "equivalence-power", "--spec-file", str(path),
    ]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["analyzable_n_per_group"] == 69
    assert result["provenance"]["specification"] == spec
    assert result["provenance"]["scientific_evidence_eligible"] is False


def test_practical_power_cli_preserves_input_provenance(tmp_path, capsys) -> None:
    import json
    from research_machine.interfaces.cli import main

    spec = {
        "study_design": "independent_groups",
        "smallest_effect_size_of_interest": 0.5,
        "assumed_true_effect": 1.0, "assumed_standard_deviation": 1.0,
        "alpha": 0.05, "confidence_level": 0.95,
        "target_power": 0.8, "alternative": "positive",
    }
    path = tmp_path / "practical-power.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    assert main([
        "--json", "design", "practical-power", "--spec-file", str(path),
    ]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["analyzable_n_per_group"] == 63
    assert result["provenance"]["specification"] == spec
    assert result["provenance"]["scientific_evidence_eligible"] is False


def test_equivalence_power_receipt_binds_protocol_margin_alpha_and_interval() -> None:
    plan = build_sample_size_planning_receipt({
        "strategy": "equivalence_power", "target_hypothesis_id": "h1",
        "target_measurement_id": "m1", "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups", "equivalence_margin": 0.5,
            "assumed_true_difference": 0.0, "assumed_standard_deviation": 1.0,
            "alpha": 0.05, "target_power": 0.8,
        },
        "justification": "Power the registered interval-within-margin decision.",
    })
    contract = AnalysisContract(
        **{**_planning_contract().__dict__,
           "support_rule": "interval_within_equivalence_margin",
           "confidence_level": 0.90}
    )
    validate_planning_inference_coherence(
        sample_size_plan=plan, analysis_contract=contract,
        expected_direction="equivalence", multiplicity_alpha=0.05,
        measurement_unit="fixture units", smallest_effect_size_of_interest=0.5,
        maximum_excluded_fraction=0.25,
    )
    with pytest.raises(ValidationError, match="margin must match"):
        validate_planning_inference_coherence(
            sample_size_plan=plan, analysis_contract=contract,
            expected_direction="equivalence", multiplicity_alpha=0.05,
            measurement_unit="fixture units", smallest_effect_size_of_interest=0.4,
            maximum_excluded_fraction=0.25,
        )


def test_precision_sensitivity_cli_preserves_explicit_assumptions(tmp_path, capsys):
    import json
    from research_machine.interfaces.cli import main
    spec = {"study_design": "independent_groups", "target_half_width": 1,
            "assumed_standard_deviation": 2,
            "maximum_observed_to_assumed_sd_ratio": 1.5,
            "sensitivity_standard_deviations": [1, 2, 4]}
    path = tmp_path / "plan.json"
    original = json.dumps(spec)
    path.write_text(original)
    assert main(["--json", "design", "precision", "--spec-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    scenarios = result["sensitivity"]["scenarios"]
    assert [item["assumed_standard_deviation"] for item in scenarios] == [1, 2, 4]
    assert [item["analyzable_n_per_group"] for item in scenarios] == [8, 31, 123]
    assert result["analyzable_n_per_group"] == 31
    assert result["maximum_observed_to_assumed_sd_ratio"] == 1.5
    assert path.read_text() == original
    import hashlib
    provenance = result["provenance"]
    assert provenance["specification"] == spec
    assert provenance["specification_sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert provenance["specification_size_bytes"] == len(original.encode())
    assert provenance["scientific_evidence_eligible"] is False
    path.write_text(original + "\n")
    assert main(["--json", "design", "precision", "--spec-file", str(path)]) == 0
    reformatted = json.loads(capsys.readouterr().out)["result"]
    assert reformatted["analyzable_n_per_group"] == result["analyzable_n_per_group"]
    assert reformatted["provenance"]["specification_sha256"] != provenance["specification_sha256"]


@pytest.mark.parametrize("scenarios", [[], [1, 1.0], [False], [None], [-1], [float("inf")], "1,2"])
def test_invalid_precision_scenarios_fail_closed(scenarios):
    with pytest.raises(ValidationError):
        plan_two_group_precision({"study_design": "independent_groups", "target_half_width": 1,
                                  "assumed_standard_deviation": 2, "sensitivity_standard_deviations": scenarios})


@pytest.mark.parametrize("sd,width", [(1e308, 1e-308), (1e-308, 1e308), (10 ** 1000, 1)])
def test_unrepresentable_precision_target_rejects_cleanly(sd, width):
    with pytest.raises(ValidationError):
        plan_two_group_precision({"study_design": "independent_groups", "target_half_width": width,
                                  "assumed_standard_deviation": sd})


def test_precision_floor_and_extreme_confidence_are_explicit():
    import math
    spec = {"study_design": "independent_groups", "target_half_width": 100,
            "assumed_standard_deviation": 1}
    plan = plan_two_group_precision(spec)
    assert plan["analyzable_n_per_group"] == 2
    assert plan["minimum_two_per_group_applied"] is True
    extreme = plan_two_group_precision({**spec, "confidence_level": math.nextafter(1, 0)})
    assert math.isfinite(extreme["normal_quantile"])


def test_two_group_precision_plan_requires_explicit_design_and_variability() -> None:
    spec = {
        "study_design": "independent_groups",
        "target_half_width": 1.0,
        "assumed_standard_deviation": 2.0,
        "confidence_level": 0.95,
        "anticipated_attrition_fraction": 0.1,
    }
    plan = plan_two_group_precision(spec)
    assert plan["enrollment_n_per_group"] >= plan["analyzable_n_per_group"]
    with pytest.raises(ValidationError, match="study_design"):
        plan_two_group_precision({**spec, "study_design": "paired"})


def test_two_group_power_plan_is_explicit_bounded_and_attrition_aware() -> None:
    plan = plan_two_group_power({
        "study_design": "independent_groups",
        "smallest_effect_size_of_interest": 0.5,
        "assumed_standard_deviation": 1.0,
        "alpha": 0.05,
        "target_power": 0.8,
        "alternative": "two_sided",
        "anticipated_attrition_fraction": 0.1,
    })
    assert plan["analyzable_n_per_group"] == 63
    assert plan["enrollment_n_per_group"] == 70
    assert plan["standardized_effect_size"] == 0.5
    assert plan["scientific_interpretation_verified"] is False
    assert any("multiplicity" in item for item in plan["assumptions"])
    assert any("causal identification" in item for item in plan["assumptions"])


def test_power_sensitivity_and_cli_preserve_researcher_assumptions(
    tmp_path, capsys
) -> None:
    import hashlib
    import json
    from research_machine.interfaces.cli import main

    spec = {
        "study_design": "independent_groups",
        "smallest_effect_size_of_interest": 0.5,
        "assumed_standard_deviation": 1.0,
        "sensitivity_effect_sizes": [0.25, 0.5, 1.0],
        "sensitivity_standard_deviations": [0.75, 1.0, 1.5],
    }
    path = tmp_path / "power.json"
    raw = json.dumps(spec)
    path.write_text(raw, encoding="utf-8")
    assert main(["--json", "design", "power", "--spec-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert [item["analyzable_n_per_group"] for item in result["sensitivity"][
        "smallest_effect_size_of_interest"
    ]] == [252, 63, 16]
    assert [item["analyzable_n_per_group"] for item in result["sensitivity"][
        "assumed_standard_deviation"
    ]] == [36, 63, 142]
    assert result["provenance"]["specification"] == spec
    assert result["provenance"]["specification_sha256"] == hashlib.sha256(
        raw.encode()
    ).hexdigest()
    assert result["provenance"]["scientific_evidence_eligible"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"study_design": "paired"},
        {"smallest_effect_size_of_interest": 0},
        {"assumed_standard_deviation": float("inf")},
        {"alpha": 0},
        {"target_power": 1},
        {"alternative": "post_hoc"},
        {"anticipated_attrition_fraction": 0.9},
        {"sensitivity_effect_sizes": [0.5, 0.5]},
        {"unknown": 1},
    ],
)
def test_invalid_power_plans_fail_closed(overrides) -> None:
    spec = {
        "study_design": "independent_groups",
        "smallest_effect_size_of_interest": 0.5,
        "assumed_standard_deviation": 1.0,
        **overrides,
    }
    with pytest.raises(ValidationError):
        plan_two_group_power(spec)


def test_protocol_binds_recomputed_sample_size_plan_and_rejects_forgery(
    tmp_path,
) -> None:
    from dataclasses import fields
    from research_machine.application.commands import CreateProtocol, RecordRun
    from research_machine.domain.models import (
        AnalysisMode, DatasetArtifact, ProtocolKind, QualityGateResult,
        QualityGateStatus,
    )
    from test_execution import prepared_service

    service, hypothesis_id = prepared_service(tmp_path)
    planning_input = {
        "strategy": "power",
        "specification": {
            "study_design": "independent_groups",
            "smallest_effect_size_of_interest": 0.5,
            "assumed_standard_deviation": 1.0,
            "alpha": 0.05,
            "target_power": 0.8,
            "alternative": "two_sided",
            "anticipated_attrition_fraction": 0.1,
        },
        "justification": "Power the registered primary comparison for the smallest important effect.",
    }
    command = CreateProtocol(
        experiment_id="power-bound-protocol",
        title="Power-bound protocol",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis_id],
        primary_outcome="Registered outcome",
        protocol_kind=ProtocolKind.FORMAL,
        methodology="Apply the registered comparison.",
        quality_requirements=["integrity"],
        controls=["A negative control must remain null."],
        expected_outputs=["Registered result"],
        success_conditions=["Report the registered comparison."],
        environment_requirements=["Pinned analysis environment."],
        sample_size_or_stopping_rule="Enroll 70 per group for 63 analyzable per group.",
        sample_size_plan=planning_input,
        failure_conditions=["The integrity gate fails."],
        safety_constraints=["No physical intervention."],
        analysis_code_hash="a" * 64,
    )
    draft = service.create_protocol(command)
    assert draft.sample_size_plan["calculation"]["analyzable_n_per_group"] == 63
    assert draft.sample_size_plan["calculation"]["enrollment_n_per_group"] == 70
    frozen = service.freeze_protocol(draft.protocol_id)
    assert frozen.protocol_hash
    output = tmp_path / "unbound-plan-result.json"
    output.write_text('{"result":"complete"}\n', encoding="utf-8")
    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    unbound_run = service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at="2026-09-02T12:01:00Z",
        completed_at="2026-09-02T12:02:00Z",
        analysis_code_hash="a" * 64,
        environment_hash="b" * 64,
        output_artifacts=[DatasetArtifact(
            output.name, output_sha256, output.stat().st_size, "application/json"
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "integrity", QualityGateStatus.PASSED, "Output was checked.",
            details={"evidence_sha256": output_sha256},
        )],
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared", "deviations": [],
        }},
    ))
    assert unbound_run.status.value == "completed"
    assert unbound_run.scientific_evidence_eligible is False
    assert unbound_run.metadata["sample_size_plan_check"]["status"] == "unbound"

    values = {field.name: getattr(frozen, field.name) for field in fields(CreateProtocol)}
    amended = service.amend_protocol(
        frozen.protocol_id,
        CreateProtocol(**values),
        "Clarify without changing the planning assumptions.",
        "before_collection",
        "not_seen",
    )
    assert amended.sample_size_plan == frozen.sample_size_plan

    forged = dict(frozen.sample_size_plan)
    forged["calculation"] = {
        **forged["calculation"],
        "enrollment_total_n": 2,
    }
    with pytest.raises(ValidationError, match="does not reproduce exactly"):
        service.create_protocol(CreateProtocol(
            **{**command.__dict__, "experiment_id": "forged-plan", "sample_size_plan": forged}
        ))
