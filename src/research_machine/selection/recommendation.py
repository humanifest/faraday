from __future__ import annotations

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ActionCandidate,
    ActionLane,
    ActionRecommendation,
    ActionScore,
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


def rank_actions(
    candidates: list[ActionCandidate], weights: SelectionWeights
) -> list[ActionScore]:
    """Rank safe, currently feasible actions using an auditable utility function."""

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
