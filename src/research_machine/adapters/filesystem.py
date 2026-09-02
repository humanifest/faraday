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
    Claim,
    EvidenceRecord,
    Hypothesis,
    HypothesisWorkflowState,
    Inquiry,
    Question,
)

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")
_HYPOTHESIS_LOCATIONS = {
    HypothesisWorkflowState.UNREVIEWED.value: "drafts/hypotheses",
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
            "hypotheses/active",
            "hypotheses/parked",
            "hypotheses/retired",
            "datasets",
            "protocols/draft",
            "protocols/frozen",
            "runs",
            "evidence",
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
        ledger = self._inquiry_dir(inquiry_id) / "ledger.jsonl"
        previous_hash: str | None = None
        count = 0
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
        return {"valid": True, "events": count, "head_hash": previous_hash}

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
