from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateProtocol,
    CreateInquiry,
    ProposeHypothesis,
    RecommendActionPortfolio,
    RecommendNextAction,
    RecordCrossLaneLesson,
    RecordEvidence,
    RecordRun,
    RegisterDataset,
    ReviewClaim,
    RetireHypothesis,
    SetInquiryDecision,
)
from research_machine.application.artifact_integrity import verify_run_artifacts
from research_machine.application.policies import (
    normalize_confidence,
    normalize_text,
    require_text,
    require_text_list,
    require_unique_text_list,
    require_sha256,
    validate_action_candidates,
    validate_action_lanes,
    validate_cross_lane_lesson,
    validate_dataset_artifacts,
    validate_evidence_annotations,
    validate_evidence_target,
    validate_hypothesis_activation,
    validate_hypothesis_staging,
    validate_protocol_freeze,
    validate_portfolio_action_candidates,
    validate_quality_gates,
    validate_selection_weights,
    validate_validation_tag_context,
)
from research_machine.application.rigor import audit_research_state
from research_machine.domain.errors import ConflictError, NotFoundError, ValidationError
from research_machine.domain.models import (
    ActionRecommendation,
    AnalysisMode,
    Claim,
    CrossLaneLesson,
    ClaimDisposition,
    ClaimEpistemicLayer,
    DatasetManifest,
    DatasetRole,
    EvidenceAssessment,
    EvidenceRecord,
    ExperimentProtocol,
    Hypothesis,
    HypothesisWorkflowState,
    Inquiry,
    Question,
    QuestionStatus,
    RejectionType,
    ProtocolStatus,
    ProtocolKind,
    QualityGateStatus,
    ResearchRun,
    RunRecordPreflight,
    RigorAudit,
    RigorSeverity,
    RunStatus,
)
from research_machine.ports.repository import WorkspaceRepository
from research_machine.reporting.synthesis import build_synthesis
from research_machine.selection import rank_actions, rank_actions_by_lane


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "inquiry"


def _sha256_json(value: dict[str, Any]) -> str:
    content = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _protocol_commitment(protocol: ExperimentProtocol) -> str:
    payload = protocol.to_dict()
    for field_name in (
        "status",
        "protocol_hash",
        "registration_timestamp",
        "external_anchor",
    ):
        payload.pop(field_name, None)
    return _sha256_json(payload)


def _parse_aware_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValidationError(f"{field_name} must include a UTC offset")
    return parsed


def _protocol_chronology_receipt(
    *,
    protocol: ExperimentProtocol,
    started: datetime,
    metadata: dict[str, object],
    output_artifacts: list,
) -> dict[str, object]:
    if not protocol.registration_timestamp:
        raise ValidationError("frozen protocol has no canonical registration timestamp")
    registered = _parse_aware_timestamp(
        protocol.registration_timestamp, "protocol registration_timestamp"
    )
    external = metadata.get("external_protocol_freeze")
    if external is None:
        if started < registered:
            raise ValidationError(
                "run started before canonical protocol registration; an externally "
                "frozen run requires metadata.external_protocol_freeze"
            )
        return {
            "status": "local_preregistered",
            "canonical_registration_timestamp": protocol.registration_timestamp,
            "run_started_at": started.isoformat(),
            "canonical_registration_precedes_run": True,
        }
    if not isinstance(external, dict):
        raise ValidationError("metadata.external_protocol_freeze must be an object")
    allowed_fields = {
        "declared_frozen_at",
        "canonicalized_after_execution",
        "protocol_artifact",
        "analysis_source_artifact",
        "freeze_manifest_artifact",
    }
    unknown_fields = sorted(set(external) - allowed_fields)
    if unknown_fields:
        raise ValidationError(
            "unknown external_protocol_freeze fields: " + ", ".join(unknown_fields)
        )
    missing_fields = sorted(allowed_fields - set(external))
    if missing_fields:
        raise ValidationError(
            "external_protocol_freeze is missing fields: " + ", ".join(missing_fields)
        )
    if not protocol.external_anchor:
        raise ValidationError(
            "external_protocol_freeze requires a frozen protocol external_anchor"
        )
    declared_text = require_text(
        external["declared_frozen_at"],
        "external_protocol_freeze.declared_frozen_at",
    )
    declared = _parse_aware_timestamp(
        declared_text, "external_protocol_freeze.declared_frozen_at"
    )
    if declared > started:
        raise ValidationError(
            "external protocol freeze must not postdate the run start"
        )
    canonicalized_after = external["canonicalized_after_execution"]
    if not isinstance(canonicalized_after, bool):
        raise ValidationError(
            "external_protocol_freeze.canonicalized_after_execution must be true or false"
        )
    observed_after = registered > started
    if canonicalized_after is not observed_after:
        raise ValidationError(
            "external_protocol_freeze.canonicalized_after_execution conflicts with "
            "the canonical registration and run timestamps"
        )
    protocol_locator = require_text(
        external["protocol_artifact"],
        "external_protocol_freeze.protocol_artifact",
    )
    source_locator = require_text(
        external["analysis_source_artifact"],
        "external_protocol_freeze.analysis_source_artifact",
    )
    manifest_locator = require_text(
        external["freeze_manifest_artifact"],
        "external_protocol_freeze.freeze_manifest_artifact",
    )
    if len({protocol_locator, source_locator, manifest_locator}) != 3:
        raise ValidationError(
            "external protocol, analysis source, and freeze manifest artifacts must be distinct"
        )
    expected_roles = {
        protocol_locator: "external_frozen_protocol",
        source_locator: "analysis_source",
        manifest_locator: "external_freeze_manifest",
    }
    for locator, role in expected_roles.items():
        matching = [
            artifact
            for artifact in output_artifacts
            if artifact.locator == locator
            and artifact.metadata.get("artifact_role") == role
        ]
        if len(matching) != 1:
            raise ValidationError(
                f"exactly one {role} output artifact must match {locator}"
            )
    return {
        "status": "externally_attested_pre_execution_freeze",
        "canonical_registration_timestamp": protocol.registration_timestamp,
        "external_declared_frozen_at": declared_text,
        "run_started_at": started.isoformat(),
        "canonical_registration_precedes_run": not observed_after,
        "canonicalized_after_execution": canonicalized_after,
        "external_anchor": protocol.external_anchor,
        "protocol_artifact": protocol_locator,
        "analysis_source_artifact": source_locator,
        "freeze_manifest_artifact": manifest_locator,
        "chronology_cryptographically_verified": False,
    }


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
            decision_to_support=normalize_text(
                command.decision_to_support, "decision_to_support"
            ),
            minimum_evidence=normalize_text(
                command.minimum_evidence, "minimum_evidence"
            ),
            decision_change_criteria=require_unique_text_list(
                command.decision_change_criteria, "decision_change_criteria"
            ),
            decision_owner=normalize_text(command.decision_owner, "decision_owner"),
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

    def set_inquiry_decision(
        self,
        command: SetInquiryDecision,
        inquiry_id: str | None = None,
    ) -> Inquiry:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        inquiry = self.repository.load_inquiry(resolved)
        updated = replace(
            inquiry,
            decision_to_support=require_text(
                command.decision_to_support, "decision_to_support"
            ),
            minimum_evidence=require_text(command.minimum_evidence, "minimum_evidence"),
            decision_change_criteria=require_unique_text_list(
                command.decision_change_criteria, "decision_change_criteria"
            ),
            decision_owner=normalize_text(command.decision_owner, "decision_owner"),
        )
        if not updated.decision_change_criteria:
            raise ValidationError(
                "decision_change_criteria must contain at least one criterion"
            )
        self.repository.save_inquiry(updated)
        self._event(
            resolved,
            "inquiry.decision.set",
            "inquiry",
            resolved,
            {
                "decision_to_support": updated.decision_to_support,
                "minimum_evidence": updated.minimum_evidence,
                "decision_change_criteria": updated.decision_change_criteria,
                "decision_owner": updated.decision_owner,
            },
        )
        return updated

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
            "datasets": [
                item.to_dict() for item in self.repository.list_datasets(resolved)
            ],
            "protocols": [
                item.to_dict() for item in self.repository.list_protocols(resolved)
            ],
            "runs": [item.to_dict() for item in self.repository.list_runs(resolved)],
            "recommendations": [
                item.to_dict()
                for item in self.repository.list_recommendations(resolved)
            ],
            "cross_lane_lessons": [
                item.to_dict()
                for item in self.repository.list_cross_lane_lessons(resolved)
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
        conflicts_with = require_unique_text_list(
            command.conflicts_with, "conflicts_with"
        )
        known = {claim.claim_id for claim in claims}
        missing = sorted((set(parent_claims) | set(conflicts_with)) - known)
        if missing:
            raise ValidationError("unknown claim references: " + ", ".join(missing))
        overlap = sorted(set(parent_claims) & set(conflicts_with))
        if overlap:
            raise ValidationError(
                "claims cannot be both dependencies and conflicts: "
                + ", ".join(overlap)
            )
        if not isinstance(command.epistemic_layer, ClaimEpistemicLayer):
            raise ValidationError("epistemic_layer must be a ClaimEpistemicLayer")
        if not isinstance(command.disposition, ClaimDisposition):
            raise ValidationError("disposition must be a ClaimDisposition")
        claim = Claim(
            claim_id=f"clm-{self.token()}",
            statement=require_text(command.statement, "claim statement"),
            level=command.level,
            created_at=self.clock(),
            parent_claims=parent_claims,
            scope=normalize_text(command.scope, "scope"),
            epistemic_layer=command.epistemic_layer,
            disposition=command.disposition,
            confidence=normalize_confidence(command.confidence),
            source_refs=require_unique_text_list(command.source_refs, "source_refs"),
            conflicts_with=conflicts_with,
            falsified_by=require_unique_text_list(command.falsified_by, "falsified_by"),
            last_reviewed=(
                require_text(command.last_reviewed, "last_reviewed")
                if command.last_reviewed is not None
                else None
            ),
            decision_owner=normalize_text(command.decision_owner, "decision_owner"),
        )
        self._validate_claim_authority(claim)
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

    def review_claim(
        self, command: ReviewClaim, inquiry_id: str | None = None
    ) -> Claim:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        claims = self.repository.load_claims(resolved)
        known = {claim.claim_id for claim in claims}
        if command.epistemic_layer is not None and not isinstance(
            command.epistemic_layer, ClaimEpistemicLayer
        ):
            raise ValidationError("epistemic_layer must be a ClaimEpistemicLayer")
        if command.disposition is not None and not isinstance(
            command.disposition, ClaimDisposition
        ):
            raise ValidationError("disposition must be a ClaimDisposition")
        for index, claim in enumerate(claims):
            if claim.claim_id != command.claim_id:
                continue
            conflicts_with = (
                claim.conflicts_with
                if command.conflicts_with is None
                else require_unique_text_list(command.conflicts_with, "conflicts_with")
            )
            if claim.claim_id in conflicts_with:
                raise ValidationError("a claim cannot conflict with itself")
            missing = sorted(set(conflicts_with) - known)
            if missing:
                raise ValidationError("unknown conflict claims: " + ", ".join(missing))
            overlap = sorted(set(claim.parent_claims) & set(conflicts_with))
            if overlap:
                raise ValidationError(
                    "claims cannot be both dependencies and conflicts: "
                    + ", ".join(overlap)
                )
            updated = replace(
                claim,
                epistemic_layer=command.epistemic_layer or claim.epistemic_layer,
                disposition=command.disposition or claim.disposition,
                confidence=(
                    claim.confidence
                    if command.confidence is None
                    else normalize_confidence(command.confidence)
                ),
                source_refs=(
                    claim.source_refs
                    if command.source_refs is None
                    else require_unique_text_list(command.source_refs, "source_refs")
                ),
                conflicts_with=conflicts_with,
                falsified_by=(
                    claim.falsified_by
                    if command.falsified_by is None
                    else require_unique_text_list(command.falsified_by, "falsified_by")
                ),
                last_reviewed=(
                    require_text(command.reviewed_at, "reviewed_at")
                    if command.reviewed_at is not None
                    else self.clock()
                ),
                decision_owner=(
                    claim.decision_owner
                    if command.decision_owner is None
                    else normalize_text(command.decision_owner, "decision_owner")
                ),
            )
            self._validate_claim_authority(updated)
            claims[index] = updated
            self.repository.save_claims(resolved, claims)
            self._event(
                resolved,
                "claim.review",
                "claim",
                updated.claim_id,
                updated.to_dict(),
            )
            return updated
        raise NotFoundError(f"claim {command.claim_id} does not exist")

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

    def stage_hypothesis(
        self,
        hypothesis_id: str,
        rationale: str,
        confidence: str,
        inquiry_id: str | None = None,
    ) -> Hypothesis:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        hypothesis = self.repository.find_hypothesis(resolved, hypothesis_id)
        validate_hypothesis_staging(hypothesis)
        normalized_confidence = require_text(confidence, "confidence")
        if normalized_confidence != "high":
            raise ValidationError(
                "pending-review staging requires explicitly high confidence"
            )
        staged = replace(
            hypothesis,
            workflow_state=HypothesisWorkflowState.PENDING_REVIEW,
            pending_review_at=self.clock(),
            pending_review_by=self.actor,
            pending_review_confidence=normalized_confidence,
            pending_review_rationale=require_text(
                rationale, "pending-review rationale"
            ),
            activated_at=None,
            retirement=None,
        )
        self.repository.move_hypothesis(resolved, staged, "pending_review")
        self._event(
            resolved,
            "hypothesis.stage_pending_review",
            "hypothesis",
            hypothesis_id,
            staged.to_dict(),
        )
        return staged

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

    def register_dataset(
        self, command: RegisterDataset, inquiry_id: str | None = None
    ) -> DatasetManifest:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        if not isinstance(command.role, DatasetRole):
            raise ValidationError("role must be a DatasetRole")
        if not isinstance(command.synthetic, bool):
            raise ValidationError("synthetic must be true or false")
        if not isinstance(command.metadata, dict):
            raise ValidationError("metadata must be an object")
        artifacts = validate_dataset_artifacts(command.artifacts)
        source_ids = require_text_list(command.source_dataset_ids, "source_dataset_ids")
        if len(set(source_ids)) != len(source_ids):
            raise ValidationError("source_dataset_ids must not contain duplicates")
        sources = [
            self.repository.find_dataset(resolved, source_id)
            for source_id in source_ids
        ]

        protected_roles = {DatasetRole.CONFIRMATORY, DatasetRole.REPLICATION}
        if command.role in protected_roles:
            incompatible = [
                source.dataset_id
                for source in sources
                if source.role is not command.role
            ]
            if incompatible:
                raise ValidationError(
                    f"{command.role.value} datasets may only derive from the same "
                    "role; incompatible sources: " + ", ".join(incompatible)
                )
        elif any(source.role in protected_roles for source in sources):
            raise ValidationError(
                "confirmatory and replication observations cannot feed calibration, "
                "exploration, or training datasets"
            )

        protocol: ExperimentProtocol | None = None
        role_to_mode = {
            DatasetRole.EXPLORATORY: AnalysisMode.EXPLORATORY,
            DatasetRole.CONFIRMATORY: AnalysisMode.CONFIRMATORY,
            DatasetRole.REPLICATION: AnalysisMode.REPLICATION,
        }
        if command.protocol_id:
            if command.role not in role_to_mode:
                raise ValidationError(
                    f"{command.role.value} datasets cannot bind an analysis protocol"
                )
            protocol = self.repository.find_protocol(resolved, command.protocol_id)
            if protocol.status is not ProtocolStatus.FROZEN:
                raise ValidationError("datasets may only bind frozen protocols")
            if protocol.analysis_mode is not role_to_mode[command.role]:
                raise ValidationError(
                    f"dataset role {command.role.value} does not match protocol mode "
                    f"{protocol.analysis_mode.value}"
                )
        elif command.role in protected_roles:
            raise ValidationError(
                f"{command.role.value} datasets require a frozen protocol"
            )

        existing_digests = {
            artifact.sha256: dataset
            for dataset in self.repository.list_datasets(resolved)
            for artifact in dataset.artifacts
        }
        collisions = [
            (artifact.sha256, existing_digests[artifact.sha256])
            for artifact in artifacts
            if artifact.sha256 in existing_digests
        ]
        if collisions:
            digest, existing = collisions[0]
            raise ConflictError(
                f"artifact {digest} is already registered in dataset "
                f"{existing.dataset_id} with role {existing.role.value}; observations "
                "cannot be relabeled"
            )

        dataset_id = command.dataset_id or f"ds-{self.token()}"
        dataset = DatasetManifest(
            dataset_id=dataset_id,
            name=require_text(command.name, "dataset name"),
            role=command.role,
            created_at=self.clock(),
            artifacts=artifacts,
            description=normalize_text(command.description, "description"),
            observation_unit=normalize_text(
                command.observation_unit, "observation_unit"
            ),
            source_dataset_ids=source_ids,
            protocol_id=protocol.protocol_id if protocol else None,
            synthetic=command.synthetic or any(source.synthetic for source in sources),
            quality_attestations=require_text_list(
                command.quality_attestations, "quality_attestations"
            ),
            metadata=dict(command.metadata),
        )
        self.repository.save_dataset(resolved, dataset)
        self._event(
            resolved,
            "dataset.register",
            "dataset",
            dataset.dataset_id,
            dataset.to_dict(),
        )
        return dataset

    def list_datasets(self, inquiry_id: str | None = None) -> list[DatasetManifest]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.list_datasets(resolved)

    def create_protocol(
        self, command: CreateProtocol, inquiry_id: str | None = None
    ) -> ExperimentProtocol:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        family_id = f"prt-{self.token()}"
        protocol = self._build_protocol(
            resolved,
            command,
            protocol_family_id=family_id,
            version=1,
        )
        self.repository.save_protocol(resolved, protocol)
        self._event(
            resolved,
            "protocol.create",
            "protocol",
            protocol.protocol_id,
            protocol.to_dict(),
        )
        return protocol

    def freeze_protocol(
        self,
        protocol_id: str,
        inquiry_id: str | None = None,
        *,
        external_anchor: str | None = None,
    ) -> ExperimentProtocol:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        protocol = self.repository.find_protocol(resolved, protocol_id)
        validate_protocol_freeze(protocol)
        for hypothesis_id in protocol.hypotheses_tested:
            hypothesis = self.repository.find_hypothesis(resolved, hypothesis_id)
            if hypothesis.workflow_state is HypothesisWorkflowState.ACTIVE:
                continue
            if (
                hypothesis.workflow_state is HypothesisWorkflowState.PENDING_REVIEW
                and protocol.analysis_mode is AnalysisMode.EXPLORATORY
            ):
                continue
            if hypothesis.workflow_state is HypothesisWorkflowState.PENDING_REVIEW:
                raise ValidationError(
                    f"protocol hypothesis {hypothesis_id} is pending human review; "
                    "only exploratory protocols may be frozen"
                )
            raise ValidationError(
                f"protocol hypothesis {hypothesis_id} must be active or pending review "
                "before freeze"
            )
        anchor = (
            normalize_text(external_anchor, "external_anchor")
            if external_anchor is not None
            else protocol.external_anchor
        )
        frozen = replace(
            protocol,
            status=ProtocolStatus.FROZEN,
            protocol_hash=_protocol_commitment(protocol),
            registration_timestamp=self.clock(),
            external_anchor=anchor,
        )
        self.repository.freeze_protocol(resolved, frozen)
        self._event(
            resolved,
            "protocol.freeze",
            "protocol",
            protocol_id,
            frozen.to_dict(),
        )
        return frozen

    def amend_protocol(
        self,
        protocol_id: str,
        command: CreateProtocol,
        reason: str,
        inquiry_id: str | None = None,
    ) -> ExperimentProtocol:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        predecessor = self.repository.find_protocol(resolved, protocol_id)
        if predecessor.status is not ProtocolStatus.FROZEN:
            raise ValidationError("only frozen protocols can be amended")
        family = [
            item
            for item in self.repository.list_protocols(resolved)
            if item.protocol_family_id == predecessor.protocol_family_id
        ]
        if any(item.version > predecessor.version for item in family):
            raise ConflictError(
                f"protocol {protocol_id} is not the latest version in its family"
            )
        if command.experiment_id != predecessor.experiment_id:
            raise ValidationError("an amendment cannot change experiment_id")
        amended = self._build_protocol(
            resolved,
            command,
            protocol_family_id=predecessor.protocol_family_id,
            version=predecessor.version + 1,
            supersedes_protocol_id=predecessor.protocol_id,
            amendment_reason=require_text(reason, "amendment reason"),
        )
        self.repository.save_protocol(resolved, amended)
        self._event(
            resolved,
            "protocol.amend",
            "protocol",
            amended.protocol_id,
            amended.to_dict(),
        )
        return amended

    def list_protocols(self, inquiry_id: str | None = None) -> list[ExperimentProtocol]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.list_protocols(resolved)

    def get_protocol(
        self, protocol_id: str, inquiry_id: str | None = None
    ) -> ExperimentProtocol:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.find_protocol(resolved, protocol_id)

    def _prepare_run(
        self,
        command: RecordRun,
        resolved: str,
        *,
        run_id: str,
    ) -> ResearchRun:
        if not isinstance(command.synthetic, bool):
            raise ValidationError("synthetic must be true or false")
        if not isinstance(command.metadata, dict):
            raise ValidationError("metadata must be an object")
        if "artifact_integrity" in command.metadata:
            raise ValidationError(
                "metadata.artifact_integrity is reserved for machine verification"
            )
        if "protocol_chronology" in command.metadata:
            raise ValidationError(
                "metadata.protocol_chronology is reserved for machine verification"
            )
        protocol = self.repository.find_protocol(resolved, command.protocol_id)
        if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
            raise ValidationError("runs require a frozen, hash-committed protocol")
        if _protocol_commitment(protocol) != protocol.protocol_hash:
            raise ValidationError(
                "frozen protocol content no longer matches its hash commitment"
            )

        analysis_code_hash = require_sha256(
            command.analysis_code_hash, "analysis_code_hash"
        )
        if analysis_code_hash != protocol.analysis_code_hash:
            raise ValidationError(
                "run analysis_code_hash does not match the frozen protocol"
            )
        environment_hash = require_sha256(command.environment_hash, "environment_hash")
        seed_reveal = (
            require_text(command.random_seed_reveal, "random_seed_reveal")
            if command.random_seed_reveal is not None
            else None
        )
        if protocol.random_seed_commitment:
            if seed_reveal is None:
                raise ValidationError(
                    "run must reveal the random seed committed by the protocol"
                )
            actual_commitment = hashlib.sha256(seed_reveal.encode("utf-8")).hexdigest()
            if actual_commitment != protocol.random_seed_commitment:
                raise ValidationError(
                    "random_seed_reveal does not match the protocol commitment"
                )
        started_at = require_text(command.started_at, "started_at")
        completed_at = require_text(command.completed_at, "completed_at")
        started = _parse_aware_timestamp(started_at, "started_at")
        completed = _parse_aware_timestamp(completed_at, "completed_at")
        if completed < started:
            raise ValidationError("completed_at must not precede started_at")

        dataset_ids = require_text_list(command.dataset_ids, "dataset_ids")
        if len(set(dataset_ids)) != len(dataset_ids):
            raise ValidationError("dataset_ids must not contain duplicates")
        datasets = [
            self.repository.find_dataset(resolved, dataset_id)
            for dataset_id in dataset_ids
        ]
        self._validate_run_datasets(protocol, datasets)

        outputs = validate_dataset_artifacts(command.output_artifacts)
        protocol_chronology = _protocol_chronology_receipt(
            protocol=protocol,
            started=started,
            metadata=command.metadata,
            output_artifacts=outputs,
        )
        expected_attestation_schema_sha256 = (
            require_sha256(
                command.expected_attestation_schema_sha256,
                "expected_attestation_schema_sha256",
            )
            if command.expected_attestation_schema_sha256 is not None
            else None
        )
        verify_artifacts = any(
            value is not None
            for value in (
                command.artifact_root,
                command.attestation_schema_path,
                expected_attestation_schema_sha256,
            )
        ) or isinstance(
            command.metadata.get("replication_independence"), dict
        ) or isinstance(command.metadata.get("external_protocol_freeze"), dict)
        artifact_integrity = (
            verify_run_artifacts(
                outputs,
                artifact_root=command.artifact_root,
                actor=self.actor,
                analysis_code_hash=analysis_code_hash,
                run_metadata=command.metadata,
                attestation_schema_path=command.attestation_schema_path,
                expected_attestation_schema_sha256=(expected_attestation_schema_sha256),
            )
            if verify_artifacts
            else None
        )
        gates = validate_quality_gates(command.quality_gates)
        gates_by_id = {gate.gate_id: gate for gate in gates}
        missing_gates = sorted(set(protocol.quality_requirements) - set(gates_by_id))
        required_gate_failure = any(
            gate.required and gate.status is not QualityGateStatus.PASSED
            for gate in gates
        )
        protocol_gate_failure = any(
            gates_by_id[gate_id].status is not QualityGateStatus.PASSED
            for gate_id in protocol.quality_requirements
            if gate_id in gates_by_id
        )
        invalid = bool(
            missing_gates
            or required_gate_failure
            or protocol_gate_failure
            or (
                artifact_integrity is not None and artifact_integrity.status != "passed"
            )
        )
        synthetic = command.synthetic or any(dataset.synthetic for dataset in datasets)
        run = ResearchRun(
            run_id=run_id,
            protocol_id=protocol.protocol_id,
            protocol_hash=protocol.protocol_hash,
            analysis_mode=protocol.analysis_mode,
            started_at=started_at,
            completed_at=completed_at,
            executed_by=self.actor,
            analysis_code_hash=analysis_code_hash,
            environment_hash=environment_hash,
            random_seed_reveal=seed_reveal,
            dataset_ids=dataset_ids,
            output_artifacts=outputs,
            quality_gates=gates,
            status=RunStatus.INVALID if invalid else RunStatus.COMPLETED,
            scientific_evidence_eligible=not invalid and not synthetic,
            summary=normalize_text(command.summary, "run summary"),
            synthetic=synthetic,
            metadata={
                **dict(command.metadata),
                "protocol_chronology": protocol_chronology,
                **({"missing_quality_gates": missing_gates} if missing_gates else {}),
                **(
                    {"artifact_integrity": artifact_integrity.to_dict()}
                    if artifact_integrity is not None
                    else {}
                ),
            },
        )
        return run

    def record_run(
        self, command: RecordRun, inquiry_id: str | None = None
    ) -> ResearchRun:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        run = self._prepare_run(
            command,
            resolved,
            run_id=command.run_id or f"run-{self.token()}",
        )
        artifact_integrity = run.metadata.get("artifact_integrity")
        if (
            isinstance(artifact_integrity, dict)
            and artifact_integrity.get("status") != "passed"
        ):
            codes = [
                finding.get("code", "UNKNOWN")
                for finding in artifact_integrity.get("findings", [])
                if isinstance(finding, dict)
            ]
            raise ValidationError(
                "artifact integrity preflight failed: " + ", ".join(codes)
            )
        self.repository.save_run(resolved, run)
        self._event(resolved, "run.record", "run", run.run_id, run.to_dict())
        return run

    def preflight_run(
        self, command: RecordRun, inquiry_id: str | None = None
    ) -> RunRecordPreflight:
        """Predict run-record validity without writing state or consuming an ID."""
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        preview = self._prepare_run(
            command,
            resolved,
            run_id=command.run_id or "run-id-assigned-only-on-record",
        )
        protocol = self.repository.find_protocol(resolved, command.protocol_id)
        required_ids = list(protocol.quality_requirements)
        provided_ids = [gate.gate_id for gate in preview.quality_gates]
        required_set = set(required_ids)
        provided_set = set(provided_ids)
        missing_ids = sorted(required_set - provided_set)
        unexpected_ids = sorted(provided_set - required_set)
        gates_by_id = {gate.gate_id: gate for gate in preview.quality_gates}
        failed_required_ids = [
            gate.gate_id
            for gate in preview.quality_gates
            if gate.required and gate.status is not QualityGateStatus.PASSED
        ]
        failed_protocol_ids = [
            gate_id
            for gate_id in required_ids
            if gate_id in gates_by_id
            and gates_by_id[gate_id].status is not QualityGateStatus.PASSED
        ]
        run_id_conflict = command.run_id is not None and any(
            existing.run_id == command.run_id
            for existing in self.repository.list_runs(resolved)
        )
        artifact_integrity = preview.metadata.get("artifact_integrity")
        artifact_reject = (
            isinstance(artifact_integrity, dict)
            and artifact_integrity.get("status") != "passed"
        )
        return RunRecordPreflight(
            status=(
                "would_reject"
                if run_id_conflict or artifact_reject
                else (
                    "ready"
                    if preview.status is RunStatus.COMPLETED
                    else "would_record_invalid"
                )
            ),
            would_append_event=False,
            protocol_id=protocol.protocol_id,
            protocol_hash=protocol.protocol_hash or "",
            requested_run_id=command.run_id,
            requested_run_id_conflicts=run_id_conflict,
            record_status_if_submitted=(
                None if run_id_conflict or artifact_reject else preview.status
            ),
            scientific_evidence_eligible_if_submitted=(
                None
                if run_id_conflict or artifact_reject
                else preview.scientific_evidence_eligible
            ),
            synthetic_if_submitted=preview.synthetic,
            required_quality_gate_ids=required_ids,
            provided_quality_gate_ids=provided_ids,
            missing_quality_gate_ids=missing_ids,
            unexpected_quality_gate_ids=unexpected_ids,
            failed_required_gate_ids=failed_required_ids,
            failed_protocol_gate_ids=failed_protocol_ids,
            exact_quality_gate_set=(not missing_ids and not unexpected_ids),
            quality_gate_order_matches_protocol=(provided_ids == required_ids),
            artifact_integrity=(
                dict(artifact_integrity)
                if isinstance(artifact_integrity, dict)
                else None
            ),
            protocol_chronology=dict(
                preview.metadata.get("protocol_chronology", {})
            ),
            conclusion_ceiling=(
                "Prospective record-shape validation only. This preflight writes "
                "no run or ledger event. When an artifact root and pinned "
                "attestation schema are supplied it also validates local bytes "
                "and record consistency, but never execution truth, attester "
                "identity, scientific methods, or conclusions."
            ),
        )

    def run_record_template(
        self, protocol_id: str, inquiry_id: str | None = None
    ) -> dict[str, Any]:
        """Return a deliberately non-submittable skeleton with exact gate IDs."""
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        protocol = self.repository.find_protocol(resolved, protocol_id)
        if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
            raise ValidationError("run templates require a frozen protocol")
        if _protocol_commitment(protocol) != protocol.protocol_hash:
            raise ValidationError(
                "frozen protocol content no longer matches its hash commitment"
            )
        return {
            "schema_version": 1,
            "template_kind": "research-machine-run-record-v1",
            "template_only": True,
            "would_append_event": False,
            "protocol_hash": protocol.protocol_hash,
            "record": {
                "protocol_id": protocol.protocol_id,
                "started_at": "<ISO-8601 timestamp with UTC offset>",
                "completed_at": "<ISO-8601 timestamp with UTC offset>",
                "analysis_code_hash": protocol.analysis_code_hash,
                "environment_hash": "<64 lowercase hexadecimal characters>",
                "random_seed_reveal": (
                    "<exact seed matching the frozen commitment>"
                    if protocol.random_seed_commitment
                    else None
                ),
                "dataset_ids": [],
                "output_artifacts": [],
                "quality_gates": [
                    {
                        "gate_id": gate_id,
                        "status": "skipped",
                        "summary": "<replace with the observed gate result>",
                        "required": True,
                        "details": {},
                    }
                    for gate_id in protocol.quality_requirements
                ],
                "summary": "",
                "synthetic": False,
                "metadata": {},
            },
            "instructions": [
                "Replace every angle-bracket placeholder with observed provenance.",
                "Add at least one output artifact with its real hash.",
                "Set every gate status from observed output; skipped or failed required gates make the run invalid.",
                "Run `research run preflight --record-file ...` before `research run record`.",
            ],
            "conclusion_ceiling": (
                "Template generation only. No execution, result, run, or ledger "
                "event is created."
            ),
        }

    def list_runs(self, inquiry_id: str | None = None) -> list[ResearchRun]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.list_runs(resolved)

    def get_run(self, run_id: str, inquiry_id: str | None = None) -> ResearchRun:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.find_run(resolved, run_id)

    def recommend_next_action(
        self, command: RecommendNextAction, inquiry_id: str | None = None
    ) -> ActionRecommendation:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        researchable_hypotheses = {
            hypothesis.hypothesis_id
            for hypothesis in self.repository.list_hypotheses(resolved)
            if hypothesis.workflow_state
            in {
                HypothesisWorkflowState.PENDING_REVIEW,
                HypothesisWorkflowState.ACTIVE,
            }
        }
        candidates = validate_action_candidates(
            command.candidates, researchable_hypotheses
        )
        weights = validate_selection_weights(command.weights)
        scores = rank_actions(candidates, weights)
        selected = next(
            candidate
            for candidate in candidates
            if candidate.action_id == scores[0].action_id
        )
        recommendation = ActionRecommendation(
            recommendation_id=f"rec-{self.token()}",
            selected_action_id=selected.action_id,
            created_at=self.clock(),
            created_by=self.actor,
            rationale=selected.rationale,
            candidates=candidates,
            ranked_scores=scores,
            weights=weights,
        )
        self.repository.save_recommendation(resolved, recommendation)
        self._event(
            resolved,
            "next-action.recommend",
            "recommendation",
            recommendation.recommendation_id,
            recommendation.to_dict(),
        )
        return recommendation

    def recommend_action_portfolio(
        self, command: RecommendActionPortfolio, inquiry_id: str | None = None
    ) -> ActionRecommendation:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        researchable_hypotheses = {
            hypothesis.hypothesis_id
            for hypothesis in self.repository.list_hypotheses(resolved)
            if hypothesis.workflow_state
            in {
                HypothesisWorkflowState.PENDING_REVIEW,
                HypothesisWorkflowState.ACTIVE,
            }
        }
        lanes = validate_action_lanes(command.lanes)
        candidates, completed = validate_portfolio_action_candidates(
            command.candidates,
            researchable_hypotheses,
            lanes,
            command.completed_action_ids,
        )
        weights = validate_selection_weights(command.weights)
        rankings = rank_actions_by_lane(candidates, lanes, completed, weights)
        selected_by_lane = {
            lane.lane_id: rankings[lane.lane_id][0].action_id
            for lane in lanes
            if lane.status == "active"
        }
        ranked_scores = [
            score
            for lane in lanes
            if lane.status == "active"
            for score in rankings[lane.lane_id]
        ]
        selected_candidates = {
            candidate.action_id: candidate for candidate in candidates
        }
        selected_ids = list(selected_by_lane.values())
        rationale = "; ".join(
            f"{lane_id}: {selected_candidates[action_id].rationale}"
            for lane_id, action_id in selected_by_lane.items()
        )
        recommendation = ActionRecommendation(
            recommendation_id=f"rec-{self.token()}",
            selected_action_id=selected_ids[0],
            created_at=self.clock(),
            created_by=self.actor,
            rationale=rationale,
            candidates=candidates,
            ranked_scores=ranked_scores,
            weights=weights,
            selection_mode="portfolio",
            selected_action_ids_by_lane=selected_by_lane,
            lanes=lanes,
            completed_action_ids=completed,
        )
        self.repository.save_recommendation(resolved, recommendation)
        self._event(
            resolved,
            "next-action.portfolio",
            "recommendation",
            recommendation.recommendation_id,
            recommendation.to_dict(),
        )
        return recommendation

    def record_cross_lane_lesson(
        self, command: RecordCrossLaneLesson, inquiry_id: str | None = None
    ) -> CrossLaneLesson:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        normalized = validate_cross_lane_lesson(
            origin_lane_id=command.origin_lane_id,
            target_lane_ids=command.target_lane_ids,
            origin_artifact_locator=command.origin_artifact_locator,
            origin_artifact_sha256=command.origin_artifact_sha256,
            origin_integrity_status=command.origin_integrity_status,
            observation=command.observation,
            failure_class=command.failure_class,
            strongest_alternative_explanation=(
                command.strongest_alternative_explanation
            ),
            challenged_invariant=command.challenged_invariant,
            first_permitted_future_versions=(
                command.first_permitted_future_versions
            ),
            prohibited_retroactive_targets=(
                command.prohibited_retroactive_targets
            ),
            proposed_repair=command.proposed_repair,
            repair_falsifier=command.repair_falsifier,
            conclusion_ceiling=command.conclusion_ceiling,
        )
        lesson = CrossLaneLesson(
            lesson_id=f"lesson-{self.token()}",
            created_at=self.clock(),
            created_by=self.actor,
            **normalized,
        )
        self.repository.save_cross_lane_lesson(resolved, lesson)
        self._event(
            resolved,
            "cross-lane-lesson.record",
            "cross_lane_lesson",
            lesson.lesson_id,
            lesson.to_dict(),
        )
        return lesson

    def list_cross_lane_lessons(
        self, inquiry_id: str | None = None
    ) -> list[CrossLaneLesson]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.list_cross_lane_lessons(resolved)

    def list_recommendations(
        self, inquiry_id: str | None = None
    ) -> list[ActionRecommendation]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.list_recommendations(resolved)

    def record_evidence(
        self, command: RecordEvidence, inquiry_id: str | None = None
    ) -> EvidenceRecord:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        hypothesis = self.repository.find_hypothesis(resolved, command.hypothesis_id)
        validate_evidence_target(hypothesis, exploratory=command.exploratory)
        run: ResearchRun | None = None
        protocol: ExperimentProtocol | None = None
        dataset = None
        datasets: list[DatasetManifest] = []
        analysis_id = normalize_text(command.analysis_id, "analysis_id")
        if command.run_id:
            run = self.repository.find_run(resolved, command.run_id)
            protocol = self.repository.find_protocol(resolved, run.protocol_id)
            datasets = [
                self.repository.find_dataset(resolved, dataset_id)
                for dataset_id in run.dataset_ids
            ]
            if command.hypothesis_id not in protocol.hypotheses_tested:
                raise ValidationError(
                    f"protocol {protocol.protocol_id} does not test hypothesis "
                    f"{command.hypothesis_id}"
                )
            if analysis_id and analysis_id != run.run_id:
                raise ValidationError(
                    "analysis_id must equal run_id when a run is used"
                )
            analysis_id = run.run_id
            if command.dataset_id:
                if command.dataset_id not in run.dataset_ids:
                    raise ValidationError(
                        "evidence dataset_id must be one of the run dataset_ids"
                    )
                dataset = self.repository.find_dataset(resolved, command.dataset_id)
            elif len(run.dataset_ids) == 1:
                dataset = self.repository.find_dataset(resolved, run.dataset_ids[0])
        elif command.dataset_id:
            dataset = self.repository.find_dataset(resolved, command.dataset_id)
            datasets = [dataset]

        if command.exploratory:
            if run and run.analysis_mode is not AnalysisMode.EXPLORATORY:
                raise ValidationError(
                    "exploratory evidence requires an exploratory run"
                )
            if not run:
                if dataset is None:
                    raise ValidationError(
                        "exploratory evidence requires a dataset or recorded run"
                    )
                if dataset.role is not DatasetRole.EXPLORATORY:
                    raise ValidationError(
                        "dataset-only exploratory evidence requires an exploratory dataset"
                    )
                analysis_id = require_text(analysis_id, "analysis_id")
        else:
            if run is None:
                raise ValidationError(
                    "confirmatory evidence requires a recorded, quality-gated run"
                )
            if run.analysis_mode not in {
                AnalysisMode.CONFIRMATORY,
                AnalysisMode.REPLICATION,
            }:
                raise ValidationError(
                    "confirmatory evidence requires a confirmatory or replication run"
                )
            if not run.scientific_evidence_eligible:
                raise ValidationError(
                    "run is not eligible for scientific evidence; inspect its gates and "
                    "synthetic status"
                )
        if command.claim_id:
            claim_ids = {
                claim.claim_id for claim in self.repository.load_claims(resolved)
            }
            if command.claim_id not in claim_ids:
                raise NotFoundError(f"claim {command.claim_id} does not exist")
        (
            scope,
            uncertainty,
            controls_passed,
            controls_failed,
            conclusion_ceiling,
            validation_tags,
        ) = validate_evidence_annotations(
            direction=command.direction,
            scope=command.scope,
            uncertainty=command.uncertainty,
            controls_passed=command.controls_passed,
            controls_failed=command.controls_failed,
            higher_level_conclusions_unsupported=(
                command.higher_level_conclusions_unsupported
            ),
            validation_tags=command.validation_tags,
        )
        replicated_run: ResearchRun | None = None
        if run is not None:
            replicated_run_id = run.metadata.get("replicates_run_id")
            if replicated_run_id is not None:
                replicated_run = self.repository.find_run(
                    resolved, require_text(replicated_run_id, "replicates_run_id")
                )
        validate_validation_tag_context(
            tags=validation_tags,
            hypothesis=hypothesis,
            exploratory=command.exploratory,
            protocol=protocol,
            run=run,
            datasets=datasets,
            controls_passed=controls_passed,
            replicated_run=replicated_run,
        )
        evidence = EvidenceRecord(
            evidence_id=f"evd-{self.token()}",
            hypothesis_id=command.hypothesis_id,
            claim_id=command.claim_id,
            direction=command.direction,
            summary=require_text(command.summary, "evidence summary"),
            dataset_id=dataset.dataset_id if dataset else command.dataset_id,
            analysis_id=analysis_id,
            created_at=self.clock(),
            protocol_id=protocol.protocol_id if protocol else None,
            run_id=run.run_id if run else None,
            scientific_evidence_eligible=(
                run.scientific_evidence_eligible if run else False
            ),
            effect_estimate=normalize_text(command.effect_estimate, "effect_estimate"),
            uncertainty=uncertainty,
            scope=scope,
            controls_passed=controls_passed,
            controls_failed=controls_failed,
            higher_level_conclusions_unsupported=conclusion_ceiling,
            validation_tags=validation_tags,
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
        claims = self.repository.load_claims(resolved)
        hypotheses = self.repository.list_hypotheses(resolved)
        evidence = self.repository.list_evidence(resolved)
        datasets = self.repository.list_datasets(resolved)
        protocols = self.repository.list_protocols(resolved)
        runs = self.repository.list_runs(resolved)
        rigor_audit = audit_research_state(
            inquiry=inquiry,
            claims=claims,
            hypotheses=hypotheses,
            evidence=evidence,
            datasets=datasets,
            protocols=protocols,
            runs=runs,
        )
        content = build_synthesis(
            inquiry,
            self.repository.load_questions(resolved),
            claims,
            hypotheses,
            evidence,
            datasets,
            protocols,
            runs,
            self.repository.list_recommendations(resolved),
            self.repository.list_cross_lane_lessons(resolved),
            rigor_audit,
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

    def audit_rigor(
        self,
        inquiry_id: str | None = None,
        *,
        fail_on: str = "never",
    ) -> RigorAudit:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        audit = audit_research_state(
            inquiry=self.repository.load_inquiry(resolved),
            claims=self.repository.load_claims(resolved),
            hypotheses=self.repository.list_hypotheses(resolved),
            evidence=self.repository.list_evidence(resolved),
            datasets=self.repository.list_datasets(resolved),
            protocols=self.repository.list_protocols(resolved),
            runs=self.repository.list_runs(resolved),
        )
        if fail_on not in {"never", "error", "warning"}:
            raise ValidationError("fail_on must be never, error, or warning")
        severities = {finding.severity for finding in audit.findings}
        should_fail = (fail_on == "error" and RigorSeverity.ERROR in severities) or (
            fail_on == "warning"
            and bool(severities & {RigorSeverity.ERROR, RigorSeverity.WARNING})
        )
        if should_fail:
            counts = {
                severity.value: sum(
                    finding.severity is severity for finding in audit.findings
                )
                for severity in RigorSeverity
            }
            raise ValidationError(
                "rigor audit failed at threshold "
                f"{fail_on}: {counts['error']} errors, "
                f"{counts['warning']} warnings"
            )
        return audit

    def verify_ledger(self, inquiry_id: str | None = None) -> dict[str, Any]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self.repository.verify_ledger(resolved)

    @staticmethod
    def _validate_claim_authority(claim: Claim) -> None:
        source_grounded_layers = {
            ClaimEpistemicLayer.DOCUMENTED_FACT,
            ClaimEpistemicLayer.SOURCE_CLAIM,
        }
        if (
            claim.disposition is ClaimDisposition.ACCEPTED
            and claim.epistemic_layer in source_grounded_layers
            and not claim.source_refs
        ):
            raise ValidationError(
                "accepted documented facts and source claims require source_refs"
            )

    @staticmethod
    def _validate_run_datasets(
        protocol: ExperimentProtocol, datasets: list[DatasetManifest]
    ) -> None:
        if any(
            dataset.protocol_id and dataset.protocol_id != protocol.protocol_id
            for dataset in datasets
        ):
            raise ValidationError(
                "a run cannot use a protected dataset bound to another protocol"
            )
        roles = {dataset.role for dataset in datasets}
        if protocol.analysis_mode is AnalysisMode.EXPLORATORY:
            forbidden = roles & {DatasetRole.CONFIRMATORY, DatasetRole.REPLICATION}
            if forbidden:
                raise ValidationError(
                    "exploratory runs cannot inspect confirmatory or replication data"
                )
            required_role = DatasetRole.EXPLORATORY
        elif protocol.analysis_mode is AnalysisMode.CONFIRMATORY:
            forbidden = roles & {DatasetRole.EXPLORATORY, DatasetRole.REPLICATION}
            if forbidden:
                raise ValidationError(
                    "confirmatory runs cannot inspect exploratory or replication data"
                )
            required_role = DatasetRole.CONFIRMATORY
        else:
            forbidden = roles & {DatasetRole.EXPLORATORY, DatasetRole.CONFIRMATORY}
            if forbidden:
                raise ValidationError(
                    "replication runs cannot inspect exploratory or confirmatory data"
                )
            required_role = DatasetRole.REPLICATION

        if (
            protocol.protocol_kind
            in {
                ProtocolKind.OBSERVATIONAL,
                ProtocolKind.EXPERIMENTAL,
            }
            and required_role not in roles
        ):
            raise ValidationError(
                f"{protocol.protocol_kind.value} {protocol.analysis_mode.value} runs "
                f"require a {required_role.value} dataset"
            )

    def _build_protocol(
        self,
        inquiry_id: str,
        command: CreateProtocol,
        *,
        protocol_family_id: str,
        version: int,
        supersedes_protocol_id: str | None = None,
        amendment_reason: str | None = None,
    ) -> ExperimentProtocol:
        if not isinstance(command.analysis_mode, AnalysisMode):
            raise ValidationError("analysis_mode must be an AnalysisMode")
        if not isinstance(command.protocol_kind, ProtocolKind):
            raise ValidationError("protocol_kind must be a ProtocolKind")
        hypotheses = require_text_list(command.hypotheses_tested, "hypotheses_tested")
        if len(set(hypotheses)) != len(hypotheses):
            raise ValidationError("hypotheses_tested must not contain duplicates")
        for hypothesis_id in hypotheses:
            self.repository.find_hypothesis(inquiry_id, hypothesis_id)
        protocol_id = f"{protocol_family_id}-v{version}"
        return ExperimentProtocol(
            protocol_id=protocol_id,
            protocol_family_id=protocol_family_id,
            version=version,
            experiment_id=require_text(command.experiment_id, "experiment_id"),
            title=require_text(command.title, "protocol title"),
            analysis_mode=command.analysis_mode,
            hypotheses_tested=hypotheses,
            primary_outcome=normalize_text(command.primary_outcome, "primary_outcome"),
            created_at=self.clock(),
            created_by=self.actor,
            protocol_kind=command.protocol_kind,
            methodology=normalize_text(command.methodology, "methodology"),
            inputs_required=require_text_list(
                command.inputs_required, "inputs_required"
            ),
            quality_requirements=require_text_list(
                command.quality_requirements, "quality_requirements"
            ),
            controls=require_text_list(command.controls, "controls"),
            measurement_definitions=list(command.measurement_definitions),
            expected_outputs=require_text_list(
                command.expected_outputs, "expected_outputs"
            ),
            success_conditions=require_text_list(
                command.success_conditions, "success_conditions"
            ),
            environment_requirements=require_text_list(
                command.environment_requirements, "environment_requirements"
            ),
            secondary_outcomes=require_text_list(
                command.secondary_outcomes, "secondary_outcomes"
            ),
            independent_variables=require_text_list(
                command.independent_variables, "independent_variables"
            ),
            randomization_plan=normalize_text(
                command.randomization_plan, "randomization_plan"
            ),
            blinding_plan=normalize_text(command.blinding_plan, "blinding_plan"),
            sampling_unit=normalize_text(command.sampling_unit, "sampling_unit"),
            sample_size_or_stopping_rule=normalize_text(
                command.sample_size_or_stopping_rule,
                "sample_size_or_stopping_rule",
            ),
            inclusion_rules=require_text_list(
                command.inclusion_rules, "inclusion_rules"
            ),
            exclusion_rules=require_text_list(
                command.exclusion_rules, "exclusion_rules"
            ),
            sensor_requirements=require_text_list(
                command.sensor_requirements, "sensor_requirements"
            ),
            calibration_requirements=require_text_list(
                command.calibration_requirements, "calibration_requirements"
            ),
            clock_accuracy_requirement=normalize_text(
                command.clock_accuracy_requirement, "clock_accuracy_requirement"
            ),
            preprocessing_pipeline=normalize_text(
                command.preprocessing_pipeline, "preprocessing_pipeline"
            ),
            statistical_model=normalize_text(
                command.statistical_model, "statistical_model"
            ),
            control_windows=require_text_list(
                command.control_windows, "control_windows"
            ),
            multiple_testing_policy=normalize_text(
                command.multiple_testing_policy, "multiple_testing_policy"
            ),
            missing_data_policy=normalize_text(
                command.missing_data_policy, "missing_data_policy"
            ),
            failure_conditions=require_text_list(
                command.failure_conditions, "failure_conditions"
            ),
            safety_constraints=require_text_list(
                command.safety_constraints, "safety_constraints"
            ),
            analysis_code_hash=normalize_text(
                command.analysis_code_hash, "analysis_code_hash"
            ).lower(),
            external_anchor=(
                normalize_text(command.external_anchor, "external_anchor")
                if command.external_anchor is not None
                else None
            ),
            random_seed_commitment=(
                normalize_text(
                    command.random_seed_commitment, "random_seed_commitment"
                ).lower()
                if command.random_seed_commitment is not None
                else None
            ),
            supersedes_protocol_id=supersedes_protocol_id,
            amendment_reason=amendment_reason,
        )

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
