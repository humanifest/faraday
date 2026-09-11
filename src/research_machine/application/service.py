from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
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
    RecordEthicsReviewEvent,
    RecordEvidenceStatusEvent,
    RecordEvidence,
    ExportSherlockEvidence,
    RecordRun,
    RegisterDataset,
    ReviewClaim,
    RetireHypothesis,
    SetInquiryDecision,
)
from research_machine.collaboration.redaction import (
    COLLABORATOR_CONTEXT_REDACTION_MARKER,
    OPERATIONAL_CONTEXT_KEYS,
)
from research_machine.application.artifact_integrity import verify_run_artifacts
from research_machine.application.policies import (
    declares_legacy_pre_registration_result_exposure,
    is_canonical_sha256,
    normalize_confidence,
    normalize_text,
    require_bounded_report_text,
    require_canonical_bounded_report_text,
    require_bounded_evidence_summary,
    require_canonical_text,
    require_pending_review_rationale,
    require_nonempty_unique_bounded_report_text_list,
    require_text,
    require_text_list,
    require_unique_canonical_text_list,
    require_unique_text_list,
    require_sha256,
    validate_action_candidates,
    adjudicate_conclusion_contract,
    validate_action_lanes,
    validate_control_witness_evidence,
    validate_cross_lane_lesson,
    validate_historical_cross_lane_lesson_structure,
    validate_dataset_artifacts,
    validate_evidence_annotations,
    validate_result_direction,
    validate_evidence_target,
    validate_hypothesis_activation,
    validate_hypothesis_pending_review_boundary,
    validate_hypothesis_retirement_boundary,
    validate_hypothesis_staging,
    validate_protocol_freeze,
    validate_portfolio_action_candidates,
    validate_quality_gates,
    validate_named_component_gate_metadata,
    validate_selection_weights,
    validate_validation_tag_context,
    typed_result_exposure_allows_evidence,
)
from research_machine.application.cross_lane_lesson_integrity import (
    cross_lane_lesson_payload_sha256,
    validate_cross_lane_lesson_payload_commitment,
)
from research_machine.application.protocol_integrity import (
    protocol_commitment,
)
from research_machine.application.rigor import audit_research_state
from research_machine.measurement.custody import validate_measurement_custody
from research_machine.measurement.instrument import (
    verify_instrument_inspection_record,
    verify_stream_timing_assessment_record,
    verify_temporal_order_assessment_record,
)
from research_machine.measurement.preprocessing import (
    verify_preprocessing_conformance_record,
)
from research_machine.domain.errors import ConflictError, NotFoundError, ValidationError
from research_machine.domain.models import (
    ActionRecommendation,
    AnalysisMode,
    Claim,
    CrossLaneLesson,
    ClaimDisposition,
    ClaimEpistemicLayer,
    ClaimLevel,
    CrossLaneTransferAuthorityStatus,
    DatasetArtifact,
    AnalysisContract,
    AnalysisStepContract,
    CalibrationCriterion,
    ConclusionContract,
    DatasetManifest,
    DatasetRole,
    EvidenceAssessment,
    EvidenceDirection,
    EvidenceRecord,
    EvidenceStatusEvent,
    EthicsReviewEvent,
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
from research_machine.replication.package import export_replication_package
from research_machine.selection import (
    rank_actions,
    rank_actions_by_lane,
    recommendation_payload_sha256,
    verify_recommendation_score_replay,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "inquiry"


def _hypothesis_alternatives(
    hypotheses: list[Hypothesis],
) -> dict[str, list[str]]:
    alternatives: dict[str, list[str]] = {}
    for hypothesis in hypotheses:
        values: list[str] = []
        if hypothesis.null_model.strip():
            values.append(hypothesis.null_model.strip())
        values.extend(item.strip() for item in hypothesis.competing_models if item.strip())
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value not in seen:
                seen.add(value)
                deduped.append(value)
        alternatives[hypothesis.hypothesis_id] = deduped
    return alternatives


def _validate_protocol_deviation_disclosure(value: Any) -> dict[str, Any]:
    """Validate an execution disclosure without judging its substantive impact."""
    if value is None:
        return {
            "status": "legacy_not_declared",
            "deviations": [],
            "automatic_evidence_eligible": False,
        }
    if not isinstance(value, dict) or set(value) != {"status", "deviations"}:
        raise ValidationError(
            "protocol_deviation_disclosure requires exactly status and deviations"
        )
    status = value["status"]
    if status not in {"no_deviations_declared", "deviations_declared"}:
        raise ValidationError("protocol deviation disclosure status is invalid")
    deviations = value["deviations"]
    if not isinstance(deviations, list):
        raise ValidationError("protocol deviation disclosure deviations must be an array")
    if (status == "no_deviations_declared") != (not deviations):
        raise ValidationError("protocol deviation disclosure status disagrees with deviations")
    required = {
        "deviation_id", "stage", "frozen_commitment", "actual_method", "reason",
        "timing", "potential_impact", "corrective_action", "evidence_sha256",
        "evidence_location",
    }
    allowed_timing = {
        "before_execution", "during_execution", "after_execution_before_results",
        "after_results_seen", "unknown",
    }
    allowed_impact = {"none", "minor", "potentially_material", "invalidating", "unknown"}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in deviations:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError("each protocol deviation must contain the exact documented fields")
        deviation_id = require_canonical_text(item["deviation_id"], "deviation_id")
        if deviation_id in seen:
            raise ValidationError(f"duplicate protocol deviation_id: {deviation_id}")
        seen.add(deviation_id)
        if item["timing"] not in allowed_timing:
            raise ValidationError(f"protocol deviation {deviation_id} timing is invalid")
        if item["potential_impact"] not in allowed_impact:
            raise ValidationError(f"protocol deviation {deviation_id} potential_impact is invalid")
        normalized.append({
            "deviation_id": deviation_id,
            "stage": require_canonical_bounded_report_text(item["stage"], "deviation stage"),
            "frozen_commitment": require_canonical_bounded_report_text(
                item["frozen_commitment"], "frozen commitment"
            ),
            "actual_method": require_canonical_bounded_report_text(
                item["actual_method"], "actual method"
            ),
            "reason": require_canonical_bounded_report_text(
                item["reason"], "deviation reason"
            ),
            "timing": item["timing"],
            "potential_impact": item["potential_impact"],
            "corrective_action": require_canonical_bounded_report_text(
                item["corrective_action"], "corrective action"
            ),
            "evidence_sha256": require_sha256(item["evidence_sha256"], "deviation evidence_sha256"),
            "evidence_location": require_canonical_text(
                item["evidence_location"], "deviation evidence_location"
            ),
        })
    return {
        "status": status,
        "deviations": normalized,
        "automatic_evidence_eligible": status == "no_deviations_declared",
        "interpretation_boundary": (
            "A no-deviation declaration is an unauthenticated execution assertion, not proof of adherence. "
            "Any declared departure requires separate scientific review and cannot automatically support evidence."
        ),
    }


def _validate_result_exposure_disclosure(value: Any) -> dict[str, Any]:
    """Normalize the declared pre-registration exposure to candidate output.

    The declaration is custody metadata, not proof of blinding.  Silence is
    retained for historical readability but cannot grant automatic evidence
    eligibility to a newly recorded run.
    """
    if value is None:
        return {
            "status": "legacy_not_declared",
            "exposures": [],
            "automatic_evidence_eligible": False,
        }
    if not isinstance(value, dict) or set(value) != {"status", "exposures"}:
        raise ValidationError(
            "result_exposure_disclosure requires exactly status and exposures"
        )
    status = value["status"]
    allowed_statuses = {
        "no_relevant_output_seen",
        "favorable_output_seen",
        "full_output_seen",
        "unknown",
    }
    if status not in allowed_statuses:
        raise ValidationError("result exposure disclosure status is invalid")
    exposures = value["exposures"]
    if not isinstance(exposures, list):
        raise ValidationError("result exposure disclosure exposures must be an array")
    required = {
        "exposure_id",
        "artifact_locator",
        "artifact_sha256",
        "seen_at",
        "description",
    }
    seen_ids: set[str] = set()
    normalized: list[dict[str, str]] = []
    for item in exposures:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError(
                "each result exposure must contain the exact documented fields"
            )
        exposure_id = require_canonical_text(item["exposure_id"], "exposure_id")
        if exposure_id in seen_ids:
            raise ValidationError(f"duplicate result exposure_id: {exposure_id}")
        seen_ids.add(exposure_id)
        seen_at = require_canonical_text(
            item["seen_at"], "result exposure seen_at"
        )
        _parse_aware_timestamp(seen_at, "result exposure seen_at")
        normalized.append({
            "exposure_id": exposure_id,
            "artifact_locator": require_canonical_text(
                item["artifact_locator"], "result exposure artifact_locator"
            ),
            "artifact_sha256": require_sha256(
                item["artifact_sha256"], "result exposure artifact_sha256"
            ),
            "seen_at": seen_at,
            "description": require_canonical_bounded_report_text(
                item["description"], "result exposure description"
            ),
        })
    if status == "no_relevant_output_seen" and normalized:
        raise ValidationError(
            "no_relevant_output_seen result exposure disclosure requires no exposures"
        )
    if status in {"favorable_output_seen", "full_output_seen"} and not normalized:
        raise ValidationError(
            f"{status} result exposure disclosure requires at least one exposure"
        )
    return {
        "status": status,
        "exposures": normalized,
        "automatic_evidence_eligible": status == "no_relevant_output_seen",
        "interpretation_boundary": (
            "This is an unauthenticated exposure assertion, not proof of blinding. "
            "Favorable, full, or unknown pre-registration exposure blocks automatic "
            "scientific-evidence eligibility while preserving the run."
        ),
    }


def _sha256_json(value: dict[str, Any]) -> str:
    content = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _resolve_json_pointer(value: Any, pointer: str, field_name: str) -> Any:
    pointer = require_text(pointer, field_name)
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValidationError(f"{field_name} must be an absolute JSON Pointer")
    current = value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValidationError(f"{field_name} does not resolve in the verified analysis result")
    return current


def _strict_json_artifact(path: Path, field_name: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_bytes(),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"{field_name} cites invalid JSON evidence: {exc}") from exc


def _verify_json_artifact_location(
    outputs: list[DatasetArtifact],
    artifact_root: str | None,
    digest: str,
    location: str,
    field_name: str,
) -> bool:
    """Resolve a location when its already hash-verified artifact is JSON."""
    return _resolve_json_artifact_location(
        outputs, artifact_root, digest, location, field_name
    )[0]


def _resolve_json_artifact_location(
    outputs: list[DatasetArtifact],
    artifact_root: str | None,
    digest: str,
    location: str,
    field_name: str,
) -> tuple[bool, Any]:
    """Return the selected JSON value when a verified artifact is machine-readable."""
    if artifact_root is None:
        return False, None
    artifact = next((item for item in outputs if item.sha256 == digest), None)
    if artifact is None:
        return False, None
    is_json = (
        artifact.media_type.lower().split(";", 1)[0].strip() == "application/json"
        or Path(artifact.locator).suffix.lower() == ".json"
    )
    if not is_json:
        return False, None
    selected = _resolve_json_pointer(
        _strict_json_artifact(Path(artifact_root) / artifact.locator, field_name),
        location,
        field_name,
    )
    return True, selected


_STRUCTURED_RESULT_DETAIL_KEYS = {
    "canary_target_assessment",
    "causal_assumption_results",
    "instrument_inspection",
    "measurement_validity_results",
    "named_component_results",
    "missingness_assessment_result",
    "preprocessing_conformance",
    "stream_timing_assessment",
    "temporal_order_assessment",
}


def _contains_template_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped == "" or (stripped.startswith("<") and stripped.endswith(">"))
    if isinstance(value, dict):
        return any(_contains_template_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_template_placeholder(item) for item in value)
    return False


def _contains_canonical_sha256(value: Any) -> bool:
    if is_canonical_sha256(value):
        return True
    if isinstance(value, dict):
        return any(_contains_canonical_sha256(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_canonical_sha256(item) for item in value)
    return False


def _reject_skipped_gate_structured_results(gate: QualityGateResult) -> None:
    if gate.status is not QualityGateStatus.SKIPPED:
        return
    if is_canonical_sha256(gate.details.get("evidence_sha256")):
        raise ValidationError(
            f"skipped quality gate {gate.gate_id} cannot cite evidence_sha256"
        )
    retained = sorted(
        key
        for key in _STRUCTURED_RESULT_DETAIL_KEYS.intersection(gate.details)
        if _contains_canonical_sha256(gate.details[key])
        or not _contains_template_placeholder(gate.details[key])
    )
    if retained:
        raise ValidationError(
            f"skipped quality gate {gate.gate_id} cannot report structured results: "
            + ", ".join(retained)
        )


def _validate_canary_target_assessment_gate(
    *,
    protocol: ExperimentProtocol,
    gate: QualityGateResult,
    outputs: list[DatasetArtifact],
    artifact_root: str | None,
    verified_gate_result: Any,
    verified_gate_output_sha256: str | None,
) -> None:
    assessment = gate.details.get("canary_target_assessment")
    if assessment is None:
        return
    plan = protocol.canary_target_plan
    if plan is None:
        raise ValidationError(
            f"quality gate {gate.gate_id} has canary_target_assessment but the protocol has no canary_target_plan"
        )
    if gate.gate_id != plan.assessment_gate_id:
        raise ValidationError(
            "canary_target_assessment must be recorded on the frozen canary assessment gate"
        )
    required_fields = {
        "plan_id",
        "assignment_artifact_sha256",
        "revealed_target_id",
        "comparator_target_ids",
        "assessment_status",
        "observed_pattern",
        "interpretation",
        "evidence_sha256",
        "evidence_location",
    }
    derived_fields = {"selected_value_sha256"}
    if (
        not isinstance(assessment, dict)
        or not required_fields <= set(assessment)
        or set(assessment) - required_fields - derived_fields
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} canary_target_assessment must contain at least: "
            + ", ".join(sorted(required_fields))
        )
    prefix = f"quality gate {gate.gate_id} canary_target_assessment"
    if require_canonical_text(assessment["plan_id"], f"{prefix}.plan_id") != plan.plan_id:
        raise ValidationError("canary assessment plan_id does not match the frozen plan")
    if (
        require_sha256(
            assessment["assignment_artifact_sha256"],
            f"{prefix}.assignment_artifact_sha256",
        )
        != plan.assignment_artifact_sha256
    ):
        raise ValidationError(
            "canary assessment assignment_artifact_sha256 does not match the frozen plan"
        )
    candidates = set(plan.candidate_target_ids)
    revealed_target_id = require_canonical_text(
        assessment["revealed_target_id"], f"{prefix}.revealed_target_id"
    )
    if revealed_target_id not in candidates:
        raise ValidationError(
            "canary assessment revealed_target_id is not in the frozen candidate set"
        )
    comparators = require_unique_canonical_text_list(
        assessment["comparator_target_ids"],
        f"{prefix}.comparator_target_ids",
    )
    if not comparators:
        raise ValidationError("canary assessment requires comparator_target_ids")
    if revealed_target_id in comparators:
        raise ValidationError(
            "canary assessment comparator_target_ids cannot include the revealed target"
        )
    unknown = sorted(set(comparators) - candidates)
    if unknown:
        raise ValidationError(
            "canary assessment comparator_target_ids are not in the frozen candidate set: "
            + ", ".join(unknown)
        )
    assessment_status = require_canonical_text(
        assessment["assessment_status"], f"{prefix}.assessment_status"
    )
    if assessment_status not in {
        "consistent_with_revealed_target",
        "follows_comparator_or_decoy",
        "follows_no_target",
        "mixed",
        "inconclusive",
    }:
        raise ValidationError("canary assessment_status is unsupported")
    if (
        gate.status is QualityGateStatus.PASSED
        and assessment_status != "consistent_with_revealed_target"
    ):
        raise ValidationError(
            "passed canary assessment gate requires consistent_with_revealed_target"
        )
    if (
        gate.status is QualityGateStatus.WARNING
        and assessment_status not in {"mixed", "inconclusive"}
    ):
        raise ValidationError(
            "warning canary assessment gate requires mixed or inconclusive status"
        )
    if (
        gate.status is QualityGateStatus.FAILED
        and assessment_status
        not in {"follows_comparator_or_decoy", "follows_no_target"}
    ):
        raise ValidationError(
            "failed canary assessment gate requires comparator, decoy, or no-target status"
        )
    require_canonical_bounded_report_text(
        assessment["observed_pattern"], f"{prefix}.observed_pattern"
    )
    require_canonical_bounded_report_text(
        assessment["interpretation"], f"{prefix}.interpretation"
    )
    evidence_sha256 = require_sha256(
        assessment["evidence_sha256"], f"{prefix}.evidence_sha256"
    )
    if evidence_sha256 not in {artifact.sha256 for artifact in outputs}:
        raise ValidationError(
            "canary assessment evidence must reference a run output artifact"
        )
    location = require_canonical_text(
        assessment["evidence_location"], f"{prefix}.evidence_location"
    )
    location_verified, selected_value = _resolve_json_artifact_location(
        outputs,
        artifact_root,
        evidence_sha256,
        location,
        f"{prefix}.evidence_location",
    )
    if location_verified:
        selected_value_sha256 = _result_selection_sha256(selected_value)
        supplied = assessment.get("selected_value_sha256")
        if supplied is not None and require_sha256(
            supplied, f"{prefix}.selected_value_sha256"
        ) != selected_value_sha256:
            raise ValidationError(
                "canary assessment selected_value_sha256 does not match the verified JSON value"
            )
        assessment["selected_value_sha256"] = selected_value_sha256
    if (
        not location_verified
        and verified_gate_result is not None
        and evidence_sha256 == verified_gate_output_sha256
    ):
        if not location.startswith("/"):
            raise ValidationError(
                "canary assessment evidence in the verified analysis output "
                "requires an absolute JSON Pointer evidence_location"
            )
        selected_value = _resolve_json_pointer(
            verified_gate_result, location, f"{prefix}.evidence_location"
        )
        selected_value_sha256 = _result_selection_sha256(selected_value)
        supplied = assessment.get("selected_value_sha256")
        if supplied is not None and require_sha256(
            supplied, f"{prefix}.selected_value_sha256"
        ) != selected_value_sha256:
            raise ValidationError(
                "canary assessment selected_value_sha256 does not match the verified analysis result value"
            )
        assessment["selected_value_sha256"] = selected_value_sha256


def _validate_preprocessing_conformance_gate(
    *,
    protocol: ExperimentProtocol,
    gate: QualityGateResult,
    outputs: list[DatasetArtifact],
    artifact_root: str | None,
    artifact_integrity: Any,
) -> None:
    conformance = gate.details.get("preprocessing_conformance")
    if conformance is None:
        return
    if not isinstance(conformance, dict):
        raise ValidationError(
            f"quality gate {gate.gate_id} preprocessing_conformance must be an object"
        )
    required_fields = {
        "locator",
        "sha256",
        "status",
        "registered_pipeline_sha256",
        "observed_pipeline_sha256",
    }
    if set(conformance) != required_fields:
        raise ValidationError(
            f"quality gate {gate.gate_id} preprocessing_conformance must contain exactly: "
            + ", ".join(sorted(required_fields))
        )
    prefix = f"quality gate {gate.gate_id} preprocessing_conformance"
    locator = require_canonical_text(conformance["locator"], f"{prefix}.locator")
    record_sha256 = require_sha256(conformance["sha256"], f"{prefix}.sha256")
    declared_status = require_canonical_text(conformance["status"], f"{prefix}.status")
    allowed_statuses = {
        "preprocessing_conformance_passed",
        "preprocessing_conformance_failed",
    }
    if declared_status not in allowed_statuses:
        raise ValidationError(f"{prefix}.status is unsupported")
    evidence_sha256 = require_sha256(
        gate.details.get("evidence_sha256"),
        f"quality gate {gate.gate_id} evidence_sha256",
    )
    if evidence_sha256 != record_sha256:
        raise ValidationError(
            f"quality gate {gate.gate_id} evidence_sha256 must match preprocessing_conformance.sha256"
        )
    if not any(
        artifact.locator == locator
        and artifact.sha256 == record_sha256
        for artifact in outputs
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} preprocessing_conformance must reference a declared run output artifact"
        )
    if artifact_root is None:
        raise ValidationError(
            f"quality gate {gate.gate_id} preprocessing_conformance requires artifact_root"
        )
    if (
        artifact_integrity is None
        or artifact_integrity.status != "passed"
        or artifact_integrity.all_artifacts_match is not True
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} preprocessing_conformance requires passed artifact_integrity"
        )
    verified = verify_preprocessing_conformance_record(
        Path(artifact_root) / locator,
        record_sha256,
        expected_registered_pipeline_sha256=require_sha256(
            conformance["registered_pipeline_sha256"],
            f"{prefix}.registered_pipeline_sha256",
        ),
        expected_observed_pipeline_sha256=require_sha256(
            conformance["observed_pipeline_sha256"],
            f"{prefix}.observed_pipeline_sha256",
        ),
    )
    if (
        is_canonical_sha256(protocol.preprocessing_pipeline)
        and verified["registered_pipeline_sha256"] != protocol.preprocessing_pipeline
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} preprocessing_conformance registered pipeline "
            "does not match frozen protocol preprocessing_pipeline"
        )
    if declared_status != verified["record_status"]:
        raise ValidationError(
            f"quality gate {gate.gate_id} preprocessing_conformance status does not match the verified record"
        )
    if gate.status is QualityGateStatus.PASSED:
        if verified["record_status"] != "preprocessing_conformance_passed":
            raise ValidationError(
                f"passed quality gate {gate.gate_id} requires a passed preprocessing conformance record"
            )
    elif gate.status is QualityGateStatus.FAILED:
        if verified["record_status"] != "preprocessing_conformance_failed":
            raise ValidationError(
                f"failed quality gate {gate.gate_id} requires a failed preprocessing conformance record"
            )
    else:
        raise ValidationError(
            f"quality gate {gate.gate_id} preprocessing_conformance must be passed or failed according to the record"
        )


def _validate_temporal_order_assessment_gate(
    *,
    gate: QualityGateResult,
    outputs: list[DatasetArtifact],
    artifact_root: str | None,
    artifact_integrity: Any,
) -> None:
    assessment = gate.details.get("temporal_order_assessment")
    if assessment is None:
        return
    if not isinstance(assessment, dict):
        raise ValidationError(
            f"quality gate {gate.gate_id} temporal_order_assessment must be an object"
        )
    required_fields = {
        "locator",
        "sha256",
        "status",
        "timing_assessment_sha256",
        "specification_sha256",
    }
    derived_fields = {
        "check_count",
        "failed_check_count",
        "warning_check_count",
        "finding_count",
    }
    allowed_fields = required_fields | derived_fields
    if set(assessment) - allowed_fields or not required_fields <= set(assessment):
        raise ValidationError(
            f"quality gate {gate.gate_id} temporal_order_assessment must contain at least: "
            + ", ".join(sorted(required_fields))
        )
    prefix = f"quality gate {gate.gate_id} temporal_order_assessment"
    locator = require_canonical_text(assessment["locator"], f"{prefix}.locator")
    record_sha256 = require_sha256(assessment["sha256"], f"{prefix}.sha256")
    declared_status = require_canonical_text(assessment["status"], f"{prefix}.status")
    allowed_statuses = {"temporal_order_passed", "temporal_order_failed"}
    if declared_status not in allowed_statuses:
        raise ValidationError(f"{prefix}.status is unsupported")
    evidence_sha256 = require_sha256(
        gate.details.get("evidence_sha256"),
        f"quality gate {gate.gate_id} evidence_sha256",
    )
    if evidence_sha256 != record_sha256:
        raise ValidationError(
            f"quality gate {gate.gate_id} evidence_sha256 must match temporal_order_assessment.sha256"
        )
    if not any(
        artifact.locator == locator
        and artifact.sha256 == record_sha256
        for artifact in outputs
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} temporal_order_assessment must reference a declared run output artifact"
        )
    if artifact_root is None:
        raise ValidationError(
            f"quality gate {gate.gate_id} temporal_order_assessment requires artifact_root"
        )
    if (
        artifact_integrity is None
        or artifact_integrity.status != "passed"
        or artifact_integrity.all_artifacts_match is not True
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} temporal_order_assessment requires passed artifact_integrity"
        )
    verified = verify_temporal_order_assessment_record(
        Path(artifact_root) / locator,
        record_sha256,
        expected_timing_assessment_sha256=require_sha256(
            assessment["timing_assessment_sha256"],
            f"{prefix}.timing_assessment_sha256",
        ),
        expected_specification_sha256=require_sha256(
            assessment["specification_sha256"],
            f"{prefix}.specification_sha256",
        ),
    )
    if declared_status != verified["record_status"]:
        raise ValidationError(
            f"quality gate {gate.gate_id} temporal_order_assessment status does not match the verified record"
        )
    for field in derived_fields:
        expected = verified[field]
        supplied = assessment.get(field)
        if supplied is not None and supplied != expected:
            raise ValidationError(
                f"quality gate {gate.gate_id} temporal_order_assessment {field} "
                "does not match the verified record"
            )
        assessment[field] = expected
    if gate.status is QualityGateStatus.PASSED:
        if verified["record_status"] != "temporal_order_passed":
            raise ValidationError(
                f"passed quality gate {gate.gate_id} requires a passed temporal-order assessment"
            )
    elif gate.status is QualityGateStatus.FAILED:
        if verified["record_status"] != "temporal_order_failed":
            raise ValidationError(
                f"failed quality gate {gate.gate_id} requires a failed temporal-order assessment"
            )
    else:
        raise ValidationError(
            f"quality gate {gate.gate_id} temporal_order_assessment must be passed or failed according to the record"
        )


def _validate_instrument_inspection_gate(
    *,
    gate: QualityGateResult,
    outputs: list[DatasetArtifact],
    artifact_root: str | None,
    artifact_integrity: Any,
) -> None:
    inspection = gate.details.get("instrument_inspection")
    if inspection is None:
        return
    if not isinstance(inspection, dict):
        raise ValidationError(
            f"quality gate {gate.gate_id} instrument_inspection must be an object"
        )
    required_fields = {
        "locator",
        "sha256",
        "status",
        "source_sha256",
        "config_sha256",
        "implementation_sha256",
    }
    derived_fields = {
        "stream_count",
        "temporal_metadata_status",
    }
    allowed_fields = required_fields | derived_fields
    if set(inspection) - allowed_fields or not required_fields <= set(inspection):
        raise ValidationError(
            f"quality gate {gate.gate_id} instrument_inspection must contain at least: "
            + ", ".join(sorted(required_fields))
        )
    prefix = f"quality gate {gate.gate_id} instrument_inspection"
    locator = require_canonical_text(inspection["locator"], f"{prefix}.locator")
    record_sha256 = require_sha256(inspection["sha256"], f"{prefix}.sha256")
    declared_status = require_canonical_text(inspection["status"], f"{prefix}.status")
    if declared_status != "inspection_recorded":
        raise ValidationError(f"{prefix}.status is unsupported")
    evidence_sha256 = require_sha256(
        gate.details.get("evidence_sha256"),
        f"quality gate {gate.gate_id} evidence_sha256",
    )
    if evidence_sha256 != record_sha256:
        raise ValidationError(
            f"quality gate {gate.gate_id} evidence_sha256 must match instrument_inspection.sha256"
        )
    if not any(
        artifact.locator == locator
        and artifact.sha256 == record_sha256
        for artifact in outputs
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} instrument_inspection must reference a declared run output artifact"
        )
    if artifact_root is None:
        raise ValidationError(
            f"quality gate {gate.gate_id} instrument_inspection requires artifact_root"
        )
    if (
        artifact_integrity is None
        or artifact_integrity.status != "passed"
        or artifact_integrity.all_artifacts_match is not True
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} instrument_inspection requires passed artifact_integrity"
        )
    verified = verify_instrument_inspection_record(
        Path(artifact_root) / locator,
        record_sha256,
        expected_source_sha256=require_sha256(
            inspection["source_sha256"],
            f"{prefix}.source_sha256",
        ),
        expected_config_sha256=require_sha256(
            inspection["config_sha256"],
            f"{prefix}.config_sha256",
        ),
        expected_implementation_sha256=require_sha256(
            inspection["implementation_sha256"],
            f"{prefix}.implementation_sha256",
        ),
    )
    if declared_status != verified["record_status"]:
        raise ValidationError(
            f"quality gate {gate.gate_id} instrument_inspection status does not match the verified record"
        )
    for field in derived_fields:
        expected = verified[field]
        supplied = inspection.get(field)
        if supplied is not None and supplied != expected:
            raise ValidationError(
                f"quality gate {gate.gate_id} instrument_inspection {field} "
                "does not match the verified record"
            )
        inspection[field] = expected
    if gate.status is not QualityGateStatus.PASSED:
        raise ValidationError(
            f"quality gate {gate.gate_id} instrument_inspection can only record a passed retention gate"
        )


def _validate_stream_timing_assessment_gate(
    *,
    gate: QualityGateResult,
    outputs: list[DatasetArtifact],
    artifact_root: str | None,
    artifact_integrity: Any,
) -> None:
    assessment = gate.details.get("stream_timing_assessment")
    if assessment is None:
        return
    if not isinstance(assessment, dict):
        raise ValidationError(
            f"quality gate {gate.gate_id} stream_timing_assessment must be an object"
        )
    required_fields = {
        "locator",
        "sha256",
        "status",
        "inspection_sha256",
        "specification_sha256",
    }
    derived_fields = {
        "required_stream_count",
        "required_stream_failure_count",
        "event_count",
        "event_failure_count",
        "finding_count",
    }
    allowed_fields = required_fields | derived_fields
    if set(assessment) - allowed_fields or not required_fields <= set(assessment):
        raise ValidationError(
            f"quality gate {gate.gate_id} stream_timing_assessment must contain at least: "
            + ", ".join(sorted(required_fields))
        )
    prefix = f"quality gate {gate.gate_id} stream_timing_assessment"
    locator = require_canonical_text(assessment["locator"], f"{prefix}.locator")
    record_sha256 = require_sha256(assessment["sha256"], f"{prefix}.sha256")
    declared_status = require_canonical_text(assessment["status"], f"{prefix}.status")
    allowed_statuses = {"timing_feasibility_passed", "timing_feasibility_failed"}
    if declared_status not in allowed_statuses:
        raise ValidationError(f"{prefix}.status is unsupported")
    evidence_sha256 = require_sha256(
        gate.details.get("evidence_sha256"),
        f"quality gate {gate.gate_id} evidence_sha256",
    )
    if evidence_sha256 != record_sha256:
        raise ValidationError(
            f"quality gate {gate.gate_id} evidence_sha256 must match stream_timing_assessment.sha256"
        )
    if not any(
        artifact.locator == locator
        and artifact.sha256 == record_sha256
        for artifact in outputs
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} stream_timing_assessment must reference a declared run output artifact"
        )
    if artifact_root is None:
        raise ValidationError(
            f"quality gate {gate.gate_id} stream_timing_assessment requires artifact_root"
        )
    if (
        artifact_integrity is None
        or artifact_integrity.status != "passed"
        or artifact_integrity.all_artifacts_match is not True
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} stream_timing_assessment requires passed artifact_integrity"
        )
    verified = verify_stream_timing_assessment_record(
        Path(artifact_root) / locator,
        record_sha256,
        expected_inspection_sha256=require_sha256(
            assessment["inspection_sha256"],
            f"{prefix}.inspection_sha256",
        ),
        expected_specification_sha256=require_sha256(
            assessment["specification_sha256"],
            f"{prefix}.specification_sha256",
        ),
    )
    if declared_status != verified["record_status"]:
        raise ValidationError(
            f"quality gate {gate.gate_id} stream_timing_assessment status does not match the verified record"
        )
    for field in derived_fields:
        expected = verified[field]
        supplied = assessment.get(field)
        if supplied is not None and supplied != expected:
            raise ValidationError(
                f"quality gate {gate.gate_id} stream_timing_assessment {field} "
                "does not match the verified record"
            )
        assessment[field] = expected
    if gate.status is QualityGateStatus.PASSED:
        if verified["record_status"] != "timing_feasibility_passed":
            raise ValidationError(
                f"passed quality gate {gate.gate_id} requires a passed stream-timing assessment"
            )
    elif gate.status is QualityGateStatus.FAILED:
        if verified["record_status"] != "timing_feasibility_failed":
            raise ValidationError(
                f"failed quality gate {gate.gate_id} requires a failed stream-timing assessment"
            )
    else:
        raise ValidationError(
            f"quality gate {gate.gate_id} stream_timing_assessment must be passed or failed according to the record"
        )


def _canonical_result_value(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError("selected analysis result is not finite canonical JSON") from exc


def _result_selection_sha256(value: Any) -> str:
    try:
        content = (json.dumps(
            value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
        ) + "\n").encode()
    except (TypeError, ValueError) as exc:
        raise ValidationError("selected analysis result is not finite JSON") from exc
    return hashlib.sha256(content).hexdigest()


def _protocol_commitment(protocol: ExperimentProtocol) -> str:
    return protocol_commitment(protocol)


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
        ethics_events = self._validated_ethics_review_events(resolved)
        datasets = self.repository.list_datasets(resolved)
        protocols = self.repository.list_protocols(resolved)
        runs = self.repository.list_runs(resolved)
        evidence = self.repository.list_evidence(resolved)
        hypotheses = self.repository.list_hypotheses(resolved)
        claims = self.repository.load_claims(resolved)
        from research_machine.application.claim_integrity import (
            validate_claim_dependency_levels,
            validate_claim_scientific_commitment,
        )
        claims_by_id = {claim.claim_id: claim for claim in claims}
        for claim in claims:
            validate_claim_scientific_commitment(claim)
            validate_claim_dependency_levels(claim, claims_by_id)
        from research_machine.application.hypothesis_integrity import (
            validate_hypothesis_scientific_commitment,
        )
        for hypothesis in hypotheses:
            validate_hypothesis_scientific_commitment(hypothesis)
            validate_hypothesis_pending_review_boundary(hypothesis)
            validate_hypothesis_retirement_boundary(hypothesis)
        protocols_by_id = {item.protocol_id: item for item in protocols}
        datasets_by_id = {item.dataset_id: item for item in datasets}
        hypotheses_by_id = {item.hypothesis_id: item for item in hypotheses}
        from research_machine.application.hypothesis_integrity import (
            validate_protocol_hypothesis_commitments,
        )
        for protocol in protocols:
            if protocol.status is ProtocolStatus.FROZEN:
                if not protocol.protocol_hash:
                    raise ValidationError(
                        f"frozen protocol {protocol.protocol_id} no longer matches its commitment"
                    )
                if protocol.hypothesis_commitments:
                    if _protocol_commitment(protocol) != protocol.protocol_hash:
                        raise ValidationError(
                            f"frozen protocol {protocol.protocol_id} no longer matches its commitment"
                        )
                    validate_protocol_hypothesis_commitments(
                        protocol, hypotheses_by_id
                    )
                else:
                    self.repository.verify_legacy_protocol_integrity(
                        resolved, protocol
                    )
        from research_machine.application.ethics import (
            reverify_ethics_condition_discharge,
        )
        from research_machine.application.dataset_integrity import (
            validate_protected_dataset_lineage_closure,
        )
        for dataset in datasets:
            from research_machine.application.dataset_integrity import (
                validate_dataset_payload_commitment,
            )
            validate_dataset_payload_commitment(dataset)
            validate_protected_dataset_lineage_closure(dataset, datasets_by_id)
            if (
                dataset.role in {DatasetRole.CONFIRMATORY, DatasetRole.REPLICATION}
                and not dataset.synthetic
            ):
                from research_machine.application.dataset_integrity import (
                    reverify_dataset_artifacts,
                )
            protocol = protocols_by_id.get(dataset.protocol_id or "")
            if (
                dataset.role in {DatasetRole.CONFIRMATORY, DatasetRole.REPLICATION}
                and not dataset.synthetic
            ):
                if protocol is None:
                    raise ValidationError(
                        f"verified dataset {dataset.dataset_id} references an unknown protocol"
                    )
                reverify_dataset_artifacts(dataset, protocol)
            if "ethics_condition_verification" in dataset.metadata and protocol is None:
                raise ValidationError(
                    f"condition-verified dataset {dataset.dataset_id} references an unknown protocol"
                )
            if "ethics_condition_verification" in dataset.metadata:
                assert protocol is not None
                reverify_ethics_condition_discharge(protocol, dataset)
            if protocol is not None and protocol.measurement_custody_requirements:
                from research_machine.measurement.custody import (
                    reverify_dataset_measurement_custody,
                )
                reverify_dataset_measurement_custody(protocol, dataset)
        from research_machine.application.run_integrity import (
            reverify_run_artifacts,
            validate_run_payload_commitment,
        )
        for run in runs:
            validate_run_payload_commitment(run)
            protocol = protocols_by_id.get(run.protocol_id)
            legacy_protocol = (
                protocol is not None and not protocol.hypothesis_commitments
            )
            artifact_integrity_replayed = False
            if "artifact_integrity" in run.metadata and not legacy_protocol:
                reverify_run_artifacts(run)
                artifact_integrity_replayed = True
            if not run.scientific_evidence_eligible:
                continue
            if (
                protocol is None
                or run.protocol_hash != protocol.protocol_hash
            ):
                raise ValidationError(
                    f"evidence-eligible run {run.run_id} no longer matches its frozen protocol"
                )
            if not protocol.hypothesis_commitments:
                self.repository.verify_legacy_protocol_integrity(
                    resolved, protocol
                )
                # The historical run remains ledger-bound and visible, but the
                # missing prospective hypothesis commitment is never inferred.
                continue
            if _protocol_commitment(protocol) != protocol.protocol_hash:
                raise ValidationError(
                    f"evidence-eligible run {run.run_id} no longer matches its frozen protocol"
                )
            run_datasets = [
                self.repository.find_dataset(resolved, dataset_id)
                for dataset_id in run.dataset_ids
            ]
            self._validate_run_datasets(protocol, run_datasets, all_datasets=datasets)
            if not artifact_integrity_replayed:
                reverify_run_artifacts(run)
        from research_machine.application.evidence_admission import (
            validate_evidence_admission_receipts,
        )
        current_evidence = [item for item in evidence if item.admission_checks]
        validate_evidence_admission_receipts(
            current_evidence, claims, runs, protocols, datasets, ethics_events
        )
        for record in evidence:
            if not record.admission_checks:
                self.repository.verify_legacy_evidence_integrity(
                    resolved, record
                )
        return {
            "inquiry": self.repository.load_inquiry(resolved).to_dict(),
            "questions": [
                item.to_dict() for item in self.repository.load_questions(resolved)
            ],
            "claims": [
                item.to_dict() for item in claims
            ],
            "hypotheses": [
                item.to_dict() for item in hypotheses
            ],
            "evidence": [
                item.to_dict() for item in evidence
            ],
            "evidence_status_events": [
                item.to_dict()
                for item in self.list_evidence_status_events(resolved)
            ],
            "datasets": [
                item.to_dict() for item in datasets
            ],
            "protocols": [
                item.to_dict() for item in protocols
            ],
            "runs": [item.to_dict() for item in runs],
            "recommendations": [
                item.to_dict()
                for item in self._verified_recommendations(resolved)
            ],
            "cross_lane_lessons": [
                item.to_dict()
                for item in self._verified_cross_lane_lessons(resolved)
            ],
            "ethics_review_events": [
                item.to_dict()
                for item in ethics_events
            ],
        }

    def _validated_ethics_review_events(
        self, inquiry_id: str
    ) -> list[EthicsReviewEvent]:
        events = self.repository.list_ethics_review_events(inquiry_id)
        for event in events:
            for field, value in (
                ("event_id", event.event_id),
                ("protocol_id", event.protocol_id),
            ):
                text = require_text(value, f"ethics review event {field}")
                if text != value:
                    raise ValidationError(
                        f"ethics review event {field} must be canonical without surrounding whitespace"
                    )
            if event.supersedes_event_id is not None:
                supersedes = require_text(
                    event.supersedes_event_id,
                    "ethics review event supersedes_event_id",
                )
                if supersedes != event.supersedes_event_id:
                    raise ValidationError(
                        "ethics review event supersedes_event_id must be canonical without surrounding whitespace"
                    )
        protocols = {
            item.protocol_id: item
            for item in self.repository.list_protocols(inquiry_id)
        }
        unknown = sorted({item.protocol_id for item in events} - set(protocols))
        if unknown:
            raise ValidationError(
                "ethics review events reference unknown protocols: " + ", ".join(unknown)
            )
        from research_machine.application.ethics import (
            validate_ethics_review_event_chain,
            validate_original_review_artifact,
        )
        validated: list[EthicsReviewEvent] = []
        for protocol in protocols.values():
            if protocol.human_subjects and protocol.status is ProtocolStatus.FROZEN:
                validate_original_review_artifact(protocol)
        for protocol_id in sorted({item.protocol_id for item in events}):
            validated.extend(validate_ethics_review_event_chain(
                protocols[protocol_id],
                [item for item in events if item.protocol_id == protocol_id],
            ))
        return validated

    def collaborator_context(
        self, inquiry_id: str | None = None, *, purpose: str = ""
    ) -> dict[str, Any]:
        """Read-only context for a UI or optional local/remote model adapter."""
        def redact_operational_context(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: (
                        COLLABORATOR_CONTEXT_REDACTION_MARKER
                        if key in OPERATIONAL_CONTEXT_KEYS and item
                        else redact_operational_context(item)
                    )
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [redact_operational_context(item) for item in value]
            return value

        purpose_text = require_text(purpose, "purpose")
        if purpose_text != purpose:
            raise ValidationError(
                "purpose must be canonical without surrounding whitespace"
            )
        state = self.show_inquiry(inquiry_id)
        redacted_state = redact_operational_context(state)
        open_questions = [
            question
            for question in redacted_state["questions"]
            if question["status"] == QuestionStatus.OPEN.value
        ]
        context_reference_index = [
            {
                "ref": f"inquiry:{redacted_state['inquiry']['inquiry_id']}",
                "kind": "inquiry",
            },
            *[
                {"ref": f"question:{item['question_id']}", "kind": "open_question"}
                for item in open_questions
            ],
            *[
                {"ref": f"claim:{item['claim_id']}", "kind": "claim"}
                for item in redacted_state["claims"]
            ],
            *[
                {"ref": f"hypothesis:{item['hypothesis_id']}", "kind": "active_hypothesis"}
                for item in redacted_state["hypotheses"]
                if item["workflow_state"] == HypothesisWorkflowState.ACTIVE.value
            ],
            *[
                {"ref": f"hypothesis:{item['hypothesis_id']}", "kind": "pending_hypothesis"}
                for item in redacted_state["hypotheses"]
                if item["workflow_state"] == HypothesisWorkflowState.PENDING_REVIEW.value
            ],
            *[
                {"ref": f"evidence:{item['evidence_id']}", "kind": "evidence"}
                for item in redacted_state["evidence"]
            ],
            *[
                {
                    "ref": f"evidence_status_event:{item['event_id']}",
                    "kind": "evidence_status_event",
                }
                for item in redacted_state["evidence_status_events"]
            ],
            *[
                {"ref": f"dataset:{item['dataset_id']}", "kind": "dataset"}
                for item in redacted_state["datasets"]
            ],
            *[
                {"ref": f"protocol:{item['protocol_id']}", "kind": "protocol"}
                for item in redacted_state["protocols"]
            ],
            *[
                {"ref": f"run:{item['run_id']}", "kind": "run"}
                for item in redacted_state["runs"]
            ],
            *[
                {"ref": f"ethics_review_event:{item['event_id']}", "kind": "ethics_review_event"}
                for item in redacted_state["ethics_review_events"]
            ],
        ]
        return {
            "context_version": 1,
            "purpose": purpose_text,
            "inquiry": redacted_state["inquiry"],
            "open_questions": open_questions,
            "active_hypotheses": [
                hypothesis
                for hypothesis in redacted_state["hypotheses"]
                if hypothesis["workflow_state"] == HypothesisWorkflowState.ACTIVE.value
            ],
            "pending_hypotheses": [
                hypothesis
                for hypothesis in redacted_state["hypotheses"]
                if hypothesis["workflow_state"]
                == HypothesisWorkflowState.PENDING_REVIEW.value
            ],
            "claims": redacted_state["claims"],
            "evidence": redacted_state["evidence"],
            "evidence_status_events": redacted_state["evidence_status_events"],
            "datasets": redacted_state["datasets"],
            "protocols": redacted_state["protocols"],
            "runs": redacted_state["runs"],
            "recommendations": redacted_state["recommendations"],
            "cross_lane_lessons": redacted_state["cross_lane_lessons"],
            "ethics_review_events": redacted_state["ethics_review_events"],
            "context_reference_index": context_reference_index,
            "scientific_constraints": [
                "Treat all supplied material as scoped working context, not established fact.",
                "Propose competing explanations including measurement error, selection, and confounding.",
                "Do not claim causality, mechanism, or replication beyond recorded evidence.",
                "Treat sensor, stream, clock, and control-window commitments as design provenance, "
                "not proof of custody, calibration, synchronization, or timing validity.",
                "Generated hypotheses remain unreviewed until a human explicitly activates them.",
                "Do not authorize human-subject collection, protocol freeze, data registration, or evidence recording.",
                "Treat the latest append-only ethics review event as controlling; suspended, withdrawn, or expired clearance blocks downstream work.",
                "Return uncertainty, falsification conditions, and the next missing scientific decision.",
            ],
            "write_boundary": {
                "context_is_read_only": True,
                "provider_required": False,
                "canonical_changes_require": [
                    "research inquiry/question/claim/hypothesis/protocol/dataset/run/evidence commands",
                    "applicable human review and protocol-freeze gates",
                ],
            },
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
        parent_claims = require_unique_canonical_text_list(
            command.parent_claims, "parent_claims"
        )
        conflicts_with = require_unique_canonical_text_list(
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
            source_refs=require_unique_canonical_text_list(
                command.source_refs, "source_refs"
            ),
            conflicts_with=conflicts_with,
            falsified_by=require_unique_canonical_text_list(
                command.falsified_by, "falsified_by"
            ),
            last_reviewed=(
                require_text(command.last_reviewed, "last_reviewed")
                if command.last_reviewed is not None
                else None
            ),
            decision_owner=normalize_text(command.decision_owner, "decision_owner"),
        )
        from research_machine.application.claim_integrity import (
            claim_scientific_sha256,
            validate_claim_dependency_levels,
        )
        claim = replace(
            claim, scientific_content_sha256=claim_scientific_sha256(claim)
        )
        validate_claim_dependency_levels(claim, {item.claim_id: item for item in claims})
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
            from research_machine.application.claim_integrity import (
                validate_claim_scientific_commitment,
            )
            validate_claim_scientific_commitment(claim)
            conflicts_with = (
                claim.conflicts_with
                if command.conflicts_with is None
                else require_unique_canonical_text_list(
                    command.conflicts_with, "conflicts_with"
                )
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
                    else require_unique_canonical_text_list(
                        command.source_refs, "source_refs"
                    )
                ),
                conflicts_with=conflicts_with,
                falsified_by=(
                    claim.falsified_by
                    if command.falsified_by is None
                    else require_unique_canonical_text_list(
                        command.falsified_by, "falsified_by"
                    )
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
        parent_claims = require_unique_canonical_text_list(
            command.parent_claims, "parent_claims"
        )
        lineage = require_unique_canonical_text_list(command.lineage, "lineage")
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
        contrast_definition = normalize_text(
            command.contrast_definition, "contrast_definition"
        )
        contrast_groups = require_unique_canonical_text_list(
            command.contrast_groups, "contrast_groups"
        )
        if bool(contrast_definition) != bool(contrast_groups):
            raise ValidationError(
                "contrast_definition and contrast_groups must be declared together"
            )
        if contrast_groups and (
            len(contrast_groups) != 2 or len(set(contrast_groups)) != 2
        ):
            raise ValidationError(
                "contrast_groups must contain exactly two distinct ordered levels"
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
            contrast_definition=contrast_definition,
            contrast_groups=contrast_groups,
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
        from research_machine.application.hypothesis_integrity import (
            hypothesis_scientific_sha256,
        )
        hypothesis = replace(
            hypothesis,
            scientific_content_sha256=hypothesis_scientific_sha256(hypothesis),
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
        from research_machine.application.hypothesis_integrity import (
            validate_hypothesis_scientific_commitment,
        )
        validate_hypothesis_scientific_commitment(hypothesis)
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
        from research_machine.application.hypothesis_integrity import (
            validate_hypothesis_scientific_commitment,
        )
        validate_hypothesis_scientific_commitment(hypothesis)
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
            pending_review_rationale=require_pending_review_rationale(rationale),
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
        from research_machine.application.hypothesis_integrity import (
            validate_hypothesis_scientific_commitment,
        )
        validate_hypothesis_scientific_commitment(hypothesis)
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
                "reason": require_canonical_bounded_report_text(
                    command.reason, "retirement reason"
                ),
                "limitations": require_canonical_bounded_report_text(
                    command.limitations, "retirement limitations"
                ),
                "resurrection_conditions": require_nonempty_unique_bounded_report_text_list(
                    command.resurrection_conditions, "resurrection_conditions"
                ),
                "superseded_by": command.superseded_by,
                "decided_at": self.clock(),
                "decided_by": self.actor,
            },
        )
        validate_hypothesis_retirement_boundary(retired)
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
        hypotheses = self.repository.list_hypotheses(resolved, state)
        from research_machine.application.hypothesis_integrity import (
            validate_hypothesis_scientific_commitment,
        )
        for hypothesis in hypotheses:
            validate_hypothesis_scientific_commitment(hypothesis)
            validate_hypothesis_pending_review_boundary(hypothesis)
            validate_hypothesis_retirement_boundary(hypothesis)
        return hypotheses

    def get_hypothesis(
        self, hypothesis_id: str, inquiry_id: str | None = None
    ) -> Hypothesis:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        hypothesis = self.repository.find_hypothesis(resolved, hypothesis_id)
        from research_machine.application.hypothesis_integrity import (
            validate_hypothesis_scientific_commitment,
        )
        validate_hypothesis_scientific_commitment(hypothesis)
        validate_hypothesis_pending_review_boundary(hypothesis)
        validate_hypothesis_retirement_boundary(hypothesis)
        return hypothesis

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
        if "measurement_custody_verification" in command.metadata:
            raise ValidationError(
                "measurement_custody_verification is service-generated and cannot be supplied"
            )
        if "dataset_artifact_verification" in command.metadata:
            raise ValidationError(
                "dataset_artifact_verification is service-generated and cannot be supplied"
            )
        if "dataset_payload_sha256" in command.metadata:
            raise ValidationError(
                "dataset_payload_sha256 is service-generated and cannot be supplied"
            )
        if "ethics_condition_verification" in command.metadata:
            raise ValidationError(
                "ethics_condition_verification is service-generated and cannot be supplied"
            )
        if "ethics_review_status_check" in command.metadata:
            raise ValidationError(
                "ethics_review_status_check is service-generated and cannot be supplied"
            )
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
            if command.role in protected_roles:
                cross_protocol_sources = [
                    source.dataset_id
                    for source in sources
                    if source.protocol_id != protocol.protocol_id
                ]
                if cross_protocol_sources:
                    raise ValidationError(
                        "protected dataset lineage must remain bound to the exact same "
                        "frozen protocol; cross-protocol sources: "
                        + ", ".join(cross_protocol_sources)
                    )
        elif command.role in protected_roles:
            raise ValidationError(
                f"{command.role.value} datasets require a frozen protocol"
            )

        custody_requirements = protocol.measurement_custody_requirements if protocol else []
        dataset_metadata = dict(command.metadata)
        if command.role in protected_roles and not command.synthetic:
            if command.artifact_root is None:
                raise ValidationError(
                    f"non-synthetic {command.role.value} datasets require artifact_root "
                    "so registered observation bytes are verified"
                )
            from research_machine.application.dataset_integrity import (
                verify_dataset_artifacts,
            )
            dataset_metadata["dataset_artifact_verification"] = verify_dataset_artifacts(
                artifacts,
                command.artifact_root,
                actor=self.actor,
                verified_at=self.clock(),
                protocol_hash=protocol.protocol_hash if protocol else None,
            )
        elif command.artifact_root is not None:
            raise ValidationError(
                "artifact_root is only accepted for non-synthetic confirmatory or replication datasets"
            )
        if protocol and protocol.human_subjects:
            from research_machine.application.ethics import evaluate_ethics_clearance
            dataset_metadata["ethics_review_status_check"] = evaluate_ethics_clearance(
                protocol,
                self.repository.list_ethics_review_events(resolved, protocol.protocol_id),
                _parse_aware_timestamp(self.clock(), "dataset registration time"),
            )
            discharge = command.metadata.get("ethics_condition_discharge")
            if protocol.independent_review_decision == "approved_with_conditions":
                if command.ethics_artifact_root is None:
                    raise ValidationError(
                        "conditionally approved human-subject data require ethics_artifact_root"
                    )
                from research_machine.application.ethics import (
                    verify_ethics_condition_discharge,
                )
                dataset_metadata["ethics_condition_verification"] = (
                    verify_ethics_condition_discharge(
                        discharge,
                        protocol,
                        command.ethics_artifact_root,
                        actor=self.actor,
                        verified_at=self.clock(),
                    )
                )
            elif discharge is not None or command.ethics_artifact_root is not None:
                raise ValidationError(
                    "unconditional human-subject approval must not invent a condition discharge"
                )
        if custody_requirements or "measurement_custody" in command.metadata:
            custody = validate_measurement_custody(
                command.metadata.get("measurement_custody"), custody_requirements,
                protocol.calibration_acceptance_criteria if protocol else (),
            )
            covered = {item["source_output_sha256"] for item in custody["derived_observations"]}
            if {artifact.sha256 for artifact in artifacts} != covered:
                raise ValidationError(
                    "measurement custody derived observations must cover exactly "
                    "the registered dataset artifact hashes"
                )
            if custody_requirements and command.custody_artifact_root is None:
                raise ValidationError(
                    "protected measurement custody requires custody_artifact_root so raw, "
                    "transformation implementation, derived-output, and supporting-evidence bytes are verified at registration"
                )
            if command.custody_artifact_root is not None:
                custody_artifacts = validate_dataset_artifacts([
                    DatasetArtifact(
                        locator=item["locator"],
                        sha256=item["sha256"],
                        size_bytes=item.get("size_bytes"),
                    )
                    for item in [
                        *custody["raw_sources"], *custody["evidence_artifacts"],
                        *({"locator": item["implementation_locator"], "sha256": item["implementation_sha256"]}
                          for item in custody["transformations"]),
                        *({"locator": item["output_locator"], "sha256": item["output_sha256"]}
                          for item in custody["transformations"]),
                    ]
                ])
                report = verify_run_artifacts(
                    custody_artifacts,
                    artifact_root=command.custody_artifact_root,
                    actor=self.actor,
                    analysis_code_hash="",
                    run_metadata={},
                    attestation_schema_path=None,
                    expected_attestation_schema_sha256=None,
                )
                if report.status != "passed":
                    raise ValidationError(
                        "custody artifact verification failed: "
                        + ", ".join(item["code"] for item in report.findings)
                    )
                dataset_metadata["measurement_custody_verification"] = {
                    "verification_version": 1,
                    "verified_at": self.clock(),
                    "verified_by": self.actor,
                    "custody_artifact_root": str(
                        Path(command.custody_artifact_root).expanduser().resolve()
                    ),
                    "custody_receipt_sha256": _sha256_json(custody),
                    "protocol_hash": protocol.protocol_hash if protocol else None,
                    "required_gate_ids": list(custody_requirements),
                    "artifact_integrity": report.to_dict(),
                    "scope": "raw-source, transformation implementation, derived-output, and supporting-evidence bytes under the supplied local artifact root",
                    "scientific_interpretation_verified": False,
                }

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
            metadata=dataset_metadata,
        )
        from research_machine.application.dataset_integrity import (
            dataset_payload_sha256,
            validate_protected_dataset_lineage_closure,
        )
        dataset = replace(
            dataset,
            metadata={
                **dataset.metadata,
                "dataset_payload_sha256": dataset_payload_sha256(dataset),
            },
        )
        validate_protected_dataset_lineage_closure(
            dataset,
            {
                item.dataset_id: item
                for item in [*self.repository.list_datasets(resolved), dataset]
            },
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

    def export_replication_package(
        self,
        protocol_id: str,
        output: str,
        inquiry_id: str | None = None,
        *,
        include_locators: bool = False,
    ) -> dict[str, Any]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return export_replication_package(
            self.repository.find_protocol(resolved, protocol_id),
            self.repository.list_datasets(resolved),
            self.repository.list_runs(resolved),
            self.repository.list_ethics_review_events(resolved, protocol_id),
            Path(output),
            include_locators=include_locators,
        )

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
        review_artifact_root: str | None = None,
    ) -> ExperimentProtocol:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        protocol = self.repository.find_protocol(resolved, protocol_id)
        if not isinstance(protocol.causal_claim, bool):
            raise ValidationError("causal_claim must be true or false")
        if protocol.causal_claim:
            from research_machine.design.causal import audit_causal_identification
            if not protocol.causal_identification:
                raise ValidationError("causal protocol freeze requires causal_identification")
            causal_audit = audit_causal_identification(protocol.causal_identification)
            if causal_audit["violations"]:
                raise ValidationError(
                    "causal identification audit is blocked: "
                    + ", ".join(item["code"] for item in causal_audit["violations"])
                )
            if (protocol.protocol_kind is ProtocolKind.OBSERVATIONAL
                    and causal_audit["assignment_type"] != "observational"):
                raise ValidationError("observational causal protocols require observational identification")
            if (causal_audit["assignment_type"] == "observational"
                    and causal_audit["backdoor_criterion_satisfied"] is not True):
                raise ValidationError("observational causal protocol does not satisfy the supplied backdoor criterion")
            protocol = replace(protocol, causal_identification_audit=causal_audit)
        elif protocol.causal_identification or protocol.causal_identification_audit:
            raise ValidationError("causal identification requires causal_claim true")
        validate_protocol_freeze(protocol)
        review_verification: dict[str, Any] = {}
        if protocol.human_subjects:
            if review_artifact_root is None:
                raise ValidationError(
                    "human-subject protocol freeze requires review_artifact_root for independent-review byte verification"
                )
            canonical_review_root = require_canonical_text(
                review_artifact_root, "review_artifact_root"
            )
            review_report = verify_run_artifacts(
                [DatasetArtifact(
                    locator=protocol.independent_review_artifact_locator,
                    sha256=protocol.independent_review_artifact_sha256,
                )],
                artifact_root=canonical_review_root,
                actor=self.actor,
                analysis_code_hash="",
                run_metadata={},
                attestation_schema_path=None,
                expected_attestation_schema_sha256=None,
            )
            if review_report.status != "passed":
                raise ValidationError(
                    "independent review artifact verification failed: "
                    + ", ".join(item["code"] for item in review_report.findings)
                )
            reviewed_at = _parse_aware_timestamp(protocol.independent_reviewed_at, "independent_reviewed_at")
            frozen_at = _parse_aware_timestamp(self.clock(), "protocol freeze time")
            if reviewed_at > frozen_at:
                raise ValidationError("independent review decision cannot postdate protocol freeze")
            review_verification = {
                "verification_version": 1,
                "verified_at": frozen_at.isoformat(),
                "verified_by": self.actor,
                "review_artifact_root": str(
                    Path(canonical_review_root).expanduser().resolve()
                ),
                "artifact_integrity": review_report.to_dict(),
                "scope": "local independent-review artifact byte identity and internal chronology",
                "reviewer_identity_authenticated": False,
                "substantive_adequacy_verified": False,
            }
        primary_hypothesis: Hypothesis | None = None
        causal_hypothesis: Hypothesis | None = None
        tested_hypotheses: list[Hypothesis] = []
        causal_estimand = (
            protocol.causal_identification_audit.get("causal_estimand")
            if protocol.causal_claim
            else None
        )
        for hypothesis_id in protocol.hypotheses_tested:
            hypothesis = self.repository.find_hypothesis(resolved, hypothesis_id)
            tested_hypotheses.append(hypothesis)
            if (
                causal_estimand is not None
                and hypothesis_id == causal_estimand["target_hypothesis_id"]
            ):
                causal_hypothesis = hypothesis
            if protocol.analysis_contract is not None and hypothesis_id == protocol.analysis_contract.primary_hypothesis_id:
                primary_hypothesis = hypothesis
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
        if protocol.causal_claim:
            if causal_hypothesis is None:
                raise ValidationError("causal estimand target hypothesis is unavailable")
            if not causal_hypothesis.primary_estimand.strip():
                raise ValidationError(
                    "causal estimand target hypothesis has no reviewed primary_estimand"
                )
            if causal_hypothesis.primary_estimand != causal_estimand["description"]:
                raise ValidationError(
                    "causal estimand description does not match the target hypothesis primary_estimand"
                )
        if protocol.analysis_contract is not None:
            if primary_hypothesis is None:
                raise ValidationError("analysis contract primary hypothesis is unavailable")
            if not primary_hypothesis.primary_estimand.strip():
                raise ValidationError("analysis contract primary hypothesis has no reviewed primary_estimand")
            if primary_hypothesis.primary_estimand != protocol.analysis_contract.estimand:
                raise ValidationError("analysis contract estimand does not match the primary hypothesis estimand")
            if (
                primary_hypothesis.contrast_definition
                or protocol.analysis_contract.contrast_definition
            ) and (
                not primary_hypothesis.contrast_definition
                or not protocol.analysis_contract.contrast_definition
                or primary_hypothesis.contrast_definition
                != protocol.analysis_contract.contrast_definition
            ):
                raise ValidationError(
                    "analysis contract contrast_definition must exactly match the primary hypothesis contrast_definition"
                )
            hypothesis_groups = primary_hypothesis.contrast_groups
            contract_groups = protocol.analysis_contract.contrast_groups
            if (
                hypothesis_groups or contract_groups
                or primary_hypothesis.contrast_definition
                or protocol.analysis_contract.contrast_definition
            ):
                if (
                    len(hypothesis_groups) != 2
                    or len(set(hypothesis_groups)) != 2
                    or hypothesis_groups != contract_groups
                    or contract_groups != protocol.analysis_contract.groups
                ):
                    raise ValidationError(
                        "analysis contract contrast_groups must exactly match the primary hypothesis and executable group order"
                    )
            if primary_hypothesis.expected_effect_direction not in {
                "positive", "negative", "two_sided", "equivalence",
            }:
                raise ValidationError(
                    "analysis contract primary hypothesis must declare expected_effect_direction as positive, negative, two_sided, or equivalence"
                )
            from research_machine.application.policies import (
                validate_equivalence_design_coherence,
            )
            validate_equivalence_design_coherence(
                analysis_contract=protocol.analysis_contract,
                conclusion_contract=protocol.conclusion_contract,
                expected_direction=primary_hypothesis.expected_effect_direction,
                multiplicity_method=protocol.multiplicity_method,
                multiplicity_alpha=protocol.multiplicity_alpha,
            )
            if protocol.sample_size_plan:
                from research_machine.application.policies import (
                    validate_planning_inference_coherence,
                )
                validate_planning_inference_coherence(
                    sample_size_plan=protocol.sample_size_plan,
                    analysis_contract=protocol.analysis_contract,
                    expected_direction=primary_hypothesis.expected_effect_direction,
                    multiplicity_alpha=protocol.multiplicity_alpha,
                    measurement_unit=next(
                        item.unit for item in protocol.measurement_definitions
                        if item.measurement_id
                        == protocol.analysis_contract.primary_measurement_id
                    ),
                    smallest_effect_size_of_interest=(
                        protocol.conclusion_contract.smallest_effect_size_of_interest
                        if protocol.conclusion_contract is not None else None
                    ),
                    maximum_excluded_fraction=(
                        protocol.analysis_contract.maximum_excluded_fraction
                    ),
                    multiplicity_method=protocol.multiplicity_method,
                )
        from research_machine.application.hypothesis_integrity import (
            build_hypothesis_commitments,
        )
        protocol = replace(
            protocol,
            hypothesis_commitments=build_hypothesis_commitments(tested_hypotheses),
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
            independent_review_verification=review_verification,
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
        amendment_timing: str,
        evidence_exposure: str,
        inquiry_id: str | None = None,
    ) -> ExperimentProtocol:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        predecessor = self.repository.find_protocol(resolved, protocol_id)
        if predecessor.status is not ProtocolStatus.FROZEN:
            raise ValidationError("only frozen protocols can be amended")
        self._validate_frozen_protocol_integrity(resolved, predecessor)
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
        if amendment_timing not in {"before_collection", "during_collection", "after_collection", "after_analysis", "unknown"}:
            raise ValidationError("invalid protocol amendment_timing")
        if evidence_exposure not in {"not_seen", "aggregate_seen", "full_data_seen", "unknown"}:
            raise ValidationError("invalid protocol evidence_exposure")
        amended = self._build_protocol(
            resolved,
            command,
            protocol_family_id=predecessor.protocol_family_id,
            version=predecessor.version + 1,
            supersedes_protocol_id=predecessor.protocol_id,
            amendment_reason=require_text(reason, "amendment reason"),
            amendment_timing=amendment_timing,
            evidence_exposure=evidence_exposure,
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
        protocols = self.repository.list_protocols(resolved)
        for protocol in protocols:
            if protocol.status is ProtocolStatus.FROZEN:
                self._validate_frozen_protocol_integrity(resolved, protocol)
        return protocols

    def get_protocol(
        self, protocol_id: str, inquiry_id: str | None = None
    ) -> ExperimentProtocol:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        protocol = self.repository.find_protocol(resolved, protocol_id)
        if protocol.status is ProtocolStatus.FROZEN:
            self._validate_frozen_protocol_integrity(resolved, protocol)
        return protocol

    def _validate_frozen_protocol_integrity(
        self, inquiry_id: str, protocol: ExperimentProtocol
    ) -> None:
        if not protocol.protocol_hash:
            raise ValidationError(
                f"frozen protocol {protocol.protocol_id} no longer matches its commitment"
            )
        from research_machine.application.hypothesis_integrity import (
            validate_protocol_hypothesis_commitments,
        )
        if protocol.hypothesis_commitments:
            if _protocol_commitment(protocol) != protocol.protocol_hash:
                raise ValidationError(
                    f"frozen protocol {protocol.protocol_id} no longer matches its commitment"
                )
            validate_protocol_hypothesis_commitments(
                protocol,
                {
                    hypothesis_id: self.repository.find_hypothesis(
                        inquiry_id, hypothesis_id
                    )
                    for hypothesis_id in protocol.hypotheses_tested
                },
            )
        else:
            self.repository.verify_legacy_protocol_integrity(inquiry_id, protocol)

    def record_ethics_review_event(
        self, command: RecordEthicsReviewEvent, inquiry_id: str | None = None
    ) -> EthicsReviewEvent:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        protocol_id = require_text(command.protocol_id, "protocol_id")
        if protocol_id != command.protocol_id:
            raise ValidationError(
                "protocol_id must be canonical without surrounding whitespace"
            )
        if command.event_id is not None:
            event_id = require_text(command.event_id, "event_id")
            if event_id != command.event_id:
                raise ValidationError(
                    "event_id must be canonical without surrounding whitespace"
                )
        else:
            event_id = None
        if command.supersedes_event_id is not None:
            supersedes_event_id = require_text(
                command.supersedes_event_id, "supersedes_event_id"
            )
            if supersedes_event_id != command.supersedes_event_id:
                raise ValidationError(
                    "supersedes_event_id must be canonical without surrounding whitespace"
                )
        else:
            supersedes_event_id = None
        protocol = self.repository.find_protocol(resolved, protocol_id)
        if (protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash
                or _protocol_commitment(protocol) != protocol.protocol_hash):
            raise ValidationError("ethics review events require an intact frozen protocol")
        if not protocol.human_subjects:
            raise ValidationError("ethics review events require a human-subject protocol")
        status = require_text(command.status, "ethics review status")
        if status != command.status:
            raise ValidationError(
                "ethics review status must be canonical without surrounding whitespace"
            )
        if status not in {"active", "suspended", "withdrawn", "expired"}:
            raise ValidationError("ethics review status must be active, suspended, withdrawn, or expired")
        created_at = self.clock()
        created = _parse_aware_timestamp(created_at, "ethics review event creation time")
        effective_at = require_text(command.effective_at, "effective_at")
        if effective_at != command.effective_at:
            raise ValidationError(
                "effective_at must be canonical without surrounding whitespace"
            )
        effective = _parse_aware_timestamp(effective_at, "effective_at")
        reviewed = _parse_aware_timestamp(protocol.independent_reviewed_at, "independent_reviewed_at")
        if effective < reviewed:
            raise ValidationError("ethics review event cannot predate the independent review")
        if effective > created:
            raise ValidationError("ethics review event cannot take effect in the future")
        expires_at = require_text(command.expires_at, "expires_at") if command.expires_at is not None else None
        if expires_at is not None and expires_at != command.expires_at:
            raise ValidationError(
                "expires_at must be canonical without surrounding whitespace"
            )
        if status == "active" and expires_at is not None:
            if _parse_aware_timestamp(expires_at, "expires_at") <= effective:
                raise ValidationError("active ethics clearance expires_at must follow effective_at")
        elif status != "active" and expires_at is not None:
            raise ValidationError("non-active ethics review events cannot declare expires_at")
        from research_machine.application.ethics import validate_ethics_review_event_chain
        prior = validate_ethics_review_event_chain(
            protocol,
            self.repository.list_ethics_review_events(resolved, protocol.protocol_id),
        )
        latest = prior[-1] if prior else None
        if latest is None and supersedes_event_id is not None:
            raise ValidationError("first ethics review event cannot supersede another event")
        if latest is not None:
            if supersedes_event_id != latest.event_id:
                raise ValidationError("ethics review event must supersede the exact latest event")
            if effective < _parse_aware_timestamp(latest.effective_at, "prior effective_at"):
                raise ValidationError("ethics review event effective_at cannot move backward")
        artifact_hash = require_sha256(command.review_artifact_sha256, "review_artifact_sha256")
        review_artifact_locator = require_canonical_text(
            command.review_artifact_locator, "review_artifact_locator"
        )
        review_artifact_root = require_canonical_text(
            command.review_artifact_root, "review_artifact_root"
        )
        report = verify_run_artifacts(
            [DatasetArtifact(
                locator=review_artifact_locator,
                sha256=artifact_hash,
            )],
            artifact_root=review_artifact_root,
            actor=self.actor, analysis_code_hash="", run_metadata={},
            attestation_schema_path=None, expected_attestation_schema_sha256=None,
        )
        if report.status != "passed":
            raise ValidationError("ethics review event artifact verification failed: "
                                  + ", ".join(item["code"] for item in report.findings))
        reason = require_canonical_bounded_report_text(
            command.reason, "ethics review event reason"
        )
        created_by = require_canonical_text(
            self.actor, "ethics review event created_by"
        )
        event = EthicsReviewEvent(
            event_id=event_id or f"ethics-{self.token()}",
            sequence=len(prior) + 1,
            protocol_id=protocol.protocol_id, protocol_hash=protocol.protocol_hash,
            status=status, effective_at=effective_at, expires_at=expires_at,
            reason=reason,
            review_artifact_locator=review_artifact_locator,
            review_artifact_sha256=artifact_hash,
            review_artifact_root=str(
                Path(review_artifact_root).expanduser().resolve()
            ),
            supersedes_event_id=supersedes_event_id,
            created_at=created_at, created_by=created_by,
            artifact_integrity=report.to_dict(),
            conclusion_ceiling=require_canonical_bounded_report_text(
                (
                    "Records local review-status evidence and blocks work when non-active; "
                    "does not authenticate the reviewer or judge substantive adequacy."
                ),
                "review event conclusion_ceiling",
            ),
        )
        self.repository.save_ethics_review_event(resolved, event)
        self._event(resolved, "ethics.review_status", "protocol", protocol.protocol_id, event.to_dict())
        return event

    def validate_analysis_execution(
        self, protocol_id: str, specification: dict[str, Any],
        unit_structure: dict[str, Any], implementation_sha256: str,
        specification_sha256: str, dataset_id: str, input_sha256: str,
        input_size_bytes: int, maximum_inference_level: str,
        inquiry_id: str | None = None,
    ) -> dict[str, Any]:
        """Route a protocol-bound executable to its frozen workflow contract."""
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        protocol = self.repository.find_protocol(resolved, protocol_id)
        ethics_execution_check: dict[str, Any] = {}
        if protocol.human_subjects:
            from research_machine.application.ethics import (
                evaluate_ethics_clearance,
                validate_ethics_conditions_for_run,
            )
            dataset = self.repository.find_dataset(resolved, dataset_id)
            checked_at = _parse_aware_timestamp(
                self.clock(), "analysis execution ethics-check time"
            )
            ethics_execution_check = {
                "review_status": evaluate_ethics_clearance(
                    protocol,
                    self.repository.list_ethics_review_events(
                        resolved, protocol.protocol_id
                    ),
                    checked_at,
                ),
                "conditions": validate_ethics_conditions_for_run(
                    protocol, [dataset], checked_at
                ),
                "checked_before_execution": True,
            }
        workflow_matches = [
            step for step in protocol.analysis_steps
            if step.specification_sha256 == specification_sha256
            and step.method == specification.get("method")
        ]
        if len(workflow_matches) == 1 and workflow_matches[0].role == "confirmatory_test":
            result = self.validate_confirmatory_test_design(
                protocol_id, workflow_matches[0], specification, unit_structure,
                implementation_sha256, dataset_id, input_sha256,
                input_size_bytes, maximum_inference_level, inquiry_id,
            )
        elif specification.get("method") == "holm_adjustment":
            result = self.validate_multiplicity_analysis_design(
                protocol_id, specification, implementation_sha256,
                specification_sha256, dataset_id, input_sha256,
                input_size_bytes, maximum_inference_level, inquiry_id,
            )
        else:
            result = self.validate_analysis_design(
                protocol_id, specification, unit_structure, implementation_sha256,
                specification_sha256, dataset_id, input_sha256, input_size_bytes,
                maximum_inference_level, inquiry_id,
            )
        if ethics_execution_check:
            result["ethics_execution_check"] = ethics_execution_check
        return result

    def validate_confirmatory_test_design(
        self, protocol_id: str, step: AnalysisStepContract,
        specification: dict[str, Any], unit_structure: dict[str, Any],
        implementation_sha256: str, dataset_id: str, input_sha256: str,
        input_size_bytes: int, maximum_inference_level: str,
        inquiry_id: str | None = None,
    ) -> dict[str, Any]:
        """Bind an outcome test to its frozen workflow, measurement, and data."""
        protocol = self.get_protocol(protocol_id, inquiry_id)
        if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
            raise ValidationError("confirmatory-test execution requires a frozen protocol")
        if _protocol_commitment(protocol) != protocol.protocol_hash:
            raise ValidationError("frozen protocol content no longer matches its hash commitment")
        if step not in protocol.analysis_steps or step.role != "confirmatory_test":
            raise ValidationError("analysis step is not a frozen confirmatory_test")
        if require_sha256(implementation_sha256, "implementation_sha256") != step.implementation_sha256:
            raise ValidationError("confirmatory-test implementation does not match its frozen step")
        measurements = [
            item for item in protocol.measurement_definitions
            if item.measurement_id == step.measurement_id
        ]
        if len(measurements) != 1 or specification.get("outcome_column") != measurements[0].data_column:
            raise ValidationError("confirmatory-test outcome_column does not match its frozen measurement")
        if specification.get("study_design") != protocol.analysis_design:
            raise ValidationError("confirmatory-test study_design does not match the protocol")
        contract = protocol.analysis_contract
        if contract is None:
            raise ValidationError("confirmatory-test execution requires the protocol comparison contract")
        for field_name in ("group_column", "groups", "missing_data_policy"):
            if specification.get(field_name) != getattr(contract, field_name):
                raise ValidationError(
                    f"confirmatory-test {field_name} does not match the frozen comparison contract"
                )
        if protocol.causal_claim and maximum_inference_level != "design_conditional_effect":
            raise ValidationError("causal confirmatory tests require a design_conditional_effect method ceiling")
        if not isinstance(unit_structure, dict) or unit_structure.get("unit_id_column") != protocol.unit_id_column:
            raise ValidationError("confirmatory-test unit identity does not match the protocol")
        if protocol.repeated_measures is False and unit_structure.get("repeated_unit_count") != 0:
            raise ValidationError("confirmatory-test data repeat units despite the frozen design")
        if contract.assignment_type == "randomized_between_units" and unit_structure.get("unit_group_allocation_sha256") != contract.allocation_sha256:
            raise ValidationError("confirmatory-test allocation does not match the frozen randomization")
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        dataset = self.repository.find_dataset(resolved, dataset_id)
        self._validate_run_datasets(
            protocol,
            [dataset],
            all_datasets=self.repository.list_datasets(resolved),
        )
        digest = require_sha256(input_sha256, "input_sha256")
        artifacts = [item for item in dataset.artifacts if item.sha256 == digest]
        if not artifacts:
            raise ValidationError("confirmatory-test input bytes do not match the registered dataset")
        if type(input_size_bytes) is not int or input_size_bytes < 0:
            raise ValidationError("input_size_bytes must be a non-negative integer")
        if any(item.size_bytes is not None and item.size_bytes != input_size_bytes for item in artifacts):
            raise ValidationError("confirmatory-test input size does not match the registered dataset")
        return {
            "protocol_id": protocol.protocol_id, "protocol_hash": protocol.protocol_hash,
            "scope": "frozen_confirmatory_test_and_registered_input", "status": "passed",
            "analysis_step_contract": step.to_dict(),
            "analysis_specification_sha256": step.specification_sha256,
            "executed_analysis_specification": dict(specification),
            "measurement_contracts": [measurements[0].to_dict()],
            "unit_structure": dict(unit_structure), "dataset_id": dataset.dataset_id,
            "input_sha256": digest, "synthetic": dataset.synthetic,
            "method_inference_check": {
                "maximum_inference_level": maximum_inference_level,
                "status": "passed",
                "scope": "method ceiling retained; not evidence of causal validity",
            },
            "scientific_evidence_eligible": False,
        }

    def validate_multiplicity_analysis_design(
        self, protocol_id: str, specification: dict[str, Any],
        implementation_sha256: str, specification_sha256: str,
        dataset_id: str, input_sha256: str, input_size_bytes: int,
        maximum_inference_level: str, inquiry_id: str | None = None,
    ) -> dict[str, Any]:
        """Bind Holm execution to an exact frozen workflow family and input."""
        protocol = self.get_protocol(protocol_id, inquiry_id)
        if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
            raise ValidationError("multiplicity execution requires a frozen protocol")
        if _protocol_commitment(protocol) != protocol.protocol_hash:
            raise ValidationError("frozen protocol content no longer matches its hash commitment")
        matches = [
            step for step in protocol.analysis_steps
            if step.role == "multiplicity" and step.method == "holm_adjustment"
            and step.specification_sha256 == specification_sha256
        ]
        if len(matches) != 1:
            raise ValidationError(
                "Holm execution specification is not the unique frozen multiplicity step"
            )
        step = matches[0]
        if require_sha256(implementation_sha256, "implementation_sha256") != step.implementation_sha256:
            raise ValidationError("Holm implementation does not match the frozen analysis step")
        if maximum_inference_level != "descriptive":
            raise ValidationError("Holm adjustment must retain a descriptive inference ceiling")
        expected_member_ids = [item.member_id for item in step.family_members]
        if specification.get("family_hypothesis_ids") != expected_member_ids:
            raise ValidationError(
                "Holm family_hypothesis_ids do not match the frozen family members in order"
            )
        if specification.get("family_name") != step.family_id:
            raise ValidationError("Holm family_name does not match the frozen family_id")
        if specification.get("alpha") != step.alpha:
            raise ValidationError("Holm alpha does not match the frozen analysis step")
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        dataset = self.repository.find_dataset(resolved, dataset_id)
        self._validate_run_datasets(
            protocol,
            [dataset],
            all_datasets=self.repository.list_datasets(resolved),
        )
        digest = require_sha256(input_sha256, "input_sha256")
        artifacts = [item for item in dataset.artifacts if item.sha256 == digest]
        if not artifacts:
            raise ValidationError("Holm input bytes do not match the registered dataset")
        if type(input_size_bytes) is not int or input_size_bytes < 0:
            raise ValidationError("input_size_bytes must be a non-negative integer")
        if any(item.size_bytes is not None and item.size_bytes != input_size_bytes for item in artifacts):
            raise ValidationError("Holm input size does not match the registered dataset")
        return {
            "protocol_id": protocol.protocol_id,
            "protocol_hash": protocol.protocol_hash,
            "scope": "frozen_multiplicity_step_and_registered_input",
            "status": "passed",
            "analysis_step_contract": step.to_dict(),
            "analysis_specification_sha256": specification_sha256,
            "executed_analysis_specification": dict(specification),
            "dataset_id": dataset.dataset_id,
            "input_sha256": digest,
            "synthetic": dataset.synthetic,
            "dependency_status": "declared_not_execution_verified",
            "dependency_notice": "Source-step identities are frozen, but this receipt does not yet verify their result receipts.",
            "scientific_evidence_eligible": False,
        }

    def validate_analysis_design(
        self, protocol_id: str, specification: dict[str, Any],
        unit_structure: dict[str, Any],
        implementation_sha256: str, specification_sha256: str,
        dataset_id: str, input_sha256: str, input_size_bytes: int,
        maximum_inference_level: str,
        inquiry_id: str | None = None,
    ) -> dict[str, Any]:
        """Read-only consistency check, not evidence or analysis-plan approval."""
        protocol = self.get_protocol(protocol_id, inquiry_id)
        if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
            raise ValidationError("analysis design checks require a frozen protocol")
        if _protocol_commitment(protocol) != protocol.protocol_hash:
            raise ValidationError("frozen protocol content no longer matches its hash commitment")
        if not protocol.analysis_design or protocol.repeated_measures is None or not protocol.independent_unit:
            raise ValidationError("frozen protocol has no complete structured design declaration")
        if specification.get("study_design") != protocol.analysis_design:
            raise ValidationError("analysis study_design does not match the frozen protocol")
        contract = protocol.analysis_contract
        if contract is None:
            raise ValidationError("frozen protocol has no semantic analysis contract")
        from research_machine.addons.models import INFERENCE_LEVELS
        if maximum_inference_level not in INFERENCE_LEVELS:
            raise ValidationError("analysis method has an unsupported maximum_inference_level")
        required_inference_level = (
            "design_conditional_effect" if protocol.causal_claim else "not_causal"
        )
        if protocol.causal_claim and maximum_inference_level != "design_conditional_effect":
            raise ValidationError(
                "causal primary analysis requires a design_conditional_effect method ceiling"
            )
        comparisons = {
            "method": contract.method,
            "outcome_column": contract.outcome_column,
            "group_column": contract.group_column,
            "groups": contract.groups,
            "covariate_columns": contract.adjustment_columns,
            "estimand": contract.estimand,
            "contrast_definition": contract.contrast_definition,
            "missing_data_policy": contract.missing_data_policy,
        }
        for field_name, expected in comparisons.items():
            observed = (
                specification.get(field_name, [])
                if field_name == "covariate_columns"
                else specification.get(field_name, "")
                if field_name == "contrast_definition"
                else specification.get(field_name)
            )
            if observed != expected:
                raise ValidationError(
                    f"analysis {field_name} does not match the frozen analysis contract"
                )
        executed_semantics = {
            "study_design": specification.get("study_design"),
            **{
                field_name: (
                    specification.get(field_name, [])
                    if field_name == "covariate_columns"
                    else specification.get(field_name)
                )
                for field_name in comparisons
            },
            "contrast_groups": list(specification.get("groups", [])),
        }
        if not isinstance(unit_structure, dict) or unit_structure.get("unit_id_column") != protocol.unit_id_column:
            raise ValidationError("analysis unit or pair column does not match the frozen protocol unit_id_column")
        required_unit_fields = {"unit_id_column", "row_count", "unit_count", "repeated_unit_count",
                                "minimum_observations_per_unit", "maximum_observations_per_unit",
                                "row_to_unit_mapping_sha256", "unit_group_allocation_sha256"}
        if set(unit_structure) != required_unit_fields:
            raise ValidationError("analysis unit structure fields do not match the documented contract")
        for field in ("row_count", "unit_count", "repeated_unit_count",
                      "minimum_observations_per_unit", "maximum_observations_per_unit"):
            value = unit_structure[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValidationError("analysis unit structure counts must be non-negative integers")
        require_sha256(unit_structure["row_to_unit_mapping_sha256"], "row_to_unit_mapping_sha256")
        require_sha256(unit_structure["unit_group_allocation_sha256"], "unit_group_allocation_sha256")
        if unit_structure["row_count"] < 1 or unit_structure["unit_count"] < 1:
            raise ValidationError("analysis unit structure must contain observations and units")
        if unit_structure["unit_count"] > unit_structure["row_count"]:
            raise ValidationError("analysis unit count cannot exceed row count")
        if unit_structure["repeated_unit_count"] > unit_structure["unit_count"]:
            raise ValidationError("repeated unit count cannot exceed unit count")
        if (unit_structure["minimum_observations_per_unit"] < 1
                or unit_structure["maximum_observations_per_unit"] < unit_structure["minimum_observations_per_unit"]):
            raise ValidationError("analysis unit observation-count bounds are inconsistent")
        if ((unit_structure["unit_count"] == unit_structure["row_count"])
                != (unit_structure["repeated_unit_count"] == 0)):
            raise ValidationError("analysis unit repetition counts are internally inconsistent")
        if protocol.repeated_measures is False and unit_structure["repeated_unit_count"]:
            raise ValidationError("dataset repeats unit identifiers despite a no-repeated-measures protocol")
        if protocol.analysis_design == "paired" and (
            unit_structure["minimum_observations_per_unit"] != 2
            or unit_structure["maximum_observations_per_unit"] != 2
        ):
            raise ValidationError("paired analysis requires exactly two observations per frozen unit identifier")
        if contract.assignment_type == "randomized_between_units" and unit_structure["unit_group_allocation_sha256"] != contract.allocation_sha256:
            raise ValidationError("observed unit-group allocation does not match the frozen randomized allocation")
        if require_sha256(implementation_sha256, "implementation_sha256") != protocol.analysis_code_hash:
            raise ValidationError("analysis implementation does not match the frozen protocol")
        if not protocol.analysis_specification_sha256:
            raise ValidationError("frozen protocol has no analysis specification commitment")
        if require_sha256(specification_sha256, "specification_sha256") != protocol.analysis_specification_sha256:
            raise ValidationError("analysis specification does not match the frozen protocol")
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        dataset = self.repository.find_dataset(resolved, dataset_id)
        self._validate_run_datasets(
            protocol,
            [dataset],
            all_datasets=self.repository.list_datasets(resolved),
        )
        digest = require_sha256(input_sha256, "input_sha256")
        matches = [artifact for artifact in dataset.artifacts if artifact.sha256 == digest]
        if not matches:
            raise ValidationError("analysis input bytes do not match the registered dataset")
        if type(input_size_bytes) is not int or input_size_bytes < 0:
            raise ValidationError("input_size_bytes must be a non-negative integer")
        if any(item.size_bytes is not None and item.size_bytes != input_size_bytes for item in matches):
            raise ValidationError("analysis input size does not match the registered dataset")
        return {"protocol_id": protocol.protocol_id, "protocol_hash": protocol.protocol_hash,
                "scope": "design_code_specification_and_registered_input", "status": "passed",
                "analysis_specification_sha256": specification_sha256,
                "analysis_contract": contract.to_dict(),
                "method_inference_check": {
                    "required_inference_level": required_inference_level,
                    "maximum_inference_level": maximum_inference_level,
                    "status": "passed",
                    "scope": "method capability combined with frozen protocol; not causal proof",
                },
                "executed_analysis_semantics": executed_semantics,
                "measurement_contracts": [
                    item.to_dict() for item in protocol.measurement_definitions
                    if item.data_column
                ],
                "unit_structure": dict(unit_structure),
                "dataset_id": dataset.dataset_id, "input_sha256": digest,
                "synthetic": dataset.synthetic,
                "scientific_evidence_eligible": False}

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
        if "ethics_condition_check" in command.metadata:
            raise ValidationError(
                "metadata.ethics_condition_check is reserved for machine verification"
            )
        if "ethics_review_status_check" in command.metadata:
            raise ValidationError(
                "metadata.ethics_review_status_check is reserved for machine verification"
            )
        for reserved in (
            "run_artifact_root",
            "run_attestation_schema_path",
            "expected_attestation_schema_sha256",
            "artifact_integrity_missing_for_evidence",
            "run_payload_sha256",
            "sample_size_plan_check",
        ):
            if reserved in command.metadata:
                raise ValidationError(f"metadata.{reserved} is reserved for machine verification")
        if (
            "execution_handoff" in command.metadata
            and "workflow_adjudication_handoff" in command.metadata
        ):
            raise ValidationError(
                "a run cannot contain both execution and workflow adjudication handoffs"
            )
        protocol = self.repository.find_protocol(resolved, command.protocol_id)
        if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
            raise ValidationError("runs require a frozen, hash-committed protocol")
        if _protocol_commitment(protocol) != protocol.protocol_hash:
            raise ValidationError(
                "frozen protocol content no longer matches its hash commitment"
            )
        from research_machine.application.hypothesis_integrity import (
            validate_protocol_hypothesis_commitments,
        )
        validate_protocol_hypothesis_commitments(
            protocol,
            {
                hypothesis_id: self.repository.find_hypothesis(
                    resolved, hypothesis_id
                )
                for hypothesis_id in protocol.hypotheses_tested
            },
        )

        analysis_code_hash = require_sha256(
            command.analysis_code_hash, "analysis_code_hash"
        )
        allowed_analysis_hashes = {
            protocol.analysis_code_hash,
            *[step.implementation_sha256 for step in protocol.analysis_steps],
        }
        if analysis_code_hash not in allowed_analysis_hashes:
            raise ValidationError(
                "run analysis_code_hash does not match any frozen protocol analysis step"
            )
        # A module-level implementation digest can legitimately be shared by
        # several registered functions.  Hash equality therefore cannot tell a
        # primary estimator from another workflow step.  Once a protocol has a
        # frozen workflow, require the verified execution receipt to identify
        # and bind every component (including the primary estimate).
        if (
            protocol.analysis_steps
            and "execution_handoff" not in command.metadata
            and "workflow_adjudication_handoff" not in command.metadata
        ):
            raise ValidationError(
                "frozen workflow analyses require a verified execution_handoff"
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
        self._validate_run_datasets(
            protocol,
            datasets,
            all_datasets=self.repository.list_datasets(resolved),
        )
        from research_machine.application.ethics import (
            evaluate_ethics_clearance,
            validate_ethics_conditions_for_run,
        )
        ethics_review_status_check = evaluate_ethics_clearance(
            protocol,
            self.repository.list_ethics_review_events(resolved, protocol.protocol_id),
            completed,
        )
        ethics_condition_check = validate_ethics_conditions_for_run(
            protocol, datasets, completed
        )

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
        artifact_root = (
            require_canonical_text(command.artifact_root, "artifact_root")
            if command.artifact_root is not None
            else None
        )
        attestation_schema_path = (
            require_canonical_text(
                command.attestation_schema_path, "attestation_schema_path"
            )
            if command.attestation_schema_path is not None
            else None
        )
        verify_artifacts = any(
            value is not None
            for value in (
                artifact_root,
                attestation_schema_path,
                expected_attestation_schema_sha256,
            )
        ) or isinstance(
            command.metadata.get("replication_independence"), dict
        ) or isinstance(command.metadata.get("external_protocol_freeze"), dict)
        artifact_integrity = (
            verify_run_artifacts(
                outputs,
                artifact_root=artifact_root,
                actor=self.actor,
                analysis_code_hash=analysis_code_hash,
                run_metadata=command.metadata,
                attestation_schema_path=attestation_schema_path,
                expected_attestation_schema_sha256=(expected_attestation_schema_sha256),
            )
            if verify_artifacts
            else None
        )
        verified_handoff: dict[str, Any] | None = None
        execution_handoff = command.metadata.get("execution_handoff")
        if execution_handoff is not None:
            if not isinstance(execution_handoff, dict):
                raise ValidationError("execution_handoff must be an object")
            if artifact_root is None:
                raise ValidationError("execution_handoff requires artifact_root for receipt and output verification")
            try:
                receipt_sha256 = execution_handoff["receipt_sha256"]
            except KeyError as exc:
                raise ValidationError("execution_handoff lacks receipt_sha256") from exc
            from research_machine.addons.receipt import verify_execution_output
            verified_handoff = verify_execution_output(
                Path(artifact_root),
                require_sha256(receipt_sha256, "execution_handoff.receipt_sha256"),
            )
            if verified_handoff != execution_handoff:
                raise ValidationError("execution_handoff does not match the verified receipt and output bytes")
            receipt = verified_handoff["receipt"]
            binding = receipt.get("protocol_design_check")
            if not isinstance(binding, dict) or binding.get("status") != "passed":
                raise ValidationError("execution_handoff requires a passed protocol design binding")
            if (
                binding.get("protocol_id") != protocol.protocol_id
                or binding.get("protocol_hash") != protocol.protocol_hash
            ):
                raise ValidationError("execution_handoff is bound to a different protocol")
            if receipt.get("implementation", {}).get("sha256") != analysis_code_hash:
                raise ValidationError("execution_handoff implementation disagrees with the run analysis_code_hash")
            if dataset_ids != [binding.get("dataset_id")]:
                raise ValidationError("execution_handoff run must use exactly its bound dataset")
            receipt_output = receipt.get("output")
            if not isinstance(receipt_output, dict) or not any(
                artifact.locator == receipt_output.get("locator")
                and artifact.sha256 == receipt_output.get("sha256")
                and artifact.size_bytes == receipt_output.get("size_bytes")
                for artifact in outputs
            ):
                raise ValidationError("execution_handoff run output does not exactly include the verified result")
            try:
                specification = (
                    binding["executed_analysis_specification"]
                    if "analysis_step_contract" in binding
                    else binding["executed_analysis_semantics"]
                )
                canonical_binding = self.validate_analysis_execution(
                    binding["protocol_id"], specification,
                    binding.get("unit_structure", {}),
                    receipt["implementation"]["sha256"],
                    receipt["specification"]["sha256"], binding["dataset_id"],
                    receipt["input"]["sha256"], receipt["input"]["size_bytes"],
                    receipt["maximum_inference_level"], resolved,
                )
            except (KeyError, TypeError) as exc:
                raise ValidationError("execution_handoff lacks required protocol binding fields") from exc
            if canonical_binding != binding:
                raise ValidationError("execution_handoff protocol binding disagrees with canonical records")
            if "analysis_contract" in binding:
                contract = protocol.analysis_contract
                selection = receipt.get("registered_result_selection")
                if contract is None or not isinstance(selection, dict):
                    raise ValidationError("execution_handoff lacks registered result selection")
                expected_selection = {
                    "effect_estimate_path": contract.effect_estimate_path,
                    "uncertainty_path": contract.uncertainty_path,
                    "null_value": contract.null_value,
                    "support_rule": contract.support_rule,
                    "confidence_interval_validated": True,
                    "registered_confidence_level": contract.confidence_level,
                    "effect_estimate_sha256": _result_selection_sha256(_resolve_json_pointer(
                        verified_handoff["result"], contract.effect_estimate_path,
                        "effect_estimate_path",
                    )),
                    "uncertainty_sha256": _result_selection_sha256(_resolve_json_pointer(
                        verified_handoff["result"], contract.uncertainty_path,
                        "uncertainty_path",
                    )),
                }
                if selection != expected_selection:
                    raise ValidationError("execution_handoff registered result selection is invalid")
                from research_machine.addons.execution import validate_registered_information
                if receipt.get("registered_information_check") != validate_registered_information(
                    verified_handoff["result"], contract.to_dict()
                ):
                    raise ValidationError("execution_handoff registered information check is invalid")
        verified_adjudication: dict[str, Any] | None = None
        adjudication_handoff = command.metadata.get("workflow_adjudication_handoff")
        if adjudication_handoff is not None:
            if not isinstance(adjudication_handoff, dict):
                raise ValidationError("workflow_adjudication_handoff must be an object")
            if command.artifact_root is None:
                raise ValidationError("workflow_adjudication_handoff requires artifact_root")
            try:
                adjudication_receipt_sha256 = adjudication_handoff["receipt_sha256"]
            except KeyError as exc:
                raise ValidationError("workflow_adjudication_handoff lacks receipt_sha256") from exc
            from research_machine.addons.workflow import verify_holm_adjudication
            verified_adjudication = verify_holm_adjudication(
                self, Path(command.artifact_root),
                require_sha256(
                    adjudication_receipt_sha256,
                    "workflow_adjudication_handoff.receipt_sha256",
                ),
                resolved,
            )
            if verified_adjudication != adjudication_handoff:
                raise ValidationError(
                    "workflow_adjudication_handoff does not match recomputed canonical state"
                )
            adjudication = verified_adjudication["adjudication"]
            if (
                adjudication.get("protocol_id") != protocol.protocol_id
                or adjudication.get("protocol_hash") != protocol.protocol_hash
            ):
                raise ValidationError("workflow adjudication is bound to a different protocol")
            if analysis_code_hash != protocol.analysis_code_hash:
                raise ValidationError("composite run must retain the frozen primary analysis hash")
            if dataset_ids != [adjudication.get("observation_dataset_id")]:
                raise ValidationError("composite run must use its adjudicated observation dataset")
            adjudication_output = verified_adjudication["receipt"].get("output")
            if not isinstance(adjudication_output, dict) or not any(
                artifact.locator == adjudication_output.get("locator")
                and artifact.sha256 == adjudication_output.get("sha256")
                and artifact.size_bytes == adjudication_output.get("size_bytes")
                for artifact in outputs
            ):
                raise ValidationError("composite run output does not exactly include the verified adjudication")
        gates = validate_quality_gates(command.quality_gates)
        if verified_adjudication is not None:
            from research_machine.addons.workflow import composite_quality_gates
            expected_composite_gates = composite_quality_gates(
                verified_adjudication["adjudication"],
                verified_adjudication["receipt"]["output"]["sha256"],
            )
            if [gate.to_dict() for gate in gates] != expected_composite_gates:
                raise ValidationError(
                    "composite run quality gates must exactly equal the inherited canonical gate adjudication"
                )
        gates_by_id = {gate.gate_id: gate for gate in gates}
        output_hashes = {artifact.sha256 for artifact in outputs}
        verified_gate_result = (
            verified_handoff["result"] if verified_handoff is not None else
            verified_adjudication["adjudication"] if verified_adjudication is not None else
            None
        )
        verified_gate_output_sha256 = (
            verified_handoff["receipt"]["output"]["sha256"] if verified_handoff is not None else
            verified_adjudication["receipt"]["output"]["sha256"] if verified_adjudication is not None else
            None
        )
        for gate in gates:
            _reject_skipped_gate_structured_results(gate)
            prerequisites = gate.details.get("prerequisite_gate_ids", [])
            if not isinstance(prerequisites, list) or any(
                not isinstance(item, str) or not item.strip() for item in prerequisites
            ):
                raise ValidationError(
                    f"quality gate {gate.gate_id} prerequisite_gate_ids must be a list of non-blank gate IDs"
                )
            prerequisites = [
                require_canonical_text(
                    item, f"quality gate {gate.gate_id} prerequisite_gate_ids item"
                )
                for item in prerequisites
            ]
            if len(set(prerequisites)) != len(prerequisites):
                raise ValidationError(f"quality gate {gate.gate_id} has duplicate prerequisites")
            if gate.gate_id in prerequisites:
                raise ValidationError(f"quality gate {gate.gate_id} cannot require itself")
            if gate.status is QualityGateStatus.PASSED:
                evidence_sha256 = require_sha256(
                    gate.details.get("evidence_sha256"),
                    f"passed quality gate {gate.gate_id} evidence_sha256",
                )
                if evidence_sha256 not in output_hashes:
                    raise ValidationError(
                        f"passed quality gate {gate.gate_id} evidence_sha256 must reference a run output artifact"
                    )
                for prerequisite_id in prerequisites:
                    prerequisite = gates_by_id.get(prerequisite_id)
                    if prerequisite is None:
                        raise ValidationError(
                            f"passed quality gate {gate.gate_id} has an unknown prerequisite: {prerequisite_id}"
                        )
                    if prerequisite.status is not QualityGateStatus.PASSED:
                        raise ValidationError(
                            f"passed quality gate {gate.gate_id} requires prerequisite {prerequisite_id} to pass"
                        )
            _validate_preprocessing_conformance_gate(
                protocol=protocol,
                gate=gate,
                outputs=outputs,
                artifact_root=artifact_root,
                artifact_integrity=artifact_integrity,
            )
            _validate_instrument_inspection_gate(
                gate=gate,
                outputs=outputs,
                artifact_root=artifact_root,
                artifact_integrity=artifact_integrity,
            )
            _validate_stream_timing_assessment_gate(
                gate=gate,
                outputs=outputs,
                artifact_root=artifact_root,
                artifact_integrity=artifact_integrity,
            )
            _validate_temporal_order_assessment_gate(
                gate=gate,
                outputs=outputs,
                artifact_root=artifact_root,
                artifact_integrity=artifact_integrity,
            )
            _validate_canary_target_assessment_gate(
                protocol=protocol,
                gate=gate,
                outputs=outputs,
                artifact_root=artifact_root,
                verified_gate_result=verified_gate_result,
                verified_gate_output_sha256=verified_gate_output_sha256,
            )
        preprocessing_conformance_missing = bool(
            is_canonical_sha256(protocol.preprocessing_pipeline)
            and not any(
                isinstance(gate.details.get("preprocessing_conformance"), dict)
                for gate in gates
                if gate.status is not QualityGateStatus.SKIPPED
            )
        )
        if protocol.canary_target_plan is not None:
            canary_gate = gates_by_id.get(protocol.canary_target_plan.assessment_gate_id)
            if (
                canary_gate is not None
                and canary_gate.status is not QualityGateStatus.SKIPPED
                and "canary_target_assessment" not in canary_gate.details
            ):
                raise ValidationError(
                    "performed canary assessment gate requires a structured canary_target_assessment result"
                )
        controls_by_gate: dict[str, list[Any]] = {}
        for control in protocol.control_definitions:
            controls_by_gate.setdefault(control.evaluation_gate_id, []).append(control)
        for gate_id, controls in controls_by_gate.items():
            gate = gates_by_id.get(gate_id)
            if gate is None or gate.status is not QualityGateStatus.PASSED:
                continue  # Failed or absent evaluation remains an invalid run.
            results = gate.details.get("control_results")
            expected_control_ids = {control.control_id for control in controls}
            if not isinstance(results, dict) or set(results) != expected_control_ids:
                raise ValidationError(
                    f"passed control gate {gate_id} requires exact evaluations for: "
                    + ", ".join(sorted(expected_control_ids))
                )
            for control in controls:
                evaluation = results[control.control_id]
                required_fields = {
                    "observed_behavior", "interpretation", "matches_expected",
                    "evidence_sha256", "evidence_location",
                }
                allowed_fields = required_fields | {"selected_value_sha256"}
                if control.witness_contract is not None:
                    allowed_fields.add("witness")
                if (
                    not isinstance(evaluation, dict)
                    or not required_fields <= set(evaluation)
                    or set(evaluation) - allowed_fields
                ):
                    raise ValidationError(
                        f"passed control gate requires an exact evaluation for {control.control_id}"
                    )
                require_text(evaluation["observed_behavior"], "control observed_behavior")
                require_text(evaluation["interpretation"], "control interpretation")
                require_text(evaluation["evidence_location"], "control evidence_location")
                if type(evaluation["matches_expected"]) is not bool:
                    raise ValidationError("control matches_expected must be a boolean")
                digest = require_sha256(
                    evaluation["evidence_sha256"], "control evidence_sha256"
                )
                if digest not in output_hashes:
                    raise ValidationError(
                        "control evaluation evidence must reference a run output artifact"
                    )
                location_verified, selected_value = _resolve_json_artifact_location(
                    outputs,
                    artifact_root,
                    digest,
                    evaluation["evidence_location"],
                    f"control {control.control_id} evidence_location",
                )
                if location_verified:
                    selected_value_sha256 = _result_selection_sha256(selected_value)
                    supplied = evaluation.get("selected_value_sha256")
                    if supplied is not None and require_sha256(
                        supplied, f"control {control.control_id} selected_value_sha256"
                    ) != selected_value_sha256:
                        raise ValidationError(
                            "control selected_value_sha256 does not match the verified JSON value"
                        )
                    evaluation["selected_value_sha256"] = selected_value_sha256
                if (
                    not location_verified
                    and verified_gate_result is not None
                    and digest == verified_gate_output_sha256
                ):
                    location = evaluation["evidence_location"]
                    if not location.startswith("/"):
                        raise ValidationError(
                            "control evidence in the verified analysis output requires "
                            "an absolute JSON Pointer evidence_location"
                        )
                    selected_value = _resolve_json_pointer(
                        verified_gate_result, location,
                        f"control {control.control_id} evidence_location",
                    )
                    selected_value_sha256 = _result_selection_sha256(selected_value)
                    supplied = evaluation.get("selected_value_sha256")
                    if supplied is not None and require_sha256(
                        supplied, f"control {control.control_id} selected_value_sha256"
                    ) != selected_value_sha256:
                        raise ValidationError(
                            "control selected_value_sha256 does not match the verified analysis result value"
                        )
                    evaluation["selected_value_sha256"] = selected_value_sha256
                    location_verified = True
                if control.witness_contract is not None:
                    witness = evaluation.get("witness")
                    if not location_verified or not isinstance(selected_value, dict):
                        raise ValidationError(
                            f"control {control.control_id} witness requires retained, artifact-bound JSON object evidence"
                        )
                    validate_control_witness_evidence(
                        protocol=protocol,
                        control=control,
                        witness=witness,
                        matches_expected=evaluation["matches_expected"],
                    )
                    if selected_value != witness:
                        raise ValidationError(
                            f"control {control.control_id} witness does not match its retained JSON evidence"
                        )
        validity_checks_by_gate: dict[str, list[Any]] = {}
        for check in protocol.measurement_validity_checks:
            validity_checks_by_gate.setdefault(
                check.assessment_gate_id, []
            ).append(check)
        for gate_id, checks in validity_checks_by_gate.items():
            gate = gates_by_id.get(gate_id)
            if gate is None or gate.status is QualityGateStatus.SKIPPED:
                continue
            results = gate.details.get("measurement_validity_results")
            expected_check_ids = {check.check_id for check in checks}
            if not isinstance(results, dict) or set(results) != expected_check_ids:
                raise ValidationError(
                    f"performed measurement validity gate {gate_id} requires exact results for: "
                    + ", ".join(sorted(expected_check_ids))
                )
            for check in checks:
                result = results[check.check_id]
                required_fields = {
                    "observed_diagnostic", "interpretation", "assessment_status",
                    "evidence_type", "evidence_sha256", "evidence_location",
                }
                derived_fields = {"selected_value_sha256"}
                if (
                    not isinstance(result, dict)
                    or not required_fields <= set(result)
                    or set(result) - required_fields - derived_fields
                ):
                    raise ValidationError(
                        f"measurement validity result for {check.check_id} must contain exactly the documented fields"
                    )
                for name in (
                    "observed_diagnostic", "interpretation", "evidence_location",
                ):
                    require_text(result[name], f"measurement validity {name}")
                if result["evidence_type"] != check.evidence_type:
                    raise ValidationError(
                        "measurement validity evidence_type does not match the frozen protocol"
                    )
                allowed_statuses = {
                    "consistent_with_validity_claim", "contradicted_validity_claim",
                    "inconclusive",
                }
                if result["assessment_status"] not in allowed_statuses:
                    raise ValidationError(
                        "measurement validity result has an unsupported assessment_status"
                    )
                expected_status = {
                    QualityGateStatus.PASSED: "consistent_with_validity_claim",
                    QualityGateStatus.WARNING: "inconclusive",
                    QualityGateStatus.FAILED: "contradicted_validity_claim",
                }[gate.status]
                if result["assessment_status"] != expected_status:
                    raise ValidationError(
                        f"{gate.status.value} measurement validity gate requires {expected_status}"
                    )
                digest = require_sha256(
                    result["evidence_sha256"],
                    "measurement validity evidence_sha256",
                )
                if digest not in output_hashes:
                    raise ValidationError(
                        "measurement validity evidence must reference a run output artifact"
                    )
                location = result["evidence_location"]
                location_verified, selected_value = _resolve_json_artifact_location(
                    outputs,
                    command.artifact_root,
                    digest,
                    location,
                    f"measurement validity {check.check_id} evidence_location",
                )
                if location_verified:
                    selected_value_sha256 = _result_selection_sha256(selected_value)
                    supplied = result.get("selected_value_sha256")
                    if supplied is not None and require_sha256(
                        supplied, f"measurement validity {check.check_id} selected_value_sha256"
                    ) != selected_value_sha256:
                        raise ValidationError(
                            "measurement validity selected_value_sha256 does not match the verified JSON value"
                        )
                    result["selected_value_sha256"] = selected_value_sha256
                if (
                    not location_verified
                    and verified_gate_result is not None
                    and digest == verified_gate_output_sha256
                ):
                    if not location.startswith("/"):
                        raise ValidationError(
                            "measurement validity evidence in the verified analysis output requires an absolute JSON Pointer evidence_location"
                        )
                    selected_value = _resolve_json_pointer(
                        verified_gate_result, location,
                        f"measurement validity {check.check_id} evidence_location",
                    )
                    selected_value_sha256 = _result_selection_sha256(selected_value)
                    supplied = result.get("selected_value_sha256")
                    if supplied is not None and require_sha256(
                        supplied, f"measurement validity {check.check_id} selected_value_sha256"
                    ) != selected_value_sha256:
                        raise ValidationError(
                            "measurement validity selected_value_sha256 does not match the verified analysis result value"
                        )
                    result["selected_value_sha256"] = selected_value_sha256
        named_component_gates = {
            contract.evaluation_gate_id
            for contract in protocol.named_component_contracts
        }
        for gate_id in named_component_gates:
            gate = gates_by_id.get(gate_id)
            if gate is None or gate.status is QualityGateStatus.SKIPPED:
                continue
            validate_named_component_gate_metadata(
                protocol=protocol,
                gate=gate,
                output_hashes=output_hashes,
            )
            results = gate.details["named_component_results"]
            for contract in protocol.named_component_contracts:
                if contract.evaluation_gate_id != gate_id:
                    continue
                result = results[contract.contract_id]
                digest = result["evidence_sha256"]
                location = result["evidence_location"]
                location_verified, structured_evidence = _resolve_json_artifact_location(
                    outputs,
                    command.artifact_root,
                    digest,
                    location,
                    f"named component {contract.contract_id} evidence_location",
                )
                if (
                    not location_verified
                    and verified_gate_result is not None
                    and digest == verified_gate_output_sha256
                ):
                    if not location.startswith("/"):
                        raise ValidationError(
                            "named component evidence in the verified analysis output requires "
                            "an absolute JSON Pointer evidence_location"
                        )
                    structured_evidence = _resolve_json_pointer(
                        verified_gate_result,
                        location,
                        f"named component {contract.contract_id} evidence_location",
                    )
                    location_verified = True
                if not location_verified or not isinstance(structured_evidence, dict):
                    raise ValidationError(
                        "named component result requires retained, artifact-bound JSON mapping evidence"
                    )
                mapping_fields = {
                    "source_component_ids",
                    "source_selection_indices",
                    "relabeled_component_ids",
                    "relabeled_selection_indices",
                    "source_selected_component_ids",
                    "relabeled_selected_component_ids",
                }
                if any(
                    structured_evidence.get(field_name) != result[field_name]
                    for field_name in mapping_fields
                ):
                    raise ValidationError(
                        "named component result does not match its retained JSON mapping evidence"
                    )
                selected_value_sha256 = _result_selection_sha256(
                    structured_evidence
                )
                supplied = result.get("selected_value_sha256")
                if supplied is not None and require_sha256(
                    supplied,
                    f"named component {contract.contract_id} selected_value_sha256",
                ) != selected_value_sha256:
                    raise ValidationError(
                        "named component selected_value_sha256 does not match the verified JSON value"
                    )
                result["selected_value_sha256"] = selected_value_sha256
        contract = protocol.analysis_contract
        if contract is not None and contract.missingness_assessment_gate_id:
            gate = gates_by_id.get(contract.missingness_assessment_gate_id)
            if gate is not None and gate.status is not QualityGateStatus.SKIPPED:
                result = gate.details.get("missingness_assessment_result")
                required_fields = {
                    "observed_diagnostic", "interpretation", "assessment_status",
                    "assessment_kind", "evidence_sha256", "evidence_location",
                }
                derived_fields = {"selected_value_sha256"}
                if (
                    not isinstance(result, dict)
                    or not required_fields <= set(result)
                    or set(result) - required_fields - derived_fields
                ):
                    raise ValidationError(
                        "performed missingness assessment gate requires one exact result"
                    )
                require_text(
                    result["observed_diagnostic"],
                    "missingness assessment observed_diagnostic",
                )
                require_text(
                    result["interpretation"], "missingness assessment interpretation"
                )
                require_text(
                    result["evidence_location"],
                    "missingness assessment evidence_location",
                )
                if result["assessment_kind"] != contract.missingness_assessment_kind:
                    raise ValidationError(
                        "missingness assessment_kind does not match the frozen analysis contract"
                    )
                allowed_statuses = {
                    "consistent_with_assumption", "contradicted_assumption",
                    "inconclusive",
                }
                if result["assessment_status"] not in allowed_statuses:
                    raise ValidationError(
                        "missingness assessment has an unsupported assessment_status"
                    )
                if (
                    gate.status is QualityGateStatus.PASSED
                    and result["assessment_status"] != "consistent_with_assumption"
                ):
                    raise ValidationError(
                        "passed missingness assessment gate requires "
                        "consistent_with_assumption"
                    )
                if (
                    gate.status is QualityGateStatus.WARNING
                    and result["assessment_status"] != "inconclusive"
                ):
                    raise ValidationError(
                        "warning missingness assessment gate requires inconclusive"
                    )
                if (
                    gate.status is QualityGateStatus.FAILED
                    and result["assessment_status"] != "contradicted_assumption"
                ):
                    raise ValidationError(
                        "failed missingness assessment gate requires "
                        "contradicted_assumption"
                    )
                digest = require_sha256(
                    result["evidence_sha256"],
                    "missingness assessment evidence_sha256",
                )
                if digest not in output_hashes:
                    raise ValidationError(
                        "missingness assessment evidence must reference a run output artifact"
                    )
                location_verified, selected_value = _resolve_json_artifact_location(
                    outputs,
                    command.artifact_root,
                    digest,
                    result["evidence_location"],
                    "missingness assessment evidence_location",
                )
                if location_verified:
                    selected_value_sha256 = _result_selection_sha256(selected_value)
                    supplied = result.get("selected_value_sha256")
                    if supplied is not None and require_sha256(
                        supplied, "missingness assessment selected_value_sha256"
                    ) != selected_value_sha256:
                        raise ValidationError(
                            "missingness assessment selected_value_sha256 does not match the verified JSON value"
                        )
                    result["selected_value_sha256"] = selected_value_sha256
                if (
                    not location_verified
                    and verified_gate_result is not None
                    and digest == verified_gate_output_sha256
                ):
                    location = result["evidence_location"]
                    if not location.startswith("/"):
                        raise ValidationError(
                            "missingness evidence in the verified analysis output requires "
                            "an absolute JSON Pointer evidence_location"
                        )
                    selected_value = _resolve_json_pointer(
                        verified_gate_result, location,
                        "missingness assessment evidence_location",
                    )
                    selected_value_sha256 = _result_selection_sha256(selected_value)
                    supplied = result.get("selected_value_sha256")
                    if supplied is not None and require_sha256(
                        supplied, "missingness assessment selected_value_sha256"
                    ) != selected_value_sha256:
                        raise ValidationError(
                            "missingness assessment selected_value_sha256 does not match the verified analysis result value"
                        )
                    result["selected_value_sha256"] = selected_value_sha256
        if protocol.causal_claim:
            assumptions_by_gate: dict[str, list[dict[str, Any]]] = {}
            for assumption in protocol.causal_identification_audit["assumption_register"]:
                assumptions_by_gate.setdefault(
                    assumption["assessment_gate_id"], []
                ).append(assumption)
            allowed_assessment_statuses = {
                "consistent_with_assumption",
                "contradicted_assumption",
                "inconclusive",
            }
            for gate_id, assumptions in assumptions_by_gate.items():
                gate = gates_by_id.get(gate_id)
                if gate is None or gate.status is QualityGateStatus.SKIPPED:
                    continue  # Missing or unperformed assessment remains an invalid run.
                results = gate.details.get("causal_assumption_results")
                expected_categories = {item["category"] for item in assumptions}
                if not isinstance(results, dict) or set(results) != expected_categories:
                    raise ValidationError(
                        f"causal assessment gate {gate_id} requires exact results for: "
                        + ", ".join(sorted(expected_categories))
                    )
                observed_statuses: set[str] = set()
                for assumption in assumptions:
                    result = results[assumption["category"]]
                    required_fields = {
                        "observed_diagnostic", "interpretation", "assessment_status",
                        "assessment_kind", "evidence_sha256", "evidence_location",
                    }
                    derived_fields = {"selected_value_sha256"}
                    if (
                        not isinstance(result, dict)
                        or not required_fields <= set(result)
                        or set(result) - required_fields - derived_fields
                    ):
                        raise ValidationError(
                            f"causal assessment gate requires an exact result for {assumption['category']}"
                        )
                    require_text(
                        result["observed_diagnostic"],
                        f"causal assumption {assumption['category']} observed_diagnostic",
                    )
                    require_text(
                        result["interpretation"],
                        f"causal assumption {assumption['category']} interpretation",
                    )
                    require_text(
                        result["evidence_location"],
                        f"causal assumption {assumption['category']} evidence_location",
                    )
                    expected_assessment_kind = assumption.get(
                        "assessment_kind", "legacy_unclassified"
                    )
                    if result["assessment_kind"] != expected_assessment_kind:
                        raise ValidationError(
                            f"causal assumption {assumption['category']} assessment_kind "
                            "does not match the frozen assumption register"
                        )
                    if result["assessment_status"] not in allowed_assessment_statuses:
                        raise ValidationError(
                            f"causal assumption {assumption['category']} has an unsupported assessment_status"
                        )
                    observed_statuses.add(result["assessment_status"])
                    digest = require_sha256(
                        result["evidence_sha256"],
                        f"causal assumption {assumption['category']} evidence_sha256",
                    )
                    if digest not in output_hashes:
                        raise ValidationError(
                            "causal assumption assessment evidence must reference a run output artifact"
                        )
                    location = result["evidence_location"]
                    location_verified, selected_value = _resolve_json_artifact_location(
                        outputs,
                        command.artifact_root,
                        digest,
                        location,
                        f"causal assumption {assumption['category']} evidence_location",
                    )
                    if location_verified:
                        selected_value_sha256 = _result_selection_sha256(selected_value)
                        supplied = result.get("selected_value_sha256")
                        if supplied is not None and require_sha256(
                            supplied,
                            f"causal assumption {assumption['category']} selected_value_sha256",
                        ) != selected_value_sha256:
                            raise ValidationError(
                                "causal assumption selected_value_sha256 does not match the verified JSON value"
                            )
                        result["selected_value_sha256"] = selected_value_sha256
                    if (
                        not location_verified
                        and verified_gate_result is not None
                        and digest == verified_gate_output_sha256
                    ):
                        if not location.startswith("/"):
                            raise ValidationError(
                                "causal assumption evidence in the verified analysis output "
                                "requires an absolute JSON Pointer evidence_location"
                            )
                        selected_value = _resolve_json_pointer(
                            verified_gate_result, location,
                            f"causal assumption {assumption['category']} evidence_location",
                        )
                        selected_value_sha256 = _result_selection_sha256(selected_value)
                        supplied = result.get("selected_value_sha256")
                        if supplied is not None and require_sha256(
                            supplied,
                            f"causal assumption {assumption['category']} selected_value_sha256",
                        ) != selected_value_sha256:
                            raise ValidationError(
                                "causal assumption selected_value_sha256 does not match the verified analysis result value"
                            )
                        result["selected_value_sha256"] = selected_value_sha256
                if gate.status is QualityGateStatus.PASSED and observed_statuses != {
                    "consistent_with_assumption"
                }:
                    raise ValidationError(
                        f"passed causal assessment gate {gate_id} requires every result "
                        "to be consistent_with_assumption"
                    )
                if gate.status is QualityGateStatus.WARNING and (
                    "contradicted_assumption" in observed_statuses
                    or "inconclusive" not in observed_statuses
                ):
                    raise ValidationError(
                        f"warning causal assessment gate {gate_id} requires at least one "
                        "inconclusive result and no contradicted assumptions"
                    )
                if gate.status is QualityGateStatus.FAILED and (
                    "contradicted_assumption" not in observed_statuses
                ):
                    raise ValidationError(
                        f"failed causal assessment gate {gate_id} requires at least one "
                        "contradicted_assumption result"
                    )
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
            or preprocessing_conformance_missing
            or (
                artifact_integrity is not None and artifact_integrity.status != "passed"
            )
        )
        synthetic = command.synthetic or any(dataset.synthetic for dataset in datasets)
        workflow_component = verified_adjudication is None and bool(
            protocol.multiplicity_method == "holm"
            or (
                verified_handoff
                and isinstance(
                    verified_handoff["receipt"].get("protocol_design_check"), dict
                )
                and "analysis_step_contract" in verified_handoff["receipt"]["protocol_design_check"]
            )
        )
        deviation_disclosure = _validate_protocol_deviation_disclosure(
            command.metadata.get("protocol_deviation_disclosure")
        )
        result_exposure_disclosure = _validate_result_exposure_disclosure(
            command.metadata.get("result_exposure_disclosure")
        )
        registered_at = _parse_aware_timestamp(
            protocol.registration_timestamp,
            "protocol registration_timestamp",
        )
        for exposure in result_exposure_disclosure["exposures"]:
            if _parse_aware_timestamp(
                exposure["seen_at"], "result exposure seen_at"
            ) > registered_at:
                raise ValidationError(
                    "result exposure seen_at cannot follow protocol registration"
                )
        for deviation in deviation_disclosure["deviations"]:
            digest = deviation["evidence_sha256"]
            if digest not in output_hashes:
                raise ValidationError(
                    f"protocol deviation {deviation['deviation_id']} evidence must reference a run output artifact"
                )
            if verified_gate_result is not None and digest == verified_gate_output_sha256:
                location = deviation["evidence_location"]
                if not location.startswith("/"):
                    raise ValidationError(
                        "protocol deviation evidence in the verified analysis output requires an absolute JSON Pointer"
                    )
                _resolve_json_pointer(
                    verified_gate_result,
                    location,
                    f"protocol deviation {deviation['deviation_id']} evidence_location",
                )
        sample_size_plan_check: dict[str, Any] = {
            "status": "not_applicable",
            "reason": "protocol has no machine-recomputed sample_size_plan",
        }
        sample_size_plan_allows_evidence = True
        if protocol.sample_size_plan:
            calculation = protocol.sample_size_plan["calculation"]
            expected_analyzable = calculation["analyzable_n_per_group"]
            information_check = (
                verified_handoff["receipt"].get("registered_information_check")
                if verified_handoff is not None
                else verified_adjudication["adjudication"].get(
                    "primary_estimate", {}
                ).get("registered_information_check")
                if verified_adjudication is not None
                else None
            )
            execution_bound = bool(
                protocol.analysis_contract is not None
                and protocol.analysis_contract.minimum_analyzable_units
                == expected_analyzable
                and isinstance(information_check, dict)
                and information_check.get("status") == "passed"
                and information_check.get(
                    "registered_minimum_analyzable_units"
                )
                == expected_analyzable
                and information_check.get(
                    "observed_minimum_analyzable_units"
                )
                >= expected_analyzable
            )
            primary_uncertainty = (
                _resolve_json_pointer(
                    verified_handoff["result"],
                    protocol.analysis_contract.uncertainty_path,
                    "analysis_contract.uncertainty_path",
                )
                if verified_handoff is not None
                and protocol.analysis_contract is not None
                and isinstance(
                    verified_handoff["receipt"].get(
                        "registered_result_selection"
                    ), dict,
                )
                else verified_adjudication["adjudication"].get(
                    "primary_estimate", {}
                ).get("uncertainty")
                if verified_adjudication is not None
                else None
            )
            from research_machine.application.policies import (
                assess_attrition_achievement, assess_precision_achievement,
                assess_variance_assumption,
            )
            precision_achievement = assess_precision_achievement(
                protocol.sample_size_plan, primary_uncertainty
            )
            attrition_achievement = assess_attrition_achievement(
                protocol.sample_size_plan, information_check
            )
            observed_standard_deviation = (
                verified_handoff["result"].get("result", {}).get(
                    "pooled_within_group_standard_deviation"
                )
                if verified_handoff is not None
                else verified_adjudication["adjudication"].get(
                    "primary_estimate", {}
                ).get("observed_pooled_standard_deviation")
                if verified_adjudication is not None
                else None
            )
            variance_assumption = assess_variance_assumption(
                protocol.sample_size_plan, observed_standard_deviation
            )
            sample_size_plan_allows_evidence = execution_bound
            sample_size_plan_check = {
                "status": "passed" if execution_bound else "unbound",
                "strategy": protocol.sample_size_plan["strategy"],
                "target_hypothesis_id": protocol.sample_size_plan.get(
                    "target_hypothesis_id"
                ),
                "target_measurement_id": protocol.sample_size_plan.get(
                    "target_measurement_id"
                ),
                "measurement_unit": protocol.sample_size_plan.get(
                    "measurement_unit"
                ),
                "planning_target_sha256": protocol.sample_size_plan.get(
                    "planning_target_sha256"
                ),
                "specification_sha256": protocol.sample_size_plan[
                    "specification_sha256"
                ],
                "required_analyzable_units_per_group": expected_analyzable,
                "observed_minimum_analyzable_units_per_group": (
                    information_check.get("observed_minimum_analyzable_units")
                    if isinstance(information_check, dict)
                    else None
                ),
                "anticipated_attrition_fraction": calculation[
                    "anticipated_attrition_fraction"
                ],
                "registered_maximum_excluded_fraction": (
                    protocol.analysis_contract.maximum_excluded_fraction
                    if protocol.analysis_contract is not None else None
                ),
                "observed_excluded_fraction": (
                    information_check.get("observed_excluded_fraction")
                    if isinstance(information_check, dict) else None
                ),
                "precision_achievement": precision_achievement,
                "attrition_achievement": attrition_achievement,
                "variance_assumption": variance_assumption,
                "execution_information_check_verified": execution_bound,
                "scientific_interpretation_verified": False,
            }
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
            scientific_evidence_eligible=(
                not invalid
                and not synthetic
                and not workflow_component
                and deviation_disclosure["automatic_evidence_eligible"]
                and result_exposure_disclosure["automatic_evidence_eligible"]
                and artifact_integrity is not None
                and artifact_integrity.status == "passed"
                and sample_size_plan_allows_evidence
            ),
            summary=require_bounded_report_text(
                command.summary, "run summary", allow_empty=True
            ),
            synthetic=synthetic,
            metadata={
                **dict(command.metadata),
                "protocol_deviation_disclosure": deviation_disclosure,
                "result_exposure_disclosure": result_exposure_disclosure,
                "protocol_chronology": protocol_chronology,
                "sample_size_plan_check": sample_size_plan_check,
                **(
                    {"ethics_review_status_check": ethics_review_status_check}
                    if ethics_review_status_check
                    else {}
                ),
                **(
                    {"ethics_condition_check": ethics_condition_check}
                    if ethics_condition_check
                    else {}
                ),
                **({"missing_quality_gates": missing_gates} if missing_gates else {}),
                **(
                    {"preprocessing_conformance_missing": True}
                    if preprocessing_conformance_missing
                    else {}
                ),
                **(
                    {"artifact_integrity": artifact_integrity.to_dict()}
                    if artifact_integrity is not None
                    else {}
                ),
                **(
                    {"run_artifact_root": str(Path(artifact_root).expanduser().resolve())}
                    if artifact_integrity is not None and artifact_root is not None
                    else {}
                ),
                **(
                    {"run_attestation_schema_path": str(Path(attestation_schema_path).expanduser().resolve())}
                    if attestation_schema_path is not None
                    else {}
                ),
                **(
                    {"expected_attestation_schema_sha256": expected_attestation_schema_sha256}
                    if expected_attestation_schema_sha256 is not None
                    else {}
                ),
                **(
                    {"artifact_integrity_missing_for_evidence": True}
                    if artifact_integrity is None
                    else {}
                ),
                **({"workflow_component_only": True} if workflow_component else {}),
            },
        )
        from research_machine.application.run_integrity import run_payload_sha256
        run = replace(
            run,
            metadata={**run.metadata, "run_payload_sha256": run_payload_sha256(run)},
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
        causal_assumptions_by_gate: dict[str, list[dict[str, Any]]] = {}
        if protocol.causal_claim:
            for assumption in protocol.causal_identification_audit["assumption_register"]:
                causal_assumptions_by_gate.setdefault(
                    assumption["assessment_gate_id"], []
                ).append(assumption)
        temporal_order_gate_ids = {
            gate_id
            for gate_id, assumptions in causal_assumptions_by_gate.items()
            if any(
                assumption.get("category") == "temporal_order"
                for assumption in assumptions
            )
        }
        validity_checks_by_gate: dict[str, list[Any]] = {}
        for check in protocol.measurement_validity_checks:
            validity_checks_by_gate.setdefault(
                check.assessment_gate_id, []
            ).append(check)
        named_component_contracts_by_gate: dict[str, list[Any]] = {}
        for contract in protocol.named_component_contracts:
            named_component_contracts_by_gate.setdefault(
                contract.evaluation_gate_id, []
            ).append(contract)
        missingness_gate_id = (
            protocol.analysis_contract.missingness_assessment_gate_id
            if protocol.analysis_contract is not None
            else ""
        )
        preprocessing_pipeline_sha256 = (
            protocol.preprocessing_pipeline
            if is_canonical_sha256(protocol.preprocessing_pipeline)
            else None
        )
        canary_plan = protocol.canary_target_plan
        return {
            "schema_version": 1,
            "template_kind": "research-machine-run-record-v1",
            "control_plan": [control.to_dict() for control in protocol.control_definitions],
            "named_component_plan": [
                contract.to_dict()
                for contract in protocol.named_component_contracts
            ],
            "canary_target_plan": (
                canary_plan.to_dict() if canary_plan is not None else None
            ),
            "preprocessing_pipeline_commitment_sha256": preprocessing_pipeline_sha256,
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
                        "details": {
                            "evidence_sha256": "<hash of a listed run output artifact>",
                            "prerequisite_gate_ids": [],
                            **({"preprocessing_conformance": {
                                "locator": "<path below artifact_root to preprocessing-conformance.json>",
                                "sha256": "<hash of that preprocessing conformance record>",
                                "status": "<preprocessing_conformance_passed or preprocessing_conformance_failed>",
                                "registered_pipeline_sha256": preprocessing_pipeline_sha256,
                                "observed_pipeline_sha256": "<hash of the observed preprocessing pipeline declaration>",
                            }} if preprocessing_pipeline_sha256 is not None else {}),
                            **({"instrument_inspection": {
                                "locator": "<path below artifact_root to instrument-inspection.json>",
                                "sha256": "<hash of that instrument-inspection record>",
                                "status": "inspection_recorded",
                                "source_sha256": "<hash of the inspected immutable source bytes>",
                                "config_sha256": "<hash of the committed inspection config>",
                                "implementation_sha256": "<hash of the executed adapter implementation>",
                            }} if gate_id in temporal_order_gate_ids else {}),
                            **({"stream_timing_assessment": {
                                "locator": "<path below artifact_root to stream-timing-assessment.json>",
                                "sha256": "<hash of that stream-timing assessment record>",
                                "status": "<timing_feasibility_passed or timing_feasibility_failed>",
                                "inspection_sha256": "<hash of the trusted instrument-inspection record>",
                                "specification_sha256": "<hash of the registered stream-timing specification>",
                            }} if gate_id in temporal_order_gate_ids else {}),
                            **({"temporal_order_assessment": {
                                "locator": "<path below artifact_root to temporal-order-assessment.json>",
                                "sha256": "<hash of that temporal-order assessment record>",
                                "status": "<temporal_order_passed or temporal_order_failed>",
                                "timing_assessment_sha256": "<hash of the trusted stream-timing assessment>",
                                "specification_sha256": "<hash of the registered temporal-order specification>",
                            }} if gate_id in temporal_order_gate_ids else {}),
                            **({"canary_target_assessment": {
                                "plan_id": canary_plan.plan_id,
                                "assignment_artifact_sha256": canary_plan.assignment_artifact_sha256,
                                "revealed_target_id": "<target revealed from the frozen assignment artifact>",
                                "comparator_target_ids": [
                                    "<frozen candidate target used as a decoy or comparator>"
                                ],
                                "assessment_status": "<consistent_with_revealed_target, follows_comparator_or_decoy, follows_no_target, mixed, or inconclusive>",
                                "observed_pattern": "<observed target-following pattern>",
                                "interpretation": "<bounded interpretation; do not infer mechanism or intent>",
                                "evidence_sha256": "<hash of a listed run output artifact>",
                                "evidence_location": "<exact table, figure, section, record range, or JSON Pointer within that artifact>",
                                "selected_value_sha256": "<derived hash of the exact selected JSON value when evidence_location is machine-resolvable>",
                            }} if (
                                canary_plan is not None
                                and gate_id == canary_plan.assessment_gate_id
                            ) else {}),
                            **({"control_results": {
                            control.control_id: {
                                "observed_behavior": "",
                                "interpretation": "",
                                "matches_expected": None,
                                "evidence_sha256": "<hash of a listed run output artifact>",
                                "evidence_location": "<exact table, figure, section, record range, or JSON Pointer within that artifact>",
                                "selected_value_sha256": "<derived hash of the exact selected JSON value when evidence_location is machine-resolvable>",
                                **({"witness": {
                                    "control_id": control.control_id,
                                    "intervention_id": control.witness_contract.intervention_id,
                                    "measurement_id": control.witness_contract.measurement_id,
                                    "quantity": next(
                                        measurement.observable
                                        for measurement in protocol.measurement_definitions
                                        if measurement.measurement_id
                                        == control.witness_contract.measurement_id
                                    ),
                                    "unit": next(
                                        measurement.unit
                                        for measurement in protocol.measurement_definitions
                                        if measurement.measurement_id
                                        == control.witness_contract.measurement_id
                                    ),
                                    "comparator": control.witness_contract.comparator,
                                    "reference_value": control.witness_contract.reference_value,
                                    "observed_value": "<finite non-Boolean number>",
                                    "decision": None,
                                }} if control.witness_contract is not None else {}),
                            }
                            for control in protocol.control_definitions
                            if control.evaluation_gate_id == gate_id
                        }} if any(control.evaluation_gate_id == gate_id for control in protocol.control_definitions) else {}),
                            **({"causal_assumption_results": {
                                assumption["category"]: {
                                    "observed_diagnostic": "",
                                    "interpretation": "",
                                    "assessment_kind": assumption.get(
                                        "assessment_kind", "legacy_unclassified"
                                    ),
                                    "assessment_status": "<consistent_with_assumption if passed; inconclusive if warning; contradicted_assumption if failed>",
                                    "evidence_sha256": "<hash of a listed run output artifact>",
                                    "evidence_location": "<exact table, figure, section, record range, or JSON Pointer within that artifact>",
                                    "selected_value_sha256": "<derived hash of the exact selected JSON value when evidence_location is machine-resolvable>",
                                }
                                for assumption in causal_assumptions_by_gate[gate_id]
                            }} if gate_id in causal_assumptions_by_gate else {}),
                            **({"missingness_assessment_result": {
                                "observed_diagnostic": "",
                                "interpretation": "",
                                "assessment_kind": protocol.analysis_contract.missingness_assessment_kind,
                                "assessment_status": "<consistent_with_assumption if passed; inconclusive if warning; contradicted_assumption if failed>",
                                "evidence_sha256": "<hash of a listed run output artifact>",
                                "evidence_location": "<exact table, figure, section, record range, or JSON Pointer within that artifact>",
                                "selected_value_sha256": "<derived hash of the exact selected JSON value when evidence_location is machine-resolvable>",
                            }} if gate_id == missingness_gate_id else {}),
                            **({"measurement_validity_results": {
                                check.check_id: {
                                    "observed_diagnostic": "",
                                    "interpretation": "",
                                    "assessment_status": "<consistent_with_validity_claim if passed; inconclusive if warning; contradicted_validity_claim if failed>",
                                    "evidence_type": check.evidence_type,
                                    "evidence_sha256": "<hash of a listed run output artifact>",
                                    "evidence_location": "<exact table, figure, section, record range, or JSON Pointer within that artifact>",
                                    "selected_value_sha256": "<derived hash of the exact selected JSON value when evidence_location is machine-resolvable>",
                                }
                                for check in validity_checks_by_gate[gate_id]
                            }} if gate_id in validity_checks_by_gate else {}),
                            **({"named_component_results": {
                                contract.contract_id: {
                                    "source_component_ids": list(contract.component_ids),
                                    "source_selection_indices": [
                                        contract.component_ids.index(component_id)
                                        for component_id in contract.selected_component_ids
                                    ],
                                    "relabeled_component_ids": list(
                                        contract.relabeled_component_ids
                                    ),
                                    "relabeled_selection_indices": [
                                        contract.relabeled_component_ids.index(component_id)
                                        for component_id in contract.selected_component_ids
                                    ],
                                    "source_selected_component_ids": list(
                                        contract.selected_component_ids
                                    ),
                                    "relabeled_selected_component_ids": list(
                                        contract.selected_component_ids
                                    ),
                                    "assessment_status": "<consistent_with_named_selection if passed; inconclusive if warning; contradicted_named_selection if failed>",
                                    "observed_behavior": "",
                                    "interpretation": "",
                                    "evidence_sha256": "<hash of a listed run output artifact>",
                                    "evidence_location": "<exact JSON Pointer or location within that artifact>",
                                    "selected_value_sha256": "<derived hash of the exact selected JSON value when evidence_location is machine-resolvable>",
                                }
                                for contract in named_component_contracts_by_gate[gate_id]
                            }} if gate_id in named_component_contracts_by_gate else {}),
                        },
                    }
                    for gate_id in protocol.quality_requirements
                ],
                "summary": "",
                "synthetic": False,
                "metadata": {
                    "protocol_deviation_disclosure": {
                        "status": "no_deviations_declared",
                        "deviations": [],
                    },
                    "result_exposure_disclosure": {
                        "status": "no_relevant_output_seen",
                        "exposures": [],
                    },
                },
            },
            "instructions": [
                "Replace every angle-bracket placeholder with observed provenance.",
                "Add at least one output artifact with its real hash.",
                "Set every gate status from observed output; skipped or failed required gates make the run invalid.",
                "Every passed gate must cite one listed output artifact by details.evidence_sha256; declare prerequisite_gate_ids when its interpretation depends on other gates.",
                "For control evaluations, record observed behavior and interpretation separately from the frozen expectation; never copy an expectation as an observation.",
                "For a control with witness_contract, select the exact witness JSON object as evidence, report a finite scalar observed_value, and let the frozen comparator determine decision and matches_expected.",
                "A structured control witness strengthens observable custody and inspectability; it cannot prove that producing code was not hardcoded.",
                "For named-component evaluations, replace the suggested index maps with observed maps; the same frozen component names must be recovered after the adverse relabeling.",
                "For every causal-assumption assessment, identify the exact location within its cited output artifact; when citing the verified analysis result, use an absolute JSON Pointer that resolves in that result.",
                "For every performed measurement-validity check, record the observed diagnostic separately from interpretation, use the frozen evidence type, and cite the exact output location; a passed gate requires consistent_with_validity_claim, not proof of validity.",
                "When preprocessing_pipeline_commitment_sha256 is present, any preprocessing_conformance gate must cite a verified conformance record whose registered_pipeline_sha256 exactly matches it.",
                "For causal temporal-order gates, cite an instrument_inspection record whose source, config, implementation, and retained record hashes replay from current bytes; the inspection remains low-authority acquisition metadata and does not authenticate calibration or custody truth.",
                "For causal temporal-order gates, cite a stream_timing_assessment record whose inspection and specification hashes replay from current bytes; the assessment verifies timing feasibility without authenticating acquisition or calibration truth.",
                "For causal temporal-order gates, cite a temporal_order_assessment record whose timing and specification hashes replay from current bytes; the assessment classifies order without proving causality.",
                "For canary target assessments, reveal the target only from the frozen assignment artifact and report whether the pattern followed the revealed target, a comparator or decoy, no target, mixed targets, or remained inconclusive; this is not proof of adaptation, mechanism, or intent.",
                "Explicitly disclose every departure from the frozen protocol. A declared departure remains recordable but blocks automatic scientific-evidence eligibility.",
                "Explicitly disclose whether relevant candidate output was seen before registration. Favorable, full, unknown, or omitted exposure blocks automatic scientific-evidence eligibility.",
                "Run `research run preflight --record-file ...` before `research run record`.",
            ],
            "conclusion_ceiling": (
                "Template generation only. No execution, result, run, or ledger "
                "event is created."
            ),
        }

    def measurement_custody_template(
        self, protocol_id: str, inquiry_id: str | None = None
    ) -> dict[str, Any]:
        """Return a review-only custody skeleton derived from a frozen protocol."""
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        protocol = self.repository.find_protocol(resolved, protocol_id)
        if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
            raise ValidationError("measurement custody templates require a frozen protocol")
        if _protocol_commitment(protocol) != protocol.protocol_hash:
            raise ValidationError("frozen protocol content no longer matches its hash commitment")
        if not protocol.measurement_custody_requirements:
            raise ValidationError("protocol has no frozen measurement custody requirements")
        calibrations = []
        for criterion in protocol.calibration_acceptance_criteria:
            calibration = {
                "calibration_id": criterion.calibration_id,
                "criterion_id": criterion.criterion_id,
                "reference": "<reference artifact or standard>",
                "performed_at": "<ISO-8601 timestamp with UTC offset>",
                "result": "<observed calibration result, not the expected result>",
                "status": "<passed only if every frozen scalar or component bound is met>",
                "evidence_sha256": "<hash of a listed evidence artifact>",
            }
            if criterion.component_bounds:
                calibration["observed_components"] = [{
                    "component_id": component["component_id"],
                    "observed_value": "<finite numeric value>",
                    "observed_unit": component["unit"],
                } for component in criterion.component_bounds]
            else:
                calibration["observed_value"] = "<finite numeric value>"
                calibration["observed_unit"] = criterion.unit
            calibrations.append(calibration)
        return {
            "schema_version": 1,
            "template_kind": "research-machine-measurement-custody-v1",
            "template_only": True,
            "would_register_dataset": False,
            "protocol_id": protocol.protocol_id,
            "protocol_hash": protocol.protocol_hash,
            "frozen_calibration_criteria": [
                criterion.to_dict() for criterion in protocol.calibration_acceptance_criteria
            ],
            "receipt": {
                "receipt_id": "<stable custody receipt ID>",
                "raw_sources": [{"locator": "<path below the custody artifact root>",
                    "sha256": "<64 lowercase hexadecimal characters>",
                    "captured_at": "<ISO-8601 timestamp with UTC offset>",
                    "acquisition_method": "<instrument or acquisition procedure>"}],
                "transformations": [{"transformation_id": "<stable transformation ID>",
                    "version": "<transformation version>",
                    "performed_at": "<ISO-8601 timestamp with UTC offset>",
                    "implementation_locator": "<implementation path below artifact root>",
                    "implementation_sha256": "<implementation SHA-256>",
                    "input_sha256": "<raw or prior transformation output SHA-256>",
                    "output_locator": "<derived output path below artifact root>",
                    "output_sha256": "<derived output SHA-256>"}],
                "calibrations": calibrations,
                "quality_gates": [{"gate_id": gate_id, "status": "skipped",
                    "evaluated_at": "<ISO-8601 timestamp with UTC offset>",
                    "summary": "<observed gate result>",
                    "evidence_sha256": "<hash of a listed evidence artifact>",
                    "prerequisite_calibration_ids": [],
                    "prerequisite_artifact_sha256s": []}
                    for gate_id in protocol.measurement_custody_requirements],
                "derived_observations": [{"observation_id": "<stable observation ID>",
                    "definition": "<exact derived observation definition>",
                    "derived_at": "<ISO-8601 timestamp with UTC offset>",
                    "source_output_sha256": "<transformation output SHA-256>",
                    "quality_gate_ids": []}],
                "evidence_artifacts": [{"locator": "<path below the custody artifact root>",
                    "sha256": "<64 lowercase hexadecimal characters>"}],
            },
            "instructions": [
                "This is a review-only template; it records no dataset and asserts no gate pass.",
                "Replace every angle-bracket placeholder from observed files and events.",
                "Do not copy expected calibration behavior into observed result fields.",
                "List exact calibration and artifact prerequisites for each gate and exact clearing gates for each derived observation.",
                "Validate with measurement validate --artifact-root before protected dataset registration.",
            ],
            "conclusion_ceiling": "Template generation only. No custody claim, dataset, evidence, or ledger event is created.",
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
        hypotheses = self.repository.list_hypotheses(resolved)
        researchable_hypotheses = {
            hypothesis.hypothesis_id: hypothesis.workflow_state.value
            for hypothesis in hypotheses
            if hypothesis.workflow_state
            in {
                HypothesisWorkflowState.PENDING_REVIEW,
                HypothesisWorkflowState.ACTIVE,
            }
        }
        hypothesis_alternatives = _hypothesis_alternatives(hypotheses)
        candidates = validate_action_candidates(
            command.candidates,
            researchable_hypotheses,
            hypothesis_alternatives=hypothesis_alternatives,
        )
        for candidate in candidates:
            if candidate.depends_on:
                raise ValidationError(
                    "single next-action recommendations cannot rank dependent "
                    "actions; use next-action portfolio with completed_action_ids"
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
        recommendation = replace(
            recommendation,
            recommendation_payload_sha256=recommendation_payload_sha256(
                recommendation
            ),
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
        hypotheses = self.repository.list_hypotheses(resolved)
        researchable_hypotheses = {
            hypothesis.hypothesis_id: hypothesis.workflow_state.value
            for hypothesis in hypotheses
            if hypothesis.workflow_state
            in {
                HypothesisWorkflowState.PENDING_REVIEW,
                HypothesisWorkflowState.ACTIVE,
            }
        }
        hypothesis_alternatives = _hypothesis_alternatives(hypotheses)
        lanes = validate_action_lanes(command.lanes)
        candidates, completed = validate_portfolio_action_candidates(
            command.candidates,
            researchable_hypotheses,
            hypothesis_alternatives,
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
        recommendation = replace(
            recommendation,
            recommendation_payload_sha256=recommendation_payload_sha256(
                recommendation
            ),
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
        lesson = replace(
            lesson,
            lesson_payload_sha256=cross_lane_lesson_payload_sha256(lesson),
        )
        self.repository.save_cross_lane_lesson(resolved, lesson)
        self._event(
            resolved,
            "cross-lane-lesson.record",
            "cross_lane_lesson",
            lesson.lesson_id,
            lesson.to_dict(),
        )
        return replace(
            lesson,
            transfer_authority_status=CrossLaneTransferAuthorityStatus.CURRENT,
            current_transfer_authority=True,
        )

    def list_cross_lane_lessons(
        self, inquiry_id: str | None = None
    ) -> list[CrossLaneLesson]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self._verified_cross_lane_lessons(resolved)

    def _verified_cross_lane_lessons(
        self, inquiry_id: str
    ) -> list[CrossLaneLesson]:
        lessons = self.repository.list_cross_lane_lessons(inquiry_id)
        verified: list[CrossLaneLesson] = []
        for lesson in lessons:
            self.repository.verify_cross_lane_lesson_integrity(inquiry_id, lesson)
            commitment = validate_cross_lane_lesson_payload_commitment(lesson)
            validation = {
                "origin_lane_id": lesson.origin_lane_id,
                "target_lane_ids": lesson.target_lane_ids,
                "origin_artifact_locator": lesson.origin_artifact_locator,
                "origin_artifact_sha256": lesson.origin_artifact_sha256,
                "origin_integrity_status": lesson.origin_integrity_status,
                "observation": lesson.observation,
                "failure_class": lesson.failure_class,
                "strongest_alternative_explanation": (
                    lesson.strongest_alternative_explanation
                ),
                "challenged_invariant": lesson.challenged_invariant,
                "first_permitted_future_versions": (
                    lesson.first_permitted_future_versions
                ),
                "prohibited_retroactive_targets": (
                    lesson.prohibited_retroactive_targets
                ),
                "proposed_repair": lesson.proposed_repair,
                "repair_falsifier": lesson.repair_falsifier,
                "conclusion_ceiling": lesson.conclusion_ceiling,
            }
            try:
                validate_cross_lane_lesson(**validation)
            except ValidationError as current_error:
                findings = validate_historical_cross_lane_lesson_structure(
                    **validation
                )
                if not findings:
                    raise current_error
                status = (
                    CrossLaneTransferAuthorityStatus.LEGACY_REPORT_PROSE
                    if commitment is not None
                    else CrossLaneTransferAuthorityStatus.LEGACY_PROSE_UNCOMMITTED
                )
                verified.append(
                    replace(
                        lesson,
                        transfer_authority_status=status,
                        current_transfer_authority=False,
                        report_prose_findings=findings,
                    )
                )
                continue
            if commitment is None:
                verified.append(
                    replace(
                        lesson,
                        transfer_authority_status=(
                            CrossLaneTransferAuthorityStatus.LEGACY_UNCOMMITTED
                        ),
                        current_transfer_authority=False,
                    )
                )
            else:
                verified.append(
                    replace(
                        lesson,
                        transfer_authority_status=(
                            CrossLaneTransferAuthorityStatus.CURRENT
                        ),
                        current_transfer_authority=True,
                    )
                )
        return verified

    def list_recommendations(
        self, inquiry_id: str | None = None
    ) -> list[ActionRecommendation]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        return self._verified_recommendations(resolved)

    def _verified_recommendations(
        self, inquiry_id: str
    ) -> list[ActionRecommendation]:
        recommendations = self.repository.list_recommendations(inquiry_id)
        hypothesis_alternatives = _hypothesis_alternatives(
            self.repository.list_hypotheses(inquiry_id)
        )
        for recommendation in recommendations:
            if (
                recommendation.recommendation_payload_sha256
                or not self.repository.has_legacy_recommendation_event(
                    inquiry_id, recommendation.recommendation_id
                )
            ):
                verify_recommendation_score_replay(
                    recommendation,
                    hypothesis_alternatives=hypothesis_alternatives,
                )
            else:
                self.repository.verify_legacy_recommendation_integrity(
                    inquiry_id, recommendation
                )
        return recommendations

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
        effect_estimate = normalize_text(command.effect_estimate, "effect_estimate")
        uncertainty_input = normalize_text(command.uncertainty, "uncertainty")
        analysis_output_sha256 = normalize_text(command.analysis_output_sha256, "analysis_output_sha256")
        effect_estimate_path = normalize_text(command.effect_estimate_path, "effect_estimate_path")
        uncertainty_path = normalize_text(command.uncertainty_path, "uncertainty_path")
        analysis_claim_ceiling = ""
        method_maximum_inference_level: str | None = None
        result_direction_check = "not_applicable"
        evidence_created_at = self.clock()
        admission_checks: dict[str, Any] = {}
        composite_permitted_claim_level: ClaimLevel | None = None
        composite_expected_scope = ""
        if command.run_id:
            run = self.repository.find_run(resolved, command.run_id)
            from research_machine.application.run_integrity import (
                validate_run_payload_commitment,
            )
            validate_run_payload_commitment(run)
            protocol = self.repository.find_protocol(resolved, run.protocol_id)
            from research_machine.application.hypothesis_integrity import (
                validate_protocol_hypothesis_commitments,
            )
            validate_protocol_hypothesis_commitments(
                protocol,
                {
                    hypothesis_id: self.repository.find_hypothesis(
                        resolved, hypothesis_id
                    )
                    for hypothesis_id in protocol.hypotheses_tested
                },
            )
            datasets = [
                self.repository.find_dataset(resolved, dataset_id)
                for dataset_id in run.dataset_ids
            ]
            if run.protocol_hash != protocol.protocol_hash or _protocol_commitment(
                protocol
            ) != protocol.protocol_hash:
                raise ValidationError(
                    "evidence admission requires the run's exact frozen protocol commitment"
                )
            if (
                not command.exploratory
                and not typed_result_exposure_allows_evidence(run.metadata)
            ):
                legacy_exposure = (
                    " Legacy structured metadata explicitly records favorable "
                    "pre-registration output."
                    if declares_legacy_pre_registration_result_exposure(run.metadata)
                    else ""
                )
                raise ValidationError(
                    "confirmatory evidence requires a typed no-relevant-output-seen "
                    f"result exposure disclosure.{legacy_exposure}"
                )
            if run.scientific_evidence_eligible:
                self._validate_run_datasets(
                    protocol,
                    datasets,
                    all_datasets=self.repository.list_datasets(resolved),
                )
                from research_machine.application.run_integrity import (
                    reverify_run_artifacts,
                )
                current_run_integrity = reverify_run_artifacts(run)
                from research_machine.application.ethics import (
                    evaluate_ethics_clearance,
                )
                ethics_check = evaluate_ethics_clearance(
                    protocol,
                    self.repository.list_ethics_review_events(
                        resolved, protocol.protocol_id
                    ),
                    _parse_aware_timestamp(
                        evidence_created_at, "evidence admission time"
                    ),
                )
                admission_checks = {
                    "check_version": 1,
                    "checked_at": evidence_created_at,
                    "protocol_id": protocol.protocol_id,
                    "protocol_hash": protocol.protocol_hash,
                    "dataset_ids": list(run.dataset_ids),
                    "dataset_current_bytes_status": (
                        "verified" if datasets else "not_applicable"
                    ),
                    "run_output_current_bytes_verified": True,
                    "run_artifact_set_sha256": current_run_integrity[
                        "artifact_set_sha256"
                    ],
                    "ethics_review_status_check": ethics_check,
                    "scientific_interpretation_verified": False,
                }
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
            handoff = run.metadata.get("execution_handoff")
            if isinstance(handoff, dict):
                try:
                    output_sha256 = handoff["receipt"]["output"]["sha256"]
                    verified_result = handoff["result"]
                except (KeyError, TypeError) as exc:
                    raise ValidationError("execution-backed run has an incomplete verified result handoff") from exc
                if require_sha256(analysis_output_sha256, "analysis_output_sha256") != output_sha256:
                    raise ValidationError("evidence analysis_output_sha256 does not match the recorded run output")
                if protocol.analysis_contract is None:
                    raise ValidationError("execution-backed evidence requires a frozen analysis contract")
                if effect_estimate_path != protocol.analysis_contract.effect_estimate_path:
                    raise ValidationError("effect_estimate_path does not match the frozen analysis contract")
                if uncertainty_path != protocol.analysis_contract.uncertainty_path:
                    raise ValidationError("uncertainty_path does not match the frozen analysis contract")
                selected_effect_value = _resolve_json_pointer(
                    verified_result, effect_estimate_path, "effect_estimate_path"
                )
                selected_effect = _canonical_result_value(selected_effect_value)
                selected_uncertainty_value = _resolve_json_pointer(
                    verified_result, uncertainty_path, "uncertainty_path"
                )
                selected_uncertainty = _canonical_result_value(selected_uncertainty_value)
                if effect_estimate and effect_estimate != selected_effect:
                    raise ValidationError("effect_estimate does not match its verified result selector")
                if uncertainty_input and uncertainty_input != selected_uncertainty:
                    raise ValidationError("uncertainty does not match its verified result selector")
                effect_estimate = selected_effect
                uncertainty_input = selected_uncertainty
                analysis_claim_ceiling = require_text(
                    verified_result.get("claim_ceiling"), "verified analysis claim_ceiling"
                )
                method_maximum_inference_level = require_text(
                    verified_result.get("maximum_inference_level"),
                    "verified analysis maximum_inference_level",
                )
                result_direction_check = validate_result_direction(
                    expected_direction=hypothesis.expected_effect_direction,
                    evidence_direction=command.direction,
                    effect=selected_effect_value,
                    uncertainty=selected_uncertainty_value,
                    null_value=protocol.analysis_contract.null_value,
                    support_rule=protocol.analysis_contract.support_rule,
                    equivalence_margin=(
                        protocol.conclusion_contract.smallest_effect_size_of_interest
                        if protocol.conclusion_contract is not None else None
                    ),
                )
                if (
                    protocol.conclusion_contract is not None
                    and run.scientific_evidence_eligible
                ):
                    direct_conclusion = adjudicate_conclusion_contract(
                        conclusion=protocol.conclusion_contract,
                        analysis=protocol.analysis_contract,
                        hypothesis=hypothesis,
                        effect=selected_effect_value,
                        uncertainty=selected_uncertainty_value,
                    )
                    if command.direction.value != direct_conclusion[
                        "adjudicated_evidence_direction"
                    ]:
                        raise ValidationError(
                            "evidence direction must equal the frozen conclusion disposition"
                        )
                    direct_scope = direct_conclusion["scope"]
                    expected_scope = (
                        f"Population: {direct_scope['population']}; "
                        f"Setting: {direct_scope['setting']}; "
                        f"Time window: {direct_scope['time_window']}"
                    )
                    if normalize_text(command.scope, "scope") != expected_scope:
                        raise ValidationError(
                            "evidence scope must exactly retain the frozen conclusion population, setting, and time window"
                        )
                    if command.higher_level_conclusions_unsupported != direct_conclusion[
                        "higher_level_conclusions_unsupported"
                    ]:
                        raise ValidationError(
                            "evidence must exactly retain the frozen unsupported conclusions"
                        )
                    composite_expected_scope = expected_scope
                    composite_permitted_claim_level = ClaimLevel(
                        direct_conclusion["permitted_claim_level"]
                    )
                    result_direction_check += "; prospective_conclusion_contract_checked"
            else:
                composite_handoff = run.metadata.get("workflow_adjudication_handoff")
                if isinstance(composite_handoff, dict):
                    try:
                        output_sha256 = composite_handoff["receipt"]["output"]["sha256"]
                        verified_result = composite_handoff["adjudication"]
                        primary_result = verified_result["primary_estimate"]
                        family = verified_result["confirmatory_family"]
                    except (KeyError, TypeError) as exc:
                        raise ValidationError(
                            "composite run has an incomplete verified adjudication handoff"
                        ) from exc
                    if require_sha256(
                        analysis_output_sha256, "analysis_output_sha256"
                    ) != output_sha256:
                        raise ValidationError(
                            "evidence analysis_output_sha256 does not match the composite run output"
                        )
                    if protocol.analysis_contract is None:
                        raise ValidationError(
                            "composite evidence requires a frozen analysis contract"
                        )
                    expected_effect_path = "/primary_estimate/effect_estimate"
                    expected_uncertainty_path = "/primary_estimate/uncertainty"
                    if effect_estimate_path != expected_effect_path:
                        raise ValidationError(
                            "effect_estimate_path must select the adjudicated primary estimate"
                        )
                    if uncertainty_path != expected_uncertainty_path:
                        raise ValidationError(
                            "uncertainty_path must select the adjudicated primary uncertainty"
                        )
                    selected_effect_value = _resolve_json_pointer(
                        verified_result, effect_estimate_path, "effect_estimate_path"
                    )
                    selected_uncertainty_value = _resolve_json_pointer(
                        verified_result, uncertainty_path, "uncertainty_path"
                    )
                    selected_effect = _canonical_result_value(selected_effect_value)
                    selected_uncertainty = _canonical_result_value(selected_uncertainty_value)
                    if effect_estimate and effect_estimate != selected_effect:
                        raise ValidationError(
                            "effect_estimate does not match the adjudicated primary estimate"
                        )
                    if uncertainty_input and uncertainty_input != selected_uncertainty:
                        raise ValidationError(
                            "uncertainty does not match the adjudicated primary uncertainty"
                        )
                    effect_estimate = selected_effect
                    uncertainty_input = selected_uncertainty
                    analysis_claim_ceiling = require_text(
                        verified_result.get("claim_ceiling"),
                        "workflow adjudication claim_ceiling",
                    )
                    result_direction_check = validate_result_direction(
                        expected_direction=hypothesis.expected_effect_direction,
                        evidence_direction=command.direction,
                        effect=selected_effect_value,
                        uncertainty=selected_uncertainty_value,
                        null_value=protocol.analysis_contract.null_value,
                        support_rule=protocol.analysis_contract.support_rule,
                        equivalence_margin=(
                            protocol.conclusion_contract.smallest_effect_size_of_interest
                            if protocol.conclusion_contract is not None else None
                        ),
                    )
                    primary_decisions = [
                        item for item in family.get("decisions", [])
                        if isinstance(item, dict)
                        and item.get("hypothesis_id") == command.hypothesis_id
                        and item.get("measurement_id") == protocol.analysis_contract.primary_measurement_id
                        and item.get("outcome") == protocol.primary_outcome
                    ] if isinstance(family, dict) else []
                    if len(primary_decisions) != 1:
                        raise ValidationError(
                            "composite evidence lacks one exact adjusted primary decision"
                        )
                    if (
                        command.direction is EvidenceDirection.SUPPORTS
                        and primary_decisions[0].get("reject_at_alpha") is not True
                    ):
                        raise ValidationError(
                            "supporting evidence requires rejection by the adjusted primary decision"
                        )
                    conclusion = verified_result.get("conclusion")
                    if not isinstance(conclusion, dict):
                        raise ValidationError("composite evidence lacks its frozen conclusion adjudication")
                    if command.direction.value != conclusion.get("adjudicated_evidence_direction"):
                        raise ValidationError(
                            "evidence direction must equal the frozen composite conclusion disposition"
                        )
                    conclusion_scope = conclusion.get("scope")
                    if not isinstance(conclusion_scope, dict):
                        raise ValidationError("composite evidence lacks its frozen conclusion scope")
                    expected_scope = (
                        f"Population: {conclusion_scope.get('population')}; "
                        f"Setting: {conclusion_scope.get('setting')}; "
                        f"Time window: {conclusion_scope.get('time_window')}"
                    )
                    if normalize_text(command.scope, "scope") != expected_scope:
                        raise ValidationError(
                            "composite evidence scope must exactly retain the frozen conclusion population, setting, and time window"
                        )
                    composite_expected_scope = expected_scope
                    try:
                        composite_permitted_claim_level = ClaimLevel(
                            conclusion["permitted_claim_level"]
                        )
                    except (KeyError, ValueError) as exc:
                        raise ValidationError(
                            "composite evidence has an invalid permitted claim level"
                        ) from exc
                    if command.higher_level_conclusions_unsupported != conclusion.get(
                        "higher_level_conclusions_unsupported"
                    ):
                        raise ValidationError(
                            "composite evidence must exactly retain the frozen unsupported conclusions"
                        )
                    result_direction_check += "; multiplicity_adjusted_primary_decision_checked"
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
        claim = None
        if command.claim_id:
            claims_by_id = {
                item.claim_id: item for item in self.repository.load_claims(resolved)
            }
            claim = claims_by_id.get(command.claim_id)
            if claim is None:
                raise NotFoundError(f"claim {command.claim_id} does not exist")
        if composite_permitted_claim_level is not None:
            if claim is None:
                raise ValidationError(
                    "composite evidence requires an exact claim bound by the conclusion contract"
                )
            if claim.level is not composite_permitted_claim_level:
                raise ValidationError(
                    "composite evidence claim level exceeds or differs from the frozen permitted level"
                )
            if claim.scope != composite_expected_scope:
                raise ValidationError(
                    "composite evidence claim scope must exactly match the frozen conclusion scope"
                )
        if admission_checks:
            from research_machine.application.claim_integrity import (
                claim_scientific_sha256,
            )
            admission_checks["claim_scientific_sha256"] = (
                claim_scientific_sha256(claim) if claim is not None else None
            )
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
            uncertainty=uncertainty_input,
            controls_passed=command.controls_passed,
            controls_failed=command.controls_failed,
            higher_level_conclusions_unsupported=(
                command.higher_level_conclusions_unsupported
            ),
            validation_tags=command.validation_tags,
        )
        replicated_run: ResearchRun | None = None
        if run is not None and protocol is not None:
            gates_by_id = {gate.gate_id: gate for gate in run.quality_gates}
            expected_controls: set[str] = set()
            unexpected_controls: set[str] = set()
            for control in protocol.control_definitions:
                gate = gates_by_id.get(control.evaluation_gate_id)
                results = gate.details.get("control_results", {}) if gate else {}
                evaluation = results.get(control.control_id, {}) if isinstance(results, dict) else {}
                if isinstance(evaluation, dict):
                    if evaluation.get("matches_expected") is True:
                        expected_controls.add(control.registered_control)
                    elif evaluation.get("matches_expected") is False:
                        unexpected_controls.add(control.registered_control)
            if protocol.control_definitions:
                if len(set(controls_passed)) != len(controls_passed) or len(
                    set(controls_failed)
                ) != len(controls_failed):
                    raise ValidationError(
                        "evidence control disclosures must not contain duplicates"
                    )
                if set(controls_passed) != expected_controls or set(
                    controls_failed
                ) != unexpected_controls:
                    raise ValidationError(
                        "evidence controls_passed and controls_failed must exactly partition "
                        "the frozen controls by their recorded run evaluations"
                    )
        if run is not None:
            replicated_run_id = run.metadata.get("replicates_run_id")
            if replicated_run_id is not None:
                replicated_run = self.repository.find_run(
                    resolved, require_text(replicated_run_id, "replicates_run_id")
                )
        measurement_validity_check_ids: list[str] = []
        if run is not None and protocol is not None:
            gates_by_id = {gate.gate_id: gate for gate in run.quality_gates}
            for check in protocol.measurement_validity_checks:
                gate = gates_by_id.get(check.assessment_gate_id)
                results = (
                    gate.details.get("measurement_validity_results", {})
                    if gate is not None else {}
                )
                result = results.get(check.check_id) if isinstance(results, dict) else None
                if (
                    isinstance(result, dict)
                    and result.get("assessment_status")
                    == "consistent_with_validity_claim"
                ):
                    measurement_validity_check_ids.append(check.check_id)
        if (
            claim is not None
            and claim.level is ClaimLevel.MEASUREMENT_VALIDITY
            and command.direction is EvidenceDirection.SUPPORTS
            and not measurement_validity_check_ids
        ):
            raise ValidationError(
                "supporting evidence for a measurement-validity claim requires an exact frozen validity check with an artifact-bound consistent result"
            )
        validate_validation_tag_context(
            tags=validation_tags,
            direction=command.direction,
            hypothesis=hypothesis,
            exploratory=command.exploratory,
            protocol=protocol,
            run=run,
            datasets=datasets,
            controls_passed=controls_passed,
            replicated_run=replicated_run,
            claim=claim,
            method_maximum_inference_level=method_maximum_inference_level,
        )
        evidence = EvidenceRecord(
            evidence_id=f"evd-{self.token()}",
            hypothesis_id=command.hypothesis_id,
            claim_id=command.claim_id,
            direction=command.direction,
            summary=require_bounded_evidence_summary(command.summary),
            dataset_id=dataset.dataset_id if dataset else command.dataset_id,
            analysis_id=analysis_id,
            created_at=evidence_created_at,
            protocol_id=protocol.protocol_id if protocol else None,
            run_id=run.run_id if run else None,
            scientific_evidence_eligible=(
                run.scientific_evidence_eligible if run else False
            ),
            effect_estimate=effect_estimate,
            uncertainty=uncertainty,
            scope=scope,
            controls_passed=controls_passed,
            controls_failed=controls_failed,
            higher_level_conclusions_unsupported=conclusion_ceiling,
            validation_tags=validation_tags,
            measurement_validity_check_ids=measurement_validity_check_ids,
            exploratory=command.exploratory,
            analysis_output_sha256=analysis_output_sha256,
            effect_estimate_path=effect_estimate_path,
            uncertainty_path=uncertainty_path,
            analysis_claim_ceiling=analysis_claim_ceiling,
            result_direction_check=result_direction_check,
            admission_checks=admission_checks,
        )
        if admission_checks:
            from research_machine.application.evidence_admission import (
                evidence_payload_sha256,
            )
            evidence = replace(
                evidence,
                admission_checks={
                    **admission_checks,
                    "evidence_payload_sha256": evidence_payload_sha256(evidence),
                },
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

    def export_sherlock_evidence(
        self, command: ExportSherlockEvidence, inquiry_id: str | None = None
    ) -> dict[str, Any]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        self.show_inquiry(resolved)
        from research_machine.application.sherlock_bridge import (
            bridge_receipt_for_summary,
            build_sherlock_evidence_summary,
            validate_sherlock_export_options,
            write_sherlock_evidence_export,
        )

        (
            evidence_id,
            sherlock_case_id,
            sherlock_kind,
            sherlock_id,
            sherlock_artifact_sha256,
        ) = validate_sherlock_export_options(
            evidence_id=command.evidence_id,
            sherlock_case_id=command.sherlock_case_id,
            sherlock_kind=command.sherlock_kind,
            sherlock_id=command.sherlock_id,
            sherlock_artifact_sha256=command.sherlock_artifact_sha256,
        )
        matches = [
            item
            for item in self.repository.list_evidence(resolved)
            if item.evidence_id == evidence_id
        ]
        if not matches:
            raise NotFoundError(f"evidence {evidence_id} does not exist")
        evidence = matches[0]
        inquiry = self.repository.load_inquiry(resolved)
        claims = {claim.claim_id: claim for claim in self.repository.load_claims(resolved)}
        claim = claims.get(evidence.claim_id) if evidence.claim_id else None
        hypothesis = self.repository.find_hypothesis(resolved, evidence.hypothesis_id)
        dataset = (
            self.repository.find_dataset(resolved, evidence.dataset_id)
            if evidence.dataset_id
            else None
        )
        protocol = (
            self.repository.find_protocol(resolved, evidence.protocol_id)
            if evidence.protocol_id
            else None
        )
        run = self.repository.find_run(resolved, evidence.run_id) if evidence.run_id else None
        created_at = self.clock()
        summary = build_sherlock_evidence_summary(
            inquiry=inquiry,
            evidence=evidence,
            hypothesis=hypothesis,
            claim=claim,
            dataset=dataset,
            protocol=protocol,
            run=run,
            status_events=self.list_evidence_status_events(
                resolved, evidence_id=evidence.evidence_id
            ),
            created_at=created_at,
        )
        summary_bytes = (
            json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        summary_sha256 = hashlib.sha256(summary_bytes).hexdigest()
        summary_locator = "faraday-summary.json"
        receipt = bridge_receipt_for_summary(
            evidence=evidence,
            run=run,
            summary_sha256=summary_sha256,
            summary_locator=summary_locator,
            created_at=created_at,
            receipt_id=f"faraday-sherlock-link-{self.token()}",
            sherlock_case_id=sherlock_case_id,
            sherlock_kind=sherlock_kind,
            sherlock_id=sherlock_id,
            sherlock_artifact_sha256=sherlock_artifact_sha256,
        )
        result = write_sherlock_evidence_export(
            output_dir=Path(command.output_dir).expanduser().resolve(),
            summary=summary,
            receipt=receipt,
        )
        self._event(
            resolved,
            "sherlock.evidence.export",
            "bridge_export",
            evidence.evidence_id,
            {
                **result,
                "sherlock_case_id": sherlock_case_id,
                "sherlock_kind": sherlock_kind,
                "sherlock_id": sherlock_id,
                "authority_boundary": receipt["authority_boundary"],
            },
        )
        return {**result, "receipt": receipt}

    def record_evidence_status_event(
        self, command: RecordEvidenceStatusEvent, inquiry_id: str | None = None
    ) -> EvidenceStatusEvent:
        """Append an artifact-backed correction state without rewriting evidence."""
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        evidence_id = require_text(command.evidence_id, "evidence_id")
        if evidence_id != command.evidence_id:
            raise ValidationError(
                "evidence_id must be canonical without surrounding whitespace"
            )
        if command.event_id is not None:
            event_id = require_text(command.event_id, "event_id")
            if event_id != command.event_id:
                raise ValidationError(
                    "event_id must be canonical without surrounding whitespace"
                )
        else:
            event_id = None
        if command.supersedes_event_id is not None:
            supersedes_event_id = require_text(
                command.supersedes_event_id, "supersedes_event_id"
            )
            if supersedes_event_id != command.supersedes_event_id:
                raise ValidationError(
                    "supersedes_event_id must be canonical without surrounding whitespace"
                )
        else:
            supersedes_event_id = None
        evidence = next(
            (
                item
                for item in self.repository.list_evidence(resolved)
                if item.evidence_id == evidence_id
            ),
            None,
        )
        if evidence is None:
            raise NotFoundError(f"evidence {evidence_id} does not exist")
        status = require_text(command.status, "evidence status")
        if status != command.status:
            raise ValidationError(
                "evidence status must be canonical without surrounding whitespace"
            )
        if status not in {"active", "qualified", "withdrawn", "retracted"}:
            raise ValidationError(
                "evidence status must be active, qualified, withdrawn, or retracted"
            )
        created_at = self.clock()
        created = _parse_aware_timestamp(created_at, "evidence status creation time")
        effective_at = require_text(command.effective_at, "effective_at")
        effective = _parse_aware_timestamp(effective_at, "effective_at")
        evidence_created = _parse_aware_timestamp(evidence.created_at, "evidence created_at")
        if effective < evidence_created:
            raise ValidationError("evidence status event cannot predate its evidence")
        if effective > created:
            raise ValidationError("evidence status event cannot take effect in the future")
        from research_machine.application.evidence_status import (
            validate_evidence_status_event_chains,
        )
        all_evidence = self.repository.list_evidence(resolved)
        all_events = self.repository.list_evidence_status_events(resolved)
        chains = validate_evidence_status_event_chains(all_evidence, all_events)
        prior = chains.get(evidence.evidence_id, [])
        latest = prior[-1] if prior else None
        if latest is None and supersedes_event_id is not None:
            raise ValidationError("first evidence status event cannot supersede another event")
        if latest is not None:
            if latest.status == "retracted":
                raise ValidationError("retracted evidence status is terminal")
            if supersedes_event_id != latest.event_id:
                raise ValidationError("evidence status event must supersede the exact latest event")
            if effective < _parse_aware_timestamp(latest.effective_at, "prior effective_at"):
                raise ValidationError("evidence status event effective_at cannot move backward")
        artifact_hash = require_sha256(
            command.review_artifact_sha256, "review_artifact_sha256"
        )
        review_artifact_locator = require_canonical_text(
            command.review_artifact_locator, "review_artifact_locator"
        )
        review_artifact_root = require_canonical_text(
            command.review_artifact_root, "review_artifact_root"
        )
        report = verify_run_artifacts(
            [DatasetArtifact(
                locator=review_artifact_locator,
                sha256=artifact_hash,
            )],
            artifact_root=review_artifact_root,
            actor=self.actor,
            analysis_code_hash="",
            run_metadata={},
            attestation_schema_path=None,
            expected_attestation_schema_sha256=None,
        )
        if report.status != "passed":
            raise ValidationError(
                "evidence status artifact verification failed: "
                + ", ".join(item["code"] for item in report.findings)
            )
        reason = require_canonical_bounded_report_text(
            command.reason, "evidence status reason"
        )
        event = EvidenceStatusEvent(
            event_id=event_id or f"evidence-status-{self.token()}",
            sequence=len(prior) + 1,
            evidence_id=evidence.evidence_id,
            status=status,
            effective_at=effective_at,
            reason=reason,
            review_artifact_locator=review_artifact_locator,
            review_artifact_sha256=artifact_hash,
            review_artifact_root=str(
                Path(review_artifact_root).expanduser().resolve()
            ),
            supersedes_event_id=supersedes_event_id,
            created_at=created_at,
            created_by=self.actor,
            artifact_integrity=report.to_dict(),
            conclusion_ceiling=require_canonical_bounded_report_text(
                (
                    "Append-only evidence interpretation status; preserves the original record "
                    "and verifies local review bytes without authenticating the reviewer or its judgment."
                ),
                "evidence status conclusion ceiling",
            ),
        )
        self.repository.save_evidence_status_event(resolved, event)
        self._event(
            resolved,
            "evidence.review_status",
            "evidence",
            evidence.evidence_id,
            event.to_dict(),
        )
        return event

    def list_evidence_status_events(
        self, inquiry_id: str | None = None, *, evidence_id: str | None = None
    ) -> list[EvidenceStatusEvent]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        evidence = self.repository.list_evidence(resolved)
        events = self.repository.list_evidence_status_events(resolved)
        from research_machine.application.evidence_status import (
            validate_evidence_status_event_chains,
        )
        validate_evidence_status_event_chains(evidence, events)
        return [
            event for event in events
            if evidence_id is None or event.evidence_id == evidence_id
        ]

    def _currently_contributing_evidence(
        self, inquiry_id: str, evidence: list[EvidenceRecord]
    ) -> tuple[list[EvidenceRecord], list[EvidenceStatusEvent]]:
        events = self.repository.list_evidence_status_events(inquiry_id)
        from research_machine.application.evidence_status import (
            currently_contributing_evidence,
        )
        contributing, _ = currently_contributing_evidence(evidence, events)
        return contributing, events

    def build_synthesis(self, inquiry_id: str | None = None) -> dict[str, Any]:
        resolved = self.repository.resolve_inquiry_id(inquiry_id)
        self.show_inquiry(resolved)
        inquiry = self.repository.load_inquiry(resolved)
        claims = self.repository.load_claims(resolved)
        hypotheses = self.repository.list_hypotheses(resolved)
        evidence = self.repository.list_evidence(resolved)
        currently_contributing_evidence, evidence_status_events = (
            self._currently_contributing_evidence(resolved, evidence)
        )
        datasets = self.repository.list_datasets(resolved)
        protocols = self.repository.list_protocols(resolved)
        runs = self.repository.list_runs(resolved)
        cross_lane_lessons = self._verified_cross_lane_lessons(resolved)
        rigor_audit = audit_research_state(
            inquiry=inquiry,
            claims=claims,
            hypotheses=hypotheses,
            evidence=currently_contributing_evidence,
            datasets=datasets,
            protocols=protocols,
            runs=runs,
            cross_lane_lessons=cross_lane_lessons,
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
            self._verified_recommendations(resolved),
            cross_lane_lessons,
            rigor_audit,
            evidence_status_events,
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
        self.show_inquiry(resolved)
        evidence, _ = self._currently_contributing_evidence(
            resolved, self.repository.list_evidence(resolved)
        )
        audit = audit_research_state(
            inquiry=self.repository.load_inquiry(resolved),
            claims=self.repository.load_claims(resolved),
            hypotheses=self.repository.list_hypotheses(resolved),
            evidence=evidence,
            datasets=self.repository.list_datasets(resolved),
            protocols=self.repository.list_protocols(resolved),
            runs=self.repository.list_runs(resolved),
            cross_lane_lessons=self._verified_cross_lane_lessons(resolved),
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
        if claim.disposition is ClaimDisposition.ACCEPTED and not claim.last_reviewed:
            raise ValidationError("accepted claims require last_reviewed")
        if (
            claim.disposition is ClaimDisposition.ACCEPTED
            and not claim.decision_owner.strip()
        ):
            raise ValidationError("accepted claims require decision_owner")
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
        protocol: ExperimentProtocol,
        datasets: list[DatasetManifest],
        *,
        all_datasets: list[DatasetManifest] | None = None,
    ) -> None:
        from research_machine.application.dataset_integrity import (
            validate_dataset_payload_commitment,
            validate_protected_dataset_lineage_closure,
        )
        dataset_scope = all_datasets if all_datasets is not None else datasets
        datasets_by_id = {dataset.dataset_id: dataset for dataset in dataset_scope}
        for dataset in datasets:
            validate_dataset_payload_commitment(dataset)
            validate_protected_dataset_lineage_closure(dataset, datasets_by_id)
        if any(
            dataset.protocol_id and dataset.protocol_id != protocol.protocol_id
            for dataset in datasets
        ):
            raise ValidationError(
                "a run cannot use a protected dataset bound to another protocol"
            )
        from research_machine.application.dataset_integrity import (
            reverify_dataset_artifacts,
        )
        for dataset in datasets:
            if (
                dataset.role in {DatasetRole.CONFIRMATORY, DatasetRole.REPLICATION}
                and not dataset.synthetic
            ):
                reverify_dataset_artifacts(dataset, protocol)
        if protocol.measurement_custody_requirements:
            from research_machine.measurement.custody import (
                reverify_dataset_measurement_custody,
            )
            for dataset in datasets:
                reverify_dataset_measurement_custody(protocol, dataset)
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
        amendment_timing: str | None = None,
        evidence_exposure: str | None = None,
    ) -> ExperimentProtocol:
        if not isinstance(command.analysis_mode, AnalysisMode):
            raise ValidationError("analysis_mode must be an AnalysisMode")
        if not isinstance(command.causal_claim, bool):
            raise ValidationError("causal_claim must be true or false")
        if not isinstance(command.causal_identification, dict):
            raise ValidationError("causal_identification must be an object")
        if not isinstance(command.protocol_kind, ProtocolKind):
            raise ValidationError("protocol_kind must be a ProtocolKind")
        hypotheses = require_text_list(command.hypotheses_tested, "hypotheses_tested")
        if len(set(hypotheses)) != len(hypotheses):
            raise ValidationError("hypotheses_tested must not contain duplicates")
        for hypothesis_id in hypotheses:
            self.repository.find_hypothesis(inquiry_id, hypothesis_id)
        if command.sample_size_plan:
            from research_machine.design.precision import (
                build_sample_size_planning_receipt,
            )
            sample_size_plan = build_sample_size_planning_receipt(
                command.sample_size_plan
            )
        else:
            sample_size_plan = {}
        protocol_id = f"{protocol_family_id}-v{version}"
        sensor_requirements = require_text_list(
            command.sensor_requirements, "sensor_requirements"
        )
        if len({item.casefold() for item in sensor_requirements}) != len(
            sensor_requirements
        ):
            raise ValidationError(
                "sensor_requirements must not contain duplicate labels ignoring case"
            )
        control_windows = require_text_list(
            command.control_windows, "control_windows"
        )
        if len({item.casefold() for item in control_windows}) != len(
            control_windows
        ):
            raise ValidationError(
                "control_windows must not contain duplicate labels ignoring case"
            )
        clock_accuracy_requirement = normalize_text(
            command.clock_accuracy_requirement, "clock_accuracy_requirement"
        )
        if control_windows and not clock_accuracy_requirement:
            raise ValidationError(
                "control_windows require a clock_accuracy_requirement"
            )
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
            control_definitions=list(command.control_definitions),
            measurement_definitions=list(command.measurement_definitions),
            named_component_contracts=list(command.named_component_contracts),
            measurement_validity_checks=list(command.measurement_validity_checks),
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
            confirmatory_outcomes=require_text_list(
                command.confirmatory_outcomes, "confirmatory_outcomes"
            ),
            exploratory_outcomes=require_text_list(
                command.exploratory_outcomes, "exploratory_outcomes"
            ),
            multiplicity_method=normalize_text(
                command.multiplicity_method, "multiplicity_method"
            ),
            multiplicity_alpha=command.multiplicity_alpha,
            independent_variables=require_text_list(
                command.independent_variables, "independent_variables"
            ),
            manipulated_factors=require_text_list(
                command.manipulated_factors, "manipulated_factors"
            ),
            factorial_or_crossover_design=command.factorial_or_crossover_design,
            factor_interpretability_plan=normalize_text(
                command.factor_interpretability_plan,
                "factor_interpretability_plan",
            ),
            canary_target_plan=command.canary_target_plan,
            randomization_plan=normalize_text(
                command.randomization_plan, "randomization_plan"
            ),
            blinding_plan=normalize_text(command.blinding_plan, "blinding_plan"),
            sampling_unit=normalize_text(command.sampling_unit, "sampling_unit"),
            independent_unit=normalize_text(command.independent_unit, "independent_unit"),
            repeated_measures=command.repeated_measures,
            analysis_design=normalize_text(command.analysis_design, "analysis_design"),
            unit_analysis_plan=normalize_text(command.unit_analysis_plan, "unit_analysis_plan"),
            unit_id_column=normalize_text(command.unit_id_column, "unit_id_column"),
            analysis_specification_sha256=normalize_text(command.analysis_specification_sha256, "analysis_specification_sha256"),
            analysis_contract=command.analysis_contract,
            analysis_steps=list(command.analysis_steps),
            conclusion_contract=command.conclusion_contract,
            sample_size_or_stopping_rule=normalize_text(
                command.sample_size_or_stopping_rule,
                "sample_size_or_stopping_rule",
            ),
            sample_size_plan=sample_size_plan,
            inclusion_rules=require_text_list(
                command.inclusion_rules, "inclusion_rules"
            ),
            exclusion_rules=require_text_list(
                command.exclusion_rules, "exclusion_rules"
            ),
            sensor_requirements=sensor_requirements,
            calibration_requirements=require_text_list(
                command.calibration_requirements, "calibration_requirements"
            ),
            calibration_acceptance_criteria=list(command.calibration_acceptance_criteria),
            measurement_custody_requirements=require_text_list(
                command.measurement_custody_requirements,
                "measurement_custody_requirements",
            ),
            clock_accuracy_requirement=clock_accuracy_requirement,
            preprocessing_pipeline=normalize_text(
                command.preprocessing_pipeline, "preprocessing_pipeline"
            ),
            statistical_model=normalize_text(
                command.statistical_model, "statistical_model"
            ),
            control_windows=control_windows,
            multiple_testing_policy=normalize_text(
                command.multiple_testing_policy, "multiple_testing_policy"
            ),
            missing_data_policy=normalize_text(
                command.missing_data_policy, "missing_data_policy"
            ),
            causal_claim=command.causal_claim,
            causal_identification=dict(command.causal_identification),
            failure_conditions=require_text_list(
                command.failure_conditions, "failure_conditions"
            ),
            safety_constraints=require_text_list(
                command.safety_constraints, "safety_constraints"
            ),
            human_subjects=command.human_subjects,
            consent_plan=normalize_text(command.consent_plan, "consent_plan"),
            withdrawal_plan=normalize_text(command.withdrawal_plan, "withdrawal_plan"),
            privacy_plan=normalize_text(command.privacy_plan, "privacy_plan"),
            retention_deletion_plan=normalize_text(
                command.retention_deletion_plan, "retention_deletion_plan"
            ),
            risk_assessment=normalize_text(command.risk_assessment, "risk_assessment"),
            vulnerable_population_plan=normalize_text(
                command.vulnerable_population_plan, "vulnerable_population_plan"
            ),
            data_security_plan=normalize_text(command.data_security_plan, "data_security_plan"),
            incidental_findings_plan=normalize_text(
                command.incidental_findings_plan, "incidental_findings_plan"
            ),
            independent_review_receipt=normalize_text(
                command.independent_review_receipt, "independent_review_receipt"
            ),
            independent_review_decision=normalize_text(
                command.independent_review_decision, "independent_review_decision"
            ),
            independent_reviewer_role=normalize_text(
                command.independent_reviewer_role, "independent_reviewer_role"
            ),
            independent_reviewed_at=normalize_text(
                command.independent_reviewed_at, "independent_reviewed_at"
            ),
            independent_review_scope=normalize_text(
                command.independent_review_scope, "independent_review_scope"
            ),
            independent_review_artifact_locator=normalize_text(
                command.independent_review_artifact_locator,
                "independent_review_artifact_locator",
            ),
            independent_review_artifact_sha256=normalize_text(
                command.independent_review_artifact_sha256,
                "independent_review_artifact_sha256",
            ).lower(),
            independent_review_conditions=require_text_list(
                command.independent_review_conditions, "independent_review_conditions"
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
            amendment_timing=amendment_timing,
            evidence_exposure=evidence_exposure,
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
