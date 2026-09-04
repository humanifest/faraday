from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import CreateInquiry, RecordCrossLaneLesson
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError


def prepared_service(root: Path) -> ResearchService:
    counter = iter(f"lesson{index:02d}" for index in range(100))
    service = ResearchService(
        FileSystemRepository(root),
        actor="lesson-test",
        clock=lambda: "2026-09-04T13:00:00Z",
        token=lambda: next(counter),
    )
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry("Dogfood transfer", "Can failures improve future work?", "dogfood")
    )
    return service


def valid_command(**overrides) -> RecordCrossLaneLesson:
    values = {
        "origin_lane_id": "theory",
        "target_lane_ids": ["machine"],
        "origin_artifact_locator": "results/exposed-run.json",
        "origin_artifact_sha256": "a" * 64,
        "origin_integrity_status": "declared",
        "observation": "A control omitted its evaluation time.",
        "failure_class": "interface_ambiguity",
        "strongest_alternative_explanation": (
            "The implementation, rather than the contract, may be defective."
        ),
        "challenged_invariant": "Every sealed target has a complete measurement.",
        "first_permitted_future_versions": ["machine-v-next", "protocol-v2"],
        "prohibited_retroactive_targets": [
            "machine-v-current",
            "protocol-v1",
            "oracle-v1",
        ],
        "proposed_repair": "Require a typed evaluation point for every target.",
        "repair_falsifier": "An omitted-time fixture is accepted by the next validator.",
        "conclusion_ceiling": "Process lesson only; no theory evidence.",
    }
    values.update(overrides)
    return RecordCrossLaneLesson(**values)


def test_cross_lane_lesson_is_immutable_ledgered_process_state(tmp_path: Path) -> None:
    service = prepared_service(tmp_path)
    lesson = service.record_cross_lane_lesson(valid_command())

    assert lesson.lesson_id == "lesson-lesson00"
    assert lesson.failure_class == "interface_ambiguity"
    assert service.list_cross_lane_lessons() == [lesson]
    assert service.show_inquiry()["cross_lane_lessons"] == [lesson.to_dict()]
    assert "Cross-lane process lessons: 1" in service.build_synthesis()["content"]
    assert service.verify_ledger()["events"] == 3


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"target_lane_ids": ["theory"]}, "must target a different lane"),
        ({"failure_class": "desired_result"}, "failure_class is not recognized"),
        ({"origin_artifact_sha256": "not-a-hash"}, "64 lowercase hex"),
        (
            {"prohibited_retroactive_targets": []},
            "must name at least one frozen or exposed target",
        ),
        (
            {
                "first_permitted_future_versions": ["protocol-v1"],
                "prohibited_retroactive_targets": ["protocol-v1"],
            },
            "future versions cannot also be prohibited",
        ),
        (
            {"strongest_alternative_explanation": ""},
            "strongest_alternative_explanation must not be empty",
        ),
    ],
)
def test_cross_lane_lesson_fails_closed_before_ledger_mutation(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    service = prepared_service(tmp_path)
    before = service.verify_ledger()
    with pytest.raises(ValidationError, match=message):
        service.record_cross_lane_lesson(valid_command(**overrides))
    assert service.list_cross_lane_lessons() == []
    assert service.verify_ledger() == before
