from __future__ import annotations

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ActionCandidate,
    ActionLane,
    ActionScore,
    SelectionWeights,
)


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

    scores = [
        ActionScore(
            action_id=candidate.action_id,
            utility=round(
                weights.expected_discrimination * candidate.expected_discrimination
                + weights.uncertainty_reduction * candidate.uncertainty_reduction
                - weights.cost * candidate.cost
                - weights.burden * candidate.burden
                - weights.safety_risk * candidate.safety_risk
                - weights.ambiguity_risk * candidate.ambiguity_risk,
                8,
            ),
        )
        for candidate in eligible
    ]
    return sorted(scores, key=lambda score: (-score.utility, score.action_id))


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
