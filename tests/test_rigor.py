from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    CreateInquiry,
    CreateProtocol,
    ProposeHypothesis,
    RecordEvidence,
    RecordEvidenceStatusEvent,
    RecordRun,
)
from research_machine.application.service import ResearchService
from research_machine.application.rigor import audit_research_state
from research_machine.reporting.synthesis import build_synthesis
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisMode,
    DatasetArtifact,
    EvidenceDirection,
    MeasurementDefinition,
    MeasurementRole,
    ProtocolKind,
    QualityGateResult,
    QualityGateStatus,
    ValidationTag,
)


def _service(root: Path, *, actor: str = "author") -> ResearchService:
    counter = iter(f"{actor}{index:02d}" for index in range(100))
    return ResearchService(
        FileSystemRepository(root),
        actor=actor,
        clock=lambda: "2026-09-02T12:00:00Z",
        token=lambda: next(counter),
    )


def _prepared_run(root: Path):
    service = _service(root)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry("Rigor gate", "Can the result survive overclaim checks?", "rigor")
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The candidate preserves the registered invariant.",
            observable_prediction="The checker accepts the invariant.",
            null_model="The checker rejects the invariant.",
            falsification_conditions=["A required checker gate fails."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    draft = service.create_protocol(
        CreateProtocol(
            experiment_id="rigor-check",
            title="Controlled invariant check",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[hypothesis.hypothesis_id],
            primary_outcome="Checker acceptance",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Replay the candidate and a deliberately invalid control.",
            quality_requirements=["checker"],
            controls=["The deliberately invalid candidate must fail."],
            expected_outputs=["Checker transcript"],
            success_conditions=["The candidate passes and the control fails."],
            environment_requirements=["Pinned checker"],
            sample_size_or_stopping_rule="One candidate and one fixed negative control.",
            failure_conditions=["Any required assertion fails."],
            safety_constraints=["No physical intervention."],
            analysis_code_hash="a" * 64,
        )
    )
    protocol = service.freeze_protocol(draft.protocol_id)
    output = root / "result.json"
    output.write_text('{"checker":"passed"}\n', encoding="utf-8")
    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    run = service.record_run(
        RecordRun(
            protocol_id=protocol.protocol_id,
            started_at="2026-09-02T12:01:00Z",
            completed_at="2026-09-02T12:02:00Z",
            analysis_code_hash="a" * 64,
            environment_hash="b" * 64,
            output_artifacts=[DatasetArtifact(
                "result.json", output_sha256, output.stat().st_size,
                "application/json",
            )],
            artifact_root=str(root),
            quality_gates=[
                QualityGateResult(
                    gate_id="checker",
                    status=QualityGateStatus.PASSED,
                    summary="Candidate passed and invalid control failed.",
                    details={"evidence_sha256": output_sha256},
                )
            ],
            metadata={"protocol_deviation_disclosure": {
                "status": "no_deviations_declared", "deviations": [],
            }},
        )
    )
    return service, hypothesis, run


def test_rigor_reports_missed_precision_without_marking_run_invalid(tmp_path) -> None:
    service, hypothesis, run = _prepared_run(tmp_path)
    repository = service.repository
    inquiry_id = repository.resolve_inquiry_id(None)
    protocol = service.get_protocol(run.protocol_id)
    precision_protocol = replace(
        protocol, sample_size_plan={"strategy": "precision"},
    )
    observed_run = replace(run, metadata={
        **run.metadata,
        "sample_size_plan_check": {
            "status": "passed",
            "precision_achievement": {
                "status": "not_met", "target_half_width": 1.0,
                "observed_half_width": 1.5,
            },
            "attrition_achievement": {
                "status": "exceeded_assumption",
                "anticipated_attrition_fraction": 0.1,
                "observed_excluded_fraction": 0.15,
                "observed_excluded_fraction_by_group": {"a": 0.1, "b": 0.2},
            },
            "variance_assumption": {
                "status": "exceeded_registered_tolerance",
                "observed_to_assumed_ratio": 1.5,
                "maximum_registered_ratio": 1.25,
                "assumed_standard_deviation": 2.0,
                "observed_pooled_standard_deviation": 3.0,
                "measurement_unit": "fixture units",
                "adequacy_threshold_registered": True,
            },
        },
    })
    inquiry = repository.load_inquiry(inquiry_id)
    claims = repository.load_claims(inquiry_id)
    evidence = repository.list_evidence(inquiry_id)
    datasets = repository.list_datasets(inquiry_id)
    audit = audit_research_state(
        inquiry=inquiry, claims=claims,
        hypotheses=[hypothesis], evidence=evidence, datasets=datasets,
        protocols=[precision_protocol], runs=[observed_run],
    )
    finding = next(
        item for item in audit.findings
        if item.code == "RUN_PRECISION_TARGET_NOT_MET"
    )
    assert finding.entity_id == run.run_id
    assert "observed half-width 1.5 against target 1" in finding.remediation
    attrition_finding = next(
        item for item in audit.findings
        if item.code == "RUN_ATTRITION_EXCEEDED_PLANNING_ASSUMPTION"
    )
    assert "observed excluded fraction 0.15 against anticipated 0.1" in attrition_finding.remediation
    variance_finding = next(
        item for item in audit.findings
        if item.code == "RUN_VARIANCE_EXCEEDED_REGISTERED_TOLERANCE"
    )
    assert "ratio 1.5 against registered maximum 1.25" in variance_finding.remediation
    assert observed_run.status.value == "completed"
    assert observed_run.scientific_evidence_eligible is True
    synthesis = build_synthesis(
        inquiry, [], claims, [hypothesis], evidence, datasets,
        [precision_protocol], [observed_run], [], [], audit, [],
    )
    assert "Precision target: not_met; target half-width 1.0" in synthesis
    assert "evidence eligible: yes" in synthesis
    assert "A missed target does not erase the result or imply invalidity." in synthesis
    assert "Attrition assumption: exceeded_assumption" in synthesis
    assert "Variability assumption: exceeded_registered_tolerance" in synthesis
    assert "Registered maximum ratio 1.25." in synthesis
    assert "a planning miss does not erase the result or imply invalidity." in synthesis


def _classified_evidence(hypothesis_id: str, run_id: str, **overrides):
    values = {
        "hypothesis_id": hypothesis_id,
        "direction": EvidenceDirection.SUPPORTS,
        "summary": "The registered controlled checker accepted the candidate.",
        "analysis_id": "",
        "run_id": run_id,
        "uncertainty": "Bounded to the pinned formal system and checker.",
        "scope": "The registered invariant only.",
        "controls_passed": ["The deliberately invalid candidate was rejected."],
        "higher_level_conclusions_unsupported": [
            "The candidate is empirically correct.",
            "The result is independently replicated.",
        ],
        "validation_tags": [
            ValidationTag.INTERNAL_CONSISTENCY,
            ValidationTag.CONTROLLED_BENCHMARK,
        ],
        "exploratory": False,
    }
    values.update(overrides)
    return RecordEvidence(**values)


def _status_command(
    evidence_id: str, root: Path, name: str, status: str, **overrides
) -> RecordEvidenceStatusEvent:
    artifact = root / name
    artifact.write_text(f"{status} review for {evidence_id}", encoding="utf-8")
    values = {
        "evidence_id": evidence_id,
        "status": status,
        "effective_at": "2026-09-02T12:00:00Z",
        "reason": f"Independent review classified this evidence as {status}.",
        "review_artifact_locator": name,
        "review_artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "review_artifact_root": str(root),
    }
    values.update(overrides)
    return RecordEvidenceStatusEvent(**values)


def test_append_only_retraction_removes_evidence_from_current_rigor_not_history(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path / "workspace")
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    assert service.audit_rigor().capabilities["controlled_benchmark"] is True
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    event = service.record_evidence_status_event(
        _status_command(evidence.evidence_id, review_root, "retraction.txt", "retracted")
    )
    assert event.sequence == 1
    assert service.list_evidence()[0].evidence_id == evidence.evidence_id
    synthesis = service.build_synthesis()["content"]
    assert "current status: retracted" in synthesis
    assert "Currently contributing evidence records: 0" in synthesis
    assert "Evidence correction and retraction history" in synthesis
    assert service.audit_rigor().capabilities["controlled_benchmark"] is False
    (review_root / "retraction.txt").write_text("review bytes changed", encoding="utf-8")
    with pytest.raises(ValidationError, match="no longer matches its integrity receipt"):
        service.build_synthesis()


def test_evidence_status_chain_requires_exact_predecessor_and_retraction_is_terminal(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path / "workspace")
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    qualified = service.record_evidence_status_event(
        _status_command(evidence.evidence_id, review_root, "qualified.txt", "qualified")
    )
    with pytest.raises(ValidationError, match="exact latest"):
        service.record_evidence_status_event(
            _status_command(evidence.evidence_id, review_root, "bad.txt", "active")
        )
    retracted = service.record_evidence_status_event(
        _status_command(
            evidence.evidence_id,
            review_root,
            "retracted.txt",
            "retracted",
            supersedes_event_id=qualified.event_id,
        )
    )
    assert retracted.sequence == 2
    with pytest.raises(ValidationError, match="terminal"):
        service.record_evidence_status_event(
            _status_command(
                evidence.evidence_id,
                review_root,
                "reinstate.txt",
                "active",
                supersedes_event_id=retracted.event_id,
            )
        )


def test_evidence_status_reads_fail_closed_on_semantic_chain_tampering(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    service, hypothesis, run = _prepared_run(workspace)
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    event = service.record_evidence_status_event(
        _status_command(evidence.evidence_id, review_root, "qualified.txt", "qualified")
    )
    event_file = next(workspace.rglob(f"{event.event_id}.json"))
    tampered = json.loads(event_file.read_text(encoding="utf-8"))
    tampered["sequence"] = 3
    event_file.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValidationError, match="contiguous from 1"):
        service.list_evidence_status_events()
    with pytest.raises(ValidationError, match="contiguous from 1"):
        service.audit_rigor()


def test_new_evidence_requires_scope_ceiling_and_classification(tmp_path: Path) -> None:
    service, hypothesis, run = _prepared_run(tmp_path)
    with pytest.raises(ValidationError, match="scope must not be empty"):
        service.record_evidence(
            RecordEvidence(
                hypothesis_id=hypothesis.hypothesis_id,
                direction=EvidenceDirection.INCONCLUSIVE,
                summary="An unscoped result must fail.",
                analysis_id="",
                run_id=run.run_id,
                exploratory=False,
            )
        )
    with pytest.raises(ValidationError, match="unclassified new evidence"):
        service.record_evidence(
            _classified_evidence(
                hypothesis.hypothesis_id,
                run.run_id,
                validation_tags=[],
            )
        )


def test_protocol_freeze_requires_controls_quality_gates_and_stop_rule(
    tmp_path: Path,
) -> None:
    service, hypothesis, _ = _prepared_run(tmp_path)
    draft = service.create_protocol(
        CreateProtocol(
            experiment_id="under-specified",
            title="Under-specified protocol",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[hypothesis.hypothesis_id],
            primary_outcome="An assertion",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Run one checker.",
            expected_outputs=["Output"],
            success_conditions=["The assertion passes."],
            environment_requirements=["Pinned checker"],
            failure_conditions=["The assertion fails."],
            safety_constraints=["No physical intervention."],
            analysis_code_hash="9" * 64,
        )
    )
    with pytest.raises(ValidationError) as captured:
        service.freeze_protocol(draft.protocol_id)
    message = str(captured.value)
    assert "quality_requirements" in message
    assert "controls" in message
    assert "sample_size_or_stopping_rule" in message


def test_typed_measurement_contract_rejects_omitted_control_time(
    tmp_path: Path,
) -> None:
    service, hypothesis, _ = _prepared_run(tmp_path)
    control = "The negative dissipator must violate complete positivity."

    def measurement(
        measurement_id: str,
        role: MeasurementRole,
        target: str,
        point: str,
    ) -> MeasurementDefinition:
        return MeasurementDefinition(
            measurement_id=measurement_id,
            role=role,
            registered_target=target,
            observable="minimum Choi eigenvalue",
            input_condition="fixed finite CQ generator",
            parameter_values={"t": "0.01 dimensionless"},
            evaluation_point=point,
            convention="column-vectorization Choi convention",
            aggregation="minimum over Hermitian eigenspectrum",
            tolerance="absolute error <= 1e-6",
            expected_behavior="negative for the malformed generator",
        )

    common = dict(
        title="Typed CQ control contract",
        analysis_mode=AnalysisMode.REPLICATION,
        hypotheses_tested=[hypothesis.hypothesis_id],
        primary_outcome="Main channel structural verdict",
        protocol_kind=ProtocolKind.COMPUTATIONAL,
        methodology="Evaluate the main channel and fixed malformed control.",
        quality_requirements=["contract-check"],
        controls=[control],
        expected_outputs=["Measurement packet"],
        success_conditions=["The fixed measurement contract is reproduced."],
        environment_requirements=["Pinned numerical environment"],
        sample_size_or_stopping_rule="Exactly one fixed evaluation.",
        failure_conditions=["Any registered measurement is omitted."],
        safety_constraints=["No physical intervention."],
        analysis_code_hash="8" * 64,
    )
    untyped = service.create_protocol(
        CreateProtocol(experiment_id="typed-cq-legacy", **common)
    )
    service.freeze_protocol(untyped.protocol_id)
    audit = service.audit_rigor()
    assert any(
        item.code == "PROTECTED_COMPUTATIONAL_MEASUREMENTS_UNTYPED"
        and item.entity_id == untyped.protocol_id
        for item in audit.findings
    )

    incomplete = service.create_protocol(
        CreateProtocol(
            experiment_id="typed-cq-incomplete",
            measurement_definitions=[
                measurement(
                    "main",
                    MeasurementRole.PRIMARY,
                    common["primary_outcome"],
                    "t=0.05",
                ),
                measurement("negative", MeasurementRole.CONTROL, control, ""),
            ],
            **common,
        )
    )
    with pytest.raises(ValidationError, match="evaluation_point"):
        service.freeze_protocol(incomplete.protocol_id)

    misaligned = service.create_protocol(
        CreateProtocol(
            experiment_id="typed-cq-misaligned",
            measurement_definitions=[
                measurement(
                    "main",
                    MeasurementRole.PRIMARY,
                    common["primary_outcome"],
                    "t=0.05",
                ),
                measurement(
                    "negative",
                    MeasurementRole.CONTROL,
                    "An unregistered control",
                    "t=0.01",
                ),
            ],
            **common,
        )
    )
    with pytest.raises(ValidationError, match="exactly one measurement"):
        service.freeze_protocol(misaligned.protocol_id)

    complete = service.create_protocol(
        CreateProtocol(
            experiment_id="typed-cq-complete",
            measurement_definitions=[
                measurement(
                    "main",
                    MeasurementRole.PRIMARY,
                    common["primary_outcome"],
                    "t=0.05",
                ),
                measurement("negative", MeasurementRole.CONTROL, control, "t=0.01"),
            ],
            **common,
        )
    )
    frozen = service.freeze_protocol(complete.protocol_id)
    assert frozen.measurement_definitions[1].evaluation_point == "t=0.01"
    reloaded = service.get_protocol(frozen.protocol_id)
    assert reloaded.measurement_definitions[0].role is MeasurementRole.PRIMARY


def test_advanced_tags_cannot_overstate_a_formal_self_check(tmp_path: Path) -> None:
    service, hypothesis, run = _prepared_run(tmp_path)
    with pytest.raises(ValidationError, match="replication-mode run"):
        service.record_evidence(
            _classified_evidence(
                hypothesis.hypothesis_id,
                run.run_id,
                validation_tags=[ValidationTag.INDEPENDENT_REPLICATION],
            )
        )
    with pytest.raises(ValidationError, match="observational or experimental"):
        service.record_evidence(
            _classified_evidence(
                hypothesis.hypothesis_id,
                run.run_id,
                validation_tags=[ValidationTag.EMPIRICAL_TEST],
            )
        )


def test_audit_and_synthesis_publish_a_conservative_ceiling(tmp_path: Path) -> None:
    service, hypothesis, run = _prepared_run(tmp_path)
    service.record_evidence(_classified_evidence(hypothesis.hypothesis_id, run.run_id))

    audit = service.audit_rigor(fail_on="error")
    assert audit.structurally_valid is True
    assert audit.conclusion_ceiling == "controlled but internally generated result"
    assert audit.capabilities["internal_consistency"] is True
    assert audit.capabilities["controlled_benchmark"] is True
    assert audit.capabilities["independent_replication"] is False
    assert any(
        finding.code == "CAPABILITY_INDEPENDENT_REPLICATION_ABSENT"
        for finding in audit.findings
    )
    with pytest.raises(ValidationError, match="rigor audit failed"):
        service.audit_rigor(fail_on="warning")

    synthesis = service.build_synthesis()["content"]
    assert "Epistemic rigor audit" in synthesis
    assert "controlled but internally generated result" in synthesis
    assert "independent_replication: absent" in synthesis


def test_retrospectively_amended_evidence_cannot_raise_prospective_ceiling(tmp_path: Path) -> None:
    service, hypothesis, predecessor_run = _prepared_run(tmp_path)
    predecessor = service.get_protocol(predecessor_run.protocol_id)
    values = {field.name: getattr(predecessor, field.name) for field in fields(CreateProtocol)}
    amendment = service.amend_protocol(
        predecessor.protocol_id, CreateProtocol(**values), "Changed after inspecting output",
        "after_analysis", "full_data_seen",
    )
    frozen = service.freeze_protocol(amendment.protocol_id)
    amended_output = tmp_path / "amended.json"
    amended_output.write_text('{"checker":"passed"}\n', encoding="utf-8")
    amended_sha256 = hashlib.sha256(amended_output.read_bytes()).hexdigest()
    run = service.record_run(RecordRun(
        protocol_id=frozen.protocol_id, started_at="2026-09-02T12:03:00Z",
        completed_at="2026-09-02T12:04:00Z", analysis_code_hash="a" * 64,
        environment_hash="b" * 64, output_artifacts=[DatasetArtifact(
            "amended.json", amended_sha256, amended_output.stat().st_size,
            "application/json",
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(gate_id="checker", status=QualityGateStatus.PASSED,
                                         summary="Amended checker passed.",
                                         details={"evidence_sha256": amended_sha256})],
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared", "deviations": [],
        }},
    ))
    service.record_evidence(_classified_evidence(hypothesis.hypothesis_id, run.run_id))
    audit = service.audit_rigor()
    assert audit.capabilities["controlled_benchmark"] is True
    assert audit.conclusion_ceiling == "retrospectively amended evidence only; prospective confirmation required"
    assert any(item.code == "EVIDENCE_FROM_RETROSPECTIVE_OR_EXPOSED_AMENDMENT"
               for item in audit.findings)


def test_independent_replication_requires_clean_room_attestation(
    tmp_path: Path,
) -> None:
    author, hypothesis, original = _prepared_run(tmp_path)
    draft = author.create_protocol(
        CreateProtocol(
            experiment_id="rigor-check-replication",
            title="Independent invariant replication",
            analysis_mode=AnalysisMode.REPLICATION,
            hypotheses_tested=[hypothesis.hypothesis_id],
            primary_outcome="Independent checker acceptance",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Reimplement the invariant check with a distinct checker.",
            quality_requirements=["replication-check"],
            controls=["The independent invalid candidate must fail."],
            expected_outputs=["Independent checker transcript"],
            success_conditions=["Independent reproduction passes."],
            environment_requirements=["Distinct pinned checker"],
            sample_size_or_stopping_rule="One original result and one replication.",
            failure_conditions=["The reproduction or its control fails."],
            safety_constraints=["No physical intervention."],
            analysis_code_hash="d" * 64,
        )
    )
    protocol = author.freeze_protocol(draft.protocol_id)
    replicator = _service(tmp_path, actor="replicator")
    incomplete_output = tmp_path / "replication.json"
    incomplete_output.write_text('{"reproduced":true}\n', encoding="utf-8")
    incomplete_sha256 = hashlib.sha256(incomplete_output.read_bytes()).hexdigest()
    incomplete_replication = replicator.record_run(
        RecordRun(
            protocol_id=protocol.protocol_id,
            started_at="2026-09-02T12:03:00Z",
            completed_at="2026-09-02T12:04:00Z",
            analysis_code_hash="d" * 64,
            environment_hash="e" * 64,
            output_artifacts=[DatasetArtifact(
                "replication.json", incomplete_sha256,
                incomplete_output.stat().st_size, "application/json",
            )],
            artifact_root=str(tmp_path),
            quality_gates=[
                QualityGateResult(
                    gate_id="replication-check",
                    status=QualityGateStatus.PASSED,
                    summary="Independent implementation reproduced the result.",
                    details={"evidence_sha256": incomplete_sha256},
                )
            ],
            metadata={
                "replicates_run_id": original.run_id,
                "protocol_deviation_disclosure": {
                    "status": "no_deviations_declared", "deviations": [],
                },
            },
        )
    )
    with pytest.raises(
        ValidationError, match="replication_independence"
    ):
        replicator.record_evidence(
            _classified_evidence(
                hypothesis.hypothesis_id,
                incomplete_replication.run_id,
                validation_tags=[ValidationTag.INDEPENDENT_REPLICATION],
            )
        )

    attestation_locator = "independence-attestation.json"
    artifact_root = tmp_path / "replication-artifacts"
    artifact_root.mkdir()
    result_path = artifact_root / "replication-clean-room.json"
    result_path.write_text('{"reproduced":true}\n', encoding="utf-8")
    attestation = {
        "target_run_id": original.run_id,
        "executor_identity": "replicator",
        "design": "clean_room",
        "independence_dimensions": ["executor", "implementation"],
        "prior_implementation_accessed": False,
        "allowed_input_manifest": {
            "locator": "contract.md",
            "sha256": "2" * 64,
        },
        "analysis_code_hash": "d" * 64,
        "contamination_disclosures": [],
    }
    attestation_path = artifact_root / attestation_locator
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
    attestation_schema = tmp_path / "attestation.schema.json"
    attestation_schema.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": list(attestation),
                "properties": {
                    "target_run_id": {"const": original.run_id},
                    "executor_identity": {"const": "replicator"},
                    "design": {"const": "clean_room"},
                    "independence_dimensions": {
                        "type": "array",
                        "minItems": 2,
                        "uniqueItems": True,
                        "items": {"type": "string"},
                    },
                    "prior_implementation_accessed": {"const": False},
                    "allowed_input_manifest": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["locator", "sha256"],
                        "properties": {
                            "locator": {"type": "string", "minLength": 1},
                            "sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                        },
                    },
                    "analysis_code_hash": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "contamination_disclosures": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    schema_hash = hashlib.sha256(attestation_schema.read_bytes()).hexdigest()
    replication = replicator.record_run(
        RecordRun(
            run_id="run-independent-clean-room",
            protocol_id=protocol.protocol_id,
            started_at="2026-09-02T12:05:00Z",
            completed_at="2026-09-02T12:06:00Z",
            analysis_code_hash="d" * 64,
            environment_hash="e" * 64,
            output_artifacts=[
                DatasetArtifact(
                    "replication-clean-room.json",
                    hashlib.sha256(result_path.read_bytes()).hexdigest(),
                    size_bytes=result_path.stat().st_size,
                ),
                DatasetArtifact(
                    attestation_locator,
                    hashlib.sha256(attestation_path.read_bytes()).hexdigest(),
                    size_bytes=attestation_path.stat().st_size,
                    metadata={"artifact_role": "independence_attestation"},
                ),
            ],
            quality_gates=[
                QualityGateResult(
                    gate_id="replication-check",
                    status=QualityGateStatus.PASSED,
                    summary="Clean-room implementation reproduced the result.",
                    details={"evidence_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()},
                )
            ],
            metadata={
                "replicates_run_id": original.run_id,
                "protocol_deviation_disclosure": {
                    "status": "no_deviations_declared", "deviations": [],
                },
                "replication_independence": {
                    "design": "clean_room",
                    "independence_dimensions": ["executor", "implementation"],
                    "prior_implementation_accessed": False,
                    "allowed_inputs": [
                        {"locator": "contract.md", "sha256": "2" * 64}
                    ],
                    "contamination_disclosures": [],
                    "attestation_artifact": attestation_locator,
                },
            },
            artifact_root=str(artifact_root),
            attestation_schema_path=str(attestation_schema),
            expected_attestation_schema_sha256=schema_hash,
        )
    )
    assert replication.metadata["artifact_integrity"]["status"] == "passed"
    evidence = replicator.record_evidence(
        _classified_evidence(
            hypothesis.hypothesis_id,
            replication.run_id,
            summary="A distinct executor and code artifact reproduced the result.",
            validation_tags=[ValidationTag.INDEPENDENT_REPLICATION],
        )
    )
    assert evidence.validation_tags == [ValidationTag.INDEPENDENT_REPLICATION]
