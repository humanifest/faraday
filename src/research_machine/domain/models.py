from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class InquiryStatus(StrEnum):
    CLARIFYING = "clarifying"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    DEFERRED = "deferred"


class ClaimLevel(StrEnum):
    MEASUREMENT_VALIDITY = "measurement_validity"
    STATISTICAL_ASSOCIATION = "statistical_association"
    CAUSAL_DIRECTION = "causal_direction"
    ROBUSTNESS = "robustness"
    MECHANISM = "mechanism"
    ADAPTATION = "adaptation"
    ATTRIBUTION_INTENT = "attribution_intent"
    OTHER = "other"


class HypothesisWorkflowState(StrEnum):
    UNREVIEWED = "unreviewed"
    ACTIVE = "active"
    PARKED = "parked"
    RETIRED = "retired"


class EvidenceAssessment(StrEnum):
    UNASSESSED = "unassessed"
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class ReplicationState(StrEnum):
    UNTESTED = "untested"
    PENDING = "pending"
    REPLICATED = "replicated"
    FAILED = "failed"
    MIXED = "mixed"


class RejectionType(StrEnum):
    EMPIRICALLY_REFUTED = "empirically_refuted"
    WEAKENED = "weakened"
    NOT_IDENTIFIABLE = "not_identifiable"
    INSUFFICIENT_DATA = "insufficient_data"
    MEASUREMENT_INVALID = "measurement_invalid"
    REDUNDANT = "redundant"
    SUPERSEDED = "superseded"
    OUT_OF_SCOPE = "out_of_scope"
    CURRENTLY_UNTESTABLE = "currently_untestable"
    ETHICALLY_PROHIBITED = "ethically_prohibited"


class EvidenceDirection(StrEnum):
    SUPPORTS = "supports"
    WEAKENS = "weakens"
    REFUTES = "refutes"
    INCONCLUSIVE = "inconclusive"


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


class Serializable:
    def to_dict(self) -> dict[str, Any]:
        # Concrete subclasses are dataclasses; keeping the mixin undecorated avoids
        # injecting fields or constructor behavior into the domain models.
        return _jsonable(asdict(self))  # type: ignore[call-overload]


@dataclass(frozen=True)
class Inquiry(Serializable):
    inquiry_id: str
    title: str
    initial_statement: str
    created_at: str
    status: InquiryStatus = InquiryStatus.CLARIFYING
    current_synthesis_path: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Inquiry":
        return cls(
            inquiry_id=value["inquiry_id"],
            title=value["title"],
            initial_statement=value["initial_statement"],
            created_at=value["created_at"],
            status=InquiryStatus(value.get("status", InquiryStatus.CLARIFYING)),
            current_synthesis_path=value.get("current_synthesis_path"),
        )


@dataclass(frozen=True)
class Question(Serializable):
    question_id: str
    text: str
    created_at: str
    status: QuestionStatus = QuestionStatus.OPEN
    answer: str | None = None
    answered_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Question":
        return cls(
            question_id=value["question_id"],
            text=value["text"],
            created_at=value["created_at"],
            status=QuestionStatus(value.get("status", QuestionStatus.OPEN)),
            answer=value.get("answer"),
            answered_at=value.get("answered_at"),
        )


@dataclass(frozen=True)
class Claim(Serializable):
    claim_id: str
    statement: str
    level: ClaimLevel
    created_at: str
    parent_claims: list[str] = field(default_factory=list)
    scope: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Claim":
        return cls(
            claim_id=value["claim_id"],
            statement=value["statement"],
            level=ClaimLevel(value["level"]),
            created_at=value["created_at"],
            parent_claims=list(value.get("parent_claims", [])),
            scope=value.get("scope", ""),
        )


@dataclass(frozen=True)
class Hypothesis(Serializable):
    hypothesis_id: str
    statement: str
    created_at: str
    generated_by: str
    parent_claims: list[str] = field(default_factory=list)
    lineage: list[str] = field(default_factory=list)
    source_context: list[str] = field(default_factory=list)
    scope: str = ""
    observable_prediction: str = ""
    null_model: str = ""
    competing_models: list[str] = field(default_factory=list)
    causal_direction: str = ""
    primary_estimand: str = ""
    expected_effect_direction: str = ""
    time_window: str = ""
    covariates: list[str] = field(default_factory=list)
    known_confounds: list[str] = field(default_factory=list)
    falsification_conditions: list[str] = field(default_factory=list)
    support_conditions: list[str] = field(default_factory=list)
    boundary_conditions: list[str] = field(default_factory=list)
    required_replications: int | None = None
    workflow_state: HypothesisWorkflowState = HypothesisWorkflowState.UNREVIEWED
    evidence_assessment: EvidenceAssessment = EvidenceAssessment.UNASSESSED
    replication_state: ReplicationState = ReplicationState.UNTESTED
    activated_at: str | None = None
    retirement: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Hypothesis":
        copied = dict(value)
        copied["workflow_state"] = HypothesisWorkflowState(
            copied.get("workflow_state", HypothesisWorkflowState.UNREVIEWED)
        )
        copied["evidence_assessment"] = EvidenceAssessment(
            copied.get("evidence_assessment", EvidenceAssessment.UNASSESSED)
        )
        copied["replication_state"] = ReplicationState(
            copied.get("replication_state", ReplicationState.UNTESTED)
        )
        return cls(**copied)


@dataclass(frozen=True)
class EvidenceRecord(Serializable):
    evidence_id: str
    hypothesis_id: str
    direction: EvidenceDirection
    summary: str
    dataset_id: str
    analysis_id: str
    created_at: str
    claim_id: str | None = None
    effect_estimate: str = ""
    uncertainty: str = ""
    scope: str = ""
    controls_passed: list[str] = field(default_factory=list)
    controls_failed: list[str] = field(default_factory=list)
    higher_level_conclusions_unsupported: list[str] = field(default_factory=list)
    exploratory: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvidenceRecord":
        copied = dict(value)
        copied["direction"] = EvidenceDirection(copied["direction"])
        return cls(**copied)
