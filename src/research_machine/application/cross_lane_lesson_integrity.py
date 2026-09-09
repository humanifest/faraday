"""Payload commitments for cross-lane process lessons."""

from __future__ import annotations

import hashlib
import json

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import CrossLaneLesson


def cross_lane_lesson_payload_sha256(lesson: CrossLaneLesson) -> str:
    """Commit the immutable lesson while excluding the commitment itself."""
    payload = lesson.to_dict()
    payload.pop("lesson_payload_sha256", None)
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def validate_cross_lane_lesson_payload_commitment(
    lesson: CrossLaneLesson,
) -> str | None:
    retained = lesson.lesson_payload_sha256
    if retained == "":
        return None
    expected = cross_lane_lesson_payload_sha256(lesson)
    if retained != expected:
        raise ValidationError(
            f"cross-lane lesson {lesson.lesson_id} payload no longer matches its service-generated commitment"
        )
    return retained
