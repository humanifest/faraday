import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    CreateInquiry,
    ProposeHypothesis,
    RecommendActionPortfolio,
)
from research_machine.application.service import ResearchService
from research_machine.application.audit_prerequisite import (
    AUDIT_PREREQUISITE_CONCLUSION_CEILING,
)
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ActionCandidate,
    ActionAuditClass,
    ActionLane,
    AuditPrerequisiteArtifact,
    AuditPrerequisiteContract,
    AuditPrerequisiteSubject,
    HypothesisDiscriminationTarget,
    SelectionWeights,
)


AUDIT_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "audit-prerequisite"
SUBJECT_SHA256 = "962db3ccf52bd2e7cb2f1c1c6f377fcb7c7b777d66ba3b1b5433d86389505984"
AUDIT_SHA256 = "1007b052c7bb6e43ffe8fee59108e64735c6b191c9d644e8868300723d521bf2"


def audit_contract(*, candidate_advancing: bool) -> AuditPrerequisiteContract:
    if not candidate_advancing:
        return AuditPrerequisiteContract(
            contract_version=1,
            action_class=ActionAuditClass.EXPOSED_EVALUATOR_DEVELOPMENT,
            subjects=[],
            required_audits=[],
            evaluator_exposure_statement=(
                "Evaluator implementation is exposed development and cannot advance a candidate."
            ),
            limitations=["Synthetic workflow fixture only."],
            conclusion_ceiling=AUDIT_PREREQUISITE_CONCLUSION_CEILING,
        )
    return AuditPrerequisiteContract(
        contract_version=1,
        action_class=ActionAuditClass.CANDIDATE_ADVANCING,
        subjects=[
            AuditPrerequisiteSubject(
                subject_role="candidate",
                subject_id="fixture-candidate",
                artifact_locator="subject.txt",
                artifact_sha256=SUBJECT_SHA256,
            )
        ],
        required_audits=[
            AuditPrerequisiteArtifact(
                audit_id="audit-fixture-favorable",
                artifact_role="adversarial_candidate_audit",
                artifact_locator="favorable-audit.json",
                artifact_sha256=AUDIT_SHA256,
                audited_subject_role="candidate",
                audited_subject_id="fixture-candidate",
                audited_subject_sha256=SUBJECT_SHA256,
                verdict="favorable",
                scope="Exact synthetic candidate artifact bytes for workflow-gate testing only.",
                auditor_identity="synthetic-test-auditor",
                audited_at="2026-09-12T12:00:00Z",
                limitations=[
                    "Synthetic fixture; does not authenticate the auditor or establish scientific validity."
                ],
            )
        ],
        evaluator_exposure_statement="",
        limitations=["Synthetic workflow fixture only."],
        conclusion_ceiling=AUDIT_PREREQUISITE_CONCLUSION_CEILING,
    )


def prepared_service(root: Path) -> ResearchService:
    counter = iter(f"portfolio{index:02d}" for index in range(100))
    service = ResearchService(
        FileSystemRepository(root),
        actor="portfolio-test",
        clock=lambda: "2026-09-04T12:00:00Z",
        token=lambda: next(counter),
        audit_artifact_root=AUDIT_FIXTURE_ROOT,
    )
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            "Parallel research",
            "Can two research lanes make auditable progress without starvation?",
            "parallel-research",
        )
    )
    return service


def candidate(
    action_id: str,
    lane_id: str,
    score: float,
    *,
    depends_on: list[str] | None = None,
    safety_approved: bool = True,
    manipulated_factors: list[str] | None = None,
    factorial_or_crossover_design: bool = False,
    factor_interpretability_plan: str = "",
    distinguishes_hypotheses: list[str] | None = None,
    hypothesis_discrimination_targets: list[HypothesisDiscriminationTarget] | None = None,
    prerequisite_evidence_refs: list[str] | None = None,
    safety_review_refs: list[str] | None = None,
    metadata: dict[str, object] | None = None,
    duration: float = 0.0,
) -> ActionCandidate:
    hypotheses = distinguishes_hypotheses or []
    return ActionCandidate(
        action_id=action_id,
        title=action_id.replace("-", " ").title(),
        distinguishes_hypotheses=hypotheses,
        information_targets=[f"{lane_id}:uncertainty"],
        expected_discrimination=score if distinguishes_hypotheses else 0.0,
        uncertainty_reduction=score,
        cost=0.1,
        duration=duration,
        burden=0.1,
        safety_risk=0.0,
        ambiguity_risk=0.1,
        rationale=f"Reduce uncertainty in {lane_id}.",
        prerequisite_evidence_refs=(
            [f"prerequisite-review:{action_id}"]
            if prerequisite_evidence_refs is None
            else prerequisite_evidence_refs
        ),
        safety_review_refs=(
            [f"safety-review:{action_id}"]
            if safety_review_refs is None
            else safety_review_refs
        ),
        safety_approved=safety_approved,
        lane_id=lane_id,
        depends_on=depends_on or [],
        manipulated_factors=manipulated_factors or [],
        factorial_or_crossover_design=factorial_or_crossover_design,
        factor_interpretability_plan=factor_interpretability_plan,
        hypothesis_discrimination_targets=hypothesis_discrimination_targets or [],
        metadata=metadata or {},
        audit_prerequisite_contract=audit_contract(
            candidate_advancing=bool(hypotheses)
        ),
    )


def lanes() -> list[ActionLane]:
    return [
        ActionLane("machine", "Research Machine"),
        ActionLane("theory", "Theory falsification"),
    ]


def reviewed_hypothesis(service: ResearchService, statement: str) -> str:
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement=statement,
            observable_prediction="The prespecified observable differs by target condition.",
            null_model="No condition-linked difference is observed.",
            competing_models=["Measurement error or selection explains the apparent pattern."],
            falsification_conditions=["The effect disappears under the discriminating control."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    return hypothesis.hypothesis_id


def discrimination_target(
    hypothesis_id: str,
    label: str,
    competing_model_ref: str = (
        "Measurement error or selection explains the apparent pattern."
    ),
) -> HypothesisDiscriminationTarget:
    return HypothesisDiscriminationTarget(
        hypothesis_id=hypothesis_id,
        discriminating_observation=f"{label} separates the target pattern from the comparator.",
        expected_if_hypothesis=f"{label} follows the target hypothesis prediction.",
        expected_if_alternative=f"{label} follows the competing model prediction.",
        would_weaken_if=f"{label} is absent or follows the competing model.",
        competing_model_ref=competing_model_ref,
    )


def test_portfolio_selects_one_action_per_active_lane_without_starvation(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    recommendation = service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate("machine-high", "machine", 1.0),
                candidate("machine-low", "machine", 0.4),
                candidate("theory-best", "theory", 0.6),
            ],
        )
    )

    assert recommendation.selection_mode == "portfolio"
    assert len(recommendation.recommendation_payload_sha256) == 64
    assert recommendation.selected_action_ids_by_lane == {
        "machine": "machine-high",
        "theory": "theory-best",
    }
    assert recommendation.selected_action_id == "machine-high"
    score_by_id = {
        score.action_id: score for score in recommendation.ranked_scores
    }
    assert score_by_id["machine-high"].weighted_components == {
        "expected_discrimination": 0.0,
        "uncertainty_reduction": 0.5,
        "cost_penalty": -0.025,
        "duration_penalty": -0.0,
        "burden_penalty": -0.035,
        "safety_risk_penalty": -0.0,
        "ambiguity_risk_penalty": -0.075,
    }
    assert score_by_id["machine-high"].utility == 0.365
    assert service.list_recommendations() == [recommendation]
    synthesis = service.build_synthesis()["content"]
    assert (
        "Selected next actions by lane: machine: machine-high; "
        "theory: theory-best" in synthesis
    )
    assert "machine: utility 0.365" in synthesis
    assert "expected_discrimination 0" in synthesis
    assert (
        "Eligibility basis: machine: prerequisites_met=True via "
        "prerequisite-review:machine-high; safety_approved=True via "
        "safety-review:machine-high" in synthesis
    )
    assert (
        "Payload commitment: " + recommendation.recommendation_payload_sha256
        in synthesis
    )


def test_action_selection_penalizes_duration_separately_from_cost(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    recommendation = service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[ActionLane("machine", "Machine")],
            candidates=[
                candidate("slow-slightly-better", "machine", 0.9, duration=1.0),
                candidate("fast-informative", "machine", 0.8, duration=0.0),
            ],
        )
    )

    assert recommendation.selected_action_id == "fast-informative"
    score_by_id = {
        score.action_id: score for score in recommendation.ranked_scores
    }
    assert score_by_id["slow-slightly-better"].weighted_components[
        "duration_penalty"
    ] == -0.25
    assert score_by_id["fast-informative"].weighted_components[
        "duration_penalty"
    ] == -0.0


def test_hypothesis_discrimination_targets_are_retained_and_visible(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    target_hypothesis = reviewed_hypothesis(
        service, "The target-linked pattern survives the planned control."
    )
    competing_hypothesis = reviewed_hypothesis(
        service, "The same pattern follows an ordinary competing process."
    )
    recommendation = service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate(
                    "machine-discriminator",
                    "machine",
                    0.9,
                    distinguishes_hypotheses=[
                        target_hypothesis,
                        competing_hypothesis,
                    ],
                    hypothesis_discrimination_targets=[
                        discrimination_target(target_hypothesis, "Target channel"),
                        discrimination_target(competing_hypothesis, "Control channel"),
                    ],
                ),
                candidate("theory-next", "theory", 0.7),
            ],
        )
    )
    assert recommendation.score_contract_version == 3
    assert len(recommendation.recommendation_payload_sha256) == 64

    selected = next(
        item
        for item in recommendation.candidates
        if item.action_id == "machine-discriminator"
    )
    assert selected.hypothesis_workflow_states == {
        competing_hypothesis: "active",
        target_hypothesis: "active",
    }
    assert [item.hypothesis_id for item in selected.hypothesis_discrimination_targets] == [
        *sorted([competing_hypothesis, target_hypothesis]),
    ]
    synthesis = service.build_synthesis()["content"]
    assert "Discrimination targets: machine: " in synthesis
    assert f"{target_hypothesis} [active]: Target channel separates" in synthesis
    assert (
        "alternative Measurement error or selection explains the apparent pattern"
        in synthesis
    )
    assert "weakens if Target channel is absent" in synthesis

    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["candidates"][0]["hypothesis_discrimination_targets"][0][
        "would_weaken_if"
    ] = "A canonical post-score rewrite would weaken the target hypothesis."
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ValidationError,
        match="payload no longer matches its service-generated commitment",
    ):
        service.list_recommendations()


def test_pending_review_discrimination_targets_retain_visible_workflow_state(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    pending = service.propose_hypothesis(
        ProposeHypothesis(
            statement="A complete pending explanation.",
            observable_prediction="The target observable follows the pending pattern.",
            null_model="The target observable follows the ordinary alternative.",
            competing_models=["A mundane process explains the target observable."],
            falsification_conditions=[
                "The pending pattern disappears under the registered falsifier."
            ],
        )
    )
    staged = service.stage_hypothesis(
        pending.hypothesis_id,
        rationale="The proposal is complete enough for exploratory planning.",
        confidence="high",
    )

    recommendation = service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate(
                    "pending-review-discriminator",
                    "machine",
                    0.9,
                    distinguishes_hypotheses=[staged.hypothesis_id],
                    hypothesis_discrimination_targets=[
                        discrimination_target(
                            staged.hypothesis_id,
                            "Pending target",
                            "The target observable follows the ordinary alternative.",
                        )
                    ],
                ),
                candidate("theory-next", "theory", 0.7),
            ],
        )
    )

    selected = next(
        item
        for item in recommendation.candidates
        if item.action_id == "pending-review-discriminator"
    )
    assert selected.hypothesis_workflow_states == {
        staged.hypothesis_id: "pending_review"
    }
    synthesis = service.build_synthesis()["content"]
    assert (
        f"{staged.hypothesis_id} [pending_review]: Pending target separates"
        in synthesis
    )

    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["candidates"][0]["hypothesis_workflow_states"][
        staged.hypothesis_id
    ] = "active"
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ValidationError,
        match="payload no longer matches its service-generated commitment",
    ):
        service.list_recommendations()


def test_caller_supplied_hypothesis_workflow_state_is_not_trusted(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    hypothesis_id = reviewed_hypothesis(
        service, "The selected target is already active in the canonical store."
    )
    stale_candidate = replace(
        candidate(
            "stale-status-discriminator",
            "machine",
            0.9,
            distinguishes_hypotheses=[hypothesis_id],
            hypothesis_discrimination_targets=[
                discrimination_target(hypothesis_id, "Canonical status")
            ],
        ),
        hypothesis_workflow_states={hypothesis_id: "pending_review"},
    )

    recommendation = service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                stale_candidate,
                candidate("theory-next", "theory", 0.7),
            ],
        )
    )

    selected = next(
        item
        for item in recommendation.candidates
        if item.action_id == "stale-status-discriminator"
    )
    assert selected.hypothesis_workflow_states == {hypothesis_id: "active"}


def test_legacy_sealed_recommendation_without_workflow_states_remains_readable(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    hypothesis_id = reviewed_hypothesis(
        service, "A legacy recommendation cited this active hypothesis."
    )
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate(
                    "legacy-status-discriminator",
                    "machine",
                    0.9,
                    distinguishes_hypotheses=[hypothesis_id],
                    hypothesis_discrimination_targets=[
                        discrimination_target(hypothesis_id, "Legacy target")
                    ],
                ),
                candidate("theory-next", "theory", 0.7),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["score_contract_version"] = 2
    for item in payload["candidates"]:
        item.pop("hypothesis_workflow_states", None)
    payload_without_commitment = dict(payload)
    payload_without_commitment.pop("recommendation_payload_sha256", None)
    payload["recommendation_payload_sha256"] = hashlib.sha256(
        json.dumps(
            payload_without_commitment,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    recommendation = service.list_recommendations()[0]
    selected = next(
        item
        for item in recommendation.candidates
        if item.action_id == "legacy-status-discriminator"
    )
    assert selected.hypothesis_workflow_states == {}
    assert "legacy_state_missing" in service.build_synthesis()["content"]


def test_new_action_recommendations_require_eligibility_basis(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    with pytest.raises(
        ValidationError,
        match="must retain prerequisite_evidence_refs",
    ):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate(
                        "missing-prerequisite-basis",
                        "machine",
                        0.9,
                        prerequisite_evidence_refs=[],
                    ),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )
    with pytest.raises(
        ValidationError,
        match="must retain safety_review_refs",
    ):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate(
                        "missing-safety-basis",
                        "machine",
                        0.9,
                        safety_review_refs=[],
                    ),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )


def test_information_only_actions_cannot_claim_expected_discrimination(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    misleading = replace(
        candidate("info-only", "machine", 0.8),
        expected_discrimination=0.8,
    )

    with pytest.raises(
        ValidationError,
        match="names no hypothesis distinction, so expected_discrimination must be 0",
    ):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=[ActionLane("machine", "Machine")],
                candidates=[misleading],
            )
        )


def test_recommendation_reads_replay_eligibility_basis(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate("machine-high", "machine", 1.0),
                candidate("theory-best", "theory", 0.6),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["candidates"][0]["prerequisite_evidence_refs"] = []
    payload["recommendation_payload_sha256"] = ""
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="must retain prerequisite_evidence_refs",
    ):
        service.list_recommendations()


def test_recommendation_reads_replay_information_only_discrimination_score(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[ActionLane("machine", "Machine")],
            candidates=[candidate("info-only", "machine", 0.8)],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["candidates"][0]["expected_discrimination"] = 0.8
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="names no hypothesis distinction, so expected_discrimination must be 0",
    ):
        service.list_recommendations()


def test_legacy_sealed_recommendation_without_eligibility_basis_remains_visible(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate("legacy-machine", "machine", 0.9),
                candidate("legacy-theory", "theory", 0.7),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["score_contract_version"] = 2
    for item in payload["candidates"]:
        item.pop("prerequisite_evidence_refs", None)
        item.pop("safety_review_refs", None)
    payload_without_commitment = dict(payload)
    payload_without_commitment.pop("recommendation_payload_sha256", None)
    payload["recommendation_payload_sha256"] = hashlib.sha256(
        json.dumps(
            payload_without_commitment,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    recommendation = service.list_recommendations()[0]
    assert recommendation.candidates[0].prerequisite_evidence_refs == []
    synthesis = service.build_synthesis()["content"]
    assert (
        "Eligibility basis: machine: prerequisites_met=True via legacy_missing"
        in synthesis
    )


def test_legacy_sealed_recommendation_without_duration_remains_readable(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[ActionLane("machine", "Machine")],
            candidates=[candidate("legacy-duration", "machine", 0.8)],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["score_contract_version"] = 2
    payload["weights"].pop("duration")
    for item in payload["candidates"]:
        item.pop("duration")
    for score in payload["ranked_scores"]:
        score["weighted_components"].pop("duration_penalty")
        score["utility"] = round(sum(score["weighted_components"].values()), 8)
    payload_without_commitment = dict(payload)
    payload_without_commitment.pop("recommendation_payload_sha256", None)
    payload["recommendation_payload_sha256"] = hashlib.sha256(
        json.dumps(
            payload_without_commitment,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    recommendation = service.list_recommendations()[0]
    assert recommendation.candidates[0].duration == 0.0
    assert (
        "duration_penalty"
        not in recommendation.ranked_scores[0].weighted_components
    )


def test_current_recommendation_without_duration_component_rejects(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[ActionLane("machine", "Machine")],
            candidates=[candidate("current-duration", "machine", 0.8)],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    for score in payload["ranked_scores"]:
        score["weighted_components"].pop("duration_penalty")
        score["utility"] = round(sum(score["weighted_components"].values()), 8)
    payload_without_commitment = dict(payload)
    payload_without_commitment.pop("recommendation_payload_sha256", None)
    payload["recommendation_payload_sha256"] = hashlib.sha256(
        json.dumps(
            payload_without_commitment,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="ranked scores do not replay"):
        service.list_recommendations()


def test_recommendation_reads_replay_ranked_score_components(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate("machine-high", "machine", 1.0),
                candidate("theory-best", "theory", 0.6),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["ranked_scores"][0]["weighted_components"][
        "uncertainty_reduction"
    ] = 0.0
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="ranked scores do not replay"):
        service.list_recommendations()
    with pytest.raises(ValidationError, match="ranked scores do not replay"):
        service.show_inquiry()
    with pytest.raises(ValidationError, match="ranked scores do not replay"):
        service.build_synthesis()


def test_recommendation_replay_rejects_legacy_invalid_selection_weights(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[ActionLane("machine", "Machine")],
            candidates=[
                candidate("low-information", "machine", 0.1),
                candidate("high-information", "machine", 0.9),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["weights"] = {
        "expected_discrimination": -1.0,
        "uncertainty_reduction": 0.0,
        "cost": 0.0,
        "burden": 0.0,
        "safety_risk": 0.0,
        "ambiguity_risk": 0.0,
    }
    payload["selected_action_id"] = "low-information"
    payload["selected_action_ids_by_lane"] = {"machine": "low-information"}
    payload["ranked_scores"] = [
        {
            "action_id": "low-information",
            "utility": -0.1,
            "weighted_components": {
                "expected_discrimination": -0.1,
                "uncertainty_reduction": 0.0,
                "cost_penalty": -0.0,
                "duration_penalty": -0.0,
                "burden_penalty": -0.0,
                "safety_risk_penalty": -0.0,
                "ambiguity_risk_penalty": -0.0,
            },
        },
        {
            "action_id": "high-information",
            "utility": -0.9,
            "weighted_components": {
                "expected_discrimination": -0.9,
                "uncertainty_reduction": 0.0,
                "cost_penalty": -0.0,
                "duration_penalty": -0.0,
                "burden_penalty": -0.0,
                "safety_risk_penalty": -0.0,
                "ambiguity_risk_penalty": -0.0,
            },
        },
    ]
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="selection weight expected_discrimination must be a finite non-negative number",
    ):
        service.list_recommendations()


def test_recommendation_replay_rejects_legacy_invalid_candidate_score(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[ActionLane("machine", "Machine")],
            candidates=[candidate("candidate-with-bad-score", "machine", 0.8)],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["candidates"][0]["expected_discrimination"] = 1.2
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="expected_discrimination must be a number from 0 to 1",
    ):
        service.list_recommendations()


def test_portfolio_replay_rejects_aimless_retained_candidate(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate("machine-high", "machine", 1.0),
                replace(
                    candidate("machine-ineligible", "machine", 0.2),
                    prerequisites_met=False,
                ),
                candidate("theory-best", "theory", 0.6),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["candidates"][1]["information_targets"] = []
    payload["candidates"][1]["distinguishes_hypotheses"] = []
    payload["candidates"][1]["hypothesis_discrimination_targets"] = []
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match=(
            "action machine-ineligible must distinguish at least one "
            "hypothesis or name at least one information target"
        ),
    ):
        service.list_recommendations()


def test_recommendation_replay_rejects_legacy_self_confirming_discriminator(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    hypothesis_id = reviewed_hypothesis(
        service, "The target explanation must remain distinguishable."
    )
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[ActionLane("machine", "Machine")],
            candidates=[
                candidate(
                    "self-confirming-target",
                    "machine",
                    0.8,
                    distinguishes_hypotheses=[hypothesis_id],
                    hypothesis_discrimination_targets=[
                        discrimination_target(hypothesis_id, "Target channel")
                    ],
                )
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    target = payload["candidates"][0]["hypothesis_discrimination_targets"][0]
    target["expected_if_alternative"] = target["expected_if_hypothesis"]
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="must retain different expected observations",
    ):
        service.list_recommendations()


def test_action_discriminators_must_cite_registered_alternatives(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    hypothesis_id = reviewed_hypothesis(
        service, "The target explanation is compared with registered alternatives."
    )
    with pytest.raises(
        ValidationError,
        match="competing_model_ref must match the hypothesis null_model",
    ):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate(
                        "invented-alternative",
                        "machine",
                        0.8,
                        distinguishes_hypotheses=[hypothesis_id],
                        hypothesis_discrimination_targets=[
                            discrimination_target(
                                hypothesis_id,
                                "Target channel",
                                "An unregistered exciting alternative.",
                            )
                        ],
                    ),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )


def test_recommendation_replay_rejects_alternative_ref_drift(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    hypothesis_id = reviewed_hypothesis(
        service, "The retained action discriminator names a registered alternative."
    )
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[ActionLane("machine", "Machine")],
            candidates=[
                candidate(
                    "alternative-drift-target",
                    "machine",
                    0.8,
                    distinguishes_hypotheses=[hypothesis_id],
                    hypothesis_discrimination_targets=[
                        discrimination_target(hypothesis_id, "Target channel")
                    ],
                )
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["candidates"][0]["hypothesis_discrimination_targets"][0][
        "competing_model_ref"
    ] = "A later invented alternative."
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="competing_model_ref must match the hypothesis null_model",
    ):
        service.list_recommendations()


def test_recommendation_replay_rejects_legacy_invalid_lane_state(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[ActionLane("machine", "Machine")],
            candidates=[candidate("machine-next", "machine", 0.8)],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["lanes"][0]["status"] = "active "
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="lane status must be canonical",
    ):
        service.list_recommendations()


def test_recommendation_replay_rejects_legacy_dependency_drift(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[ActionLane("machine", "Machine")],
            candidates=[candidate("machine-next", "machine", 0.8)],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["candidates"][0]["depends_on"] = ["missing-action"]
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="has unknown dependencies",
    ):
        service.list_recommendations()


def test_portfolio_recommendation_reads_replay_lane_selections(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate("machine-high", "machine", 1.0),
                candidate("theory-best", "theory", 0.6),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["selected_action_ids_by_lane"]["theory"] = "machine-high"
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="lane selections do not replay"):
        service.list_recommendations()


def test_blocked_lane_is_visible_but_not_selected(tmp_path: Path) -> None:
    service = prepared_service(tmp_path)
    recommendation = service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=[
                ActionLane("machine", "Research Machine"),
                ActionLane(
                    "theory",
                    "Theory falsification",
                    status="blocked",
                    blocked_on=["external-review"],
                ),
            ],
            candidates=[
                candidate("machine-next", "machine", 0.7),
                candidate("theory-next", "theory", 1.0),
            ],
        )
    )

    assert recommendation.selected_action_ids_by_lane == {
        "machine": "machine-next"
    }
    assert recommendation.lanes[1].blocked_on == ["external-review"]


def test_dependencies_are_derived_from_completed_actions(tmp_path: Path) -> None:
    service = prepared_service(tmp_path)
    candidates = [
        candidate("machine-foundation", "machine", 0.4),
        candidate(
            "machine-followup",
            "machine",
            0.3,
            depends_on=["machine-foundation"],
        ),
        candidate(
            "theory-dependent",
            "theory",
            0.9,
            depends_on=["machine-foundation"],
        ),
    ]
    with pytest.raises(
        ValidationError, match="theory has no safe, dependency-complete action"
    ):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(lanes=lanes(), candidates=candidates)
        )

    recommendation = service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=candidates,
            completed_action_ids=["machine-foundation"],
        )
    )
    assert recommendation.selected_action_ids_by_lane == {
        "machine": "machine-followup",
        "theory": "theory-dependent",
    }


@pytest.mark.parametrize(
    ("lane_values", "candidate_values", "completed", "message"),
    [
        (
            [ActionLane("machine", "Machine"), ActionLane("machine", "Duplicate")],
            [candidate("machine-next", "machine", 0.8)],
            [],
            "duplicate lane_id",
        ),
        (
            [ActionLane("machine", "Machine")],
            [candidate("unknown-lane", "theory", 0.8)],
            [],
            "references unknown lane",
        ),
        (
            [ActionLane("machine", "Machine")],
            [
                candidate("action-a", "machine", 0.8, depends_on=["action-b"]),
                candidate("action-b", "machine", 0.7, depends_on=["action-a"]),
            ],
            [],
            "dependency graph contains a cycle",
        ),
        (
            [ActionLane("machine", "Machine")],
            [candidate("machine-next", "machine", 0.8)],
            ["unknown-action"],
            "completed_action_ids reference unknown actions",
        ),
    ],
)
def test_portfolio_rejects_ambiguous_lane_and_dependency_graphs(
    tmp_path: Path,
    lane_values: list[ActionLane],
    candidate_values: list[ActionCandidate],
    completed: list[str],
    message: str,
) -> None:
    service = prepared_service(tmp_path)
    with pytest.raises(ValidationError, match=message):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lane_values,
                candidates=candidate_values,
                completed_action_ids=completed,
            )
        )


def test_active_lane_cannot_borrow_an_unsafe_action_from_another_lane(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    with pytest.raises(
        ValidationError, match="theory has no safe, dependency-complete action"
    ):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate("machine-safe", "machine", 0.4),
                    candidate(
                        "theory-unsafe",
                        "theory",
                        1.0,
                        safety_approved=False,
                    ),
                ],
            )
        )


def test_portfolio_rejects_degenerate_utility_weights(tmp_path: Path) -> None:
    service = prepared_service(tmp_path)

    with pytest.raises(
        ValidationError, match="at least one positive utility term"
    ):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate("machine-next", "machine", 0.9),
                    candidate("theory-next", "theory", 0.8),
                ],
                weights=SelectionWeights(
                    expected_discrimination=0.0,
                    uncertainty_reduction=0.0,
                    cost=0.0,
                    duration=0.0,
                    burden=0.0,
                    safety_risk=0.0,
                    ambiguity_risk=0.0,
                ),
            )
        )


def test_portfolio_rejects_tied_top_utility_within_lane(tmp_path: Path) -> None:
    service = prepared_service(tmp_path)

    with pytest.raises(ValidationError, match="top action utility is tied"):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate("machine-alpha", "machine", 0.8),
                    candidate("machine-beta", "machine", 0.8),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )


@pytest.mark.parametrize(
    ("targets", "message"),
    [
        ([], "must explain how it distinguishes each named hypothesis"),
        (
            [
                discrimination_target("hyp-placeholder", "Duplicate A"),
                discrimination_target("hyp-placeholder", "Duplicate B"),
            ],
            "repeat a hypothesis_id",
        ),
        (
            [
                HypothesisDiscriminationTarget(
                    " hyp-placeholder ",
                    "Observation",
                    "Expected target",
                    "Expected alternative",
                    "Weakening condition",
                    "Measurement error or selection explains the apparent pattern.",
                )
            ],
            "hypothesis_discrimination_target hypothesis_id",
        ),
        (
            [
                HypothesisDiscriminationTarget(
                    "hyp-placeholder",
                    " Observation ",
                    "Expected target",
                    "Expected alternative",
                    "Weakening condition",
                    "Measurement error or selection explains the apparent pattern.",
                )
            ],
            "hypothesis_discrimination_target discriminating_observation",
        ),
        (
            [
                HypothesisDiscriminationTarget(
                    "hyp-placeholder",
                    "Observation",
                    "Target and alternative both produce the same pattern.",
                    "Target and alternative both produce the same pattern.",
                    "Weakening condition",
                    "Measurement error or selection explains the apparent pattern.",
                )
            ],
            "must state different expected observations",
        ),
        (
            [
                HypothesisDiscriminationTarget(
                    "hyp-placeholder",
                    "Observation",
                    "Target-favorable pattern appears.",
                    "Competing model pattern appears.",
                    "Target-favorable pattern appears.",
                    "Measurement error or selection explains the apparent pattern.",
                )
            ],
            "cannot use the hypothesis-favorable expectation",
        ),
        (
            [
                HypothesisDiscriminationTarget(
                    "hyp-placeholder",
                    "Observation",
                    "Target-favorable pattern appears.",
                    "Competing model pattern appears.",
                    "Target-favorable pattern disappears.",
                    " Measurement error or selection explains the apparent pattern. ",
                )
            ],
            "hypothesis_discrimination_target competing_model_ref",
        ),
    ],
)
def test_hypothesis_distinguishing_actions_require_discrimination_targets(
    tmp_path: Path,
    targets: list[HypothesisDiscriminationTarget],
    message: str,
) -> None:
    service = prepared_service(tmp_path)
    hypothesis_id = reviewed_hypothesis(
        service, "The proposed follow-up separates two competing models."
    )
    normalized_targets = [
        HypothesisDiscriminationTarget(
            hypothesis_id if target.hypothesis_id == "hyp-placeholder" else target.hypothesis_id,
            target.discriminating_observation,
            target.expected_if_hypothesis,
            target.expected_if_alternative,
            target.would_weaken_if,
            target.competing_model_ref,
        )
        for target in targets
    ]

    with pytest.raises(ValidationError, match=message):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate(
                        "machine-discriminator",
                        "machine",
                        0.9,
                        distinguishes_hypotheses=[hypothesis_id],
                        hypothesis_discrimination_targets=normalized_targets,
                    ),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )


def test_information_target_actions_cannot_carry_hypothesis_discriminators(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    with pytest.raises(
        ValidationError,
        match="without distinguishes_hypotheses",
    ):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate(
                        "machine-infrastructure",
                        "machine",
                        0.9,
                        hypothesis_discrimination_targets=[
                            discrimination_target("hyp-unknown", "Target channel")
                        ],
                    ),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )


def test_multi_factor_actions_require_factorial_or_crossover_interpretability(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    with pytest.raises(ValidationError, match="changes multiple factors"):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate(
                        "change-room-and-device",
                        "machine",
                        0.9,
                        manipulated_factors=["room", "apparatus"],
                    ),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )
    with pytest.raises(ValidationError, match="factor_interpretability_plan"):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate(
                        "checkbox-only-design",
                        "machine",
                        0.9,
                        manipulated_factors=["room", "apparatus"],
                        factorial_or_crossover_design=True,
                    ),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )
    with pytest.raises(ValidationError, match="without manipulated_factors"):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate(
                        "factorial-without-factors",
                        "machine",
                        0.9,
                        factorial_or_crossover_design=True,
                        factor_interpretability_plan=(
                            "Cross the declared factors before analysis."
                        ),
                    ),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )

    recommendation = service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate(
                    "cross-room-and-device",
                    "machine",
                    0.9,
                    manipulated_factors=["room", "apparatus"],
                    factorial_or_crossover_design=True,
                    factor_interpretability_plan=(
                        "Cross each room with each apparatus while holding the "
                        "operator and analysis label fixed."
                    ),
                ),
                candidate("theory-next", "theory", 0.7),
            ],
        )
    )
    selected = next(
        item
        for item in recommendation.candidates
        if item.action_id == "cross-room-and-device"
    )
    assert selected.manipulated_factors == ["room", "apparatus"]
    assert selected.factorial_or_crossover_design is True
    assert selected.factor_interpretability_plan.startswith("Cross each room")
    synthesis = service.build_synthesis()["content"]
    assert (
        "machine: room, apparatus (factorial/crossover declared; plan: Cross each room"
        in synthesis
    )
    assert "theory: no manipulated factors declared" in synthesis


@pytest.mark.parametrize(
    ("candidate_values", "message"),
    [
        (
            {
                "title": "Validated follow-up",
            },
            "action title uses recommendation-prohibited",
        ),
        (
            {
                "rationale": "Confirmed that this action is the right next step.",
            },
            "action rationale uses recommendation-prohibited",
        ),
        (
            {
                "manipulated_factors": ["room", "apparatus"],
                "factorial_or_crossover_design": True,
                "factor_interpretability_plan": (
                    "Validated that any difference follows the person."
                ),
            },
            "factor_interpretability_plan uses recommendation-prohibited",
        ),
    ],
)
def test_recommendation_candidates_reject_overclaiming_prose(
    tmp_path: Path,
    candidate_values: dict[str, object],
    message: str,
) -> None:
    service = prepared_service(tmp_path)
    base = candidate("overclaiming-action", "machine", 0.9).to_dict()
    with pytest.raises(ValidationError, match=message):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    ActionCandidate(**{**base, **candidate_values}),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (
            {"review_note": "Validated that this action is safe."},
            "action metadata uses report-prohibited",
        ),
        (
            {" confirmed_status": "bounded context"},
            "action metadata keys must be canonical",
        ),
        (
            {"nested": {"confirmed_status": "bounded context"}},
            "action metadata keys use report-prohibited",
        ),
    ],
)
def test_recommendation_candidates_reject_authority_smuggling_metadata(
    tmp_path: Path,
    metadata: dict[str, object],
    message: str,
) -> None:
    service = prepared_service(tmp_path)
    with pytest.raises(ValidationError, match=message):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate(
                        "metadata-side-channel",
                        "machine",
                        0.9,
                        metadata=metadata,
                    ),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )


def test_recommendation_replay_rejects_legacy_overclaiming_metadata(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate("machine-high", "machine", 1.0),
                candidate("theory-best", "theory", 0.6),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["candidates"][0]["metadata"] = {
        "review_note": "Confirmed that this action is scientifically valid."
    }
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="action metadata uses recommendation-prohibited",
    ):
        service.list_recommendations()


def test_recommendation_discrimination_targets_reject_overclaiming_prose(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    hypothesis_id = reviewed_hypothesis(
        service, "The target explanation must remain bounded."
    )
    target = discrimination_target(hypothesis_id, "Target channel")
    with pytest.raises(
        ValidationError,
        match="discriminating_observation uses recommendation-prohibited",
    ):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lanes(),
                candidates=[
                    candidate(
                        "overclaiming-discriminator",
                        "machine",
                        0.9,
                        distinguishes_hypotheses=[hypothesis_id],
                        hypothesis_discrimination_targets=[
                            HypothesisDiscriminationTarget(
                                target.hypothesis_id,
                                "Confirmed the target channel.",
                                target.expected_if_hypothesis,
                                target.expected_if_alternative,
                                target.would_weaken_if,
                                target.competing_model_ref,
                            )
                        ],
                    ),
                    candidate("theory-next", "theory", 0.7),
                ],
            )
        )


def test_recommendation_lanes_reject_overclaiming_titles(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    with pytest.raises(
        ValidationError,
        match="lane title uses recommendation-prohibited",
    ):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=[
                    ActionLane("machine", "Validated lane"),
                    ActionLane("theory", "Theory falsification"),
                ],
                candidates=[
                    candidate("machine-high", "machine", 1.0),
                    candidate("theory-best", "theory", 0.6),
                ],
            )
        )


def test_recommendation_replay_rejects_legacy_overclaiming_rationale(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate("machine-high", "machine", 1.0),
                candidate("theory-best", "theory", 0.6),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["candidates"][0]["rationale"] = (
        "Validated that this action should be selected."
    )
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="action rationale uses recommendation-prohibited",
    ):
        service.list_recommendations()


def test_recommendation_replay_rejects_legacy_overclaiming_summary_rationale(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate("machine-high", "machine", 1.0),
                candidate("theory-best", "theory", 0.6),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["rationale"] = "Confirmed that these selected actions are correct."
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="recommendation rationale uses recommendation-prohibited",
    ):
        service.list_recommendations()


def test_recommendation_replay_rejects_legacy_summary_rationale_drift(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.recommend_action_portfolio(
        RecommendActionPortfolio(
            lanes=lanes(),
            candidates=[
                candidate("machine-high", "machine", 1.0),
                candidate("theory-best", "theory", 0.6),
            ],
        )
    )
    recommendation_file = next(tmp_path.rglob("recommendations/*.json"))
    payload = json.loads(recommendation_file.read_text(encoding="utf-8"))
    payload["recommendation_payload_sha256"] = ""
    payload["rationale"] = "machine: Reduce uncertainty in machine."
    recommendation_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="rationale does not replay from the selected action rationales",
    ):
        service.list_recommendations()


@pytest.mark.parametrize(
    ("lane_values", "candidate_values", "completed", "message"),
    [
        (
            [ActionLane(" machine ", "Machine")],
            [candidate("machine-next", "machine", 0.8)],
            [],
            "lane_id must be canonical",
        ),
        (
            [
                ActionLane(
                    "machine", "Machine", status="blocked", blocked_on=[" review "]
                )
            ],
            [candidate("machine-next", "machine", 0.8)],
            [],
            "blocked_on item must be canonical",
        ),
        (
            [ActionLane("machine", "Machine")],
            [candidate(" action-a ", "machine", 0.8)],
            [],
            "action_id must be canonical",
        ),
        (
            [ActionLane("machine", "Machine")],
            [
                ActionCandidate(
                    **{
                        **candidate("action-a", "machine", 0.8).to_dict(),
                        "lane_id": " machine ",
                    }
                )
            ],
            [],
            "lane_id must be canonical",
        ),
        (
            [ActionLane("machine", "Machine")],
            [
                ActionCandidate(
                    **{
                        **candidate("action-a", "machine", 0.8).to_dict(),
                        "information_targets": [" machine:uncertainty "],
                    }
                )
            ],
            [],
            "information_targets item must be canonical",
        ),
        (
            [ActionLane("machine", "Machine")],
            [
                candidate("action-a", "machine", 0.8),
                candidate("action-b", "machine", 0.7, depends_on=[" action-a "]),
            ],
            [],
            "depends_on item must be canonical",
        ),
        (
            [ActionLane("machine", "Machine")],
            [candidate("action-a", "machine", 0.8)],
            [" action-a "],
            "completed_action_ids item must be canonical",
        ),
        (
            [ActionLane("machine", "Machine")],
            [
                candidate(
                    "action-a",
                    "machine",
                    0.8,
                    manipulated_factors=[" room "],
                )
            ],
            [],
            "manipulated_factors item must be canonical",
        ),
        (
            [ActionLane("machine", "Machine")],
            [
                candidate(
                    "action-a",
                    "machine",
                    0.8,
                    manipulated_factors=["room", "apparatus"],
                    factorial_or_crossover_design=True,
                    factor_interpretability_plan=" Cross factors ",
                )
            ],
            [],
            "factor_interpretability_plan must be canonical",
        ),
        (
            [ActionLane("machine", "Machine")],
            [
                candidate(
                    "action-a",
                    "machine",
                    0.8,
                    prerequisite_evidence_refs=[" review:a "],
                )
            ],
            [],
            "prerequisite_evidence_refs item must be canonical",
        ),
        (
            [ActionLane("machine", "Machine")],
            [
                candidate(
                    "action-a",
                    "machine",
                    0.8,
                    safety_review_refs=[" review:a "],
                )
            ],
            [],
            "safety_review_refs item must be canonical",
        ),
    ],
)
def test_portfolio_selection_handles_must_be_canonical(
    tmp_path: Path,
    lane_values: list[ActionLane],
    candidate_values: list[ActionCandidate],
    completed: list[str],
    message: str,
) -> None:
    service = prepared_service(tmp_path)
    with pytest.raises(ValidationError, match=message):
        service.recommend_action_portfolio(
            RecommendActionPortfolio(
                lanes=lane_values,
                candidates=candidate_values,
                completed_action_ids=completed,
            )
        )
