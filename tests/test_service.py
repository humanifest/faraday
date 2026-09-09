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
from research_machine.application.claim_integrity import claim_scientific_sha256
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


def test_unreferenced_claims_and_hypotheses_reject_scientific_content_drift(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Seals", "Do records drift?", "seals"))
    claim = service.add_claim(AddClaim(
        statement="The instrument measures the registered construct.",
        level=ClaimLevel.MEASUREMENT_VALIDITY,
        scope="The registered instrument configuration.",
    ))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="The registered signal differs from the null process.",
        observable_prediction="The bounded signal statistic changes.",
        null_model="The bounded signal statistic does not change.",
        falsification_conditions=["The registered statistic remains in the null region."],
    ))
    service.show_inquiry()

    claims_path = tmp_path / "inquiries" / "seals" / "claims.json"
    claims_bytes = claims_path.read_bytes()
    claims = json.loads(claims_bytes)
    claims[0]["statement"] = "A substituted measurement proposition."
    claims_path.write_text(json.dumps(claims), encoding="utf-8")
    with pytest.raises(ValidationError, match=f"claim {claim.claim_id} scientific content"):
        service.show_inquiry()
    claims_path.write_bytes(claims_bytes)

    hypothesis_path = (
        tmp_path
        / "inquiries"
        / "seals"
        / "drafts"
        / "hypotheses"
        / f"{hypothesis.hypothesis_id}.json"
    )
    hypothesis_value = json.loads(hypothesis_path.read_text())
    hypothesis_value["null_model"] = "A substituted null model."
    hypothesis_path.write_text(json.dumps(hypothesis_value), encoding="utf-8")
    with pytest.raises(
        ValidationError, match=f"hypothesis {hypothesis.hypothesis_id} scientific content"
    ):
        service.list_hypotheses()


def test_claim_hierarchy_rejects_higher_inference_parent_dependencies(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Claim ladder", "Can claims depend upward?", "ladder"))
    measurement = service.add_claim(
        AddClaim(
            statement="The instrument detected the registered event.",
            level=ClaimLevel.MEASUREMENT_VALIDITY,
        )
    )
    service.add_claim(
        AddClaim(
            statement="The event is associated with the registered condition.",
            level=ClaimLevel.STATISTICAL_ASSOCIATION,
            parent_claims=[measurement.claim_id],
        )
    )
    causal = service.add_claim(
        AddClaim(
            statement="The condition directionally precedes the event in scope.",
            level=ClaimLevel.CAUSAL_DIRECTION,
            parent_claims=[measurement.claim_id],
        )
    )

    with pytest.raises(ValidationError, match="higher-inference parent claim"):
        service.add_claim(
            AddClaim(
                statement="A lower-level measurement assertion cannot depend on causal direction.",
                level=ClaimLevel.MEASUREMENT_VALIDITY,
                parent_claims=[causal.claim_id],
            )
        )


def test_authoritative_inquiry_read_rejects_resealed_inverted_claim_hierarchy(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Claim read", "Can resealed claims invert?", "read"))
    measurement = service.add_claim(
        AddClaim(
            statement="The instrument detected the registered event.",
            level=ClaimLevel.MEASUREMENT_VALIDITY,
        )
    )
    causal = service.add_claim(
        AddClaim(
            statement="The registered condition precedes the event.",
            level=ClaimLevel.CAUSAL_DIRECTION,
            parent_claims=[measurement.claim_id],
        )
    )

    claims_path = tmp_path / "inquiries" / "read" / "claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8"))
    claims[0]["parent_claims"] = [causal.claim_id]
    resealed = type(measurement).from_dict(claims[0])
    claims[0]["scientific_content_sha256"] = claim_scientific_sha256(resealed)
    claims_path.write_text(json.dumps(claims), encoding="utf-8")

    with pytest.raises(ValidationError, match="higher-inference parent claim"):
        service.show_inquiry()


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


@pytest.mark.parametrize("overclaim", ["proved", "confirmed", "explained"])
def test_evidence_summary_rejects_report_overclaim_language(
    tmp_path: Path, overclaim: str
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry("Bounded reports", "Can reports avoid overclaiming?", "bounded")
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The bounded association differs from the null model.",
            observable_prediction="The prespecified statistic moves away from the null.",
            null_model="The statistic remains compatible with the null model.",
            competing_models=["Measurement error creates the apparent association."],
            falsification_conditions=["The statistic remains in the null region."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    service.register_dataset(
        RegisterDataset(
            dataset_id="dataset-bounded",
            name="Bounded fixture",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("bounded.csv", "a" * 64)],
        )
    )

    with pytest.raises(ValidationError, match="report-prohibited overclaiming"):
        service.record_evidence(
            RecordEvidence(
                hypothesis_id=hypothesis.hypothesis_id,
                direction=EvidenceDirection.INCONCLUSIVE,
                summary=f"This {overclaim} the mechanism behind the observation.",
                dataset_id="dataset-bounded",
                analysis_id="analysis-bounded",
                uncertainty="Synthetic fixture leaves mechanism unresolved.",
                scope="Synthetic fixture only.",
                higher_level_conclusions_unsupported=[
                    "Mechanism and causality remain unsupported."
                ],
                validation_tags=[ValidationTag.CALIBRATION],
                exploratory=True,
            )
        )

    evidence = service.record_evidence(
        RecordEvidence(
            hypothesis_id=hypothesis.hypothesis_id,
            direction=EvidenceDirection.INCONCLUSIVE,
            summary="The result is inconclusive against the registered alternatives.",
            dataset_id="dataset-bounded",
            analysis_id="analysis-bounded",
            uncertainty="Synthetic fixture leaves mechanism unresolved.",
            scope="Synthetic fixture only.",
            higher_level_conclusions_unsupported=[
                "Mechanism and causality remain unsupported."
            ],
            validation_tags=[ValidationTag.CALIBRATION],
            exploratory=True,
        )
    )
    synthesis = service.build_synthesis()["content"]
    assert evidence.summary in synthesis
    assert "confirmed the mechanism" not in synthesis


def test_supporting_evidence_cannot_promote_to_explanatory_claim_levels(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            "Mechanism ceiling",
            "Can calibration support a mechanism claim?",
            "mechanism-ceiling",
        )
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The observed process has an explanatory mechanism.",
            observable_prediction="The observed process recurs under the registered condition.",
            null_model="The recurrence is compatible with ordinary measurement error.",
            competing_models=["Selection or measurement error creates the pattern."],
            falsification_conditions=["The registered observation is absent."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    claim = service.add_claim(
        AddClaim(
            statement="The proposed mechanism explains the observed process.",
            level=ClaimLevel.MECHANISM,
        )
    )
    service.register_dataset(
        RegisterDataset(
            dataset_id="dataset-mechanism-fixture",
            name="Mechanism fixture",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("mechanism.csv", "a" * 64)],
        )
    )

    with pytest.raises(ValidationError, match="cannot target mechanism"):
        service.record_evidence(
            RecordEvidence(
                hypothesis_id=hypothesis.hypothesis_id,
                claim_id=claim.claim_id,
                direction=EvidenceDirection.SUPPORTS,
                summary="The calibration fixture is consistent with the mechanism.",
                dataset_id="dataset-mechanism-fixture",
                analysis_id="analysis-mechanism-fixture",
                uncertainty="The fixture does not distinguish mechanism from alternatives.",
                scope="Synthetic fixture only.",
                controls_passed=["negative control fixture"],
                higher_level_conclusions_unsupported=[
                    "Mechanism, adaptation, and intent remain unsupported."
                ],
                validation_tags=[ValidationTag.CALIBRATION],
                exploratory=True,
            )
        )

    inconclusive = service.record_evidence(
        RecordEvidence(
            hypothesis_id=hypothesis.hypothesis_id,
            claim_id=claim.claim_id,
            direction=EvidenceDirection.INCONCLUSIVE,
            summary="The calibration fixture does not discriminate the mechanism claim.",
            dataset_id="dataset-mechanism-fixture",
            analysis_id="analysis-mechanism-fixture",
            uncertainty="The fixture remains compatible with mundane alternatives.",
            scope="Synthetic fixture only.",
            higher_level_conclusions_unsupported=[
                "Mechanism, adaptation, and intent remain unsupported."
            ],
            validation_tags=[ValidationTag.CALIBRATION],
            exploratory=True,
        )
    )
    assert inconclusive.claim_id == claim.claim_id


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
