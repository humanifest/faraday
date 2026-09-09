from __future__ import annotations

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ActionCandidate,
    ActionLane,
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
