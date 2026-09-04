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


class ClaimEpistemicLayer(StrEnum):
    DOCUMENTED_FACT = "documented_fact"
    SOURCE_CLAIM = "source_claim"
    PROJECT_INTERPRETATION = "project_interpretation"
    REASONABLE_INFERENCE = "reasonable_inference"
    UNRESOLVED = "unresolved"


class ClaimDisposition(StrEnum):
    UNRESOLVED = "unresolved"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class HypothesisWorkflowState(StrEnum):
    UNREVIEWED = "unreviewed"
    PENDING_REVIEW = "pending_review"
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


class ValidationTag(StrEnum):
    SOURCE_ASSESSMENT = "source_assessment"
    CALIBRATION = "calibration"
    INTERNAL_CONSISTENCY = "internal_consistency"
    CONTROLLED_BENCHMARK = "controlled_benchmark"
    INDEPENDENT_REPLICATION = "independent_replication"
    KNOWN_RESULT_REPRODUCTION = "known_result_reproduction"
    NOVEL_PREDICTION = "novel_prediction"
    EMPIRICAL_TEST = "empirical_test"


class DatasetRole(StrEnum):
    CALIBRATION = "calibration"
    EXPLORATORY = "exploratory"
    TRAINING = "training"
    CONFIRMATORY = "confirmatory"
    REPLICATION = "replication"


class AnalysisMode(StrEnum):
    EXPLORATORY = "exploratory"
    CONFIRMATORY = "confirmatory"
    REPLICATION = "replication"


class ProtocolStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"


class ProtocolKind(StrEnum):
    OBSERVATIONAL = "observational"
    EXPERIMENTAL = "experimental"
    COMPUTATIONAL = "computational"
    FORMAL = "formal"
    LITERATURE = "literature"
    SYNTHESIS = "synthesis"


class MeasurementRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    CONTROL = "control"


class QualityGateStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


class RunStatus(StrEnum):
    COMPLETED = "completed"
    INVALID = "invalid"
    FAILED = "failed"


class RigorSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


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
    decision_to_support: str = ""
    minimum_evidence: str = ""
    decision_change_criteria: list[str] = field(default_factory=list)
    decision_owner: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Inquiry":
        return cls(
            inquiry_id=value["inquiry_id"],
            title=value["title"],
            initial_statement=value["initial_statement"],
            created_at=value["created_at"],
            status=InquiryStatus(value.get("status", InquiryStatus.CLARIFYING)),
            current_synthesis_path=value.get("current_synthesis_path"),
            decision_to_support=value.get("decision_to_support", ""),
            minimum_evidence=value.get("minimum_evidence", ""),
            decision_change_criteria=list(value.get("decision_change_criteria", [])),
            decision_owner=value.get("decision_owner", ""),
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
    epistemic_layer: ClaimEpistemicLayer = ClaimEpistemicLayer.UNRESOLVED
    disposition: ClaimDisposition = ClaimDisposition.UNRESOLVED
    confidence: float | None = None
    source_refs: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    falsified_by: list[str] = field(default_factory=list)
    last_reviewed: str | None = None
    decision_owner: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Claim":
        return cls(
            claim_id=value["claim_id"],
            statement=value["statement"],
            level=ClaimLevel(value["level"]),
            created_at=value["created_at"],
            parent_claims=list(value.get("parent_claims", [])),
            scope=value.get("scope", ""),
            epistemic_layer=ClaimEpistemicLayer(
                value.get("epistemic_layer", ClaimEpistemicLayer.UNRESOLVED)
            ),
            disposition=ClaimDisposition(
                value.get("disposition", ClaimDisposition.UNRESOLVED)
            ),
            confidence=value.get("confidence"),
            source_refs=list(value.get("source_refs", [])),
            conflicts_with=list(value.get("conflicts_with", [])),
            falsified_by=list(value.get("falsified_by", [])),
            last_reviewed=value.get("last_reviewed"),
            decision_owner=value.get("decision_owner", ""),
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
    pending_review_at: str | None = None
    pending_review_by: str | None = None
    pending_review_confidence: str = ""
    pending_review_rationale: str = ""
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
    dataset_id: str | None
    analysis_id: str
    created_at: str
    claim_id: str | None = None
    protocol_id: str | None = None
    run_id: str | None = None
    scientific_evidence_eligible: bool = False
    effect_estimate: str = ""
    uncertainty: str = ""
    scope: str = ""
    controls_passed: list[str] = field(default_factory=list)
    controls_failed: list[str] = field(default_factory=list)
    higher_level_conclusions_unsupported: list[str] = field(default_factory=list)
    validation_tags: list[ValidationTag] = field(default_factory=list)
    exploratory: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvidenceRecord":
        copied = dict(value)
        copied["direction"] = EvidenceDirection(copied["direction"])
        copied["validation_tags"] = [
            ValidationTag(item) for item in copied.get("validation_tags", [])
        ]
        return cls(**copied)


@dataclass(frozen=True)
class DatasetArtifact(Serializable):
    locator: str
    sha256: str
    size_bytes: int | None = None
    media_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DatasetArtifact":
        return cls(**value)


@dataclass(frozen=True)
class DatasetManifest(Serializable):
    dataset_id: str
    name: str
    role: DatasetRole
    created_at: str
    artifacts: list[DatasetArtifact]
    description: str = ""
    observation_unit: str = ""
    source_dataset_ids: list[str] = field(default_factory=list)
    protocol_id: str | None = None
    synthetic: bool = False
    quality_attestations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DatasetManifest":
        copied = dict(value)
        copied["role"] = DatasetRole(copied["role"])
        copied["artifacts"] = [
            DatasetArtifact.from_dict(item) for item in copied.get("artifacts", [])
        ]
        return cls(**copied)


@dataclass(frozen=True)
class MeasurementDefinition(Serializable):
    measurement_id: str
    role: MeasurementRole
    registered_target: str
    observable: str
    input_condition: str
    parameter_values: dict[str, str]
    evaluation_point: str
    convention: str
    aggregation: str
    tolerance: str
    expected_behavior: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MeasurementDefinition":
        copied = dict(value)
        copied["role"] = MeasurementRole(copied["role"])
        return cls(**copied)


@dataclass(frozen=True)
class ExperimentProtocol(Serializable):
    protocol_id: str
    protocol_family_id: str
    version: int
    experiment_id: str
    title: str
    analysis_mode: AnalysisMode
    hypotheses_tested: list[str]
    primary_outcome: str
    created_at: str
    created_by: str
    protocol_kind: ProtocolKind = ProtocolKind.EXPERIMENTAL
    methodology: str = ""
    inputs_required: list[str] = field(default_factory=list)
    quality_requirements: list[str] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)
    measurement_definitions: list[MeasurementDefinition] = field(
        default_factory=list
    )
    expected_outputs: list[str] = field(default_factory=list)
    success_conditions: list[str] = field(default_factory=list)
    environment_requirements: list[str] = field(default_factory=list)
    secondary_outcomes: list[str] = field(default_factory=list)
    independent_variables: list[str] = field(default_factory=list)
    randomization_plan: str = ""
    blinding_plan: str = ""
    sampling_unit: str = ""
    sample_size_or_stopping_rule: str = ""
    inclusion_rules: list[str] = field(default_factory=list)
    exclusion_rules: list[str] = field(default_factory=list)
    sensor_requirements: list[str] = field(default_factory=list)
    calibration_requirements: list[str] = field(default_factory=list)
    clock_accuracy_requirement: str = ""
    preprocessing_pipeline: str = ""
    statistical_model: str = ""
    control_windows: list[str] = field(default_factory=list)
    multiple_testing_policy: str = ""
    missing_data_policy: str = ""
    failure_conditions: list[str] = field(default_factory=list)
    safety_constraints: list[str] = field(default_factory=list)
    analysis_code_hash: str = ""
    status: ProtocolStatus = ProtocolStatus.DRAFT
    protocol_hash: str | None = None
    registration_timestamp: str | None = None
    external_anchor: str | None = None
    random_seed_commitment: str | None = None
    supersedes_protocol_id: str | None = None
    amendment_reason: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExperimentProtocol":
        copied = dict(value)
        copied["analysis_mode"] = AnalysisMode(copied["analysis_mode"])
        copied["status"] = ProtocolStatus(copied.get("status", ProtocolStatus.DRAFT))
        copied["protocol_kind"] = ProtocolKind(
            copied.get("protocol_kind", ProtocolKind.EXPERIMENTAL)
        )
        copied["measurement_definitions"] = [
            item
            if isinstance(item, MeasurementDefinition)
            else MeasurementDefinition.from_dict(item)
            for item in copied.get("measurement_definitions", [])
        ]
        return cls(**copied)


# ``ResearchProtocol`` is the domain-neutral name.  Keep the original class name
# as the serialized/backwards-compatible API while clients migrate terminology.
ResearchProtocol = ExperimentProtocol


@dataclass(frozen=True)
class QualityGateResult(Serializable):
    gate_id: str
    status: QualityGateStatus
    summary: str
    required: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QualityGateResult":
        copied = dict(value)
        copied["status"] = QualityGateStatus(copied["status"])
        return cls(**copied)


@dataclass(frozen=True)
class ResearchRun(Serializable):
    run_id: str
    protocol_id: str
    protocol_hash: str
    analysis_mode: AnalysisMode
    started_at: str
    completed_at: str
    executed_by: str
    analysis_code_hash: str
    environment_hash: str
    random_seed_reveal: str | None = None
    dataset_ids: list[str] = field(default_factory=list)
    output_artifacts: list[DatasetArtifact] = field(default_factory=list)
    quality_gates: list[QualityGateResult] = field(default_factory=list)
    status: RunStatus = RunStatus.COMPLETED
    scientific_evidence_eligible: bool = False
    summary: str = ""
    synthetic: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ResearchRun":
        copied = dict(value)
        copied["analysis_mode"] = AnalysisMode(copied["analysis_mode"])
        copied["status"] = RunStatus(copied.get("status", RunStatus.COMPLETED))
        copied["output_artifacts"] = [
            DatasetArtifact.from_dict(item)
            for item in copied.get("output_artifacts", [])
        ]
        copied["quality_gates"] = [
            QualityGateResult.from_dict(item)
            for item in copied.get("quality_gates", [])
        ]
        return cls(**copied)


@dataclass(frozen=True)
class RunRecordPreflight(Serializable):
    status: str
    would_append_event: bool
    protocol_id: str
    protocol_hash: str
    requested_run_id: str | None
    requested_run_id_conflicts: bool
    record_status_if_submitted: RunStatus | None
    scientific_evidence_eligible_if_submitted: bool | None
    synthetic_if_submitted: bool
    required_quality_gate_ids: list[str]
    provided_quality_gate_ids: list[str]
    missing_quality_gate_ids: list[str]
    unexpected_quality_gate_ids: list[str]
    failed_required_gate_ids: list[str]
    failed_protocol_gate_ids: list[str]
    exact_quality_gate_set: bool
    quality_gate_order_matches_protocol: bool
    artifact_integrity: dict[str, Any] | None
    protocol_chronology: dict[str, Any]
    conclusion_ceiling: str


@dataclass(frozen=True)
class RigorFinding(Serializable):
    code: str
    severity: RigorSeverity
    message: str
    entity_type: str = "workspace"
    entity_id: str = ""
    remediation: str = ""


@dataclass(frozen=True)
class RigorAudit(Serializable):
    structurally_valid: bool
    conclusion_ceiling: str
    capabilities: dict[str, bool]
    evidence_counts: dict[str, int]
    findings: list[RigorFinding] = field(default_factory=list)


@dataclass(frozen=True)
class ActionCandidate(Serializable):
    action_id: str
    title: str
    distinguishes_hypotheses: list[str]
    expected_discrimination: float
    uncertainty_reduction: float
    cost: float
    burden: float
    safety_risk: float
    ambiguity_risk: float
    rationale: str
    prerequisites_met: bool = True
    safety_approved: bool = True
    lane_id: str = "default"
    information_targets: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionCandidate":
        return cls(**value)


@dataclass(frozen=True)
class SelectionWeights(Serializable):
    expected_discrimination: float = 1.0
    uncertainty_reduction: float = 0.5
    cost: float = 0.25
    burden: float = 0.35
    safety_risk: float = 0.75
    ambiguity_risk: float = 0.75

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SelectionWeights":
        return cls(**value)


@dataclass(frozen=True)
class ActionScore(Serializable):
    action_id: str
    utility: float

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionScore":
        return cls(**value)


@dataclass(frozen=True)
class ActionLane(Serializable):
    lane_id: str
    title: str
    status: str = "active"
    blocked_on: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionLane":
        return cls(**value)


@dataclass(frozen=True)
class ActionRecommendation(Serializable):
    recommendation_id: str
    selected_action_id: str
    created_at: str
    created_by: str
    rationale: str
    candidates: list[ActionCandidate]
    ranked_scores: list[ActionScore]
    weights: SelectionWeights
    selection_mode: str = "single"
    selected_action_ids_by_lane: dict[str, str] = field(default_factory=dict)
    lanes: list[ActionLane] = field(default_factory=list)
    completed_action_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionRecommendation":
        copied = dict(value)
        copied["ranked_scores"] = [
            ActionScore.from_dict(item) for item in copied.get("ranked_scores", [])
        ]
        copied["candidates"] = [
            ActionCandidate.from_dict(item) for item in copied.get("candidates", [])
        ]
        copied["weights"] = SelectionWeights.from_dict(copied.get("weights", {}))
        copied["lanes"] = [
            ActionLane.from_dict(item) for item in copied.get("lanes", [])
        ]
        return cls(**copied)


@dataclass(frozen=True)
class CrossLaneLesson(Serializable):
    lesson_id: str
    origin_lane_id: str
    target_lane_ids: list[str]
    origin_artifact_locator: str
    origin_artifact_sha256: str
    origin_integrity_status: str
    observation: str
    failure_class: str
    strongest_alternative_explanation: str
    challenged_invariant: str
    first_permitted_future_versions: list[str]
    prohibited_retroactive_targets: list[str]
    proposed_repair: str
    repair_falsifier: str
    conclusion_ceiling: str
    created_at: str
    created_by: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CrossLaneLesson":
        return cls(**value)
