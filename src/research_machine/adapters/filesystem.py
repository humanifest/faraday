from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from research_machine.domain.errors import (
    ConflictError,
    IntegrityError,
    NotFoundError,
    ValidationError,
)
from research_machine.domain.models import (
    ActionRecommendation,
    AliasProxyMappingRecord,
    Claim,
    CrossLaneLesson,
    DatasetManifest,
    EvidenceRecord,
    EvidenceStatusEvent,
    EthicsReviewEvent,
    ExperimentProtocol,
    Hypothesis,
    HypothesisWorkflowState,
    Inquiry,
    Question,
    ResearchRun,
)

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")
_HYPOTHESIS_LOCATIONS = {
    HypothesisWorkflowState.UNREVIEWED.value: "drafts/hypotheses",
    HypothesisWorkflowState.PENDING_REVIEW.value: "hypotheses/pending_review",
    HypothesisWorkflowState.ACTIVE.value: "hypotheses/active",
    HypothesisWorkflowState.PARKED.value: "hypotheses/parked",
    HypothesisWorkflowState.RETIRED.value: "hypotheses/retired",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class FileSystemRepository:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    @property
    def workspace_file(self) -> Path:
        return self.root / "workspace.json"

    def is_initialized(self) -> bool:
        return self.workspace_file.is_file()

    def init_workspace(self, created_at: str) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "inquiries").mkdir(exist_ok=True)
        (self.root / "artifacts").mkdir(exist_ok=True)
        if self.workspace_file.exists():
            return self._read_json(self.workspace_file)
        config = {
            "schema_version": 1,
            "created_at": created_at,
            "active_inquiry_id": None,
            "inquiry_ids": [],
        }
        self._atomic_json(self.workspace_file, config)
        return config

    def require_initialized(self) -> None:
        if not self.is_initialized():
            raise NotFoundError(
                f"{self.root} is not a research workspace; run `workspace init` first"
            )

    def create_inquiry(self, inquiry: Inquiry) -> None:
        self.require_initialized()
        self._validate_id(inquiry.inquiry_id, "inquiry_id")
        directory = self._inquiry_dir(inquiry.inquiry_id)
        if directory.exists():
            raise ConflictError(f"inquiry {inquiry.inquiry_id} already exists")
        for relative in (
            "drafts/hypotheses",
            "hypotheses/pending_review",
            "hypotheses/active",
            "hypotheses/parked",
            "hypotheses/retired",
            "datasets",
            "protocols/draft",
            "protocols/frozen",
            "protocols/abandoned",
            "runs",
            "recommendations",
            "cross_lane_lessons",
            "evidence",
            "ethics_review_events",
            "alias_proxy_mapping_records",
            "evidence_status_events",
            "reports",
        ):
            (directory / relative).mkdir(parents=True, exist_ok=True)
        self._atomic_json(directory / "inquiry.json", inquiry.to_dict())
        self._atomic_json(directory / "questions.json", [])
        self._atomic_json(directory / "claims.json", [])
        (directory / "ledger.jsonl").touch(mode=0o600)

        config = self._read_json(self.workspace_file)
        config.setdefault("inquiry_ids", []).append(inquiry.inquiry_id)
        config["active_inquiry_id"] = inquiry.inquiry_id
        self._atomic_json(self.workspace_file, config)

    def resolve_inquiry_id(self, inquiry_id: str | None) -> str:
        self.require_initialized()
        if inquiry_id:
            self._validate_id(inquiry_id, "inquiry_id")
            if not self._inquiry_dir(inquiry_id).is_dir():
                raise NotFoundError(f"inquiry {inquiry_id} does not exist")
            return inquiry_id
        config = self._read_json(self.workspace_file)
        active = config.get("active_inquiry_id")
        if not active:
            raise NotFoundError("no active inquiry; create or select one")
        return str(active)

    def load_inquiry(self, inquiry_id: str) -> Inquiry:
        return Inquiry.from_dict(
            self._read_json(self._inquiry_dir(inquiry_id) / "inquiry.json")
        )

    def save_inquiry(self, inquiry: Inquiry) -> None:
        self._atomic_json(
            self._inquiry_dir(inquiry.inquiry_id) / "inquiry.json", inquiry.to_dict()
        )

    def set_active_inquiry(self, inquiry_id: str) -> None:
        resolved = self.resolve_inquiry_id(inquiry_id)
        config = self._read_json(self.workspace_file)
        config["active_inquiry_id"] = resolved
        self._atomic_json(self.workspace_file, config)

    def load_questions(self, inquiry_id: str) -> list[Question]:
        values = self._read_json(self._inquiry_dir(inquiry_id) / "questions.json")
        return [Question.from_dict(value) for value in values]

    def save_questions(self, inquiry_id: str, questions: list[Question]) -> None:
        self._atomic_json(
            self._inquiry_dir(inquiry_id) / "questions.json",
            [question.to_dict() for question in questions],
        )

    def load_claims(self, inquiry_id: str) -> list[Claim]:
        values = self._read_json(self._inquiry_dir(inquiry_id) / "claims.json")
        return [Claim.from_dict(value) for value in values]

    def save_claims(self, inquiry_id: str, claims: list[Claim]) -> None:
        self._atomic_json(
            self._inquiry_dir(inquiry_id) / "claims.json",
            [claim.to_dict() for claim in claims],
        )

    def save_hypothesis(self, inquiry_id: str, hypothesis: Hypothesis) -> None:
        location = _HYPOTHESIS_LOCATIONS[hypothesis.workflow_state.value]
        path = (
            self._inquiry_dir(inquiry_id)
            / location
            / f"{hypothesis.hypothesis_id}.json"
        )
        self._atomic_json(path, hypothesis.to_dict())

    def find_hypothesis(self, inquiry_id: str, hypothesis_id: str) -> Hypothesis:
        self._validate_id(hypothesis_id, "hypothesis_id")
        base = self._inquiry_dir(inquiry_id)
        for location in _HYPOTHESIS_LOCATIONS.values():
            path = base / location / f"{hypothesis_id}.json"
            if path.is_file():
                return Hypothesis.from_dict(self._read_json(path))
        raise NotFoundError(f"hypothesis {hypothesis_id} does not exist")

    def move_hypothesis(
        self, inquiry_id: str, hypothesis: Hypothesis, destination: str
    ) -> None:
        if destination not in _HYPOTHESIS_LOCATIONS:
            raise ValidationError(f"unknown hypothesis destination {destination}")
        base = self._inquiry_dir(inquiry_id)
        existing: Path | None = None
        for location in _HYPOTHESIS_LOCATIONS.values():
            candidate = base / location / f"{hypothesis.hypothesis_id}.json"
            if candidate.is_file():
                existing = candidate
                break
        if existing is None:
            raise NotFoundError(f"hypothesis {hypothesis.hypothesis_id} does not exist")
        target = (
            base
            / _HYPOTHESIS_LOCATIONS[destination]
            / f"{hypothesis.hypothesis_id}.json"
        )
        self._atomic_json(target, hypothesis.to_dict())
        if existing != target:
            existing.unlink()

    def list_hypotheses(
        self, inquiry_id: str, state: str | None = None
    ) -> list[Hypothesis]:
        base = self._inquiry_dir(inquiry_id)
        if state:
            if state not in _HYPOTHESIS_LOCATIONS:
                raise ValidationError(f"unknown hypothesis state {state}")
            locations = [_HYPOTHESIS_LOCATIONS[state]]
        else:
            locations = list(_HYPOTHESIS_LOCATIONS.values())
        hypotheses: list[Hypothesis] = []
        for location in locations:
            for path in sorted((base / location).glob("*.json")):
                hypotheses.append(Hypothesis.from_dict(self._read_json(path)))
        return sorted(
            hypotheses, key=lambda item: (item.created_at, item.hypothesis_id)
        )

    def save_evidence(self, inquiry_id: str, evidence: EvidenceRecord) -> None:
        path = (
            self._inquiry_dir(inquiry_id) / "evidence" / f"{evidence.evidence_id}.json"
        )
        if path.exists():
            raise ConflictError(f"evidence {evidence.evidence_id} already exists")
        self._atomic_json(path, evidence.to_dict())

    def list_evidence(self, inquiry_id: str) -> list[EvidenceRecord]:
        directory = self._inquiry_dir(inquiry_id) / "evidence"
        return [
            EvidenceRecord.from_dict(self._read_json(path))
            for path in sorted(directory.glob("*.json"))
        ]

    def save_evidence_status_event(
        self, inquiry_id: str, event: EvidenceStatusEvent
    ) -> None:
        self._validate_id(event.event_id, "evidence status event_id")
        directory = self._inquiry_dir(inquiry_id) / "evidence_status_events"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{event.event_id}.json"
        if path.exists():
            raise ConflictError(f"evidence status event {event.event_id} already exists")
        self._atomic_json(path, event.to_dict())

    def list_evidence_status_events(
        self, inquiry_id: str, evidence_id: str | None = None
    ) -> list[EvidenceStatusEvent]:
        directory = self._inquiry_dir(inquiry_id) / "evidence_status_events"
        if not directory.is_dir():
            return []
        events = [
            EvidenceStatusEvent.from_dict(self._read_json(path))
            for path in sorted(directory.glob("*.json"))
        ]
        if evidence_id is not None:
            events = [item for item in events if item.evidence_id == evidence_id]
        return sorted(events, key=lambda item: (item.evidence_id, item.sequence))

    def save_dataset(self, inquiry_id: str, dataset: DatasetManifest) -> None:
        self._validate_id(dataset.dataset_id, "dataset_id")
        path = self._inquiry_dir(inquiry_id) / "datasets" / f"{dataset.dataset_id}.json"
        if path.exists():
            raise ConflictError(f"dataset {dataset.dataset_id} already exists")
        self._atomic_json(path, dataset.to_dict())

    def find_dataset(self, inquiry_id: str, dataset_id: str) -> DatasetManifest:
        self._validate_id(dataset_id, "dataset_id")
        path = self._inquiry_dir(inquiry_id) / "datasets" / f"{dataset_id}.json"
        if not path.is_file():
            raise NotFoundError(f"dataset {dataset_id} does not exist")
        return DatasetManifest.from_dict(self._read_json(path))

    def list_datasets(self, inquiry_id: str) -> list[DatasetManifest]:
        directory = self._inquiry_dir(inquiry_id) / "datasets"
        datasets = [
            DatasetManifest.from_dict(self._read_json(path))
            for path in sorted(directory.glob("*.json"))
        ]
        return sorted(datasets, key=lambda item: (item.created_at, item.dataset_id))

    def save_protocol(self, inquiry_id: str, protocol: ExperimentProtocol) -> None:
        self._validate_id(protocol.protocol_id, "protocol_id")
        try:
            self.find_protocol(inquiry_id, protocol.protocol_id)
        except NotFoundError:
            pass
        else:
            raise ConflictError(f"protocol {protocol.protocol_id} already exists")
        path = (
            self._inquiry_dir(inquiry_id)
            / "protocols"
            / "draft"
            / f"{protocol.protocol_id}.json"
        )
        self._atomic_json(path, protocol.to_dict())

    def find_protocol(self, inquiry_id: str, protocol_id: str) -> ExperimentProtocol:
        self._validate_id(protocol_id, "protocol_id")
        base = self._inquiry_dir(inquiry_id) / "protocols"
        for status in ("draft", "frozen", "abandoned"):
            path = base / status / f"{protocol_id}.json"
            if path.is_file():
                return ExperimentProtocol.from_dict(self._read_json(path))
        raise NotFoundError(f"protocol {protocol_id} does not exist")

    def freeze_protocol(self, inquiry_id: str, protocol: ExperimentProtocol) -> None:
        base = self._inquiry_dir(inquiry_id) / "protocols"
        draft = base / "draft" / f"{protocol.protocol_id}.json"
        frozen = base / "frozen" / f"{protocol.protocol_id}.json"
        if not draft.is_file():
            raise NotFoundError(f"draft protocol {protocol.protocol_id} does not exist")
        if frozen.exists():
            raise ConflictError(
                f"frozen protocol {protocol.protocol_id} already exists"
            )
        self._atomic_json(frozen, protocol.to_dict())
        draft.unlink()

    def list_protocols(self, inquiry_id: str) -> list[ExperimentProtocol]:
        base = self._inquiry_dir(inquiry_id) / "protocols"
        protocols: list[ExperimentProtocol] = []
        for status in ("draft", "frozen", "abandoned"):
            protocols.extend(
                ExperimentProtocol.from_dict(self._read_json(path))
                for path in sorted((base / status).glob("*.json"))
            )
        return sorted(
            protocols,
            key=lambda item: (item.protocol_family_id, item.version),
        )

    def save_alias_proxy_mapping_record(
        self, inquiry_id: str, record: AliasProxyMappingRecord
    ) -> None:
        self._validate_id(record.record_id, "alias proxy mapping record_id")
        directory = self._inquiry_dir(inquiry_id) / "alias_proxy_mapping_records"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{record.record_id}.json"
        if path.exists():
            raise ConflictError(
                f"alias/proxy mapping record {record.record_id} already exists"
            )
        self._atomic_json(path, record.to_dict())

    def list_alias_proxy_mapping_records(
        self, inquiry_id: str, protocol_id: str | None = None
    ) -> list[AliasProxyMappingRecord]:
        directory = self._inquiry_dir(inquiry_id) / "alias_proxy_mapping_records"
        if not directory.is_dir():
            return []
        records = [
            AliasProxyMappingRecord.from_dict(self._read_json(path))
            for path in sorted(directory.glob("*.json"))
        ]
        if protocol_id is not None:
            records = [item for item in records if item.protocol_id == protocol_id]
        return sorted(records, key=lambda item: (item.protocol_id, item.record_id))

    def save_run(self, inquiry_id: str, run: ResearchRun) -> None:
        self._validate_id(run.run_id, "run_id")
        path = self._inquiry_dir(inquiry_id) / "runs" / f"{run.run_id}.json"
        if path.exists():
            raise ConflictError(f"run {run.run_id} already exists")
        self._atomic_json(path, run.to_dict())

    def find_run(self, inquiry_id: str, run_id: str) -> ResearchRun:
        self._validate_id(run_id, "run_id")
        path = self._inquiry_dir(inquiry_id) / "runs" / f"{run_id}.json"
        if not path.is_file():
            raise NotFoundError(f"run {run_id} does not exist")
        return ResearchRun.from_dict(self._read_json(path))

    def list_runs(self, inquiry_id: str) -> list[ResearchRun]:
        directory = self._inquiry_dir(inquiry_id) / "runs"
        runs = [
            ResearchRun.from_dict(self._read_json(path))
            for path in sorted(directory.glob("*.json"))
        ]
        return sorted(runs, key=lambda item: (item.completed_at, item.run_id))

    def save_recommendation(
        self, inquiry_id: str, recommendation: ActionRecommendation
    ) -> None:
        self._validate_id(recommendation.recommendation_id, "recommendation_id")
        path = (
            self._inquiry_dir(inquiry_id)
            / "recommendations"
            / f"{recommendation.recommendation_id}.json"
        )
        if path.exists():
            raise ConflictError(
                f"recommendation {recommendation.recommendation_id} already exists"
            )
        self._atomic_json(path, recommendation.to_dict())

    def list_recommendations(self, inquiry_id: str) -> list[ActionRecommendation]:
        directory = self._inquiry_dir(inquiry_id) / "recommendations"
        recommendations = [
            ActionRecommendation.from_dict(self._read_json(path))
            for path in sorted(directory.glob("*.json"))
        ]
        return sorted(
            recommendations,
            key=lambda item: (item.created_at, item.recommendation_id),
        )

    def save_cross_lane_lesson(
        self, inquiry_id: str, lesson: CrossLaneLesson
    ) -> None:
        self._validate_id(lesson.lesson_id, "lesson_id")
        path = (
            self._inquiry_dir(inquiry_id)
            / "cross_lane_lessons"
            / f"{lesson.lesson_id}.json"
        )
        if path.exists():
            raise ConflictError(f"cross-lane lesson {lesson.lesson_id} already exists")
        self._atomic_json(path, lesson.to_dict())

    def list_cross_lane_lessons(self, inquiry_id: str) -> list[CrossLaneLesson]:
        directory = self._inquiry_dir(inquiry_id) / "cross_lane_lessons"
        if not directory.is_dir():
            return []
        lessons = [
            CrossLaneLesson.from_dict(self._read_json(path))
            for path in sorted(directory.glob("*.json"))
        ]
        return sorted(lessons, key=lambda item: (item.created_at, item.lesson_id))

    def verify_cross_lane_lesson_integrity(
        self,
        inquiry_id: str,
        lesson: CrossLaneLesson,
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Bind a lesson projection to its unique hash-verified record event."""

        verified_events = (
            events if events is not None else self._verified_ledger_events(inquiry_id)
        )
        payload = self._creation_payload(
            verified_events,
            command="cross-lane-lesson.record",
            aggregate_type="cross_lane_lesson",
            aggregate_id=lesson.lesson_id,
        )
        path = (
            self._inquiry_dir(inquiry_id)
            / "cross_lane_lessons"
            / f"{lesson.lesson_id}.json"
        )
        current_payload = self._read_json(path)
        derived_fields = {
            "transfer_authority_status",
            "current_transfer_authority",
            "report_prose_findings",
        }
        if derived_fields.intersection(payload):
            raise IntegrityError(
                f"cross-lane lesson {lesson.lesson_id} persists derived transfer authority"
            )
        if (
            current_payload != payload
            or CrossLaneLesson.from_dict(payload) != lesson
        ):
            raise IntegrityError(
                f"cross-lane lesson {lesson.lesson_id} differs from its record event"
            )
        retained = payload.get("lesson_payload_sha256", "")
        legacy_origin_custody_omission_verified = False
        if retained:
            if not isinstance(retained, str) or not re.fullmatch(
                r"[0-9a-f]{64}", retained
            ):
                raise IntegrityError(
                    f"cross-lane lesson {lesson.lesson_id} has an invalid payload commitment"
                )
            committed_payload = dict(payload)
            committed_payload.pop("lesson_payload_sha256", None)
            expected = hashlib.sha256(
                canonical_json(committed_payload).encode("utf-8")
            ).hexdigest()
            if retained != expected:
                raise IntegrityError(
                    f"cross-lane lesson {lesson.lesson_id} payload no longer "
                    "matches its service-generated commitment"
                )
            legacy_origin_custody_omission_verified = (
                "origin_artifact_root" not in payload
                and "origin_artifact_integrity" not in payload
                and lesson.origin_artifact_root == ""
                and lesson.origin_artifact_integrity == {}
            )
        return {
            "status": (
                "ledger_bound_with_payload_commitment"
                if retained
                else "ledger_bound_without_payload_commitment"
            ),
            "lesson_id": lesson.lesson_id,
            "payload_commitment_present": bool(retained),
            "legacy_origin_custody_omission_verified": (
                legacy_origin_custody_omission_verified
            ),
        }

    def save_ethics_review_event(
        self, inquiry_id: str, event: EthicsReviewEvent
    ) -> None:
        self._validate_id(event.event_id, "ethics review event_id")
        directory = self._inquiry_dir(inquiry_id) / "ethics_review_events"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{event.event_id}.json"
        if path.exists():
            raise ConflictError(f"ethics review event {event.event_id} already exists")
        self._atomic_json(path, event.to_dict())

    def list_ethics_review_events(
        self, inquiry_id: str, protocol_id: str | None = None
    ) -> list[EthicsReviewEvent]:
        directory = self._inquiry_dir(inquiry_id) / "ethics_review_events"
        if not directory.is_dir():
            return []
        events = [
            EthicsReviewEvent.from_dict(self._read_json(path))
            for path in sorted(directory.glob("*.json"))
        ]
        if protocol_id is not None:
            events = [item for item in events if item.protocol_id == protocol_id]
        return sorted(events, key=lambda item: item.sequence)

    def write_report(self, inquiry_id: str, name: str, content: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", name):
            raise ValidationError("report name contains unsafe characters")
        relative = Path("inquiries") / inquiry_id / "reports" / name
        path = self.root / relative
        self._atomic_text(path, content)
        return str(relative)

    def append_event(
        self,
        inquiry_id: str,
        *,
        timestamp: str,
        actor: str,
        command: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        ledger = self._inquiry_dir(inquiry_id) / "ledger.jsonl"
        last = self._last_ledger_event(ledger)
        body = {
            "sequence": 1 if last is None else int(last["sequence"]) + 1,
            "event_id": f"evt-{uuid.uuid4().hex[:16]}",
            "timestamp": timestamp,
            "actor": actor,
            "command": command,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "payload": payload,
            "previous_hash": None if last is None else last["event_hash"],
        }
        event = dict(body)
        event["event_hash"] = hashlib.sha256(
            canonical_json(body).encode("utf-8")
        ).hexdigest()
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def verify_ledger(self, inquiry_id: str) -> dict[str, Any]:
        events = self._verified_ledger_events(inquiry_id)
        return {
            "valid": True,
            "events": len(events),
            "head_hash": events[-1]["event_hash"] if events else None,
        }

    def _verified_ledger_events(self, inquiry_id: str) -> list[dict[str, Any]]:
        ledger = self._inquiry_dir(inquiry_id) / "ledger.jsonl"
        previous_hash: str | None = None
        count = 0
        events: list[dict[str, Any]] = []
        with ledger.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise IntegrityError(
                        f"ledger line {line_number} is not valid JSON"
                    ) from exc
                count += 1
                if event.get("sequence") != count:
                    raise IntegrityError(
                        f"ledger sequence mismatch at line {line_number}"
                    )
                if event.get("previous_hash") != previous_hash:
                    raise IntegrityError(f"ledger chain mismatch at line {line_number}")
                body = {
                    key: value for key, value in event.items() if key != "event_hash"
                }
                expected = hashlib.sha256(
                    canonical_json(body).encode("utf-8")
                ).hexdigest()
                if event.get("event_hash") != expected:
                    raise IntegrityError(
                        f"ledger event hash mismatch at line {line_number}"
                    )
                previous_hash = expected
                events.append(event)
        return events

    @staticmethod
    def _creation_payload(
        events: list[dict[str, Any]],
        *,
        command: str,
        aggregate_type: str,
        aggregate_id: str,
    ) -> dict[str, Any]:
        matches = [
            event
            for event in events
            if event.get("command") == command
            and event.get("aggregate_type") == aggregate_type
            and event.get("aggregate_id") == aggregate_id
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("payload"), dict):
            raise IntegrityError(
                f"legacy {aggregate_type} {aggregate_id} does not have exactly one "
                f"hash-verified {command} event"
            )
        return matches[0]["payload"]

    def verify_legacy_protocol_integrity(
        self,
        inquiry_id: str,
        protocol: ExperimentProtocol,
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Validate a pre-hypothesis-commitment protocol against its sealed event.

        Modern model defaults cannot safely reconstruct the historical hash input.
        The hash-verified freeze event is therefore the only authoritative v0.8
        serialization, and the current projection must match it exactly.
        """

        if protocol.hypothesis_commitments:
            raise IntegrityError(
                f"protocol {protocol.protocol_id} is not a legacy uncommitted protocol"
            )
        verified_events = (
            events if events is not None else self._verified_ledger_events(inquiry_id)
        )
        payload = self._creation_payload(
            verified_events,
            command="protocol.freeze",
            aggregate_type="protocol",
            aggregate_id=protocol.protocol_id,
        )
        recorded = ExperimentProtocol.from_dict(payload)
        if recorded.hypothesis_commitments:
            raise IntegrityError(
                f"protocol {protocol.protocol_id} lost its hypothesis commitments"
            )
        path = (
            self._inquiry_dir(inquiry_id)
            / "protocols"
            / "frozen"
            / f"{protocol.protocol_id}.json"
        )
        current_payload = self._read_json(path)
        if current_payload != payload:
            raise IntegrityError(
                f"legacy protocol {protocol.protocol_id} differs from its freeze event"
            )
        committed_payload = dict(payload)
        for field_name in (
            "status",
            "protocol_hash",
            "registration_timestamp",
            "external_anchor",
        ):
            committed_payload.pop(field_name, None)
        legacy_commitment = hashlib.sha256(
            canonical_json(committed_payload).encode("utf-8")
        ).hexdigest()
        if not protocol.protocol_hash or legacy_commitment != protocol.protocol_hash:
            raise IntegrityError(
                f"legacy protocol {protocol.protocol_id} does not match its v0.8 commitment"
            )
        return {
            "status": "legacy_protocol_without_prospective_hypothesis_commitments",
            "protocol_id": protocol.protocol_id,
            "protocol_hash": protocol.protocol_hash,
            "new_runs_or_evidence_permitted": False,
        }

    def verify_legacy_evidence_integrity(
        self,
        inquiry_id: str,
        evidence: EvidenceRecord,
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Bind a pre-admission-receipt record to its hash-verified ledger event."""

        if evidence.admission_checks:
            raise IntegrityError(
                f"evidence {evidence.evidence_id} is not a legacy unreceipted record"
            )
        verified_events = (
            events if events is not None else self._verified_ledger_events(inquiry_id)
        )
        payload = self._creation_payload(
            verified_events,
            command="evidence.record",
            aggregate_type="evidence",
            aggregate_id=evidence.evidence_id,
        )
        recorded = EvidenceRecord.from_dict(payload)
        if recorded.admission_checks:
            raise IntegrityError(
                f"legacy evidence {evidence.evidence_id} lost its admission receipt"
            )
        path = (
            self._inquiry_dir(inquiry_id)
            / "evidence"
            / f"{evidence.evidence_id}.json"
        )
        if self._read_json(path) != payload or recorded.to_dict() != evidence.to_dict():
            raise IntegrityError(
                f"legacy evidence {evidence.evidence_id} differs from its record event"
            )
        return {
            "status": "legacy_evidence_without_admission_receipt",
            "evidence_id": evidence.evidence_id,
            "current_scientific_admission": False,
        }

    def verify_legacy_recommendation_integrity(
        self,
        inquiry_id: str,
        recommendation: ActionRecommendation,
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Preserve an uncommitted historical selection without upgrading it."""

        if recommendation.recommendation_payload_sha256:
            raise IntegrityError(
                f"recommendation {recommendation.recommendation_id} is not legacy"
            )
        verified_events = (
            events if events is not None else self._verified_ledger_events(inquiry_id)
        )
        payload = self._recommendation_selection_payload(
            verified_events, recommendation.recommendation_id
        )
        if payload.get("recommendation_payload_sha256"):
            raise IntegrityError(
                f"recommendation {recommendation.recommendation_id} has a "
                "modern committed selection event"
            )
        path = (
            self._inquiry_dir(inquiry_id)
            / "recommendations"
            / f"{recommendation.recommendation_id}.json"
        )
        if self._read_json(path) != payload:
            raise IntegrityError(
                f"legacy recommendation {recommendation.recommendation_id} "
                "differs from its selection event"
            )
        return {
            "status": "legacy_recommendation_without_payload_commitment",
            "recommendation_id": recommendation.recommendation_id,
            "current_selection_authority": False,
        }

    def verify_historical_recommendation_integrity(
        self,
        inquiry_id: str,
        recommendation: ActionRecommendation,
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Bind a versioned historical score record to its exact ledger event."""

        if recommendation.score_contract_version != 1:
            raise IntegrityError(
                f"recommendation {recommendation.recommendation_id} is not historical"
            )
        verified_events = (
            events if events is not None else self._verified_ledger_events(inquiry_id)
        )
        payload = self._recommendation_selection_payload(
            verified_events, recommendation.recommendation_id
        )
        if payload.get("score_contract_version", 1) != 1:
            raise IntegrityError(
                f"historical recommendation {recommendation.recommendation_id} "
                "has a nonhistorical score contract event"
            )
        path = (
            self._inquiry_dir(inquiry_id)
            / "recommendations"
            / f"{recommendation.recommendation_id}.json"
        )
        if self._read_json(path) != payload:
            raise IntegrityError(
                f"historical recommendation {recommendation.recommendation_id} "
                "differs from its selection event"
            )
        return {
            "status": "historical_recommendation_score_contract_v1",
            "recommendation_id": recommendation.recommendation_id,
            "current_selection_authority": False,
        }

    def verify_current_recommendation_integrity(
        self,
        inquiry_id: str,
        recommendation: ActionRecommendation,
        *,
        expected_score_contract_version: int,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Bind a current recommendation to its exact hash-verified event."""

        if recommendation.score_contract_version != expected_score_contract_version:
            raise IntegrityError(
                f"recommendation {recommendation.recommendation_id} is not current"
            )
        verified_events = (
            events if events is not None else self._verified_ledger_events(inquiry_id)
        )
        payload = self._recommendation_selection_payload(
            verified_events, recommendation.recommendation_id
        )
        if payload.get("score_contract_version") != expected_score_contract_version:
            raise IntegrityError(
                f"current recommendation {recommendation.recommendation_id} "
                "score contract differs from its selection event"
            )
        path = (
            self._inquiry_dir(inquiry_id)
            / "recommendations"
            / f"{recommendation.recommendation_id}.json"
        )
        if self._read_json(path) != payload:
            raise IntegrityError(
                f"current recommendation {recommendation.recommendation_id} "
                "differs from its selection event"
            )
        return {
            "status": "current_recommendation_event_bound",
            "recommendation_id": recommendation.recommendation_id,
            "score_contract_version": expected_score_contract_version,
        }

    def has_legacy_recommendation_event(
        self, inquiry_id: str, recommendation_id: str
    ) -> bool:
        payload = self._recommendation_selection_payload(
            self._verified_ledger_events(inquiry_id), recommendation_id
        )
        return not bool(payload.get("recommendation_payload_sha256"))

    @staticmethod
    def _recommendation_selection_payload(
        events: list[dict[str, Any]], recommendation_id: str
    ) -> dict[str, Any]:
        matches = [
            event
            for event in events
            if event.get("command")
            in {"next-action.recommend", "next-action.portfolio"}
            and event.get("aggregate_type") == "recommendation"
            and event.get("aggregate_id") == recommendation_id
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("payload"), dict):
            raise IntegrityError(
                f"recommendation {recommendation_id} does not have exactly one "
                "hash-verified selection event"
            )
        return matches[0]["payload"]

    def _inquiry_dir(self, inquiry_id: str) -> Path:
        self._validate_id(inquiry_id, "inquiry_id")
        return self.root / "inquiries" / inquiry_id

    @staticmethod
    def _validate_id(value: str, field_name: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise ValidationError(
                f"{field_name} must contain lowercase letters, digits, and hyphens only"
            )

    @staticmethod
    def _read_json(path: Path) -> Any:
        if not path.is_file():
            raise NotFoundError(f"required file does not exist: {path}")
        try:
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise IntegrityError(f"invalid JSON in {path}") from exc

    @staticmethod
    def _atomic_json(path: Path, value: Any) -> None:
        content = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        FileSystemRepository._atomic_text(path, content)

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _last_ledger_event(path: Path) -> dict[str, Any] | None:
        last: dict[str, Any] | None = None
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = json.loads(line)
        return last
