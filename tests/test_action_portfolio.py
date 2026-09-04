from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    CreateInquiry,
    RecommendActionPortfolio,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import ActionCandidate, ActionLane


def prepared_service(root: Path) -> ResearchService:
    counter = iter(f"portfolio{index:02d}" for index in range(100))
    service = ResearchService(
        FileSystemRepository(root),
        actor="portfolio-test",
        clock=lambda: "2026-09-04T12:00:00Z",
        token=lambda: next(counter),
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
) -> ActionCandidate:
    return ActionCandidate(
        action_id=action_id,
        title=action_id.replace("-", " ").title(),
        distinguishes_hypotheses=[],
        information_targets=[f"{lane_id}:uncertainty"],
        expected_discrimination=score,
        uncertainty_reduction=score,
        cost=0.1,
        burden=0.1,
        safety_risk=0.0,
        ambiguity_risk=0.1,
        rationale=f"Reduce uncertainty in {lane_id}.",
        safety_approved=safety_approved,
        lane_id=lane_id,
        depends_on=depends_on or [],
    )


def lanes() -> list[ActionLane]:
    return [
        ActionLane("machine", "Research Machine"),
        ActionLane("theory", "Theory falsification"),
    ]


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
    assert recommendation.selected_action_ids_by_lane == {
        "machine": "machine-high",
        "theory": "theory-best",
    }
    assert recommendation.selected_action_id == "machine-high"
    assert service.list_recommendations() == [recommendation]
    synthesis = service.build_synthesis()["content"]
    assert (
        "Selected next actions by lane: machine: machine-high; "
        "theory: theory-best" in synthesis
    )


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
