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


_CANDIDATE_SCORE_FIELDS = (
    "expected_discrimination",
    "uncertainty_reduction",
    "cost",
    "burden",
    "safety_risk",
    "ambiguity_risk",
)


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


def _validate_candidate_score_inputs_for_replay(candidate: ActionCandidate) -> None:
    if not isinstance(candidate, ActionCandidate):
        raise ValidationError("candidates must contain ActionCandidate values")
    _require_canonical_text(candidate.action_id, "action_id")
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


def _validate_discrimination_target_replay(candidate: ActionCandidate) -> None:
    hypotheses = [_require_canonical_text(item, "distinguishes_hypotheses item")
                  for item in candidate.distinguishes_hypotheses]
    if len(set(hypotheses)) != len(hypotheses):
        raise ValidationError(
            f"action {candidate.action_id} repeats a hypothesis distinction"
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
    if seen != set(hypotheses):
        raise ValidationError(
            f"action {candidate.action_id} hypothesis discrimination targets "
            "do not replay from distinguishes_hypotheses"
        )


def rank_actions(
    candidates: list[ActionCandidate], weights: SelectionWeights
) -> list[ActionScore]:
    """Rank safe, currently feasible actions using an auditable utility function."""

    _validate_selection_weights_for_replay(weights)
    for candidate in candidates:
        _validate_candidate_score_inputs_for_replay(candidate)
        _validate_discrimination_target_replay(candidate)
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
) -> dict[str, list[ActionScore]]:
    """Rank feasible actions separately so one active lane cannot starve another."""

    _validate_selection_weights_for_replay(weights)
    for candidate in candidates:
        _validate_candidate_score_inputs_for_replay(candidate)
        _validate_discrimination_target_replay(candidate)
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
        rankings[lane.lane_id] = rank_actions(eligible, weights)
    return rankings


def recommendation_payload_sha256(recommendation: ActionRecommendation) -> str:
    """Commit the immutable recommendation while excluding the commitment itself."""
    payload = recommendation.to_dict()
    payload.pop("recommendation_payload_sha256", None)
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def validate_recommendation_payload_commitment(
    recommendation: ActionRecommendation,
) -> str | None:
    retained = recommendation.recommendation_payload_sha256
    if retained == "":
        return None
    expected = recommendation_payload_sha256(recommendation)
    if retained != expected:
        raise ValidationError(
            f"recommendation {recommendation.recommendation_id} payload no "
            "longer matches its service-generated commitment"
        )
    return retained


def verify_recommendation_score_replay(
    recommendation: ActionRecommendation,
) -> None:
    """Replay stored recommendation scores from retained candidates and weights."""

    if recommendation.selection_mode == "single":
        expected_scores = rank_actions(
            recommendation.candidates, recommendation.weights
        )
        expected_selected_action_id = expected_scores[0].action_id
        expected_selected_by_lane: dict[str, str] = {}
    elif recommendation.selection_mode == "portfolio":
        rankings = rank_actions_by_lane(
            recommendation.candidates,
            recommendation.lanes,
            recommendation.completed_action_ids,
            recommendation.weights,
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
