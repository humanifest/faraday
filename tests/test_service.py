from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateInquiry,
    ProposeHypothesis,
    RecordEvidence,
    RegisterDataset,
    RetireHypothesis,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import IntegrityError, ValidationError
from research_machine.domain.models import (
    ClaimLevel,
    DatasetArtifact,
    DatasetRole,
    EvidenceDirection,
    RejectionType,
    ValidationTag,
)


def make_service(root: Path) -> ResearchService:
    counter = iter(f"token{i:02d}" for i in range(100))
    return ResearchService(
        FileSystemRepository(root),
        actor="test-researcher",
        clock=lambda: "2026-09-01T12:00:00Z",
        token=lambda: next(counter),
    )


def test_complete_inquiry_loop_preserves_rejected_hypotheses(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    inquiry = service.create_inquiry(
        CreateInquiry(
            title="AI hiring bias",
            initial_statement="I suspect persistent group disparities in AI hiring.",
            inquiry_id="ai-hiring-bias",
        )
    )
    question = service.add_question(
        AddQuestion("Which hiring stage and outcome are in scope?")
    )
    service.answer_question(
        question.question_id, "Resume screening recommendations in 2025."
    )
    claim = service.add_claim(
        AddClaim(
            statement="Recorded recommendations represent actual model outputs.",
            level=ClaimLevel.MEASUREMENT_VALIDITY,
        )
    )

    with pytest.raises(ValidationError, match="non-negative integer"):
        service.propose_hypothesis(
            ProposeHypothesis(
                statement="An invalid proposal must not be silently repaired.",
                required_replications=-1,
            )
        )

    incomplete = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The apparent disparity is a timestamp join artifact.",
            parent_claims=[claim.claim_id],
        )
    )
    with pytest.raises(ValidationError, match="cannot be activated"):
        service.activate_hypothesis(incomplete.hypothesis_id)

    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="Historical labels produce group-dependent ranking errors.",
            parent_claims=[claim.claim_id],
            scope="Resume screening for the sampled roles and period.",
            observable_prediction=(
                "Group-dependent ranking errors persist on independently adjudicated labels."
            ),
            null_model="Error rates do not differ beyond sampling uncertainty.",
            competing_models=[
                "The observed difference is caused by applicant-pool composition."
            ],
            falsification_conditions=[
                "The independently adjudicated holdout shows no meaningful error disparity."
            ],
            required_replications=1,
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    service.register_dataset(
        RegisterDataset(
            dataset_id="dataset-holdout-01",
            name="Exploratory holdout",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("holdout.csv", "a" * 64)],
        )
    )
    evidence = service.record_evidence(
        RecordEvidence(
            hypothesis_id=hypothesis.hypothesis_id,
            claim_id=claim.claim_id,
            direction=EvidenceDirection.INCONCLUSIVE,
            summary="The estimate is too imprecise to distinguish the models.",
            dataset_id="dataset-holdout-01",
            analysis_id="analysis-error-rates-01",
            uncertainty="95% interval crosses the registered equivalence region.",
            scope="The sampled resume-screening roles and 2025 period only.",
            higher_level_conclusions_unsupported=[
                "The AI component caused a persistent systemic disparity."
            ],
            validation_tags=[ValidationTag.CALIBRATION],
            exploratory=True,
        )
    )
    retired = service.retire_hypothesis(
        RetireHypothesis(
            hypothesis_id=hypothesis.hypothesis_id,
            rejection_type=RejectionType.INSUFFICIENT_DATA,
            reason="The confirmatory sample did not meet the registered precision target.",
            limitations="This does not establish equal performance.",
            resurrection_conditions=[
                "Reconsider when an independently adjudicated sample reaches the precision target."
            ],
        )
    )
    report = service.build_synthesis()

    assert inquiry.inquiry_id == "ai-hiring-bias"
    assert evidence.hypothesis_id == hypothesis.hypothesis_id
    assert retired.retirement is not None
    assert retired.retirement["rejection_type"] == "insufficient_data"
    assert "Rejected and retired hypothesis memory" in report["content"]
    assert "Reconsider when" in report["content"]
    assert (tmp_path / report["path"]).is_file()
    assert (
        tmp_path
        / "inquiries/ai-hiring-bias/hypotheses/retired"
        / f"{hypothesis.hypothesis_id}.json"
    ).is_file()
    assert service.verify_ledger() == {
        "valid": True,
        "events": 11,
        "head_hash": service.verify_ledger()["head_hash"],
    }


def test_ledger_verification_detects_tampering(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            "Integrity test", "Can ledger tampering be detected?", "integrity"
        )
    )
    service.add_question(AddQuestion("What constitutes tampering?"))

    ledger = tmp_path / "inquiries/integrity/ledger.jsonl"
    events = ledger.read_text(encoding="utf-8").splitlines()
    first = json.loads(events[0])
    first["payload"]["title"] = "Altered after capture"
    events[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(events) + "\n", encoding="utf-8")

    with pytest.raises(IntegrityError, match="event hash mismatch"):
        service.verify_ledger("integrity")


def test_pending_review_requires_complete_high_confidence_proposal(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry("Review gate", "Can this proposal enter exploration?", "gate")
    )
    incomplete = service.propose_hypothesis(
        ProposeHypothesis(statement="An incomplete proposal.")
    )
    with pytest.raises(ValidationError, match="cannot enter pending review"):
        service.stage_hypothesis(
            incomplete.hypothesis_id,
            rationale="This should fail before rationale matters.",
            confidence="high",
        )

    complete = service.propose_hypothesis(
        ProposeHypothesis(
            statement="A complete competing explanation.",
            observable_prediction="A registered observable changes.",
            null_model="The observable does not change.",
            falsification_conditions=["No registered change is observed."],
        )
    )
    with pytest.raises(ValidationError, match="explicitly high confidence"):
        service.stage_hypothesis(
            complete.hypothesis_id,
            rationale="The structure is complete but confidence is not high.",
            confidence="medium",
        )
