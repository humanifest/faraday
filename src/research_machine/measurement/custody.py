from __future__ import annotations

from typing import Any, Sequence
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import tempfile

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    CalibrationCriterion,
    DatasetArtifact,
    DatasetManifest,
    ExperimentProtocol,
    ProtocolStatus,
)


_HEX = set("0123456789abcdef")
_CUSTODY_RECORD_CONCLUSION_CEILING = (
    "This record verifies local bytes, internal chronology, frozen calibration "
    "bounds, and custody references. It does not authenticate actors or time, "
    "validate scientific interpretation, register a dataset, or establish evidence."
)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"measurement custody {field} must be non-empty text")
    return value


def _canonical_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if text != text.strip():
        raise ValidationError(
            f"measurement custody {field} must be canonical without surrounding whitespace"
        )
    return text


def _digest(value: Any, field: str) -> str:
    value = _text(value, field)
    if len(value) != 64 or set(value) - _HEX:
        raise ValidationError(f"measurement custody {field} must be a lowercase SHA-256")
    return value


def _timestamp(value: Any, field: str) -> datetime:
    value = _text(value, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"measurement custody {field} must be an ISO-8601 timestamp with UTC offset") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"measurement custody {field} must include a UTC offset")
    return parsed


def _canonical_text_sequence(values: Sequence[str], field: str) -> list[str]:
    items = [_canonical_text(value, field) for value in values]
    if len(items) != len(set(items)):
        raise ValidationError(f"measurement custody {field} must be unique")
    return items


def _finite_number(value: Any, field: str) -> float | int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValidationError(f"measurement custody {field} must be a finite number")
    return value


def _nonnegative_int_or_none(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(
            f"measurement custody {field} must be a non-negative integer or null"
        )
    return value


def _require_known_fields(item: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(item) - allowed)
    if unknown:
        raise ValidationError(
            f"measurement custody {label} has unknown fields: "
            + ", ".join(unknown)
        )


def validate_measurement_custody(
    receipt: Any,
    required_gate_ids: Sequence[str] = (),
    required_calibration_criteria: Sequence[CalibrationCriterion] = (),
) -> dict[str, Any]:
    """Require a fully traceable raw-to-derived measurement chain."""
    if not isinstance(receipt, dict):
        raise ValidationError("measurement_custody metadata must be an object")
    allowed = {
        "receipt_id",
        "raw_sources",
        "transformations",
        "calibrations",
        "quality_gates",
        "derived_observations",
        "evidence_artifacts",
    }
    unknown = sorted(set(receipt) - allowed)
    if unknown:
        raise ValidationError("unknown measurement custody fields: " + ", ".join(unknown))
    _canonical_text(receipt.get("receipt_id"), "receipt_id")
    required_gate_ids = _canonical_text_sequence(
        required_gate_ids, "required_gate_ids"
    )
    evidence = receipt.get("evidence_artifacts")
    if not isinstance(evidence, list) or not evidence:
        raise ValidationError("measurement custody evidence_artifacts must be a non-empty array")
    evidence_hashes: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise ValidationError("each evidence artifact must be an object")
        _require_known_fields(
            item, {"locator", "sha256", "size_bytes"}, "evidence artifact"
        )
        _canonical_text(item.get("locator"), "evidence artifact locator")
        _nonnegative_int_or_none(
            item.get("size_bytes"), "evidence artifact size_bytes"
        )
        digest = _digest(item.get("sha256"), "evidence artifact sha256")
        if digest in evidence_hashes:
            raise ValidationError("duplicate evidence artifact hash")
        evidence_hashes.add(digest)

    def require_evidence(item: dict[str, Any], label: str) -> None:
        digest = _digest(item.get("evidence_sha256"), f"{label}.evidence_sha256")
        if digest not in evidence_hashes:
            raise ValidationError(f"{label} evidence must reference a listed evidence artifact")
    sources = receipt.get("raw_sources")
    if not isinstance(sources, list) or not sources:
        raise ValidationError("measurement custody raw_sources must be a non-empty array")
    hashes: set[str] = set()
    available_at: dict[str, datetime] = {}
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValidationError("each raw source must be an object")
        _require_known_fields(
            source,
            {"locator", "sha256", "size_bytes", "captured_at", "acquisition_method"},
            f"raw_sources[{index}]",
        )
        for field in ("locator", "captured_at", "acquisition_method"):
            _canonical_text(source.get(field), f"raw_sources[{index}].{field}")
        _nonnegative_int_or_none(
            source.get("size_bytes"), f"raw_sources[{index}].size_bytes"
        )
        captured_at = _timestamp(source["captured_at"], f"raw_sources[{index}].captured_at")
        digest = _digest(source.get("sha256"), f"raw_sources[{index}].sha256")
        if digest in hashes:
            raise ValidationError("duplicate raw source hash")
        hashes.add(digest)
        available_at[digest] = captured_at
    transformations = receipt.get("transformations")
    if not isinstance(transformations, list) or not transformations:
        raise ValidationError("measurement custody transformations must be a non-empty array")
    outputs: set[str] = set()
    transformation_ids: set[str] = set()
    for index, item in enumerate(transformations):
        if not isinstance(item, dict):
            raise ValidationError("each transformation must be an object")
        _require_known_fields(
            item,
            {
                "transformation_id",
                "version",
                "performed_at",
                "implementation_locator",
                "implementation_sha256",
                "input_sha256",
                "output_locator",
                "output_sha256",
            },
            f"transformations[{index}]",
        )
        for field in ("transformation_id", "version", "performed_at", "implementation_locator", "output_locator"):
            _canonical_text(item.get(field), f"transformations[{index}].{field}")
        performed_at = _timestamp(item["performed_at"], f"transformations[{index}].performed_at")
        identifier = _canonical_text(
            item["transformation_id"], f"transformations[{index}].transformation_id"
        )
        if identifier in transformation_ids:
            raise ValidationError("measurement custody transformation_id must be unique")
        transformation_ids.add(identifier)
        _digest(
            item.get("implementation_sha256"),
            f"transformations[{index}].implementation_sha256",
        )
        source = _digest(item.get("input_sha256"), f"transformations[{index}].input_sha256")
        output = _digest(item.get("output_sha256"), f"transformations[{index}].output_sha256")
        if source not in hashes | outputs:
            raise ValidationError(
                "transformation input_sha256 must be a raw source or prior "
                "transformation output"
            )
        if performed_at < available_at[source]:
            raise ValidationError("transformation performed_at predates availability of its input")
        if output in hashes | outputs or output == source:
            raise ValidationError("transformation output_sha256 must identify a new unique derived artifact")
        outputs.add(output)
        available_at[output] = performed_at
    calibrations = receipt.get("calibrations")
    if not isinstance(calibrations, list) or not calibrations:
        raise ValidationError("measurement custody calibrations must be a non-empty array")
    calibration_ids: set[str] = set()
    calibration_times: dict[str, datetime] = {}
    criteria: dict[str, CalibrationCriterion] = {}
    for criterion in required_calibration_criteria:
        if not isinstance(criterion, CalibrationCriterion):
            raise ValidationError(
                "measurement custody required calibration criteria must be CalibrationCriterion values"
            )
        calibration_id = _canonical_text(
            criterion.calibration_id, "calibration criterion calibration_id"
        )
        if calibration_id in criteria:
            raise ValidationError(
                "measurement custody required calibration criteria must be unique"
            )
        criteria[calibration_id] = criterion
    for item in calibrations:
        if not isinstance(item, dict):
            raise ValidationError("each calibration must be an object")
        _require_known_fields(
            item,
            {
                "calibration_id",
                "reference",
                "performed_at",
                "result",
                "status",
                "criterion_id",
                "observed_value",
                "observed_unit",
                "observed_components",
                "evidence_sha256",
            },
            "calibration",
        )
        for field in ("calibration_id", "reference", "performed_at", "result"):
            _canonical_text(item.get(field), f"calibration.{field}")
        if "observed_components" in item and (
            "observed_value" in item or "observed_unit" in item
        ):
            raise ValidationError(
                "measurement custody calibration must not mix scalar and component observations"
            )
        performed_at = _timestamp(item["performed_at"], "calibration.performed_at")
        if item.get("status") != "passed":
            raise ValidationError("measurement custody calibration status must be passed")
        calibration_id = _canonical_text(item["calibration_id"], "calibration.calibration_id")
        if calibration_id in calibration_ids:
            raise ValidationError("measurement custody calibration_id must be unique")
        calibration_ids.add(calibration_id)
        calibration_times[calibration_id] = performed_at
        require_evidence(item, "calibration")
        if criteria:
            criterion = criteria.get(calibration_id)
            if criterion is None:
                raise ValidationError(f"calibration {calibration_id} has no frozen acceptance criterion")
            criterion_id = _canonical_text(item.get("criterion_id"), "calibration.criterion_id")
            if criterion_id != criterion.criterion_id:
                raise ValidationError(f"calibration {calibration_id} does not reference its frozen criterion")
            if criterion.component_bounds:
                if "observed_value" in item or "observed_unit" in item:
                    raise ValidationError(
                        f"calibration {calibration_id} must not mix scalar and component observations"
                    )
                observed_components = item.get("observed_components")
                if not isinstance(observed_components, list):
                    raise ValidationError(
                        f"calibration {calibration_id} observed_components must be an array"
                    )
                expected_component_ids = [
                    _canonical_text(
                        component["component_id"],
                        f"calibration {calibration_id} frozen component_id",
                    )
                    for component in criterion.component_bounds
                ]
                received_component_ids: list[str] = []
                for index, observed_component in enumerate(observed_components):
                    if not isinstance(observed_component, dict):
                        raise ValidationError(
                            f"calibration {calibration_id} observed_components entries must be objects"
                        )
                    required_fields = {
                        "component_id",
                        "observed_value",
                        "observed_unit",
                    }
                    if set(observed_component) != required_fields:
                        raise ValidationError(
                            f"calibration {calibration_id} observed_components fields are invalid"
                        )
                    component_id = _canonical_text(
                        observed_component["component_id"],
                        f"calibration {calibration_id} observed_components[{index}].component_id",
                    )
                    received_component_ids.append(component_id)
                if received_component_ids != expected_component_ids:
                    raise ValidationError(
                        f"calibration {calibration_id} observed_components must match frozen component order exactly"
                    )
                for observed_component, frozen_component in zip(
                    observed_components,
                    criterion.component_bounds,
                    strict=True,
                ):
                    component_id = observed_component["component_id"]
                    if observed_component.get("observed_unit") != frozen_component["unit"]:
                        raise ValidationError(
                            f"calibration {calibration_id} component {component_id} observed_unit does not match its frozen criterion"
                        )
                    observed = _finite_number(
                        observed_component.get("observed_value"),
                        f"calibration {calibration_id} component {component_id}.observed_value",
                    )
                    lower_bound = frozen_component.get("lower_bound")
                    upper_bound = frozen_component.get("upper_bound")
                    if lower_bound is not None and observed < lower_bound:
                        raise ValidationError(
                            f"calibration {calibration_id} component {component_id} failed its frozen lower bound"
                        )
                    if upper_bound is not None and observed > upper_bound:
                        raise ValidationError(
                            f"calibration {calibration_id} component {component_id} failed its frozen upper bound"
                        )
            else:
                if "observed_components" in item:
                    raise ValidationError(
                        f"calibration {calibration_id} has no frozen component_bounds"
                    )
                if item.get("observed_unit") != criterion.unit:
                    raise ValidationError(f"calibration {calibration_id} observed_unit does not match its frozen criterion")
                observed = _finite_number(
                    item.get("observed_value"),
                    f"calibration {calibration_id} observed_value",
                )
                if criterion.lower_bound is not None and observed < criterion.lower_bound:
                    raise ValidationError(f"calibration {calibration_id} failed its frozen lower bound")
                if criterion.upper_bound is not None and observed > criterion.upper_bound:
                    raise ValidationError(f"calibration {calibration_id} failed its frozen upper bound")
    missing_calibrations = sorted(set(criteria) - calibration_ids)
    if missing_calibrations:
        raise ValidationError("measurement custody is missing calibrations with frozen criteria: " + ", ".join(missing_calibrations))
    gates = receipt.get("quality_gates")
    if not isinstance(gates, list) or not gates:
        raise ValidationError("measurement custody quality_gates must be a non-empty array")
    gate_ids: set[str] = set()
    gate_artifacts: dict[str, set[str]] = {}
    for item in gates:
        if not isinstance(item, dict):
            raise ValidationError("each measurement quality gate must be an object")
        _require_known_fields(
            item,
            {
                "gate_id",
                "status",
                "evaluated_at",
                "summary",
                "evidence_sha256",
                "prerequisite_calibration_ids",
                "prerequisite_artifact_sha256s",
            },
            "quality gate",
        )
        gate_id = _canonical_text(item.get("gate_id"), "quality gate gate_id")
        if gate_id in gate_ids:
            raise ValidationError("measurement custody gate_id must be unique")
        gate_ids.add(gate_id)
        evaluated_at = _timestamp(item.get("evaluated_at"), f"quality gate {gate_id}.evaluated_at")
        require_evidence(item, f"quality gate {gate_id}")
        prerequisites = item.get("prerequisite_calibration_ids", [])
        if not isinstance(prerequisites, list) or any(
            not isinstance(value, str) or not value.strip()
            for value in prerequisites
        ):
            raise ValidationError(f"quality gate {gate_id} references an unavailable calibration prerequisite")
        prerequisites = [
            _canonical_text(value, f"quality gate {gate_id} prerequisite_calibration_ids item")
            for value in prerequisites
        ]
        if any(value not in calibration_ids for value in prerequisites):
            raise ValidationError(f"quality gate {gate_id} references an unavailable calibration prerequisite")
        if len(prerequisites) != len(set(prerequisites)):
            raise ValidationError(f"quality gate {gate_id} has duplicate calibration prerequisites")
        if any(calibration_times[value] > evaluated_at for value in prerequisites):
            raise ValidationError(f"quality gate {gate_id} predates a calibration prerequisite")
        artifact_prerequisites = item.get("prerequisite_artifact_sha256s")
        if (not isinstance(artifact_prerequisites, list) or not artifact_prerequisites
                or any(not isinstance(value, str) for value in artifact_prerequisites)):
            raise ValidationError(f"quality gate {gate_id} requires prerequisite_artifact_sha256s")
        artifact_prerequisites = [
            _digest(value, f"quality gate {gate_id} prerequisite artifact")
            for value in artifact_prerequisites
        ]
        if len(artifact_prerequisites) != len(set(artifact_prerequisites)):
            raise ValidationError(f"quality gate {gate_id} has duplicate artifact prerequisites")
        if any(value not in available_at for value in artifact_prerequisites):
            raise ValidationError(f"quality gate {gate_id} references an unavailable artifact prerequisite")
        if any(available_at[value] > evaluated_at for value in artifact_prerequisites):
            raise ValidationError(f"quality gate {gate_id} predates an artifact prerequisite")
        gate_artifacts[gate_id] = set(artifact_prerequisites)
        _canonical_text(item.get("summary"), f"quality gate {gate_id} summary")
        if item.get("status") != "passed":
            raise ValidationError(
                f"measurement quality gate {gate_id} must be passed"
            )
    missing = sorted(set(required_gate_ids) - gate_ids)
    if missing:
        raise ValidationError("measurement custody is missing required gates: " + ", ".join(missing))
    observations = receipt.get("derived_observations")
    if not isinstance(observations, list) or not observations:
        raise ValidationError("measurement custody derived_observations must be a non-empty array")
    observation_ids: set[str] = set()
    for item in observations:
        if not isinstance(item, dict):
            raise ValidationError("each derived observation must be an object")
        _require_known_fields(
            item,
            {
                "observation_id",
                "definition",
                "derived_at",
                "source_output_sha256",
                "quality_gate_ids",
            },
            "derived observation",
        )
        identifier = _canonical_text(
            item.get("observation_id"), "derived observation observation_id"
        )
        if identifier in observation_ids:
            raise ValidationError("measurement custody observation_id must be unique")
        observation_ids.add(identifier)
        _canonical_text(item.get("definition"), "derived observation definition")
        derived_at = _timestamp(item.get("derived_at"), "derived observation derived_at")
        output = _digest(
            item.get("source_output_sha256"),
            "derived observation source_output_sha256",
        )
        if output not in outputs:
            raise ValidationError("derived observation source_output_sha256 must be a transformation output")
        if derived_at < available_at[output]:
            raise ValidationError("derived observation predates its transformation output")
        observation_gates = item.get("quality_gate_ids")
        if (not isinstance(observation_gates, list) or not observation_gates
                or any(not isinstance(value, str) or not value.strip() for value in observation_gates)):
            raise ValidationError("derived observation quality_gate_ids must name passed measurement gates")
        observation_gates = [
            _canonical_text(value, "derived observation quality_gate_ids item")
            for value in observation_gates
        ]
        if any(value not in gate_ids for value in observation_gates):
            raise ValidationError("derived observation quality_gate_ids must name passed measurement gates")
        if len(observation_gates) != len(set(observation_gates)):
            raise ValidationError("derived observation has duplicate quality_gate_ids")
        if any(output not in gate_artifacts[gate_id] for gate_id in observation_gates):
            raise ValidationError("derived observation gate must cite its transformation output as a prerequisite")
    return receipt


def _load_json_bytes(raw: bytes, label: str) -> Any:
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
            raw,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"{label} is not strict valid JSON: {exc}") from exc


def _verify_custody_artifacts(
    custody: dict[str, Any], artifact_root: Path, actor: str
) -> dict[str, Any]:
    from research_machine.application.artifact_integrity import verify_run_artifacts
    from research_machine.application.policies import validate_dataset_artifacts

    artifacts = validate_dataset_artifacts([
        DatasetArtifact(
            locator=item["locator"],
            sha256=item["sha256"],
            size_bytes=item.get("size_bytes"),
        )
        for item in [
            *custody["raw_sources"],
            *custody["evidence_artifacts"],
            *(
                {
                    "locator": item["implementation_locator"],
                    "sha256": item["implementation_sha256"],
                }
                for item in custody["transformations"]
            ),
            *(
                {"locator": item["output_locator"], "sha256": item["output_sha256"]}
                for item in custody["transformations"]
            ),
        ]
    ])
    integrity = verify_run_artifacts(
        artifacts,
        artifact_root=str(artifact_root.expanduser().resolve()),
        actor=_canonical_text(actor, "actor"),
        analysis_code_hash="",
        run_metadata={},
        attestation_schema_path=None,
        expected_attestation_schema_sha256=None,
    )
    if integrity.status != "passed":
        raise ValidationError(
            "custody artifact verification failed: "
            + ", ".join(item["code"] for item in integrity.findings)
        )
    return integrity.to_dict()


def reverify_dataset_measurement_custody(
    protocol: ExperimentProtocol, dataset: DatasetManifest
) -> dict[str, Any]:
    """Replay canonical dataset custody from retained structure and current bytes."""
    verification = dataset.metadata.get("measurement_custody_verification")
    if not isinstance(verification, dict):
        raise ValidationError(
            f"dataset {dataset.dataset_id} lacks service-generated measurement custody verification"
        )
    custody = validate_measurement_custody(
        dataset.metadata.get("measurement_custody"),
        protocol.measurement_custody_requirements,
        protocol.calibration_acceptance_criteria,
    )
    root = verification.get("custody_artifact_root")
    if not isinstance(root, str) or not root.strip():
        raise ValidationError(
            f"dataset {dataset.dataset_id} lacks retained custody artifact root"
        )
    verified_by = _canonical_text(verification.get("verified_by"), "verification actor")
    verified_at = _canonical_text(verification.get("verified_at"), "verification time")
    _timestamp(verified_at, "verification time")
    current_integrity = _verify_custody_artifacts(custody, Path(root), verified_by)
    expected = {
        "verification_version": 1,
        "verified_at": verified_at,
        "verified_by": verified_by,
        "custody_artifact_root": str(Path(root).expanduser().resolve()),
        "custody_receipt_sha256": hashlib.sha256(json.dumps(
            custody, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()).hexdigest(),
        "protocol_hash": protocol.protocol_hash,
        "required_gate_ids": list(protocol.measurement_custody_requirements),
        "artifact_integrity": current_integrity,
        "scope": "raw-source, transformation implementation, derived-output, and supporting-evidence bytes under the supplied local artifact root",
        "scientific_interpretation_verified": False,
    }
    if verification != expected:
        raise ValidationError(
            f"dataset {dataset.dataset_id} measurement custody verification no longer reproduces exactly"
        )
    if {item.sha256 for item in dataset.artifacts} != {
        item["source_output_sha256"] for item in custody["derived_observations"]
    }:
        raise ValidationError(
            f"dataset {dataset.dataset_id} artifacts no longer match custody-derived observations"
        )
    return verification


def create_measurement_custody_record(
    receipt_file: Path,
    expected_receipt_sha256: str,
    protocol: ExperimentProtocol,
    artifact_root: Path,
    output: Path,
    *,
    actor: str,
) -> dict[str, Any]:
    """Publish a write-once, byte-verified custody record bound to a protocol."""
    if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
        raise ValidationError("measurement custody records require a frozen protocol")
    if not protocol.measurement_custody_requirements:
        raise ValidationError("protocol has no frozen measurement custody requirements")
    expected = _digest(expected_receipt_sha256, "expected_receipt_sha256")
    source = receipt_file.expanduser().resolve()
    if not source.is_file():
        raise ValidationError(f"measurement custody receipt file is not a file: {source}")
    raw = source.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValidationError("measurement custody receipt does not match expected_receipt_sha256")
    parsed = _load_json_bytes(raw, "measurement custody receipt file")
    custody = validate_measurement_custody(
        parsed,
        protocol.measurement_custody_requirements,
        protocol.calibration_acceptance_criteria,
    )

    integrity = _verify_custody_artifacts(custody, artifact_root, actor)
    actor = _canonical_text(actor, "actor")

    record = {
        "custody_record_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "recorded_by": actor,
        "protocol_id": protocol.protocol_id,
        "protocol_hash": protocol.protocol_hash,
        "receipt_input": {
            "sha256": actual,
            "size_bytes": len(raw),
        },
        "required_gate_ids": list(protocol.measurement_custody_requirements),
        "frozen_calibration_criteria": [
            item.to_dict() for item in protocol.calibration_acceptance_criteria
        ],
        "receipt": custody,
        "artifact_integrity": integrity,
        "status": "custody_recorded",
        "scientific_evidence_eligible": False,
        "conclusion_ceiling": _CUSTODY_RECORD_CONCLUSION_CEILING,
    }
    encoded = (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError(f"measurement custody record output path already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-", dir=root.parent) as temporary:
        staging = Path(temporary) / root.name
        staging.mkdir()
        (staging / "measurement-custody-record.json").write_bytes(encoded)
        try:
            os.replace(staging, root)
        except OSError as exc:
            raise ValidationError(
                f"could not publish measurement custody record atomically: {exc}"
            ) from exc
    return {
        "path": str(root),
        "protocol_id": protocol.protocol_id,
        "receipt_id": custody["receipt_id"],
        "receipt_sha256": actual,
        "custody_record_sha256": hashlib.sha256(encoded).hexdigest(),
        "status": "custody_recorded",
        "scientific_evidence_eligible": False,
    }


def verify_measurement_custody_record(
    record_file: Path,
    expected_record_sha256: str,
    receipt_file: Path,
    protocol: ExperimentProtocol,
    artifact_root: Path,
    *,
    actor: str,
) -> dict[str, Any]:
    """Recompute a standalone custody record from independently trusted inputs."""
    expected_record = _digest(expected_record_sha256, "expected_record_sha256")
    record_path = record_file.expanduser().resolve()
    if not record_path.is_file():
        raise ValidationError(f"measurement custody record file is not a file: {record_path}")
    record_raw = record_path.read_bytes()
    record_sha256 = hashlib.sha256(record_raw).hexdigest()
    if record_sha256 != expected_record:
        raise ValidationError("measurement custody record does not match expected_record_sha256")
    record = _load_json_bytes(record_raw, "measurement custody record file")
    allowed = {
        "custody_record_version", "recorded_at", "recorded_by", "protocol_id",
        "protocol_hash", "receipt_input", "required_gate_ids",
        "frozen_calibration_criteria", "receipt", "artifact_integrity", "status",
        "scientific_evidence_eligible", "conclusion_ceiling",
    }
    if not isinstance(record, dict) or set(record) != allowed:
        raise ValidationError("measurement custody record fields do not match version 1")
    if record.get("custody_record_version") != 1 or record.get("status") != "custody_recorded":
        raise ValidationError("unsupported measurement custody record")
    if record.get("scientific_evidence_eligible") is not False:
        raise ValidationError("measurement custody record must remain scientific-evidence ineligible")
    recorded_at = _canonical_text(record.get("recorded_at"), "recorded_at")
    _timestamp(recorded_at, "recorded_at")
    _canonical_text(record.get("recorded_by"), "recorded_by")
    if record.get("conclusion_ceiling") != _CUSTODY_RECORD_CONCLUSION_CEILING:
        raise ValidationError("measurement custody record conclusion ceiling has changed")
    if protocol.status is not ProtocolStatus.FROZEN or not protocol.protocol_hash:
        raise ValidationError("measurement custody record verification requires a frozen protocol")
    if record.get("protocol_id") != protocol.protocol_id or record.get("protocol_hash") != protocol.protocol_hash:
        raise ValidationError("measurement custody record does not match the frozen protocol")
    if record.get("required_gate_ids") != list(protocol.measurement_custody_requirements):
        raise ValidationError("measurement custody record required gates differ from the frozen protocol")
    criteria = [item.to_dict() for item in protocol.calibration_acceptance_criteria]
    if record.get("frozen_calibration_criteria") != criteria:
        raise ValidationError("measurement custody record calibration criteria differ from the frozen protocol")

    receipt_path = receipt_file.expanduser().resolve()
    if not receipt_path.is_file():
        raise ValidationError(f"measurement custody receipt file is not a file: {receipt_path}")
    receipt_raw = receipt_path.read_bytes()
    receipt_sha256 = hashlib.sha256(receipt_raw).hexdigest()
    if record.get("receipt_input") != {
        "sha256": receipt_sha256,
        "size_bytes": len(receipt_raw),
    }:
        raise ValidationError("measurement custody record does not match the supplied receipt bytes")
    receipt = _load_json_bytes(receipt_raw, "measurement custody receipt file")
    validated = validate_measurement_custody(
        receipt,
        protocol.measurement_custody_requirements,
        protocol.calibration_acceptance_criteria,
    )
    if record.get("receipt") != validated:
        raise ValidationError("measurement custody record embedded receipt differs from supplied bytes")
    integrity = _verify_custody_artifacts(validated, artifact_root, actor)
    if record.get("artifact_integrity") != integrity:
        raise ValidationError("measurement custody record artifact-integrity receipt does not recompute exactly")
    return {
        "status": "custody_record_verified",
        "record_sha256": record_sha256,
        "receipt_sha256": receipt_sha256,
        "protocol_id": protocol.protocol_id,
        "protocol_hash": protocol.protocol_hash,
        "artifact_integrity": integrity,
        "scientific_evidence_eligible": False,
        "conclusion_ceiling": record["conclusion_ceiling"],
    }
