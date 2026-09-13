import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import CreateInquiry, RecordCrossLaneLesson
from research_machine.application.cross_lane_lesson_integrity import (
    cross_lane_lesson_payload_sha256,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import IntegrityError, ValidationError
from research_machine.domain.models import (
    CrossLaneLesson,
    CrossLaneTransferAuthorityStatus,
)


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


def save_historical_lesson(
    service: ResearchService,
    command: RecordCrossLaneLesson,
    *,
    committed: bool = False,
    lesson_id: str = "lesson-historical01",
) -> CrossLaneLesson:
    lesson = CrossLaneLesson(
        lesson_id=lesson_id,
        created_at="2026-08-01T00:00:00Z",
        created_by="historical-runtime",
        **asdict(command),
    )
    if committed:
        lesson = replace(
            lesson,
            lesson_payload_sha256=cross_lane_lesson_payload_sha256(lesson),
        )
    inquiry_id = service.repository.resolve_inquiry_id(None)
    service.repository.save_cross_lane_lesson(inquiry_id, lesson)
    service.repository.append_event(
        inquiry_id,
        timestamp=lesson.created_at,
        actor=lesson.created_by,
        command="cross-lane-lesson.record",
        aggregate_type="cross_lane_lesson",
        aggregate_id=lesson.lesson_id,
        payload=lesson.to_dict(),
    )
    return lesson


def test_cross_lane_lesson_is_immutable_ledgered_process_state(tmp_path: Path) -> None:
    service = prepared_service(tmp_path)
    lesson = service.record_cross_lane_lesson(valid_command())

    assert lesson.lesson_id == "lesson-lesson00"
    assert len(lesson.lesson_payload_sha256) == 64
    assert lesson.failure_class == "interface_ambiguity"
    assert lesson.current_transfer_authority is True
    assert (
        lesson.transfer_authority_status
        is CrossLaneTransferAuthorityStatus.CURRENT
    )
    restored = service.list_cross_lane_lessons()[0]
    assert restored == lesson
    assert restored.current_transfer_authority is True
    assert "current_transfer_authority" not in restored.to_dict()
    assert "transfer_authority_status" not in restored.to_dict()
    assert service.show_inquiry()["cross_lane_lessons"] == [lesson.to_dict()]
    synthesis = service.build_synthesis()["content"]
    assert "Cross-lane process lessons: 1" in synthesis
    assert f"payload commitment `{lesson.lesson_payload_sha256}`" in synthesis
    assert "origin artifact `" + ("a" * 64) + "` (declared)" in synthesis
    assert service.verify_ledger()["events"] == 3


def test_cross_lane_lesson_reads_replay_payload_commitment(tmp_path: Path) -> None:
    service = prepared_service(tmp_path)
    service.record_cross_lane_lesson(valid_command())
    lesson_file = next(tmp_path.rglob("cross_lane_lessons/*.json"))
    payload = json.loads(lesson_file.read_text(encoding="utf-8"))
    payload["proposed_repair"] = "Silently rewrite the old target."
    lesson_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(IntegrityError, match="differs from its record event"):
        service.list_cross_lane_lessons()
    with pytest.raises(IntegrityError, match="differs from its record event"):
        service.show_inquiry()
    with pytest.raises(IntegrityError, match="differs from its record event"):
        service.build_synthesis()


def test_legacy_cross_lane_lessons_without_payload_commitment_remain_readable(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    lesson = save_historical_lesson(service, valid_command())

    restored = service.list_cross_lane_lessons()[0]
    assert restored.lesson_id == lesson.lesson_id
    assert restored.lesson_payload_sha256 == ""
    assert restored.current_transfer_authority is False
    assert (
        restored.transfer_authority_status
        is CrossLaneTransferAuthorityStatus.LEGACY_UNCOMMITTED
    )
    synthesis = service.build_synthesis()["content"]
    assert "payload commitment `legacy_missing`" in synthesis
    assert "current transfer authority `denied` (`legacy_uncommitted`)" in synthesis
    assert any(
        item.code == "CROSS_LANE_LESSON_LEGACY_UNCOMMITTED"
        and item.entity_id == lesson.lesson_id
        for item in service.audit_rigor().findings
    )


def test_ledger_bound_pre_origin_custody_lesson_commitment_remains_readable(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    lesson = CrossLaneLesson(
        lesson_id="lesson-live-shaped-pre-origin-custody",
        created_at="2026-09-11T18:08:55Z",
        created_by="historical-runtime",
        **asdict(valid_command(origin_integrity_status="verified_elsewhere")),
    )
    payload = lesson.to_dict()
    payload.pop("lesson_payload_sha256")
    payload.pop("origin_artifact_root")
    payload.pop("origin_artifact_integrity")
    payload["lesson_payload_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    lesson_file = (
        tmp_path
        / "inquiries"
        / "dogfood"
        / "cross_lane_lessons"
        / f"{lesson.lesson_id}.json"
    )
    lesson_file.parent.mkdir(parents=True, exist_ok=True)
    lesson_file.write_text(json.dumps(payload), encoding="utf-8")
    service.repository.append_event(
        "dogfood",
        timestamp=lesson.created_at,
        actor=lesson.created_by,
        command="cross-lane-lesson.record",
        aggregate_type="cross_lane_lesson",
        aggregate_id=lesson.lesson_id,
        payload=payload,
    )

    restored = service.list_cross_lane_lessons()[0]
    integrity = service.repository.verify_cross_lane_lesson_integrity(
        "dogfood", restored
    )

    assert restored.lesson_payload_sha256 == payload["lesson_payload_sha256"]
    assert restored.origin_artifact_root == ""
    assert restored.origin_artifact_integrity == {}
    assert restored.current_transfer_authority is True
    assert integrity["legacy_origin_custody_omission_verified"] is True


@pytest.mark.parametrize("committed", [False, True])
def test_ledger_bound_historical_report_prose_is_readable_but_not_authoritative(
    tmp_path: Path, committed: bool
) -> None:
    service = prepared_service(tmp_path)
    save_historical_lesson(
        service,
        valid_command(
            proposed_repair=(
                "Treat a component as independently validated before reuse."
            )
        ),
        committed=committed,
    )

    restored = service.list_cross_lane_lessons()[0]
    assert restored.current_transfer_authority is False
    assert restored.report_prose_findings == ["proposed_repair:validated"]
    expected_status = (
        CrossLaneTransferAuthorityStatus.LEGACY_REPORT_PROSE
        if committed
        else CrossLaneTransferAuthorityStatus.LEGACY_PROSE_UNCOMMITTED
    )
    assert restored.transfer_authority_status is expected_status
    assert service.show_inquiry()["cross_lane_lessons"] == [restored.to_dict()]
    audit = service.audit_rigor()
    finding = next(
        item
        for item in audit.findings
        if item.code == "CROSS_LANE_LESSON_LEGACY_REPORT_PROSE"
    )
    assert finding.entity_id == restored.lesson_id
    synthesis = service.build_synthesis()["content"]
    assert "current transfer authority `denied`" in synthesis
    assert expected_status.value in synthesis
    assert "lexical legacy findings `proposed_repair:validated`" in synthesis


def test_historical_report_prose_does_not_excuse_structural_invalidity(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    save_historical_lesson(
        service,
        valid_command(
            target_lane_ids=["theory"],
            proposed_repair="Treat the old result as independently validated.",
        ),
    )

    with pytest.raises(ValidationError, match="must target a different lane"):
        service.list_cross_lane_lessons()


def test_removed_current_commitment_cannot_claim_legacy_status(tmp_path: Path) -> None:
    service = prepared_service(tmp_path)
    service.record_cross_lane_lesson(valid_command())
    lesson_file = next(tmp_path.rglob("cross_lane_lessons/*.json"))
    payload = json.loads(lesson_file.read_text(encoding="utf-8"))
    payload.pop("lesson_payload_sha256")
    lesson_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(IntegrityError, match="differs from its record event"):
        service.list_cross_lane_lessons()


def test_current_lesson_cannot_use_pre_origin_custody_commitment_projection(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    service.record_cross_lane_lesson(
        valid_command(origin_integrity_status="verified_elsewhere")
    )
    lesson_file = next(tmp_path.rglob("cross_lane_lessons/*.json"))
    payload = json.loads(lesson_file.read_text(encoding="utf-8"))
    payload.pop("origin_artifact_root")
    payload.pop("origin_artifact_integrity")
    lesson_file.write_text(json.dumps(payload), encoding="utf-8")
    ledger = tmp_path / "inquiries" / "dogfood" / "ledger.jsonl"
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    events[-1]["payload"] = payload
    body = {key: value for key, value in events[-1].items() if key != "event_hash"}
    events[-1]["event_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    ledger.write_text("\n".join(json.dumps(item) for item in events) + "\n")

    with pytest.raises(IntegrityError, match="payload no longer matches"):
        service.list_cross_lane_lessons()


def test_projection_without_unique_record_event_cannot_claim_legacy_status(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    lesson = CrossLaneLesson(
        lesson_id="lesson-unledgered01",
        created_at="2026-08-01T00:00:00Z",
        created_by="historical-runtime",
        **asdict(
            valid_command(
                proposed_repair="Treat this component as independently validated."
            )
        ),
    )
    inquiry_id = service.repository.resolve_inquiry_id(None)
    service.repository.save_cross_lane_lesson(inquiry_id, lesson)

    with pytest.raises(IntegrityError, match="exactly one hash-verified"):
        service.list_cross_lane_lessons()


def test_projection_with_duplicate_record_events_cannot_claim_legacy_status(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    lesson = save_historical_lesson(
        service,
        valid_command(
            proposed_repair="Treat this component as independently validated."
        ),
    )
    inquiry_id = service.repository.resolve_inquiry_id(None)
    service.repository.append_event(
        inquiry_id,
        timestamp="2026-08-01T00:00:01Z",
        actor=lesson.created_by,
        command="cross-lane-lesson.record",
        aggregate_type="cross_lane_lesson",
        aggregate_id=lesson.lesson_id,
        payload=lesson.to_dict(),
    )

    with pytest.raises(IntegrityError, match="exactly one hash-verified"):
        service.list_cross_lane_lessons()


def test_ledger_bound_lesson_with_bad_payload_commitment_fails_closed(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    lesson = save_historical_lesson(service, valid_command())
    inquiry_id = service.repository.resolve_inquiry_id(None)
    lesson_file = next(tmp_path.rglob("cross_lane_lessons/*.json"))
    payload = lesson.to_dict()
    payload["lesson_payload_sha256"] = "b" * 64
    lesson_file.write_text(json.dumps(payload), encoding="utf-8")
    ledger = tmp_path / "inquiries" / inquiry_id / "ledger.jsonl"
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    events[-1]["payload"] = payload
    body = {key: value for key, value in events[-1].items() if key != "event_hash"}
    events[-1]["event_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    ledger.write_text("\n".join(json.dumps(item) for item in events) + "\n")

    with pytest.raises(IntegrityError, match="payload no longer matches"):
        service.list_cross_lane_lessons()


def test_verified_local_cross_lane_lesson_replays_origin_bytes(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)
    artifact_root = tmp_path / "artifacts"
    artifact = artifact_root / "results" / "exposed-run.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b'{"status":"failed","gate":"fixture"}\n')
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

    lesson = service.record_cross_lane_lesson(
        valid_command(
            origin_artifact_sha256=digest,
            origin_integrity_status="verified_local",
            origin_artifact_root=str(artifact_root),
        )
    )

    assert lesson.origin_artifact_root == str(artifact_root.resolve())
    assert lesson.origin_artifact_integrity["status"] == "passed"
    assert lesson.origin_artifact_integrity["all_artifacts_match"] is True
    assert service.list_cross_lane_lessons() == [lesson]
    assert (
        "origin artifact `" + digest + "` (verified_local)"
        in service.build_synthesis()["content"]
    )

    artifact.write_bytes(b'{"status":"passed","gate":"fixture"}\n')
    with pytest.raises(ValidationError, match="current origin artifact bytes"):
        service.list_cross_lane_lessons()
    with pytest.raises(ValidationError, match="current origin artifact bytes"):
        service.show_inquiry()
    with pytest.raises(ValidationError, match="current origin artifact bytes"):
        service.build_synthesis()


def test_cross_lane_lesson_rejects_unearned_local_verification(
    tmp_path: Path,
) -> None:
    service = prepared_service(tmp_path)

    with pytest.raises(ValidationError, match="require origin_artifact_root"):
        service.record_cross_lane_lesson(
            valid_command(origin_integrity_status="verified_local")
        )

    with pytest.raises(ValidationError, match="only accepted for verified_local"):
        service.record_cross_lane_lesson(
            valid_command(origin_artifact_root=str(tmp_path))
        )


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
        ({"origin_lane_id": " theory "}, "origin_lane_id must be canonical"),
        (
            {"target_lane_ids": [" machine "]},
            "target_lane_ids item must be canonical",
        ),
        (
            {"origin_artifact_locator": " results/exposed-run.json "},
            "origin_artifact_locator must be canonical",
        ),
        (
            {"origin_integrity_status": " declared "},
            "origin_integrity_status must be canonical",
        ),
        (
            {"origin_integrity_status": "locally_attested"},
            "origin_integrity_status must be declared, verified_elsewhere, or verified_local",
        ),
        ({"failure_class": " interface_ambiguity "}, "failure_class must be canonical"),
        (
            {"first_permitted_future_versions": [" machine-v-next "]},
            "first_permitted_future_versions item must be canonical",
        ),
        (
            {"prohibited_retroactive_targets": [" protocol-v1 "]},
            "prohibited_retroactive_targets item must be canonical",
        ),
        ({"observation": " Confirmed failure."}, "observation must be canonical"),
        (
            {"observation": "Confirmed failure."},
            "observation uses report-prohibited",
        ),
        (
            {
                "strongest_alternative_explanation": (
                    "Validated that the interface caused the issue."
                )
            },
            "strongest_alternative_explanation uses report-prohibited",
        ),
        (
            {"challenged_invariant": "This proved a missing invariant."},
            "challenged_invariant uses report-prohibited",
        ),
        (
            {"proposed_repair": "Validated repair path."},
            "proposed_repair uses report-prohibited",
        ),
        (
            {"repair_falsifier": "Confirmed by the next validator."},
            "repair_falsifier uses report-prohibited",
        ),
        (
            {"conclusion_ceiling": "Explained the scientific result."},
            "conclusion_ceiling uses report-prohibited",
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
