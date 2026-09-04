"""Transparent, deterministic research-action selection."""

from research_machine.selection.recommendation import (
    rank_actions,
    rank_actions_by_lane,
)

__all__ = ["rank_actions", "rank_actions_by_lane"]
