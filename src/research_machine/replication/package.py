from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisMode,
    DatasetManifest,
    DatasetArtifact,
    EthicsReviewEvent,
    ExperimentProtocol,
    ProtocolStatus,
    QualityGateResult,
    ResearchRun,
    RunStatus,
    DatasetRole,
    QualityGateStatus,
)
from research_machine.application.policies import (
    assess_attrition_achievement,
    assess_precision_achievement,
    assess_variance_assumption,
    is_canonical_sha256,
    require_sha256,
    require_canonical_text,
    require_unique_canonical_text_list,
    normalize_text,
    validate_quality_gates,
)
from research_machine.application.protocol_integrity import protocol_commitment
from research_machine.application.dataset_integrity import (
    validate_dataset_payload_commitment,
)
from research_machine.application.run_integrity import validate_run_payload_commitment


_V2_LIMITATIONS = [
    "Raw data are not included.",
    "Artifact locators may be unavailable to an independent executor.",
    "A package export does not validate replication results.",
    "Recorded ethics status does not authorize a new site, population, or replication.",
]


_V1_VERIFICATION_CONTRACT = "replication_package_v1_file_integrity"
_V2_VERIFICATION_CONTRACT = "replication_package_v2_guardrails"
_REDACTED_ARTIFACT_LOCATOR = "[redacted: obtain from authorized source]"


_V2_INSTRUCTIONS = (
    "# Independent replication instructions\n\n"
    "This package contains frozen protocol and provenance metadata only. It does "
    "not copy raw data files or claim that the original result is correct. "
    "Free-text metadata may contain sensitive information; review before sharing. "
    "When locators are redacted, nested receipts are redacted derivatives, not "
    "the original hash-verifiable receipt bytes. Retained receipt hashes refer "
    "to originals obtainable from the authorized source. "
    "Obtain data through the authorized source, verify every listed SHA-256, "
    "use an independent executor and implementation where possible, and return a new "
    "run through Research Machine's replication workflow.\n"
    "Inspect ethics-review-events.json before any human-subject reuse; a "
    "suspension, withdrawal, expiry, or even an active event in this package "
    "does not authorize a new site or replication. Obtain independent current approval.\n"
)


def _strict_json_bytes(content: bytes, label: str) -> Any:
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
            content,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"invalid strict JSON in {label}: {exc}") from exc


def _validate_packaged_artifacts(
    *,
    artifacts: list[DatasetArtifact],
    label: str,
    locator_policy: str,
) -> list[DatasetArtifact]:
    if not artifacts:
        raise ValidationError(f"{label} must contain at least one artifact")
    normalized: list[DatasetArtifact] = []
    locators: set[str] = set()
    digests: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, DatasetArtifact):
            raise ValidationError(f"{label} artifacts must be DatasetArtifact values")
        locator = require_canonical_text(artifact.locator, f"{label} artifact locator")
        if locator_policy == "redacted":
            if locator != _REDACTED_ARTIFACT_LOCATOR:
                raise ValidationError(
                    f"{label} redacted artifact locator must use the package redaction placeholder"
                )
        elif locator in locators:
            raise ValidationError(f"{label} repeats an artifact locator")
        digest = require_sha256(artifact.sha256, f"{label} artifact sha256")
        if digest in digests:
            raise ValidationError(f"{label} repeats an artifact digest")
        if artifact.size_bytes is not None and (
            isinstance(artifact.size_bytes, bool)
            or not isinstance(artifact.size_bytes, int)
            or artifact.size_bytes < 0
        ):
            raise ValidationError(f"{label} artifact size_bytes must be non-negative or null")
        media_type = normalize_text(
            artifact.media_type, f"{label} artifact media_type"
        )
        if media_type != artifact.media_type:
            raise ValidationError(
                f"{label} artifact media_type must be canonical without surrounding whitespace"
            )
        if not isinstance(artifact.metadata, dict):
            raise ValidationError(f"{label} artifact metadata must be an object")
        locators.add(locator)
        digests.add(digest)
        normalized.append(
            DatasetArtifact(
                locator=locator,
                sha256=digest,
                size_bytes=artifact.size_bytes,
                media_type=media_type,
                metadata=dict(artifact.metadata),
            )
        )
    return normalized


def _validate_package_identity_list(values: Any, field_name: str) -> list[str]:
    return require_unique_canonical_text_list(values, field_name)


def _validate_preprocessing_conformance_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
) -> None:
    conformance = gate.details.get("preprocessing_conformance")
    if conformance is None:
        return
    if not isinstance(conformance, dict):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} preprocessing_conformance must be an object"
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
            f"package run {run_id} gate {gate.gate_id} preprocessing_conformance fields are invalid"
        )
    prefix = f"package run {run_id} gate {gate.gate_id} preprocessing_conformance"
    locator = require_canonical_text(conformance["locator"], f"{prefix}.locator")
    record_sha256 = require_sha256(conformance["sha256"], f"{prefix}.sha256")
    declared_status = require_canonical_text(conformance["status"], f"{prefix}.status")
    if declared_status not in {
        "preprocessing_conformance_passed",
        "preprocessing_conformance_failed",
    }:
        raise ValidationError(f"{prefix}.status is unsupported")
    registered_pipeline_sha256 = require_sha256(
        conformance["registered_pipeline_sha256"],
        f"{prefix}.registered_pipeline_sha256",
    )
    require_sha256(
        conformance["observed_pipeline_sha256"],
        f"{prefix}.observed_pipeline_sha256",
    )
    evidence_sha256 = require_sha256(
        gate.details.get("evidence_sha256"),
        f"package run {run_id} gate {gate.gate_id} evidence_sha256",
    )
    if evidence_sha256 != record_sha256:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} evidence does not match preprocessing conformance record"
        )
    if (
        is_canonical_sha256(protocol.preprocessing_pipeline)
        and registered_pipeline_sha256 != protocol.preprocessing_pipeline
    ):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} preprocessing conformance registered pipeline "
            "does not match frozen protocol preprocessing_pipeline"
        )
    if not any(
        artifact.locator == locator and artifact.sha256 == record_sha256
        for artifact in output_artifacts
    ):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} preprocessing conformance record is not a declared output artifact"
        )
    if gate.status is QualityGateStatus.PASSED:
        if declared_status != "preprocessing_conformance_passed":
            raise ValidationError(
                f"package run {run_id} passed preprocessing gate {gate.gate_id} lacks passed conformance metadata"
            )
    elif gate.status is QualityGateStatus.FAILED:
        if declared_status != "preprocessing_conformance_failed":
            raise ValidationError(
                f"package run {run_id} failed preprocessing gate {gate.gate_id} lacks failed conformance metadata"
            )
    else:
        raise ValidationError(
            f"package run {run_id} preprocessing gate {gate.gate_id} must be passed or failed according to conformance metadata"
        )


def _validate_temporal_order_assessment_gate_metadata(
    *,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
) -> None:
    assessment = gate.details.get("temporal_order_assessment")
    if assessment is None:
        return
    if not isinstance(assessment, dict):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} temporal_order_assessment must be an object"
        )
    required_fields = {
        "locator",
        "sha256",
        "status",
        "timing_assessment_sha256",
        "specification_sha256",
    }
    if set(assessment) != required_fields:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} temporal_order_assessment fields are invalid"
        )
    prefix = f"package run {run_id} gate {gate.gate_id} temporal_order_assessment"
    locator = require_canonical_text(assessment["locator"], f"{prefix}.locator")
    record_sha256 = require_sha256(assessment["sha256"], f"{prefix}.sha256")
    declared_status = require_canonical_text(assessment["status"], f"{prefix}.status")
    if declared_status not in {"temporal_order_passed", "temporal_order_failed"}:
        raise ValidationError(f"{prefix}.status is unsupported")
    require_sha256(
        assessment["timing_assessment_sha256"],
        f"{prefix}.timing_assessment_sha256",
    )
    require_sha256(
        assessment["specification_sha256"],
        f"{prefix}.specification_sha256",
    )
    if not any(
        artifact.locator == locator and artifact.sha256 == record_sha256
        for artifact in output_artifacts
    ):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} temporal-order assessment record is not a declared output artifact"
        )
    if gate.status is QualityGateStatus.PASSED:
        if declared_status != "temporal_order_passed":
            raise ValidationError(
                f"package run {run_id} passed temporal-order gate {gate.gate_id} lacks passed assessment metadata"
            )
    elif gate.status is QualityGateStatus.FAILED:
        if declared_status != "temporal_order_failed":
            raise ValidationError(
                f"package run {run_id} failed temporal-order gate {gate.gate_id} lacks failed assessment metadata"
            )
    else:
        raise ValidationError(
            f"package run {run_id} temporal-order gate {gate.gate_id} must be passed or failed according to assessment metadata"
        )


def _validate_instrument_inspection_gate_metadata(
    *,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
) -> None:
    inspection = gate.details.get("instrument_inspection")
    if inspection is None:
        return
    if not isinstance(inspection, dict):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} instrument_inspection must be an object"
        )
    required_fields = {
        "locator",
        "sha256",
        "status",
        "source_sha256",
        "config_sha256",
        "implementation_sha256",
    }
    if set(inspection) != required_fields:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} instrument_inspection fields are invalid"
        )
    prefix = f"package run {run_id} gate {gate.gate_id} instrument_inspection"
    locator = require_canonical_text(inspection["locator"], f"{prefix}.locator")
    record_sha256 = require_sha256(inspection["sha256"], f"{prefix}.sha256")
    declared_status = require_canonical_text(inspection["status"], f"{prefix}.status")
    if declared_status != "inspection_recorded":
        raise ValidationError(f"{prefix}.status is unsupported")
    require_sha256(inspection["source_sha256"], f"{prefix}.source_sha256")
    require_sha256(inspection["config_sha256"], f"{prefix}.config_sha256")
    require_sha256(
        inspection["implementation_sha256"],
        f"{prefix}.implementation_sha256",
    )
    if not any(
        artifact.locator == locator and artifact.sha256 == record_sha256
        for artifact in output_artifacts
    ):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} instrument inspection record is not a declared output artifact"
        )
    if gate.status is not QualityGateStatus.PASSED:
        raise ValidationError(
            f"package run {run_id} instrument-inspection gate {gate.gate_id} must be a passed retention gate"
        )


def _validate_stream_timing_assessment_gate_metadata(
    *,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
) -> None:
    assessment = gate.details.get("stream_timing_assessment")
    if assessment is None:
        return
    if not isinstance(assessment, dict):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} stream_timing_assessment must be an object"
        )
    required_fields = {
        "locator",
        "sha256",
        "status",
        "inspection_sha256",
        "specification_sha256",
    }
    if set(assessment) != required_fields:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} stream_timing_assessment fields are invalid"
        )
    prefix = f"package run {run_id} gate {gate.gate_id} stream_timing_assessment"
    locator = require_canonical_text(assessment["locator"], f"{prefix}.locator")
    record_sha256 = require_sha256(assessment["sha256"], f"{prefix}.sha256")
    declared_status = require_canonical_text(assessment["status"], f"{prefix}.status")
    if declared_status not in {
        "timing_feasibility_passed",
        "timing_feasibility_failed",
    }:
        raise ValidationError(f"{prefix}.status is unsupported")
    require_sha256(
        assessment["inspection_sha256"],
        f"{prefix}.inspection_sha256",
    )
    require_sha256(
        assessment["specification_sha256"],
        f"{prefix}.specification_sha256",
    )
    if not any(
        artifact.locator == locator and artifact.sha256 == record_sha256
        for artifact in output_artifacts
    ):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} stream-timing assessment record is not a declared output artifact"
        )
    if gate.status is QualityGateStatus.PASSED:
        if declared_status != "timing_feasibility_passed":
            raise ValidationError(
                f"package run {run_id} passed stream-timing gate {gate.gate_id} lacks passed assessment metadata"
            )
    elif gate.status is QualityGateStatus.FAILED:
        if declared_status != "timing_feasibility_failed":
            raise ValidationError(
                f"package run {run_id} failed stream-timing gate {gate.gate_id} lacks failed assessment metadata"
            )
    else:
        raise ValidationError(
            f"package run {run_id} stream-timing gate {gate.gate_id} must be passed or failed according to assessment metadata"
        )


def _validate_canary_target_assessment_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
) -> None:
    assessment = gate.details.get("canary_target_assessment")
    if assessment is None:
        return
    plan = protocol.canary_target_plan
    if plan is None:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary_target_assessment has no frozen canary target plan"
        )
    if gate.gate_id != plan.assessment_gate_id:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary_target_assessment is not bound to the frozen canary gate"
        )
    if not isinstance(assessment, dict):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary_target_assessment must be an object"
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
    if set(assessment) != required_fields:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary_target_assessment fields are invalid"
        )
    prefix = f"package run {run_id} gate {gate.gate_id} canary_target_assessment"
    plan_id = require_canonical_text(assessment["plan_id"], f"{prefix}.plan_id")
    if plan_id != plan.plan_id:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary target plan_id disagrees with protocol"
        )
    assignment_sha256 = require_sha256(
        assessment["assignment_artifact_sha256"],
        f"{prefix}.assignment_artifact_sha256",
    )
    if assignment_sha256 != plan.assignment_artifact_sha256:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary assignment artifact disagrees with protocol"
        )
    revealed = require_canonical_text(
        assessment["revealed_target_id"], f"{prefix}.revealed_target_id"
    )
    candidates = set(plan.candidate_target_ids)
    if revealed not in candidates:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary revealed target is not in the frozen candidate set"
        )
    comparators = require_unique_canonical_text_list(
        assessment["comparator_target_ids"], f"{prefix}.comparator_target_ids"
    )
    if not comparators:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary assessment requires at least one comparator target"
        )
    unavailable = sorted(set(comparators) - candidates)
    if unavailable:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary comparator targets are not in the frozen candidate set: "
            + ", ".join(unavailable)
        )
    if revealed in comparators:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary comparator targets must not include the revealed target"
        )
    status = require_canonical_text(
        assessment["assessment_status"], f"{prefix}.assessment_status"
    )
    if status not in {
        "consistent_with_revealed_target",
        "follows_comparator_or_decoy",
        "follows_no_target",
        "mixed",
        "inconclusive",
    }:
        raise ValidationError(f"{prefix}.assessment_status is unsupported")
    require_canonical_text(assessment["observed_pattern"], f"{prefix}.observed_pattern")
    require_canonical_text(assessment["interpretation"], f"{prefix}.interpretation")
    evidence_sha256 = require_sha256(
        assessment["evidence_sha256"], f"{prefix}.evidence_sha256"
    )
    if not any(artifact.sha256 == evidence_sha256 for artifact in output_artifacts):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary assessment evidence is not a declared output artifact"
        )
    if gate.details.get("evidence_sha256") != evidence_sha256:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} canary assessment evidence does not match gate evidence"
        )
    require_canonical_text(assessment["evidence_location"], f"{prefix}.evidence_location")


def _validate_control_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
) -> None:
    controls = [
        control
        for control in protocol.control_definitions
        if control.evaluation_gate_id == gate.gate_id
    ]
    if not controls or gate.status is not QualityGateStatus.PASSED:
        return
    results = gate.details.get("control_results")
    expected_ids = {control.control_id for control in controls}
    if not isinstance(results, dict) or set(results) != expected_ids:
        raise ValidationError(
            f"package run {run_id} passed control gate {gate.gate_id} requires exact evaluations for: "
            + ", ".join(sorted(expected_ids))
        )
    output_hashes = {artifact.sha256 for artifact in output_artifacts}
    for control in controls:
        result = results[control.control_id]
        required_fields = {
            "observed_behavior",
            "interpretation",
            "matches_expected",
            "evidence_sha256",
            "evidence_location",
        }
        if not isinstance(result, dict) or set(result) != required_fields:
            raise ValidationError(
                f"package run {run_id} passed control gate {gate.gate_id} requires an exact evaluation for {control.control_id}"
            )
        prefix = (
            f"package run {run_id} gate {gate.gate_id} control_results "
            f"{control.control_id}"
        )
        if not isinstance(result["observed_behavior"], str) or not result[
            "observed_behavior"
        ].strip():
            raise ValidationError(f"{prefix}.observed_behavior must be nonempty text")
        if not isinstance(result["interpretation"], str) or not result[
            "interpretation"
        ].strip():
            raise ValidationError(f"{prefix}.interpretation must be nonempty text")
        if type(result["matches_expected"]) is not bool:
            raise ValidationError(f"{prefix}.matches_expected must be a boolean")
        digest = require_sha256(result["evidence_sha256"], f"{prefix}.evidence_sha256")
        if digest not in output_hashes:
            raise ValidationError(
                f"package run {run_id} gate {gate.gate_id} control evaluation evidence must reference a run output artifact"
            )
        if not isinstance(result["evidence_location"], str) or not result[
            "evidence_location"
        ].strip():
            raise ValidationError(f"{prefix}.evidence_location must be nonempty text")


def _validate_measurement_validity_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
) -> None:
    checks = [
        check
        for check in protocol.measurement_validity_checks
        if check.assessment_gate_id == gate.gate_id
    ]
    if not checks or gate.status is QualityGateStatus.SKIPPED:
        return
    results = gate.details.get("measurement_validity_results")
    expected_ids = {check.check_id for check in checks}
    if not isinstance(results, dict) or set(results) != expected_ids:
        raise ValidationError(
            f"package run {run_id} performed measurement validity gate {gate.gate_id} requires exact results for: "
            + ", ".join(sorted(expected_ids))
        )
    expected_status = {
        QualityGateStatus.PASSED: "consistent_with_validity_claim",
        QualityGateStatus.WARNING: "inconclusive",
        QualityGateStatus.FAILED: "contradicted_validity_claim",
    }.get(gate.status)
    if expected_status is None:
        raise ValidationError(
            f"package run {run_id} measurement-validity gate {gate.gate_id} must be passed, warning, failed, or skipped"
        )
    output_hashes = {artifact.sha256 for artifact in output_artifacts}
    for check in checks:
        result = results[check.check_id]
        required_fields = {
            "observed_diagnostic",
            "interpretation",
            "assessment_status",
            "evidence_type",
            "evidence_sha256",
            "evidence_location",
        }
        if not isinstance(result, dict) or set(result) != required_fields:
            raise ValidationError(
                f"package run {run_id} measurement validity result for {check.check_id} must contain exactly the documented fields"
            )
        prefix = (
            f"package run {run_id} gate {gate.gate_id} measurement_validity_results "
            f"{check.check_id}"
        )
        for field in ("observed_diagnostic", "interpretation", "evidence_location"):
            if not isinstance(result[field], str) or not result[field].strip():
                raise ValidationError(f"{prefix}.{field} must be nonempty text")
        if result["evidence_type"] != check.evidence_type:
            raise ValidationError(
                f"package run {run_id} measurement validity evidence_type does not match the frozen protocol"
            )
        status = require_canonical_text(
            result["assessment_status"], f"{prefix}.assessment_status"
        )
        if status not in {
            "consistent_with_validity_claim",
            "contradicted_validity_claim",
            "inconclusive",
        }:
            raise ValidationError(
                f"package run {run_id} measurement validity result has an unsupported assessment_status"
            )
        if status != expected_status:
            raise ValidationError(
                f"package run {run_id} {gate.status.value} measurement validity gate requires {expected_status}"
            )
        digest = require_sha256(result["evidence_sha256"], f"{prefix}.evidence_sha256")
        if digest not in output_hashes:
            raise ValidationError(
                f"package run {run_id} measurement validity evidence must reference a run output artifact"
            )


def _validate_missingness_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
) -> None:
    contract = protocol.analysis_contract
    if (
        contract is None
        or not contract.missingness_assessment_gate_id
        or gate.gate_id != contract.missingness_assessment_gate_id
        or gate.status is QualityGateStatus.SKIPPED
    ):
        return
    result = gate.details.get("missingness_assessment_result")
    required_fields = {
        "observed_diagnostic",
        "interpretation",
        "assessment_status",
        "assessment_kind",
        "evidence_sha256",
        "evidence_location",
    }
    if not isinstance(result, dict) or set(result) != required_fields:
        raise ValidationError(
            f"package run {run_id} performed missingness assessment gate {gate.gate_id} requires one exact result"
        )
    prefix = f"package run {run_id} gate {gate.gate_id} missingness_assessment_result"
    for field in ("observed_diagnostic", "interpretation", "evidence_location"):
        if not isinstance(result[field], str) or not result[field].strip():
            raise ValidationError(f"{prefix}.{field} must be nonempty text")
    if result["assessment_kind"] != contract.missingness_assessment_kind:
        raise ValidationError(
            f"package run {run_id} missingness assessment_kind does not match the frozen analysis contract"
        )
    status = require_canonical_text(
        result["assessment_status"], f"{prefix}.assessment_status"
    )
    if status not in {
        "consistent_with_assumption",
        "contradicted_assumption",
        "inconclusive",
    }:
        raise ValidationError(
            f"package run {run_id} missingness assessment has an unsupported assessment_status"
        )
    expected_status = {
        QualityGateStatus.PASSED: "consistent_with_assumption",
        QualityGateStatus.WARNING: "inconclusive",
        QualityGateStatus.FAILED: "contradicted_assumption",
    }.get(gate.status)
    if expected_status is None:
        raise ValidationError(
            f"package run {run_id} missingness gate {gate.gate_id} must be passed, warning, failed, or skipped"
        )
    if status != expected_status:
        raise ValidationError(
            f"package run {run_id} {gate.status.value} missingness assessment gate requires {expected_status}"
        )
    digest = require_sha256(
        result["evidence_sha256"], f"{prefix}.evidence_sha256"
    )
    if not any(artifact.sha256 == digest for artifact in output_artifacts):
        raise ValidationError(
            f"package run {run_id} missingness assessment evidence must reference a run output artifact"
        )


def _validate_causal_assumption_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
) -> None:
    if not protocol.causal_claim or gate.status is QualityGateStatus.SKIPPED:
        return
    assumptions = [
        assumption
        for assumption in protocol.causal_identification_audit.get(
            "assumption_register", []
        )
        if assumption["assessment_gate_id"] == gate.gate_id
    ]
    if not assumptions:
        return
    results = gate.details.get("causal_assumption_results")
    expected_categories = {assumption["category"] for assumption in assumptions}
    if not isinstance(results, dict) or set(results) != expected_categories:
        raise ValidationError(
            f"package run {run_id} causal assessment gate {gate.gate_id} requires exact results for: "
            + ", ".join(sorted(expected_categories))
        )
    output_hashes = {artifact.sha256 for artifact in output_artifacts}
    observed_statuses: set[str] = set()
    for assumption in assumptions:
        category = assumption["category"]
        result = results[category]
        required_fields = {
            "observed_diagnostic",
            "interpretation",
            "assessment_status",
            "assessment_kind",
            "evidence_sha256",
            "evidence_location",
        }
        if not isinstance(result, dict) or set(result) != required_fields:
            raise ValidationError(
                f"package run {run_id} causal assessment gate {gate.gate_id} requires an exact result for {category}"
            )
        prefix = (
            f"package run {run_id} gate {gate.gate_id} "
            f"causal_assumption_results {category}"
        )
        for field in ("observed_diagnostic", "interpretation", "evidence_location"):
            if not isinstance(result[field], str) or not result[field].strip():
                raise ValidationError(f"{prefix}.{field} must be nonempty text")
        if result["assessment_kind"] != assumption.get(
            "assessment_kind", "legacy_unclassified"
        ):
            raise ValidationError(
                f"package run {run_id} causal assumption {category} assessment_kind does not match the frozen assumption register"
            )
        status = require_canonical_text(
            result["assessment_status"], f"{prefix}.assessment_status"
        )
        if status not in {
            "consistent_with_assumption",
            "contradicted_assumption",
            "inconclusive",
        }:
            raise ValidationError(
                f"package run {run_id} causal assumption {category} has an unsupported assessment_status"
            )
        observed_statuses.add(status)
        digest = require_sha256(result["evidence_sha256"], f"{prefix}.evidence_sha256")
        if digest not in output_hashes:
            raise ValidationError(
                f"package run {run_id} causal assumption assessment evidence must reference a run output artifact"
            )
    if gate.status is QualityGateStatus.PASSED and observed_statuses != {
        "consistent_with_assumption"
    }:
        raise ValidationError(
            f"package run {run_id} passed causal assessment gate {gate.gate_id} requires every result to be consistent_with_assumption"
        )
    if gate.status is QualityGateStatus.WARNING and (
        "contradicted_assumption" in observed_statuses
        or "inconclusive" not in observed_statuses
    ):
        raise ValidationError(
            f"package run {run_id} warning causal assessment gate {gate.gate_id} requires at least one inconclusive result and no contradicted assumptions"
        )
    if (
        gate.status is QualityGateStatus.FAILED
        and "contradicted_assumption" not in observed_statuses
    ):
        raise ValidationError(
            f"package run {run_id} failed causal assessment gate {gate.gate_id} requires at least one contradicted_assumption result"
        )


def _validate_protocol_deviation_disclosure_metadata(
    *,
    run_id: str,
    metadata: dict[str, Any],
    output_artifacts: list[DatasetArtifact],
) -> dict[str, Any]:
    disclosure = metadata.get("protocol_deviation_disclosure")
    if not isinstance(disclosure, dict):
        raise ValidationError(
            f"package run {run_id} requires protocol_deviation_disclosure metadata"
        )
    status = require_canonical_text(
        disclosure.get("status"),
        f"package run {run_id} protocol_deviation_disclosure.status",
    )
    deviations = disclosure.get("deviations")
    if not isinstance(deviations, list):
        raise ValidationError(
            f"package run {run_id} protocol_deviation_disclosure.deviations must be an array"
        )
    automatic = disclosure.get("automatic_evidence_eligible")
    if type(automatic) is not bool:
        raise ValidationError(
            f"package run {run_id} protocol_deviation_disclosure.automatic_evidence_eligible must be a boolean"
        )
    if status == "legacy_not_declared":
        if set(disclosure) != {
            "status",
            "deviations",
            "automatic_evidence_eligible",
        }:
            raise ValidationError(
                f"package run {run_id} legacy protocol deviation disclosure fields are invalid"
            )
        if deviations or automatic:
            raise ValidationError(
                f"package run {run_id} legacy protocol deviation disclosure must remain ineligible"
            )
        return disclosure
    if status not in {"no_deviations_declared", "deviations_declared"}:
        raise ValidationError(
            f"package run {run_id} protocol deviation disclosure status is invalid"
        )
    if set(disclosure) != {
        "status",
        "deviations",
        "automatic_evidence_eligible",
        "interpretation_boundary",
    }:
        raise ValidationError(
            f"package run {run_id} protocol deviation disclosure fields are invalid"
        )
    boundary = require_canonical_text(
        disclosure["interpretation_boundary"],
        f"package run {run_id} protocol_deviation_disclosure.interpretation_boundary",
    )
    if (
        "no-deviation declaration is an unauthenticated execution assertion"
        not in boundary
        or "declared departure requires separate scientific review" not in boundary
    ):
        raise ValidationError(
            f"package run {run_id} protocol deviation disclosure boundary is invalid"
        )
    if automatic is not (status == "no_deviations_declared"):
        raise ValidationError(
            f"package run {run_id} protocol deviation disclosure eligibility disagrees with status"
        )
    if (status == "no_deviations_declared") != (not deviations):
        raise ValidationError(
            f"package run {run_id} protocol deviation disclosure status disagrees with deviations"
        )
    required_fields = {
        "deviation_id",
        "stage",
        "frozen_commitment",
        "actual_method",
        "reason",
        "timing",
        "potential_impact",
        "corrective_action",
        "evidence_sha256",
        "evidence_location",
    }
    allowed_timing = {
        "before_execution",
        "during_execution",
        "after_execution_before_results",
        "after_results_seen",
        "unknown",
    }
    allowed_impact = {
        "none",
        "minor",
        "potentially_material",
        "invalidating",
        "unknown",
    }
    output_hashes = {artifact.sha256 for artifact in output_artifacts}
    seen_ids: set[str] = set()
    for deviation in deviations:
        if not isinstance(deviation, dict) or set(deviation) != required_fields:
            raise ValidationError(
                f"package run {run_id} protocol deviation must contain the exact documented fields"
            )
        deviation_id = require_canonical_text(
            deviation["deviation_id"],
            f"package run {run_id} protocol deviation deviation_id",
        )
        if deviation_id in seen_ids:
            raise ValidationError(
                f"package run {run_id} repeats protocol deviation_id {deviation_id}"
            )
        seen_ids.add(deviation_id)
        for field in (
            "stage",
            "frozen_commitment",
            "actual_method",
            "reason",
            "corrective_action",
            "evidence_location",
        ):
            require_canonical_text(
                deviation[field],
                f"package run {run_id} protocol deviation {deviation_id} {field}",
            )
        timing = require_canonical_text(
            deviation["timing"],
            f"package run {run_id} protocol deviation {deviation_id} timing",
        )
        if timing not in allowed_timing:
            raise ValidationError(
                f"package run {run_id} protocol deviation {deviation_id} timing is invalid"
            )
        impact = require_canonical_text(
            deviation["potential_impact"],
            f"package run {run_id} protocol deviation {deviation_id} potential_impact",
        )
        if impact not in allowed_impact:
            raise ValidationError(
                f"package run {run_id} protocol deviation {deviation_id} potential_impact is invalid"
            )
        digest = require_sha256(
            deviation["evidence_sha256"],
            f"package run {run_id} protocol deviation {deviation_id} evidence_sha256",
        )
        if digest not in output_hashes:
            raise ValidationError(
                f"package run {run_id} protocol deviation evidence must reference a run output artifact"
            )
    return disclosure


def _resolve_json_pointer(value: Any, pointer: str, field_name: str) -> Any:
    pointer = require_canonical_text(pointer, field_name)
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValidationError(f"{field_name} must be an absolute JSON Pointer")
    current = value
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not part.isdigit():
                raise ValidationError(f"{field_name} does not resolve")
            index = int(part)
            if index >= len(current):
                raise ValidationError(f"{field_name} does not resolve")
            current = current[index]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ValidationError(f"{field_name} does not resolve")
    return current


def _validate_sample_size_plan_check_metadata(
    *,
    protocol: ExperimentProtocol,
    run: ResearchRun,
) -> dict[str, Any]:
    check = run.metadata.get("sample_size_plan_check")
    if not protocol.sample_size_plan:
        expected = {
            "status": "not_applicable",
            "reason": "protocol has no machine-recomputed sample_size_plan",
        }
        if check != expected:
            raise ValidationError(
                f"package run {run.run_id} sample_size_plan_check disagrees with the protocol"
            )
        return expected
    if not isinstance(check, dict):
        raise ValidationError(
            f"package run {run.run_id} requires sample_size_plan_check metadata"
        )
    required_fields = {
        "status",
        "strategy",
        "target_hypothesis_id",
        "target_measurement_id",
        "measurement_unit",
        "planning_target_sha256",
        "specification_sha256",
        "required_analyzable_units_per_group",
        "observed_minimum_analyzable_units_per_group",
        "anticipated_attrition_fraction",
        "registered_maximum_excluded_fraction",
        "observed_excluded_fraction",
        "precision_achievement",
        "attrition_achievement",
        "variance_assumption",
        "execution_information_check_verified",
        "scientific_interpretation_verified",
    }
    if set(check) != required_fields:
        raise ValidationError(
            f"package run {run.run_id} sample_size_plan_check fields are invalid"
        )
    status = require_canonical_text(
        check["status"], f"package run {run.run_id} sample_size_plan_check.status"
    )
    if status not in {"passed", "unbound"}:
        raise ValidationError(
            f"package run {run.run_id} sample_size_plan_check status is invalid"
        )
    for field in (
        "strategy",
        "target_hypothesis_id",
        "target_measurement_id",
        "measurement_unit",
        "planning_target_sha256",
        "specification_sha256",
    ):
        value = check[field]
        if value is not None:
            require_canonical_text(
                value, f"package run {run.run_id} sample_size_plan_check.{field}"
            )
    if check["planning_target_sha256"] is not None:
        require_sha256(
            check["planning_target_sha256"],
            f"package run {run.run_id} sample_size_plan_check.planning_target_sha256",
        )
    require_sha256(
        check["specification_sha256"],
        f"package run {run.run_id} sample_size_plan_check.specification_sha256",
    )
    if type(check["execution_information_check_verified"]) is not bool:
        raise ValidationError(
            f"package run {run.run_id} sample_size_plan_check execution_information_check_verified must be a boolean"
        )
    if check["scientific_interpretation_verified"] is not False:
        raise ValidationError(
            f"package run {run.run_id} sample_size_plan_check must not verify scientific interpretation"
        )
    try:
        calculation = protocol.sample_size_plan["calculation"]
        expected_analyzable = calculation["analyzable_n_per_group"]
        anticipated_attrition = calculation["anticipated_attrition_fraction"]
        execution_handoff = run.metadata.get("execution_handoff")
        adjudication_handoff = run.metadata.get("workflow_adjudication_handoff")
        if execution_handoff is not None and not isinstance(execution_handoff, dict):
            raise ValidationError(
                f"package run {run.run_id} execution_handoff must be an object"
            )
        if adjudication_handoff is not None and not isinstance(
            adjudication_handoff, dict
        ):
            raise ValidationError(
                f"package run {run.run_id} workflow_adjudication_handoff must be an object"
            )
        if execution_handoff is not None and adjudication_handoff is not None:
            raise ValidationError(
                f"package run {run.run_id} cannot retain both execution and adjudication handoffs"
            )
        information_check = (
            execution_handoff.get("receipt", {}).get("registered_information_check")
            if isinstance(execution_handoff, dict)
            else adjudication_handoff.get("adjudication", {})
            .get("primary_estimate", {})
            .get("registered_information_check")
            if isinstance(adjudication_handoff, dict)
            else None
        )
        observed_minimum = (
            information_check.get("observed_minimum_analyzable_units")
            if isinstance(information_check, dict)
            else None
        )
        execution_bound = bool(
            protocol.analysis_contract is not None
            and protocol.analysis_contract.minimum_analyzable_units
            == expected_analyzable
            and isinstance(information_check, dict)
            and information_check.get("status") == "passed"
            and information_check.get("registered_minimum_analyzable_units")
            == expected_analyzable
            and not isinstance(observed_minimum, bool)
            and isinstance(observed_minimum, (int, float))
            and observed_minimum >= expected_analyzable
        )
        primary_uncertainty = (
            _resolve_json_pointer(
                execution_handoff["result"],
                protocol.analysis_contract.uncertainty_path,
                f"package run {run.run_id} analysis_contract.uncertainty_path",
            )
            if isinstance(execution_handoff, dict)
            and protocol.analysis_contract is not None
            and isinstance(
                execution_handoff.get("receipt", {}).get(
                    "registered_result_selection"
                ),
                dict,
            )
            else adjudication_handoff.get("adjudication", {})
            .get("primary_estimate", {})
            .get("uncertainty")
            if isinstance(adjudication_handoff, dict)
            else None
        )
        observed_standard_deviation = (
            execution_handoff.get("result", {})
            .get("result", {})
            .get("pooled_within_group_standard_deviation")
            if isinstance(execution_handoff, dict)
            else adjudication_handoff.get("adjudication", {})
            .get("primary_estimate", {})
            .get("observed_pooled_standard_deviation")
            if isinstance(adjudication_handoff, dict)
            else None
        )
        expected = {
            "status": "passed" if execution_bound else "unbound",
            "strategy": protocol.sample_size_plan["strategy"],
            "target_hypothesis_id": protocol.sample_size_plan.get(
                "target_hypothesis_id"
            ),
            "target_measurement_id": protocol.sample_size_plan.get(
                "target_measurement_id"
            ),
            "measurement_unit": protocol.sample_size_plan.get("measurement_unit"),
            "planning_target_sha256": protocol.sample_size_plan.get(
                "planning_target_sha256"
            ),
            "specification_sha256": protocol.sample_size_plan[
                "specification_sha256"
            ],
            "required_analyzable_units_per_group": expected_analyzable,
            "observed_minimum_analyzable_units_per_group": observed_minimum,
            "anticipated_attrition_fraction": anticipated_attrition,
            "registered_maximum_excluded_fraction": (
                protocol.analysis_contract.maximum_excluded_fraction
                if protocol.analysis_contract is not None
                else None
            ),
            "observed_excluded_fraction": (
                information_check.get("observed_excluded_fraction")
                if isinstance(information_check, dict)
                else None
            ),
            "precision_achievement": assess_precision_achievement(
                protocol.sample_size_plan, primary_uncertainty
            ),
            "attrition_achievement": assess_attrition_achievement(
                protocol.sample_size_plan, information_check
            ),
            "variance_assumption": assess_variance_assumption(
                protocol.sample_size_plan, observed_standard_deviation
            ),
            "execution_information_check_verified": execution_bound,
            "scientific_interpretation_verified": False,
        }
    except KeyError as exc:
        raise ValidationError(
            f"package run {run.run_id} sample_size_plan_check cannot be replayed"
        ) from exc
    if check != expected:
        raise ValidationError(
            f"package run {run.run_id} sample_size_plan_check no longer matches the protocol-bound calculation"
        )
    return check


def verify_replication_package(root: Path, expected_manifest_sha256: str) -> dict[str, Any]:
    """Verify packaged bytes against an independently retained export commitment."""
    expected_manifest_sha256 = require_sha256(
        expected_manifest_sha256, "expected manifest SHA-256"
    )
    try:
        if not root.is_dir() or root.is_symlink():
            raise ValidationError("package must be a directory, not a symbolic link")
        manifest_path = root / "package-manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValidationError("package manifest must be a regular file")
        content = manifest_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected_manifest_sha256:
            raise ValidationError("package manifest hash does not match trusted commitment")
        manifest = _strict_json_bytes(content, "package-manifest.json")
        if not isinstance(manifest, dict) or type(manifest.get("package_version")) is not int or manifest["package_version"] not in {1, 2}:
            raise ValidationError("unsupported package manifest version")
        expected_files = {"protocol.json", "datasets.json", "runs.json", "INSTRUCTIONS.md"}
        if manifest["package_version"] == 2:
            expected_files.add("ethics-review-events.json")
        if {path.name for path in root.iterdir()} != expected_files | {"package-manifest.json"}:
            raise ValidationError("package contains missing or unexpected files")
        for name in expected_files:
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise ValidationError(f"package entry must be a regular file: {name}")
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != expected_files:
            raise ValidationError("manifest must cover exactly the package files")
        for name, expected in files.items():
            expected_file_sha256 = require_sha256(
                expected, f"manifest file hash for {name}"
            )
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected_file_sha256:
                raise ValidationError(f"package file hash mismatch: {name}")
        if manifest["package_version"] == 2:
            if (root / "INSTRUCTIONS.md").read_text(encoding="utf-8") != _V2_INSTRUCTIONS:
                raise ValidationError(
                    "version-2 package instructions must match the non-evidentiary replication contract"
                )
            required_v2 = {
                "package_version", "privacy_mode", "artifact_locator_policy",
                "protocol", "dataset_ids", "run_ids", "ethics_review_event_ids",
                "latest_recorded_ethics_status", "replication_ethics_authorized",
                "files", "limitations",
            }
            if set(manifest) != required_v2:
                raise ValidationError("version-2 package manifest fields do not match the contract")
            if manifest.get("privacy_mode") != "metadata_only":
                raise ValidationError(
                    "version-2 package privacy_mode must be metadata_only"
                )
            if manifest.get("artifact_locator_policy") not in {"redacted", "included"}:
                raise ValidationError(
                    "version-2 package artifact_locator_policy is unsupported"
                )
            if manifest.get("limitations") != _V2_LIMITATIONS:
                raise ValidationError(
                    "version-2 package limitations must match the non-evidentiary replication contract"
                )
            protocol_value = _strict_json_bytes(
                (root / "protocol.json").read_bytes(), "protocol.json"
            )
            protocol = ExperimentProtocol.from_dict(protocol_value)
            protocol_id = require_canonical_text(
                protocol.protocol_id, "package protocol protocol_id"
            )
            protocol_hash = require_sha256(
                protocol.protocol_hash, "package protocol protocol_hash"
            )
            registration_timestamp = require_canonical_text(
                protocol.registration_timestamp,
                "package protocol registration_timestamp",
            )
            protocol_gate_ids = [
                require_canonical_text(gate_id, "quality_requirements item")
                for gate_id in protocol.quality_requirements
            ]
            if len(protocol_gate_ids) != len(set(protocol_gate_ids)):
                raise ValidationError(
                    "package protocol repeats a quality requirement"
                )
            from research_machine.application.ethics import validate_original_review_artifact
            validate_original_review_artifact(
                protocol, verify_current_artifact=False
            )
            protocol_summary = manifest.get("protocol")
            if not isinstance(protocol_summary, dict) or set(protocol_summary) != {
                "protocol_id", "protocol_hash", "registration_timestamp"
            }:
                raise ValidationError("version-2 package protocol summary is invalid")
            summary_protocol_id = require_canonical_text(
                protocol_summary["protocol_id"],
                "version-2 package protocol summary protocol_id",
            )
            summary_protocol_hash = require_sha256(
                protocol_summary["protocol_hash"],
                "version-2 package protocol summary protocol_hash",
            )
            summary_registration_timestamp = require_canonical_text(
                protocol_summary["registration_timestamp"],
                "version-2 package protocol summary registration_timestamp",
            )
            if (
                summary_protocol_id != protocol_id
                or summary_protocol_hash != protocol_hash
                or summary_registration_timestamp != registration_timestamp
            ):
                raise ValidationError("version-2 package protocol summary disagrees with protocol.json")
            manifest_ethics_event_ids = _validate_package_identity_list(
                manifest.get("ethics_review_event_ids"),
                "version-2 package manifest ethics_review_event_ids",
            )
            if manifest.get("artifact_locator_policy") == "included":
                if (
                    not protocol.protocol_hash
                    or protocol_commitment(protocol) != protocol.protocol_hash
                ):
                    raise ValidationError(
                        "package protocol content no longer matches its hash commitment"
                    )
            ethics_value = _strict_json_bytes(
                (root / "ethics-review-events.json").read_bytes(),
                "ethics-review-events.json",
            )
            if not isinstance(ethics_value, list):
                raise ValidationError("ethics-review-events.json must contain an array")
            events = [EthicsReviewEvent.from_dict(item) for item in ethics_value]
            from research_machine.application.ethics import validate_ethics_review_event_chain
            events = validate_ethics_review_event_chain(
                protocol, events, verify_current_artifacts=False
            )
            if manifest_ethics_event_ids != [item.event_id for item in events]:
                raise ValidationError("package ethics event IDs disagree with the event chain")
            expected_status = (
                events[-1].status
                if events
                else (
                    protocol.independent_review_decision
                    if protocol.human_subjects
                    else "not_applicable"
                )
            )
            if manifest.get("latest_recorded_ethics_status") != expected_status:
                raise ValidationError("package latest ethics status disagrees with the event chain")
            if manifest.get("replication_ethics_authorized") is not False:
                raise ValidationError("replication package must not authorize replication ethics")
            dataset_value = _strict_json_bytes(
                (root / "datasets.json").read_bytes(), "datasets.json"
            )
            run_value = _strict_json_bytes(
                (root / "runs.json").read_bytes(), "runs.json"
            )
            if not isinstance(dataset_value, list) or not isinstance(run_value, list):
                raise ValidationError("package datasets and runs must be arrays")
            datasets = [DatasetManifest.from_dict(item) for item in dataset_value]
            runs = [ResearchRun.from_dict(item) for item in run_value]
            dataset_ids = _validate_package_identity_list(
                [item.dataset_id for item in datasets],
                "package dataset IDs",
            )
            run_ids = _validate_package_identity_list(
                [item.run_id for item in runs],
                "package run IDs",
            )
            manifest_dataset_ids = _validate_package_identity_list(
                manifest.get("dataset_ids"),
                "version-2 package manifest dataset_ids",
            )
            manifest_run_ids = _validate_package_identity_list(
                manifest.get("run_ids"),
                "version-2 package manifest run_ids",
            )
            if manifest_dataset_ids != sorted(dataset_ids):
                raise ValidationError("package dataset IDs disagree with unique dataset records")
            if manifest_run_ids != sorted(run_ids):
                raise ValidationError("package run IDs disagree with unique run records")
            dataset_by_id = {item.dataset_id: item for item in datasets}
            protected_dataset_role = {
                AnalysisMode.CONFIRMATORY: DatasetRole.CONFIRMATORY,
                AnalysisMode.REPLICATION: DatasetRole.REPLICATION,
            }.get(protocol.analysis_mode)
            for dataset in datasets:
                dataset_id = require_canonical_text(
                    dataset.dataset_id, "package dataset dataset_id"
                )
                if dataset.protocol_id is not None:
                    require_canonical_text(
                        dataset.protocol_id,
                        f"package dataset {dataset_id} protocol_id",
                    )
                require_unique_canonical_text_list(
                    dataset.source_dataset_ids,
                    f"package dataset {dataset_id} source_dataset_ids",
                )
                if protected_dataset_role is not None and (
                    dataset.role is not protected_dataset_role
                    or dataset.protocol_id != protocol_id
                ):
                    raise ValidationError(
                        f"package protected dataset {dataset_id} is outside the packaged protocol-closed lineage"
                    )
                _validate_packaged_artifacts(
                    artifacts=dataset.artifacts,
                    label=f"package dataset {dataset_id}",
                    locator_policy=manifest["artifact_locator_policy"],
                )
                if manifest.get("artifact_locator_policy") == "included":
                    validate_dataset_payload_commitment(dataset)
                unavailable = sorted(set(dataset.source_dataset_ids) - set(dataset_by_id))
                if unavailable:
                    raise ValidationError(
                        f"package dataset {dataset_id} has unavailable lineage sources: "
                        + ", ".join(unavailable)
                    )
            visiting: set[str] = set()
            visited: set[str] = set()

            def visit(dataset_id: str) -> None:
                if dataset_id in visiting:
                    raise ValidationError("package dataset lineage contains a cycle")
                if dataset_id in visited:
                    return
                visiting.add(dataset_id)
                for source_id in dataset_by_id[dataset_id].source_dataset_ids:
                    visit(source_id)
                visiting.remove(dataset_id)
                visited.add(dataset_id)

            for dataset_id in dataset_by_id:
                visit(dataset_id)
            roots = {
                item.dataset_id for item in datasets
                if item.protocol_id == protocol_id
            }
            reachable = set(roots)
            pending = list(roots)
            while pending:
                current = dataset_by_id[pending.pop()]
                for source_id in current.source_dataset_ids:
                    if source_id not in reachable:
                        reachable.add(source_id)
                        pending.append(source_id)
            if reachable != set(dataset_by_id):
                raise ValidationError("package contains datasets outside protocol lineage closure")
            for run in runs:
                run_id = require_canonical_text(run.run_id, "package run run_id")
                run_protocol_id = require_canonical_text(
                    run.protocol_id, f"package run {run_id} protocol_id"
                )
                run_protocol_hash = require_sha256(
                    run.protocol_hash, f"package run {run_id} protocol_hash"
                )
                run_dataset_ids = require_unique_canonical_text_list(
                    run.dataset_ids, f"package run {run_id} dataset_ids"
                )
                if manifest.get("artifact_locator_policy") == "included":
                    validate_run_payload_commitment(run)
                if run_protocol_id != protocol_id or run_protocol_hash != protocol_hash:
                    raise ValidationError(
                        f"package run {run_id} does not match the packaged frozen protocol"
                    )
                if run.analysis_mode is not protocol.analysis_mode:
                    raise ValidationError(
                        f"package run {run_id} analysis mode disagrees with the protocol"
                    )
                missing_inputs = sorted(set(run_dataset_ids) - set(dataset_by_id))
                if missing_inputs:
                    raise ValidationError(
                        f"package run {run_id} has unavailable dataset inputs: "
                        + ", ".join(missing_inputs)
                    )
                input_datasets = [dataset_by_id[value] for value in run_dataset_ids]
                expected_role = {
                    AnalysisMode.EXPLORATORY: DatasetRole.EXPLORATORY,
                    AnalysisMode.CONFIRMATORY: DatasetRole.CONFIRMATORY,
                    AnalysisMode.REPLICATION: DatasetRole.REPLICATION,
                }[protocol.analysis_mode]
                if any(item.role is not expected_role for item in input_datasets):
                    raise ValidationError(
                        f"package run {run.run_id} uses a dataset role outside its protocol mode"
                    )
                if any(item.synthetic for item in input_datasets) and not run.synthetic:
                    raise ValidationError(
                        f"package run {run.run_id} drops synthetic status from an input"
                    )
                output_artifacts = _validate_packaged_artifacts(
                    artifacts=run.output_artifacts,
                    label=f"package run {run.run_id}",
                    locator_policy=manifest["artifact_locator_policy"],
                )
                quality_gates = validate_quality_gates(run.quality_gates)
                gate_by_id = {item.gate_id: item for item in quality_gates}
                if len(gate_by_id) != len(quality_gates):
                    raise ValidationError(f"package run {run.run_id} repeats a quality gate")
                missing_gates = sorted(set(protocol_gate_ids) - set(gate_by_id))
                protocol_gate_failure = any(
                    gate_by_id[value].status is not QualityGateStatus.PASSED
                    for value in protocol_gate_ids
                    if value in gate_by_id
                )
                required_gate_failure = any(
                    item.required and item.status is not QualityGateStatus.PASSED
                    for item in quality_gates
                )
                output_hashes = {item.sha256 for item in output_artifacts}
                for gate in quality_gates:
                    if gate.status is QualityGateStatus.PASSED:
                        if gate.details.get("evidence_sha256") not in output_hashes:
                            raise ValidationError(
                                f"package run {run.run_id} passed gate {gate.gate_id} lacks output-bound evidence"
                            )
                    _validate_preprocessing_conformance_gate_metadata(
                        protocol=protocol,
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                    )
                    _validate_instrument_inspection_gate_metadata(
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                    )
                    _validate_stream_timing_assessment_gate_metadata(
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                    )
                    _validate_temporal_order_assessment_gate_metadata(
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                    )
                    _validate_canary_target_assessment_gate_metadata(
                        protocol=protocol,
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                    )
                    _validate_control_gate_metadata(
                        protocol=protocol,
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                    )
                    _validate_measurement_validity_gate_metadata(
                        protocol=protocol,
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                    )
                    _validate_missingness_gate_metadata(
                        protocol=protocol,
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                    )
                    _validate_causal_assumption_gate_metadata(
                        protocol=protocol,
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                    )
                    prerequisites = gate.details.get("prerequisite_gate_ids", [])
                    if not isinstance(prerequisites, list) or any(
                        not isinstance(value, str) or not value.strip()
                        for value in prerequisites
                    ):
                        raise ValidationError(
                            f"package run {run.run_id} gate {gate.gate_id} has invalid prerequisites"
                        )
                    if any(value != value.strip() for value in prerequisites):
                        raise ValidationError(
                            f"package run {run.run_id} gate {gate.gate_id} has invalid prerequisites"
                        )
                    if len(prerequisites) != len(set(prerequisites)) or gate.gate_id in prerequisites:
                        raise ValidationError(
                            f"package run {run.run_id} gate {gate.gate_id} has invalid prerequisites"
                        )
                    if gate.status is QualityGateStatus.PASSED and any(
                        value not in gate_by_id
                        or gate_by_id[value].status is not QualityGateStatus.PASSED
                        for value in prerequisites
                    ):
                        raise ValidationError(
                            f"package run {run.run_id} gate {gate.gate_id} has an unmet prerequisite"
                        )
                if protocol.canary_target_plan is not None:
                    canary_gate = gate_by_id.get(
                        protocol.canary_target_plan.assessment_gate_id
                    )
                    if (
                        canary_gate is not None
                        and canary_gate.status is not QualityGateStatus.SKIPPED
                        and "canary_target_assessment" not in canary_gate.details
                    ):
                        raise ValidationError(
                            f"package run {run.run_id} performed canary gate "
                            f"{canary_gate.gate_id} requires structured canary_target_assessment metadata"
                        )
                artifact_integrity = run.metadata.get("artifact_integrity")
                artifact_failure = (
                    isinstance(artifact_integrity, dict)
                    and artifact_integrity.get("status") != "passed"
                )
                deviation_disclosure = _validate_protocol_deviation_disclosure_metadata(
                    run_id=run.run_id,
                    metadata=run.metadata,
                    output_artifacts=output_artifacts,
                )
                sample_size_plan_check = _validate_sample_size_plan_check_metadata(
                    protocol=protocol,
                    run=run,
                )
                invalid = bool(
                    missing_gates
                    or protocol_gate_failure
                    or required_gate_failure
                    or artifact_failure
                )
                if (run.status is RunStatus.INVALID) != invalid:
                    raise ValidationError(
                        f"package run {run.run_id} status disagrees with its quality gates"
                    )
                expected_eligible = (
                    not invalid
                    and not run.synthetic
                    and run.metadata.get("workflow_component_only") is not True
                    and deviation_disclosure.get("status")
                    == "no_deviations_declared"
                    and deviation_disclosure.get("deviations") == []
                    and deviation_disclosure.get("automatic_evidence_eligible") is True
                    and isinstance(artifact_integrity, dict)
                    and artifact_integrity.get("status") == "passed"
                    and (
                        not protocol.sample_size_plan
                        or sample_size_plan_check.get("status") == "passed"
                    )
                )
                if run.scientific_evidence_eligible is not expected_eligible:
                    raise ValidationError(
                        f"package run {run.run_id} evidence eligibility disagrees with gates, synthetic status, workflow role, or deviation disclosure"
                    )
    except (OSError, TypeError, ValueError) as exc:
        raise ValidationError(f"cannot verify replication package: {exc}") from exc
    verification_contract = (
        _V2_VERIFICATION_CONTRACT
        if manifest["package_version"] == 2
        else _V1_VERIFICATION_CONTRACT
    )
    return {
        "status": "passed", "verification_scope": "package_file_integrity",
        "package_version": manifest["package_version"],
        "verification_contract": verification_contract,
        "package_manifest_sha256": expected_manifest_sha256,
        "verified_files": sorted(expected_files), "scientific_evidence_eligible": False,
        "limitations": ["Requires an independently trusted manifest hash.",
                        "Does not verify raw data, protocol validity, execution, or replication outcomes."],
    }


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _write(path: Path, value: Any) -> str:
    content = _bytes(value)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _redact_artifact_locators(value: dict[str, Any]) -> dict[str, Any]:
    def redact(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: "[redacted: obtain from authorized source]"
                if key == "locator"
                or key.endswith("_locator")
                or key.endswith("_artifact_root")
                or key == "run_attestation_schema_path"
                else redact(child)
                    for key, child in item.items()}
        if isinstance(item, list):
            return [redact(child) for child in item]
        return item
    return redact(value)


def export_replication_package(
    protocol: ExperimentProtocol,
    datasets: list[DatasetManifest],
    runs: list[ResearchRun],
    ethics_review_events: list[EthicsReviewEvent],
    output: Path,
    *,
    include_locators: bool = False,
) -> dict[str, Any]:
    """Export immutable commitments and lineage, never raw research data."""
    if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
        raise ValidationError("replication packages require a frozen protocol with a hash")
    from research_machine.application.ethics import (
        validate_ethics_review_event_chain,
        validate_original_review_artifact,
    )
    validate_original_review_artifact(protocol)
    selected_ethics_events = validate_ethics_review_event_chain(
        protocol,
        [item for item in ethics_review_events if item.protocol_id == protocol.protocol_id],
    )
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError(f"replication package path already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    dataset_by_id = {dataset.dataset_id: dataset for dataset in datasets}
    selected_ids = {dataset.dataset_id for dataset in datasets if dataset.protocol_id == protocol.protocol_id}
    pending = list(selected_ids)
    while pending:
        dataset = dataset_by_id[pending.pop()]
        for source_id in dataset.source_dataset_ids:
            if source_id not in dataset_by_id:
                raise ValidationError(f"dataset {dataset.dataset_id} references unavailable source dataset {source_id}")
            if source_id not in selected_ids:
                selected_ids.add(source_id)
                pending.append(source_id)
    selected_datasets = sorted(
        (dataset_by_id[dataset_id] for dataset_id in selected_ids),
        key=lambda item: item.dataset_id,
    )
    selected_runs = sorted(
        (run for run in runs if run.protocol_id == protocol.protocol_id),
        key=lambda item: item.run_id,
    )
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-", dir=root.parent) as temporary:
        staging = Path(temporary) / root.name
        staging.mkdir()
        dataset_records = [dataset.to_dict() for dataset in selected_datasets]
        run_records = [run.to_dict() for run in selected_runs]
        ethics_records = [item.to_dict() for item in selected_ethics_events]
        protocol_record = protocol.to_dict()
        if not include_locators:
            protocol_record = _redact_artifact_locators(protocol_record)
            dataset_records = [_redact_artifact_locators(item) for item in dataset_records]
            run_records = [_redact_artifact_locators(item) for item in run_records]
            ethics_records = [_redact_artifact_locators(item) for item in ethics_records]
        hashes = {
            "protocol.json": _write(staging / "protocol.json", protocol_record),
            "datasets.json": _write(staging / "datasets.json", dataset_records),
            "runs.json": _write(staging / "runs.json", run_records),
            "ethics-review-events.json": _write(
                staging / "ethics-review-events.json", ethics_records
            ),
        }
        instruction_bytes = _V2_INSTRUCTIONS.encode()
        (staging / "INSTRUCTIONS.md").write_bytes(instruction_bytes)
        hashes["INSTRUCTIONS.md"] = hashlib.sha256(instruction_bytes).hexdigest()
        manifest = {
            "package_version": 2,
            "privacy_mode": "metadata_only",
            "artifact_locator_policy": "included" if include_locators else "redacted",
            "protocol": {
                "protocol_id": protocol.protocol_id,
                "protocol_hash": protocol.protocol_hash,
                "registration_timestamp": protocol.registration_timestamp,
            },
            "dataset_ids": [dataset.dataset_id for dataset in selected_datasets],
            "run_ids": [run.run_id for run in selected_runs],
            "ethics_review_event_ids": [
                item.event_id for item in selected_ethics_events
            ],
            "latest_recorded_ethics_status": (
                selected_ethics_events[-1].status
                if selected_ethics_events
                else (
                    protocol.independent_review_decision
                    if protocol.human_subjects
                    else "not_applicable"
                )
            ),
            "replication_ethics_authorized": False,
            "files": hashes,
            "limitations": list(_V2_LIMITATIONS),
        }
        manifest_hash = _write(staging / "package-manifest.json", manifest)
        verify_replication_package(staging, manifest_hash)
        try:
            os.replace(staging, root)
        except OSError as exc:
            raise ValidationError(f"could not publish replication package atomically: {exc}") from exc
    return {
        "path": str(root),
        "package_version": 2,
        "verification_contract": _V2_VERIFICATION_CONTRACT,
        "package_manifest_sha256": manifest_hash,
        "privacy_mode": "metadata_only",
        "artifact_locator_policy": "included" if include_locators else "redacted",
        "dataset_count": len(selected_datasets),
        "run_count": len(selected_runs),
    }
