from collections.abc import Sequence
import math
import re

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ActionCandidate,
    ActionLane,
    AnalysisMode,
    DatasetManifest,
    DatasetArtifact,
    EvidenceDirection,
    ExperimentProtocol,
    Hypothesis,
    HypothesisWorkflowState,
    MeasurementDefinition,
    MeasurementRole,
    ProtocolKind,
    ProtocolStatus,
    QualityGateResult,
    QualityGateStatus,
    ResearchRun,
    SelectionWeights,
    ValidationTag,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def require_sha256(value: str, field_name: str) -> str:
    digest = require_text(value, field_name).lower()
    if not _SHA256.fullmatch(digest):
        raise ValidationError(f"{field_name} must be 64 lowercase hex characters")
    return digest


def normalize_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    return value.strip()


def require_text(value: str, field_name: str) -> str:
    normalized = normalize_text(value, field_name)
    if not normalized:
        raise ValidationError(f"{field_name} must not be empty")
    return normalized


def require_text_list(values: Sequence[str], field_name: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValidationError(f"{field_name} must be a list of text values")
    return [require_text(value, f"{field_name} item") for value in values]


def require_unique_text_list(values: Sequence[str], field_name: str) -> list[str]:
    normalized = require_text_list(values, field_name)
    if len(set(normalized)) != len(normalized):
        raise ValidationError(f"{field_name} must not contain duplicates")
    return normalized


def normalize_confidence(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("confidence must be a number from 0 through 1 or null")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0 <= normalized <= 1:
        raise ValidationError("confidence must be a number from 0 through 1 or null")
    return normalized


def validate_hypothesis_activation(hypothesis: Hypothesis) -> None:
    if hypothesis.workflow_state not in {
        HypothesisWorkflowState.UNREVIEWED,
        HypothesisWorkflowState.PENDING_REVIEW,
        HypothesisWorkflowState.PARKED,
    }:
        raise ValidationError(
            f"hypothesis {hypothesis.hypothesis_id} cannot be activated from "
            f"{hypothesis.workflow_state.value}"
        )
    missing: list[str] = []
    if not hypothesis.observable_prediction.strip():
        missing.append("observable_prediction")
    if not hypothesis.falsification_conditions:
        missing.append("falsification_conditions")
    if not hypothesis.null_model.strip() and not hypothesis.competing_models:
        missing.append("null_model or competing_models")
    if missing:
        raise ValidationError(
            "hypothesis cannot be activated until it defines: " + ", ".join(missing)
        )


def validate_hypothesis_staging(hypothesis: Hypothesis) -> None:
    if hypothesis.workflow_state not in {
        HypothesisWorkflowState.UNREVIEWED,
        HypothesisWorkflowState.PARKED,
    }:
        raise ValidationError(
            f"hypothesis {hypothesis.hypothesis_id} cannot be staged from "
            f"{hypothesis.workflow_state.value}"
        )
    missing: list[str] = []
    if not hypothesis.observable_prediction.strip():
        missing.append("observable_prediction")
    if not hypothesis.falsification_conditions:
        missing.append("falsification_conditions")
    if not hypothesis.null_model.strip() and not hypothesis.competing_models:
        missing.append("null_model or competing_models")
    if missing:
        raise ValidationError(
            "hypothesis cannot enter pending review until it defines: "
            + ", ".join(missing)
        )


def validate_evidence_target(hypothesis: Hypothesis, *, exploratory: bool) -> None:
    if hypothesis.workflow_state is HypothesisWorkflowState.UNREVIEWED:
        raise ValidationError(
            "evidence cannot be attached to an unreviewed proposal; stage or activate "
            "it first"
        )
    if (
        hypothesis.workflow_state is HypothesisWorkflowState.PENDING_REVIEW
        and not exploratory
    ):
        raise ValidationError(
            "confirmatory evidence cannot be attached while human review is pending"
        )


def validate_evidence_annotations(
    *,
    direction: EvidenceDirection,
    scope: str,
    uncertainty: str,
    controls_passed: Sequence[str],
    controls_failed: Sequence[str],
    higher_level_conclusions_unsupported: Sequence[str],
    validation_tags: Sequence[ValidationTag],
) -> tuple[str, str, list[str], list[str], list[str], list[ValidationTag]]:
    normalized_scope = require_text(scope, "scope")
    normalized_uncertainty = require_text(uncertainty, "uncertainty")
    passed = require_text_list(controls_passed, "controls_passed")
    failed = require_text_list(controls_failed, "controls_failed")
    ceilings = require_text_list(
        higher_level_conclusions_unsupported,
        "higher_level_conclusions_unsupported",
    )
    if not ceilings:
        raise ValidationError(
            "higher_level_conclusions_unsupported must name at least one claim ceiling"
        )
    if direction in {
        EvidenceDirection.SUPPORTS,
        EvidenceDirection.WEAKENS,
        EvidenceDirection.REFUTES,
    } and not (passed or failed):
        raise ValidationError(
            "directional evidence must record at least one passed or failed control"
        )
    if isinstance(validation_tags, (str, bytes)) or not isinstance(
        validation_tags, Sequence
    ):
        raise ValidationError("validation_tags must be a list")
    tags: list[ValidationTag] = []
    for value in validation_tags:
        if not isinstance(value, ValidationTag):
            raise ValidationError("validation_tags must contain ValidationTag values")
        tags.append(value)
    if not tags:
        raise ValidationError(
            "validation_tags must classify the evidence; unclassified new evidence "
            "is not permitted"
        )
    if len(set(tags)) != len(tags):
        raise ValidationError("validation_tags must not contain duplicates")
    return (
        normalized_scope,
        normalized_uncertainty,
        passed,
        failed,
        ceilings,
        tags,
    )


def validate_validation_tag_context(
    *,
    tags: Sequence[ValidationTag],
    hypothesis: Hypothesis,
    exploratory: bool,
    protocol: ExperimentProtocol | None,
    run: ResearchRun | None,
    datasets: Sequence[DatasetManifest],
    controls_passed: Sequence[str],
    replicated_run: ResearchRun | None,
) -> None:
    tag_set = set(tags)

    def require_eligible_run(tag: ValidationTag) -> ResearchRun:
        if run is None or not run.scientific_evidence_eligible:
            raise ValidationError(
                f"validation tag {tag.value} requires an eligible recorded run"
            )
        return run

    if ValidationTag.SOURCE_ASSESSMENT in tag_set:
        if run is not None and (
            protocol is None or protocol.protocol_kind is not ProtocolKind.LITERATURE
        ):
            raise ValidationError(
                "source_assessment requires a literature run or dataset-only evidence"
            )
        if run is None and not datasets:
            raise ValidationError(
                "source_assessment requires a dataset or literature run"
            )

    if ValidationTag.CALIBRATION in tag_set and run is None and not datasets:
        raise ValidationError("calibration requires a dataset or recorded run")

    if ValidationTag.INTERNAL_CONSISTENCY in tag_set:
        require_eligible_run(ValidationTag.INTERNAL_CONSISTENCY)

    if ValidationTag.CONTROLLED_BENCHMARK in tag_set:
        require_eligible_run(ValidationTag.CONTROLLED_BENCHMARK)
        if protocol is None or not protocol.controls:
            raise ValidationError(
                "controlled_benchmark requires a protocol with registered controls"
            )
        if not controls_passed:
            raise ValidationError(
                "controlled_benchmark requires at least one recorded passed control"
            )

    if ValidationTag.INDEPENDENT_REPLICATION in tag_set:
        current = require_eligible_run(ValidationTag.INDEPENDENT_REPLICATION)
        if current.analysis_mode is not AnalysisMode.REPLICATION:
            raise ValidationError(
                "independent_replication requires a replication-mode run"
            )
        if replicated_run is None:
            raise ValidationError(
                "independent_replication requires run metadata.replicates_run_id"
            )
        if not replicated_run.scientific_evidence_eligible:
            raise ValidationError(
                "independent_replication target must be an eligible recorded run"
            )
        if current.executed_by == replicated_run.executed_by:
            raise ValidationError(
                "independent_replication requires a different executor identity"
            )
        if current.analysis_code_hash == replicated_run.analysis_code_hash:
            raise ValidationError(
                "independent_replication requires a distinct analysis-code hash"
            )
        independence = current.metadata.get("replication_independence")
        if not isinstance(independence, dict):
            raise ValidationError(
                "independent_replication requires run metadata.replication_independence"
            )
        if independence.get("design") != "clean_room":
            raise ValidationError(
                "independent_replication requires a clean_room replication design"
            )
        dimensions = require_text_list(
            independence.get("independence_dimensions", []),
            "replication_independence.independence_dimensions",
        )
        missing_dimensions = {"executor", "implementation"} - set(dimensions)
        if missing_dimensions:
            raise ValidationError(
                "independent_replication requires executor and implementation "
                "independence dimensions"
            )
        if independence.get("prior_implementation_accessed") is not False:
            raise ValidationError(
                "independent_replication requires an explicit false "
                "prior_implementation_accessed declaration"
            )
        allowed_inputs = independence.get("allowed_inputs")
        if not isinstance(allowed_inputs, list) or not allowed_inputs:
            raise ValidationError(
                "independent_replication requires a non-empty allowed_inputs manifest"
            )
        for index, item in enumerate(allowed_inputs):
            if not isinstance(item, dict):
                raise ValidationError(
                    "replication_independence.allowed_inputs items must be objects"
                )
            require_text(
                item.get("locator", ""),
                f"replication_independence.allowed_inputs[{index}].locator",
            )
            require_sha256(
                item.get("sha256", ""),
                f"replication_independence.allowed_inputs[{index}].sha256",
            )
        disclosures = independence.get("contamination_disclosures")
        if not isinstance(disclosures, list):
            raise ValidationError(
                "independent_replication requires a contamination_disclosures list"
            )
        require_text_list(
            disclosures,
            "replication_independence.contamination_disclosures",
        )
        attestation_locator = require_text(
            independence.get("attestation_artifact", ""),
            "replication_independence.attestation_artifact",
        )
        matching_attestations = [
            artifact
            for artifact in current.output_artifacts
            if artifact.locator == attestation_locator
            and artifact.metadata.get("artifact_role") == "independence_attestation"
        ]
        if not matching_attestations:
            raise ValidationError(
                "independent_replication requires a hashed output artifact matching "
                "attestation_artifact with artifact_role=independence_attestation"
            )
        artifact_integrity = current.metadata.get("artifact_integrity")
        if not isinstance(artifact_integrity, dict):
            raise ValidationError(
                "independent_replication requires machine-verified artifact_integrity"
            )
        if (
            artifact_integrity.get("status") != "passed"
            or artifact_integrity.get("all_artifacts_match") is not True
            or artifact_integrity.get("attestation_schema_matches_commitment")
            is not True
            or artifact_integrity.get("attestation_schema_valid") is not True
            or artifact_integrity.get("attestation_consistent") is not True
        ):
            raise ValidationError(
                "independent_replication requires passed artifact bytes, pinned "
                "attestation schema validation, and run-attestation consistency"
            )

    if ValidationTag.KNOWN_RESULT_REPRODUCTION in tag_set:
        current = require_eligible_run(ValidationTag.KNOWN_RESULT_REPRODUCTION)
        passed_gate_ids = {
            gate.gate_id
            for gate in current.quality_gates
            if gate.status is QualityGateStatus.PASSED
        }
        if "known-result-reproduction" not in passed_gate_ids:
            raise ValidationError(
                "known_result_reproduction requires a passed "
                "known-result-reproduction quality gate"
            )

    if ValidationTag.NOVEL_PREDICTION in tag_set:
        current = require_eligible_run(ValidationTag.NOVEL_PREDICTION)
        if (
            exploratory
            or hypothesis.workflow_state is not HypothesisWorkflowState.ACTIVE
        ):
            raise ValidationError(
                "novel_prediction requires confirmatory evidence for an active hypothesis"
            )
        if current.analysis_mode is not AnalysisMode.CONFIRMATORY:
            raise ValidationError("novel_prediction requires a confirmatory-mode run")
        if protocol is None or not protocol.registration_timestamp:
            raise ValidationError(
                "novel_prediction requires a frozen protocol timestamp"
            )

    if ValidationTag.EMPIRICAL_TEST in tag_set:
        require_eligible_run(ValidationTag.EMPIRICAL_TEST)
        if (
            exploratory
            or hypothesis.workflow_state is not HypothesisWorkflowState.ACTIVE
        ):
            raise ValidationError(
                "empirical_test requires confirmatory evidence for an active hypothesis"
            )
        if protocol is None or protocol.protocol_kind not in {
            ProtocolKind.OBSERVATIONAL,
            ProtocolKind.EXPERIMENTAL,
        }:
            raise ValidationError(
                "empirical_test requires an observational or experimental protocol"
            )
        if not datasets:
            raise ValidationError(
                "empirical_test requires at least one recorded dataset"
            )
        if any(dataset.synthetic for dataset in datasets):
            raise ValidationError("empirical_test cannot use synthetic data")


def validate_dataset_artifacts(
    artifacts: Sequence[DatasetArtifact],
) -> list[DatasetArtifact]:
    if isinstance(artifacts, (str, bytes)) or not isinstance(artifacts, Sequence):
        raise ValidationError("artifacts must be a list")
    if not artifacts:
        raise ValidationError("a dataset must contain at least one hashed artifact")
    normalized: list[DatasetArtifact] = []
    locators: set[str] = set()
    digests: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, DatasetArtifact):
            raise ValidationError("artifacts must be DatasetArtifact values")
        locator = require_text(artifact.locator, "artifact locator")
        digest = require_sha256(artifact.sha256, "artifact sha256")
        if artifact.size_bytes is not None and (
            isinstance(artifact.size_bytes, bool)
            or not isinstance(artifact.size_bytes, int)
            or artifact.size_bytes < 0
        ):
            raise ValidationError("artifact size_bytes must be non-negative or null")
        if not isinstance(artifact.metadata, dict):
            raise ValidationError("artifact metadata must be an object")
        if locator in locators:
            raise ValidationError(f"duplicate artifact locator: {locator}")
        if digest in digests:
            raise ValidationError(f"duplicate artifact digest: {digest}")
        locators.add(locator)
        digests.add(digest)
        normalized.append(
            DatasetArtifact(
                locator=locator,
                sha256=digest,
                size_bytes=artifact.size_bytes,
                media_type=normalize_text(artifact.media_type, "artifact media_type"),
                metadata=dict(artifact.metadata),
            )
        )
    return normalized


def validate_protocol_freeze(protocol: ExperimentProtocol) -> None:
    if protocol.status is not ProtocolStatus.DRAFT:
        raise ValidationError("only draft protocols can be frozen")
    missing: list[str] = []
    required_text = {
        "experiment_id": protocol.experiment_id,
        "title": protocol.title,
        "primary_outcome": protocol.primary_outcome,
        "methodology": protocol.methodology,
        "analysis_code_hash": protocol.analysis_code_hash,
    }
    if protocol.protocol_kind in {
        ProtocolKind.OBSERVATIONAL,
        ProtocolKind.EXPERIMENTAL,
    }:
        required_text.update(
            {
                "sampling_unit": protocol.sampling_unit,
                "sample_size_or_stopping_rule": (protocol.sample_size_or_stopping_rule),
                "preprocessing_pipeline": protocol.preprocessing_pipeline,
                "statistical_model": protocol.statistical_model,
                "multiple_testing_policy": protocol.multiple_testing_policy,
                "missing_data_policy": protocol.missing_data_policy,
            }
        )
    if protocol.protocol_kind is ProtocolKind.EXPERIMENTAL:
        required_text.update(
            {
                "randomization_plan": protocol.randomization_plan,
                "blinding_plan": protocol.blinding_plan,
            }
        )
    for name, value in required_text.items():
        if not isinstance(value, str) or not value.strip():
            missing.append(name)
    if not protocol.hypotheses_tested:
        missing.append("hypotheses_tested")
    if not protocol.quality_requirements:
        missing.append("quality_requirements")
    if not protocol.controls:
        missing.append("controls")
    if (
        not protocol.sample_size_or_stopping_rule.strip()
        and "sample_size_or_stopping_rule" not in missing
    ):
        missing.append("sample_size_or_stopping_rule")
    if not protocol.failure_conditions:
        missing.append("failure_conditions")
    if not protocol.safety_constraints:
        missing.append("safety_constraints")
    if not protocol.expected_outputs:
        missing.append("expected_outputs")
    if not protocol.success_conditions:
        missing.append("success_conditions")
    if len(set(protocol.quality_requirements)) != len(protocol.quality_requirements):
        raise ValidationError("quality_requirements must not contain duplicates")
    if protocol.measurement_definitions:
        validate_measurement_contract(protocol)
    if (
        protocol.protocol_kind
        in {
            ProtocolKind.COMPUTATIONAL,
            ProtocolKind.FORMAL,
        }
        and not protocol.environment_requirements
    ):
        missing.append("environment_requirements")
    if missing:
        raise ValidationError(
            "protocol cannot be frozen until it defines: " + ", ".join(missing)
        )
    require_sha256(protocol.analysis_code_hash, "analysis_code_hash")
    if protocol.random_seed_commitment:
        require_sha256(protocol.random_seed_commitment, "random_seed_commitment")


def validate_measurement_contract(protocol: ExperimentProtocol) -> None:
    definitions = protocol.measurement_definitions
    if any(not isinstance(item, MeasurementDefinition) for item in definitions):
        raise ValidationError(
            "measurement_definitions must contain MeasurementDefinition values"
        )
    identifiers: set[str] = set()
    observed_targets: list[tuple[MeasurementRole, str]] = []
    for index, definition in enumerate(definitions):
        prefix = f"measurement_definitions[{index}]"
        measurement_id = require_text(
            definition.measurement_id, f"{prefix}.measurement_id"
        )
        if measurement_id in identifiers:
            raise ValidationError(f"duplicate measurement_id: {measurement_id}")
        identifiers.add(measurement_id)
        if not isinstance(definition.role, MeasurementRole):
            raise ValidationError(f"{prefix}.role must be a MeasurementRole")
        target = require_text(
            definition.registered_target, f"{prefix}.registered_target"
        )
        for field_name in (
            "observable",
            "input_condition",
            "evaluation_point",
            "convention",
            "aggregation",
            "tolerance",
            "expected_behavior",
        ):
            require_text(getattr(definition, field_name), f"{prefix}.{field_name}")
        if (
            not isinstance(definition.parameter_values, dict)
            or not definition.parameter_values
        ):
            raise ValidationError(
                f"{prefix}.parameter_values must be a non-empty object"
            )
        for name, value in definition.parameter_values.items():
            require_text(name, f"{prefix}.parameter_values key")
            require_text(value, f"{prefix}.parameter_values[{name!r}]")
        observed_targets.append((definition.role, target))

    expected_targets = (
        [(MeasurementRole.PRIMARY, protocol.primary_outcome)]
        + [(MeasurementRole.SECONDARY, item) for item in protocol.secondary_outcomes]
        + [(MeasurementRole.CONTROL, item) for item in protocol.controls]
    )
    if sorted((role.value, target) for role, target in observed_targets) != sorted(
        (role.value, target) for role, target in expected_targets
    ):
        raise ValidationError(
            "measurement_definitions must define exactly one measurement for the "
            "primary outcome, every secondary outcome, and every registered control"
        )


def validate_quality_gates(
    gates: Sequence[QualityGateResult],
) -> list[QualityGateResult]:
    if isinstance(gates, (str, bytes)) or not isinstance(gates, Sequence):
        raise ValidationError("quality_gates must be a list")
    normalized: list[QualityGateResult] = []
    seen: set[str] = set()
    for gate in gates:
        if not isinstance(gate, QualityGateResult):
            raise ValidationError("quality_gates must contain QualityGateResult values")
        gate_id = require_text(gate.gate_id, "quality gate id")
        if gate_id in seen:
            raise ValidationError(f"duplicate quality gate id: {gate_id}")
        if not isinstance(gate.status, QualityGateStatus):
            raise ValidationError("quality gate status must be a QualityGateStatus")
        if not isinstance(gate.required, bool):
            raise ValidationError("quality gate required must be true or false")
        if not isinstance(gate.details, dict):
            raise ValidationError("quality gate details must be an object")
        seen.add(gate_id)
        normalized.append(
            QualityGateResult(
                gate_id=gate_id,
                status=gate.status,
                summary=require_text(gate.summary, "quality gate summary"),
                required=gate.required,
                details=dict(gate.details),
            )
        )
    return normalized


def validate_action_candidates(
    candidates: Sequence[ActionCandidate],
    known_hypotheses: set[str],
) -> list[ActionCandidate]:
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise ValidationError("candidates must be a list")
    if not candidates:
        raise ValidationError("at least one action candidate is required")
    normalized: list[ActionCandidate] = []
    seen: set[str] = set()
    score_fields = (
        "expected_discrimination",
        "uncertainty_reduction",
        "cost",
        "burden",
        "safety_risk",
        "ambiguity_risk",
    )
    for candidate in candidates:
        if not isinstance(candidate, ActionCandidate):
            raise ValidationError("candidates must contain ActionCandidate values")
        action_id = require_text(candidate.action_id, "action_id")
        if action_id in seen:
            raise ValidationError(f"duplicate action_id: {action_id}")
        hypotheses = require_text_list(
            candidate.distinguishes_hypotheses, "distinguishes_hypotheses"
        )
        information_targets = require_unique_text_list(
            candidate.information_targets, "information_targets"
        )
        if not hypotheses and not information_targets:
            raise ValidationError(
                f"action {action_id} must distinguish at least one hypothesis or "
                "name at least one information target"
            )
        if len(set(hypotheses)) != len(hypotheses):
            raise ValidationError(
                f"action {action_id} repeats a hypothesis distinction"
            )
        unknown = sorted(set(hypotheses) - known_hypotheses)
        if unknown:
            raise ValidationError(
                f"action {action_id} references unknown hypotheses: "
                + ", ".join(unknown)
            )
        for field_name in score_fields:
            value = getattr(candidate, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError(f"{field_name} must be a number from 0 to 1")
            if not 0 <= float(value) <= 1:
                raise ValidationError(f"{field_name} must be a number from 0 to 1")
        if not isinstance(candidate.prerequisites_met, bool):
            raise ValidationError("prerequisites_met must be true or false")
        if not isinstance(candidate.safety_approved, bool):
            raise ValidationError("safety_approved must be true or false")
        if not isinstance(candidate.metadata, dict):
            raise ValidationError("action metadata must be an object")
        depends_on = require_unique_text_list(candidate.depends_on, "depends_on")
        seen.add(action_id)
        normalized.append(
            ActionCandidate(
                action_id=action_id,
                title=require_text(candidate.title, "action title"),
                distinguishes_hypotheses=hypotheses,
                expected_discrimination=float(candidate.expected_discrimination),
                uncertainty_reduction=float(candidate.uncertainty_reduction),
                cost=float(candidate.cost),
                burden=float(candidate.burden),
                safety_risk=float(candidate.safety_risk),
                ambiguity_risk=float(candidate.ambiguity_risk),
                rationale=require_text(candidate.rationale, "action rationale"),
                prerequisites_met=candidate.prerequisites_met,
                safety_approved=candidate.safety_approved,
                lane_id=require_text(candidate.lane_id, "lane_id"),
                information_targets=information_targets,
                depends_on=depends_on,
                metadata=dict(candidate.metadata),
            )
        )
    return normalized


def validate_action_lanes(lanes: Sequence[ActionLane]) -> list[ActionLane]:
    if isinstance(lanes, (str, bytes)) or not isinstance(lanes, Sequence):
        raise ValidationError("lanes must be a list")
    if not lanes:
        raise ValidationError("at least one action lane is required")
    normalized: list[ActionLane] = []
    seen: set[str] = set()
    for lane in lanes:
        if not isinstance(lane, ActionLane):
            raise ValidationError("lanes must contain ActionLane values")
        lane_id = require_text(lane.lane_id, "lane_id")
        if lane_id in seen:
            raise ValidationError(f"duplicate lane_id: {lane_id}")
        status = require_text(lane.status, "lane status")
        if status not in {"active", "blocked"}:
            raise ValidationError("lane status must be active or blocked")
        blocked_on = require_unique_text_list(lane.blocked_on, "blocked_on")
        if status == "active" and blocked_on:
            raise ValidationError(f"active lane {lane_id} cannot declare blocked_on")
        if status == "blocked" and not blocked_on:
            raise ValidationError(f"blocked lane {lane_id} must declare blocked_on")
        seen.add(lane_id)
        normalized.append(
            ActionLane(
                lane_id=lane_id,
                title=require_text(lane.title, "lane title"),
                status=status,
                blocked_on=blocked_on,
            )
        )
    if not any(lane.status == "active" for lane in normalized):
        raise ValidationError("at least one action lane must be active")
    return normalized


def validate_portfolio_action_candidates(
    candidates: Sequence[ActionCandidate],
    known_hypotheses: set[str],
    lanes: Sequence[ActionLane],
    completed_action_ids: Sequence[str],
) -> tuple[list[ActionCandidate], list[str]]:
    normalized = validate_action_candidates(candidates, known_hypotheses)
    lane_ids = {lane.lane_id for lane in lanes}
    for candidate in normalized:
        if candidate.lane_id not in lane_ids:
            raise ValidationError(
                f"action {candidate.action_id} references unknown lane: "
                f"{candidate.lane_id}"
            )

    action_ids = {candidate.action_id for candidate in normalized}
    completed = require_unique_text_list(completed_action_ids, "completed_action_ids")
    unknown_completed = sorted(set(completed) - action_ids)
    if unknown_completed:
        raise ValidationError(
            "completed_action_ids reference unknown actions: "
            + ", ".join(unknown_completed)
        )
    for candidate in normalized:
        unknown_dependencies = sorted(set(candidate.depends_on) - action_ids)
        if unknown_dependencies:
            raise ValidationError(
                f"action {candidate.action_id} has unknown dependencies: "
                + ", ".join(unknown_dependencies)
            )
        if candidate.action_id in candidate.depends_on:
            raise ValidationError(
                f"action {candidate.action_id} cannot depend on itself"
            )

    dependencies = {
        candidate.action_id: set(candidate.depends_on) for candidate in normalized
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(action_id: str) -> None:
        if action_id in visiting:
            raise ValidationError("action dependency graph contains a cycle")
        if action_id in visited:
            return
        visiting.add(action_id)
        for dependency in dependencies[action_id]:
            visit(dependency)
        visiting.remove(action_id)
        visited.add(action_id)

    for action_id in sorted(dependencies):
        visit(action_id)
    return normalized, completed


def validate_selection_weights(weights: SelectionWeights) -> SelectionWeights:
    if not isinstance(weights, SelectionWeights):
        raise ValidationError("weights must be SelectionWeights")
    values: dict[str, float] = {}
    for field_name in (
        "expected_discrimination",
        "uncertainty_reduction",
        "cost",
        "burden",
        "safety_risk",
        "ambiguity_risk",
    ):
        value = getattr(weights, field_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValidationError(f"selection weight {field_name} must be non-negative")
        values[field_name] = float(value)
    return SelectionWeights(**values)


def validate_cross_lane_lesson(
    *,
    origin_lane_id: str,
    target_lane_ids: Sequence[str],
    origin_artifact_locator: str,
    origin_artifact_sha256: str,
    origin_integrity_status: str,
    observation: str,
    failure_class: str,
    strongest_alternative_explanation: str,
    challenged_invariant: str,
    first_permitted_future_versions: Sequence[str],
    prohibited_retroactive_targets: Sequence[str],
    proposed_repair: str,
    repair_falsifier: str,
    conclusion_ceiling: str,
) -> dict[str, object]:
    origin_lane = require_text(origin_lane_id, "origin_lane_id")
    target_lanes = require_unique_text_list(target_lane_ids, "target_lane_ids")
    if not target_lanes:
        raise ValidationError("target_lane_ids must name at least one target lane")
    if origin_lane in target_lanes:
        raise ValidationError("a cross-lane lesson must target a different lane")
    integrity_status = require_text(
        origin_integrity_status, "origin_integrity_status"
    )
    if integrity_status not in {"declared", "verified_elsewhere"}:
        raise ValidationError(
            "origin_integrity_status must be declared or verified_elsewhere"
        )
    failure = require_text(failure_class, "failure_class")
    if failure not in {
        "theory_failure",
        "machine_failure",
        "interface_ambiguity",
        "infrastructure_failure",
        "inconclusive",
    }:
        raise ValidationError("failure_class is not recognized")
    future_versions = require_unique_text_list(
        first_permitted_future_versions, "first_permitted_future_versions"
    )
    prohibited_targets = require_unique_text_list(
        prohibited_retroactive_targets, "prohibited_retroactive_targets"
    )
    if not future_versions:
        raise ValidationError(
            "first_permitted_future_versions must name at least one future version"
        )
    if not prohibited_targets:
        raise ValidationError(
            "prohibited_retroactive_targets must name at least one frozen or "
            "exposed target"
        )
    overlap = sorted(set(future_versions) & set(prohibited_targets))
    if overlap:
        raise ValidationError(
            "future versions cannot also be prohibited retroactive targets: "
            + ", ".join(overlap)
        )
    return {
        "origin_lane_id": origin_lane,
        "target_lane_ids": target_lanes,
        "origin_artifact_locator": require_text(
            origin_artifact_locator, "origin_artifact_locator"
        ),
        "origin_artifact_sha256": require_sha256(
            origin_artifact_sha256, "origin_artifact_sha256"
        ),
        "origin_integrity_status": integrity_status,
        "observation": require_text(observation, "observation"),
        "failure_class": failure,
        "strongest_alternative_explanation": require_text(
            strongest_alternative_explanation,
            "strongest_alternative_explanation",
        ),
        "challenged_invariant": require_text(
            challenged_invariant, "challenged_invariant"
        ),
        "first_permitted_future_versions": future_versions,
        "prohibited_retroactive_targets": prohibited_targets,
        "proposed_repair": require_text(proposed_repair, "proposed_repair"),
        "repair_falsifier": require_text(repair_falsifier, "repair_falsifier"),
        "conclusion_ceiling": require_text(
            conclusion_ceiling, "conclusion_ceiling"
        ),
    }
