from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateInquiry,
    ProposeHypothesis,
    RecordEvidence,
    RetireHypothesis,
)
from research_machine.application.policies import (
    normalize_text,
    require_text,
    require_text_list,
    validate_evidence_target,
    validate_hypothesis_activation,
)
from research_machine.domain.errors import ConflictError, NotFoundError, ValidationError
from research_machine.domain.models import (
    Claim,
    EvidenceAssessment,
    EvidenceRecord,
    Hypothesis,
    HypothesisWorkflowState,
    Inquiry,
    Question,
    QuestionStatus,
    RejectionType,
)
from research_machine.ports.repository import WorkspaceRepository
from research_machine.reporting.synthesis import build_synthesis


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "inquiry"


class ResearchService:
    def __init__(
        self,
        repository: WorkspaceRepository,
        *,
        actor: str = "codex",
        clock: Callable[[], str] = utc_now,
        token: Callable[[], str] | None = None,
    ):
        self.repository = repository
        self.actor = require_text(actor, "actor")
        self.clock = clock
        self.token = token or (lambda: uuid.uuid4().hex[:12])

    def init_workspace(self) -> dict[str, Any]:
        return self.repository.init_workspace(self.clock())

    def create_inquiry(self, command: CreateInquiry) -> Inquiry:
        title = require_text(command.title, "title")
        statement = require_text(command.initial_statement, "initial_statement")
        inquiry_id = command.inquiry_id or f"{_slugify(title)[:54]}-{self.token()[:8]}"
        inquiry = Inquiry(
            inquiry_id=inquiry_id,
            title=title,
            initial_statement=statement,
            created_at=self.clock(),
        )
        self.repository.create_inquiry(inquiry)
        self._event(
            inquiry_id,
            "inquiry.create",
            "inquiry",
            inquiry_id,
            inquiry.to_dict(),
        )
        return inquiry

    def select_inquiry(self, inquiry_id: str) -> Inquiry:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        self.repository.set_active_inquiry(resolved)
        inquiry = self.repository.load_inquiry(resolved)
        self._event(
            resolved,
            "inquiry.select",
            "inquiry",
            resolved,
            {"active_inquiry_id": resolved},
        )
        return inquiry

    def show_inquiry(self, inquiry_id: str | None = None) -> dict[str, Any]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return {
            "inquiry": self.repository.load_inquiry(resolved).to_dict(),
            "questions": [
                item.to_dict() for item in self.repository.load_questions(resolved)
            ],
            "claims": [
                item.to_dict() for item in self.repository.load_claims(resolved)
            ],
            "hypotheses": [
                item.to_dict() for item in self.repository.list_hypotheses(resolved)
            ],
            "evidence": [
                item.to_dict() for item in self.repository.list_evidence(resolved)
            ],
        }

    def add_question(
        self, command: AddQuestion, inquiry_id: str | None = None
    ) -> Question:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        question = Question(
            question_id=f"q-{self.token()}",
            text=require_text(command.text, "question"),
            created_at=self.clock(),
        )
        questions = self.repository.load_questions(resolved)
        questions.append(question)
        self.repository.save_questions(resolved, questions)
        self._event(
            resolved,
            "question.add",
            "question",
            question.question_id,
            question.to_dict(),
        )
        return question

    def answer_question(
        self, question_id: str, answer: str, inquiry_id: str | None = None
    ) -> Question:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        questions = self.repository.load_questions(resolved)
        for index, question in enumerate(questions):
            if question.question_id == question_id:
                updated = replace(
                    question,
                    answer=require_text(answer, "answer"),
                    status=QuestionStatus.ANSWERED,
                    answered_at=self.clock(),
                )
                questions[index] = updated
                self.repository.save_questions(resolved, questions)
                self._event(
                    resolved,
                    "question.answer",
                    "question",
                    question_id,
                    updated.to_dict(),
                )
                return updated
        raise NotFoundError(f"question {question_id} does not exist")

    def add_claim(self, command: AddClaim, inquiry_id: str | None = None) -> Claim:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        claims = self.repository.load_claims(resolved)
        parent_claims = require_text_list(command.parent_claims, "parent_claims")
        known = {claim.claim_id for claim in claims}
        missing = sorted(set(parent_claims) - known)
        if missing:
            raise ValidationError("unknown parent claims: " + ", ".join(missing))
        claim = Claim(
            claim_id=f"clm-{self.token()}",
            statement=require_text(command.statement, "claim statement"),
            level=command.level,
            created_at=self.clock(),
            parent_claims=parent_claims,
            scope=normalize_text(command.scope, "scope"),
        )
        claims.append(claim)
        self.repository.save_claims(resolved, claims)
        self._event(
            resolved,
            "claim.add",
            "claim",
            claim.claim_id,
            claim.to_dict(),
        )
        return claim

    def propose_hypothesis(
        self, command: ProposeHypothesis, inquiry_id: str | None = None
    ) -> Hypothesis:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        parent_claims = require_text_list(command.parent_claims, "parent_claims")
        lineage = require_text_list(command.lineage, "lineage")
        claims = {claim.claim_id for claim in self.repository.load_claims(resolved)}
        missing_claims = sorted(set(parent_claims) - claims)
        if missing_claims:
            raise ValidationError("unknown parent claims: " + ", ".join(missing_claims))
        known_hypotheses = {
            hypothesis.hypothesis_id
            for hypothesis in self.repository.list_hypotheses(resolved)
        }
        missing_lineage = sorted(set(lineage) - known_hypotheses)
        if missing_lineage:
            raise ValidationError(
                "unknown lineage hypotheses: " + ", ".join(missing_lineage)
            )
        if command.required_replications is not None and (
            isinstance(command.required_replications, bool)
            or not isinstance(command.required_replications, int)
            or command.required_replications < 0
        ):
            raise ValidationError(
                "required_replications must be a non-negative integer or null"
            )
        hypothesis = Hypothesis(
            hypothesis_id=f"hyp-{self.token()}",
            statement=require_text(command.statement, "hypothesis statement"),
            created_at=self.clock(),
            generated_by=require_text(command.generated_by, "generated_by"),
            parent_claims=parent_claims,
            lineage=lineage,
            source_context=require_text_list(command.source_context, "source_context"),
            scope=normalize_text(command.scope, "scope"),
            observable_prediction=normalize_text(
                command.observable_prediction, "observable_prediction"
            ),
            null_model=normalize_text(command.null_model, "null_model"),
            competing_models=require_text_list(
                command.competing_models, "competing_models"
            ),
            causal_direction=normalize_text(
                command.causal_direction, "causal_direction"
            ),
            primary_estimand=normalize_text(
                command.primary_estimand, "primary_estimand"
            ),
            expected_effect_direction=normalize_text(
                command.expected_effect_direction, "expected_effect_direction"
            ),
            time_window=normalize_text(command.time_window, "time_window"),
            covariates=require_text_list(command.covariates, "covariates"),
            known_confounds=require_text_list(
                command.known_confounds, "known_confounds"
            ),
            falsification_conditions=require_text_list(
                command.falsification_conditions, "falsification_conditions"
            ),
            support_conditions=require_text_list(
                command.support_conditions, "support_conditions"
            ),
            boundary_conditions=require_text_list(
                command.boundary_conditions, "boundary_conditions"
            ),
            required_replications=command.required_replications,
        )
        self.repository.save_hypothesis(resolved, hypothesis)
        self._event(
            resolved,
            "hypothesis.propose",
            "hypothesis",
            hypothesis.hypothesis_id,
            hypothesis.to_dict(),
        )
        return hypothesis

    def activate_hypothesis(
        self, hypothesis_id: str, inquiry_id: str | None = None
    ) -> Hypothesis:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        hypothesis = self.repository.find_hypothesis(resolved, hypothesis_id)
        validate_hypothesis_activation(hypothesis)
        activated = replace(
            hypothesis,
            workflow_state=HypothesisWorkflowState.ACTIVE,
            activated_at=self.clock(),
            retirement=None,
        )
        self.repository.move_hypothesis(resolved, activated, "active")
        self._event(
            resolved,
            "hypothesis.activate",
            "hypothesis",
            hypothesis_id,
            activated.to_dict(),
        )
        return activated

    def retire_hypothesis(
        self, command: RetireHypothesis, inquiry_id: str | None = None
    ) -> Hypothesis:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        hypothesis = self.repository.find_hypothesis(resolved, command.hypothesis_id)
        if hypothesis.workflow_state is HypothesisWorkflowState.RETIRED:
            raise ConflictError(
                f"hypothesis {command.hypothesis_id} is already retired"
            )
        if command.superseded_by:
            self.repository.find_hypothesis(resolved, command.superseded_by)
        assessment = hypothesis.evidence_assessment
        if command.rejection_type is RejectionType.EMPIRICALLY_REFUTED:
            assessment = EvidenceAssessment.REFUTED
        elif command.rejection_type is RejectionType.WEAKENED:
            assessment = EvidenceAssessment.WEAKENED
        retired = replace(
            hypothesis,
            workflow_state=HypothesisWorkflowState.RETIRED,
            evidence_assessment=assessment,
            retirement={
                "rejection_type": command.rejection_type.value,
                "reason": require_text(command.reason, "retirement reason"),
                "limitations": normalize_text(command.limitations, "limitations"),
                "resurrection_conditions": require_text_list(
                    command.resurrection_conditions, "resurrection_conditions"
                ),
                "superseded_by": command.superseded_by,
                "decided_at": self.clock(),
                "decided_by": self.actor,
            },
        )
        self.repository.move_hypothesis(resolved, retired, "retired")
        self._event(
            resolved,
            "hypothesis.retire",
            "hypothesis",
            command.hypothesis_id,
            retired.to_dict(),
        )
        return retired

    def list_hypotheses(
        self, inquiry_id: str | None = None, state: str | None = None
    ) -> list[Hypothesis]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.list_hypotheses(resolved, state)

    def record_evidence(
        self, command: RecordEvidence, inquiry_id: str | None = None
    ) -> EvidenceRecord:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        hypothesis = self.repository.find_hypothesis(resolved, command.hypothesis_id)
        validate_evidence_target(hypothesis)
        if command.claim_id:
            claim_ids = {
                claim.claim_id for claim in self.repository.load_claims(resolved)
            }
            if command.claim_id not in claim_ids:
                raise NotFoundError(f"claim {command.claim_id} does not exist")
        evidence = EvidenceRecord(
            evidence_id=f"evd-{self.token()}",
            hypothesis_id=command.hypothesis_id,
            claim_id=command.claim_id,
            direction=command.direction,
            summary=require_text(command.summary, "evidence summary"),
            dataset_id=require_text(command.dataset_id, "dataset_id"),
            analysis_id=require_text(command.analysis_id, "analysis_id"),
            created_at=self.clock(),
            effect_estimate=normalize_text(command.effect_estimate, "effect_estimate"),
            uncertainty=normalize_text(command.uncertainty, "uncertainty"),
            scope=normalize_text(command.scope, "scope"),
            controls_passed=require_text_list(
                command.controls_passed, "controls_passed"
            ),
            controls_failed=require_text_list(
                command.controls_failed, "controls_failed"
            ),
            higher_level_conclusions_unsupported=require_text_list(
                command.higher_level_conclusions_unsupported,
                "higher_level_conclusions_unsupported",
            ),
            exploratory=command.exploratory,
        )
        self.repository.save_evidence(resolved, evidence)
        self._event(
            resolved,
            "evidence.record",
            "evidence",
            evidence.evidence_id,
            evidence.to_dict(),
        )
        return evidence

    def list_evidence(self, inquiry_id: str | None = None) -> list[EvidenceRecord]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.list_evidence(resolved)

    def build_synthesis(self, inquiry_id: str | None = None) -> dict[str, Any]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        inquiry = self.repository.load_inquiry(resolved)
        content = build_synthesis(
            inquiry,
            self.repository.load_questions(resolved),
            self.repository.load_claims(resolved),
            self.repository.list_hypotheses(resolved),
            self.repository.list_evidence(resolved),
        )
        path = self.repository.write_report(resolved, "current-synthesis.md", content)
        updated = replace(inquiry, current_synthesis_path=path)
        self.repository.save_inquiry(updated)
        self._event(
            resolved,
            "synthesis.build",
            "report",
            "current-synthesis",
            {"path": path},
        )
        return {"path": path, "content": content}

    def verify_ledger(self, inquiry_id: str | None = None) -> dict[str, Any]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.verify_ledger(resolved)

    def _event(
        self,
        inquiry_id: str,
        command: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.repository.append_event(
            inquiry_id,
            timestamp=self.clock(),
            actor=self.actor,
            command=command,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
        )
