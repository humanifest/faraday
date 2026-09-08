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
    is_canonical_sha256,
    require_sha256,
    require_canonical_text,
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
            if (
                protocol_summary["protocol_id"] != protocol.protocol_id
                or protocol_summary["protocol_hash"] != protocol.protocol_hash
                or protocol_summary["registration_timestamp"]
                != protocol.registration_timestamp
            ):
                raise ValidationError("version-2 package protocol summary disagrees with protocol.json")
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
            if manifest.get("ethics_review_event_ids") != [item.event_id for item in events]:
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
            dataset_ids = [item.dataset_id for item in datasets]
            run_ids = [item.run_id for item in runs]
            if len(dataset_ids) != len(set(dataset_ids)) or manifest.get("dataset_ids") != sorted(dataset_ids):
                raise ValidationError("package dataset IDs disagree with unique dataset records")
            if len(run_ids) != len(set(run_ids)) or manifest.get("run_ids") != sorted(run_ids):
                raise ValidationError("package run IDs disagree with unique run records")
            dataset_by_id = {item.dataset_id: item for item in datasets}
            for dataset in datasets:
                if manifest.get("artifact_locator_policy") == "included":
                    validate_dataset_payload_commitment(dataset)
                if len(dataset.source_dataset_ids) != len(set(dataset.source_dataset_ids)):
                    raise ValidationError(
                        f"package dataset {dataset.dataset_id} repeats a lineage source"
                    )
                unavailable = sorted(set(dataset.source_dataset_ids) - set(dataset_by_id))
                if unavailable:
                    raise ValidationError(
                        f"package dataset {dataset.dataset_id} has unavailable lineage sources: "
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
                if item.protocol_id == protocol.protocol_id
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
                if manifest.get("artifact_locator_policy") == "included":
                    validate_run_payload_commitment(run)
                if run.protocol_id != protocol.protocol_id or run.protocol_hash != protocol.protocol_hash:
                    raise ValidationError(
                        f"package run {run.run_id} does not match the packaged frozen protocol"
                    )
                if len(run.dataset_ids) != len(set(run.dataset_ids)):
                    raise ValidationError(f"package run {run.run_id} repeats a dataset input")
                if run.analysis_mode is not protocol.analysis_mode:
                    raise ValidationError(
                        f"package run {run.run_id} analysis mode disagrees with the protocol"
                    )
                missing_inputs = sorted(set(run.dataset_ids) - set(dataset_by_id))
                if missing_inputs:
                    raise ValidationError(
                        f"package run {run.run_id} has unavailable dataset inputs: "
                        + ", ".join(missing_inputs)
                    )
                input_datasets = [dataset_by_id[value] for value in run.dataset_ids]
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
                output_hashes = {item.sha256 for item in run.output_artifacts}
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
                        output_artifacts=run.output_artifacts,
                    )
                    _validate_stream_timing_assessment_gate_metadata(
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=run.output_artifacts,
                    )
                    _validate_temporal_order_assessment_gate_metadata(
                        run_id=run.run_id,
                        gate=gate,
                        output_artifacts=run.output_artifacts,
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
                artifact_integrity = run.metadata.get("artifact_integrity")
                artifact_failure = (
                    isinstance(artifact_integrity, dict)
                    and artifact_integrity.get("status") != "passed"
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
                    and isinstance(
                        run.metadata.get("protocol_deviation_disclosure"), dict
                    )
                    and run.metadata["protocol_deviation_disclosure"].get("status")
                    == "no_deviations_declared"
                    and run.metadata["protocol_deviation_disclosure"].get("deviations")
                    == []
                    and run.metadata["protocol_deviation_disclosure"].get(
                        "automatic_evidence_eligible"
                    )
                    is True
                    and isinstance(artifact_integrity, dict)
                    and artifact_integrity.get("status") == "passed"
                    and (
                        not protocol.sample_size_plan
                        or (
                            isinstance(
                                run.metadata.get("sample_size_plan_check"), dict
                            )
                            and run.metadata["sample_size_plan_check"].get("status")
                            == "passed"
                        )
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
