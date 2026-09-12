from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateInquiry,
    DeferQuestion,
    ProposeHypothesis,
    RecordEvidence,
    RegisterDataset,
    RetireHypothesis,
)
from research_machine.application.service import ResearchService
from research_machine.application.claim_integrity import claim_scientific_sha256
from research_machine.domain.errors import IntegrityError, ValidationError
from research_machine.domain.models import (
    ClaimDisposition,
    ClaimEpistemicLayer,
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


def test_authoritative_inquiry_read_rejects_accepted_claim_authority_drift(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry("Claim authority", "Can accepted claims drift?", "claim-authority")
    )
    service.add_claim(
        AddClaim(
            statement="The source record documents the fixture observation.",
            level=ClaimLevel.OTHER,
            epistemic_layer=ClaimEpistemicLayer.DOCUMENTED_FACT,
            disposition=ClaimDisposition.ACCEPTED,
            confidence=0.8,
            source_refs=["fixture:source-record"],
            last_reviewed="2026-09-01T12:00:00Z",
            decision_owner="review-owner",
        )
    )
    service.show_inquiry()

    claims_path = tmp_path / "inquiries" / "claim-authority" / "claims.json"
    claims_bytes = claims_path.read_bytes()
    claims = json.loads(claims_bytes)
    claims[0]["decision_owner"] = ""
    claims_path.write_text(json.dumps(claims), encoding="utf-8")
    with pytest.raises(ValidationError, match="accepted claims require decision_owner"):
        service.show_inquiry()

    claims = json.loads(claims_bytes)
    claims[0]["source_refs"] = []
    claims_path.write_text(json.dumps(claims), encoding="utf-8")
    with pytest.raises(
        ValidationError,
        match="accepted documented facts and source claims require source_refs",
    ):
        service.show_inquiry()


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


def test_synthesis_surfaces_open_questions_as_live_ambiguity(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            title="Ambiguity synthesis",
            initial_statement="Can the design distinguish models?",
            inquiry_id="ambiguity-synthesis",
            decision_to_support="Choose whether to proceed.",
            minimum_evidence="A reviewed result answers the decision boundary.",
            decision_change_criteria=[
                "Stop if the registered falsifier appears."
            ],
            decision_owner="review-owner",
        )
    )
    answered = service.add_question(
        AddQuestion("Which outcome is primary?")
    )
    service.answer_question(answered.question_id, "Primary score.")
    service.add_question(
        AddQuestion("Could measurement drift explain the apparent effect?")
    )

    synthesis = service.build_synthesis()["content"]

    assert "- Open questions still unresolved: 1" in synthesis
    assert "- Deferred questions retained as unresolved: 0" in synthesis
    assert (
        "Open and deferred questions remain live ambiguity, not evidence, "
        "answers, or authorization to choose a preferred explanation."
    ) in synthesis
    assert "[open] Could measurement drift explain the apparent effect?" in synthesis
    assert "[answered] Which outcome is primary? — Primary score." in synthesis
    assert service.verify_ledger()["valid"]


def test_question_deferral_preserves_unresolved_ambiguity(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            title="Deferred ambiguity",
            initial_statement="Can the design discriminate causes?",
            inquiry_id="deferred-ambiguity",
            decision_to_support="Decide whether the design is ready to freeze.",
            minimum_evidence="Every blocking ambiguity has a recorded disposition.",
            decision_change_criteria=["Do not freeze if measurement drift remains live."],
            decision_owner="review-owner",
        )
    )
    question = service.add_question(
        AddQuestion("Could measurement drift explain the apparent effect?")
    )

    deferred = service.defer_question(
        question.question_id,
        DeferQuestion("Handled in the next protocol revision before freeze."),
    )

    assert deferred.status.value == "deferred"
    assert deferred.answer == "Handled in the next protocol revision before freeze."
    audit = service.audit_rigor()
    finding = next(
        item for item in audit.findings
        if item.code == "INQUIRY_OPEN_QUESTIONS_UNRESOLVED"
    )
    assert "open or deferred clarifying question" in finding.message
    assert question.question_id in finding.remediation
    assert audit.structurally_valid is True

    synthesis = service.build_synthesis()["content"]
    assert "- Open questions still unresolved: 0" in synthesis
    assert "- Deferred questions retained as unresolved: 1" in synthesis
    assert (
        "[deferred] Could measurement drift explain the apparent effect? — "
        "Handled in the next protocol revision before freeze."
    ) in synthesis
    assert "INQUIRY_OPEN_QUESTIONS_UNRESOLVED (1)" in synthesis
    assert service.verify_ledger()["valid"]

    with pytest.raises(ValidationError, match="already deferred"):
        service.defer_question(
            question.question_id,
            DeferQuestion("Do not rewrite the retained rationale."),
        )
    answered = service.add_question(AddQuestion("Which endpoint is primary?"))
    service.answer_question(answered.question_id, "Primary score.")
    with pytest.raises(ValidationError, match="answered question cannot be deferred"):
        service.defer_question(
            answered.question_id,
            DeferQuestion("Do not hide a retained answer by deferring it later."),
        )


def test_hypothesis_retirement_requires_bounded_limitations_and_resurrection(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry("Retirement boundary", "Can rejection memory drift?", "retire")
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The fixture hypothesis has a testable alternative.",
            observable_prediction="The bounded fixture statistic changes.",
            null_model="The bounded fixture statistic does not change.",
            falsification_conditions=["The fixture statistic remains unchanged."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)

    with pytest.raises(ValidationError, match="retirement limitations"):
        service.retire_hypothesis(
            RetireHypothesis(
                hypothesis_id=hypothesis.hypothesis_id,
                rejection_type=RejectionType.INSUFFICIENT_DATA,
                reason="The fixture is underpowered.",
                limitations="",
                resurrection_conditions=["Reconsider with more independent units."],
            )
        )
    with pytest.raises(ValidationError, match="at least one item"):
        service.retire_hypothesis(
            RetireHypothesis(
                hypothesis_id=hypothesis.hypothesis_id,
                rejection_type=RejectionType.INSUFFICIENT_DATA,
                reason="The fixture is underpowered.",
                limitations="This does not refute the scoped alternative.",
                resurrection_conditions=[],
            )
        )
    with pytest.raises(ValidationError, match="overclaiming"):
        service.retire_hypothesis(
            RetireHypothesis(
                hypothesis_id=hypothesis.hypothesis_id,
                rejection_type=RejectionType.INSUFFICIENT_DATA,
                reason="The fixture confirmed the null model.",
                limitations="This does not refute the scoped alternative.",
                resurrection_conditions=["Reconsider with more independent units."],
            )
        )

    retired = service.retire_hypothesis(
        RetireHypothesis(
            hypothesis_id=hypothesis.hypothesis_id,
            rejection_type=RejectionType.INSUFFICIENT_DATA,
            reason="The fixture did not meet its registered information target.",
            limitations="This does not refute the scoped alternative.",
            resurrection_conditions=["Reconsider with more independent units."],
        )
    )
    assert retired.workflow_state.value == "retired"

    hypothesis_path = (
        tmp_path
        / "inquiries"
        / "retire"
        / "hypotheses"
        / "retired"
        / f"{hypothesis.hypothesis_id}.json"
    )
    stored = json.loads(hypothesis_path.read_text(encoding="utf-8"))
    stored["retirement"]["resurrection_conditions"] = []
    hypothesis_path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ValidationError, match="at least one item"):
        service.list_hypotheses(state="retired")


def test_hypothesis_proposal_rejects_noncanonical_lineage_and_contrast_handles(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            title="Hypothesis handles",
            initial_statement="Can proposal handles be padded?",
            inquiry_id="hypothesis-handles",
        )
    )
    claim = service.add_claim(
        AddClaim(
            statement="The source claim exists.",
            level=ClaimLevel.OTHER,
        )
    )
    prior = service.propose_hypothesis(
        ProposeHypothesis(statement="The prior candidate remains unreviewed.")
    )
    with pytest.raises(ValidationError, match="parent_claims item must be canonical"):
        service.propose_hypothesis(
            ProposeHypothesis(
                statement="A padded parent claim should fail.",
                parent_claims=[f" {claim.claim_id} "],
            )
        )
    with pytest.raises(ValidationError, match="lineage item must be canonical"):
        service.propose_hypothesis(
            ProposeHypothesis(
                statement="A padded lineage link should fail.",
                lineage=[f" {prior.hypothesis_id} "],
            )
        )
    with pytest.raises(ValidationError, match="contrast_groups item must be canonical"):
        service.propose_hypothesis(
            ProposeHypothesis(
                statement="A padded contrast level should fail.",
                contrast_definition="Treatment minus control.",
                contrast_groups=["treatment", " control "],
            )
        )


@pytest.mark.parametrize(
    "overclaim",
    ["proved", "confirmed", "explained", "validates", "validated"],
)
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
    assert "validated the mechanism" not in synthesis


def test_evidence_unsupported_conclusion_ceiling_rejects_report_overclaim(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            "Ceiling overclaim",
            "Can a ceiling smuggle a stronger conclusion?",
            "ceiling-overclaim",
        )
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The registered association differs from the null process.",
            observable_prediction="The prespecified statistic moves away from the null.",
            null_model="The statistic remains compatible with the null model.",
            competing_models=["Measurement error creates the apparent association."],
            falsification_conditions=["The statistic remains in the null region."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    service.register_dataset(
        RegisterDataset(
            dataset_id="dataset-ceiling-overclaim",
            name="Ceiling overclaim fixture",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("ceiling.csv", "a" * 64)],
        )
    )

    with pytest.raises(ValidationError, match="report-prohibited overclaiming"):
        service.record_evidence(
            RecordEvidence(
                hypothesis_id=hypothesis.hypothesis_id,
                direction=EvidenceDirection.INCONCLUSIVE,
                summary="The exploratory result remains inconclusive.",
                dataset_id="dataset-ceiling-overclaim",
                analysis_id="analysis-ceiling-overclaim",
                uncertainty="Synthetic fixture uncertainty remains large.",
                scope="Synthetic fixture only.",
                higher_level_conclusions_unsupported=[
                    "The mechanism is not validated by this result."
                ],
                validation_tags=[ValidationTag.CALIBRATION],
                exploratory=True,
            )
        )


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
    with pytest.raises(ValidationError, match="provisional staging"):
        service.stage_hypothesis(
            complete.hypothesis_id,
            rationale="Codex approved and validated this proposal for human review.",
            confidence="high",
        )
    staged = service.stage_hypothesis(
        complete.hypothesis_id,
        rationale="The structure is complete and exploratory work is reversible.",
        confidence="high",
    )
    assert staged.workflow_state.value == "pending_review"

    hypothesis_path = (
        tmp_path
        / "inquiries"
        / "gate"
        / "hypotheses"
        / "pending_review"
        / f"{complete.hypothesis_id}.json"
    )
    stored = json.loads(hypothesis_path.read_text(encoding="utf-8"))
    stored["pending_review_rationale"] = (
        "Codex approved and validated this proposal after human review."
    )
    hypothesis_path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ValidationError, match="provisional staging"):
        service.list_hypotheses(state="pending_review")
