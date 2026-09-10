from __future__ import annotations

import hashlib
import json
import math

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ActionCandidate,
    ActionLane,
    ActionRecommendation,
    ActionScore,
    HypothesisDiscriminationTarget,
    SelectionWeights,
)


def _weighted_components(
    candidate: ActionCandidate, weights: SelectionWeights
) -> dict[str, float]:
    return {
        "expected_discrimination": round(
            weights.expected_discrimination * candidate.expected_discrimination, 8
        ),
        "uncertainty_reduction": round(
            weights.uncertainty_reduction * candidate.uncertainty_reduction, 8
        ),
        "cost_penalty": round(-(weights.cost * candidate.cost), 8),
        "burden_penalty": round(-(weights.burden * candidate.burden), 8),
        "safety_risk_penalty": round(
            -(weights.safety_risk * candidate.safety_risk), 8
        ),
        "ambiguity_risk_penalty": round(
            -(weights.ambiguity_risk * candidate.ambiguity_risk), 8
        ),
    }


def _require_canonical_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be non-empty text")
    if value != value.strip():
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return value


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be non-empty text")
    return value


def _require_unique_canonical_text_list(value: object, field: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise ValidationError(f"{field} must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _require_canonical_text(item, f"{field} item")
        if text in seen:
            raise ValidationError(f"{field} must not repeat items")
        seen.add(text)
        normalized.append(text)
    return normalized


_CANDIDATE_SCORE_FIELDS = (
    "expected_discrimination",
    "uncertainty_reduction",
    "cost",
    "burden",
    "safety_risk",
    "ambiguity_risk",
)

_RECOMMENDATION_HYPOTHESIS_STATES = {"active", "pending_review"}


def _validate_selection_weights_for_replay(weights: SelectionWeights) -> None:
    if not isinstance(weights, SelectionWeights):
        raise ValidationError("weights must be SelectionWeights")
    values: list[float] = []
    for field_name in _CANDIDATE_SCORE_FIELDS:
        value = getattr(weights, field_name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValidationError(
                f"selection weight {field_name} must be a finite non-negative number"
            )
        values.append(float(value))
    if not any(value > 0 for value in values):
        raise ValidationError(
            "selection weights must include at least one positive utility term"
        )


def _validate_candidate_score_inputs_for_replay(
    candidate: ActionCandidate,
    *,
    allow_legacy_missing_eligibility_basis: bool = False,
) -> None:
    if not isinstance(candidate, ActionCandidate):
        raise ValidationError("candidates must contain ActionCandidate values")
    _require_canonical_text(candidate.action_id, "action_id")
    _require_text(candidate.title, "action title")
    _require_text(candidate.rationale, "action rationale")
    _require_unique_canonical_text_list(
        candidate.information_targets, "information_targets"
    )
    _require_unique_canonical_text_list(candidate.depends_on, "depends_on")
    manipulated_factors = _require_unique_canonical_text_list(
        candidate.manipulated_factors, "manipulated_factors"
    )
    _require_canonical_text(candidate.lane_id, "lane_id")
    for field_name in _CANDIDATE_SCORE_FIELDS:
        value = getattr(candidate, field_name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 <= float(value) <= 1
        ):
            raise ValidationError(f"{field_name} must be a number from 0 to 1")
    if not isinstance(candidate.prerequisites_met, bool):
        raise ValidationError("prerequisites_met must be true or false")
    if not isinstance(candidate.safety_approved, bool):
        raise ValidationError("safety_approved must be true or false")
    prerequisite_evidence_refs = _require_unique_canonical_text_list(
        candidate.prerequisite_evidence_refs, "prerequisite_evidence_refs"
    )
    safety_review_refs = _require_unique_canonical_text_list(
        candidate.safety_review_refs, "safety_review_refs"
    )
    if (
        not allow_legacy_missing_eligibility_basis
        and not prerequisite_evidence_refs
    ):
        raise ValidationError(
            f"action {candidate.action_id} must retain prerequisite_evidence_refs "
            "for its prerequisite status"
        )
    if not allow_legacy_missing_eligibility_basis and not safety_review_refs:
        raise ValidationError(
            f"action {candidate.action_id} must retain safety_review_refs for "
            "its safety approval status"
        )
    if not isinstance(candidate.factorial_or_crossover_design, bool):
        raise ValidationError("factorial_or_crossover_design must be true or false")
    if not isinstance(candidate.factor_interpretability_plan, str):
        raise ValidationError("factor_interpretability_plan must be text")
    factor_interpretability_plan = ""
    if candidate.factor_interpretability_plan:
        factor_interpretability_plan = _require_canonical_text(
            candidate.factor_interpretability_plan,
            "factor_interpretability_plan",
        )
    if candidate.factorial_or_crossover_design and not manipulated_factors:
        raise ValidationError(
            f"action {candidate.action_id} declares a factorial or crossover "
            "design without manipulated_factors"
        )
    if (
        candidate.factorial_or_crossover_design
        and not factor_interpretability_plan
    ):
        raise ValidationError(
            f"action {candidate.action_id} declares a factorial or crossover "
            "design without a factor_interpretability_plan"
        )
    if (
        len(manipulated_factors) > 1
        and (
            not candidate.factorial_or_crossover_design
            or not factor_interpretability_plan
        )
    ):
        raise ValidationError(
            f"action {candidate.action_id} changes multiple factors without a "
            "factorial or crossover interpretability design"
        )


def _validate_discrimination_target_replay(candidate: ActionCandidate) -> None:
    hypotheses = _require_unique_canonical_text_list(
        candidate.distinguishes_hypotheses, "distinguishes_hypotheses"
    )
    workflow_states = candidate.hypothesis_workflow_states
    if not isinstance(workflow_states, dict):
        raise ValidationError("hypothesis_workflow_states must be an object")
    if workflow_states:
        normalized_states: dict[str, str] = {}
        for hypothesis_id, state in workflow_states.items():
            normalized_hypothesis = _require_canonical_text(
                hypothesis_id, "hypothesis_workflow_states hypothesis_id"
            )
            normalized_state = _require_canonical_text(
                state, "hypothesis_workflow_states state"
            )
            if normalized_state not in _RECOMMENDATION_HYPOTHESIS_STATES:
                raise ValidationError(
                    "hypothesis_workflow_states may only retain active or "
                    "pending_review targets"
                )
            normalized_states[normalized_hypothesis] = normalized_state
        if set(normalized_states) != set(hypotheses):
            raise ValidationError(
                f"action {candidate.action_id} hypothesis_workflow_states do "
                "not replay from distinguishes_hypotheses"
            )
    targets = candidate.hypothesis_discrimination_targets
    if not isinstance(targets, list):
        raise ValidationError("hypothesis_discrimination_targets must be a list")
    if not hypotheses:
        if targets:
            raise ValidationError(
                f"action {candidate.action_id} declares hypothesis_discrimination_targets "
                "without distinguishes_hypotheses"
            )
        return
    if not targets:
        raise ValidationError(
            f"action {candidate.action_id} must retain hypothesis discrimination targets"
        )
    seen = set()
    for target in targets:
        if not isinstance(target, HypothesisDiscriminationTarget):
            raise ValidationError(
                "hypothesis_discrimination_targets must contain "
                "HypothesisDiscriminationTarget values"
            )
        hypothesis_id = _require_canonical_text(
            target.hypothesis_id, "hypothesis_discrimination_target hypothesis_id"
        )
        if hypothesis_id in seen:
            raise ValidationError(
                "hypothesis_discrimination_targets repeat a hypothesis_id"
            )
        seen.add(hypothesis_id)
        _require_canonical_text(
            target.discriminating_observation,
            "hypothesis_discrimination_target discriminating_observation",
        )
        _require_canonical_text(
            target.expected_if_hypothesis,
            "hypothesis_discrimination_target expected_if_hypothesis",
        )
        _require_canonical_text(
            target.expected_if_alternative,
            "hypothesis_discrimination_target expected_if_alternative",
        )
        _require_canonical_text(
            target.would_weaken_if,
            "hypothesis_discrimination_target would_weaken_if",
        )
        _require_canonical_text(
            target.competing_model_ref,
            "hypothesis_discrimination_target competing_model_ref",
        )
        _validate_discrimination_text_contrast(target, candidate.action_id)
    if seen != set(hypotheses):
        raise ValidationError(
            f"action {candidate.action_id} hypothesis discrimination targets "
            "do not replay from distinguishes_hypotheses"
        )


def _validate_discrimination_text_contrast(
    target: HypothesisDiscriminationTarget,
    action_id: str,
) -> None:
    expected = target.expected_if_hypothesis.casefold()
    alternative = target.expected_if_alternative.casefold()
    weakening = target.would_weaken_if.casefold()
    if expected == alternative:
        raise ValidationError(
            f"action {action_id} discrimination target {target.hypothesis_id} "
            "must retain different expected observations for the hypothesis and alternative"
        )
    if expected == weakening:
        raise ValidationError(
            f"action {action_id} discrimination target {target.hypothesis_id} "
            "cannot retain the hypothesis-favorable expectation as its weakening condition"
        )


def rank_actions(
    candidates: list[ActionCandidate],
    weights: SelectionWeights,
    *,
    allow_legacy_missing_eligibility_basis: bool = False,
) -> list[ActionScore]:
    """Rank safe, currently feasible actions using an auditable utility function."""

    _validate_selection_weights_for_replay(weights)
    seen_action_ids: set[str] = set()
    for candidate in candidates:
        _validate_candidate_score_inputs_for_replay(
            candidate,
            allow_legacy_missing_eligibility_basis=(
                allow_legacy_missing_eligibility_basis
            ),
        )
        _validate_discrimination_target_replay(candidate)
        if (
            not candidate.distinguishes_hypotheses
            and not candidate.information_targets
        ):
            raise ValidationError(
                f"action {candidate.action_id} must distinguish at least one "
                "hypothesis or name at least one information target"
            )
        if candidate.action_id in seen_action_ids:
            raise ValidationError(f"duplicate action_id: {candidate.action_id}")
        seen_action_ids.add(candidate.action_id)
    eligible = [
        candidate
        for candidate in candidates
        if candidate.prerequisites_met and candidate.safety_approved
    ]
    if not eligible:
        raise ValidationError(
            "no action candidate has both satisfied prerequisites and safety approval"
        )

    scores = []
    for candidate in eligible:
        components = _weighted_components(candidate, weights)
        scores.append(
            ActionScore(
                action_id=candidate.action_id,
                utility=round(sum(components.values()), 8),
                weighted_components=components,
            )
        )
    ranked = sorted(scores, key=lambda score: (-score.utility, score.action_id))
    tied_top = [
        score.action_id for score in ranked if score.utility == ranked[0].utility
    ]
    if len(tied_top) > 1:
        raise ValidationError(
            "top action utility is tied; refine selection weights or candidate "
            "estimates before choosing among: " + ", ".join(tied_top)
        )
    return ranked


def rank_actions_by_lane(
    candidates: list[ActionCandidate],
    lanes: list[ActionLane],
    completed_action_ids: list[str],
    weights: SelectionWeights,
    *,
    allow_legacy_missing_eligibility_basis: bool = False,
) -> dict[str, list[ActionScore]]:
    """Rank feasible actions separately so one active lane cannot starve another."""

    _validate_selection_weights_for_replay(weights)
    _validate_portfolio_replay_inputs(
        candidates,
        lanes,
        completed_action_ids,
        allow_legacy_missing_eligibility_basis=(
            allow_legacy_missing_eligibility_basis
        ),
    )
    completed = set(completed_action_ids)
    rankings: dict[str, list[ActionScore]] = {}
    for lane in lanes:
        if lane.status == "blocked":
            continue
        eligible = [
            candidate
            for candidate in candidates
            if candidate.lane_id == lane.lane_id
            and candidate.action_id not in completed
            and candidate.prerequisites_met
            and candidate.safety_approved
            and set(candidate.depends_on) <= completed
        ]
        if not eligible:
            raise ValidationError(
                f"active lane {lane.lane_id} has no safe, dependency-complete action"
            )
        rankings[lane.lane_id] = rank_actions(
            eligible,
            weights,
            allow_legacy_missing_eligibility_basis=(
                allow_legacy_missing_eligibility_basis
            ),
        )
    return rankings


def _validate_lane_replay(lane: ActionLane) -> None:
    if not isinstance(lane, ActionLane):
        raise ValidationError("lanes must contain ActionLane values")
    lane_id = _require_canonical_text(lane.lane_id, "lane_id")
    _require_text(lane.title, "lane title")
    status = _require_canonical_text(lane.status, "lane status")
    if status not in {"active", "blocked"}:
        raise ValidationError("lane status must be active or blocked")
    blocked_on = _require_unique_canonical_text_list(lane.blocked_on, "blocked_on")
    if status == "active" and blocked_on:
        raise ValidationError(f"active lane {lane_id} cannot declare blocked_on")
    if status == "blocked" and not blocked_on:
        raise ValidationError(f"blocked lane {lane_id} must declare blocked_on")


def _validate_portfolio_replay_inputs(
    candidates: list[ActionCandidate],
    lanes: list[ActionLane],
    completed_action_ids: list[str],
    *,
    allow_legacy_missing_eligibility_basis: bool = False,
) -> None:
    if not lanes:
        raise ValidationError("at least one action lane is required")
    lane_ids: set[str] = set()
    active_lane_seen = False
    for lane in lanes:
        _validate_lane_replay(lane)
        if lane.lane_id in lane_ids:
            raise ValidationError(f"duplicate lane_id: {lane.lane_id}")
        lane_ids.add(lane.lane_id)
        active_lane_seen = active_lane_seen or lane.status == "active"
    if not active_lane_seen:
        raise ValidationError("at least one action lane must be active")
    action_ids: set[str] = set()
    for candidate in candidates:
        _validate_candidate_score_inputs_for_replay(
            candidate,
            allow_legacy_missing_eligibility_basis=(
                allow_legacy_missing_eligibility_basis
            ),
        )
        _validate_discrimination_target_replay(candidate)
        if candidate.action_id in action_ids:
            raise ValidationError(f"duplicate action_id: {candidate.action_id}")
        action_ids.add(candidate.action_id)
    completed = _require_unique_canonical_text_list(
        completed_action_ids, "completed_action_ids"
    )
    unknown_completed = sorted(set(completed) - action_ids)
    if unknown_completed:
        raise ValidationError(
            "completed_action_ids reference unknown actions: "
            + ", ".join(unknown_completed)
        )
    dependencies = {}
    for candidate in candidates:
        if candidate.lane_id not in lane_ids:
            raise ValidationError(
                f"action {candidate.action_id} references unknown lane: "
                f"{candidate.lane_id}"
            )
        unknown_dependencies = sorted(set(candidate.depends_on) - action_ids)
        if unknown_dependencies:
            raise ValidationError(
                f"action {candidate.action_id} has unknown dependencies: "
                + ", ".join(unknown_dependencies)
            )
        if candidate.action_id in candidate.depends_on:
            raise ValidationError(
                f"action {candidate.action_id} cannot depend on itself"
            )
        dependencies[candidate.action_id] = set(candidate.depends_on)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(action_id: str) -> None:
        if action_id in visiting:
            raise ValidationError("action dependency graph contains a cycle")
        if action_id in visited:
            return
        visiting.add(action_id)
        for dependency in dependencies[action_id]:
            visit(dependency)
        visiting.remove(action_id)
        visited.add(action_id)

    for action_id in sorted(dependencies):
        visit(action_id)


def _recommendation_payload(
    recommendation: ActionRecommendation,
    *,
    include_hypothesis_workflow_states: bool = True,
    include_eligibility_basis: bool = True,
) -> dict[str, object]:
    payload = recommendation.to_dict()
    payload.pop("recommendation_payload_sha256", None)
    if not include_hypothesis_workflow_states:
        for candidate in payload.get("candidates", []):
            if isinstance(candidate, dict):
                candidate.pop("hypothesis_workflow_states", None)
    if not include_eligibility_basis:
        for candidate in payload.get("candidates", []):
            if isinstance(candidate, dict):
                candidate.pop("prerequisite_evidence_refs", None)
                candidate.pop("safety_review_refs", None)
    return payload


def _sha256_json_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def recommendation_payload_sha256(recommendation: ActionRecommendation) -> str:
    """Commit the immutable recommendation while excluding the commitment itself."""
    return _sha256_json_payload(_recommendation_payload(recommendation))


def validate_recommendation_payload_commitment(
    recommendation: ActionRecommendation,
) -> str | None:
    retained = recommendation.recommendation_payload_sha256
    if retained == "":
        return None
    expected = recommendation_payload_sha256(recommendation)
    if retained != expected:
        legacy_variants = [
            (
                _sha256_json_payload(
                    _recommendation_payload(
                        recommendation,
                        include_hypothesis_workflow_states=False,
                    )
                ),
                all(
                    not candidate.hypothesis_workflow_states
                    for candidate in recommendation.candidates
                ),
            ),
            (
                _sha256_json_payload(
                    _recommendation_payload(
                        recommendation,
                        include_eligibility_basis=False,
                    )
                ),
                _recommendation_has_legacy_missing_eligibility_basis(
                    recommendation
                ),
            ),
            (
                _sha256_json_payload(
                    _recommendation_payload(
                        recommendation,
                        include_hypothesis_workflow_states=False,
                        include_eligibility_basis=False,
                    )
                ),
                (
                    all(
                        not candidate.hypothesis_workflow_states
                        for candidate in recommendation.candidates
                    )
                    and _recommendation_has_legacy_missing_eligibility_basis(
                        recommendation
                    )
                ),
            ),
        ]
        if any(retained == digest and allowed for digest, allowed in legacy_variants):
            return retained
        raise ValidationError(
            f"recommendation {recommendation.recommendation_id} payload no "
            "longer matches its service-generated commitment"
        )
    return retained


def _recommendation_has_legacy_missing_eligibility_basis(
    recommendation: ActionRecommendation,
) -> bool:
    return all(
        not candidate.prerequisite_evidence_refs and not candidate.safety_review_refs
        for candidate in recommendation.candidates
    )


def _recommendation_allows_legacy_missing_eligibility_basis(
    recommendation: ActionRecommendation,
) -> bool:
    retained = recommendation.recommendation_payload_sha256
    if retained == "" or not _recommendation_has_legacy_missing_eligibility_basis(
        recommendation
    ):
        return False
    legacy_expected = _sha256_json_payload(
        _recommendation_payload(
            recommendation,
            include_eligibility_basis=False,
        )
    )
    legacy_without_workflow_expected = _sha256_json_payload(
        _recommendation_payload(
            recommendation,
            include_hypothesis_workflow_states=False,
            include_eligibility_basis=False,
        )
    )
    return retained in {legacy_expected, legacy_without_workflow_expected}


def verify_recommendation_score_replay(
    recommendation: ActionRecommendation,
) -> None:
    """Replay stored recommendation scores from retained candidates and weights."""

    allow_legacy_missing_eligibility_basis = (
        _recommendation_allows_legacy_missing_eligibility_basis(recommendation)
    )
    if recommendation.selection_mode == "single":
        _validate_single_replay_inputs(recommendation)
        expected_scores = rank_actions(
            recommendation.candidates,
            recommendation.weights,
            allow_legacy_missing_eligibility_basis=(
                allow_legacy_missing_eligibility_basis
            ),
        )
        expected_selected_action_id = expected_scores[0].action_id
        expected_selected_by_lane: dict[str, str] = {}
    elif recommendation.selection_mode == "portfolio":
        rankings = rank_actions_by_lane(
            recommendation.candidates,
            recommendation.lanes,
            recommendation.completed_action_ids,
            recommendation.weights,
            allow_legacy_missing_eligibility_basis=(
                allow_legacy_missing_eligibility_basis
            ),
        )
        expected_selected_by_lane = {
            lane.lane_id: rankings[lane.lane_id][0].action_id
            for lane in recommendation.lanes
            if lane.status == "active"
        }
        selected_ids = list(expected_selected_by_lane.values())
        expected_selected_action_id = selected_ids[0] if selected_ids else ""
        expected_scores = [
            score
            for lane in recommendation.lanes
            if lane.status == "active"
            for score in rankings[lane.lane_id]
        ]
    else:
        raise ValidationError(
            f"recommendation {recommendation.recommendation_id} has unsupported "
            f"selection_mode {recommendation.selection_mode!r}"
        )

    if recommendation.selected_action_id != expected_selected_action_id:
        raise ValidationError(
            f"recommendation {recommendation.recommendation_id} selected action "
            "does not replay from stored candidates and weights"
        )
    if (
        recommendation.selection_mode == "portfolio"
        and recommendation.selected_action_ids_by_lane != expected_selected_by_lane
    ):
        raise ValidationError(
            f"recommendation {recommendation.recommendation_id} lane selections "
            "do not replay from stored candidates, lanes, dependencies, and weights"
        )
    if [score.to_dict() for score in recommendation.ranked_scores] != [
        score.to_dict() for score in expected_scores
    ]:
        raise ValidationError(
            f"recommendation {recommendation.recommendation_id} ranked scores "
            "do not replay from stored candidates and weights"
        )
    validate_recommendation_payload_commitment(recommendation)


def _validate_single_replay_inputs(recommendation: ActionRecommendation) -> None:
    if recommendation.lanes:
        raise ValidationError(
            f"recommendation {recommendation.recommendation_id} single-mode "
            "record cannot retain portfolio lanes"
        )
    if recommendation.completed_action_ids:
        raise ValidationError(
            f"recommendation {recommendation.recommendation_id} single-mode "
            "record cannot retain completed_action_ids"
        )
    if recommendation.selected_action_ids_by_lane:
        raise ValidationError(
            f"recommendation {recommendation.recommendation_id} single-mode "
            "record cannot retain selected_action_ids_by_lane"
        )
    for candidate in recommendation.candidates:
        if candidate.depends_on:
            raise ValidationError(
                f"recommendation {recommendation.recommendation_id} single-mode "
                f"action {candidate.action_id} cannot retain depends_on"
            )
