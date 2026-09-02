from __future__ import annotations

from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    CreateInquiry,
    CreateProtocol,
    ProposeHypothesis,
    RecordEvidence,
    RecordRun,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisMode,
    DatasetArtifact,
    EvidenceDirection,
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
    run = service.record_run(
        RecordRun(
            protocol_id=protocol.protocol_id,
            started_at="2026-09-02T12:01:00Z",
            completed_at="2026-09-02T12:02:00Z",
            analysis_code_hash="a" * 64,
            environment_hash="b" * 64,
            output_artifacts=[DatasetArtifact("result.json", "c" * 64)],
            quality_gates=[
                QualityGateResult(
                    gate_id="checker",
                    status=QualityGateStatus.PASSED,
                    summary="Candidate passed and invalid control failed.",
                )
            ],
        )
    )
    return service, hypothesis, run


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


def test_independent_replication_requires_distinct_executor_and_code(
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
    replication = replicator.record_run(
        RecordRun(
            protocol_id=protocol.protocol_id,
            started_at="2026-09-02T12:03:00Z",
            completed_at="2026-09-02T12:04:00Z",
            analysis_code_hash="d" * 64,
            environment_hash="e" * 64,
            output_artifacts=[DatasetArtifact("replication.json", "f" * 64)],
            quality_gates=[
                QualityGateResult(
                    gate_id="replication-check",
                    status=QualityGateStatus.PASSED,
                    summary="Independent implementation reproduced the result.",
                )
            ],
            metadata={"replicates_run_id": original.run_id},
        )
    )
    evidence = replicator.record_evidence(
        _classified_evidence(
            hypothesis.hypothesis_id,
            replication.run_id,
            summary="A distinct executor and code artifact reproduced the result.",
            validation_tags=[ValidationTag.INDEPENDENT_REPLICATION],
        )
    )
    assert evidence.validation_tags == [ValidationTag.INDEPENDENT_REPLICATION]
