import hashlib
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
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ActionCandidate,
    AnalysisMode,
    DatasetArtifact,
    DatasetRole,
    EvidenceDirection,
    ProtocolKind,
    QualityGateResult,
    QualityGateStatus,
    RunStatus,
    ValidationTag,
)


CODE_HASH = "a" * 64
ENVIRONMENT_HASH = "b" * 64
SEED_REVEAL = "registered-seed-42"
SEED_COMMITMENT = hashlib.sha256(SEED_REVEAL.encode("utf-8")).hexdigest()


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
            )
        ],
    }
    values.update(overrides)
    return RecordRun(**values)


def test_domain_neutral_protocol_run_and_evidence_chain(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)

    run = service.record_run(
        run_command(protocol.protocol_id, QualityGateStatus.PASSED)
    )
    evidence = service.record_evidence(
        RecordEvidence(
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
    )

    assert protocol.protocol_kind is ProtocolKind.FORMAL
    assert run.status is RunStatus.COMPLETED
    assert run.scientific_evidence_eligible is True
    assert evidence.dataset_id is None
    assert evidence.protocol_id == protocol.protocol_id
    assert evidence.run_id == run.run_id
    assert evidence.scientific_evidence_eligible is True


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

    report = service.preflight_run(
        run_command(protocol.protocol_id, QualityGateStatus.PASSED),
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
            "details": {},
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
