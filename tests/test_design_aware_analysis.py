from __future__ import annotations

import pytest

from research_machine.addons.general_science import (
    independent_mean_difference_ci,
    paired_mean_difference_ci,
)
from research_machine.domain.errors import ValidationError


def test_independent_estimator_requires_declared_independence() -> None:
    rows = [
        {"group": "control", "outcome": "1"},
        {"group": "control", "outcome": "2"},
        {"group": "treatment", "outcome": "4"},
        {"group": "treatment", "outcome": "5"},
    ]
    spec = {
        "outcome_column": "outcome",
        "group_column": "group",
        "groups": ["treatment", "control"],
        "study_design": "independent_groups",
        "seed": 1,
        "bootstrap_resamples": 1000,
    }
    result = independent_mean_difference_ci(spec, rows)
    assert result["mean_difference_first_minus_second"] == 3
    assert result["confidence_interval"]["level"] == 0.95
    with pytest.raises(ValidationError, match="study_design"):
        independent_mean_difference_ci({**spec, "study_design": "paired"}, rows)


def test_paired_estimator_refuses_incomplete_pairs() -> None:
    rows = [
        {"pair": "a", "group": "control", "outcome": "1"},
        {"pair": "a", "group": "treatment", "outcome": "3"},
        {"pair": "b", "group": "control", "outcome": "2"},
    ]
    spec = {
        "outcome_column": "outcome",
        "group_column": "group",
        "groups": ["treatment", "control"],
        "pair_column": "pair",
        "study_design": "paired",
        "seed": 1,
        "bootstrap_resamples": 1000,
    }
    with pytest.raises(ValidationError, match="incomplete pairs"):
        paired_mean_difference_ci(spec, rows)
