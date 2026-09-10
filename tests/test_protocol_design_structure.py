"""Synthetic protocol fixtures exercising dependence and commitment boundaries."""
from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import pytest

from research_machine.application.commands import CreateProtocol
from research_machine.application.service import _protocol_commitment
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisContract, AnalysisFamilyMember, AnalysisStepContract, ConclusionContract,
    CalibrationCriterion, CanaryTargetPlan, ExperimentProtocol, MeasurementDefinition, MeasurementRole,
    MeasurementValidityCheck, EvidenceDirection, ClaimLevel,
)
from test_execution import prepared_service, frozen_formal_protocol
from test_ethics_gate import _human_protocol
from research_machine.application.policies import validate_protocol_freeze
from research_machine.domain.models import ProtocolKind


def _analysis_measurements(primary: str, control: str) -> list[MeasurementDefinition]:
    def definition(measurement_id, role, target, condition, data_column=""):
        return MeasurementDefinition(
            measurement_id=measurement_id, role=role, registered_target=target,
            observable="Numeric synthetic outcome" if role is MeasurementRole.PRIMARY else "Control response",
            input_condition=condition, parameter_values={"scale": "fixture units"},
            evaluation_point="registered endpoint", convention="higher is larger",
            aggregation="mean by registered group", tolerance="exact fixture parsing",
            expected_behavior="Reported regardless of direction", data_column=data_column,
            scale_type="interval" if data_column else "", unit="fixture units" if data_column else "",
            valid_min=0.0 if data_column else None, valid_max=100.0 if data_column else None,
            missing_value_codes=["<blank>"] if data_column else [],
        )
    return [
        definition("primary-measurement", MeasurementRole.PRIMARY, primary, "all eligible rows", "outcome"),
        definition("control-measurement", MeasurementRole.CONTROL, control, "registered control rows"),
    ]


def _multi_step_protocol() -> ExperimentProtocol:
    base = _human_protocol(human_subjects=False)
    measurements = _analysis_measurements(base.primary_outcome, base.controls[0])
    measurements.insert(1, MeasurementDefinition(
        measurement_id="secondary-measurement", role=MeasurementRole.SECONDARY,
        registered_target="Secondary outcome", observable="Numeric secondary outcome",
        input_condition="all eligible rows", parameter_values={"scale": "fixture units"},
        evaluation_point="registered endpoint", convention="higher is larger",
        aggregation="mean by registered group", tolerance="exact fixture parsing",
        expected_behavior="Reported regardless of direction", data_column="secondary",
        scale_type="interval", unit="fixture units", valid_min=0.0, valid_max=100.0,
        missing_value_codes=["<blank>"],
    ))
    contract = AnalysisContract(
        primary_hypothesis_id="h1", primary_measurement_id="primary-measurement",
        method="independent_mean_difference_ci", outcome_column="outcome",
        group_column="group", groups=["a", "b"],
        estimand="Mean outcome difference, group a minus group b.",
        contrast_definition="group a minus group b",
        contrast_groups=["a", "b"],
        missing_data_policy="complete_case", assignment_type="nonrandomized",
        effect_estimate_path="/result/mean_difference_first_minus_second",
        uncertainty_path="/result/confidence_interval", null_value=0.0,
        support_rule="interval_excludes_null", confidence_level=0.95,
        minimum_analyzable_units=2,
        maximum_excluded_fraction=0.25,
        maximum_group_excluded_fraction_difference=0.25,
        missingness_assumption="Excluded records do not materially distort the contrast.",
        missingness_assessment_plan="Inspect total and group-specific exclusions.",
        missingness_failure_response="Stop primary interpretation.",
        missingness_assessment_kind="empirical_diagnostic",
        missingness_assessment_gate_id="missingness-assessed",
    )
    primary = AnalysisStepContract(
        "primary-estimate", "primary_estimate", "independent_mean_difference_ci", "b" * 64,
        "a" * 64, [], "h1", base.primary_outcome, "primary-measurement",
    )
    primary_test = AnalysisStepContract(
        "primary-test", "confirmatory_test", "permutation_mean_difference", "1" * 64,
        "2" * 64, [], "h1", base.primary_outcome, "primary-measurement",
        "/result/two_sided_permutation_p",
    )
    secondary_test = AnalysisStepContract(
        "secondary-test", "confirmatory_test", "permutation_mean_difference", "c" * 64,
        "d" * 64, [], "h1", "Secondary outcome", "secondary-measurement",
        "/result/two_sided_permutation_p",
    )
    adjustment = AnalysisStepContract(
        "confirmatory-holm", "multiplicity", "holm_adjustment", "e" * 64,
        "f" * 64, ["primary-test", "secondary-test"], family_id="confirmatory-family",
        family_members=[
            AnalysisFamilyMember("primary-test-p", "primary-test", "h1", base.primary_outcome, "primary-measurement"),
            AnalysisFamilyMember("secondary-test-p", "secondary-test", "h1", "Secondary outcome", "secondary-measurement"),
        ], alpha=0.05,
    )
    return replace(
        base, secondary_outcomes=["Secondary outcome"],
        confirmatory_outcomes=[base.primary_outcome, "Secondary outcome"],
        exploratory_outcomes=[], multiplicity_method="holm", multiplicity_alpha=0.05,
        quality_requirements=["integrity", "missingness-assessed"],
        measurement_definitions=measurements, unit_id_column="unit",
        analysis_specification_sha256="b" * 64, analysis_contract=contract,
        analysis_steps=[primary, primary_test, secondary_test, adjustment],
        conclusion_contract=ConclusionContract(
            primary_hypothesis_id="h1",
            decision_rule="adjusted_primary_rejection_and_interval_and_practical_significance",
            smallest_effect_size_of_interest=1.0,
            effect_scale="mean_difference_first_minus_second",
            effect_unit="fixture units",
            population="Eligible fixture units represented by the sampling plan.",
            setting="The registered synthetic test setting.",
            time_window="The registered endpoint only.",
            non_supporting_direction=EvidenceDirection.INCONCLUSIVE,
            permitted_claim_level=ClaimLevel.STATISTICAL_ASSOCIATION,
            higher_level_conclusions_unsupported=[
                "No mechanism, causal direction, or out-of-scope generalization."
            ],
        ),
    )


def test_canonical_measurement_validity_plan_is_bound_and_gate_dedicated() -> None:
    protocol = _multi_step_protocol()
    check = MeasurementValidityCheck(
        check_id="primary-reference-agreement",
        measurement_id="primary-measurement",
        evidence_type="criterion",
        validity_claim="The primary measurement agrees with a traceable reference.",
        assessment_plan="Blindly compare the prespecified subset before analysis unlock.",
        acceptance_criterion="At least 95% of comparisons differ by no more than two units.",
        failure_response="Stop primary interpretation and investigate measurement failure.",
        assessment_gate_id="measurement-validity-assessed",
    )
    bound = replace(
        protocol,
        measurement_validity_checks=[check],
        quality_requirements=[*protocol.quality_requirements, "measurement-validity-assessed"],
    )
    validate_protocol_freeze(bound)
    restored = ExperimentProtocol.from_dict(bound.to_dict())
    assert restored.measurement_validity_checks == [check]
    assert _protocol_commitment(bound) != _protocol_commitment(protocol)

    with pytest.raises(ValidationError, match="exact protocol measurement_id"):
        validate_protocol_freeze(replace(
            bound,
            measurement_validity_checks=[replace(check, measurement_id="invented")],
        ))
    with pytest.raises(ValidationError, match="must be dedicated"):
        validate_protocol_freeze(replace(
            bound,
            measurement_validity_checks=[replace(
                check, assessment_gate_id="missingness-assessed"
            )],
        ))
    with pytest.raises(ValidationError, match="measurement validity check IDs"):
        validate_protocol_freeze(replace(
            bound,
            measurement_validity_checks=[
                check,
                replace(
                    check,
                    check_id="primary-reference-agreement",
                    assessment_gate_id="second-validity-assessed",
                ),
            ],
            quality_requirements=[
                *bound.quality_requirements,
                "second-validity-assessed",
            ],
        ))
    with pytest.raises(ValidationError, match="measurement validity assessment gates"):
        validate_protocol_freeze(replace(
            bound,
            measurement_validity_checks=[
                check,
                replace(
                    check,
                    check_id="secondary-reference-agreement",
                    assessment_gate_id="measurement-validity-assessed",
                ),
            ],
        ))


def test_protocol_freeze_requires_multi_factor_interpretability_plan() -> None:
    protocol = _multi_step_protocol()
    with pytest.raises(ValidationError, match="multi-factor interventions require"):
        validate_protocol_freeze(replace(
            protocol,
            manipulated_factors=["person", "room"],
        ))

    with pytest.raises(ValidationError, match="factor_interpretability_plan"):
        validate_protocol_freeze(replace(
            protocol,
            manipulated_factors=["person", "room"],
            factorial_or_crossover_design=True,
        ))

    interpretable = replace(
        protocol,
        manipulated_factors=["person", "room"],
        factorial_or_crossover_design=True,
        factor_interpretability_plan=(
            "Cross person and room assignments before interpreting either factor."
        ),
    )
    validate_protocol_freeze(interpretable)
    restored = ExperimentProtocol.from_dict(interpretable.to_dict())
    assert restored.manipulated_factors == ["person", "room"]
    assert _protocol_commitment(interpretable) != _protocol_commitment(protocol)


def test_protocol_freeze_binds_canary_target_plan_to_dedicated_gate() -> None:
    protocol = _multi_step_protocol()
    plan = CanaryTargetPlan(
        plan_id="masked-target-plan",
        candidate_target_ids=[
            "actual-state",
            "delayed-replay",
            "silent-marker",
        ],
        seed_commitment_sha256="1" * 64,
        assignment_artifact_sha256="2" * 64,
        masking_plan="A custodian withholds the target until analysis lock.",
        ethical_disclosure="Participants consent to masked target conditions.",
        assessment_gate_id="canary-target-assessed",
    )
    bound = replace(
        protocol,
        quality_requirements=[
            *protocol.quality_requirements,
            "canary-target-assessed",
        ],
        canary_target_plan=plan,
    )

    validate_protocol_freeze(bound)
    restored = ExperimentProtocol.from_dict(bound.to_dict())
    assert restored.canary_target_plan == plan
    assert _protocol_commitment(bound) != _protocol_commitment(protocol)

    with pytest.raises(ValidationError, match="at least two candidate targets"):
        validate_protocol_freeze(replace(
            bound,
            canary_target_plan=replace(plan, candidate_target_ids=["actual-state"]),
        ))
    with pytest.raises(ValidationError, match="must be a required protocol quality gate"):
        validate_protocol_freeze(replace(
            bound,
            canary_target_plan=replace(plan, assessment_gate_id="not-required"),
        ))
    with pytest.raises(ValidationError, match="must be dedicated"):
        validate_protocol_freeze(replace(
            bound,
            canary_target_plan=replace(plan, assessment_gate_id="missingness-assessed"),
        ))
    with pytest.raises(ValidationError, match="assignment_artifact_sha256"):
        validate_protocol_freeze(replace(
            bound,
            canary_target_plan=replace(plan, assignment_artifact_sha256="2" * 63),
        ))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("check_id", "primary-reference-agreement "),
        ("measurement_id", " primary-measurement"),
        ("assessment_gate_id", "measurement-validity-assessed "),
    ],
)
def test_measurement_validity_check_handles_must_be_canonical_at_freeze(
    field, value
) -> None:
    protocol = _multi_step_protocol()
    check = MeasurementValidityCheck(
        check_id="primary-reference-agreement",
        measurement_id="primary-measurement",
        evidence_type="criterion",
        validity_claim="The primary measurement agrees with a traceable reference.",
        assessment_plan="Blindly compare the prespecified subset before analysis unlock.",
        acceptance_criterion="At least 95% of comparisons differ by no more than two units.",
        failure_response="Stop primary interpretation and investigate measurement failure.",
        assessment_gate_id="measurement-validity-assessed",
    )
    bound = replace(
        protocol,
        measurement_validity_checks=[replace(check, **{field: value})],
        quality_requirements=[*protocol.quality_requirements, "measurement-validity-assessed"],
    )

    with pytest.raises(ValidationError, match="canonical"):
        validate_protocol_freeze(bound)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_type", " criterion "),
        ("validity_claim", " The primary measurement agrees with a traceable reference. "),
        ("assessment_plan", " Blindly compare the prespecified subset before analysis unlock. "),
        ("acceptance_criterion", " At least 95% of comparisons differ by no more than two units. "),
        ("failure_response", " Stop primary interpretation and investigate measurement failure. "),
    ],
)
def test_measurement_validity_check_semantics_must_be_canonical_at_freeze(
    field, value
) -> None:
    protocol = _multi_step_protocol()
    check = MeasurementValidityCheck(
        check_id="primary-reference-agreement",
        measurement_id="primary-measurement",
        evidence_type="criterion",
        validity_claim="The primary measurement agrees with a traceable reference.",
        assessment_plan="Blindly compare the prespecified subset before analysis unlock.",
        acceptance_criterion="At least 95% of comparisons differ by no more than two units.",
        failure_response="Stop primary interpretation and investigate measurement failure.",
        assessment_gate_id="measurement-validity-assessed",
    )
    bound = replace(
        protocol,
        measurement_validity_checks=[replace(check, **{field: value})],
        quality_requirements=[*protocol.quality_requirements, "measurement-validity-assessed"],
    )

    with pytest.raises(
        ValidationError,
        match=f"measurement validity check {field} must be canonical",
    ):
        validate_protocol_freeze(bound)


def test_calibration_acceptance_ids_are_unambiguous_at_freeze() -> None:
    protocol = replace(
        _human_protocol(human_subjects=False),
        measurement_custody_requirements=["clock-sync"],
        calibration_acceptance_criteria=[
            CalibrationCriterion(
                "clock-residual", "clock", "absolute clock residual", "ms",
                "Keep synchronization error below the registered event limit.",
                lower_bound=0.0, upper_bound=1.0,
            ),
        ],
    )
    validate_protocol_freeze(protocol)

    with pytest.raises(
        ValidationError, match="calibration criterion and calibration IDs"
    ):
        validate_protocol_freeze(replace(
            protocol,
            calibration_acceptance_criteria=[
                *protocol.calibration_acceptance_criteria,
                CalibrationCriterion(
                    "clock-residual", "other-clock", "alternate residual", "ms",
                    "A duplicate criterion ID cannot become a new criterion.",
                    lower_bound=0.0, upper_bound=1.0,
                ),
            ],
        ))
    with pytest.raises(
        ValidationError, match="calibration criterion and calibration IDs"
    ):
        validate_protocol_freeze(replace(
            protocol,
            calibration_acceptance_criteria=[
                *protocol.calibration_acceptance_criteria,
                CalibrationCriterion(
                    "other-residual", "clock", "alternate residual", "ms",
                    "A duplicate calibration ID cannot become a new calibration.",
                    lower_bound=0.0, upper_bound=1.0,
                ),
            ],
        ))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("criterion_id", "clock-residual "),
        ("calibration_id", " clock"),
        ("quantity", " absolute clock residual"),
        ("unit", "ms "),
        ("rationale", " Keep synchronization error below the registered event limit."),
    ],
)
def test_calibration_acceptance_fields_must_be_canonical_at_freeze(field, value) -> None:
    protocol = replace(
        _human_protocol(human_subjects=False),
        measurement_custody_requirements=["clock-sync"],
        calibration_acceptance_criteria=[
            replace(
                CalibrationCriterion(
                    "clock-residual", "clock", "absolute clock residual", "ms",
                    "Keep synchronization error below the registered event limit.",
                    lower_bound=0.0, upper_bound=1.0,
                ),
                **{field: value},
            ),
        ],
    )
    with pytest.raises(ValidationError, match="canonical"):
        validate_protocol_freeze(protocol)


def test_scalar_calibration_acceptance_preserves_legacy_commitment_shape() -> None:
    protocol = replace(
        _human_protocol(human_subjects=False),
        measurement_custody_requirements=["clock-sync"],
        calibration_acceptance_criteria=[
            CalibrationCriterion(
                "clock-residual",
                "clock",
                "absolute clock residual",
                "ms",
                "Keep synchronization error below the registered event limit.",
                lower_bound=0.0,
                upper_bound=1.0,
            ),
        ],
    )
    legacy = protocol.to_dict()
    legacy["calibration_acceptance_criteria"][0].pop("component_bounds")

    assert _protocol_commitment(protocol) == _protocol_commitment(
        ExperimentProtocol.from_dict(legacy)
    )


def test_multicomponent_calibration_acceptance_is_hash_bound_at_freeze() -> None:
    protocol = replace(
        _human_protocol(human_subjects=False),
        measurement_custody_requirements=["field-map-check"],
        calibration_acceptance_criteria=[
            CalibrationCriterion(
                "field-map-residuals",
                "field-map",
                "two-axis field-map residual",
                "milliunit",
                "Every registered calibration axis must remain inside tolerance.",
                component_bounds=[
                    {
                        "component_id": "x-axis",
                        "quantity": "x-axis residual",
                        "unit": "milliunit",
                        "lower_bound": -0.5,
                        "upper_bound": 0.5,
                    },
                    {
                        "component_id": "y-axis",
                        "quantity": "y-axis residual",
                        "unit": "milliunit",
                        "lower_bound": -0.5,
                        "upper_bound": 0.5,
                    },
                ],
            ),
        ],
    )

    validate_protocol_freeze(protocol)

    altered = replace(
        protocol,
        calibration_acceptance_criteria=[
            replace(
                protocol.calibration_acceptance_criteria[0],
                component_bounds=[
                    *protocol.calibration_acceptance_criteria[0].component_bounds[:1],
                    {
                        **protocol.calibration_acceptance_criteria[0].component_bounds[1],
                        "upper_bound": 0.25,
                    },
                ],
            ),
        ],
    )
    assert _protocol_commitment(protocol) != _protocol_commitment(altered)


@pytest.mark.parametrize(
    ("component_bounds", "message"),
    [
        (
            [{
                "component_id": " x-axis ",
                "quantity": "x-axis residual",
                "unit": "milliunit",
                "lower_bound": -0.5,
                "upper_bound": 0.5,
            }],
            "component_bounds\\[0\\].component_id",
        ),
        (
            [
                {
                    "component_id": "x-axis",
                    "quantity": "x-axis residual",
                    "unit": "milliunit",
                    "lower_bound": -0.5,
                    "upper_bound": 0.5,
                },
                {
                    "component_id": "x-axis",
                    "quantity": "duplicate residual",
                    "unit": "milliunit",
                    "lower_bound": -0.5,
                    "upper_bound": 0.5,
                },
            ],
            "component_id values must be unique",
        ),
        (
            [{
                "component_id": "x-axis",
                "quantity": "x-axis residual",
                "unit": "milliunit",
                "lower_bound": None,
                "upper_bound": None,
            }],
            "require a lower_bound or upper_bound",
        ),
        (
            [{
                "component_id": "x-axis",
                "quantity": "x-axis residual",
                "unit": "milliunit",
                "lower_bound": 1.0,
                "upper_bound": 0.5,
            }],
            "lower_bound must not exceed",
        ),
    ],
)
def test_multicomponent_calibration_acceptance_rejects_invalid_bounds(
    component_bounds, message
) -> None:
    protocol = replace(
        _human_protocol(human_subjects=False),
        measurement_custody_requirements=["field-map-check"],
        calibration_acceptance_criteria=[
            CalibrationCriterion(
                "field-map-residuals",
                "field-map",
                "two-axis field-map residual",
                "milliunit",
                "Every registered calibration axis must remain inside tolerance.",
                component_bounds=component_bounds,
            ),
        ],
    )

    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(protocol)


def test_calibration_acceptance_rejects_mixed_scalar_and_component_bounds() -> None:
    protocol = replace(
        _human_protocol(human_subjects=False),
        measurement_custody_requirements=["field-map-check"],
        calibration_acceptance_criteria=[
            CalibrationCriterion(
                "field-map-residuals",
                "field-map",
                "two-axis field-map residual",
                "milliunit",
                "Every registered calibration axis must remain inside tolerance.",
                lower_bound=-0.5,
                upper_bound=0.5,
                component_bounds=[{
                    "component_id": "x-axis",
                    "quantity": "x-axis residual",
                    "unit": "milliunit",
                    "lower_bound": -0.5,
                    "upper_bound": 0.5,
                }],
            ),
        ],
    )

    with pytest.raises(ValidationError, match="cannot mix scalar bounds"):
        validate_protocol_freeze(protocol)


def test_measurement_contract_rejects_normalized_observed_missing_overlap() -> None:
    protocol = _human_protocol(human_subjects=False)
    measurements = _analysis_measurements(protocol.primary_outcome, protocol.controls[0])
    measurements[0] = replace(
        measurements[0],
        scale_type="nominal",
        unit="category",
        admissible_values=["detected"],
        missing_value_codes=["detected"],
        valid_min=None,
        valid_max=None,
    )
    with pytest.raises(
        ValidationError,
        match="missing-value codes cannot also be admissible observations",
    ):
        validate_protocol_freeze(
            replace(protocol, measurement_definitions=measurements)
        )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"data_column": " outcome "}, "data_column must be canonical"),
        ({"data_column": "SECONDARY"}, "case-insensitively unique"),
        ({"data_column": "group"}, "distinct from identity, assignment, and capture-time"),
    ],
)
def test_measurement_contract_rejects_ambiguous_executable_columns(change, message) -> None:
    protocol = _multi_step_protocol()
    measurements = list(protocol.measurement_definitions)
    measurements[0] = replace(measurements[0], **change)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(protocol, measurement_definitions=measurements))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"measurement_id": " primary-measurement "}, "measurement_id must be canonical"),
        ({"registered_target": " Human effect "}, "registered_target must be canonical"),
    ],
)
def test_measurement_contract_rejects_noncanonical_measurement_handles(change, message) -> None:
    protocol = _human_protocol(human_subjects=False)
    measurements = _analysis_measurements(protocol.primary_outcome, protocol.controls[0])
    measurements[0] = replace(measurements[0], **change)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(protocol, measurement_definitions=measurements))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"observable": " Numeric synthetic outcome "}, "observable must be canonical"),
        ({"input_condition": " all eligible rows "}, "input_condition must be canonical"),
        ({"evaluation_point": " registered endpoint "}, "evaluation_point must be canonical"),
        ({"convention": " higher is larger "}, "convention must be canonical"),
        ({"aggregation": " mean by registered group "}, "aggregation must be canonical"),
        ({"tolerance": " exact fixture parsing "}, "tolerance must be canonical"),
        ({"expected_behavior": " Reported regardless of direction "}, "expected_behavior must be canonical"),
        ({"unit": " fixture units "}, "unit must be canonical"),
        ({"admissible_values": [" observed "]}, "admissible_values item must be canonical"),
        ({"missing_value_codes": [" <blank> "]}, "missing_value_codes item must be canonical"),
    ],
)
def test_measurement_contract_rejects_noncanonical_measurement_semantics(change, message) -> None:
    protocol = _human_protocol(human_subjects=False)
    measurements = _analysis_measurements(protocol.primary_outcome, protocol.controls[0])
    measurements[0] = replace(measurements[0], **change)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(protocol, measurement_definitions=measurements))


@pytest.mark.parametrize(
    ("parameter_values", "message"),
    [
        ({" scale ": "fixture units"}, "parameter_values key must be canonical"),
        ({"scale": " fixture units "}, "parameter_values\\['scale'\\] must be canonical"),
    ],
)
def test_measurement_contract_rejects_noncanonical_parameter_bindings(
    parameter_values, message
) -> None:
    protocol = _human_protocol(human_subjects=False)
    measurements = _analysis_measurements(protocol.primary_outcome, protocol.controls[0])
    measurements[0] = replace(measurements[0], parameter_values=parameter_values)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(protocol, measurement_definitions=measurements))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("method", " independent_mean_difference_ci", "analysis_contract.method"),
        ("outcome_column", "outcome ", "analysis_contract.outcome_column"),
        ("group_column", " group", "analysis_contract.group_column"),
        (
            "effect_estimate_path",
            " /result/mean_difference_first_minus_second",
            "analysis_contract.effect_estimate_path",
        ),
        (
            "contrast_definition",
            " group a minus group b",
            "analysis_contract.contrast_definition",
        ),
        (
            "missingness_assessment_gate_id",
            "missingness-assessed ",
            "analysis_contract.missingness_assessment_gate_id",
        ),
    ],
)
def test_analysis_contract_rejects_noncanonical_text_handles(
    field: str, value: str, message: str
) -> None:
    protocol = _multi_step_protocol()
    contract = replace(protocol.analysis_contract, **{field: value})
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(protocol, analysis_contract=contract))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("groups", [" a", "b"], "analysis_contract.groups"),
        ("contrast_groups", ["a", "b "], "analysis_contract.contrast_groups"),
        (
            "adjustment_columns",
            [" baseline"],
            "analysis_contract.adjustment_columns",
        ),
    ],
)
def test_analysis_contract_rejects_noncanonical_list_handles(
    field: str, value: list[str], message: str
) -> None:
    protocol = _multi_step_protocol()
    contract = replace(protocol.analysis_contract, **{field: value})
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(protocol, analysis_contract=contract))


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"contrast_definition": ""},
            "analysis_contract.contrast_definition must declare the signed contrast",
        ),
        (
            {"contrast_groups": []},
            "analysis_contract.contrast_groups must exactly match",
        ),
        (
            {"contrast_groups": ["b", "a"]},
            "analysis_contract.contrast_groups must exactly match",
        ),
    ],
)
def test_analysis_contract_requires_explicit_signed_contrast(
    updates: dict[str, object], message: str
) -> None:
    protocol = _multi_step_protocol()
    contract = replace(protocol.analysis_contract, **updates)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(protocol, analysis_contract=contract))


def test_measurement_custody_requirement_ids_are_unambiguous_at_freeze() -> None:
    protocol = replace(
        _human_protocol(human_subjects=False),
        measurement_custody_requirements=["clock-sync", "clock-sync"],
        calibration_acceptance_criteria=[
            CalibrationCriterion(
                "clock-residual", "clock", "absolute clock residual", "ms",
                "Keep synchronization error below the registered event limit.",
                lower_bound=0.0, upper_bound=1.0,
            ),
        ],
    )
    with pytest.raises(ValidationError, match="measurement_custody_requirements"):
        validate_protocol_freeze(protocol)


def test_measurement_custody_requirement_ids_must_be_canonical_at_freeze() -> None:
    protocol = replace(
        _human_protocol(human_subjects=False),
        measurement_custody_requirements=["clock-sync "],
        calibration_acceptance_criteria=[
            CalibrationCriterion(
                "clock-residual", "clock", "absolute clock residual", "ms",
                "Keep synchronization error below the registered event limit.",
                lower_bound=0.0, upper_bound=1.0,
            ),
        ],
    )
    with pytest.raises(ValidationError, match="canonical"):
        validate_protocol_freeze(protocol)


def test_quality_requirement_ids_are_unambiguous_at_freeze() -> None:
    protocol = replace(
        _multi_step_protocol(),
        quality_requirements=["integrity", "missingness-assessed", "integrity"],
    )
    with pytest.raises(ValidationError, match="quality_requirements"):
        validate_protocol_freeze(protocol)


def test_quality_requirement_ids_must_be_canonical_at_freeze() -> None:
    protocol = replace(
        _multi_step_protocol(),
        quality_requirements=["integrity", "missingness-assessed "],
    )
    with pytest.raises(ValidationError, match="canonical"):
        validate_protocol_freeze(protocol)


def test_frozen_analysis_workflow_binds_primary_secondary_and_holm_family() -> None:
    validate_protocol_freeze(_multi_step_protocol())


def test_service_freezes_prospective_equivalence_as_a_distinct_decision_rule(
    tmp_path,
) -> None:
    from research_machine.application.commands import ProposeHypothesis

    service, _ = prepared_service(tmp_path)
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="The group difference is smaller than the registered practical margin.",
        observable_prediction="The 90% interval lies wholly inside plus or minus 0.5 fixture units.",
        null_model="A practically important difference of at least 0.5 units remains compatible with the data.",
        primary_estimand="Mean outcome difference, group a minus group b.",
        contrast_definition="group a minus group b",
        contrast_groups=["a", "b"],
        expected_effect_direction="equivalence",
        falsification_conditions=["Either confidence bound reaches or crosses a registered equivalence bound."],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    template = _multi_step_protocol()
    contract = replace(
        template.analysis_contract,
        primary_hypothesis_id=hypothesis.hypothesis_id,
        support_rule="interval_within_equivalence_margin",
        confidence_level=0.90,
        minimum_analyzable_units=69,
    )
    conclusion = replace(
        template.conclusion_contract,
        primary_hypothesis_id=hypothesis.hypothesis_id,
        decision_rule="equivalence_interval_within_margin",
        smallest_effect_size_of_interest=0.5,
    )
    values = {field.name: getattr(template, field.name) for field in fields(CreateProtocol)}
    sample_size_plan = {
        "strategy": "equivalence_power",
        "target_hypothesis_id": hypothesis.hypothesis_id,
        "target_measurement_id": "primary-measurement",
        "measurement_unit": "fixture units",
        "specification": {
            "study_design": "independent_groups", "equivalence_margin": 0.5,
            "assumed_true_difference": 0.0, "assumed_standard_deviation": 1.0,
            "alpha": 0.05, "target_power": 0.8,
        },
        "justification": "Power the registered interval-within-margin decision.",
    }
    draft = service.create_protocol(CreateProtocol(**{
        **values, "experiment_id": "prospective-equivalence",
        "hypotheses_tested": [hypothesis.hypothesis_id],
        "secondary_outcomes": [], "confirmatory_outcomes": [template.primary_outcome],
        "exploratory_outcomes": [], "multiplicity_method": "single_test",
        "multiplicity_alpha": 0.05, "analysis_contract": contract,
        "measurement_definitions": [
            item for item in template.measurement_definitions
            if item.measurement_id != "secondary-measurement"
        ],
        "analysis_steps": [], "conclusion_contract": conclusion,
        "sample_size_plan": sample_size_plan,
    }))
    frozen = service.freeze_protocol(draft.protocol_id)
    assert frozen.analysis_contract.confidence_level == 0.90
    assert frozen.conclusion_contract.decision_rule == "equivalence_interval_within_margin"
    assert frozen.sample_size_plan["calculation"]["analyzable_n_per_group"] == 69

    incompatible = service.create_protocol(CreateProtocol(**{
        **values, "experiment_id": "false-equivalence-from-nonsignificance",
        "hypotheses_tested": [hypothesis.hypothesis_id],
        "secondary_outcomes": [], "confirmatory_outcomes": [template.primary_outcome],
        "exploratory_outcomes": [], "multiplicity_method": "single_test",
        "multiplicity_alpha": 0.05,
        "analysis_contract": replace(contract, confidence_level=0.95),
        "measurement_definitions": [
            item for item in template.measurement_definitions
            if item.measurement_id != "secondary-measurement"
        ],
        "analysis_steps": [], "conclusion_contract": conclusion,
        "sample_size_plan": sample_size_plan,
    }))
    with pytest.raises(ValidationError, match="one minus twice"):
        service.freeze_protocol(incompatible.protocol_id)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_member", "exactly cover confirmatory source steps"),
        ("alpha", "alpha must match"),
        ("cycle", "acyclic"),
        ("primary_hash", "exactly match the frozen primary"),
    ],
)
def test_analysis_workflow_rejects_selective_or_inconsistent_steps(mutation, message) -> None:
    protocol = _multi_step_protocol()
    steps = list(protocol.analysis_steps)
    if mutation == "missing_member":
        steps[3] = replace(steps[3], family_members=steps[3].family_members[:-1])
    elif mutation == "alpha":
        steps[3] = replace(steps[3], alpha=0.01)
    elif mutation == "cycle":
        steps[1] = replace(steps[1], depends_on=["confirmatory-holm"])
    else:
        steps[0] = replace(steps[0], specification_sha256="9" * 64)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(protocol, analysis_steps=steps))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("step_id", "analysis_steps\\[1\\].step_id"),
        ("depends_on", "analysis_steps\\[3\\].depends_on items"),
        ("family_id", "Holm multiplicity step family_id"),
        ("member_id", "family member_id"),
        ("source_step_id", "family source_step_id"),
    ],
)
def test_analysis_workflow_handles_must_be_canonical_at_freeze(
    mutation, message
) -> None:
    protocol = _multi_step_protocol()
    steps = list(protocol.analysis_steps)
    if mutation == "step_id":
        steps[1] = replace(steps[1], step_id="primary-test ")
    elif mutation == "depends_on":
        steps[3] = replace(steps[3], depends_on=["primary-test ", "secondary-test"])
    elif mutation == "family_id":
        steps[3] = replace(steps[3], family_id=" confirmatory-family")
    elif mutation == "member_id":
        members = list(steps[3].family_members)
        members[0] = replace(members[0], member_id="primary-test-p ")
        steps[3] = replace(steps[3], family_members=members)
    else:
        members = list(steps[3].family_members)
        members[0] = replace(members[0], source_step_id=" primary-test")
        steps[3] = replace(steps[3], family_members=members)

    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(protocol, analysis_steps=steps))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "typed conclusion_contract"),
        ("hypothesis", "primary analysis hypothesis"),
        ("threshold", "finite non-negative"),
        ("unit", "primary measurement unit"),
        ("claim_level", "causal scope"),
        ("unsupported", "name unsupported"),
    ],
)
def test_holm_freeze_rejects_incomplete_or_overbroad_conclusion_contract(mutation, message) -> None:
    protocol = _multi_step_protocol()
    contract = protocol.conclusion_contract
    assert contract is not None
    if mutation == "missing":
        changed = None
    elif mutation == "hypothesis":
        changed = replace(contract, primary_hypothesis_id="another-hypothesis")
    elif mutation == "threshold":
        changed = replace(contract, smallest_effect_size_of_interest=-0.1)
    elif mutation == "unit":
        changed = replace(contract, effect_unit="unregistered units")
    elif mutation == "claim_level":
        changed = replace(contract, permitted_claim_level=ClaimLevel.CAUSAL_DIRECTION)
    else:
        changed = replace(contract, higher_level_conclusions_unsupported=[])
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(protocol, conclusion_contract=changed))


def test_direct_conclusion_contract_requires_statistical_and_practical_support(tmp_path) -> None:
    from research_machine.application.policies import adjudicate_conclusion_contract

    service, hypothesis_id = prepared_service(tmp_path / "workspace")
    hypothesis = service.get_hypothesis(hypothesis_id)
    protocol = _multi_step_protocol()
    analysis = replace(protocol.analysis_contract, primary_hypothesis_id=hypothesis_id)
    conclusion = replace(
        protocol.conclusion_contract,
        primary_hypothesis_id=hypothesis_id,
        decision_rule="interval_and_practical_significance",
        smallest_effect_size_of_interest=2.0,
    )
    too_small = adjudicate_conclusion_contract(
        conclusion=conclusion, analysis=analysis, hypothesis=hypothesis,
        effect=-2.5, uncertainty={"lower": -4.0, "upper": -0.1, "level": 0.95},
    )
    assert too_small["criteria"]["registered_interval_supports_expected_direction"] is True
    assert too_small["criteria"]["practical_significance_satisfied"] is False
    assert too_small["adjudicated_evidence_direction"] == "inconclusive"
    supported = adjudicate_conclusion_contract(
        conclusion=conclusion, analysis=analysis, hypothesis=hypothesis,
        effect=-2.5, uncertainty={"lower": -3.0, "upper": -2.1, "level": 0.95},
    )
    assert supported["adjudicated_evidence_direction"] == "supports"


def test_holm_execution_binds_frozen_workflow_family_and_registered_input(tmp_path, capsys) -> None:
    from research_machine.addons.execution import execute_analysis, _implementation_hash
    from research_machine.addons.general_science import (
        holm_adjustment, independent_mean_difference_ci,
        permutation_mean_difference,
    )
    from research_machine.addons.registry import default_registry
    from research_machine.addons.receipt import verify_execution_output
    from research_machine.addons.workflow import adjudicate_holm_workflow, materialize_holm_family
    from research_machine.application.commands import RegisterDataset
    from research_machine.domain.models import DatasetArtifact, DatasetRole
    from research_machine.interfaces.cli import main

    workspace = tmp_path / "workspace"
    service, hypothesis_id = prepared_service(workspace)
    holm_spec = {
        "method": "holm_adjustment", "hypothesis_column": "member_id",
        "p_value_column": "p_value", "family_name": "confirmatory-family",
        "family_hypothesis_ids": ["primary-test-p", "secondary-test-p"],
        "alpha": 0.05, "claim_ceiling": "Adjusted values only.",
    }
    holm_spec_bytes = json.dumps(holm_spec).encode()
    _, holm_hash = _implementation_hash(holm_adjustment)
    _, estimate_hash = _implementation_hash(independent_mean_difference_ci)
    _, permutation_hash = _implementation_hash(permutation_mean_difference)
    estimate_spec = {
        "method": "independent_mean_difference_ci", "study_design": "independent_groups",
        "outcome_column": "outcome", "group_column": "group", "groups": ["a", "b"],
        "unit_column": "unit", "bootstrap_resamples": 1000, "seed": 5,
        "missing_data_policy": "complete_case",
        "estimand": "Mean outcome difference, group a minus group b.",
        "contrast_definition": "group a minus group b",
        "claim_ceiling": "Registered estimate only.",
    }
    estimate_spec_bytes = json.dumps(estimate_spec).encode()
    source_specs = {
        "primary-test": {
            "method": "permutation_mean_difference", "study_design": "independent_groups",
            "outcome_column": "outcome", "group_column": "group", "groups": ["a", "b"],
            "unit_column": "unit", "permutations": 1000, "seed": 7,
            "missing_data_policy": "complete_case", "claim_ceiling": "Registered test only.",
        },
        "secondary-test": {
            "method": "permutation_mean_difference", "study_design": "independent_groups",
            "outcome_column": "secondary", "group_column": "group", "groups": ["a", "b"],
            "unit_column": "unit", "permutations": 1000, "seed": 11,
            "missing_data_policy": "complete_case", "claim_ceiling": "Registered test only.",
        },
    }
    source_spec_bytes = {
        step_id: json.dumps(value).encode() for step_id, value in source_specs.items()
    }
    template = _multi_step_protocol()
    contract = replace(
        template.analysis_contract,
        primary_hypothesis_id=hypothesis_id,
        minimum_analyzable_units=2,
    )
    steps = []
    for step in template.analysis_steps:
        members = [replace(item, hypothesis_id=hypothesis_id) for item in step.family_members]
        steps.append(replace(
            step,
            hypothesis_id=hypothesis_id if step.hypothesis_id else "",
            specification_sha256=(
                hashlib.sha256(holm_spec_bytes).hexdigest() if step.role == "multiplicity"
                else hashlib.sha256(source_spec_bytes[step.step_id]).hexdigest()
                if step.role == "confirmatory_test" else step.specification_sha256
            ),
            implementation_sha256=(
                holm_hash if step.role == "multiplicity"
                else permutation_hash if step.role == "confirmatory_test"
                else step.implementation_sha256
            ),
            family_members=members,
        ))
    values = {field.name: getattr(template, field.name) for field in fields(CreateProtocol)}
    draft = service.create_protocol(CreateProtocol(**{
        **values, "hypotheses_tested": [hypothesis_id], "analysis_contract": contract,
        "conclusion_contract": replace(
            template.conclusion_contract, primary_hypothesis_id=hypothesis_id,
        ),
        "analysis_code_hash": estimate_hash,
        "analysis_specification_sha256": hashlib.sha256(estimate_spec_bytes).hexdigest(),
        "sample_size_plan": {
            "strategy": "precision",
            "target_hypothesis_id": hypothesis_id,
            "target_measurement_id": "primary-measurement",
            "measurement_unit": "fixture units",
            "specification": {
                "study_design": "independent_groups",
                "target_half_width": 100.0,
                "assumed_standard_deviation": 1.0,
                "confidence_level": 0.95,
                "anticipated_attrition_fraction": 0.0,
            },
            "justification": "Bind the fixture's minimum analyzable unit check.",
        },
        "analysis_steps": [
            replace(
                step,
                specification_sha256=hashlib.sha256(estimate_spec_bytes).hexdigest(),
                implementation_sha256=estimate_hash,
            ) if step.role == "primary_estimate" else step
            for step in steps
        ],
    }))
    frozen = service.freeze_protocol(draft.protocol_id)
    observations = tmp_path / "observations.csv"
    observations.write_text(
        "unit,group,outcome,secondary\n"
        "u1,a,1,5\nu2,a,2,6\nu3,a,3,7\nu4,b,8,10\nu5,b,9,11\nu6,b,10,12\n"
    )
    observation_dataset = service.register_dataset(RegisterDataset(
        name="Frozen confirmatory observations", role=DatasetRole.CONFIRMATORY,
        protocol_id=frozen.protocol_id, synthetic=False,
        artifacts=[DatasetArtifact(
            "observations.csv", hashlib.sha256(observations.read_bytes()).hexdigest(),
            len(observations.read_bytes()), "text/csv",
        )],
        artifact_root=str(tmp_path),
    ))
    def record_completed_component(
        draft, execution, output_directory, summary,
        evidence_location="/result/exclusion_report",
        control_matches_expected=True,
    ):
        record = json.loads(json.dumps(draft["record"]))
        result_sha256 = execution["receipt"]["output"]["sha256"]
        for gate in record["quality_gates"]:
            gate["status"] = "passed"
            gate["summary"] = summary
            gate["details"]["evidence_sha256"] = result_sha256
            if gate["gate_id"] == "integrity":
                gate["details"]["control_results"]["reference-1"] = {
                    "observed_behavior": "The registered reference was inspected in the committed result.",
                    "interpretation": "Structural fixture control check.",
                    "matches_expected": control_matches_expected,
                    "evidence_sha256": result_sha256,
                    "evidence_location": evidence_location,
                }
            if gate["gate_id"] == "missingness-assessed":
                gate["details"]["missingness_assessment_result"] = {
                    "observed_diagnostic": "No rows were excluded in the fixture.",
                    "interpretation": "The registered diagnostic did not trigger its failure response.",
                    "assessment_kind": "empirical_diagnostic",
                    "assessment_status": "consistent_with_assumption",
                    "evidence_sha256": result_sha256,
                    "evidence_location": evidence_location,
                }
        record["environment_hash"] = "8" * 64
        record["summary"] = summary
        path = tmp_path / f"{Path(output_directory).name}-completed-run.json"
        path.write_text(json.dumps(record))
        assert main([
            "--workspace", str(workspace), "--json", "run", "record",
            "--record-file", str(path), "--artifact-root", str(output_directory),
        ]) == 0
        return json.loads(capsys.readouterr().out)["result"]
    estimate_spec_path = tmp_path / "primary-estimate.json"
    estimate_spec_path.write_bytes(estimate_spec_bytes)
    estimate_output = tmp_path / "primary-estimate-output"
    execute_analysis(
        registry=default_registry(), spec_path=estimate_spec_path,
        data_path=observations, output_dir=estimate_output,
        design_check=lambda specification, structure, implementation, specification_hash, input_hash, input_size, ceiling: service.validate_analysis_execution(
            frozen.protocol_id, specification, structure, implementation,
            specification_hash, observation_dataset.dataset_id, input_hash,
            input_size, ceiling,
        ),
    )
    estimate_receipt_hash = hashlib.sha256(
        (estimate_output / "execution-receipt.json").read_bytes()
    ).hexdigest()
    assert main([
        "--workspace", str(workspace), "--json", "analysis", "run-draft",
        "--execution-directory", str(estimate_output),
        "--expected-receipt-sha256", estimate_receipt_hash,
    ]) == 0
    estimate_draft = json.loads(capsys.readouterr().out)["result"]
    assert estimate_draft["workflow_component_only"] is True
    completed_estimate = record_completed_component(
        estimate_draft, verify_execution_output(estimate_output, estimate_receipt_hash),
        estimate_output, "Primary estimate component passed its registered fixture gates.",
    )
    completed_estimate_ref = {
        "step_id": "primary-estimate", "run_id": completed_estimate["run_id"],
        "execution_directory": str(estimate_output), "receipt_sha256": estimate_receipt_hash,
    }
    completed_test_refs = []
    source_manifest = {"family_step_id": "confirmatory-holm", "sources": []}
    for step_id, source_spec in source_specs.items():
        source_spec_path = tmp_path / f"{step_id}.json"
        source_spec_path.write_bytes(source_spec_bytes[step_id])
        source_output = tmp_path / f"{step_id}-output"
        source_execution = execute_analysis(
            registry=default_registry(), spec_path=source_spec_path,
            data_path=observations, output_dir=source_output,
            design_check=lambda specification, structure, implementation, specification_hash, input_hash, input_size, ceiling: service.validate_analysis_execution(
                frozen.protocol_id, specification, structure, implementation,
                specification_hash, observation_dataset.dataset_id, input_hash,
                input_size, ceiling,
            ),
        )
        selection = source_execution["receipt"]["registered_workflow_selection"]
        assert selection["step_id"] == step_id
        assert 0 <= selection["p_value"] <= 1
        receipt_hash = hashlib.sha256(
            (source_output / "execution-receipt.json").read_bytes()
        ).hexdigest()
        assert verify_execution_output(source_output, receipt_hash)["receipt_sha256"] == receipt_hash
        assert main([
            "--workspace", str(workspace), "--json", "analysis", "run-draft",
            "--execution-directory", str(source_output),
            "--expected-receipt-sha256", receipt_hash,
        ]) == 0
        source_draft = json.loads(capsys.readouterr().out)["result"]
        if step_id == "primary-test":
            assert source_draft["workflow_component_only"] is True
            assert source_draft["record"]["analysis_code_hash"] == permutation_hash
            source_draft["record"]["environment_hash"] = "8" * 64
            source_draft["record"]["summary"] = "Synthetic workflow component retained with unevaluated gates."
            source_record_path = tmp_path / "source-run.json"
            unbound_record = json.loads(json.dumps(source_draft["record"]))
            unbound_record["metadata"] = {}
            unbound_path = tmp_path / "unbound-source-run.json"
            unbound_path.write_text(json.dumps(unbound_record))
            assert main([
                "--workspace", str(workspace), "--json", "run", "record",
                "--record-file", str(unbound_path),
                "--artifact-root", str(source_output),
            ]) == 2
            assert "require a verified execution_handoff" in capsys.readouterr().err
            source_record_path.write_text(json.dumps(source_draft["record"]))
            assert main([
                "--workspace", str(workspace), "--json", "run", "record",
                "--record-file", str(source_record_path),
                "--artifact-root", str(source_output),
            ]) == 0
            recorded_source = json.loads(capsys.readouterr().out)["result"]
            assert recorded_source["status"] == "invalid"
            assert recorded_source["scientific_evidence_eligible"] is False
            assert recorded_source["metadata"]["workflow_component_only"] is True
            # Simulate a real-data component with every gate satisfied to prove
            # component-only ineligibility is independent of invalid/synthetic flags.
            completed_record = json.loads(json.dumps(source_draft["record"]))
            result_sha256 = source_execution["receipt"]["output"]["sha256"]
            for gate in completed_record["quality_gates"]:
                gate["status"] = "passed"
                gate["summary"] = "Synthetic fixture supplies a structurally passing observed check."
                gate["details"]["evidence_sha256"] = result_sha256
                if gate["gate_id"] == "integrity":
                    gate["details"]["control_results"]["reference-1"] = {
                        "observed_behavior": "The registered reference was represented in the fixture output.",
                        "interpretation": "Fixture-only structural control check.",
                        "matches_expected": True,
                        "evidence_sha256": result_sha256,
                        "evidence_location": "/result/two_sided_permutation_p",
                    }
                if gate["gate_id"] == "missingness-assessed":
                    gate["details"]["missingness_assessment_result"] = {
                        "observed_diagnostic": "No rows were excluded in the fixture.",
                        "interpretation": "The registered diagnostic did not trigger its failure response.",
                        "assessment_kind": "empirical_diagnostic",
                        "assessment_status": "consistent_with_assumption",
                        "evidence_sha256": result_sha256,
                        "evidence_location": "/result/exclusion_report",
                    }
            completed_path = tmp_path / "completed-source-run.json"
            completed_path.write_text(json.dumps(completed_record))
            assert main([
                "--workspace", str(workspace), "--json", "run", "record",
                "--record-file", str(completed_path),
                "--artifact-root", str(source_output),
            ]) == 0
            completed_source = json.loads(capsys.readouterr().out)["result"]
            assert completed_source["status"] == "completed"
            assert completed_source["synthetic"] is False
            assert completed_source["scientific_evidence_eligible"] is False
            assert completed_source["metadata"]["workflow_component_only"] is True
        else:
            completed_source = record_completed_component(
                source_draft, source_execution, source_output,
                "Confirmatory test component passed its registered fixture gates.",
            )
        completed_test_refs.append({
            "step_id": step_id, "run_id": completed_source["run_id"],
            "execution_directory": str(source_output), "receipt_sha256": receipt_hash,
        })
        source_manifest["sources"].append({
            "source_step_id": step_id,
            "execution_directory": str(source_output),
            "receipt_sha256": receipt_hash,
        })
    manifest_path = tmp_path / "dependencies.json"
    manifest_bytes = json.dumps(source_manifest).encode()
    manifest_path.write_bytes(manifest_bytes)
    assert main([
        "--workspace", str(workspace), "--json", "analysis", "materialize-holm",
        "--protocol", frozen.protocol_id, "--manifest-file", str(manifest_path),
        "--expected-manifest-sha256", hashlib.sha256(manifest_bytes).hexdigest(),
        "--output", str(tmp_path / "materialized-family"),
    ]) == 0
    materialized = json.loads(capsys.readouterr().out)["result"]
    materialization_receipt_hash = hashlib.sha256(
        (tmp_path / "materialized-family" / "family-materialization.json").read_bytes()
    ).hexdigest()
    incomplete_manifest = {
        "family_step_id": "confirmatory-holm",
        "sources": source_manifest["sources"][:-1],
    }
    incomplete_path = tmp_path / "incomplete-dependencies.json"
    incomplete_bytes = json.dumps(incomplete_manifest).encode()
    incomplete_path.write_bytes(incomplete_bytes)
    with pytest.raises(ValidationError, match="exactly cover"):
        materialize_holm_family(
            service, frozen.protocol_id, incomplete_path,
            hashlib.sha256(incomplete_bytes).hexdigest(), tmp_path / "incomplete-family",
        )
    padded_manifest = {
        "family_step_id": " confirmatory-holm ",
        "sources": source_manifest["sources"],
    }
    padded_path = tmp_path / "padded-dependencies.json"
    padded_bytes = json.dumps(padded_manifest).encode()
    padded_path.write_bytes(padded_bytes)
    with pytest.raises(ValidationError, match="canonical non-blank"):
        materialize_holm_family(
            service, frozen.protocol_id, padded_path,
            hashlib.sha256(padded_bytes).hexdigest(), tmp_path / "padded-family",
        )
    padded_source_manifest = {
        "family_step_id": "confirmatory-holm",
        "sources": [{**source_manifest["sources"][0], "source_step_id": " primary-test "},
                    *source_manifest["sources"][1:]],
    }
    padded_source_path = tmp_path / "padded-source-dependencies.json"
    padded_source_bytes = json.dumps(padded_source_manifest).encode()
    padded_source_path.write_bytes(padded_source_bytes)
    with pytest.raises(ValidationError, match="canonical non-blank"):
        materialize_holm_family(
            service, frozen.protocol_id, padded_source_path,
            hashlib.sha256(padded_source_bytes).hexdigest(), tmp_path / "padded-source-family",
        )
    source_result = Path(source_manifest["sources"][0]["execution_directory"]) / "analysis-result.json"
    original_source_result = source_result.read_bytes()
    source_result.write_text("{}")
    with pytest.raises(ValidationError, match="result does not match receipt"):
        materialize_holm_family(
            service, frozen.protocol_id, manifest_path,
            hashlib.sha256(manifest_bytes).hexdigest(), tmp_path / "tampered-family",
        )
    source_result.write_bytes(original_source_result)
    data = tmp_path / "materialized-family" / "holm-family.csv"
    assert data.read_text().splitlines()[1].startswith("primary-test-p,")
    assert materialized["materialization"]["output"]["row_count"] == 2
    dataset = service.register_dataset(RegisterDataset(
        name="Verified confirmatory p-value family", role=DatasetRole.CONFIRMATORY,
        protocol_id=frozen.protocol_id, synthetic=True,
        artifacts=[DatasetArtifact(
            "holm-family.csv", hashlib.sha256(data.read_bytes()).hexdigest(),
            len(data.read_bytes()), "text/csv",
        )],
    ))
    spec_path = tmp_path / "holm.json"
    spec_path.write_bytes(holm_spec_bytes)
    execution = execute_analysis(
        registry=default_registry(), spec_path=spec_path, data_path=data,
        output_dir=tmp_path / "holm-output",
        design_check=lambda specification, structure, implementation, specification_hash, input_hash, input_size, ceiling: service.validate_analysis_execution(
            frozen.protocol_id, specification, structure, implementation,
            specification_hash, dataset.dataset_id, input_hash, input_size, ceiling,
        ),
    )
    check = execution["receipt"]["protocol_design_check"]
    assert check["status"] == "passed"
    assert check["analysis_step_contract"]["family_id"] == "confirmatory-family"
    assert check["input_sha256"] == dataset.artifacts[0].sha256
    assert check["dependency_status"] == "declared_not_execution_verified"
    assert execution["receipt"]["measurement_value_check"] is None
    holm_receipt_hash = hashlib.sha256(
        (tmp_path / "holm-output" / "execution-receipt.json").read_bytes()
    ).hexdigest()
    assert verify_execution_output(tmp_path / "holm-output", holm_receipt_hash)["receipt_sha256"] == holm_receipt_hash
    assert main([
        "--workspace", str(workspace), "--json", "analysis", "run-draft",
        "--execution-directory", str(tmp_path / "holm-output"),
        "--expected-receipt-sha256", holm_receipt_hash,
    ]) == 0
    holm_draft = json.loads(capsys.readouterr().out)["result"]
    assert holm_draft["workflow_component_only"] is True
    assert holm_draft["record"]["analysis_code_hash"] == holm_hash
    completed_holm = record_completed_component(
        holm_draft, execution, tmp_path / "holm-output",
        "Multiplicity component passed its registered fixture gates.",
        "/result/results",
    )
    adjudication_manifest = {
        "primary_estimate": completed_estimate_ref,
        "confirmatory_tests": completed_test_refs,
        "materialization": {
            "directory": str(tmp_path / "materialized-family"),
            "receipt_sha256": materialization_receipt_hash,
        },
        "multiplicity": {
            "step_id": "confirmatory-holm", "run_id": completed_holm["run_id"],
            "execution_directory": str(tmp_path / "holm-output"),
            "receipt_sha256": holm_receipt_hash,
        },
    }
    padded_adjudication_manifest = {
        **adjudication_manifest,
        "confirmatory_tests": [{**completed_test_refs[0], "step_id": " primary-test "},
                               *completed_test_refs[1:]],
    }
    padded_adjudication_path = tmp_path / "padded-workflow-adjudication-manifest.json"
    padded_adjudication_bytes = json.dumps(padded_adjudication_manifest).encode()
    padded_adjudication_path.write_bytes(padded_adjudication_bytes)
    with pytest.raises(ValidationError, match="canonical non-blank"):
        adjudicate_holm_workflow(
            service, frozen.protocol_id, padded_adjudication_path,
            hashlib.sha256(padded_adjudication_bytes).hexdigest(), tmp_path / "padded-adjudication",
        )
    adjudication_manifest_path = tmp_path / "workflow-adjudication-manifest.json"
    adjudication_manifest_bytes = json.dumps(adjudication_manifest).encode()
    adjudication_manifest_path.write_bytes(adjudication_manifest_bytes)
    assert main([
        "--workspace", str(workspace), "--json", "analysis", "adjudicate-holm",
        "--protocol", frozen.protocol_id,
        "--manifest-file", str(adjudication_manifest_path),
        "--expected-manifest-sha256", hashlib.sha256(adjudication_manifest_bytes).hexdigest(),
        "--output", str(tmp_path / "workflow-adjudication"),
    ]) == 0
    adjudicated = json.loads(capsys.readouterr().out)["result"]
    assert adjudicated["adjudication"]["status"] == "passed"
    assert adjudicated["adjudication"]["scientific_evidence_eligible"] is False
    assert adjudicated["adjudication"]["canonical_status"] == "reviewed_composite_run_required"
    assert len(adjudicated["adjudication"]["confirmatory_family"]["decisions"]) == 2
    assert adjudicated["adjudication"]["primary_estimate"]["effect_estimate"] == -7.0
    assert adjudicated["adjudication"]["conclusion"]["adjudicated_evidence_direction"] == "inconclusive"
    assert adjudicated["adjudication"]["conclusion"]["criteria"] == {
        "adjusted_primary_rejects": False,
        "registered_interval_supports_expected_direction": True,
        "smallest_effect_size_of_interest": 1.0,
        "practical_significance_satisfied": True,
        "practical_significance_requires_confidence_bound": True,
    }
    adjudication_receipt_hash = hashlib.sha256(
        (tmp_path / "workflow-adjudication" / "workflow-adjudication-receipt.json").read_bytes()
    ).hexdigest()
    assert main([
        "--workspace", str(workspace), "--json", "analysis", "adjudication-run-draft",
        "--adjudication-directory", str(tmp_path / "workflow-adjudication"),
        "--expected-receipt-sha256", adjudication_receipt_hash,
    ]) == 0
    composite_draft = json.loads(capsys.readouterr().out)["result"]
    assert composite_draft["composite_workflow"] is True
    assert "workflow_adjudication_handoff" in composite_draft["record"]["metadata"]
    unbound_composite = json.loads(json.dumps(composite_draft["record"]))
    unbound_composite["metadata"] = {}
    unbound_composite_path = tmp_path / "unbound-composite-run.json"
    unbound_composite_path.write_text(json.dumps(unbound_composite))
    assert main([
        "--workspace", str(workspace), "--json", "run", "record",
        "--record-file", str(unbound_composite_path),
        "--artifact-root", str(tmp_path / "workflow-adjudication"),
    ]) == 2
    assert "verified execution_handoff" in capsys.readouterr().err
    assert all(
        gate["status"] == "passed" for gate in composite_draft["record"]["quality_gates"]
    )
    tampered_composite = json.loads(json.dumps(composite_draft["record"]))
    tampered_composite["quality_gates"][0]["summary"] = "Rewritten after adjudication."
    tampered_composite["environment_hash"] = "8" * 64
    tampered_composite["summary"] = "Tampered inherited gate fixture."
    tampered_composite_path = tmp_path / "tampered-composite-run.json"
    tampered_composite_path.write_text(json.dumps(tampered_composite))
    assert main([
        "--workspace", str(workspace), "--json", "run", "record",
        "--record-file", str(tampered_composite_path),
        "--artifact-root", str(tmp_path / "workflow-adjudication"),
    ]) == 2
    assert "exactly equal the inherited" in capsys.readouterr().err
    composite_record = json.loads(json.dumps(composite_draft["record"]))
    composite_record["environment_hash"] = "8" * 64
    composite_record["summary"] = "Composite workflow retained the exact inherited gate adjudication."
    composite_record_path = tmp_path / "completed-composite-run.json"
    composite_record_path.write_text(json.dumps(composite_record))
    assert main([
        "--workspace", str(workspace), "--json", "run", "record",
        "--record-file", str(composite_record_path),
        "--artifact-root", str(tmp_path / "workflow-adjudication"),
    ]) == 0
    completed_composite = json.loads(capsys.readouterr().out)["result"]
    assert completed_composite["status"] == "completed"
    assert completed_composite["scientific_evidence_eligible"] is True
    assert completed_composite["metadata"]["sample_size_plan_check"]["status"] == "passed"
    assert completed_composite["metadata"]["sample_size_plan_check"][
        "observed_minimum_analyzable_units_per_group"
    ] == 3
    assert completed_composite["metadata"]["sample_size_plan_check"][
        "observed_excluded_fraction"
    ] == 0.0
    assert completed_composite["metadata"]["sample_size_plan_check"][
        "registered_maximum_excluded_fraction"
    ] == 0.25
    assert completed_composite["metadata"]["sample_size_plan_check"][
        "precision_achievement"
    ]["status"] == "met"
    assert completed_composite["metadata"]["sample_size_plan_check"][
        "attrition_achievement"
    ]["status"] == "within_assumption"
    assert completed_composite["metadata"]["sample_size_plan_check"][
        "variance_assumption"
    ]["status"] == "observed_no_preregistered_tolerance"
    assert completed_composite["metadata"].get("workflow_component_only") is None
    synthesis = service.build_synthesis()["content"]
    assert "### Planning outcome accountability" in synthesis
    assert "Precision target: met; target half-width 100.0 fixture units" in synthesis
    assert "Variability assumption: observed_no_preregistered_tolerance" in synthesis
    assert "No adequacy threshold was inferred after observing the data." in synthesis
    assert "A missed target does not erase the result or imply invalidity." in synthesis
    from research_machine.application.commands import AddClaim, RecordEvidence, ReviewClaim
    from research_machine.domain.models import (
        ClaimDisposition, ClaimEpistemicLayer, EvidenceDirection, ValidationTag,
    )
    conclusion_scope = (
        "Population: Eligible fixture units represented by the sampling plan.; "
        "Setting: The registered synthetic test setting.; "
        "Time window: The registered endpoint only."
    )
    target_claim = service.add_claim(AddClaim(
        statement="The registered groups differ on the primary endpoint in the scoped fixture population.",
        level=ClaimLevel.STATISTICAL_ASSOCIATION,
        scope=conclusion_scope,
    ))
    evidence_values = {
        "hypothesis_id": hypothesis_id,
        "direction": EvidenceDirection.INCONCLUSIVE,
        "summary": "The frozen family did not reject the primary null in this fixture.",
        "analysis_id": "",
        "dataset_id": observation_dataset.dataset_id,
        "run_id": completed_composite["run_id"],
        "claim_id": target_claim.claim_id,
        "effect_estimate": "",
        "uncertainty": "",
        "scope": conclusion_scope,
        "controls_passed": [frozen.controls[0]],
        "controls_failed": [],
        "higher_level_conclusions_unsupported": list(
            frozen.conclusion_contract.higher_level_conclusions_unsupported
        ),
        "validation_tags": [ValidationTag.EMPIRICAL_TEST],
        "exploratory": False,
        "analysis_output_sha256": adjudicated["receipt"]["output"]["sha256"],
        "effect_estimate_path": "/primary_estimate/effect_estimate",
        "uncertainty_path": "/primary_estimate/uncertainty",
    }
    with pytest.raises(ValidationError, match="adjusted primary decision"):
        service.record_evidence(RecordEvidence(**{
            **evidence_values, "direction": EvidenceDirection.SUPPORTS,
        }))
    with pytest.raises(ValidationError, match="exact claim"):
        service.record_evidence(RecordEvidence(**{
            **evidence_values, "claim_id": None,
        }))
    composite_evidence = service.record_evidence(RecordEvidence(**evidence_values))
    assert composite_evidence.scientific_evidence_eligible is True
    assert composite_evidence.effect_estimate == "-7.0"
    assert "multiplicity_adjusted_primary_decision_checked" in composite_evidence.result_direction_check
    from research_machine.replication.package import verify_replication_package
    package = tmp_path / "composite-replication-package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])
    runs_path = package / "runs.json"
    manifest_path = package / "package-manifest.json"
    packaged_runs = json.loads(runs_path.read_text())
    packaged_composite = next(
        run for run in packaged_runs
        if run["run_id"] == completed_composite["run_id"]
    )
    assert "workflow_adjudication_handoff" in packaged_composite["metadata"]
    control_gate = next(
        gate for gate in packaged_composite["quality_gates"]
        if isinstance(gate["details"].get("control_results"), dict)
    )
    control_result = next(iter(control_gate["details"]["control_results"].values()))
    for mutate_handoff, message in (
        (
            lambda handoff: handoff["adjudication"].__setitem__(
                "scientific_evidence_eligible", True
            ),
            "adjudication authority boundary is invalid",
        ),
        (
            lambda handoff: handoff["adjudication"].__setitem__(
                "canonical_status", "scientific_evidence_ready"
            ),
            "adjudication authority boundary is invalid",
        ),
        (
            lambda handoff: handoff["adjudication"].__setitem__(
                "claim_ceiling", "Composite confirms the hypothesis."
            ),
            "adjudication authority boundary is invalid",
        ),
        (
            lambda handoff: handoff["receipt"].__setitem__(
                "scientific_evidence_eligible", True
            ),
            "receipt semantics are invalid",
        ),
        (
            lambda handoff: handoff["adjudication"].__setitem__(
                "protocol_id", "other-protocol"
            ),
            "adjudication authority boundary is invalid",
        ),
        (
            lambda handoff: handoff["adjudication"].__setitem__(
                "observation_dataset_id", "other-dataset"
            ),
            "adjudication authority boundary is invalid",
        ),
        (
            lambda handoff: handoff["receipt"]["output"].__setitem__(
                "locator", "renamed-adjudication.json"
            ),
            "output is invalid",
        ),
        (
            lambda handoff: handoff["receipt"]["output"].__setitem__(
                "size_bytes", handoff["receipt"]["output"]["size_bytes"] + 1
            ),
            "not a declared run artifact",
        ),
        (
            lambda handoff: handoff["receipt"]["output"].__setitem__(
                "size_bytes", True
            ),
            "output is invalid",
        ),
        (
            lambda handoff: handoff["adjudication"]["primary_estimate"].__setitem__(
                "effect_estimate", 999
            ),
            "workflow_adjudication_handoff body does not match",
        ),
    ):
        tampered_runs = json.loads(json.dumps(packaged_runs))
        tampered_composite = next(
            run for run in tampered_runs
            if run["run_id"] == completed_composite["run_id"]
        )
        mutate_handoff(
            tampered_composite["metadata"]["workflow_adjudication_handoff"]
        )
        runs_path.write_text(
            json.dumps(tampered_runs, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["runs.json"] = hashlib.sha256(
            runs_path.read_bytes()
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tampered_commitment = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        with pytest.raises(ValidationError, match=message):
            verify_replication_package(package, tampered_commitment)
    for bad_location, message in (
        ("quality_gate_adjudication/0", "absolute JSON Pointer"),
        ("/quality_gate_adjudication/missing", "does not resolve"),
    ):
        tampered_runs = json.loads(json.dumps(packaged_runs))
        tampered_composite = next(
            run for run in tampered_runs
            if run["run_id"] == completed_composite["run_id"]
        )
        tampered_gate = next(
            gate for gate in tampered_composite["quality_gates"]
            if isinstance(gate["details"].get("control_results"), dict)
        )
        next(iter(tampered_gate["details"]["control_results"].values()))[
            "evidence_location"
        ] = bad_location
        runs_path.write_text(
            json.dumps(tampered_runs, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["runs.json"] = hashlib.sha256(
            runs_path.read_bytes()
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tampered_commitment = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        with pytest.raises(ValidationError, match=message):
            verify_replication_package(package, tampered_commitment)
    assert control_result["evidence_location"].startswith("/quality_gate_adjudication/")
    service.review_claim(ReviewClaim(
        claim_id=target_claim.claim_id,
        epistemic_layer=ClaimEpistemicLayer.REASONABLE_INFERENCE,
        disposition=ClaimDisposition.ACCEPTED,
        confidence=0.7,
        decision_owner="workflow-reviewer",
    ))
    service.show_inquiry()
    claims_path = workspace / "inquiries" / "formal" / "claims.json"
    reviewed_claims = claims_path.read_bytes()
    forged_claims = json.loads(reviewed_claims)
    for claim in forged_claims:
        if claim["claim_id"] == target_claim.claim_id:
            claim["scope"] = "A broader population inserted after evidence admission."
    claims_path.write_text(json.dumps(forged_claims), encoding="utf-8")
    with pytest.raises(ValidationError, match="claim .* scientific content"):
        service.show_inquiry()
    claims_path.write_bytes(reviewed_claims)
    original_observations = observations.read_bytes()
    observations.write_text("tampered after the run\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="HASH_MISMATCH"):
        service.record_evidence(RecordEvidence(**evidence_values))
    observations.write_bytes(original_observations)
    incomplete_adjudication = json.loads(json.dumps(adjudication_manifest))
    incomplete_adjudication["confirmatory_tests"] = incomplete_adjudication["confirmatory_tests"][:-1]
    incomplete_adjudication_path = tmp_path / "incomplete-adjudication.json"
    incomplete_adjudication_bytes = json.dumps(incomplete_adjudication).encode()
    incomplete_adjudication_path.write_bytes(incomplete_adjudication_bytes)
    with pytest.raises(ValidationError, match="exactly cover"):
        adjudicate_holm_workflow(
            service, frozen.protocol_id, incomplete_adjudication_path,
            hashlib.sha256(incomplete_adjudication_bytes).hexdigest(),
            tmp_path / "incomplete-adjudication-output",
        )
    invalid_run_adjudication = json.loads(json.dumps(adjudication_manifest))
    invalid_run_adjudication["confirmatory_tests"][0]["run_id"] = recorded_source["run_id"]
    invalid_run_path = tmp_path / "invalid-run-adjudication.json"
    invalid_run_bytes = json.dumps(invalid_run_adjudication).encode()
    invalid_run_path.write_bytes(invalid_run_bytes)
    with pytest.raises(ValidationError, match="completed canonical run"):
        adjudicate_holm_workflow(
            service, frozen.protocol_id, invalid_run_path,
            hashlib.sha256(invalid_run_bytes).hexdigest(),
            tmp_path / "invalid-run-adjudication-output",
        )
    disagreeing_source = record_completed_component(
        source_draft, source_execution, source_output,
        "Alternative canonical component records an unexpected control result.",
        control_matches_expected=False,
    )
    disagreeing_adjudication = json.loads(json.dumps(adjudication_manifest))
    disagreeing_adjudication["confirmatory_tests"][-1]["run_id"] = disagreeing_source["run_id"]
    disagreeing_path = tmp_path / "disagreeing-gates-adjudication.json"
    disagreeing_bytes = json.dumps(disagreeing_adjudication).encode()
    disagreeing_path.write_bytes(disagreeing_bytes)
    with pytest.raises(ValidationError, match="disagree on scientific disposition"):
        adjudicate_holm_workflow(
            service, frozen.protocol_id, disagreeing_path,
            hashlib.sha256(disagreeing_bytes).hexdigest(),
            tmp_path / "disagreeing-gates-output",
        )


def test_protocol_freeze_rejects_nested_scaffold_placeholder():
    protocol = _human_protocol(human_subjects=False, controls=["[REVIEW REQUIRED] choose a control"])
    with pytest.raises(ValidationError, match=r"protocol.controls\[0\]"):
        validate_protocol_freeze(protocol)


@pytest.mark.parametrize("failure", [None, "design", "implementation", "specification", "unpinned", "input", "size", "role", "unit", "wrong_unit_column", "noncanonical_unit_column", "noncanonical_group_column", "same_group_unit_column", "noncanonical_group_value", "structural_group_unit_collision", "duplicate_unit", "allocation", "information_minimum", "differential_exclusion", "value_domain", "contract_method", "contract_outcome", "contract_group", "contract_levels", "contract_covariates", "contract_missingness", "contract_estimand", "contract_contrast", "contract_hypothesis", "contract_measurement", "measurement_column", "measurement_scale", "measurement_unit", "measurement_domain", "measurement_bounds", "contract_selector", "duplicate_selectors", "missing_result_selector"])
@pytest.mark.parametrize("kind", [ProtocolKind.OBSERVATIONAL, ProtocolKind.EXPERIMENTAL])
def test_cli_checks_actual_execution_against_frozen_design(tmp_path, capsys, failure, kind):
    from research_machine.addons.execution import _implementation_hash
    from research_machine.addons.general_science import independent_mean_difference_ci
    from research_machine.interfaces.cli import main
    from research_machine.application.commands import RegisterDataset
    from research_machine.domain.models import DatasetArtifact, DatasetRole

    service, hypothesis = prepared_service(tmp_path / "workspace")
    base = _human_protocol(
        human_subjects=False, protocol_kind=kind, hypotheses_tested=[hypothesis],
        title="Synthetic empirical pipeline fixture", experiment_id="synthetic-pipeline",
        sampling_unit="pot", independent_unit="pot",
        methodology="Synthetic fixture testing empirical protocol gates; not a scientific study.",
    )
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    _, digest = _implementation_hash(independent_mean_difference_ci)
    specification = json.dumps({"method": "independent_mean_difference_ci",
        "study_design": "paired" if failure == "design" else "independent_groups",
        "outcome_column": "outcome",
        "group_column": " group " if failure == "noncanonical_group_column" else "unit" if failure == "same_group_unit_column" else "group",
        "groups": ["a", "b"],
        **({} if failure == "unit" else {"unit_column": "other_unit" if failure == "wrong_unit_column" else " unit " if failure == "noncanonical_unit_column" else "unit"}),
        "seed": 1, "bootstrap_resamples": 1000, "missing_data_policy": "complete_case",
        "estimand": "Mean outcome difference, group a minus group b.",
        "contrast_definition": "group a minus group b",
        "claim_ceiling": "Synthetic fixture only"})
    measurements = _analysis_measurements(base.primary_outcome, base.controls[0])
    if failure == "measurement_column":
        measurements[0] = replace(measurements[0], data_column="surrogate_outcome")
    elif failure == "measurement_scale":
        measurements[0] = replace(measurements[0], scale_type="ordinal", admissible_values=["low", "high"], valid_min=None, valid_max=None)
    elif failure == "measurement_unit":
        measurements[0] = replace(measurements[0], unit="")
    elif failure == "measurement_domain":
        measurements[0] = replace(measurements[0], missing_value_codes=["NA", "NA"])
    elif failure == "measurement_bounds":
        measurements[0] = replace(measurements[0], valid_min=10, valid_max=10)
    elif failure == "contract_outcome":
        measurements[0] = replace(measurements[0], data_column="other_outcome")
    allocation = [
        {"unit_id": "u1", "group": "a"}, {"unit_id": "u2", "group": "a"},
        {"unit_id": "u3", "group": "b"}, {"unit_id": "u4", "group": "b"},
    ]
    if failure == "differential_exclusion":
        allocation = [
            {"unit_id": "u1", "group": "a"}, {"unit_id": "u2", "group": "a"},
            {"unit_id": "u3", "group": "a"}, {"unit_id": "u4", "group": "b"},
            {"unit_id": "u5", "group": "b"}, {"unit_id": "u6", "group": "b"},
        ]
    allocation_sha256 = hashlib.sha256(json.dumps(
        allocation, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    draft = service.create_protocol(CreateProtocol(**{
        **values, "independent_unit": "pot", "repeated_measures": False,
        "analysis_design": "independent_groups", "unit_id_column": "unit",
        "analysis_code_hash": "a" * 64 if failure == "implementation" else digest,
        "analysis_specification_sha256": "" if failure == "unpinned" else hashlib.sha256(specification.encode()).hexdigest(),
        "measurement_definitions": measurements,
            "analysis_contract": AnalysisContract(
            primary_hypothesis_id="unknown-hypothesis" if failure == "contract_hypothesis" else hypothesis,
            primary_measurement_id="unknown-measurement" if failure == "contract_measurement" else "primary-measurement",
            method="paired_mean_difference_ci" if failure == "contract_method" else "independent_mean_difference_ci",
            outcome_column="other_outcome" if failure == "contract_outcome" else "outcome",
            group_column="arm" if failure == "contract_group" else "unit" if failure == "structural_group_unit_collision" else "group",
            groups=["b", "a"] if failure == "contract_levels" else ["a", "b"],
            adjustment_columns=["baseline"] if failure == "contract_covariates" else [],
            estimand="A different post-hoc estimand." if failure == "contract_estimand" else "Mean outcome difference, group a minus group b.",
            contrast_definition="group b minus group a" if failure == "contract_contrast" else "group a minus group b",
            contrast_groups=["a", "b"],
            missing_data_policy="drop_any" if failure == "contract_missingness" else "complete_case",
            assignment_type="observational" if kind is ProtocolKind.OBSERVATIONAL else "randomized_between_units",
            effect_estimate_path=("result/value" if failure == "contract_selector" else
                                  "/result/not_present" if failure == "missing_result_selector" else
                                  "/result/mean_difference_first_minus_second"),
            uncertainty_path="/result/mean_difference_first_minus_second" if failure == "duplicate_selectors" else "/result/confidence_interval",
            null_value=0.0,
            support_rule="interval_excludes_null",
            minimum_analyzable_units=3 if failure == "information_minimum" else 2,
            maximum_excluded_fraction=0.25,
            maximum_group_excluded_fraction_difference=0.25,
            missingness_assumption="Excluded records do not materially distort the registered contrast.",
            missingness_assessment_plan="Inspect total and group-specific exclusions before interpretation.",
            missingness_failure_response="Stop primary interpretation if missingness is not defensible.",
            missingness_assessment_kind="empirical_diagnostic",
            missingness_assessment_gate_id="missingness-assessed",
                allocation_sha256="" if kind is ProtocolKind.OBSERVATIONAL else allocation_sha256,
            ) if failure != "unpinned" else None,
            "conclusion_contract": (
                    None if failure in {"unpinned", "measurement_unit", "contract_measurement"} else
                ConclusionContract(
                    primary_hypothesis_id=hypothesis,
                    decision_rule="interval_and_practical_significance",
                    smallest_effect_size_of_interest=1.0,
                    effect_scale="mean difference",
                    effect_unit="fixture units",
                    population="Registered fixture units in the sampling frame.",
                    setting="The registered synthetic execution fixture.",
                    time_window="The registered endpoint only.",
                    non_supporting_direction=EvidenceDirection.INCONCLUSIVE,
                    permitted_claim_level=ClaimLevel.STATISTICAL_ASSOCIATION,
                    higher_level_conclusions_unsupported=[
                        "No causal, mechanism, or out-of-scope conclusion."
                    ],
                )
            ),
            "quality_requirements": ["integrity", "missingness-assessed"],
    }))
    if failure in {"contract_missingness", "contract_estimand", "contract_contrast", "contract_levels", "contract_hypothesis", "contract_measurement", "measurement_column", "measurement_scale", "measurement_unit", "measurement_domain", "measurement_bounds", "contract_selector", "duplicate_selectors", "structural_group_unit_collision"}:
        message = {"contract_missingness": "complete_case", "contract_estimand": "primary hypothesis estimand", "contract_contrast": "contrast_definition", "contract_levels": "contrast_groups", "contract_hypothesis": "tested hypothesis", "contract_measurement": "primary_measurement_id", "measurement_column": "data_column", "measurement_scale": "requires a binary, interval, ratio, or count", "measurement_unit": "unit must not be empty", "measurement_domain": "missing_value_codes must contain unique", "measurement_bounds": "valid_min must be strictly below valid_max", "contract_selector": "absolute JSON Pointer", "duplicate_selectors": "must be distinct", "structural_group_unit_collision": "structural columns"}[failure]
        with pytest.raises(ValidationError, match=message):
            service.freeze_protocol(draft.protocol_id)
        return
    frozen = service.freeze_protocol(draft.protocol_id)
    data = tmp_path / "synthetic.csv"
    last_unit = "u1" if failure == "duplicate_unit" else "u4"
    last_group = "a" if failure == "allocation" else "b"
    if failure == "differential_exclusion":
        data.write_text(
            "unit,group,outcome\nu1,a,1\nu2,a,2\nu3,a,\n"
            "u4,b,3\nu5,b,4\nu6,b,5\n"
        )
    else:
        final_value = 101 if failure == "value_domain" else 4
        first_group = " a " if failure == "noncanonical_group_value" else "a"
        data.write_text(f"unit,group,outcome\nu1,{first_group},1\nu2,a,2\nu3,b,3\n{last_unit},{last_group},{final_value}\n")
    dataset = service.register_dataset(RegisterDataset(
        name="Synthetic execution fixture",
        role=DatasetRole.EXPLORATORY if failure == "role" else DatasetRole.CONFIRMATORY,
        protocol_id=None if failure == "role" else frozen.protocol_id,
        synthetic=True,
        artifacts=[DatasetArtifact("synthetic.csv", hashlib.sha256(data.read_bytes()).hexdigest(),
            size_bytes=1 if failure == "size" else len(data.read_bytes()), media_type="text/csv")],
    ))
    if failure == "input":
        data.write_text("unit,group,outcome\nu1,a,100\nu2,a,2\nu3,b,3\nu4,b,4\n")
    spec = tmp_path / "spec.json"
    spec.write_text(specification.replace('"seed": 1', '"seed": 2') if failure == "specification" else specification)
    output = tmp_path / "output"
    ledger = next((tmp_path / "workspace").rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    status = main(["--workspace", str(tmp_path / "workspace"), "--json", "analysis", "run",
        "--spec-file", str(spec), "--data-file", str(data), "--output", str(output),
        "--protocol", frozen.protocol_id, "--dataset", dataset.dataset_id])
    captured = capsys.readouterr()
    if failure:
        assert status == 2
        assert captured.err
        assert not output.exists()
    else:
        assert status == 0
        execution = json.loads(captured.out)["result"]
        receipt = execution["receipt"]
        assert execution["result"]["result"]["mean_difference_first_minus_second"] == -2
        assert frozen.protocol_kind is kind
        assert receipt["protocol_design_check"]["protocol_hash"] == frozen.protocol_hash
        assert receipt["protocol_design_check"]["dataset_id"] == dataset.dataset_id
        assert receipt["protocol_design_check"]["unit_structure"]["unit_id_column"] == "unit"
        assert receipt["protocol_design_check"]["unit_structure"]["unit_count"] == 4
        assert receipt["protocol_design_check"]["unit_structure"]["repeated_unit_count"] == 0
        assert receipt["protocol_design_check"]["synthetic"] is True
        assert receipt["measurement_value_check"]["status"] == "passed"
        assert receipt["measurement_value_check"]["measurements"][0]["observed_count"] == 4
        assert len(receipt["measurement_value_check"]["measurements"][0]["value_domain_sha256"]) == 64
        assert receipt["maximum_inference_level"] == "design_conditional_effect"
        assert receipt["protocol_design_check"]["method_inference_check"] == {
            "required_inference_level": "not_causal",
            "maximum_inference_level": "design_conditional_effect",
            "status": "passed",
            "scope": "method capability combined with frozen protocol; not causal proof",
        }
        assert receipt["protocol_design_check"]["executed_analysis_semantics"] == {
            "study_design": "independent_groups",
            "method": "independent_mean_difference_ci",
            "outcome_column": "outcome", "group_column": "group",
            "groups": ["a", "b"],
            "covariate_columns": [],
            "estimand": "Mean outcome difference, group a minus group b.",
            "contrast_definition": "group a minus group b",
            "contrast_groups": ["a", "b"],
            "missing_data_policy": "complete_case",
        }
        assert receipt["scientific_evidence_eligible"] is False
        assert receipt["registered_result_selection"]["effect_estimate_path"] == "/result/mean_difference_first_minus_second"
        assert receipt["registered_result_selection"]["uncertainty_path"] == "/result/confidence_interval"
        assert receipt["registered_result_selection"]["null_value"] == 0.0
        assert receipt["registered_result_selection"]["support_rule"] == "interval_excludes_null"
        assert receipt["registered_result_selection"]["confidence_interval_validated"] is True
        assert receipt["specification"]["sha256"] == frozen.analysis_specification_sha256
        assert receipt["input"]["sha256"] == dataset.artifacts[0].sha256
        receipt_hash = hashlib.sha256((output / "execution-receipt.json").read_bytes()).hexdigest()
        assert main(["--workspace", str(tmp_path / "workspace"), "--json", "analysis", "run-draft",
                     "--execution-directory", str(output), "--expected-receipt-sha256", receipt_hash]) == 0
        handoff = json.loads(capsys.readouterr().out)["result"]
        assert handoff["template_only"] is True
        assert handoff["record"]["synthetic"] is True
        assert handoff["record"]["dataset_ids"] == [dataset.dataset_id]
        assert all(gate["status"] == "skipped" for gate in handoff["record"]["quality_gates"])
        assert handoff["record"]["environment_hash"].startswith("<")
        assert handoff["record"]["metadata"]["execution_handoff"]["result"] == execution["result"]
        record_path = tmp_path / "review-record.json"
        record_path.write_text(json.dumps(handoff["record"]))
        preflight_args = ["--workspace", str(tmp_path / "workspace"), "--json", "run", "preflight",
                          "--record-file", str(record_path), "--artifact-root", str(output)]
        assert main(preflight_args) == 2
        assert "environment_hash" in capsys.readouterr().err
        # Fixture-only environment identity is explicit; no real observation or
        # gate approval is invented to make this synthetic workflow pass.
        handoff["record"]["environment_hash"] = hashlib.sha256(b"synthetic fixture environment").hexdigest()
        handoff["record"]["summary"] = "Synthetic pipeline fixture; required gates remain unevaluated."
        record_path.write_text(json.dumps(handoff["record"]))
        assert main(preflight_args) == 1
        preflight = json.loads(capsys.readouterr().out)["result"]
        assert preflight["status"] == "would_record_invalid"
        assert preflight["scientific_evidence_eligible_if_submitted"] is False
        assert preflight["would_append_event"] is False
        # Even a freshly pinned receipt must agree with canonical commitments.
        import copy
        receipt_path = output / "execution-receipt.json"
        original_receipt_bytes = receipt_path.read_bytes()
        for section, key, value in [
            ("protocol_design_check", "protocol_hash", "0" * 64),
            ("protocol_design_check", "dataset_id", "unknown-dataset"),
            ("protocol_design_check", "synthetic", False),
            ("protocol_design_check", "executed_analysis_semantics", {}),
            ("protocol_design_check", "analysis_contract", {}),
            ("protocol_design_check", "method_inference_check", {}),
            ("implementation", "sha256", "0" * 64),
            ("specification", "sha256", "0" * 64),
            ("input", "sha256", "0" * 64),
            ("input", "size_bytes", 1),
            ("measurement_value_check", "status", "failed"),
            ("measurement_value_check", "measurements", [
                {
                    **receipt["measurement_value_check"]["measurements"][0],
                    "value_domain_sha256": "0" * 64,
                }
            ]),
            ("registered_result_selection", "effect_estimate_sha256", "0" * 64),
            ("registered_information_check", "observed_minimum_analyzable_units", 999),
        ]:
            altered = copy.deepcopy(receipt)
            altered[section][key] = value
            receipt_path.write_text(json.dumps(altered))
            altered_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            assert main(["--workspace", str(tmp_path / "workspace"), "--json", "analysis", "run-draft",
                         "--execution-directory", str(output), "--expected-receipt-sha256", altered_hash]) == 2
            assert capsys.readouterr().err
            assert ledger.read_bytes() == before
        receipt_path.write_bytes(original_receipt_bytes)
        original_handoff_metadata = copy.deepcopy(
            handoff["record"]["metadata"]["execution_handoff"]
        )
        handoff["record"]["metadata"]["execution_handoff"]["result"]["result"][
            "mean_difference_first_minus_second"
        ] = 999
        record_path.write_text(json.dumps(handoff["record"]))
        assert main(preflight_args) == 2
        assert "does not match the verified receipt" in capsys.readouterr().err
        handoff["record"]["metadata"]["execution_handoff"] = original_handoff_metadata
        record_path.write_text(json.dumps(handoff["record"]))
        assert ledger.read_bytes() == before
    assert service.verify_ledger()["valid"]
    if failure is None:
        # Preserve an invalid synthetic run rather than erase unevaluated work.
        assert main(["--workspace", str(tmp_path / "workspace"), "--json", "run", "record",
                     "--record-file", str(record_path), "--artifact-root", str(output)]) == 0
        recorded = json.loads(capsys.readouterr().out)["result"]
        assert recorded["status"] == "invalid"
        assert recorded["scientific_evidence_eligible"] is False
        assert recorded["synthetic"] is True
        from research_machine.application.commands import RecordEvidence
        from research_machine.domain.models import ValidationTag
        evidence_command = dict(
            hypothesis_id=hypothesis, direction=EvidenceDirection.INCONCLUSIVE,
            summary="Synthetic result-selection fixture.", analysis_id="",
            run_id=recorded["run_id"], scope="Synthetic fixture only.",
            controls_passed=[], controls_failed=[],
            higher_level_conclusions_unsupported=["No scientific conclusion."],
            validation_tags=[ValidationTag.INTERNAL_CONSISTENCY], exploratory=False,
            effect_estimate_path="/result/mean_difference_first_minus_second",
            uncertainty_path="/result/confidence_interval",
        )
        with pytest.raises(ValidationError, match="analysis_output_sha256"):
            service.record_evidence(RecordEvidence(**evidence_command))
        with pytest.raises(ValidationError, match="frozen analysis contract"):
            service.record_evidence(RecordEvidence(
                **{**evidence_command, "effect_estimate_path": "/result/n_pairs"},
                analysis_output_sha256=receipt["output"]["sha256"],
            ))
        with pytest.raises(ValidationError, match="not eligible"):
            service.record_evidence(RecordEvidence(
                **evidence_command,
                analysis_output_sha256=receipt["output"]["sha256"],
            ))
        package = tmp_path / "replication-package"
        exported = service.export_replication_package(frozen.protocol_id, str(package))
        from research_machine.replication.package import verify_replication_package
        verified = verify_replication_package(package, exported["package_manifest_sha256"])
        assert verified["scientific_evidence_eligible"] is False
        packaged_runs = json.loads((package / "runs.json").read_text())
        assert len(packaged_runs) == 1
        assert packaged_runs[0]["run_id"] == recorded["run_id"]
        assert packaged_runs[0]["status"] == "invalid"
        assert packaged_runs[0]["metadata"]["execution_handoff"]["result"] == execution["result"]
        audit = service.audit_rigor()
        assert any(item.code == "FAILED_OR_INELIGIBLE_RUNS_RETAINED" for item in audit.findings)
        assert audit.conclusion_ceiling != "externally replicated result"
        packaged_receipt = packaged_runs[0]["metadata"]["execution_handoff"]["receipt"]
        for section in ("input", "implementation", "specification", "output"):
            assert packaged_receipt[section]["locator"].startswith("[redacted:")
        packaged_receipt["measurement_value_check"]["measurements"][0][
            "value_domain_sha256"
        ] = "0" * 64
        runs_path = package / "runs.json"
        runs_path.write_text(
            json.dumps(packaged_runs, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["runs.json"] = hashlib.sha256(
            runs_path.read_bytes()
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tampered_commitment = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        with pytest.raises(ValidationError, match="measurement value check domain digest"):
            verify_replication_package(package, tampered_commitment)
        # Export redaction must not mutate canonical provenance.
        retained = service.get_run(recorded["run_id"]).to_dict()
        assert retained["metadata"]["execution_handoff"]["receipt"]["input"]["locator"] == receipt["input"]["locator"]
        assert service.verify_ledger()["valid"]


@pytest.mark.parametrize("kind", [ProtocolKind.OBSERVATIONAL, ProtocolKind.EXPERIMENTAL])
def test_empirical_protocol_must_declare_dependence_before_freeze(kind):
    protocol = _human_protocol(human_subjects=False, protocol_kind=kind,
                               independent_unit="", repeated_measures=None, analysis_design="")
    with pytest.raises(ValidationError, match="structured design requires"):
        validate_protocol_freeze(protocol)
    complete = replace(protocol, independent_unit="Participant", repeated_measures=False,
                       analysis_design="independent_groups")
    validate_protocol_freeze(complete)


@pytest.mark.parametrize("declaration", [
    {"independent_unit": "pot"},
    {"independent_unit": "pot", "repeated_measures": "false", "analysis_design": "paired"},
    {"independent_unit": "pot", "repeated_measures": True, "analysis_design": "independent_groups"},
    {"independent_unit": "pot", "repeated_measures": True, "analysis_design": "paired"},
])
def test_invalid_declared_structure_cannot_freeze(tmp_path, declaration):
    service, hypothesis = prepared_service(tmp_path)
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    draft = service.create_protocol(CreateProtocol(**{**values, **declaration}))
    ledger = next(tmp_path.rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    with pytest.raises(ValidationError):
        service.freeze_protocol(draft.protocol_id)
    assert ledger.read_bytes() == before
    assert service.verify_ledger()["valid"]


def test_design_declaration_roundtrips_and_is_hash_bound(tmp_path):
    service, hypothesis = prepared_service(tmp_path)
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    draft = service.create_protocol(CreateProtocol(**{
            **values, "independent_unit": "pot", "repeated_measures": True, "analysis_design": "paired",
            "unit_analysis_plan": "Pair observations by pot ID and estimate one within-pot contrast.",
            "unit_id_column": "pair",
    }))
    frozen = service.freeze_protocol(draft.protocol_id)
    restored = ExperimentProtocol.from_dict(frozen.to_dict())
    assert restored.independent_unit == "pot"
    assert restored.repeated_measures is True
    assert restored.unit_analysis_plan == "Pair observations by pot ID and estimate one within-pot contrast."
    assert restored.unit_id_column == "pair"
    assert _protocol_commitment(restored) == frozen.protocol_hash
    assert _protocol_commitment(replace(restored, repeated_measures=False)) != frozen.protocol_hash
    assert _protocol_commitment(replace(restored, unit_analysis_plan="Average every row as independent.")) != frozen.protocol_hash
    assert service.verify_ledger()["valid"]


def test_canonical_protocol_requires_clock_accuracy_for_control_windows(tmp_path):
    service, hypothesis = prepared_service(tmp_path)
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}

    with pytest.raises(ValidationError, match="clock_accuracy_requirement"):
        service.create_protocol(CreateProtocol(**{
            **values,
            "experiment_id": "temporal-window-without-clock",
            "clock_accuracy_requirement": "",
            "control_windows": ["pre-event baseline"],
        }))

    draft = service.create_protocol(CreateProtocol(**{
        **values,
        "experiment_id": "temporal-window-with-clock",
        "sensor_requirements": ["audio recorder at 48 kHz", "event marker stream"],
        "clock_accuracy_requirement": "Clock drift remains below 10 ms.",
        "control_windows": ["pre-event baseline"],
    }))
    frozen = service.freeze_protocol(draft.protocol_id)
    restored = ExperimentProtocol.from_dict(frozen.to_dict())

    assert restored.sensor_requirements == [
        "audio recorder at 48 kHz",
        "event marker stream",
    ]
    assert restored.clock_accuracy_requirement == "Clock drift remains below 10 ms."
    assert restored.control_windows == ["pre-event baseline"]
    assert _protocol_commitment(restored) == frozen.protocol_hash
    assert _protocol_commitment(
        replace(restored, clock_accuracy_requirement="Clock drift remains below 50 ms.")
    ) != frozen.protocol_hash
    assert service.verify_ledger()["valid"]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        (
            {"sensor_requirements": ["audio recorder", "Audio Recorder"]},
            "sensor_requirements",
        ),
        (
            {
                "clock_accuracy_requirement": "Clock drift remains below 10 ms.",
                "control_windows": ["pre-event baseline", "Pre-Event Baseline"],
            },
            "control_windows",
        ),
    ],
)
def test_canonical_protocol_rejects_duplicate_acquisition_labels(
    tmp_path, override, message
):
    service, hypothesis = prepared_service(tmp_path)
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}

    with pytest.raises(ValidationError, match=message):
        service.create_protocol(CreateProtocol(**{
            **values,
            "experiment_id": f"duplicate-{message.replace('_', '-')}",
            **override,
        }))


def test_protocol_design_check_rejects_internally_inconsistent_unit_receipt(tmp_path):
    service, hypothesis = prepared_service(tmp_path)
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    draft = service.create_protocol(CreateProtocol(**{
        **values, "independent_unit": "pot", "repeated_measures": False,
        "analysis_design": "independent_groups", "unit_id_column": "unit",
        "measurement_definitions": _analysis_measurements(base.primary_outcome, base.controls[0]),
        "analysis_contract": AnalysisContract(
            hypothesis, "primary-measurement", "independent_mean_difference_ci", "outcome", "group", ["a", "b"],
            "Mean outcome difference, group a minus group b.", "complete_case", "not_applicable",
            "/result/mean_difference_first_minus_second", "/result/confidence_interval",
            0.0, "interval_excludes_null",
            2, 0.25, 0.25,
            missingness_assumption="Excluded records do not materially distort the registered contrast.",
            missingness_assessment_plan="Inspect exclusions before interpretation.",
            missingness_failure_response="Stop interpretation if missingness is not defensible.",
            missingness_assessment_kind="empirical_diagnostic",
            missingness_assessment_gate_id="missingness-assessed",
            contrast_definition="group a minus group b",
            contrast_groups=["a", "b"],
        ),
        "quality_requirements": ["integrity", "missingness-assessed"],
    }))
    # No execution is needed: this directly exercises receipt revalidation invariants.
    frozen = service.freeze_protocol(draft.protocol_id)
    structure = {"unit_id_column": "unit", "row_count": 4, "unit_count": 4,
        "repeated_unit_count": 1, "minimum_observations_per_unit": 1,
        "maximum_observations_per_unit": 1, "row_to_unit_mapping_sha256": "a" * 64,
        "unit_group_allocation_sha256": "b" * 64}
    with pytest.raises(ValidationError, match="internally inconsistent"):
        service.validate_analysis_design(
            frozen.protocol_id, {
                "method": "independent_mean_difference_ci", "outcome_column": "outcome",
                "group_column": "group", "groups": ["a", "b"],
                "missing_data_policy": "complete_case", "study_design": "independent_groups",
                "estimand": "Mean outcome difference, group a minus group b.",
                "contrast_definition": "group a minus group b",
            }, structure,
            frozen.analysis_code_hash, frozen.analysis_specification_sha256,
            "missing-dataset", "b" * 64, 1, "design_conditional_effect",
        )


def test_legacy_protocol_commitment_unchanged(tmp_path):
    service, hypothesis = prepared_service(tmp_path)
    frozen = frozen_formal_protocol(service, hypothesis)
    legacy = frozen.to_dict()
    for name in (
        "independent_unit", "repeated_measures", "analysis_design",
        "unit_analysis_plan", "unit_id_column", "analysis_specification_sha256",
        "control_definitions", "calibration_acceptance_criteria",
        "analysis_contract",
        "independent_review_decision", "independent_reviewer_role",
        "independent_reviewed_at", "independent_review_scope",
        "independent_review_artifact_locator", "independent_review_artifact_sha256",
        "independent_review_conditions", "independent_review_verification",
        "vulnerable_population_plan", "data_security_plan", "incidental_findings_plan",
        "causal_claim", "causal_identification", "causal_identification_audit",
        "amendment_timing", "evidence_exposure",
        "confirmatory_outcomes", "exploratory_outcomes", "multiplicity_method",
        "multiplicity_alpha", "analysis_steps",
        "hypothesis_commitments", "sample_size_plan",
    ):
        del legacy[name]
    payload = dict(legacy)
    for name in ("status", "protocol_hash", "registration_timestamp", "external_anchor"):
        payload.pop(name, None)
    original_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert _protocol_commitment(ExperimentProtocol.from_dict(legacy)) == original_hash


def test_nested_measurement_and_analysis_links_preserve_legacy_commitment() -> None:
    protocol = _human_protocol(human_subjects=False)
    measurement = _analysis_measurements(protocol.primary_outcome, protocol.controls[0])[0]
    legacy = replace(protocol, measurement_definitions=[replace(
        measurement, data_column="", scale_type="", unit="", admissible_values=[],
        valid_min=None, valid_max=None, missing_value_codes=[],
    )])
    payload = legacy.to_dict()
    for name in (
        "data_column", "scale_type", "unit", "admissible_values", "valid_min",
        "valid_max", "missing_value_codes",
    ):
        payload["measurement_definitions"][0].pop(name)
    for name in (
        "control_definitions",
        "calibration_acceptance_criteria",
        "analysis_contract",
        "hypothesis_commitments",
        "sample_size_plan",
    ):
        if not payload.get(name):
            payload.pop(name, None)
    for name in ("unit_analysis_plan", "unit_id_column", "analysis_specification_sha256",
                 "independent_review_decision", "independent_reviewer_role", "independent_reviewed_at",
                 "independent_review_scope", "independent_review_artifact_sha256"):
        if not payload.get(name):
            payload.pop(name, None)
    if not payload.get("independent_review_conditions"):
        payload.pop("independent_review_conditions", None)
    payload.pop("independent_review_verification", None)
    for name in ("causal_claim", "causal_identification", "causal_identification_audit"):
        if not payload.get(name):
            payload.pop(name, None)
    for name in ("amendment_timing", "evidence_exposure"):
        if payload.get(name) is None:
            payload.pop(name, None)
    for name in (
        "confirmatory_outcomes", "exploratory_outcomes", "multiplicity_method",
        "multiplicity_alpha", "analysis_steps",
    ):
        if not payload.get(name):
            payload.pop(name, None)
    for name in ("status", "protocol_hash", "registration_timestamp", "external_anchor"):
        payload.pop(name, None)
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert _protocol_commitment(legacy) == expected


def test_nested_information_thresholds_preserve_pre_threshold_contract_hash() -> None:
    protocol = _human_protocol(human_subjects=False)
    contract = AnalysisContract(
        "hypothesis", "measurement", "method", "outcome", "group", ["a", "b"],
        "estimand", "complete_case", "not_applicable", "/result/effect",
        "/result/interval", 0.0, "point_direction",
    )
    legacy = replace(protocol, analysis_contract=contract)
    payload = legacy.to_dict()
    payload["analysis_contract"].pop("minimum_analyzable_units")
    payload["analysis_contract"].pop("maximum_excluded_fraction")
    payload["analysis_contract"].pop(
        "maximum_group_excluded_fraction_difference"
    )
    for field_name in (
        "missingness_assumption", "missingness_assessment_plan",
        "missingness_failure_response", "missingness_assessment_kind",
        "missingness_assessment_gate_id",
    ):
        payload["analysis_contract"].pop(field_name)
    restored = ExperimentProtocol.from_dict(payload)
    assert restored.analysis_contract.minimum_analyzable_units is None
    assert restored.analysis_contract.maximum_excluded_fraction is None
    assert (
        restored.analysis_contract.maximum_group_excluded_fraction_difference
        is None
    )
    assert restored.analysis_contract.missingness_assessment_gate_id == ""
    assert _protocol_commitment(restored) == _protocol_commitment(legacy)
