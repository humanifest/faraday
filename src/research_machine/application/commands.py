from __future__ import annotations

from dataclasses import dataclass, field

from research_machine.domain.models import (
    ActionCandidate,
    ActionLane,
    AnalysisMode,
    AnalysisContract,
    AnalysisImplementationBundleContract,
    AnalysisStepContract,
    CanaryTargetPlan,
    ConclusionContract,
    ComputationRouteSeparationContract,
    CalibrationCriterion,
    ClaimDisposition,
    ClaimEpistemicLayer,
    ClaimLevel,
    DatasetArtifact,
    DatasetRole,
    DualityReconstructionContract,
    EvidenceDirection,
    MeasurementDefinition,
    MathematicalPredicateContract,
    NamedComponentContract,
    MeasurementValidityCheck,
    ControlDefinition,
    ProtocolKind,
    QualityGateResult,
    ReconstructionFamilyStabilityContract,
    BoundedNegativeSearchContract,
    RejectionType,
    RuntimePreflightRequirement,
    SelectionWeights,
    ValidationTag,
)


@dataclass(frozen=True)
class RecordEthicsReviewEvent:
    protocol_id: str
    status: str
    effective_at: str
    reason: str
    review_artifact_locator: str
    review_artifact_sha256: str
    review_artifact_root: str
    expires_at: str | None = None
    supersedes_event_id: str | None = None
    event_id: str | None = None


@dataclass(frozen=True)
class RecordEvidenceStatusEvent:
    evidence_id: str
    status: str
    effective_at: str
    reason: str
    review_artifact_locator: str
    review_artifact_sha256: str
    review_artifact_root: str
    supersedes_event_id: str | None = None
    event_id: str | None = None


@dataclass(frozen=True)
class CreateInquiry:
    title: str
    initial_statement: str
    inquiry_id: str | None = None
    decision_to_support: str = ""
    minimum_evidence: str = ""
    decision_change_criteria: list[str] = field(default_factory=list)
    decision_owner: str = ""


@dataclass(frozen=True)
class SetInquiryDecision:
    decision_to_support: str
    minimum_evidence: str
    decision_change_criteria: list[str]
    decision_owner: str = ""


@dataclass(frozen=True)
class AddQuestion:
    text: str


@dataclass(frozen=True)
class DeferQuestion:
    rationale: str


@dataclass(frozen=True)
class AddClaim:
    statement: str
    level: ClaimLevel
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


@dataclass(frozen=True)
class ReviewClaim:
    claim_id: str
    epistemic_layer: ClaimEpistemicLayer | None = None
    disposition: ClaimDisposition | None = None
    confidence: float | None = None
    source_refs: list[str] | None = None
    conflicts_with: list[str] | None = None
    falsified_by: list[str] | None = None
    reviewed_at: str | None = None
    decision_owner: str | None = None


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
    contrast_definition: str = ""
    contrast_groups: list[str] = field(default_factory=list)
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
    analysis_output_sha256: str = ""
    effect_estimate_path: str = ""
    uncertainty_path: str = ""


@dataclass(frozen=True)
class ExportSherlockEvidence:
    evidence_id: str
    output_dir: str
    sherlock_case_id: str = "faraday-research-bridge"
    sherlock_kind: str = "annotation"
    sherlock_id: str | None = None
    sherlock_artifact_sha256: str | None = None


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
    artifact_root: str | None = None
    custody_artifact_root: str | None = None
    ethics_artifact_root: str | None = None


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
    control_definitions: list[ControlDefinition] = field(default_factory=list)
    measurement_definitions: list[MeasurementDefinition] = field(default_factory=list)
    named_component_contracts: list[NamedComponentContract] = field(default_factory=list)
    mathematical_predicate_contracts: list[MathematicalPredicateContract] = field(
        default_factory=list
    )
    duality_reconstruction_contracts: list[DualityReconstructionContract] = field(
        default_factory=list
    )
    reconstruction_family_stability_contracts: list[
        ReconstructionFamilyStabilityContract
    ] = field(default_factory=list)
    analysis_implementation_bundle_contracts: list[
        AnalysisImplementationBundleContract
    ] = field(default_factory=list)
    computation_route_separation_contracts: list[
        ComputationRouteSeparationContract
    ] = field(default_factory=list)
    bounded_negative_search_contracts: list[
        BoundedNegativeSearchContract
    ] = field(default_factory=list)
    measurement_validity_checks: list[MeasurementValidityCheck] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    success_conditions: list[str] = field(default_factory=list)
    environment_requirements: list[str] = field(default_factory=list)
    runtime_preflight_requirement: RuntimePreflightRequirement | None = None
    notebook_freeze_input_bundle_sha256: str | None = None
    secondary_outcomes: list[str] = field(default_factory=list)
    confirmatory_outcomes: list[str] = field(default_factory=list)
    exploratory_outcomes: list[str] = field(default_factory=list)
    multiplicity_method: str = ""
    multiplicity_alpha: float | None = None
    independent_variables: list[str] = field(default_factory=list)
    manipulated_factors: list[str] = field(default_factory=list)
    factorial_or_crossover_design: bool = False
    factor_interpretability_plan: str = ""
    canary_target_plan: CanaryTargetPlan | None = None
    randomization_plan: str = ""
    blinding_plan: str = ""
    sampling_unit: str = ""
    independent_unit: str = ""
    repeated_measures: bool | None = None
    analysis_design: str = ""
    unit_analysis_plan: str = ""
    unit_id_column: str = ""
    analysis_specification_sha256: str = ""
    analysis_contract: AnalysisContract | None = None
    analysis_steps: list[AnalysisStepContract] = field(default_factory=list)
    conclusion_contract: ConclusionContract | None = None
    sample_size_or_stopping_rule: str = ""
    sample_size_plan: dict[str, object] = field(default_factory=dict)
    inclusion_rules: list[str] = field(default_factory=list)
    exclusion_rules: list[str] = field(default_factory=list)
    sensor_requirements: list[str] = field(default_factory=list)
    calibration_requirements: list[str] = field(default_factory=list)
    calibration_acceptance_criteria: list[CalibrationCriterion] = field(default_factory=list)
    measurement_custody_requirements: list[str] = field(default_factory=list)
    clock_accuracy_requirement: str = ""
    preprocessing_pipeline: str = ""
    statistical_model: str = ""
    control_windows: list[str] = field(default_factory=list)
    multiple_testing_policy: str = ""
    missing_data_policy: str = ""
    causal_claim: bool = False
    causal_identification: dict[str, object] = field(default_factory=dict)
    failure_conditions: list[str] = field(default_factory=list)
    safety_constraints: list[str] = field(default_factory=list)
    human_subjects: bool = False
    consent_plan: str = ""
    withdrawal_plan: str = ""
    privacy_plan: str = ""
    retention_deletion_plan: str = ""
    risk_assessment: str = ""
    vulnerable_population_plan: str = ""
    data_security_plan: str = ""
    incidental_findings_plan: str = ""
    independent_review_receipt: str = ""
    independent_review_decision: str = ""
    independent_reviewer_role: str = ""
    independent_reviewed_at: str = ""
    independent_review_scope: str = ""
    independent_review_artifact_locator: str = ""
    independent_review_artifact_sha256: str = ""
    independent_review_conditions: list[str] = field(default_factory=list)
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
    audit_artifact_root: str | None = None


@dataclass(frozen=True)
class RecommendActionPortfolio:
    lanes: list[ActionLane]
    candidates: list[ActionCandidate]
    completed_action_ids: list[str] = field(default_factory=list)
    weights: SelectionWeights = field(default_factory=SelectionWeights)
    audit_artifact_root: str | None = None


@dataclass(frozen=True)
class RecordCrossLaneLesson:
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
