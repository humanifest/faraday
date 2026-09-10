"""Semantic validation for append-only evidence correction histories."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from research_machine.application.policies import (
    require_canonical_bounded_report_text,
    require_sha256,
    require_text,
)
from research_machine.application.artifact_integrity import verify_run_artifacts
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import DatasetArtifact, EvidenceRecord, EvidenceStatusEvent


_STATUSES = {"active", "qualified", "withdrawn", "retracted"}


def _canonical_text(value: str | None, field: str) -> str:
    text = require_text(value, field)
    if text != value:
        raise ValidationError(f"{field} must be canonical without surrounding whitespace")
    return text


def _timestamp(value: str, field: str) -> datetime:
    _canonical_text(value, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValidationError(f"{field} must include a UTC offset")
    return parsed


def validate_evidence_status_event_chains(
    evidence: list[EvidenceRecord], events: list[EvidenceStatusEvent]
) -> dict[str, list[EvidenceStatusEvent]]:
    """Validate all chains and return them grouped by evidence ID."""
    evidence_by_id = {item.evidence_id: item for item in evidence}
    if len(evidence_by_id) != len(evidence):
        raise ValidationError("duplicate canonical evidence IDs prevent status validation")
    grouped: dict[str, list[EvidenceStatusEvent]] = defaultdict(list)
    event_ids: set[str] = set()
    for event in events:
        _canonical_text(event.event_id, "evidence status event_id")
        _canonical_text(event.evidence_id, "evidence status evidence_id")
        if event.supersedes_event_id is not None:
            _canonical_text(
                event.supersedes_event_id,
                "evidence status supersedes_event_id",
            )
        if event.event_id in event_ids:
            raise ValidationError(f"duplicate evidence status event_id: {event.event_id}")
        event_ids.add(event.event_id)
        if event.evidence_id not in evidence_by_id:
            raise ValidationError(
                f"evidence status event {event.event_id} references unknown evidence {event.evidence_id}"
            )
        grouped[event.evidence_id].append(event)

    validated: dict[str, list[EvidenceStatusEvent]] = {}
    for evidence_id, chain in grouped.items():
        ordered = sorted(chain, key=lambda item: item.sequence)
        evidence_created = _timestamp(
            evidence_by_id[evidence_id].created_at, "evidence created_at"
        )
        prior_effective: datetime | None = None
        prior_event_id: str | None = None
        terminal_seen = False
        for expected_sequence, event in enumerate(ordered, start=1):
            if event.sequence != expected_sequence:
                raise ValidationError(
                    f"evidence {evidence_id} status sequence must be contiguous from 1"
                )
            if event.supersedes_event_id != prior_event_id:
                raise ValidationError(
                    f"evidence {evidence_id} status chain must supersede the exact predecessor"
                )
            if terminal_seen:
                raise ValidationError(
                    f"evidence {evidence_id} has an event after terminal retraction"
                )
            status = _canonical_text(event.status, "evidence status")
            if status not in _STATUSES:
                raise ValidationError(
                    f"evidence status event {event.event_id} has an invalid status"
                )
            effective = _timestamp(event.effective_at, "evidence status effective_at")
            created = _timestamp(event.created_at, "evidence status created_at")
            if effective < evidence_created or effective > created:
                raise ValidationError(
                    f"evidence status event {event.event_id} has impossible chronology"
                )
            if prior_effective is not None and effective < prior_effective:
                raise ValidationError(
                    f"evidence {evidence_id} status effective time moves backward"
                )
            require_canonical_bounded_report_text(
                event.reason,
                "evidence status reason",
            )
            review_artifact_locator = _canonical_text(
                event.review_artifact_locator, "review artifact locator"
            )
            require_sha256(event.review_artifact_sha256, "review artifact SHA-256")
            artifact_root = _canonical_text(
                event.review_artifact_root, "review artifact root"
            )
            if not isinstance(event.artifact_integrity, dict) or event.artifact_integrity.get(
                "status"
            ) != "passed":
                raise ValidationError(
                    f"evidence status event {event.event_id} lacks passed artifact integrity"
                )
            current_integrity = verify_run_artifacts(
                [DatasetArtifact(
                    locator=review_artifact_locator,
                    sha256=event.review_artifact_sha256,
                )],
                artifact_root=artifact_root,
                actor=_canonical_text(event.created_by, "evidence status created_by"),
                analysis_code_hash="",
                run_metadata={},
                attestation_schema_path=None,
                expected_attestation_schema_sha256=None,
            ).to_dict()
            if current_integrity != event.artifact_integrity:
                raise ValidationError(
                    f"evidence status event {event.event_id} review artifact no longer matches its integrity receipt"
                )
            require_canonical_bounded_report_text(
                event.conclusion_ceiling,
                "evidence status conclusion ceiling",
            )
            terminal_seen = event.status == "retracted"
            prior_effective = effective
            prior_event_id = event.event_id
        validated[evidence_id] = ordered
    return validated


def currently_contributing_evidence(
    evidence: list[EvidenceRecord], events: list[EvidenceStatusEvent]
) -> tuple[list[EvidenceRecord], dict[str, list[EvidenceStatusEvent]]]:
    chains = validate_evidence_status_event_chains(evidence, events)
    contributing = [
        record
        for record in evidence
        if record.evidence_id not in chains
        or chains[record.evidence_id][-1].status == "active"
    ]
    return contributing, chains
