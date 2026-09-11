import hashlib
import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    CreateInquiry,
    CreateProtocol,
    ProposeHypothesis,
    RecommendNextAction,
    RecordEvidence,
    RecordRun,
    RegisterDataset,
    RetireHypothesis,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.application.policies import (
    adjudicate_conclusion_contract, validate_equivalence_design_coherence,
    validate_result_direction,
)
from research_machine.addons.execution import (
    validate_measurement_values, validate_registered_confidence_level,
    validate_registered_information,
)
from research_machine.measurement.preprocessing import assess_preprocessing_conformance
from research_machine.measurement.instrument import assess_temporal_order
from research_machine.domain.models import (
    ActionCandidate,
    AnalysisMode,
    AnalysisContract,
    CanaryTargetPlan,
    ClaimLevel,
    ConclusionContract,
    DatasetArtifact,
    DatasetRole,
    EvidenceDirection,
    Hypothesis,
    HypothesisDiscriminationTarget,
    ProtocolKind,
    QualityGateResult,
    QualityGateStatus,
    RejectionType,
    RunStatus,
    SelectionWeights,
    ValidationTag,
)


CODE_HASH = "a" * 64
ENVIRONMENT_HASH = "b" * 64
SEED_REVEAL = "registered-seed-42"
SEED_COMMITMENT = hashlib.sha256(SEED_REVEAL.encode("utf-8")).hexdigest()


def action_discrimination_target(
    hypothesis_id: str,
) -> HypothesisDiscriminationTarget:
    return HypothesisDiscriminationTarget(
        hypothesis_id=hypothesis_id,
        discriminating_observation=(
            "A separately implemented checker reaches the same registered result."
        ),
        expected_if_hypothesis=(
            "The independent checker accepts the registered derivation and rejects the invalid control."
        ),
        expected_if_alternative=(
            "The independent checker disagrees with the original implementation-dependent result."
        ),
        would_weaken_if=(
            "The independent checker fails the registered derivation or accepts the invalid control."
        ),
        competing_model_ref="No valid derivation exists in the bounded proof system.",
    )


def next_action_candidate(**overrides) -> ActionCandidate:
    action_id = str(overrides.get("action_id", "candidate"))
    values = {
        "title": action_id.replace("-", " ").title(),
        "distinguishes_hypotheses": [],
        "expected_discrimination": 0.8,
        "uncertainty_reduction": 0.7,
        "cost": 0.1,
        "burden": 0.1,
        "safety_risk": 0.0,
        "ambiguity_risk": 0.1,
        "rationale": f"Evaluate {action_id}.",
        "prerequisite_evidence_refs": [f"prerequisite-review:{action_id}"],
        "safety_review_refs": [f"safety-review:{action_id}"],
    }
    values.update(overrides)
    return ActionCandidate(**values)


def _measurement_contract(**overrides):
    contract = {
        "measurement_id": "m1",
        "data_column": "outcome",
        "scale_type": "nominal",
        "unit": "category",
        "admissible_values": ["yes", "no"],
        "missing_value_codes": ["not_recorded"],
        "valid_min": None,
        "valid_max": None,
    }
    contract.update(overrides)
    return contract


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"measurement_id": " m1 "}, "measurement_id must be canonical"),
        ({"measurement_id": ""}, "measurement_id must be canonical"),
        ({"measurement_id": None}, "measurement_id must be canonical"),
        ({"data_column": " outcome "}, "data_column must be canonical"),
        ({"admissible_values": ["yes", "Yes"]}, "admissible_values must be case-insensitively unique"),
        ({"missing_value_codes": ["NA", "na"]}, "missing_value_codes must be case-insensitively unique"),
        ({"admissible_values": ["yes"], "missing_value_codes": ["YES"]}, "must not overlap"),
        ({"missing_value_codes": [" NA "]}, "value-domain entries must be canonical"),
        ({"scale_type": " ratio "}, "scale_type must be canonical"),
        ({"scale_type": "magnitude"}, "scale_type is unsupported"),
        ({"unit": " category "}, "unit must be canonical"),
        ({"scale_type": "ratio", "valid_min": 1.0, "valid_max": 1.0}, "valid_min must be strictly below"),
        ({"scale_type": "ratio", "valid_min": True}, "validity bounds must be finite"),
    ],
)
def test_measurement_value_validation_rejects_noncanonical_contracts(overrides, message):
    rows = [{"outcome": "yes"}]
    with pytest.raises(ValidationError, match=message):
        validate_measurement_values(rows, [_measurement_contract(**overrides)])


def test_measurement_value_validation_rejects_duplicate_normalized_columns():
    rows = [{"outcome": "1", "Outcome2": "2"}]
    first = _measurement_contract(scale_type="ratio", admissible_values=[], valid_min=0.0, valid_max=10.0)
    second = _measurement_contract(
        measurement_id="m2",
        data_column="OUTCOME",
        scale_type="ratio",
        admissible_values=[],
        valid_min=0.0,
        valid_max=10.0,
    )
    with pytest.raises(ValidationError, match="data_column values must be case-insensitively unique"):
        validate_measurement_values(rows, [first, second])


def test_measurement_value_validation_rejects_duplicate_measurement_ids():
    rows = [{"outcome": "1", "other": "2"}]
    first = _measurement_contract(
        scale_type="ratio",
        admissible_values=[],
        valid_min=0.0,
        valid_max=10.0,
    )
    second = _measurement_contract(
        data_column="other",
        scale_type="ratio",
        admissible_values=[],
        valid_min=0.0,
        valid_max=10.0,
    )

    with pytest.raises(ValidationError, match="measurement_id values must be unique"):
        validate_measurement_values(rows, [first, second])


def test_measurement_value_validation_rejects_padded_numeric_source_values():
    rows = [{"outcome": " 1.5"}]
    contract = _measurement_contract(
        scale_type="ratio",
        admissible_values=[],
        valid_min=0.0,
        valid_max=10.0,
    )

    with pytest.raises(ValidationError, match="noncanonical numeric value"):
        validate_measurement_values(rows, [contract])


@pytest.mark.parametrize(("expected", "effect"), [("positive", 0.1), ("negative", -0.1), ("two_sided", -2.0)])
def test_supporting_direction_must_match_frozen_prediction(expected, effect) -> None:
    assert "uncertainty still governs" in validate_result_direction(
        expected_direction=expected,
        evidence_direction=EvidenceDirection.SUPPORTS,
        effect=effect,
        uncertainty={"lower": effect - 0.05, "upper": effect + 0.05, "level": 0.95},
        null_value=0.0,
        support_rule="point_direction",
    )


@pytest.mark.parametrize(("expected", "effect"), [("positive", -0.1), ("positive", 0.0), ("negative", 0.1), ("negative", 0.0)])
def test_supporting_direction_rejects_opposite_or_null_point_estimate(expected, effect) -> None:
    with pytest.raises(ValidationError, match="contradicts"):
        validate_result_direction(
            expected_direction=expected,
            evidence_direction=EvidenceDirection.SUPPORTS,
            effect=effect,
            uncertainty={"lower": effect - 0.05, "upper": effect + 0.05, "level": 0.95},
            null_value=0.0,
            support_rule="point_direction",
        )


@pytest.mark.parametrize("direction", [EvidenceDirection.WEAKENS, EvidenceDirection.REFUTES, EvidenceDirection.INCONCLUSIVE])
def test_non_supporting_evidence_is_not_suppressed_by_point_sign(direction) -> None:
    assert validate_result_direction(
        expected_direction="positive", evidence_direction=direction, effect=-1.0,
        uncertainty={"lower": -2.0, "upper": 0.0, "level": 0.95},
        null_value=0.0, support_rule="interval_excludes_null",
    ) == "not_directionally_assertive"


def test_interval_support_rule_requires_registered_interval_to_exclude_null() -> None:
    with pytest.raises(ValidationError, match="interval-excludes-null"):
        validate_result_direction(
            expected_direction="positive", evidence_direction=EvidenceDirection.SUPPORTS,
            effect=0.1, uncertainty={"lower": -0.1, "upper": 0.3, "level": 0.95},
            null_value=0.0, support_rule="interval_excludes_null",
        )


def test_equivalence_requires_interval_wholly_within_frozen_margin() -> None:
    interval = {"lower": -0.2, "upper": 0.3, "level": 0.90}
    assert validate_result_direction(
        expected_direction="equivalence", evidence_direction=EvidenceDirection.SUPPORTS,
        effect=0.05, uncertainty=interval, null_value=0.0,
        support_rule="interval_within_equivalence_margin", equivalence_margin=0.5,
    ) == "confidence_interval_wholly_within_registered_equivalence_margin"
    with pytest.raises(ValidationError, match="not wholly within"):
        validate_result_direction(
            expected_direction="equivalence", evidence_direction=EvidenceDirection.SUPPORTS,
            effect=0.05, uncertainty={"lower": -0.6, "upper": 0.3, "level": 0.90},
            null_value=0.0, support_rule="interval_within_equivalence_margin",
            equivalence_margin=0.5,
        )


def test_equivalence_conclusion_never_infers_absence_from_nonsignificance() -> None:
    analysis = AnalysisContract(
        "h1", "m1", "independent_mean_difference_ci", "outcome", "group",
        ["a", "b"], "Mean difference.", "complete_case", "randomized_between_units",
        "/result/effect", "/result/interval", 0.0,
        "interval_within_equivalence_margin", confidence_level=0.90,
    )
    conclusion = ConclusionContract(
        "h1", "equivalence_interval_within_margin", 0.5, "mean difference",
        "units", "registered population", "registered setting", "endpoint",
        EvidenceDirection.INCONCLUSIVE, ClaimLevel.STATISTICAL_ASSOCIATION,
        ["No proof of exact equality, mechanism, or unrestricted generalization."],
    )
    hypothesis = Hypothesis(
        "h1", "Groups are equivalent within half a unit.", "2026-09-06T00:00:00Z",
        "human", expected_effect_direction="equivalence",
    )
    supported = adjudicate_conclusion_contract(
        conclusion=conclusion, analysis=analysis, hypothesis=hypothesis,
        effect=0.05, uncertainty={"lower": -0.2, "upper": 0.3, "level": 0.90},
    )
    assert supported["adjudicated_evidence_direction"] == "supports"
    assert supported["criteria"]["absence_not_inferred_from_nonsignificance"] is True
    inconclusive = adjudicate_conclusion_contract(
        conclusion=conclusion, analysis=analysis, hypothesis=hypothesis,
        effect=0.0, uncertainty={"lower": -0.8, "upper": 0.8, "level": 0.90},
    )
    assert inconclusive["adjudicated_evidence_direction"] == "inconclusive"
    validate_equivalence_design_coherence(
        analysis_contract=analysis, conclusion_contract=conclusion,
        expected_direction="equivalence", multiplicity_method="single_test",
        multiplicity_alpha=0.05,
    )
    with pytest.raises(ValidationError, match="one minus twice"):
        validate_equivalence_design_coherence(
            analysis_contract=AnalysisContract(
                **{**analysis.__dict__, "confidence_level": 0.95}
            ),
            conclusion_contract=conclusion, expected_direction="equivalence",
            multiplicity_method="single_test", multiplicity_alpha=0.05,
        )
    with pytest.raises(ValidationError, match="declared together"):
        validate_equivalence_design_coherence(
            analysis_contract=analysis, conclusion_contract=conclusion,
            expected_direction="two_sided", multiplicity_method="single_test",
            multiplicity_alpha=0.05,
        )


@pytest.mark.parametrize(
    ("expected", "effect", "interval"),
    [
        ("positive", 2.5, {"lower": 0.1, "upper": 4.0, "level": 0.95}),
        ("negative", -2.5, {"lower": -4.0, "upper": -0.1, "level": 0.95}),
        ("two_sided", 2.5, {"lower": 0.1, "upper": 4.0, "level": 0.95}),
    ],
)
def test_practical_importance_requires_interval_not_only_point_estimate(
    expected, effect, interval,
) -> None:
    analysis = AnalysisContract(
        "h1", "m1", "independent_mean_difference_ci", "outcome", "group",
        ["a", "b"], "Mean difference.", "complete_case", "nonrandomized",
        "/result/effect", "/result/interval", 0.0, "interval_excludes_null",
    )
    conclusion = ConclusionContract(
        "h1", "interval_and_practical_significance", 2.0, "mean difference",
        "units", "population", "setting", "endpoint",
        EvidenceDirection.INCONCLUSIVE, ClaimLevel.STATISTICAL_ASSOCIATION,
        ["No claim beyond the registered population and endpoint."],
    )
    hypothesis = Hypothesis(
        "h1", "Registered directional hypothesis.", "2026-09-06T00:00:00Z",
        "human", expected_effect_direction=expected,
    )
    result = adjudicate_conclusion_contract(
        conclusion=conclusion, analysis=analysis, hypothesis=hypothesis,
        effect=effect, uncertainty=interval,
    )
    assert result["criteria"]["registered_interval_supports_expected_direction"] is True
    assert result["criteria"]["practical_significance_satisfied"] is False
    assert result["criteria"]["practical_significance_requires_confidence_bound"] is True
    assert result["adjudicated_evidence_direction"] == "inconclusive"
@pytest.mark.parametrize("uncertainty", [
    {"lower": 0.2, "upper": 0.4, "level": 0.95},
    {"lower": -0.1, "upper": 0.2, "level": 1.0},
    {"lower": -0.1, "upper": 0.2},
])
def test_registered_confidence_interval_must_be_coherent(uncertainty) -> None:
    with pytest.raises(ValidationError, match="confidence interval"):
        validate_result_direction(
            expected_direction="positive", evidence_direction=EvidenceDirection.INCONCLUSIVE,
            effect=0.1, uncertainty=uncertainty, null_value=0.0,
            support_rule="point_direction",
        )


def test_executed_interval_level_must_match_frozen_contract() -> None:
    interval = {"lower": -0.1, "upper": 0.2, "level": 0.95}
    validate_registered_confidence_level(interval, 0.95)
    with pytest.raises(ValidationError, match="does not match"):
        validate_registered_confidence_level(interval, 0.90)


def test_registered_information_gate_enforces_minimum_units_and_attrition() -> None:
    result = {"result": {
        "n_by_group": {"a": 4, "b": 3},
        "exclusion_report": {
            "input_records": 10, "included_records": 7,
            "excluded_records": [{}, {}, {}],
            "excluded_by_group": {"a": 1, "b": 2},
            "excluded_without_registered_group": 0,
        },
    }}
    contract = {
        "groups": ["a", "b"], "minimum_analyzable_units": 3,
        "maximum_excluded_fraction": 0.3,
        "maximum_group_excluded_fraction_difference": 0.2,
    }
    check = validate_registered_information(result, contract)
    assert check["observed_minimum_analyzable_units"] == 3
    assert check["observed_excluded_fraction"] == pytest.approx(0.3)
    assert check["observed_excluded_fraction_by_group"] == pytest.approx(
        {"a": 0.2, "b": 0.4}
    )
    assert check["observed_group_excluded_fraction_difference"] == pytest.approx(0.2)
    with pytest.raises(ValidationError, match="frozen minimum"):
        validate_registered_information(result, {**contract, "minimum_analyzable_units": 4})
    with pytest.raises(ValidationError, match="exceeds the frozen maximum"):
        validate_registered_information(result, {**contract, "maximum_excluded_fraction": 0.29})
    with pytest.raises(ValidationError, match="between-group"):
        validate_registered_information(result, {
            **contract, "maximum_group_excluded_fraction_difference": 0.19,
        })
    unidentified = {
        **result,
        "result": {**result["result"], "exclusion_report": {
            **result["result"]["exclusion_report"],
            "excluded_by_group": {"a": 1, "b": 1},
            "excluded_without_registered_group": 1,
        }},
    }
    with pytest.raises(ValidationError, match="without a registered group"):
        validate_registered_information(unidentified, contract)
    understated = {
        **result,
        "result": {**result["result"], "exclusion_report": {
            **result["result"]["exclusion_report"],
            "excluded_by_group": {"a": 0, "b": 2},
        }},
    }
    with pytest.raises(ValidationError, match="do not equal the exclusion report total"):
        validate_registered_information(understated, contract)
    inflated_included_groups = {
        **result,
        "result": {**result["result"], "n_by_group": {"a": 5, "b": 3}},
    }
    with pytest.raises(ValidationError, match="included group counts"):
        validate_registered_information(inflated_included_groups, contract)


def prepared_service(root: Path) -> tuple[ResearchService, str]:
    counter = iter(f"token{i:02d}" for i in range(100))
    service = ResearchService(
        FileSystemRepository(root),
        actor="test-researcher",
        clock=lambda: "2026-09-02T12:00:00Z",
        token=lambda: next(counter),
    )
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry("Formal theory", "Can two models be distinguished?", "formal")
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The candidate axioms entail the registered invariant.",
            observable_prediction="A checked derivation produces the invariant.",
            null_model="No valid derivation exists in the bounded proof system.",
            falsification_conditions=["The proof checker rejects the derivation."],
            primary_estimand="Mean outcome difference, group a minus group b.",
            contrast_definition="group a minus group b",
            contrast_groups=["a", "b"],
            expected_effect_direction="negative",
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    return service, hypothesis.hypothesis_id


def frozen_formal_protocol(
    service: ResearchService,
    hypothesis_id: str,
    *,
    preprocessing_pipeline: str = "",
    canary_target_plan: CanaryTargetPlan | None = None,
):
    quality_requirements = ["proof-check"]
    if canary_target_plan is not None:
        quality_requirements.append(canary_target_plan.assessment_gate_id)
    protocol = service.create_protocol(
        CreateProtocol(
            experiment_id="formal-check-01",
            title="Check the invariant derivation",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[hypothesis_id],
            primary_outcome="Proof checker acceptance",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Construct a derivation and replay it in the proof checker.",
            quality_requirements=quality_requirements,
            controls=["Replay a deliberately invalid derivation."],
            expected_outputs=["Proof object", "Checker transcript"],
            success_conditions=["The independent checker accepts the proof object."],
            environment_requirements=["Pinned checker and axiom-set hashes"],
            sample_size_or_stopping_rule=(
                "One registered proof object and one fixed invalid control."
            ),
            failure_conditions=["The checker rejects any proof step."],
            safety_constraints=["No physical or human intervention is involved."],
            preprocessing_pipeline=preprocessing_pipeline,
            canary_target_plan=canary_target_plan,
            analysis_code_hash=CODE_HASH,
            random_seed_commitment=SEED_COMMITMENT,
        )
    )
    return service.freeze_protocol(protocol.protocol_id)


def run_command(protocol_id: str, status: QualityGateStatus, **overrides) -> RecordRun:
    values = {
        "protocol_id": protocol_id,
        "started_at": "2026-09-02T12:01:00Z",
        "completed_at": "2026-09-02T12:02:00Z",
        "analysis_code_hash": CODE_HASH,
        "environment_hash": ENVIRONMENT_HASH,
        "random_seed_reveal": SEED_REVEAL,
        "output_artifacts": [
            DatasetArtifact(
                "proof-output.json", "c" * 64, media_type="application/json"
            )
        ],
        "quality_gates": [
            QualityGateResult(
                gate_id="proof-check",
                status=status,
                summary="Independent proof-checker result.",
                details={"evidence_sha256": "c" * 64} if status is QualityGateStatus.PASSED else {},
            )
        ],
        "metadata": {
            "protocol_deviation_disclosure": {
                "status": "no_deviations_declared",
                "deviations": [],
            }
        },
    }
    values.update(overrides)
    return RecordRun(**values)


def _preprocessing_pipeline(*, smoothing_window: int = 5) -> dict:
    return {
        "pipeline_id": "registered-pipeline",
        "purpose": "Synthetic fixture for preprocessing conformance.",
        "steps": [
            {
                "step_id": "load-raw",
                "operation": "read fixture bytes",
                "parameters": {"encoding": "utf-8"},
                "input_artifacts": [{
                    "artifact_id": "raw-input",
                    "sha256": "1" * 64,
                    "media_type": "text/csv",
                    "role": "raw observation fixture",
                }],
                "output_artifacts": [{
                    "artifact_id": "loaded-table",
                    "sha256": "2" * 64,
                    "media_type": "application/json",
                    "role": "loaded table fixture",
                }],
                "implementation_sha256": "3" * 64,
            },
            {
                "step_id": "smooth-signal",
                "operation": "moving average",
                "parameters": {"window": smoothing_window, "edge_policy": "drop"},
                "input_artifacts": [{
                    "artifact_id": "loaded-table",
                    "sha256": "2" * 64,
                    "media_type": "application/json",
                    "role": "loaded table fixture",
                }],
                "output_artifacts": [{
                    "artifact_id": "smoothed-table",
                    "sha256": "4" * 64,
                    "media_type": "application/json",
                    "role": "preprocessed table fixture",
                }],
                "implementation_sha256": "5" * 64,
            },
        ],
    }


def _write_json_artifact(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_payload_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _instrument_inspection_record() -> dict:
    source_sha256 = "1" * 64
    implementation_sha256 = "2" * 64
    return {
        "instrument_inspection_version": 1,
        "adapter": {
            "addon_id": "fixture_instrument",
            "addon_version": "1.0.0",
            "adapter_id": "fixture_scope",
            "authority": "acquisition_metadata_proposal_only",
            "implementation": {
                "locator": "research_addon.py",
                "sha256": implementation_sha256,
                "size_bytes": 100,
            },
        },
        "source": {
            "locator": "capture.bin",
            "sha256": source_sha256,
            "size_bytes": 8,
            "media_type": "application/octet-stream",
        },
        "config": {
            "captured_at": "2026-09-06T12:00:00Z",
            "instrument_identifier": "scope-fixture-01",
        },
        "proposed_raw_source": {
            "locator": "capture.bin",
            "sha256": source_sha256,
            "captured_at": "2026-09-06T12:00:00Z",
            "acquisition_method": "Synthetic fixture acquisition.",
        },
        "instrument": {
            "identifier": "scope-fixture-01",
            "model": "Fixture scope",
            "firmware_version": "",
            "captured_at_basis": "device_metadata",
            "native_metadata": {"fixture": True},
        },
        "temporal_metadata": {
            "status": "proposed_unverified",
            "stream_count": 1,
            "limitations": [
                "Synthetic fixture stream timing remains unverified.",
            ],
        },
        "streams": [{
            "stream_id": "stream-main",
            "source_device": "scope-fixture-01",
            "channel": "main",
            "sample_rate_hz": 256,
            "clock_source": "device clock",
            "start_time": "2026-09-06T12:00:00Z",
            "clock_drift": {
                "estimate": 0.2,
                "uncertainty": 0.05,
                "unit": "ms",
                "basis": "manufacturer sidecar",
            },
            "missing_intervals": [{
                "start_time": "2026-09-06T12:00:01Z",
                "end_time": "2026-09-06T12:00:02Z",
                "reason": "Dropped packet fixture",
            }],
            "calibration_record": "clock-sync-record-1",
            "quality_flags": ["synthetic-fixture"],
            "raw_file_sha256": source_sha256,
            "conversion_code_sha256": implementation_sha256,
        }],
        "warnings": ["Synthetic adapter fixture."],
        "status": "inspection_recorded",
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Adapter-proposed acquisition metadata bound to core-hashed source bytes. "
            "No calibration, quality gate, custody chain, dataset, or evidence is approved."
        ),
    }


def _instrument_inspection_gate_fixture(
    tmp_path: Path,
    *,
    gate_status: QualityGateStatus = QualityGateStatus.PASSED,
) -> tuple[list[DatasetArtifact], list[QualityGateResult], dict]:
    record = tmp_path / "instrument-inspection.json"
    record_value = _instrument_inspection_record()
    record_sha256 = _write_json_artifact(record, record_value)
    artifact = DatasetArtifact(
        record.name,
        record_sha256,
        size_bytes=record.stat().st_size,
        media_type="application/json",
    )
    gate = QualityGateResult(
        "proof-check",
        gate_status,
        "Instrument inspection was replayed from current bytes.",
        details={
            "evidence_sha256": record_sha256,
            "instrument_inspection": {
                "locator": record.name,
                "sha256": record_sha256,
                "status": record_value["status"],
                "source_sha256": record_value["source"]["sha256"],
                "config_sha256": _canonical_payload_sha256(record_value["config"]),
                "implementation_sha256": record_value["adapter"]["implementation"]["sha256"],
            },
        },
    )
    return [artifact], [gate], {
        "inspection_sha256": record_sha256,
        "status": record_value["status"],
    }


def _preprocessing_conformance_gate_fixture(
    tmp_path: Path,
    *,
    observed_smoothing_window: int = 5,
    gate_status: QualityGateStatus = QualityGateStatus.PASSED,
) -> tuple[list[DatasetArtifact], list[QualityGateResult], dict]:
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha256 = _write_json_artifact(registered, _preprocessing_pipeline())
    observed_sha256 = _write_json_artifact(
        observed,
        _preprocessing_pipeline(smoothing_window=observed_smoothing_window),
    )
    result = assess_preprocessing_conformance(
        registered,
        registered_sha256,
        observed,
        observed_sha256,
        tmp_path / "preprocessing-conformance",
    )
    record = Path(result["path"]) / "preprocessing-conformance.json"
    record_locator = str(record.relative_to(tmp_path))
    artifact = DatasetArtifact(
        record_locator,
        result["assessment_sha256"],
        size_bytes=record.stat().st_size,
        media_type="application/json",
    )
    gate = QualityGateResult(
        "proof-check",
        gate_status,
        "Preprocessing conformance was replayed from current bytes.",
        details={
            "evidence_sha256": result["assessment_sha256"],
            "preprocessing_conformance": {
                "locator": record_locator,
                "sha256": result["assessment_sha256"],
                "status": result["status"],
                "registered_pipeline_sha256": registered_sha256,
                "observed_pipeline_sha256": observed_sha256,
            },
        },
    )
    return [artifact], [gate], result


def _temporal_order_spec() -> dict:
    return {
        "assessment_id": "temporal-order",
        "order_checks": [
            {
                "check_id": "state-before-sound",
                "first_event_id": "state-event",
                "second_event_id": "sound-event",
                "expected_relation": "first_precedes_second",
                "minimum_separation": {"duration": 1, "unit": "ms"},
                "maximum_separation": {"duration": 20, "unit": "ms"},
                "scientific_question": "Synthetic fixture for temporal ordering.",
            }
        ],
    }


def _stream_timing_assessment_record(*, failed: bool = False) -> dict:
    findings = (
        [{
            "severity": "error",
            "code": "CLOCK_UNCERTAINTY_APPROACHES_LAG_WINDOW",
            "message": "Synthetic fixture timing uncertainty reached the threshold.",
        }]
        if failed
        else []
    )
    return {
        "stream_timing_assessment_version": 1,
        "assessment_id": "stream-timing",
        "inspection": {
            "sha256": "1" * 64,
            "size_bytes": 100,
            "stream_count": 1,
            "temporal_metadata_status": "proposed_unverified",
        },
        "specification": {
            "sha256": "2" * 64,
            "size_bytes": 100,
            "lag_window": {
                "duration": 1,
                "unit": "ms",
                "seconds": 0.001,
                "basis": "Synthetic fixture lag window.",
            },
            "maximum_uncertainty_fraction": 0.25,
        },
        "required_streams": [{
            "stream_id": "stream-main",
            "channel": "main",
            "purpose": "Primary synchronized signal fixture.",
            "observed_channel": "main",
            "status": "present",
        }],
        "events": [{
            "event_id": "state-event",
            "stream_id": "stream-main",
            "event_time": "2026-09-06T12:00:03.000000Z",
            "status": "assessed",
            "clock_uncertainty_seconds": 0.00005,
            "stream_start_time": "2026-09-06T12:00:00Z",
            "uncertainty_fraction_of_lag_window": 0.05,
            "overlapping_missing_intervals": [],
        }],
        "findings": findings,
        "status": "timing_feasibility_failed" if failed else "timing_feasibility_passed",
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Provider-free timing feasibility review from a trusted inspection record only. "
            "It does not authenticate acquisition, verify calibration or drift correction, "
            "clear a protocol gate, register a dataset, or authorize scientific evidence."
        ),
    }


def _stream_timing_assessment_gate_fixture(
    tmp_path: Path,
    *,
    failed: bool = False,
    gate_status: QualityGateStatus = QualityGateStatus.PASSED,
) -> tuple[list[DatasetArtifact], list[QualityGateResult], dict]:
    record = tmp_path / (
        "failed-stream-timing-assessment.json" if failed else "stream-timing-assessment.json"
    )
    record_value = _stream_timing_assessment_record(failed=failed)
    record_sha256 = _write_json_artifact(record, record_value)
    artifact = DatasetArtifact(
        record.name,
        record_sha256,
        size_bytes=record.stat().st_size,
        media_type="application/json",
    )
    gate = QualityGateResult(
        "proof-check",
        gate_status,
        "Stream timing was replayed from current bytes.",
        details={
            "evidence_sha256": record_sha256,
            "stream_timing_assessment": {
                "locator": record.name,
                "sha256": record_sha256,
                "status": record_value["status"],
                "inspection_sha256": record_value["inspection"]["sha256"],
                "specification_sha256": record_value["specification"]["sha256"],
            },
        },
    )
    return [artifact], [gate], {
        "assessment_sha256": record_sha256,
        "status": record_value["status"],
    }


def _temporal_timing_assessment(*, reversed_order: bool = False) -> dict:
    state_time = "2026-09-06T12:00:03.010000Z" if reversed_order else "2026-09-06T12:00:03.000000Z"
    sound_time = "2026-09-06T12:00:03.000000Z" if reversed_order else "2026-09-06T12:00:03.010000Z"
    return {
        "stream_timing_assessment_version": 1,
        "assessment_id": "temporal-order-upstream-timing",
        "inspection": {
            "sha256": "1" * 64,
            "size_bytes": 100,
            "stream_count": 1,
            "temporal_metadata_status": "proposed_unverified",
        },
        "specification": {
            "sha256": "2" * 64,
            "size_bytes": 100,
            "lag_window": {
                "duration": 1,
                "unit": "ms",
                "seconds": 0.001,
                "basis": "Synthetic fixture lag window.",
            },
            "maximum_uncertainty_fraction": 0.25,
        },
        "required_streams": [{
            "stream_id": "stream-main",
            "channel": "main",
            "purpose": "Primary synchronized signal fixture.",
            "observed_channel": "main",
            "status": "present",
        }],
        "events": [
            {
                "event_id": "state-event",
                "stream_id": "stream-main",
                "event_time": state_time,
                "status": "assessed",
                "clock_uncertainty_seconds": 0.00005,
                "stream_start_time": "2026-09-06T12:00:00Z",
                "uncertainty_fraction_of_lag_window": 0.05,
                "overlapping_missing_intervals": [],
            },
            {
                "event_id": "sound-event",
                "stream_id": "stream-main",
                "event_time": sound_time,
                "status": "assessed",
                "clock_uncertainty_seconds": 0.00005,
                "stream_start_time": "2026-09-06T12:00:00Z",
                "uncertainty_fraction_of_lag_window": 0.05,
                "overlapping_missing_intervals": [],
            },
        ],
        "findings": [],
        "status": "timing_feasibility_passed",
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Provider-free timing feasibility review from a trusted inspection record only. "
            "It does not authenticate acquisition, verify calibration or drift correction, "
            "clear a protocol gate, register a dataset, or authorize scientific evidence."
        ),
    }


def _temporal_order_assessment_gate_fixture(
    tmp_path: Path,
    *,
    reversed_order: bool = False,
    gate_status: QualityGateStatus = QualityGateStatus.PASSED,
) -> tuple[list[DatasetArtifact], list[QualityGateResult], dict]:
    suffix = "reversed" if reversed_order else "passed"
    timing = tmp_path / f"{suffix}-timing-assessment.json"
    spec = tmp_path / f"{suffix}-temporal-order-spec.json"
    timing_sha256 = _write_json_artifact(
        timing,
        _temporal_timing_assessment(reversed_order=reversed_order),
    )
    specification_sha256 = _write_json_artifact(spec, _temporal_order_spec())
    result = assess_temporal_order(
        timing,
        timing_sha256,
        spec,
        tmp_path / f"{suffix}-temporal-order",
    )
    record = Path(result["path"]) / "temporal-order-assessment.json"
    record_locator = str(record.relative_to(tmp_path))
    artifact = DatasetArtifact(
        record_locator,
        result["assessment_sha256"],
        size_bytes=record.stat().st_size,
        media_type="application/json",
    )
    gate = QualityGateResult(
        "proof-check",
        gate_status,
        "Temporal order was replayed from current bytes.",
        details={
            "evidence_sha256": result["assessment_sha256"],
            "temporal_order_assessment": {
                "locator": record_locator,
                "sha256": result["assessment_sha256"],
                "status": result["status"],
                "timing_assessment_sha256": timing_sha256,
                "specification_sha256": specification_sha256,
            },
        },
    )
    return [artifact], [gate], result


def test_run_replays_passed_preprocessing_conformance_gate(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, result = _preprocessing_conformance_gate_fixture(
        tmp_path
    )

    run = service.record_run(run_command(
        protocol.protocol_id,
        QualityGateStatus.PASSED,
        artifact_root=str(tmp_path),
        output_artifacts=output_artifacts,
        quality_gates=quality_gates,
    ))

    assert run.status is RunStatus.COMPLETED
    assert run.quality_gates[0].details["preprocessing_conformance"]["status"] == (
        "preprocessing_conformance_passed"
    )
    assert run.quality_gates[0].details["evidence_sha256"] == result["assessment_sha256"]
    assert run.metadata["artifact_integrity"]["status"] == "passed"
    synthesis = service.build_synthesis()["content"]
    assert "Preprocessing conformance provenance" in synthesis
    assert result["assessment_sha256"] in synthesis
    assert "bounded conformance replay, not evidence of implementation correctness" in synthesis
    assert any(
        finding.code == "RUN_PREPROCESSING_CONFORMANCE_REPLAYED"
        for finding in service.audit_rigor().findings
    )


def test_run_replays_passed_instrument_inspection_gate(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, result = _instrument_inspection_gate_fixture(
        tmp_path
    )

    run = service.record_run(run_command(
        protocol.protocol_id,
        QualityGateStatus.PASSED,
        artifact_root=str(tmp_path),
        output_artifacts=output_artifacts,
        quality_gates=quality_gates,
    ))

    assert run.status is RunStatus.COMPLETED
    inspection = run.quality_gates[0].details["instrument_inspection"]
    assert inspection["status"] == "inspection_recorded"
    assert inspection["stream_count"] == 1
    assert inspection["temporal_metadata_status"] == "proposed_unverified"
    assert run.quality_gates[0].details["evidence_sha256"] == result["inspection_sha256"]
    synthesis = service.build_synthesis()["content"]
    assert "Instrument inspection provenance" in synthesis
    assert result["inspection_sha256"] in synthesis
    assert "Proposed streams: 1; temporal metadata status: `proposed_unverified`" in synthesis
    assert "not calibration, custody, or scientific-evidence approval" in synthesis
    finding = next(
        finding
        for finding in service.audit_rigor().findings
        if finding.code == "RUN_INSTRUMENT_INSPECTION_REPLAYED"
    )
    assert "1 proposed streams" in finding.message
    assert "proposed_unverified" in finding.message


def test_run_rejects_instrument_inspection_summary_drift(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _instrument_inspection_gate_fixture(
        tmp_path
    )
    quality_gates[0].details["instrument_inspection"]["stream_count"] = 99

    with pytest.raises(
        ValidationError,
        match="instrument_inspection stream_count does not match the verified record",
    ):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_rejects_instrument_inspection_gate_evidence_split(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _instrument_inspection_gate_fixture(
        tmp_path
    )
    decoy = tmp_path / "instrument-decoy.json"
    decoy_sha256 = _write_json_artifact(decoy, {"fixture": "decoy"})
    output_artifacts.append(DatasetArtifact(
        decoy.name,
        decoy_sha256,
        size_bytes=decoy.stat().st_size,
        media_type="application/json",
    ))
    quality_gates[0].details["evidence_sha256"] = decoy_sha256

    with pytest.raises(
        ValidationError,
        match="evidence_sha256 must match instrument_inspection.sha256",
    ):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_rejects_instrument_inspection_implementation_hash_drift(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _instrument_inspection_gate_fixture(tmp_path)
    quality_gates[0].details["instrument_inspection"]["implementation_sha256"] = (
        "0" * 64
    )

    with pytest.raises(ValidationError, match="implementation SHA-256 mismatch"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_rejects_failed_instrument_inspection_retention_gate(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _instrument_inspection_gate_fixture(
        tmp_path,
        gate_status=QualityGateStatus.FAILED,
    )

    with pytest.raises(ValidationError, match="can only record a passed retention gate"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.FAILED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_rejects_passed_preprocessing_gate_with_failed_record(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _preprocessing_conformance_gate_fixture(
        tmp_path,
        observed_smoothing_window=9,
    )

    with pytest.raises(ValidationError, match="requires a passed preprocessing conformance record"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_preserves_failed_preprocessing_conformance_gate(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _preprocessing_conformance_gate_fixture(
        tmp_path,
        observed_smoothing_window=9,
        gate_status=QualityGateStatus.FAILED,
    )

    run = service.record_run(run_command(
        protocol.protocol_id,
        QualityGateStatus.FAILED,
        artifact_root=str(tmp_path),
        output_artifacts=output_artifacts,
        quality_gates=quality_gates,
    ))

    assert run.status is RunStatus.INVALID
    assert run.quality_gates[0].details["preprocessing_conformance"]["status"] == (
        "preprocessing_conformance_failed"
    )
    assert run.scientific_evidence_eligible is False
    synthesis = service.build_synthesis()["content"]
    assert "record status: preprocessing_conformance_failed" in synthesis
    assert any(
        finding.code == "RUN_PREPROCESSING_CONFORMANCE_FAILED"
        and finding.entity_id == run.run_id
        for finding in service.audit_rigor().findings
    )


def test_run_rejects_preprocessing_conformance_upstream_hash_drift(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _preprocessing_conformance_gate_fixture(tmp_path)
    quality_gates[0].details["preprocessing_conformance"]["registered_pipeline_sha256"] = (
        "0" * 64
    )

    with pytest.raises(ValidationError, match="registered pipeline SHA-256 mismatch"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_rejects_preprocessing_conformance_outside_frozen_pipeline(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    output_artifacts, quality_gates, result = _preprocessing_conformance_gate_fixture(
        tmp_path
    )
    protocol = frozen_formal_protocol(
        service,
        hypothesis_id,
        preprocessing_pipeline="0" * 64,
    )

    with pytest.raises(
        ValidationError,
        match="does not match frozen protocol preprocessing_pipeline",
    ):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))
    assert protocol.preprocessing_pipeline != result["registered_pipeline_sha256"]


def test_run_replays_passed_stream_timing_assessment_gate(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, result = _stream_timing_assessment_gate_fixture(
        tmp_path
    )

    run = service.record_run(run_command(
        protocol.protocol_id,
        QualityGateStatus.PASSED,
        artifact_root=str(tmp_path),
        output_artifacts=output_artifacts,
        quality_gates=quality_gates,
    ))

    assert run.status is RunStatus.COMPLETED
    assert run.quality_gates[0].details["stream_timing_assessment"]["status"] == (
        "timing_feasibility_passed"
    )
    assert run.quality_gates[0].details["stream_timing_assessment"]["required_stream_count"] == 1
    assert run.quality_gates[0].details["stream_timing_assessment"]["required_stream_failure_count"] == 0
    assert run.quality_gates[0].details["stream_timing_assessment"]["event_count"] == 1
    assert run.quality_gates[0].details["stream_timing_assessment"]["event_failure_count"] == 0
    assert run.quality_gates[0].details["stream_timing_assessment"]["finding_count"] == 0
    assert run.quality_gates[0].details["evidence_sha256"] == result["assessment_sha256"]
    synthesis = service.build_synthesis()["content"]
    assert "Stream timing provenance" in synthesis
    assert result["assessment_sha256"] in synthesis
    assert "Required streams: 1; stream failures: 0; events: 1; event failures: 0; findings: 0." in synthesis
    assert "does not authenticate acquisition" in synthesis
    assert any(
        finding.code == "RUN_STREAM_TIMING_ASSESSMENT_REPLAYED"
        and "1 required streams" in finding.message
        for finding in service.audit_rigor().findings
    )


def test_run_rejects_stream_timing_gate_evidence_split(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _stream_timing_assessment_gate_fixture(
        tmp_path
    )
    decoy = tmp_path / "stream-timing-decoy.json"
    decoy_sha256 = _write_json_artifact(decoy, {"fixture": "decoy"})
    output_artifacts.append(DatasetArtifact(
        decoy.name,
        decoy_sha256,
        size_bytes=decoy.stat().st_size,
        media_type="application/json",
    ))
    quality_gates[0].details["evidence_sha256"] = decoy_sha256

    with pytest.raises(
        ValidationError,
        match="evidence_sha256 must match stream_timing_assessment.sha256",
    ):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_rejects_passed_stream_timing_gate_with_failed_record(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _stream_timing_assessment_gate_fixture(
        tmp_path,
        failed=True,
    )

    with pytest.raises(ValidationError, match="requires a passed stream-timing assessment"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_preserves_failed_stream_timing_assessment_gate(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _stream_timing_assessment_gate_fixture(
        tmp_path,
        failed=True,
        gate_status=QualityGateStatus.FAILED,
    )

    run = service.record_run(run_command(
        protocol.protocol_id,
        QualityGateStatus.FAILED,
        artifact_root=str(tmp_path),
        output_artifacts=output_artifacts,
        quality_gates=quality_gates,
    ))

    assert run.status is RunStatus.INVALID
    assert run.quality_gates[0].details["stream_timing_assessment"]["status"] == (
        "timing_feasibility_failed"
    )
    assert run.quality_gates[0].details["stream_timing_assessment"]["required_stream_count"] == 1
    assert run.quality_gates[0].details["stream_timing_assessment"]["required_stream_failure_count"] == 0
    assert run.quality_gates[0].details["stream_timing_assessment"]["event_count"] == 1
    assert run.quality_gates[0].details["stream_timing_assessment"]["event_failure_count"] == 0
    assert run.quality_gates[0].details["stream_timing_assessment"]["finding_count"] == 1
    assert run.scientific_evidence_eligible is False
    synthesis = service.build_synthesis()["content"]
    assert "record status: timing_feasibility_failed" in synthesis
    assert "Required streams: 1; stream failures: 0; events: 1; event failures: 0; findings: 1." in synthesis
    assert any(
        finding.code == "RUN_STREAM_TIMING_ASSESSMENT_FAILED"
        and finding.entity_id == run.run_id
        and "0 event failures of 1 events" in finding.message
        for finding in service.audit_rigor().findings
    )


def test_run_rejects_stream_timing_assessment_summary_drift(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _stream_timing_assessment_gate_fixture(
        tmp_path
    )
    quality_gates[0].details["stream_timing_assessment"]["event_failure_count"] = 1

    with pytest.raises(ValidationError, match="event_failure_count.*verified record"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_rejects_stream_timing_assessment_upstream_hash_drift(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _stream_timing_assessment_gate_fixture(
        tmp_path
    )
    quality_gates[0].details["stream_timing_assessment"]["inspection_sha256"] = (
        "0" * 64
    )

    with pytest.raises(ValidationError, match="inspection SHA-256 mismatch"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_rejects_stream_timing_assessment_arithmetic_drift(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _stream_timing_assessment_gate_fixture(
        tmp_path
    )
    record_path = tmp_path / output_artifacts[0].locator
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["events"][0]["uncertainty_fraction_of_lag_window"] = 0.01
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tampered_sha256 = hashlib.sha256(record_path.read_bytes()).hexdigest()
    output_artifacts = [
        DatasetArtifact(
            output_artifacts[0].locator,
            tampered_sha256,
            size_bytes=record_path.stat().st_size,
            media_type="application/json",
        )
    ]
    quality_gates[0].details["evidence_sha256"] = tampered_sha256
    quality_gates[0].details["stream_timing_assessment"]["sha256"] = tampered_sha256

    with pytest.raises(
        ValidationError,
        match="uncertainty_fraction_of_lag_window disagrees",
    ):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_replays_passed_temporal_order_assessment_gate(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, result = _temporal_order_assessment_gate_fixture(
        tmp_path
    )

    run = service.record_run(run_command(
        protocol.protocol_id,
        QualityGateStatus.PASSED,
        artifact_root=str(tmp_path),
        output_artifacts=output_artifacts,
        quality_gates=quality_gates,
    ))

    assert run.status is RunStatus.COMPLETED
    assert run.quality_gates[0].details["temporal_order_assessment"]["status"] == (
        "temporal_order_passed"
    )
    assert run.quality_gates[0].details["temporal_order_assessment"]["check_count"] == 1
    assert run.quality_gates[0].details["temporal_order_assessment"]["failed_check_count"] == 0
    assert run.quality_gates[0].details["temporal_order_assessment"]["warning_check_count"] == 0
    assert run.quality_gates[0].details["temporal_order_assessment"]["finding_count"] == 0
    assert run.quality_gates[0].details["evidence_sha256"] == result["assessment_sha256"]
    synthesis = service.build_synthesis()["content"]
    assert "Temporal order provenance" in synthesis
    assert result["assessment_sha256"] in synthesis
    assert "Registered order checks: 1; failed: 0; warnings: 0; findings: 0." in synthesis
    assert "does not prove causality" in synthesis
    assert any(
        finding.code == "RUN_TEMPORAL_ORDER_ASSESSMENT_REPLAYED"
        and "1 registered checks" in finding.message
        for finding in service.audit_rigor().findings
    )


def test_run_rejects_temporal_order_gate_evidence_split(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _temporal_order_assessment_gate_fixture(
        tmp_path
    )
    decoy = tmp_path / "temporal-order-decoy.json"
    decoy_sha256 = _write_json_artifact(decoy, {"fixture": "decoy"})
    output_artifacts.append(DatasetArtifact(
        decoy.name,
        decoy_sha256,
        size_bytes=decoy.stat().st_size,
        media_type="application/json",
    ))
    quality_gates[0].details["evidence_sha256"] = decoy_sha256

    with pytest.raises(
        ValidationError,
        match="evidence_sha256 must match temporal_order_assessment.sha256",
    ):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_rejects_passed_temporal_order_gate_with_failed_record(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _temporal_order_assessment_gate_fixture(
        tmp_path,
        reversed_order=True,
    )

    with pytest.raises(ValidationError, match="requires a passed temporal-order assessment"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_preserves_failed_temporal_order_assessment_gate(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _temporal_order_assessment_gate_fixture(
        tmp_path,
        reversed_order=True,
        gate_status=QualityGateStatus.FAILED,
    )

    run = service.record_run(run_command(
        protocol.protocol_id,
        QualityGateStatus.FAILED,
        artifact_root=str(tmp_path),
        output_artifacts=output_artifacts,
        quality_gates=quality_gates,
    ))

    assert run.status is RunStatus.INVALID
    assert run.quality_gates[0].details["temporal_order_assessment"]["status"] == (
        "temporal_order_failed"
    )
    assert run.quality_gates[0].details["temporal_order_assessment"]["check_count"] == 1
    assert run.quality_gates[0].details["temporal_order_assessment"]["failed_check_count"] == 1
    assert run.quality_gates[0].details["temporal_order_assessment"]["warning_check_count"] == 0
    assert run.quality_gates[0].details["temporal_order_assessment"]["finding_count"] == 1
    assert run.scientific_evidence_eligible is False
    synthesis = service.build_synthesis()["content"]
    assert "record status: temporal_order_failed" in synthesis
    assert "Registered order checks: 1; failed: 1; warnings: 0; findings: 1." in synthesis
    assert any(
        finding.code == "RUN_TEMPORAL_ORDER_ASSESSMENT_FAILED"
        and finding.entity_id == run.run_id
        and "1 failed of 1 registered checks" in finding.message
        for finding in service.audit_rigor().findings
    )


def test_run_rejects_temporal_order_assessment_summary_drift(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _temporal_order_assessment_gate_fixture(
        tmp_path
    )
    quality_gates[0].details["temporal_order_assessment"]["failed_check_count"] = 1

    with pytest.raises(ValidationError, match="failed_check_count.*verified record"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_run_rejects_temporal_order_assessment_upstream_hash_drift(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output_artifacts, quality_gates, _ = _temporal_order_assessment_gate_fixture(
        tmp_path
    )
    quality_gates[0].details["temporal_order_assessment"]["specification_sha256"] = (
        "0" * 64
    )

    with pytest.raises(ValidationError, match="specification SHA-256 mismatch"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=output_artifacts,
            quality_gates=quality_gates,
        ))


def test_passed_quality_gate_requires_output_bound_evidence_and_passed_prerequisites(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    with pytest.raises(ValidationError, match="quality gate id must be canonical"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            quality_gates=[QualityGateResult(
                " proof-check",
                QualityGateStatus.PASSED,
                "Padded gate handle",
                details={"evidence_sha256": "c" * 64},
            )],
        ))
    with pytest.raises(ValidationError, match="evidence_sha256"):
        service.record_run(run_command(
            protocol.protocol_id, QualityGateStatus.PASSED,
            quality_gates=[QualityGateResult("proof-check", QualityGateStatus.PASSED, "Unsupported pass")],
        ))
    gates = [
        QualityGateResult("source-check", QualityGateStatus.FAILED, "Source failed"),
        QualityGateResult(
            "proof-check", QualityGateStatus.PASSED, "Depends on source",
            details={"evidence_sha256": "c" * 64, "prerequisite_gate_ids": ["source-check"]},
        ),
    ]
    with pytest.raises(ValidationError, match="requires prerequisite source-check to pass"):
        service.record_run(run_command(
            protocol.protocol_id, QualityGateStatus.PASSED, quality_gates=gates,
        ))
    padded_dependency = [
        QualityGateResult(
            "source-check", QualityGateStatus.PASSED, "Source passed",
            details={"evidence_sha256": "c" * 64},
        ),
        QualityGateResult(
            "proof-check", QualityGateStatus.PASSED, "Depends on source",
            details={"evidence_sha256": "c" * 64, "prerequisite_gate_ids": [" source-check"]},
        ),
    ]
    with pytest.raises(ValidationError, match="prerequisite_gate_ids item must be canonical"):
        service.record_run(run_command(
            protocol.protocol_id, QualityGateStatus.PASSED, quality_gates=padded_dependency,
        ))


def test_run_rejects_skipped_gate_with_structured_result_metadata(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)

    command = run_command(
        protocol.protocol_id,
        QualityGateStatus.SKIPPED,
        quality_gates=[
            QualityGateResult(
                "proof-check",
                QualityGateStatus.SKIPPED,
                "The synthetic fixture gate was not performed.",
                details={
                    "measurement_validity_results": {
                        "checker-reference-agreement": {
                            "observed_diagnostic": "",
                            "evidence_sha256": "c" * 64,
                        }
                    },
                },
            )
        ],
    )

    with pytest.raises(
        ValidationError,
        match="skipped quality gate proof-check cannot report structured results",
    ):
        service.record_run(command, "formal")


def test_run_rejects_skipped_gate_with_evidence_anchor(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)

    command = run_command(
        protocol.protocol_id,
        QualityGateStatus.SKIPPED,
        quality_gates=[
            QualityGateResult(
                "proof-check",
                QualityGateStatus.SKIPPED,
                "The synthetic fixture gate was not performed.",
                details={"evidence_sha256": "c" * 64},
            )
        ],
    )

    with pytest.raises(
        ValidationError,
        match="skipped quality gate proof-check cannot cite evidence_sha256",
    ):
        service.record_run(command, "formal")


def test_run_requires_explicit_no_deviation_disclosure_for_evidence(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    run = service.record_run(
        run_command(protocol.protocol_id, QualityGateStatus.PASSED, metadata={})
    )
    assert run.status is RunStatus.COMPLETED
    assert run.scientific_evidence_eligible is False
    assert run.metadata["protocol_deviation_disclosure"]["status"] == "legacy_not_declared"
    assert any(
        finding.code == "RUN_PROTOCOL_DEVIATIONS_UNDECLARED"
        for finding in service.audit_rigor().findings
    )
    assert "adherence cannot be inferred from silence" in service.build_synthesis()["content"]


def test_declared_protocol_deviation_is_preserved_and_blocks_evidence(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    disclosure = {
        "status": "deviations_declared",
        "deviations": [{
            "deviation_id": "dev-1",
            "stage": "analysis",
            "frozen_commitment": "Use the registered solver tolerance.",
            "actual_method": "Used a looser tolerance after convergence failed.",
            "reason": "The registered tolerance did not converge.",
            "timing": "after_results_seen",
            "potential_impact": "potentially_material",
            "corrective_action": "Repeat both tolerances and report all results.",
            "evidence_sha256": "c" * 64,
            "evidence_location": "/solver/tolerance",
        }],
    }
    unrelated = json.loads(json.dumps(disclosure))
    unrelated["deviations"][0]["evidence_sha256"] = "d" * 64
    with pytest.raises(ValidationError, match="must reference a run output artifact"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            metadata={"protocol_deviation_disclosure": unrelated},
        ))
    run = service.record_run(run_command(
        protocol.protocol_id,
        QualityGateStatus.PASSED,
        metadata={"protocol_deviation_disclosure": disclosure},
    ))
    assert run.status is RunStatus.COMPLETED
    assert run.scientific_evidence_eligible is False
    assert run.metadata["protocol_deviation_disclosure"]["deviations"] == disclosure["deviations"]
    assert any(
        finding.code == "RUN_PROTOCOL_DEVIATIONS_DECLARED"
        for finding in service.audit_rigor().findings
    )
    synthesis = service.build_synthesis()["content"]
    assert "deviation-restricted run" in synthesis
    assert "potential impact: potentially_material" in synthesis


def test_ineligible_run_with_retained_artifact_receipt_replays_on_read(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output = tmp_path / "proof-output.json"
    output.write_text('{"checker":"passed","deviation":"declared"}\n', encoding="utf-8")
    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    disclosure = {
        "status": "deviations_declared",
        "deviations": [{
            "deviation_id": "dev-artifact-retained",
            "stage": "analysis",
            "frozen_commitment": "Use the registered solver tolerance.",
            "actual_method": "Used a looser tolerance after convergence failed.",
            "reason": "The registered tolerance did not converge.",
            "timing": "after_results_seen",
            "potential_impact": "potentially_material",
            "corrective_action": "Repeat both tolerances and report all results.",
            "evidence_sha256": output_sha256,
            "evidence_location": "/deviation",
        }],
    }
    run = service.record_run(run_command(
        protocol.protocol_id,
        QualityGateStatus.PASSED,
        artifact_root=str(tmp_path),
        output_artifacts=[DatasetArtifact(
            output.name,
            output_sha256,
            output.stat().st_size,
            "application/json",
        )],
        quality_gates=[QualityGateResult(
            "proof-check",
            QualityGateStatus.PASSED,
            "Independent proof-checker result.",
            details={"evidence_sha256": output_sha256},
        )],
        metadata={"protocol_deviation_disclosure": disclosure},
    ))

    assert run.scientific_evidence_eligible is False
    assert run.metadata["artifact_integrity"]["status"] == "passed"
    service.show_inquiry()

    output.write_text('{"checker":"changed","deviation":"declared"}\n', encoding="utf-8")
    with pytest.raises(ValidationError, match="ARTIFACT_HASH_MISMATCH"):
        service.show_inquiry()
    with pytest.raises(ValidationError, match="ARTIFACT_HASH_MISMATCH"):
        service.audit_rigor()


def test_gate_passing_run_without_artifact_verification_is_reported_ineligible(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)

    run = service.record_run(
        run_command(protocol.protocol_id, QualityGateStatus.PASSED)
    )

    assert run.status is RunStatus.COMPLETED
    assert run.scientific_evidence_eligible is False
    assert run.metadata["artifact_integrity_missing_for_evidence"] is True

    findings = service.audit_rigor().findings
    assert any(
        finding.code == "RUN_ARTIFACT_INTEGRITY_MISSING_FOR_EVIDENCE"
        and finding.entity_id == run.run_id
        for finding in findings
    )
    synthesis = service.build_synthesis()["content"]
    assert "local output bytes were not machine-verified" in synthesis
    assert "declared hashes and passed gates are insufficient" in synthesis


def test_domain_neutral_protocol_run_and_evidence_chain(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    output = tmp_path / "proof-output.json"
    output.write_text('{"checker":"passed"}\n', encoding="utf-8")
    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()

    run = service.record_run(
        run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=[DatasetArtifact(
                output.name,
                output_sha256,
                output.stat().st_size,
                "application/json",
            )],
            quality_gates=[QualityGateResult(
                "proof-check",
                QualityGateStatus.PASSED,
                "Independent proof-checker result.",
                details={"evidence_sha256": output_sha256},
            )],
        )
    )
    evidence_command = RecordEvidence(
            hypothesis_id=hypothesis_id,
            direction=EvidenceDirection.SUPPORTS,
            summary="The registered checker accepted the proof object.",
            analysis_id="",
            run_id=run.run_id,
            uncertainty="Bounded to the pinned formal system and checker implementation.",
            scope="The registered invariant in the frozen bounded proof system.",
            controls_passed=["The deliberately invalid derivation was rejected."],
            higher_level_conclusions_unsupported=[
                "The candidate is empirically correct.",
                "The result has been independently replicated.",
            ],
            validation_tags=[
                ValidationTag.INTERNAL_CONSISTENCY,
                ValidationTag.CONTROLLED_BENCHMARK,
            ],
            exploratory=False,
        )
    evidence = service.record_evidence(evidence_command)

    assert protocol.protocol_kind is ProtocolKind.FORMAL
    assert run.status is RunStatus.COMPLETED
    assert run.scientific_evidence_eligible is True
    assert evidence.dataset_id is None
    assert evidence.protocol_id == protocol.protocol_id
    assert evidence.run_id == run.run_id
    assert evidence.scientific_evidence_eligible is True
    assert evidence.admission_checks["dataset_current_bytes_status"] == "not_applicable"
    assert evidence.admission_checks["run_output_current_bytes_verified"] is True
    assert evidence.admission_checks["protocol_hash"] == protocol.protocol_hash

    run_path = tmp_path / "inquiries" / "formal" / "runs" / f"{run.run_id}.json"
    run_bytes = run_path.read_bytes()
    forged_run = json.loads(run_bytes)
    forged_run["quality_gates"][0]["summary"] = "A substituted gate interpretation."
    run_path.write_text(json.dumps(forged_run), encoding="utf-8")
    with pytest.raises(ValidationError, match="run .* payload"):
        service.show_inquiry()
    run_path.write_bytes(run_bytes)

    evidence_path = (
        tmp_path / "inquiries" / "formal" / "evidence" / f"{evidence.evidence_id}.json"
    )
    evidence_bytes = evidence_path.read_bytes()
    forged = json.loads(evidence_bytes)
    forged["summary"] = "A stronger conclusion inserted after admission."
    evidence_path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(ValidationError, match="admission receipt"):
        service.show_inquiry()
    evidence_path.write_bytes(evidence_bytes)

    output.write_text('{"checker":"changed"}\n', encoding="utf-8")
    with pytest.raises(ValidationError, match="HASH_MISMATCH"):
        service.record_evidence(evidence_command)
    with pytest.raises(ValidationError, match="HASH_MISMATCH"):
        service.build_synthesis()


def test_frozen_protocol_binds_hypothesis_science_but_allows_lifecycle_change(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    assert set(protocol.hypothesis_commitments) == {hypothesis_id}

    service.retire_hypothesis(RetireHypothesis(
        hypothesis_id=hypothesis_id,
        rejection_type=RejectionType.WEAKENED,
        reason="Later evidence weakened the hypothesis without rewriting it.",
        limitations="This does not determine whether revised scope conditions could still hold.",
        resurrection_conditions=[
            "Reconsider if a future protocol directly tests the revised scope."
        ],
    ))
    service.show_inquiry()

    hypothesis_path = (
        tmp_path
        / "inquiries"
        / "formal"
        / "hypotheses"
        / "retired"
        / f"{hypothesis_id}.json"
    )
    forged = json.loads(hypothesis_path.read_text())
    forged["observable_prediction"] = "A substituted prediction after protocol freeze."
    hypothesis_path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(ValidationError, match="scientific content"):
        service.show_inquiry()
    with pytest.raises(ValidationError, match="scientific content"):
        service.get_protocol(protocol.protocol_id)


def test_pending_review_allows_only_exploratory_work(tmp_path: Path) -> None:
    counter = iter(f"pending{index:02d}" for index in range(100))
    service = ResearchService(
        FileSystemRepository(tmp_path),
        actor="delegated-codex-review",
        clock=lambda: "2026-09-02T12:00:00Z",
        token=lambda: next(counter),
    )
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            "Pending review",
            "Can safe exploration continue before human ratification?",
            "pending-review",
        )
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="A revised composition rule removes the obstruction.",
            observable_prediction="The exploratory gate vector changes.",
            null_model="The gate vector is unchanged.",
            falsification_conditions=["A required gate still fails."],
        )
    )
    staged = service.stage_hypothesis(
        hypothesis.hypothesis_id,
        rationale=(
            "The proposal is complete, reversible, and paired with a null model."
        ),
        confidence="high",
    )
    assert staged.workflow_state.value == "pending_review"
    assert staged.activated_at is None
    assert staged.pending_review_by == "delegated-codex-review"

    confirmatory = service.create_protocol(
        CreateProtocol(
            experiment_id="protected-check",
            title="Protected check",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[hypothesis.hypothesis_id],
            primary_outcome="A protected formal verdict",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Replay a derivation.",
            quality_requirements=["proof-check"],
            controls=["A deliberately invalid derivation must fail."],
            expected_outputs=["Proof transcript"],
            success_conditions=["All proof steps pass."],
            environment_requirements=["Pinned checker"],
            sample_size_or_stopping_rule="One proof object and one invalid control.",
            failure_conditions=["Any proof step fails."],
            safety_constraints=["No physical intervention."],
            analysis_code_hash=CODE_HASH,
        )
    )
    with pytest.raises(ValidationError, match="only exploratory protocols"):
        service.freeze_protocol(confirmatory.protocol_id)

    exploratory = service.create_protocol(
        CreateProtocol(
            experiment_id="exploratory-check",
            title="Exploratory check",
            analysis_mode=AnalysisMode.EXPLORATORY,
            hypotheses_tested=[hypothesis.hypothesis_id],
            primary_outcome="An exploratory formal verdict",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Replay a derivation without confirmatory status.",
            quality_requirements=["proof-check"],
            controls=["A deliberately invalid derivation must fail."],
            expected_outputs=["Exploratory transcript"],
            success_conditions=["The exploratory steps are reproducible."],
            environment_requirements=["Pinned checker"],
            sample_size_or_stopping_rule="One proof object and one invalid control.",
            failure_conditions=["A step cannot be reconstructed."],
            safety_constraints=["Do not report this as confirmation."],
            analysis_code_hash=CODE_HASH,
        )
    )
    frozen = service.freeze_protocol(exploratory.protocol_id)
    assert frozen.status.value == "frozen"

    dataset = service.register_dataset(
        RegisterDataset(
            dataset_id="exploratory-corpus",
            name="Exploratory corpus",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("corpus.md", "d" * 64)],
        )
    )
    evidence = service.record_evidence(
        RecordEvidence(
            hypothesis_id=hypothesis.hypothesis_id,
            direction=EvidenceDirection.INCONCLUSIVE,
            summary="The exploratory corpus does not settle the mechanism.",
            analysis_id="pending-review-analysis",
            dataset_id=dataset.dataset_id,
            uncertainty="The corpus is exploratory and was not independently replicated.",
            scope="The registered exploratory corpus only.",
            higher_level_conclusions_unsupported=[
                "The proposed mechanism is established."
            ],
            validation_tags=[ValidationTag.SOURCE_ASSESSMENT],
            exploratory=True,
        )
    )
    assert evidence.exploratory is True
    assert evidence.scientific_evidence_eligible is False

    with pytest.raises(ValidationError, match="confirmatory evidence"):
        service.record_evidence(
            RecordEvidence(
                hypothesis_id=hypothesis.hypothesis_id,
                direction=EvidenceDirection.SUPPORTS,
                summary="This must not cross the review boundary.",
                analysis_id="",
                exploratory=False,
            )
        )

    report = service.build_synthesis()["content"]
    assert "Pending human review" in report
    assert "provisionally staged for exploratory work" in report
    assert "Pending human review: 1" in report
    assert "The exploratory corpus does not settle the mechanism." in report
    assert "[exploratory; inconclusive]" in report


def test_failed_gate_and_synthetic_run_cannot_be_confirmatory_evidence(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)

    with pytest.raises(ValidationError, match="random_seed_reveal"):
        service.record_run(
            run_command(
                protocol.protocol_id,
                QualityGateStatus.PASSED,
                random_seed_reveal="wrong-seed",
            )
        )

    failed = service.record_run(
        run_command(
            protocol.protocol_id,
            QualityGateStatus.FAILED,
            run_id="run-failed",
        )
    )
    synthetic = service.record_run(
        run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            run_id="run-synthetic",
            synthetic=True,
        )
    )

    assert failed.status is RunStatus.INVALID
    assert failed.scientific_evidence_eligible is False
    assert synthetic.status is RunStatus.COMPLETED
    assert synthetic.scientific_evidence_eligible is False
    for run in (failed, synthetic):
        with pytest.raises(ValidationError, match="not eligible"):
            service.record_evidence(
                RecordEvidence(
                    hypothesis_id=hypothesis_id,
                    direction=EvidenceDirection.INCONCLUSIVE,
                    summary="This result must not cross the evidence gate.",
                    analysis_id="",
                    run_id=run.run_id,
                    exploratory=False,
                )
            )


def test_run_preflight_predicts_status_without_writing_state(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    before = service.verify_ledger("formal")

    output = tmp_path / "proof-output.json"
    output.write_text('{"checker":"passed"}\n', encoding="utf-8")
    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    report = service.preflight_run(
        run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=[DatasetArtifact(
                output.name, output_sha256, output.stat().st_size, "application/json"
            )],
            quality_gates=[QualityGateResult(
                "proof-check", QualityGateStatus.PASSED,
                "Independent proof-checker result.",
                details={"evidence_sha256": output_sha256},
            )],
        ),
        "formal",
    )

    after = service.verify_ledger("formal")
    assert report.status == "ready"
    assert report.would_append_event is False
    assert report.record_status_if_submitted is RunStatus.COMPLETED
    assert report.requested_run_id_conflicts is False
    assert report.scientific_evidence_eligible_if_submitted is True
    assert report.required_quality_gate_ids == ["proof-check"]
    assert report.provided_quality_gate_ids == ["proof-check"]
    assert report.missing_quality_gate_ids == []
    assert report.unexpected_quality_gate_ids == []
    assert report.exact_quality_gate_set is True
    assert report.quality_gate_order_matches_protocol is True
    unverified = service.preflight_run(
        run_command(protocol.protocol_id, QualityGateStatus.PASSED), "formal"
    )
    assert unverified.status == "ready"
    assert unverified.artifact_integrity is None
    assert unverified.scientific_evidence_eligible_if_submitted is False
    assert before == after
    assert service.list_runs("formal") == []


def test_run_preflight_predicts_explicit_run_id_conflict(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    command = run_command(
        protocol.protocol_id,
        QualityGateStatus.PASSED,
        run_id="run-already-recorded",
    )
    service.record_run(command, "formal")
    before = service.verify_ledger("formal")

    report = service.preflight_run(command, "formal")

    assert report.status == "would_reject"
    assert report.requested_run_id == "run-already-recorded"
    assert report.requested_run_id_conflicts is True
    assert report.record_status_if_submitted is None
    assert report.scientific_evidence_eligible_if_submitted is None
    assert service.verify_ledger("formal") == before
    assert len(service.list_runs("formal")) == 1


def test_run_preflight_exposes_label_mismatch_before_invalid_append(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    mismatched = run_command(
        protocol.protocol_id,
        QualityGateStatus.PASSED,
        quality_gates=[
            QualityGateResult(
                gate_id="accurate human paraphrase",
                status=QualityGateStatus.PASSED,
                summary="The proof check passed under a shortened label.",
                details={"evidence_sha256": "c" * 64},
            )
        ],
    )

    report = service.preflight_run(mismatched, "formal")

    assert report.status == "would_record_invalid"
    assert report.record_status_if_submitted is RunStatus.INVALID
    assert report.missing_quality_gate_ids == ["proof-check"]
    assert report.unexpected_quality_gate_ids == ["accurate human paraphrase"]
    assert report.exact_quality_gate_set is False
    assert report.quality_gate_order_matches_protocol is False
    assert service.list_runs("formal") == []


def test_run_preflight_reports_failed_gate_and_synthetic_ceiling(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)

    failed = service.preflight_run(
        run_command(protocol.protocol_id, QualityGateStatus.FAILED), "formal"
    )
    synthetic = service.preflight_run(
        run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
        ),
        "formal",
    )

    assert failed.failed_required_gate_ids == ["proof-check"]
    assert failed.failed_protocol_gate_ids == ["proof-check"]
    assert failed.record_status_if_submitted is RunStatus.INVALID
    assert synthetic.status == "ready"
    assert synthetic.record_status_if_submitted is RunStatus.COMPLETED
    assert synthetic.synthetic_if_submitted is True
    assert synthetic.scientific_evidence_eligible_if_submitted is False
    assert service.list_runs("formal") == []


def test_run_record_template_preserves_frozen_gate_order_and_is_not_submittable(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    before = service.verify_ledger("formal")

    template = service.run_record_template(protocol.protocol_id, "formal")

    assert template["template_only"] is True
    assert template["would_append_event"] is False
    assert template["protocol_hash"] == protocol.protocol_hash
    assert template["record"]["analysis_code_hash"] == CODE_HASH
    assert template["record"]["environment_hash"].startswith("<")
    assert template["record"]["output_artifacts"] == []
    assert template["record"]["quality_gates"] == [
        {
            "gate_id": "proof-check",
            "status": "skipped",
            "summary": "<replace with the observed gate result>",
            "required": True,
            "details": {
                "evidence_sha256": "<hash of a listed run output artifact>",
                "prerequisite_gate_ids": [],
            },
        }
    ]
    assert service.verify_ledger("formal") == before
    assert service.list_runs("formal") == []


def test_run_record_template_exposes_hash_bound_preprocessing_contract(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(
        service,
        hypothesis_id,
        preprocessing_pipeline="1" * 64,
    )

    template = service.run_record_template(protocol.protocol_id, "formal")

    assert template["preprocessing_pipeline_commitment_sha256"] == "1" * 64
    conformance = template["record"]["quality_gates"][0]["details"][
        "preprocessing_conformance"
    ]
    assert conformance["registered_pipeline_sha256"] == "1" * 64
    assert "observed preprocessing pipeline" in conformance[
        "observed_pipeline_sha256"
    ]


def test_hash_bound_preprocessing_pipeline_requires_conformance_gate_for_run_completion(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(
        service,
        hypothesis_id,
        preprocessing_pipeline="1" * 64,
    )

    run = service.record_run(run_command(protocol.protocol_id, QualityGateStatus.PASSED))

    assert run.status is RunStatus.INVALID
    assert run.scientific_evidence_eligible is False
    assert run.metadata["preprocessing_conformance_missing"] is True


def test_canary_target_plan_shapes_template_run_intake_and_synthesis(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    plan = CanaryTargetPlan(
        plan_id="masked-canary-plan",
        candidate_target_ids=["actual-state", "delayed-replay", "silent-marker"],
        seed_commitment_sha256="1" * 64,
        assignment_artifact_sha256="2" * 64,
        masking_plan="A custodian withholds the selected target until analysis lock.",
        ethical_disclosure="Participants consent to masked target conditions.",
        assessment_gate_id="canary-target-assessed",
    )
    protocol = frozen_formal_protocol(
        service, hypothesis_id, canary_target_plan=plan
    )

    template = service.run_record_template(protocol.protocol_id, "formal")

    assert template["canary_target_plan"] == plan.to_dict()
    canary_template = template["record"]["quality_gates"][1]["details"][
        "canary_target_assessment"
    ]
    assert canary_template["plan_id"] == "masked-canary-plan"
    assert canary_template["assignment_artifact_sha256"] == "2" * 64
    proof_output = tmp_path / "proof-output.json"
    proof_sha256 = _write_json_artifact(proof_output, {"proof": {"status": "passed"}})
    canary_output = tmp_path / "canary-output.json"
    canary_value = {
        "revealed_target_id": "actual-state",
        "status": "follows_comparator_or_decoy",
    }
    canary_sha256 = _write_json_artifact(
        canary_output,
        {"canary": {"comparison": canary_value}},
    )
    selected_value_sha256 = hashlib.sha256(
        (json.dumps(
            canary_value,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        ) + "\n").encode()
    ).hexdigest()

    run = service.record_run(
        run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=[
                DatasetArtifact(
                    proof_output.name,
                    proof_sha256,
                    size_bytes=proof_output.stat().st_size,
                    media_type="application/json",
                ),
                DatasetArtifact(
                    canary_output.name,
                    canary_sha256,
                    size_bytes=canary_output.stat().st_size,
                    media_type="application/json",
                ),
            ],
            quality_gates=[
                QualityGateResult(
                    gate_id="proof-check",
                    status=QualityGateStatus.PASSED,
                    summary="Independent proof-checker result.",
                    details={"evidence_sha256": proof_sha256},
                ),
                QualityGateResult(
                    gate_id="canary-target-assessed",
                    status=QualityGateStatus.FAILED,
                    summary="Canary target comparison was performed.",
                    details={
                        "evidence_sha256": canary_sha256,
                        "canary_target_assessment": {
                            "plan_id": "masked-canary-plan",
                            "assignment_artifact_sha256": "2" * 64,
                            "revealed_target_id": "actual-state",
                            "comparator_target_ids": ["delayed-replay"],
                            "assessment_status": "follows_comparator_or_decoy",
                            "observed_pattern": "Events followed the delayed replay stream.",
                            "interpretation": "This weakens target-specific adaptation under this protocol.",
                            "evidence_sha256": canary_sha256,
                            "evidence_location": "/canary/comparison",
                        },
                    },
                ),
            ],
        ),
        "formal",
    )

    assert run.status is RunStatus.INVALID
    assert run.scientific_evidence_eligible is False
    retained = run.quality_gates[1].details["canary_target_assessment"]
    assert retained["selected_value_sha256"] == selected_value_sha256
    synthesis = service.build_synthesis("formal")["content"]
    assert "Canary target provenance" in synthesis
    assert "follows_comparator_or_decoy" in synthesis
    assert selected_value_sha256 in synthesis
    assert "not proof of adaptation, mechanism, attribution, or intent" in synthesis
    assert any(
        finding.code == "RUN_CANARY_TARGET_FOLLOWED_COMPARATOR"
        for finding in service.audit_rigor("formal").findings
    )


def test_run_rejects_passed_canary_gate_for_comparator_or_decoy_result(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    plan = CanaryTargetPlan(
        plan_id="masked-canary-plan",
        candidate_target_ids=["actual-state", "delayed-replay"],
        seed_commitment_sha256="1" * 64,
        assignment_artifact_sha256="2" * 64,
        masking_plan="Hold the selected target until analysis lock.",
        ethical_disclosure="Masked target conditions are disclosed in consent.",
        assessment_gate_id="canary-target-assessed",
    )
    protocol = frozen_formal_protocol(
        service, hypothesis_id, canary_target_plan=plan
    )
    proof_output = tmp_path / "proof-output.json"
    proof_sha256 = _write_json_artifact(proof_output, {"proof": {"status": "passed"}})
    canary_output = tmp_path / "canary-output.json"
    canary_sha256 = _write_json_artifact(
        canary_output,
        {"canary": {"comparison": {"status": "follows_comparator_or_decoy"}}},
    )

    with pytest.raises(ValidationError, match="passed canary assessment gate"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=[
                DatasetArtifact(
                    proof_output.name,
                    proof_sha256,
                    size_bytes=proof_output.stat().st_size,
                    media_type="application/json",
                ),
                DatasetArtifact(
                    canary_output.name,
                    canary_sha256,
                    size_bytes=canary_output.stat().st_size,
                    media_type="application/json",
                ),
            ],
            quality_gates=[
                QualityGateResult(
                    gate_id="proof-check",
                    status=QualityGateStatus.PASSED,
                    summary="Independent proof-checker result.",
                    details={"evidence_sha256": proof_sha256},
                ),
                QualityGateResult(
                    gate_id="canary-target-assessed",
                    status=QualityGateStatus.PASSED,
                    summary="Canary target comparison was performed.",
                    details={
                        "evidence_sha256": canary_sha256,
                        "canary_target_assessment": {
                            "plan_id": "masked-canary-plan",
                            "assignment_artifact_sha256": "2" * 64,
                            "revealed_target_id": "actual-state",
                            "comparator_target_ids": ["delayed-replay"],
                            "assessment_status": "follows_comparator_or_decoy",
                            "observed_pattern": "Events followed the delayed replay stream.",
                            "interpretation": "This weakens target-specific adaptation under this protocol.",
                            "evidence_sha256": canary_sha256,
                            "evidence_location": "/canary/comparison",
                        },
                    },
                ),
            ],
        ))


@pytest.mark.parametrize(
    ("field_name", "field_value", "message"),
    [
        (
            "observed_pattern",
            "This confirmed adaptation.",
            "observed_pattern uses report-prohibited overclaiming language",
        ),
        (
            "interpretation",
            "This proved the mechanism.",
            "interpretation uses report-prohibited overclaiming language",
        ),
    ],
)
def test_run_rejects_canary_assessment_overclaiming_prose(
    tmp_path: Path,
    field_name: str,
    field_value: str,
    message: str,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    plan = CanaryTargetPlan(
        plan_id="masked-canary-plan",
        candidate_target_ids=["actual-state", "delayed-replay"],
        seed_commitment_sha256="1" * 64,
        assignment_artifact_sha256="2" * 64,
        masking_plan="Hold the selected target until analysis lock.",
        ethical_disclosure="Masked target conditions are disclosed in consent.",
        assessment_gate_id="canary-target-assessed",
    )
    protocol = frozen_formal_protocol(
        service, hypothesis_id, canary_target_plan=plan
    )
    proof_output = tmp_path / "proof-output.json"
    proof_sha256 = _write_json_artifact(proof_output, {"proof": {"status": "passed"}})
    canary_output = tmp_path / "canary-output.json"
    canary_sha256 = _write_json_artifact(
        canary_output,
        {
            "canary": {
                "comparison": {
                    "revealed_target_id": "actual-state",
                    "status": "consistent_with_revealed_target",
                }
            }
        },
    )
    assessment = {
        "plan_id": "masked-canary-plan",
        "assignment_artifact_sha256": "2" * 64,
        "revealed_target_id": "actual-state",
        "comparator_target_ids": ["delayed-replay"],
        "assessment_status": "consistent_with_revealed_target",
        "observed_pattern": "Events followed the revealed target.",
        "interpretation": "Bounded canary result only.",
        "evidence_sha256": canary_sha256,
        "evidence_location": "/canary/comparison",
    }
    assessment[field_name] = field_value

    with pytest.raises(ValidationError, match=message):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=[
                DatasetArtifact(
                    proof_output.name,
                    proof_sha256,
                    size_bytes=proof_output.stat().st_size,
                    media_type="application/json",
                ),
                DatasetArtifact(
                    canary_output.name,
                    canary_sha256,
                    size_bytes=canary_output.stat().st_size,
                    media_type="application/json",
                ),
            ],
            quality_gates=[
                QualityGateResult(
                    gate_id="proof-check",
                    status=QualityGateStatus.PASSED,
                    summary="Independent proof-checker result.",
                    details={"evidence_sha256": proof_sha256},
                ),
                QualityGateResult(
                    gate_id="canary-target-assessed",
                    status=QualityGateStatus.PASSED,
                    summary="Canary target comparison was performed.",
                    details={
                        "evidence_sha256": canary_sha256,
                        "canary_target_assessment": assessment,
                    },
                ),
            ],
        ))


def test_run_rejects_canary_selected_value_digest_drift(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    plan = CanaryTargetPlan(
        plan_id="masked-canary-plan",
        candidate_target_ids=["actual-state", "delayed-replay"],
        seed_commitment_sha256="1" * 64,
        assignment_artifact_sha256="2" * 64,
        masking_plan="Hold the selected target until analysis lock.",
        ethical_disclosure="Masked target conditions are disclosed in consent.",
        assessment_gate_id="canary-target-assessed",
    )
    protocol = frozen_formal_protocol(
        service, hypothesis_id, canary_target_plan=plan
    )
    proof_output = tmp_path / "proof-output.json"
    proof_sha256 = _write_json_artifact(proof_output, {"proof": {"status": "passed"}})
    canary_output = tmp_path / "canary-output.json"
    canary_sha256 = _write_json_artifact(
        canary_output,
        {"canary": {"comparison": {"status": "consistent_with_revealed_target"}}},
    )

    with pytest.raises(ValidationError, match="selected_value_sha256"):
        service.record_run(run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=[
                DatasetArtifact(
                    proof_output.name,
                    proof_sha256,
                    size_bytes=proof_output.stat().st_size,
                    media_type="application/json",
                ),
                DatasetArtifact(
                    canary_output.name,
                    canary_sha256,
                    size_bytes=canary_output.stat().st_size,
                    media_type="application/json",
                ),
            ],
            quality_gates=[
                QualityGateResult(
                    gate_id="proof-check",
                    status=QualityGateStatus.PASSED,
                    summary="Independent proof-checker result.",
                    details={"evidence_sha256": proof_sha256},
                ),
                QualityGateResult(
                    gate_id="canary-target-assessed",
                    status=QualityGateStatus.PASSED,
                    summary="Canary target comparison was performed.",
                    details={
                        "evidence_sha256": canary_sha256,
                        "canary_target_assessment": {
                            "plan_id": "masked-canary-plan",
                            "assignment_artifact_sha256": "2" * 64,
                            "revealed_target_id": "actual-state",
                            "comparator_target_ids": ["delayed-replay"],
                            "assessment_status": "consistent_with_revealed_target",
                            "observed_pattern": "Events followed the revealed target.",
                            "interpretation": "Bounded canary result only.",
                            "evidence_sha256": canary_sha256,
                            "evidence_location": "/canary/comparison",
                            "selected_value_sha256": "0" * 64,
                        },
                    },
                ),
            ],
        ))


def test_performed_canary_gate_requires_structured_result(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    plan = CanaryTargetPlan(
        plan_id="masked-canary-plan",
        candidate_target_ids=["actual-state", "delayed-replay"],
        seed_commitment_sha256="1" * 64,
        assignment_artifact_sha256="2" * 64,
        masking_plan="Hold the selected target until analysis lock.",
        ethical_disclosure="Masked target conditions are disclosed in consent.",
        assessment_gate_id="canary-target-assessed",
    )
    protocol = frozen_formal_protocol(
        service, hypothesis_id, canary_target_plan=plan
    )

    with pytest.raises(ValidationError, match="structured canary_target_assessment"):
        service.preflight_run(
            run_command(
                protocol.protocol_id,
                QualityGateStatus.PASSED,
                quality_gates=[
                    QualityGateResult(
                        gate_id="proof-check",
                        status=QualityGateStatus.PASSED,
                        summary="Independent proof-checker result.",
                        details={"evidence_sha256": "c" * 64},
                    ),
                    QualityGateResult(
                        gate_id="canary-target-assessed",
                        status=QualityGateStatus.PASSED,
                        summary="Canary result summarized without structure.",
                        details={"evidence_sha256": "c" * 64},
                    ),
                ],
            ),
            "formal",
        )


def test_next_action_selection_excludes_unsafe_options_and_is_auditable(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    candidates = [
        next_action_candidate(
            action_id="unsafe-high-score",
            title="Unsafe intervention",
            distinguishes_hypotheses=[hypothesis_id],
            hypothesis_discrimination_targets=[
                action_discrimination_target(hypothesis_id)
            ],
            expected_discrimination=1.0,
            uncertainty_reduction=1.0,
            cost=0.0,
            burden=0.0,
            safety_risk=0.0,
            ambiguity_risk=0.0,
            rationale="Would score highly, but lacks approval.",
            safety_approved=False,
        ),
        next_action_candidate(
            action_id="cheap-ambiguous",
            title="Cheap but ambiguous check",
            distinguishes_hypotheses=[hypothesis_id],
            hypothesis_discrimination_targets=[
                action_discrimination_target(hypothesis_id)
            ],
            expected_discrimination=0.4,
            uncertainty_reduction=0.3,
            cost=0.1,
            burden=0.1,
            safety_risk=0.0,
            ambiguity_risk=0.8,
            rationale="Low cost but difficult to interpret.",
        ),
        next_action_candidate(
            action_id="decisive-proof-check",
            title="Independent proof check",
            distinguishes_hypotheses=[hypothesis_id],
            hypothesis_discrimination_targets=[
                action_discrimination_target(hypothesis_id)
            ],
            expected_discrimination=0.9,
            uncertainty_reduction=0.8,
            cost=0.2,
            burden=0.1,
            safety_risk=0.0,
            ambiguity_risk=0.1,
            rationale="Directly tests the registered derivation.",
        ),
    ]

    recommendation = service.recommend_next_action(
        RecommendNextAction(candidates=candidates)
    )

    assert recommendation.selected_action_id == "decisive-proof-check"
    assert len(recommendation.recommendation_payload_sha256) == 64
    assert [score.action_id for score in recommendation.ranked_scores] == [
        "decisive-proof-check",
        "cheap-ambiguous",
    ]
    assert recommendation.ranked_scores[0].weighted_components == {
        "expected_discrimination": 0.9,
        "uncertainty_reduction": 0.4,
        "cost_penalty": -0.05,
        "burden_penalty": -0.035,
        "safety_risk_penalty": -0.0,
        "ambiguity_risk_penalty": -0.075,
    }
    assert recommendation.ranked_scores[0].utility == 1.14
    selected_candidate = next(
        candidate
        for candidate in recommendation.candidates
        if candidate.action_id == "decisive-proof-check"
    )
    assert selected_candidate.hypothesis_workflow_states == {
        hypothesis_id: "active"
    }
    assert service.list_recommendations() == [recommendation]
    synthesis = service.build_synthesis()["content"]
    assert "Utility components: utility 1.14" in synthesis
    assert "expected_discrimination 0.9" in synthesis
    assert "ambiguity_risk_penalty -0.075" in synthesis
    assert "Discrimination targets: " in synthesis
    assert f"{hypothesis_id} [active]: A separately implemented checker" in synthesis
    assert (
        "Payload commitment: " + recommendation.recommendation_payload_sha256
        in synthesis
    )

    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["candidates"][0]["hypothesis_discrimination_targets"][0][
        "would_weaken_if"
    ] = "A canonical rewrite after seeing the recommendation."
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ValidationError,
        match="payload no longer matches its service-generated commitment",
    ):
        service.list_recommendations()


def test_next_action_selection_handles_must_be_canonical(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)

    with pytest.raises(
        ValidationError, match="distinguishes_hypotheses item must be canonical"
    ):
        service.recommend_next_action(
            RecommendNextAction(
                candidates=[
                    next_action_candidate(
                        action_id="padded-hypothesis",
                        title="Padded hypothesis",
                        distinguishes_hypotheses=[f" {hypothesis_id} "],
                        expected_discrimination=0.8,
                        uncertainty_reduction=0.7,
                        cost=0.1,
                        burden=0.1,
                        safety_risk=0.0,
                        ambiguity_risk=0.1,
                        rationale="Would otherwise silently normalize the target.",
                    )
                ]
            )
        )


def test_next_action_selection_rejects_dependent_single_actions(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)

    with pytest.raises(
        ValidationError,
        match="single next-action recommendations cannot rank dependent actions",
    ):
        service.recommend_next_action(
            RecommendNextAction(candidates=[
                next_action_candidate(
                    action_id="dependent-action",
                    title="Dependent action",
                    distinguishes_hypotheses=[hypothesis_id],
                    hypothesis_discrimination_targets=[
                        action_discrimination_target(hypothesis_id)
                    ],
                    expected_discrimination=0.8,
                    uncertainty_reduction=0.7,
                    cost=0.1,
                    burden=0.1,
                    safety_risk=0.0,
                    ambiguity_risk=0.1,
                    rationale="This action should wait for a prior step.",
                    depends_on=["prior-step"],
                )
            ])
        )


def test_next_action_selection_rejects_degenerate_utility_weights(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)

    with pytest.raises(
        ValidationError, match="at least one positive utility term"
    ):
        service.recommend_next_action(
            RecommendNextAction(
                candidates=[
                    next_action_candidate(
                        action_id="lexicographic-first",
                        title="Lexicographic first",
                        distinguishes_hypotheses=[hypothesis_id],
                        hypothesis_discrimination_targets=[
                            action_discrimination_target(hypothesis_id)
                        ],
                        expected_discrimination=0.1,
                        uncertainty_reduction=0.1,
                        cost=0.1,
                        burden=0.1,
                        safety_risk=0.0,
                        ambiguity_risk=0.1,
                        rationale="Would be selected only by identifier order.",
                    ),
                    next_action_candidate(
                        action_id="more-informative",
                        title="More informative",
                        distinguishes_hypotheses=[hypothesis_id],
                        hypothesis_discrimination_targets=[
                            action_discrimination_target(hypothesis_id)
                        ],
                        expected_discrimination=0.9,
                        uncertainty_reduction=0.8,
                        cost=0.1,
                        burden=0.1,
                        safety_risk=0.0,
                        ambiguity_risk=0.1,
                        rationale="Should win when utility weights are meaningful.",
                    ),
                ],
                weights=SelectionWeights(
                    expected_discrimination=0.0,
                    uncertainty_reduction=0.0,
                    cost=0.0,
                    burden=0.0,
                    safety_risk=0.0,
                    ambiguity_risk=0.0,
                ),
            )
        )


@pytest.mark.parametrize("weight_value", [float("nan"), float("inf")])
def test_next_action_selection_weights_must_be_finite(
    tmp_path: Path, weight_value: float
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)

    with pytest.raises(
        ValidationError,
        match="selection weight expected_discrimination must be a finite non-negative number",
    ):
        service.recommend_next_action(
            RecommendNextAction(
                candidates=[
                    next_action_candidate(
                        action_id="finite-score",
                        title="Finite score",
                        distinguishes_hypotheses=[hypothesis_id],
                        hypothesis_discrimination_targets=[
                            action_discrimination_target(hypothesis_id)
                        ],
                        expected_discrimination=0.8,
                        uncertainty_reduction=0.7,
                        cost=0.1,
                        burden=0.1,
                        safety_risk=0.0,
                        ambiguity_risk=0.1,
                        rationale="The candidate itself has bounded inputs.",
                    )
                ],
                weights=SelectionWeights(
                    expected_discrimination=weight_value,
                    uncertainty_reduction=0.5,
                ),
            )
        )


def test_next_action_selection_rejects_tied_top_utility(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)

    with pytest.raises(ValidationError, match="top action utility is tied"):
        service.recommend_next_action(
            RecommendNextAction(
                candidates=[
                    next_action_candidate(
                        action_id="alpha-action",
                        title="Alpha action",
                        distinguishes_hypotheses=[hypothesis_id],
                        hypothesis_discrimination_targets=[
                            action_discrimination_target(hypothesis_id)
                        ],
                        expected_discrimination=0.8,
                        uncertainty_reduction=0.6,
                        cost=0.1,
                        burden=0.1,
                        safety_risk=0.0,
                        ambiguity_risk=0.1,
                        rationale="One equally informative option.",
                    ),
                    next_action_candidate(
                        action_id="beta-action",
                        title="Beta action",
                        distinguishes_hypotheses=[hypothesis_id],
                        hypothesis_discrimination_targets=[
                            action_discrimination_target(hypothesis_id)
                        ],
                        expected_discrimination=0.8,
                        uncertainty_reduction=0.6,
                        cost=0.1,
                        burden=0.1,
                        safety_risk=0.0,
                        ambiguity_risk=0.1,
                        rationale="Another equally informative option.",
                    ),
                ]
            )
        )


def test_next_action_replay_rejects_legacy_candidate_without_target(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    service.recommend_next_action(
        RecommendNextAction(candidates=[
            next_action_candidate(
                action_id="targeted-action",
                title="Targeted action",
                distinguishes_hypotheses=[hypothesis_id],
                hypothesis_discrimination_targets=[
                    action_discrimination_target(hypothesis_id)
                ],
                expected_discrimination=0.8,
                uncertainty_reduction=0.6,
                cost=0.1,
                burden=0.1,
                safety_risk=0.0,
                ambiguity_risk=0.1,
                rationale="A valid targeted action before legacy mutation.",
            )
        ])
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["candidates"][0]["distinguishes_hypotheses"] = []
    payload["candidates"][0]["hypothesis_discrimination_targets"] = []
    payload["candidates"][0]["hypothesis_workflow_states"] = {}
    payload["candidates"][0]["information_targets"] = []
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="must distinguish at least one hypothesis or name at least one information target",
    ):
        service.list_recommendations()


def test_next_action_replay_rejects_legacy_duplicate_action_ids(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    service.recommend_next_action(
        RecommendNextAction(candidates=[
            next_action_candidate(
                action_id="first-action",
                title="First action",
                distinguishes_hypotheses=[hypothesis_id],
                hypothesis_discrimination_targets=[
                    action_discrimination_target(hypothesis_id)
                ],
                expected_discrimination=0.9,
                uncertainty_reduction=0.7,
                cost=0.1,
                burden=0.1,
                safety_risk=0.0,
                ambiguity_risk=0.1,
                rationale="The original selected action.",
            ),
            next_action_candidate(
                action_id="second-action",
                title="Second action",
                distinguishes_hypotheses=[hypothesis_id],
                hypothesis_discrimination_targets=[
                    action_discrimination_target(hypothesis_id)
                ],
                expected_discrimination=0.6,
                uncertainty_reduction=0.5,
                cost=0.1,
                burden=0.1,
                safety_risk=0.0,
                ambiguity_risk=0.1,
                rationale="A lower-ranked valid action.",
            ),
        ])
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["candidates"][1]["action_id"] = "first-action"
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="duplicate action_id"):
        service.list_recommendations()


def test_next_action_replay_rejects_legacy_single_portfolio_fields(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    service.recommend_next_action(
        RecommendNextAction(candidates=[
            next_action_candidate(
                action_id="single-action",
                title="Single action",
                distinguishes_hypotheses=[hypothesis_id],
                hypothesis_discrimination_targets=[
                    action_discrimination_target(hypothesis_id)
                ],
                expected_discrimination=0.8,
                uncertainty_reduction=0.6,
                cost=0.1,
                burden=0.1,
                safety_risk=0.0,
                ambiguity_risk=0.1,
                rationale="A valid single action before legacy mutation.",
            )
        ])
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["candidates"][0]["depends_on"] = ["previous-action"]
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="single-mode action single-action cannot retain depends_on",
    ):
        service.list_recommendations()


def test_synthetic_status_propagates_through_derived_datasets(tmp_path: Path) -> None:
    service, _ = prepared_service(tmp_path)
    source = service.register_dataset(
        RegisterDataset(
            dataset_id="ds-synthetic-source",
            name="Synthetic source",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("synthetic.json", "d" * 64)],
            synthetic=True,
        )
    )
    derived = service.register_dataset(
        RegisterDataset(
            dataset_id="ds-derived",
            name="Derived observations",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("derived.json", "e" * 64)],
            source_dataset_ids=[source.dataset_id],
            synthetic=False,
        )
    )

    assert derived.synthetic is True
