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
from research_machine.domain.models import (
    ActionCandidate,
    AnalysisMode,
    AnalysisContract,
    ClaimLevel,
    ConclusionContract,
    DatasetArtifact,
    DatasetRole,
    EvidenceDirection,
    Hypothesis,
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


def frozen_formal_protocol(service: ResearchService, hypothesis_id: str):
    protocol = service.create_protocol(
        CreateProtocol(
            experiment_id="formal-check-01",
            title="Check the invariant derivation",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[hypothesis_id],
            primary_outcome="Proof checker acceptance",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Construct a derivation and replay it in the proof checker.",
            quality_requirements=["proof-check"],
            controls=["Replay a deliberately invalid derivation."],
            expected_outputs=["Proof object", "Checker transcript"],
            success_conditions=["The independent checker accepts the proof object."],
            environment_requirements=["Pinned checker and axiom-set hashes"],
            sample_size_or_stopping_rule=(
                "One registered proof object and one fixed invalid control."
            ),
            failure_conditions=["The checker rejects any proof step."],
            safety_constraints=["No physical or human intervention is involved."],
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


def test_next_action_selection_excludes_unsafe_options_and_is_auditable(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    candidates = [
        ActionCandidate(
            action_id="unsafe-high-score",
            title="Unsafe intervention",
            distinguishes_hypotheses=[hypothesis_id],
            expected_discrimination=1.0,
            uncertainty_reduction=1.0,
            cost=0.0,
            burden=0.0,
            safety_risk=0.0,
            ambiguity_risk=0.0,
            rationale="Would score highly, but lacks approval.",
            safety_approved=False,
        ),
        ActionCandidate(
            action_id="cheap-ambiguous",
            title="Cheap but ambiguous check",
            distinguishes_hypotheses=[hypothesis_id],
            expected_discrimination=0.4,
            uncertainty_reduction=0.3,
            cost=0.1,
            burden=0.1,
            safety_risk=0.0,
            ambiguity_risk=0.8,
            rationale="Low cost but difficult to interpret.",
        ),
        ActionCandidate(
            action_id="decisive-proof-check",
            title="Independent proof check",
            distinguishes_hypotheses=[hypothesis_id],
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
    assert [score.action_id for score in recommendation.ranked_scores] == [
        "decisive-proof-check",
        "cheap-ambiguous",
    ]
    assert recommendation.candidates == candidates
    assert service.list_recommendations() == [recommendation]


def test_next_action_selection_handles_must_be_canonical(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)

    with pytest.raises(
        ValidationError, match="distinguishes_hypotheses item must be canonical"
    ):
        service.recommend_next_action(
            RecommendNextAction(
                candidates=[
                    ActionCandidate(
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
                    ActionCandidate(
                        action_id="lexicographic-first",
                        title="Lexicographic first",
                        distinguishes_hypotheses=[hypothesis_id],
                        expected_discrimination=0.1,
                        uncertainty_reduction=0.1,
                        cost=0.1,
                        burden=0.1,
                        safety_risk=0.0,
                        ambiguity_risk=0.1,
                        rationale="Would be selected only by identifier order.",
                    ),
                    ActionCandidate(
                        action_id="more-informative",
                        title="More informative",
                        distinguishes_hypotheses=[hypothesis_id],
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
                    ActionCandidate(
                        action_id="finite-score",
                        title="Finite score",
                        distinguishes_hypotheses=[hypothesis_id],
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
                    ActionCandidate(
                        action_id="alpha-action",
                        title="Alpha action",
                        distinguishes_hypotheses=[hypothesis_id],
                        expected_discrimination=0.8,
                        uncertainty_reduction=0.6,
                        cost=0.1,
                        burden=0.1,
                        safety_risk=0.0,
                        ambiguity_risk=0.1,
                        rationale="One equally informative option.",
                    ),
                    ActionCandidate(
                        action_id="beta-action",
                        title="Beta action",
                        distinguishes_hypotheses=[hypothesis_id],
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
