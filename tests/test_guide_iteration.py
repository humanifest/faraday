"""G07 synthesis retains adverse observations and next-action gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddQuestion,
    CreateInquiry,
    ProposeHypothesis,
    RecommendNextAction,
    RecordEvidence,
    RegisterDataset,
)
from research_machine.application.service import ResearchService
from research_machine.application.audit_prerequisite import (
    AUDIT_PREREQUISITE_CONCLUSION_CEILING,
)
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ActionCandidate,
    ActionAuditClass,
    AuditPrerequisiteContract,
    DatasetArtifact,
    DatasetRole,
    EvidenceDirection,
    ValidationTag,
)


def test_synthesis_retains_weakening_and_inconclusive_observations(tmp_path: Path) -> None:
    service = ResearchService(FileSystemRepository(tmp_path / "workspace"), actor="guide-fixture")
    service.init_workspace()
    service.create_inquiry(CreateInquiry(
        "Synthetic iteration",
        "Could a treatment alter a synthetic outcome?",
        inquiry_id="guide-iteration-v1",
        decision_to_support="Whether to design a later reviewed comparison.",
    ))
    service.add_question(AddQuestion("Is the measurement valid for the target outcome?"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="The treatment could alter the registered synthetic outcome.",
        observable_prediction="A registered comparison would show a directional change.",
        null_model="No decision-relevant change exists.",
        competing_models=["Measurement error could produce the contrast."],
        falsification_conditions=["A precise independent comparison remains in the neutral range."],
    ))
    service.stage_hypothesis(
        hypothesis.hypothesis_id,
        rationale="The synthetic proposal is structurally complete for reversible exploratory review only.",
        confidence="high",
    )
    service.register_dataset(RegisterDataset(
        dataset_id="guide-iteration-data-v1",
        name="Synthetic exploratory observations",
        role=DatasetRole.EXPLORATORY,
        artifacts=[DatasetArtifact("synthetic.csv", "a" * 64)],
        synthetic=True,
    ))
    observations = (
        (EvidenceDirection.WEAKENS, "The synthetic estimate moves against the favored direction."),
        (EvidenceDirection.INCONCLUSIVE, "The synthetic interval leaves both models compatible."),
    )
    for index, (direction, summary) in enumerate(observations, start=1):
        service.record_evidence(RecordEvidence(
            hypothesis_id=hypothesis.hypothesis_id,
            direction=direction,
            summary=summary,
            dataset_id="guide-iteration-data-v1",
            analysis_id=f"synthetic-analysis-{index}",
            uncertainty="Synthetic interval and measurement limits remain unresolved.",
            scope="Fabricated units only.",
            controls_passed=(
                ["Fabricated fixture comparator check declared passed."]
                if direction is EvidenceDirection.WEAKENS else []
            ),
            higher_level_conclusions_unsupported=[
                "No real-population, causal, mechanism, or attribution conclusion."
            ],
            validation_tags=[ValidationTag.CALIBRATION],
            exploratory=True,
        ))
    first = service.build_synthesis()["content"]
    second = service.build_synthesis()["content"]
    assert first == second
    assert observations[0][1] in first
    assert observations[1][1] in first
    assert "Measurement error could produce the contrast." in first
    assert "Is the measurement valid for the target outcome?" in first
    assert "No real-population, causal, mechanism, or attribution conclusion." in first
    assert service.show_inquiry()["hypotheses"][0]["workflow_state"] == "pending_review"
    assert service.verify_ledger()["valid"] is True

    candidate = ActionCandidate(
        action_id="measurement-check-v1",
        title="Review a prospective measurement check",
        distinguishes_hypotheses=[],
        information_targets=["measurement validity for the synthetic outcome"],
        expected_discrimination=0.0,
        uncertainty_reduction=0.5,
        cost=0.1,
        duration=0.1,
        burden=0.1,
        safety_risk=0.1,
        ambiguity_risk=0.1,
        rationale="A future check could reduce measurement uncertainty.",
        prerequisites_met=False,
        safety_approved=False,
        prerequisite_evidence_refs=["prerequisite-review-pending"],
        safety_review_refs=["safety-review-pending"],
        audit_prerequisite_contract=AuditPrerequisiteContract(
            contract_version=1,
            action_class=ActionAuditClass.NONADVANCING_INFORMATION,
            subjects=[],
            required_audits=[],
            evaluator_exposure_statement="",
            nonadvancing_information_statement=(
                "The proposed review cannot advance candidate or implementation bytes."
            ),
            limitations=["Synthetic fixture; prerequisite and safety review remain missing."],
            conclusion_ceiling=AUDIT_PREREQUISITE_CONCLUSION_CEILING,
        ),
    )
    with pytest.raises(ValidationError, match="no action candidate has both satisfied prerequisites"):
        service.recommend_next_action(RecommendNextAction([candidate]))
    assert service.show_inquiry()["recommendations"] == []
