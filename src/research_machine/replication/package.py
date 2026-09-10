from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
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
    validate_protected_dataset_lineage_closure,
)
from research_machine.application.run_integrity import validate_run_payload_commitment
from research_machine.addons.result_contract import validate_analysis_result_contract


_V2_LIMITATIONS = [
    "Raw data are not included.",
    "Artifact locators may be unavailable to an independent executor.",
    "A package export does not validate replication results.",
    "Recorded ethics status does not authorize a new site, population, or replication.",
]


_V1_VERIFICATION_CONTRACT = "replication_package_v1_file_integrity"
_V2_VERIFICATION_CONTRACT = "replication_package_v2_guardrails"
_REDACTED_ARTIFACT_LOCATOR = "[redacted: obtain from authorized source]"
_DATASET_ARTIFACT_SCOPE = (
    "registered observation bytes under the supplied local artifact root"
)
_MEASUREMENT_CUSTODY_SCOPE = (
    "raw-source, transformation implementation, derived-output, and "
    "supporting-evidence bytes under the supplied local artifact root"
)

_STRUCTURED_RESULT_DETAIL_KEYS = {
    "canary_target_assessment",
    "causal_assumption_results",
    "instrument_inspection",
    "measurement_validity_results",
    "missingness_assessment_result",
    "preprocessing_conformance",
    "stream_timing_assessment",
    "temporal_order_assessment",
}
_WORKFLOW_ADJUDICATION_FIELDS = {
    "adjudication_version",
    "status",
    "protocol_id",
    "protocol_hash",
    "observation_dataset_id",
    "primary_estimate",
    "confirmatory_family",
    "conclusion",
    "quality_gate_adjudication",
    "provenance",
    "scientific_evidence_eligible",
    "canonical_status",
    "claim_ceiling",
}
_WORKFLOW_ADJUDICATION_CLAIM_CEILING = (
    "Study-level estimate and multiplicity-adjusted decisions under the frozen "
    "protocol and passed recorded gates; no proof, mechanism, unrestricted "
    "causality, or external validity."
)
_WORKFLOW_ADJUDICATION_NOTICE = (
    "Local composite verification only. Record and review a dedicated canonical "
    "composite run before creating evidence."
)


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


def _validate_package_timestamp(value: Any, field_name: str) -> str:
    timestamp = require_canonical_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be valid ISO-8601") from exc
    if parsed.utcoffset() is None:
        raise ValidationError(f"{field_name} must include a UTC offset")
    return timestamp


def _validate_packaged_root(value: Any, field_name: str, locator_policy: str) -> str:
    root = require_canonical_text(value, field_name)
    if locator_policy == "redacted":
        if root != _REDACTED_ARTIFACT_LOCATOR:
            raise ValidationError(
                f"{field_name} must use the package redaction placeholder"
            )
    elif not root.strip():
        raise ValidationError(f"{field_name} must not be blank")
    return root


def _validate_packaged_artifact_integrity(
    value: Any,
    *,
    label: str,
    expected_artifact_sha256s: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} artifact_integrity must be an object")
    required = {
        "status",
        "verification_profile",
        "artifact_count",
        "artifact_set_sha256",
        "all_artifacts_match",
        "attestation_required",
        "attestation_schema_sha256",
        "attestation_schema_matches_commitment",
        "attestation_schema_valid",
        "attestation_consistent",
        "findings",
        "artifacts",
        "conclusion_ceiling",
    }
    if set(value) != required:
        raise ValidationError(f"{label} artifact_integrity fields do not match the contract")
    if value.get("status") != "passed" or value.get("all_artifacts_match") is not True:
        raise ValidationError(f"{label} artifact_integrity must retain a passed byte check")
    require_canonical_text(
        value.get("verification_profile"),
        f"{label} artifact_integrity verification_profile",
    )
    require_sha256(
        value.get("artifact_set_sha256"),
        f"{label} artifact_integrity artifact_set_sha256",
    )
    if not isinstance(value.get("attestation_required"), bool):
        raise ValidationError(f"{label} artifact_integrity attestation_required must be boolean")
    if value.get("attestation_schema_sha256") is not None:
        require_sha256(
            value.get("attestation_schema_sha256"),
            f"{label} artifact_integrity attestation_schema_sha256",
        )
    for optional in (
        "attestation_schema_matches_commitment",
        "attestation_schema_valid",
        "attestation_consistent",
    ):
        if value.get(optional) is not None and not isinstance(value.get(optional), bool):
            raise ValidationError(
                f"{label} artifact_integrity {optional} must be boolean or null"
            )
    if not isinstance(value.get("findings"), list) or value["findings"]:
        raise ValidationError(f"{label} artifact_integrity findings must be an empty array")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValidationError(f"{label} artifact_integrity artifacts must be an array")
    count = value.get("artifact_count")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(artifacts)
        or count < 1
    ):
        raise ValidationError(f"{label} artifact_integrity artifact_count is invalid")
    observed_expected: list[str] = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise ValidationError(f"{label} artifact_integrity artifact must be an object")
        require_canonical_text(
            artifact.get("locator"),
            f"{label} artifact_integrity artifact {index} locator",
        )
        expected_sha = require_sha256(
            artifact.get("expected_sha256"),
            f"{label} artifact_integrity artifact {index} expected_sha256",
        )
        observed_sha = require_sha256(
            artifact.get("observed_sha256"),
            f"{label} artifact_integrity artifact {index} observed_sha256",
        )
        if expected_sha != observed_sha or artifact.get("status") != "passed":
            raise ValidationError(
                f"{label} artifact_integrity artifact observations must retain passed matching digests"
            )
        for size_field in ("expected_size_bytes", "observed_size_bytes"):
            size = artifact.get(size_field)
            if size is not None and (
                isinstance(size, bool) or not isinstance(size, int) or size < 0
            ):
                raise ValidationError(
                    f"{label} artifact_integrity artifact {size_field} must be non-negative or null"
                )
        observed_expected.append(expected_sha)
    if expected_artifact_sha256s is not None and observed_expected != expected_artifact_sha256s:
        raise ValidationError(
            f"{label} artifact_integrity no longer matches packaged artifact digests"
        )
    require_canonical_text(
        value.get("conclusion_ceiling"),
        f"{label} artifact_integrity conclusion_ceiling",
    )
    return value


def _validate_packaged_protected_dataset_verification(
    *,
    protocol: ExperimentProtocol,
    dataset: DatasetManifest,
    locator_policy: str,
    ethics_events_by_id: dict[str, EthicsReviewEvent],
) -> None:
    metadata = dataset.metadata
    dataset_id = dataset.dataset_id
    protected_role = dataset.role in {DatasetRole.CONFIRMATORY, DatasetRole.REPLICATION}

    artifact_receipt = metadata.get("dataset_artifact_verification")
    if protected_role and not dataset.synthetic:
        if not isinstance(artifact_receipt, dict):
            raise ValidationError(
                f"package protected dataset {dataset_id} lacks portable artifact verification"
            )
        if set(artifact_receipt) != {
            "verification_version",
            "verified_at",
            "verified_by",
            "dataset_artifact_root",
            "protocol_hash",
            "artifact_integrity",
            "scope",
            "scientific_interpretation_verified",
        }:
            raise ValidationError(
                f"package protected dataset {dataset_id} artifact verification fields do not match the contract"
            )
        if artifact_receipt.get("verification_version") != 1:
            raise ValidationError(
                f"package protected dataset {dataset_id} artifact verification version is unsupported"
            )
        _validate_package_timestamp(
            artifact_receipt.get("verified_at"),
            f"package protected dataset {dataset_id} artifact verification time",
        )
        require_canonical_text(
            artifact_receipt.get("verified_by"),
            f"package protected dataset {dataset_id} artifact verifier",
        )
        _validate_packaged_root(
            artifact_receipt.get("dataset_artifact_root"),
            f"package protected dataset {dataset_id} dataset_artifact_root",
            locator_policy,
        )
        if artifact_receipt.get("protocol_hash") != protocol.protocol_hash:
            raise ValidationError(
                f"package protected dataset {dataset_id} artifact verification does not match the protocol hash"
            )
        if artifact_receipt.get("scope") != _DATASET_ARTIFACT_SCOPE:
            raise ValidationError(
                f"package protected dataset {dataset_id} artifact verification scope changed"
            )
        if artifact_receipt.get("scientific_interpretation_verified") is not False:
            raise ValidationError(
                f"package protected dataset {dataset_id} artifact verification must remain non-interpretive"
            )
        _validate_packaged_artifact_integrity(
            artifact_receipt.get("artifact_integrity"),
            label=f"package protected dataset {dataset_id} artifact verification",
            expected_artifact_sha256s=[artifact.sha256 for artifact in dataset.artifacts],
        )
    elif artifact_receipt is not None:
        raise ValidationError(
            f"package dataset {dataset_id} contains unexpected artifact verification"
        )

    custody_receipt = metadata.get("measurement_custody_verification")
    if protocol.measurement_custody_requirements or custody_receipt is not None:
        if not isinstance(custody_receipt, dict):
            raise ValidationError(
                f"package dataset {dataset_id} lacks portable measurement custody verification"
            )
        if set(custody_receipt) != {
            "verification_version",
            "verified_at",
            "verified_by",
            "custody_artifact_root",
            "custody_receipt_sha256",
            "protocol_hash",
            "required_gate_ids",
            "artifact_integrity",
            "scope",
            "scientific_interpretation_verified",
        }:
            raise ValidationError(
                f"package dataset {dataset_id} measurement custody verification fields do not match the contract"
            )
        if custody_receipt.get("verification_version") != 1:
            raise ValidationError(
                f"package dataset {dataset_id} measurement custody verification version is unsupported"
            )
        _validate_package_timestamp(
            custody_receipt.get("verified_at"),
            f"package dataset {dataset_id} measurement custody verification time",
        )
        require_canonical_text(
            custody_receipt.get("verified_by"),
            f"package dataset {dataset_id} measurement custody verifier",
        )
        _validate_packaged_root(
            custody_receipt.get("custody_artifact_root"),
            f"package dataset {dataset_id} custody_artifact_root",
            locator_policy,
        )
        require_sha256(
            custody_receipt.get("custody_receipt_sha256"),
            f"package dataset {dataset_id} custody_receipt_sha256",
        )
        if custody_receipt.get("protocol_hash") != protocol.protocol_hash:
            raise ValidationError(
                f"package dataset {dataset_id} measurement custody verification does not match the protocol hash"
            )
        if custody_receipt.get("required_gate_ids") != list(protocol.measurement_custody_requirements):
            raise ValidationError(
                f"package dataset {dataset_id} measurement custody required gates changed"
            )
        if custody_receipt.get("scope") != _MEASUREMENT_CUSTODY_SCOPE:
            raise ValidationError(
                f"package dataset {dataset_id} measurement custody verification scope changed"
            )
        if custody_receipt.get("scientific_interpretation_verified") is not False:
            raise ValidationError(
                f"package dataset {dataset_id} measurement custody verification must remain non-interpretive"
            )
        _validate_packaged_artifact_integrity(
            custody_receipt.get("artifact_integrity"),
            label=f"package dataset {dataset_id} measurement custody verification",
        )

    ethics_status = metadata.get("ethics_review_status_check")
    if protocol.human_subjects:
        if not isinstance(ethics_status, dict):
            raise ValidationError(
                f"package human-subject dataset {dataset_id} lacks portable ethics status check"
            )
        if ethics_status.get("status") != "active":
            raise ValidationError(
                f"package human-subject dataset {dataset_id} ethics status is not active"
            )
        if ethics_status.get("protocol_id") != protocol.protocol_id or ethics_status.get("protocol_hash") != protocol.protocol_hash:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} ethics status does not match the protocol"
            )
        basis = require_canonical_text(
            ethics_status.get("basis"),
            f"package human-subject dataset {dataset_id} ethics status basis",
        )
        if basis not in {"frozen_independent_review_decision", "append_only_ethics_review_event"}:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} ethics status basis is unsupported"
            )
        checked_at = _validate_package_timestamp(
            ethics_status.get("checked_at"),
            f"package human-subject dataset {dataset_id} ethics status checked_at",
        )
        event_id = ethics_status.get("review_event_id")
        if event_id is None:
            if basis != "frozen_independent_review_decision":
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics status lacks its review event"
                )
        else:
            if basis != "append_only_ethics_review_event":
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics status event basis changed"
                )
            event_id = require_canonical_text(
                event_id,
                f"package human-subject dataset {dataset_id} ethics review_event_id",
            )
            event = ethics_events_by_id.get(event_id)
            if event is None or event.status != "active":
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics status references an unavailable active event"
                )
            if ethics_status.get("event_artifact_sha256") != event.review_artifact_sha256:
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics status event artifact changed"
                )
            if event.expires_at is not None:
                expires_at = datetime.fromisoformat(
                    event.expires_at.replace("Z", "+00:00")
                )
                checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
                if expires_at < checked:
                    raise ValidationError(
                        f"package human-subject dataset {dataset_id} ethics status event expired before the dataset check"
                    )
        if ethics_status.get("reviewer_identity_authenticated", False) is not False:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} ethics status must not authenticate reviewer identity"
            )
        if ethics_status.get("substantive_adequacy_verified", False) is not False:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} ethics status must not verify substantive adequacy"
            )
    elif ethics_status is not None:
        raise ValidationError(
            f"package dataset {dataset_id} contains unexpected ethics status check"
        )

    condition_receipt = metadata.get("ethics_condition_verification")
    if protocol.human_subjects and protocol.independent_review_decision == "approved_with_conditions":
        if not isinstance(condition_receipt, dict):
            raise ValidationError(
                f"package human-subject dataset {dataset_id} lacks portable ethics condition verification"
            )
        discharge = metadata.get("ethics_condition_discharge")
        if not isinstance(discharge, dict) or set(discharge) != {
            "discharge_id",
            "protocol_id",
            "protocol_hash",
            "independent_review_receipt",
            "assessor",
            "assessed_at",
            "evidence_artifacts",
            "conditions",
        }:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} lacks the retained ethics condition discharge"
            )
        if (
            discharge.get("protocol_id") != protocol.protocol_id
            or discharge.get("protocol_hash") != protocol.protocol_hash
            or discharge.get("independent_review_receipt")
            != protocol.independent_review_receipt
        ):
            raise ValidationError(
                f"package human-subject dataset {dataset_id} retained ethics condition discharge does not match the protocol"
            )
        require_canonical_text(
            discharge.get("discharge_id"),
            f"package human-subject dataset {dataset_id} discharge_id",
        )
        require_canonical_text(
            discharge.get("assessor"),
            f"package human-subject dataset {dataset_id} retained condition assessor",
        )
        _validate_package_timestamp(
            discharge.get("assessed_at"),
            f"package human-subject dataset {dataset_id} retained condition assessed_at",
        )
        discharge_evidence = discharge.get("evidence_artifacts")
        if not isinstance(discharge_evidence, list) or not discharge_evidence:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} retained condition evidence artifacts are missing"
            )
        discharge_evidence_hashes: set[str] = set()
        for item in discharge_evidence:
            if not isinstance(item, dict) or set(item) != {
                "locator",
                "sha256",
                "size_bytes",
                "media_type",
            }:
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} retained condition evidence artifact is invalid"
                )
            _validate_packaged_root(
                item.get("locator"),
                f"package human-subject dataset {dataset_id} retained condition evidence locator",
                locator_policy,
            )
            digest = require_sha256(
                item.get("sha256"),
                f"package human-subject dataset {dataset_id} retained condition evidence sha256",
            )
            if digest in discharge_evidence_hashes:
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} repeats condition evidence digest"
                )
            discharge_evidence_hashes.add(digest)
            size = item.get("size_bytes")
            if size is not None and (
                isinstance(size, bool) or not isinstance(size, int) or size < 0
            ):
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} retained condition evidence size is invalid"
                )
            require_canonical_text(
                item.get("media_type"),
                f"package human-subject dataset {dataset_id} retained condition evidence media_type",
            )
        discharge_conditions = discharge.get("conditions")
        if (
            not isinstance(discharge_conditions, list)
            or not all(isinstance(item, dict) for item in discharge_conditions)
        ):
            raise ValidationError(
                f"package human-subject dataset {dataset_id} retained condition results are missing"
            )
        if condition_receipt.get("verification_version") != 1:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} ethics condition verification version is unsupported"
            )
        condition_verified_at = _validate_package_timestamp(
            condition_receipt.get("verified_at"),
            f"package human-subject dataset {dataset_id} condition verification time",
        )
        require_canonical_text(
            condition_receipt.get("verified_by"),
            f"package human-subject dataset {dataset_id} condition verifier",
        )
        _validate_packaged_root(
            condition_receipt.get("evidence_artifact_root"),
            f"package human-subject dataset {dataset_id} evidence_artifact_root",
            locator_policy,
        )
        require_sha256(
            condition_receipt.get("discharge_receipt_sha256"),
            f"package human-subject dataset {dataset_id} discharge_receipt_sha256",
        )
        if (
            condition_receipt.get("protocol_id") != protocol.protocol_id
            or condition_receipt.get("protocol_hash") != protocol.protocol_hash
            or condition_receipt.get("independent_review_receipt")
            != protocol.independent_review_receipt
            or condition_receipt.get("assessor") != discharge.get("assessor")
            or condition_receipt.get("assessed_at") != discharge.get("assessed_at")
        ):
            raise ValidationError(
                f"package human-subject dataset {dataset_id} ethics condition verification does not match the protocol"
            )
        require_canonical_text(
            condition_receipt.get("assessor"),
            f"package human-subject dataset {dataset_id} condition assessor",
        )
        _validate_package_timestamp(
            condition_receipt.get("assessed_at"),
            f"package human-subject dataset {dataset_id} condition assessed_at",
        )
        condition_results = condition_receipt.get("condition_results")
        location_checks = condition_receipt.get("evidence_location_checks")
        if (
            not isinstance(condition_results, list)
            or not all(isinstance(item, dict) for item in condition_results)
            or condition_results != discharge_conditions
            or [item.get("condition") for item in condition_results]
            != list(protocol.independent_review_conditions)
        ):
            raise ValidationError(
                f"package human-subject dataset {dataset_id} ethics condition results changed"
            )
        if (
            not isinstance(location_checks, list)
            or not all(isinstance(item, dict) for item in location_checks)
            or [item.get("condition") for item in location_checks]
            != list(protocol.independent_review_conditions)
        ):
            raise ValidationError(
                f"package human-subject dataset {dataset_id} ethics condition location checks changed"
            )
        verified_time = datetime.fromisoformat(
            condition_verified_at.replace("Z", "+00:00")
        )
        reviewed_time = datetime.fromisoformat(
            protocol.independent_reviewed_at.replace("Z", "+00:00")
        )
        assessed_time = datetime.fromisoformat(
            condition_receipt["assessed_at"].replace("Z", "+00:00")
        )
        if assessed_time < reviewed_time or assessed_time > verified_time:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} ethics condition chronology changed"
            )
        artifact_integrity = _validate_packaged_artifact_integrity(
            condition_receipt.get("artifact_integrity"),
            label=f"package human-subject dataset {dataset_id} ethics condition verification",
        )
        condition_artifact_digests = {
            item.get("expected_sha256")
            for item in artifact_integrity.get("artifacts", [])
            if isinstance(item, dict)
        }
        if condition_artifact_digests != discharge_evidence_hashes:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} condition evidence artifacts no longer match the integrity receipt"
            )
        location_by_condition = {
            item.get("condition"): item for item in location_checks
        }
        any_active_control = False
        for item in condition_results:
            if set(item) != {
                "condition",
                "compliance_status",
                "rationale",
                "evidence_sha256",
                "evidence_location",
                "valid_through",
            }:
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics condition result fields changed"
                )
            condition = require_canonical_text(
                item.get("condition"),
                f"package human-subject dataset {dataset_id} ethics condition",
            )
            status = require_canonical_text(
                item.get("compliance_status"),
                f"package human-subject dataset {dataset_id} ethics condition compliance_status",
            )
            if status not in {"satisfied", "control_active"}:
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics condition compliance_status changed"
                )
            require_canonical_text(
                item.get("rationale"),
                f"package human-subject dataset {dataset_id} ethics condition rationale",
            )
            evidence_sha = require_sha256(
                item.get("evidence_sha256"),
                f"package human-subject dataset {dataset_id} ethics condition evidence_sha256",
            )
            if evidence_sha not in condition_artifact_digests:
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics condition evidence digest is not packaged"
                )
            evidence_location = require_canonical_text(
                item.get("evidence_location"),
                f"package human-subject dataset {dataset_id} ethics condition evidence_location",
            )
            valid_through = item.get("valid_through")
            if status == "control_active":
                any_active_control = True
                horizon = datetime.fromisoformat(
                    _validate_package_timestamp(
                        valid_through,
                        f"package human-subject dataset {dataset_id} ethics condition valid_through",
                    ).replace("Z", "+00:00")
                )
                if horizon < verified_time:
                    raise ValidationError(
                        f"package human-subject dataset {dataset_id} ethics condition control horizon predates verification"
                    )
            elif valid_through is not None:
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} satisfied ethics condition cannot carry a validity horizon"
                )
            check = location_by_condition.get(condition)
            if not isinstance(check, dict):
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics condition location check is missing"
                )
            if set(check) != {
                "condition",
                "evidence_sha256",
                "evidence_location",
                "location_kind",
                "selected_value_sha256",
                "status",
            }:
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics condition location check fields changed"
                )
            if (
                check.get("evidence_sha256") != evidence_sha
                or check.get("evidence_location") != evidence_location
            ):
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics condition location check no longer matches the condition result"
                )
            location_kind = check.get("location_kind")
            check_status = check.get("status")
            if location_kind == "json_pointer":
                require_sha256(
                    check.get("selected_value_sha256"),
                    f"package human-subject dataset {dataset_id} condition selected_value_sha256",
                )
                if check_status != "resolved":
                    raise ValidationError(
                        f"package human-subject dataset {dataset_id} JSON condition evidence must remain resolved"
                    )
            elif location_kind == "human_inspectable":
                if (
                    check.get("selected_value_sha256") is not None
                    or check_status != "recorded_not_machine_resolved"
                ):
                    raise ValidationError(
                        f"package human-subject dataset {dataset_id} human-inspectable condition evidence cannot claim machine resolution"
                    )
            else:
                raise ValidationError(
                    f"package human-subject dataset {dataset_id} ethics condition location kind changed"
                )
        if condition_receipt.get("reviewer_identity_authenticated") is not False:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} condition verification must not authenticate reviewer identity"
            )
        if condition_receipt.get("condition_truth_independently_established") is not False:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} condition verification must not establish condition truth"
            )
        if condition_receipt.get("ongoing_controls_require_continued_monitoring") is not any_active_control:
            raise ValidationError(
                f"package human-subject dataset {dataset_id} condition monitoring flag changed"
            )
    elif condition_receipt is not None:
        raise ValidationError(
            f"package dataset {dataset_id} contains unexpected ethics condition verification"
        )


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


def _reject_skipped_gate_structured_results(
    *, run_id: str, gate: QualityGateResult
) -> None:
    if gate.status is not QualityGateStatus.SKIPPED:
        return
    if is_canonical_sha256(gate.details.get("evidence_sha256")):
        raise ValidationError(
            f"package run {run_id} skipped quality gate {gate.gate_id} "
            "cannot cite evidence_sha256"
        )
    retained = sorted(
        key
        for key in _STRUCTURED_RESULT_DETAIL_KEYS.intersection(gate.details)
        if _contains_canonical_sha256(gate.details[key])
        or not _contains_template_placeholder(gate.details[key])
    )
    if retained:
        raise ValidationError(
            f"package run {run_id} skipped quality gate {gate.gate_id} "
            "cannot report structured results: "
            + ", ".join(retained)
        )


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
    derived_fields = {
        "check_count",
        "failed_check_count",
        "warning_check_count",
        "finding_count",
    }
    allowed_fields = required_fields | derived_fields
    if set(assessment) != allowed_fields:
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
    evidence_sha256 = require_sha256(
        gate.details.get("evidence_sha256"),
        f"package run {run_id} gate {gate.gate_id} evidence_sha256",
    )
    if evidence_sha256 != record_sha256:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} evidence does not match temporal-order assessment record"
        )
    if not any(
        artifact.locator == locator and artifact.sha256 == record_sha256
        for artifact in output_artifacts
    ):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} temporal-order assessment record is not a declared output artifact"
        )
    counts: dict[str, int] = {}
    for field in derived_fields:
        value = assessment[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValidationError(
                f"package run {run_id} gate {gate.gate_id} temporal_order_assessment {field} must be a non-negative integer"
            )
        counts[field] = value
    if "check_count" in counts:
        for field in ("failed_check_count", "warning_check_count"):
            if field in counts and counts[field] > counts["check_count"]:
                raise ValidationError(
                    f"package run {run_id} gate {gate.gate_id} temporal_order_assessment {field} exceeds check_count"
                )
        if (
            "failed_check_count" in counts
            and "warning_check_count" in counts
            and counts["failed_check_count"] + counts["warning_check_count"] > counts["check_count"]
        ):
            raise ValidationError(
                f"package run {run_id} gate {gate.gate_id} temporal_order_assessment check counts are inconsistent"
            )
    if gate.status is QualityGateStatus.PASSED:
        if declared_status != "temporal_order_passed":
            raise ValidationError(
                f"package run {run_id} passed temporal-order gate {gate.gate_id} lacks passed assessment metadata"
            )
        if counts.get("failed_check_count", 0) != 0:
            raise ValidationError(
                f"package run {run_id} passed temporal-order gate {gate.gate_id} retains failed checks"
            )
    elif gate.status is QualityGateStatus.FAILED:
        if declared_status != "temporal_order_failed":
            raise ValidationError(
                f"package run {run_id} failed temporal-order gate {gate.gate_id} lacks failed assessment metadata"
            )
        if (
            "failed_check_count" in counts
            and "finding_count" in counts
            and counts["failed_check_count"] == 0
            and counts["finding_count"] == 0
        ):
            raise ValidationError(
                f"package run {run_id} failed temporal-order gate {gate.gate_id} lacks failed-check or finding summary"
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
    derived_fields = {
        "stream_count",
        "temporal_metadata_status",
    }
    allowed_fields = required_fields | derived_fields
    if set(inspection) != allowed_fields:
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
    stream_count = inspection["stream_count"]
    if (
        not isinstance(stream_count, int)
        or isinstance(stream_count, bool)
        or stream_count < 0
    ):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} instrument_inspection stream_count must be a non-negative integer"
        )
    temporal_metadata_status = require_canonical_text(
        inspection["temporal_metadata_status"],
        f"{prefix}.temporal_metadata_status",
    )
    if temporal_metadata_status not in {"proposed_unverified", "not_provided"}:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} instrument_inspection temporal_metadata_status is unsupported"
        )
    if temporal_metadata_status == "not_provided" and stream_count != 0:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} instrument_inspection not_provided temporal metadata requires zero streams"
        )
    if temporal_metadata_status == "proposed_unverified" and stream_count == 0:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} instrument_inspection proposed temporal metadata requires streams"
        )
    evidence_sha256 = require_sha256(
        gate.details.get("evidence_sha256"),
        f"package run {run_id} gate {gate.gate_id} evidence_sha256",
    )
    if evidence_sha256 != record_sha256:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} evidence does not match instrument inspection record"
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
    derived_fields = {
        "required_stream_count",
        "required_stream_failure_count",
        "event_count",
        "event_failure_count",
        "finding_count",
    }
    allowed_fields = required_fields | derived_fields
    if set(assessment) != allowed_fields:
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
    evidence_sha256 = require_sha256(
        gate.details.get("evidence_sha256"),
        f"package run {run_id} gate {gate.gate_id} evidence_sha256",
    )
    if evidence_sha256 != record_sha256:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} evidence does not match stream-timing assessment record"
        )
    if not any(
        artifact.locator == locator and artifact.sha256 == record_sha256
        for artifact in output_artifacts
    ):
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} stream-timing assessment record is not a declared output artifact"
        )
    counts: dict[str, int] = {}
    for field in derived_fields:
        value = assessment[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValidationError(
                f"package run {run_id} gate {gate.gate_id} stream_timing_assessment {field} must be a non-negative integer"
            )
        counts[field] = value
    if counts["required_stream_failure_count"] > counts["required_stream_count"]:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} stream_timing_assessment required_stream_failure_count exceeds required_stream_count"
        )
    if counts["event_failure_count"] > counts["event_count"]:
        raise ValidationError(
            f"package run {run_id} gate {gate.gate_id} stream_timing_assessment event_failure_count exceeds event_count"
        )
    if gate.status is QualityGateStatus.PASSED:
        if declared_status != "timing_feasibility_passed":
            raise ValidationError(
                f"package run {run_id} passed stream-timing gate {gate.gate_id} lacks passed assessment metadata"
            )
        if (
            counts["required_stream_failure_count"] != 0
            or counts["event_failure_count"] != 0
        ):
            raise ValidationError(
                f"package run {run_id} passed stream-timing gate {gate.gate_id} retains stream or event failures"
            )
    elif gate.status is QualityGateStatus.FAILED:
        if declared_status != "timing_feasibility_failed":
            raise ValidationError(
                f"package run {run_id} failed stream-timing gate {gate.gate_id} lacks failed assessment metadata"
            )
        if (
            counts["required_stream_failure_count"] == 0
            and counts["event_failure_count"] == 0
            and counts["finding_count"] == 0
        ):
            raise ValidationError(
                f"package run {run_id} failed stream-timing gate {gate.gate_id} lacks failure summary"
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
    verified_results_by_sha: dict[str, Any],
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
    if gate.status is QualityGateStatus.SKIPPED:
        raise ValidationError(
            f"package run {run_id} skipped canary assessment gate {gate.gate_id} cannot report results"
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
    optional_fields = {"selected_value_sha256"}
    if not required_fields <= set(assessment) or set(assessment) - required_fields - optional_fields:
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
    if (
        gate.status is QualityGateStatus.PASSED
        and status != "consistent_with_revealed_target"
    ):
        raise ValidationError(
            f"package run {run_id} passed canary gate {gate.gate_id} requires revealed-target consistency"
        )
    if (
        gate.status is QualityGateStatus.WARNING
        and status not in {"mixed", "inconclusive"}
    ):
        raise ValidationError(
            f"package run {run_id} warning canary gate {gate.gate_id} requires mixed or inconclusive status"
        )
    if (
        gate.status is QualityGateStatus.FAILED
        and status not in {"follows_comparator_or_decoy", "follows_no_target"}
    ):
        raise ValidationError(
            f"package run {run_id} failed canary gate {gate.gate_id} requires comparator, decoy, or no-target status"
        )
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
    location = require_canonical_text(
        assessment["evidence_location"], f"{prefix}.evidence_location"
    )
    selected_value_sha256 = assessment.get("selected_value_sha256")
    if selected_value_sha256 is not None:
        selected_value_sha256 = require_sha256(
            selected_value_sha256, f"{prefix}.selected_value_sha256"
        )
    selected_value = _resolve_analysis_result_location(
        run_id=run_id,
        digest=evidence_sha256,
        location=location,
        field_name="canary assessment evidence_location",
        verified_results_by_sha=verified_results_by_sha,
    )
    if selected_value is not None:
        expected_selected_value_sha256 = _result_body_sha256(selected_value)
        if selected_value_sha256 is None:
            raise ValidationError(
                f"package run {run_id} gate {gate.gate_id} canary assessment lacks selected_value_sha256"
            )
        if selected_value_sha256 != expected_selected_value_sha256:
            raise ValidationError(
                f"package run {run_id} gate {gate.gate_id} canary selected_value_sha256 disagrees with retained result body"
            )


def _measurement_value_domain_sha256(definition: dict[str, Any]) -> str:
    return hashlib.sha256(_bytes({
        "measurement_id": definition.get("measurement_id"),
        "scale_type": definition.get("scale_type"),
        "unit": definition.get("unit"),
        "admissible_values": definition.get("admissible_values"),
        "missing_value_codes": definition.get("missing_value_codes"),
        "valid_min": definition.get("valid_min"),
        "valid_max": definition.get("valid_max"),
    })).hexdigest()


def _validate_retained_handoff_body_digest(
    *,
    run_id: str,
    handoff_name: str,
    body: dict[str, Any],
    digest: str,
    size_bytes: int,
) -> None:
    body_bytes = _bytes(body)
    if (
        hashlib.sha256(body_bytes).hexdigest() != digest
        or len(body_bytes) != size_bytes
    ):
        raise ValidationError(
            f"package run {run_id} {handoff_name} body does not match output hash and size"
        )


def _validate_execution_handoff_measurement_value_check(run: ResearchRun) -> None:
    handoff = run.metadata.get("execution_handoff")
    if handoff is None:
        return
    if not isinstance(handoff, dict):
        raise ValidationError(
            f"package run {run.run_id} execution_handoff must be an object"
        )
    receipt = handoff.get("receipt")
    if not isinstance(receipt, dict):
        raise ValidationError(
            f"package run {run.run_id} execution_handoff receipt must be an object"
        )
    binding = receipt.get("protocol_design_check")
    if not isinstance(binding, dict):
        return
    contracts = binding.get("measurement_contracts")
    if not contracts:
        return
    if not isinstance(contracts, list):
        raise ValidationError(
            f"package run {run.run_id} execution_handoff measurement contracts must be an array"
        )
    check = receipt.get("measurement_value_check")
    if not isinstance(check, dict) or check.get("status") != "passed":
        raise ValidationError(
            f"package run {run.run_id} execution_handoff measurement value check is invalid"
        )
    if (
        check.get("scope")
        != "source_values_against_frozen_scale_domain_bounds_and_missing_codes"
    ):
        raise ValidationError(
            f"package run {run.run_id} execution_handoff measurement value check scope is invalid"
        )
    rows = receipt.get("input", {}).get("row_count")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise ValidationError(
            f"package run {run.run_id} execution_handoff input row_count is invalid"
        )
    measurements = check.get("measurements")
    if not isinstance(measurements, list) or len(measurements) != len(contracts):
        raise ValidationError(
            f"package run {run.run_id} execution_handoff measurement value check coverage is invalid"
        )
    required_fields = {
        "measurement_id",
        "data_column",
        "scale_type",
        "unit",
        "value_domain_sha256",
        "observed_count",
        "missing_count",
        "status",
    }
    for index, (contract, measurement) in enumerate(zip(contracts, measurements)):
        if not isinstance(contract, dict) or not isinstance(measurement, dict):
            raise ValidationError(
                f"package run {run.run_id} execution_handoff measurement value check entries are invalid"
            )
        if set(measurement) != required_fields:
            raise ValidationError(
                f"package run {run.run_id} execution_handoff measurement value check fields are invalid"
            )
        for field in ("measurement_id", "data_column", "scale_type", "unit"):
            if measurement.get(field) != contract.get(field):
                raise ValidationError(
                    f"package run {run.run_id} execution_handoff measurement value check disagrees with frozen contract at index {index}"
                )
        digest = require_sha256(
            measurement["value_domain_sha256"],
            f"package run {run.run_id} execution_handoff measurement_value_check.value_domain_sha256",
        )
        if digest != _measurement_value_domain_sha256(contract):
            raise ValidationError(
                f"package run {run.run_id} execution_handoff measurement value check domain digest is invalid"
            )
        observed_count = measurement.get("observed_count")
        missing_count = measurement.get("missing_count")
        if (
            isinstance(observed_count, bool)
            or isinstance(missing_count, bool)
            or not isinstance(observed_count, int)
            or not isinstance(missing_count, int)
            or observed_count < 0
            or missing_count < 0
            or observed_count + missing_count != rows
            or measurement.get("status") != "passed"
        ):
            raise ValidationError(
                f"package run {run.run_id} execution_handoff measurement value check counts are invalid"
            )


def _verified_handoff_results_by_output_sha(
    *,
    protocol: ExperimentProtocol,
    run: ResearchRun,
    output_artifacts: list[DatasetArtifact],
) -> dict[str, Any]:
    execution_handoff = run.metadata.get("execution_handoff")
    adjudication_handoff = run.metadata.get("workflow_adjudication_handoff")
    if execution_handoff is not None and adjudication_handoff is not None:
        raise ValidationError(
            f"package run {run.run_id} cannot retain both execution and adjudication handoffs"
        )
    if execution_handoff is None and adjudication_handoff is None:
        return {}
    if adjudication_handoff is not None:
        if not isinstance(adjudication_handoff, dict):
            raise ValidationError(
                f"package run {run.run_id} workflow_adjudication_handoff must be an object"
            )
        receipt = adjudication_handoff.get("receipt")
        adjudication = adjudication_handoff.get("adjudication")
        if not isinstance(receipt, dict) or not isinstance(adjudication, dict):
            raise ValidationError(
                f"package run {run.run_id} workflow_adjudication_handoff receipt and adjudication must be objects"
            )
        if set(receipt) != {
            "adjudication_receipt_version",
            "status",
            "manifest",
            "output",
            "scientific_evidence_eligible",
            "notice",
        }:
            raise ValidationError(
                f"package run {run.run_id} workflow_adjudication_handoff receipt fields are invalid"
            )
        if (
            receipt.get("adjudication_receipt_version") != 1
            or receipt.get("status") != "completed"
            or receipt.get("scientific_evidence_eligible") is not False
            or receipt.get("notice") != _WORKFLOW_ADJUDICATION_NOTICE
        ):
            raise ValidationError(
                f"package run {run.run_id} workflow_adjudication_handoff receipt semantics are invalid"
            )
        if set(adjudication) != _WORKFLOW_ADJUDICATION_FIELDS:
            raise ValidationError(
                f"package run {run.run_id} workflow_adjudication_handoff adjudication fields are invalid"
            )
        if (
            adjudication.get("adjudication_version") != 1
            or adjudication.get("status") != "passed"
            or adjudication.get("protocol_id") != protocol.protocol_id
            or adjudication.get("protocol_hash") != protocol.protocol_hash
            or adjudication.get("observation_dataset_id") not in run.dataset_ids
            or adjudication.get("scientific_evidence_eligible") is not False
            or adjudication.get("canonical_status")
            != "reviewed_composite_run_required"
            or adjudication.get("claim_ceiling")
            != _WORKFLOW_ADJUDICATION_CLAIM_CEILING
        ):
            raise ValidationError(
                f"package run {run.run_id} workflow_adjudication_handoff adjudication authority boundary is invalid"
            )
        output = receipt.get("output")
        if (
            not isinstance(output, dict)
            or output.get("locator")
            not in {"workflow-adjudication.json", _REDACTED_ARTIFACT_LOCATOR}
            or isinstance(output.get("size_bytes"), bool)
            or not isinstance(output.get("size_bytes"), int)
            or output["size_bytes"] <= 0
        ):
            raise ValidationError(
                f"package run {run.run_id} workflow_adjudication_handoff output is invalid"
            )
        digest = require_sha256(
            output.get("sha256"),
            f"package run {run.run_id} workflow_adjudication_handoff output.sha256",
        )
        if not any(
            artifact.sha256 == digest
            and artifact.locator == output.get("locator")
            and artifact.size_bytes == output["size_bytes"]
            for artifact in output_artifacts
        ):
            raise ValidationError(
                f"package run {run.run_id} workflow_adjudication_handoff output is not a declared run artifact"
            )
        _validate_retained_handoff_body_digest(
            run_id=run.run_id,
            handoff_name="workflow_adjudication_handoff",
            body=adjudication,
            digest=digest,
            size_bytes=output["size_bytes"],
        )
        return {digest: adjudication}
    handoff = execution_handoff
    if not isinstance(handoff, dict):
        raise ValidationError(
            f"package run {run.run_id} execution_handoff must be an object"
        )
    receipt = handoff.get("receipt")
    result = handoff.get("result")
    if not isinstance(receipt, dict) or not isinstance(result, dict):
        raise ValidationError(
            f"package run {run.run_id} execution_handoff receipt and result must be objects"
        )
    try:
        validate_analysis_result_contract(result)
    except ValidationError as exc:
        raise ValidationError(
            f"package run {run.run_id} execution_handoff result contract is invalid: {exc}"
        ) from exc
    addon = receipt.get("addon")
    if (
        not isinstance(addon, dict)
        or not isinstance(receipt.get("method"), str)
        or receipt["method"] != result.get("method")
        or receipt.get("maximum_inference_level")
        != result.get("maximum_inference_level")
        or addon.get("addon_id") != result.get("addon_id")
        or addon.get("version") != result.get("addon_version")
        or receipt.get("randomness_control") != result.get("randomness_control")
        or receipt.get("randomness_binding") != result.get("randomness_binding")
    ):
        raise ValidationError(
            f"package run {run.run_id} execution_handoff receipt/result authority identity disagrees"
        )
    output = receipt.get("output")
    if (
        not isinstance(output, dict)
        or output.get("locator")
        not in {"analysis-result.json", _REDACTED_ARTIFACT_LOCATOR}
        or isinstance(output.get("size_bytes"), bool)
        or not isinstance(output.get("size_bytes"), int)
        or output["size_bytes"] <= 0
    ):
        raise ValidationError(
            f"package run {run.run_id} execution_handoff output is invalid"
        )
    digest = require_sha256(
        output.get("sha256"),
        f"package run {run.run_id} execution_handoff output.sha256",
    )
    if not any(
        artifact.sha256 == digest
        and artifact.locator == output["locator"]
        and artifact.size_bytes == output["size_bytes"]
        for artifact in output_artifacts
    ):
        raise ValidationError(
            f"package run {run.run_id} execution_handoff output is not a declared run artifact"
        )
    _validate_retained_handoff_body_digest(
        run_id=run.run_id,
        handoff_name="execution_handoff",
        body=result,
        digest=digest,
        size_bytes=output["size_bytes"],
    )
    return {digest: result}


def _validate_analysis_result_location(
    *,
    run_id: str,
    digest: str,
    location: str,
    field_name: str,
    verified_results_by_sha: dict[str, Any],
) -> None:
    _resolve_analysis_result_location(
        run_id=run_id,
        digest=digest,
        location=location,
        field_name=field_name,
        verified_results_by_sha=verified_results_by_sha,
    )


def _resolve_analysis_result_location(
    *,
    run_id: str,
    digest: str,
    location: str,
    field_name: str,
    verified_results_by_sha: dict[str, Any],
) -> Any | None:
    result = verified_results_by_sha.get(digest)
    if result is None:
        return None
    if not location.startswith("/"):
        raise ValidationError(
            f"package run {run_id} {field_name} in the verified analysis output requires an absolute JSON Pointer"
        )
    return _resolve_json_pointer(
        result,
        location,
        f"package run {run_id} {field_name}",
    )


def _result_body_sha256(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _validate_control_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
    verified_results_by_sha: dict[str, Any],
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
        optional_fields = {"selected_value_sha256"}
        if (
            not isinstance(result, dict)
            or not required_fields <= set(result)
            or set(result) - required_fields - optional_fields
        ):
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
        selected_value_sha256 = result.get("selected_value_sha256")
        if selected_value_sha256 is not None:
            selected_value_sha256 = require_sha256(
                selected_value_sha256, f"{prefix}.selected_value_sha256"
            )
        selected_value = _resolve_analysis_result_location(
            run_id=run_id,
            digest=digest,
            location=result["evidence_location"],
            field_name=f"control {control.control_id} evidence_location",
            verified_results_by_sha=verified_results_by_sha,
        )
        if selected_value is not None:
            expected_selected_value_sha256 = _result_body_sha256(selected_value)
            if selected_value_sha256 is None:
                raise ValidationError(
                    f"package run {run_id} gate {gate.gate_id} control {control.control_id} lacks selected_value_sha256"
                )
            if selected_value_sha256 != expected_selected_value_sha256:
                raise ValidationError(
                    f"package run {run_id} gate {gate.gate_id} control {control.control_id} selected_value_sha256 disagrees with retained result body"
                )


def _validate_measurement_validity_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
    verified_results_by_sha: dict[str, Any],
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
        optional_fields = {"selected_value_sha256"}
        if (
            not isinstance(result, dict)
            or not required_fields <= set(result)
            or set(result) - required_fields - optional_fields
        ):
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
        selected_value_sha256 = result.get("selected_value_sha256")
        if selected_value_sha256 is not None:
            selected_value_sha256 = require_sha256(
                selected_value_sha256, f"{prefix}.selected_value_sha256"
            )
        selected_value = _resolve_analysis_result_location(
            run_id=run_id,
            digest=digest,
            location=result["evidence_location"],
            field_name=f"measurement validity {check.check_id} evidence_location",
            verified_results_by_sha=verified_results_by_sha,
        )
        if selected_value is not None:
            expected_selected_value_sha256 = _result_body_sha256(selected_value)
            if selected_value_sha256 is None:
                raise ValidationError(
                    f"package run {run_id} gate {gate.gate_id} measurement validity {check.check_id} lacks selected_value_sha256"
                )
            if selected_value_sha256 != expected_selected_value_sha256:
                raise ValidationError(
                    f"package run {run_id} gate {gate.gate_id} measurement validity {check.check_id} selected_value_sha256 disagrees with retained result body"
                )


def _validate_missingness_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
    verified_results_by_sha: dict[str, Any],
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
    optional_fields = {"selected_value_sha256"}
    if (
        not isinstance(result, dict)
        or not required_fields <= set(result)
        or set(result) - required_fields - optional_fields
    ):
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
    selected_value_sha256 = result.get("selected_value_sha256")
    if selected_value_sha256 is not None:
        selected_value_sha256 = require_sha256(
            selected_value_sha256, f"{prefix}.selected_value_sha256"
        )
    selected_value = _resolve_analysis_result_location(
        run_id=run_id,
        digest=digest,
        location=result["evidence_location"],
        field_name="missingness assessment evidence_location",
        verified_results_by_sha=verified_results_by_sha,
    )
    if selected_value is not None:
        expected_selected_value_sha256 = _result_body_sha256(selected_value)
        if selected_value_sha256 is None:
            raise ValidationError(
                f"package run {run_id} gate {gate.gate_id} missingness assessment lacks selected_value_sha256"
            )
        if selected_value_sha256 != expected_selected_value_sha256:
            raise ValidationError(
                f"package run {run_id} gate {gate.gate_id} missingness selected_value_sha256 disagrees with retained result body"
            )


def _validate_causal_assumption_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    run_id: str,
    gate: QualityGateResult,
    output_artifacts: list[DatasetArtifact],
    verified_results_by_sha: dict[str, Any],
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
        optional_fields = {"selected_value_sha256"}
        if (
            not isinstance(result, dict)
            or not required_fields <= set(result)
            or set(result) - required_fields - optional_fields
        ):
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
        selected_value_sha256 = result.get("selected_value_sha256")
        if selected_value_sha256 is not None:
            selected_value_sha256 = require_sha256(
                selected_value_sha256, f"{prefix}.selected_value_sha256"
            )
        selected_value = _resolve_analysis_result_location(
            run_id=run_id,
            digest=digest,
            location=result["evidence_location"],
            field_name=f"causal assumption {category} evidence_location",
            verified_results_by_sha=verified_results_by_sha,
        )
        if selected_value is not None:
            expected_selected_value_sha256 = _result_body_sha256(selected_value)
            if selected_value_sha256 is None:
                raise ValidationError(
                    f"package run {run_id} gate {gate.gate_id} causal assumption {category} lacks selected_value_sha256"
                )
            if selected_value_sha256 != expected_selected_value_sha256:
                raise ValidationError(
                    f"package run {run_id} gate {gate.gate_id} causal assumption {category} selected_value_sha256 disagrees with retained result body"
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
            ethics_events_by_id = {item.event_id: item for item in events}
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
                _validate_packaged_protected_dataset_verification(
                    protocol=protocol,
                    dataset=dataset,
                    locator_policy=manifest["artifact_locator_policy"],
                    ethics_events_by_id=ethics_events_by_id,
                )
                if manifest.get("artifact_locator_policy") == "included":
                    validate_dataset_payload_commitment(dataset)
                unavailable = sorted(set(dataset.source_dataset_ids) - set(dataset_by_id))
                if unavailable:
                    raise ValidationError(
                        f"package dataset {dataset_id} has unavailable lineage sources: "
                        + ", ".join(unavailable)
                    )
                try:
                    validate_protected_dataset_lineage_closure(
                        dataset,
                        dataset_by_id,
                        validate_payload=False,
                    )
                except ValidationError as exc:
                    raise ValidationError(
                        f"package protected dataset {dataset_id} violates "
                        f"protocol-closed lineage: {exc}"
                    ) from exc
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
                verified_results_by_sha = _verified_handoff_results_by_output_sha(
                    protocol=protocol,
                    run=run,
                    output_artifacts=output_artifacts,
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
                    _reject_skipped_gate_structured_results(
                        run_id=run.run_id,
                        gate=gate,
                    )
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
                        verified_results_by_sha=verified_results_by_sha,
                    )
                    _validate_control_gate_metadata(
                        protocol=protocol,
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                        verified_results_by_sha=verified_results_by_sha,
                    )
                    _validate_measurement_validity_gate_metadata(
                        protocol=protocol,
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                        verified_results_by_sha=verified_results_by_sha,
                    )
                    _validate_missingness_gate_metadata(
                        protocol=protocol,
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                        verified_results_by_sha=verified_results_by_sha,
                    )
                    _validate_causal_assumption_gate_metadata(
                        protocol=protocol,
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=output_artifacts,
                        verified_results_by_sha=verified_results_by_sha,
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
                _validate_execution_handoff_measurement_value_check(run)
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
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()


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
                or key == "artifact_root"
                or key == "attestation_schema_path"
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
