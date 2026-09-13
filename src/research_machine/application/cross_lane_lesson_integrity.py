"""Payload commitments for cross-lane process lessons."""

from __future__ import annotations

import hashlib
import json

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import CrossLaneLesson


def _cross_lane_lesson_payload(
    lesson: CrossLaneLesson,
    *,
    include_origin_artifact_custody: bool = True,
) -> dict[str, object]:
    payload = lesson.to_dict()
    payload.pop("lesson_payload_sha256", None)
    if not include_origin_artifact_custody:
        payload.pop("origin_artifact_root", None)
        payload.pop("origin_artifact_integrity", None)
    return payload


def cross_lane_lesson_payload_sha256(lesson: CrossLaneLesson) -> str:
    """Commit the immutable lesson while excluding the commitment itself."""
    payload = _cross_lane_lesson_payload(lesson)
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def validate_cross_lane_lesson_payload_commitment(
    lesson: CrossLaneLesson,
    *,
    allow_ledger_verified_legacy_origin_custody_omission: bool = False,
) -> str | None:
    retained = lesson.lesson_payload_sha256
    if retained == "":
        return None
    expected = cross_lane_lesson_payload_sha256(lesson)
    if retained != expected:
        legacy_eligible = (
            allow_ledger_verified_legacy_origin_custody_omission
            and lesson.origin_artifact_root == ""
            and lesson.origin_artifact_integrity == {}
        )
        if legacy_eligible:
            legacy_expected = hashlib.sha256(
                json.dumps(
                    _cross_lane_lesson_payload(
                        lesson, include_origin_artifact_custody=False
                    ),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            if retained == legacy_expected:
                return retained
        raise ValidationError(
            f"cross-lane lesson {lesson.lesson_id} payload no longer matches its service-generated commitment"
        )
    return retained
