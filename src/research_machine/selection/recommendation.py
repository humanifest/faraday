from __future__ import annotations

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ActionCandidate,
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
