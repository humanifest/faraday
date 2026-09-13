from __future__ import annotations

from collections import Counter
from typing import Any

from research_machine.domain.models import (
    DatasetManifest,
    DatasetRole,
    ExperimentProtocol,
    RigorFinding,
    RigorSeverity,
)
from research_machine.application.dataset_source_authority import (
    dataset_source_authority_status,
)
from research_machine.domain.errors import ResearchMachineError, ValidationError


INTERPRETATION_LIMIT = (
    "This is a manifest/provenance inventory, not proof of source truth, "
    "consent truth, measurement validity, or analysis adequacy."
)
EMPTY_INVENTORY_NOTICE = (
    "No datasets are registered in canonical workspace state. Draft data-source "
    "mentions, external plugin access, and design briefs are not counted as "
    "datasets until they are registered through the service."
)
WORKFLOW_MATERIALIZATION_LIMIT = (
    "Local Holm-family byte-chain replay only; not evidence eligibility, "
    "scientific interpretation, chronology authentication, executor "
    "independence, gate success, or source-data truth."
)
INVALID_WORKFLOW_MATERIALIZATION_SUMMARY = (
    "workflow materialization metadata invalid; local byte-chain not trusted "
    "until the dataset rigor finding is resolved"
)
_WORKFLOW_MATERIALIZATION_SCOPE = (
    "Holm-family materialization from pinned source execution receipts and "
    "registered p-value selectors"
)
_WORKFLOW_MATERIALIZATION_NOTICE = (
    "Verifies local source receipt/result bytes and registered p-value selectors; "
    "it does not authenticate chronology, executors, scientific gates, or source "
    "data truth."
)


def _artifact_integrity_passed(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("artifact_integrity"), dict)
        and value["artifact_integrity"].get("status") == "passed"
        and value["artifact_integrity"].get("all_artifacts_match") is True
    )


def _payload_commitment(dataset: DatasetManifest) -> dict[str, Any]:
    payload = dataset.metadata.get("dataset_payload_sha256")
    sealed = isinstance(payload, str) and bool(payload.strip())
    return {
        "sealed": sealed,
        "sha256": payload if sealed else None,
        "summary": (
            f"payload sealed `{payload}`" if sealed else "payload seal missing or legacy"
        ),
    }


def _observation_access(dataset: DatasetManifest) -> dict[str, Any]:
    if dataset.synthetic:
        return {
            "status": "synthetic_fixture",
            "service_verified": False,
            "summary": "synthetic fixture; no real observation access claimed",
        }
    if dataset.role in {DatasetRole.CONFIRMATORY, DatasetRole.REPLICATION}:
        if _artifact_integrity_passed(
            dataset.metadata.get("dataset_artifact_verification")
        ):
            return {
                "status": "protected_observation_bytes_service_verified",
                "service_verified": True,
                "summary": (
                    "registered observation bytes service-verified under retained "
                    "local custody"
                ),
            }
        return {
            "status": "protected_observation_bytes_missing_service_verification",
            "service_verified": False,
            "summary": (
                "protected observations lack service-verified current bytes; "
                "declared hashes alone do not prove usable access"
            ),
        }
    return {
        "status": "declared_hashes_only",
        "service_verified": False,
        "summary": (
            "registered manifest with declared artifact hashes; not a protected "
            "evidence dataset or proof of current local access"
        ),
    }


def _measurement_custody(
    dataset: DatasetManifest, protocol: ExperimentProtocol | None
) -> dict[str, Any]:
    custody = dataset.metadata.get("measurement_custody_verification")
    if _artifact_integrity_passed(custody):
        return {
            "status": "service_verified",
            "required_by_protocol": bool(
                protocol is not None and protocol.measurement_custody_requirements
            ),
            "service_verified": True,
            "summary": "measurement custody service-verified",
        }
    if protocol is not None and protocol.measurement_custody_requirements:
        return {
            "status": "required_missing_service_verification",
            "required_by_protocol": True,
            "service_verified": False,
            "summary": (
                "measurement custody required by protocol but not service-verified"
            ),
        }
    if dataset.metadata.get("measurement_custody") is not None:
        return {
            "status": "described_not_service_verified",
            "required_by_protocol": False,
            "service_verified": False,
            "summary": "measurement custody described but not service-verified",
        }
    return {
        "status": "not_recorded",
        "required_by_protocol": False,
        "service_verified": False,
        "summary": "no measurement-custody verification recorded",
    }


def _sha256(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def dataset_workflow_materialization_status(
    dataset: DatasetManifest,
) -> dict[str, Any]:
    if "workflow_materialization" in dataset.metadata:
        raise ValidationError(
            f"dataset {dataset.dataset_id} retains raw workflow_materialization input"
        )
    receipt = dataset.metadata.get("workflow_materialization_verification")
    if receipt is None:
        return {
            "status": "not_recorded",
            "service_verified": False,
            "source_receipts_replayed": False,
            "scientific_evidence_eligible": False,
            "scientific_interpretation_verified": False,
            "family_step_id": "",
            "family_id": "",
            "source_count": 0,
            "output_sha256": None,
            "row_count": 0,
            "summary": "no workflow materialization verification recorded",
        }
    if not isinstance(receipt, dict):
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow_materialization_verification must be an object"
        )
    if set(receipt) != {
        "verification_version",
        "verified_at",
        "verified_by",
        "status",
        "protocol_id",
        "protocol_hash",
        "family_step_id",
        "family_id",
        "dependency_manifest",
        "materialization",
        "output",
        "verified_sources",
        "scope",
        "scientific_evidence_eligible",
        "scientific_interpretation_verified",
        "notice",
    }:
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization verification fields changed"
        )
    if receipt.get("verification_version") != 1:
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization version is unsupported"
        )
    if receipt.get("status") != "workflow_materialization_verified":
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization status changed"
        )
    if receipt.get("scientific_evidence_eligible") is not False:
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization must remain non-evidentiary"
        )
    if receipt.get("scientific_interpretation_verified") is not False:
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization must remain non-interpretive"
        )
    if receipt.get("scope") != _WORKFLOW_MATERIALIZATION_SCOPE:
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization scope changed"
        )
    if receipt.get("notice") != _WORKFLOW_MATERIALIZATION_NOTICE:
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization notice changed"
        )
    output = receipt.get("output")
    if not isinstance(output, dict):
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization output must be an object"
        )
    output_sha256 = _sha256(
        output.get("sha256"),
        f"dataset {dataset.dataset_id} workflow materialization output sha256",
    )
    matching_artifacts = [
        artifact for artifact in dataset.artifacts if artifact.sha256 == output_sha256
    ]
    if len(matching_artifacts) != 1:
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization output must match exactly one dataset artifact"
        )
    row_count = output.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 1:
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization row_count is invalid"
        )
    sources = receipt.get("verified_sources")
    if not isinstance(sources, list) or len(sources) != row_count:
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization source count changed"
        )
    family_step_id = receipt.get("family_step_id")
    family_id = receipt.get("family_id")
    if not isinstance(family_step_id, str) or not family_step_id.strip():
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization family_step_id is missing"
        )
    if family_step_id != family_step_id.strip():
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization family_step_id must be canonical"
        )
    if not isinstance(family_id, str) or not family_id.strip():
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization family_id is missing"
        )
    if family_id != family_id.strip():
        raise ValidationError(
            f"dataset {dataset.dataset_id} workflow materialization family_id must be canonical"
        )
    return {
        "status": "source_receipts_replayed",
        "service_verified": True,
        "source_receipts_replayed": True,
        "scientific_evidence_eligible": False,
        "scientific_interpretation_verified": False,
        "family_step_id": family_step_id,
        "family_id": family_id,
        "source_count": len(sources),
        "output_sha256": output_sha256,
        "row_count": row_count,
        "summary": WORKFLOW_MATERIALIZATION_LIMIT,
    }


def _invalid_workflow_materialization() -> dict[str, Any]:
    return {
        "status": "invalid_metadata",
        "service_verified": False,
        "source_receipts_replayed": False,
        "scientific_evidence_eligible": False,
        "scientific_interpretation_verified": False,
        "family_step_id": "",
        "family_id": "",
        "source_count": 0,
        "output_sha256": None,
        "row_count": 0,
        "summary": INVALID_WORKFLOW_MATERIALIZATION_SUMMARY,
    }


def _ethics_context(
    dataset: DatasetManifest, protocol: ExperimentProtocol | None
) -> dict[str, Any]:
    if protocol is None:
        return {
            "status": (
                "protocol_missing"
                if dataset.protocol_id
                else "not_bound_to_protocol"
            ),
            "human_subject_protocol": False,
            "service_checked": False,
            "conditions_service_verified": False,
            "summary": (
                "ethics protocol context unavailable"
                if dataset.protocol_id
                else "not protocol-bound"
            ),
        }
    if not protocol.human_subjects:
        return {
            "status": "not_human_subject_protocol",
            "human_subject_protocol": False,
            "service_checked": False,
            "conditions_service_verified": False,
            "summary": "not bound to a human-subject protocol",
        }
    status_check = dataset.metadata.get("ethics_review_status_check")
    active = (
        isinstance(status_check, dict)
        and status_check.get("status") == "active"
        and status_check.get("protocol_hash") == protocol.protocol_hash
    )
    if protocol.independent_review_decision != "approved_with_conditions":
        return {
            "status": "active_service_check" if active else "missing_active_service_check",
            "human_subject_protocol": True,
            "service_checked": active,
            "conditions_service_verified": False,
            "summary": (
                "active ethics status service-check"
                if active
                else "missing active ethics status service-check"
            ),
        }
    condition_check = dataset.metadata.get("ethics_condition_verification")
    conditions_verified = (
        _artifact_integrity_passed(condition_check)
        and isinstance(condition_check, dict)
        and condition_check.get("protocol_hash") == protocol.protocol_hash
    )
    return {
        "status": (
            "active_service_check_with_conditions_verified"
            if active and conditions_verified
            else "missing_required_ethics_service_verification"
        ),
        "human_subject_protocol": True,
        "service_checked": active,
        "conditions_service_verified": conditions_verified,
        "summary": (
            (
                "active ethics status service-check"
                if active
                else "missing active ethics status service-check"
            )
            + "; "
            + (
                "conditions service-verified"
                if conditions_verified
                else "conditions not service-verified"
            )
        ),
    }


def _finding_summary(finding: RigorFinding) -> dict[str, str]:
    return {
        "code": finding.code,
        "severity": finding.severity.value,
        "message": finding.message,
        "remediation": finding.remediation,
    }


def _readiness_summary(
    dataset: DatasetManifest, findings: list[RigorFinding]
) -> dict[str, Any]:
    if dataset.role not in {DatasetRole.CONFIRMATORY, DatasetRole.REPLICATION}:
        return {
            "status": "not_protected_evidence_dataset",
            "blocking_finding_codes": [],
            "warning_finding_codes": [
                finding.code
                for finding in findings
                if finding.severity is RigorSeverity.WARNING
            ],
            "summary": (
                "This dataset is not a protected confirmatory or replication "
                "evidence dataset."
            ),
        }
    blocking = [
        finding.code for finding in findings
        if finding.severity is RigorSeverity.ERROR
    ]
    warnings = [
        finding.code for finding in findings
        if finding.severity is RigorSeverity.WARNING
    ]
    if blocking:
        return {
            "status": "protected_use_blocked_by_rigor",
            "blocking_finding_codes": blocking,
            "warning_finding_codes": warnings,
            "summary": (
                "Treat this protected dataset as unusable for protected analysis "
                "until its dataset-scoped rigor errors are resolved."
            ),
        }
    if warnings:
        return {
            "status": "protected_use_has_rigor_warnings",
            "blocking_finding_codes": [],
            "warning_finding_codes": warnings,
            "summary": (
                "No dataset-scoped rigor errors were detected, but warnings remain; "
                "this is not proof of scientific adequacy."
            ),
        }
    return {
        "status": "protected_no_dataset_rigor_blockers_detected",
        "blocking_finding_codes": [],
        "warning_finding_codes": [],
        "summary": (
            "No dataset-scoped rigor blockers were detected by the current audit; "
            "this is not proof of source truth, consent truth, measurement "
            "validity, or analysis adequacy."
        ),
    }


def build_dataset_inventory(
    datasets: list[DatasetManifest],
    protocols: list[ExperimentProtocol],
    findings: list[RigorFinding] | None = None,
) -> dict[str, Any]:
    protocols_by_id = {protocol.protocol_id: protocol for protocol in protocols}
    dataset_findings: dict[str, list[RigorFinding]] = {}
    for finding in findings or []:
        if finding.entity_type == "dataset" and finding.entity_id:
            dataset_findings.setdefault(finding.entity_id, []).append(finding)
    counts = Counter(dataset.role.value for dataset in datasets)
    rows: list[dict[str, Any]] = []
    for dataset in sorted(datasets, key=lambda item: item.dataset_id):
        protocol = protocols_by_id.get(dataset.protocol_id or "")
        current_findings = sorted(
            dataset_findings.get(dataset.dataset_id, []),
            key=lambda item: (item.severity.value, item.code),
        )
        media_types = sorted(
            {
                artifact.media_type.strip() or "unknown media type"
                for artifact in dataset.artifacts
            }
        )
        try:
            workflow_materialization = dataset_workflow_materialization_status(
                dataset
            )
        except ResearchMachineError:
            workflow_materialization = _invalid_workflow_materialization()
        rows.append(
            {
                "dataset_id": dataset.dataset_id,
                "name": dataset.name,
                "role": dataset.role.value,
                "synthetic": dataset.synthetic,
                "protocol_id": dataset.protocol_id,
                "protocol_present": protocol is not None,
                "artifact_count": len(dataset.artifacts),
                "media_types": media_types,
                "source_dataset_ids": list(dataset.source_dataset_ids),
                "source_authority": dataset_source_authority_status(dataset.metadata),
                "payload_commitment": _payload_commitment(dataset),
                "observation_access": _observation_access(dataset),
                "measurement_custody": _measurement_custody(dataset, protocol),
                "workflow_materialization": workflow_materialization,
                "ethics": _ethics_context(dataset, protocol),
                "rigor_findings": [
                    _finding_summary(finding) for finding in current_findings
                ],
                "readiness": _readiness_summary(dataset, current_findings),
                "operational_roots_redacted": True,
            }
        )
    synthetic_count = sum(1 for dataset in datasets if dataset.synthetic)
    datasets_with_errors = {
        finding.entity_id for finding in findings or []
        if (
            finding.entity_type == "dataset"
            and finding.entity_id
            and finding.severity is RigorSeverity.ERROR
        )
    }
    return {
        "registered_dataset_count": len(datasets),
        "role_counts": {role: counts[role] for role in sorted(counts)},
        "synthetic_count": synthetic_count,
        "non_synthetic_count": len(datasets) - synthetic_count,
        "datasets_with_rigor_errors": len(datasets_with_errors),
        "empty_inventory_notice": EMPTY_INVENTORY_NOTICE if not datasets else "",
        "interpretation_limit": INTERPRETATION_LIMIT,
        "datasets": rows,
    }
