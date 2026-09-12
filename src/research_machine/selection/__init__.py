"""Transparent, deterministic research-action selection."""

from research_machine.selection.recommendation import (
    CURRENT_RECOMMENDATION_SCORE_CONTRACT_VERSION,
    rank_actions,
    rank_actions_by_lane,
    recommendation_payload_sha256,
    validate_recommendation_payload_commitment,
    verify_recommendation_score_replay,
)

__all__ = [
    "CURRENT_RECOMMENDATION_SCORE_CONTRACT_VERSION",
    "rank_actions",
    "rank_actions_by_lane",
    "recommendation_payload_sha256",
    "validate_recommendation_payload_commitment",
    "verify_recommendation_score_replay",
]
