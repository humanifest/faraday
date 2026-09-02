from __future__ import annotations

from typing import Any, Protocol

from research_machine.domain.models import (
    Claim,
    EvidenceRecord,
    Hypothesis,
    Inquiry,
    Question,
)


class WorkspaceRepository(Protocol):
    def init_workspace(self, created_at: str) -> dict[str, Any]: ...

    def is_initialized(self) -> bool: ...

    def create_inquiry(self, inquiry: Inquiry) -> None: ...

    def resolve_inquiry_id(self, inquiry_id: str | None) -> str: ...

    def load_inquiry(self, inquiry_id: str) -> Inquiry: ...

    def save_inquiry(self, inquiry: Inquiry) -> None: ...

    def set_active_inquiry(self, inquiry_id: str) -> None: ...

    def load_questions(self, inquiry_id: str) -> list[Question]: ...

    def save_questions(self, inquiry_id: str, questions: list[Question]) -> None: ...

    def load_claims(self, inquiry_id: str) -> list[Claim]: ...

    def save_claims(self, inquiry_id: str, claims: list[Claim]) -> None: ...

    def save_hypothesis(self, inquiry_id: str, hypothesis: Hypothesis) -> None: ...

    def find_hypothesis(self, inquiry_id: str, hypothesis_id: str) -> Hypothesis: ...

    def move_hypothesis(
        self, inquiry_id: str, hypothesis: Hypothesis, destination: str
    ) -> None: ...

    def list_hypotheses(
        self, inquiry_id: str, state: str | None = None
    ) -> list[Hypothesis]: ...

    def save_evidence(self, inquiry_id: str, evidence: EvidenceRecord) -> None: ...

    def list_evidence(self, inquiry_id: str) -> list[EvidenceRecord]: ...

    def write_report(self, inquiry_id: str, name: str, content: str) -> str: ...

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
    ) -> dict[str, Any]: ...

    def verify_ledger(self, inquiry_id: str) -> dict[str, Any]: ...
