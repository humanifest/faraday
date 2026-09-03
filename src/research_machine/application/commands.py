from __future__ import annotations

from dataclasses import dataclass, field

from research_machine.domain.models import (
    ActionCandidate,
    AnalysisMode,
    ClaimLevel,
    DatasetArtifact,
    DatasetRole,
    EvidenceDirection,
    ProtocolKind,
    QualityGateResult,
    RejectionType,
    SelectionWeights,
    ValidationTag,
)


@dataclass(frozen=True)
class CreateInquiry:
    title: str
    initial_statement: str
    inquiry_id: str | None = None


@dataclass(frozen=True)
class AddQuestion:
    text: str


@dataclass(frozen=True)
class AddClaim:
    statement: str
    level: ClaimLevel
    parent_claims: list[str] = field(default_factory=list)
    scope: str = ""


@dataclass(frozen=True)
class ProposeHypothesis:
    statement: str
    generated_by: str = "codex"
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


@dataclass(frozen=True)
class RetireHypothesis:
    hypothesis_id: str
    rejection_type: RejectionType
    reason: str
    limitations: str = ""
    resurrection_conditions: list[str] = field(default_factory=list)
    superseded_by: str | None = None


@dataclass(frozen=True)
class RecordEvidence:
    hypothesis_id: str
    direction: EvidenceDirection
    summary: str
    analysis_id: str
    dataset_id: str | None = None
    run_id: str | None = None
    claim_id: str | None = None
    effect_estimate: str = ""
    uncertainty: str = ""
    scope: str = ""
    controls_passed: list[str] = field(default_factory=list)
    controls_failed: list[str] = field(default_factory=list)
    higher_level_conclusions_unsupported: list[str] = field(default_factory=list)
    validation_tags: list[ValidationTag] = field(default_factory=list)
    exploratory: bool = True


@dataclass(frozen=True)
class RegisterDataset:
    name: str
    role: DatasetRole
    artifacts: list[DatasetArtifact]
    dataset_id: str | None = None
    description: str = ""
    observation_unit: str = ""
    source_dataset_ids: list[str] = field(default_factory=list)
    protocol_id: str | None = None
    synthetic: bool = False
    quality_attestations: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CreateProtocol:
    experiment_id: str
    title: str
    analysis_mode: AnalysisMode
    hypotheses_tested: list[str]
    primary_outcome: str
    protocol_kind: ProtocolKind = ProtocolKind.EXPERIMENTAL
    methodology: str = ""
    inputs_required: list[str] = field(default_factory=list)
    quality_requirements: list[str] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)
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
    external_anchor: str | None = None
    random_seed_commitment: str | None = None


@dataclass(frozen=True)
class RecordRun:
    protocol_id: str
    started_at: str
    completed_at: str
    analysis_code_hash: str
    environment_hash: str
    random_seed_reveal: str | None = None
    dataset_ids: list[str] = field(default_factory=list)
    output_artifacts: list[DatasetArtifact] = field(default_factory=list)
    quality_gates: list[QualityGateResult] = field(default_factory=list)
    summary: str = ""
    synthetic: bool = False
    metadata: dict[str, object] = field(default_factory=dict)
    run_id: str | None = None
    artifact_root: str | None = None
    attestation_schema_path: str | None = None
    expected_attestation_schema_sha256: str | None = None


@dataclass(frozen=True)
class RecommendNextAction:
    candidates: list[ActionCandidate]
    weights: SelectionWeights = field(default_factory=SelectionWeights)
