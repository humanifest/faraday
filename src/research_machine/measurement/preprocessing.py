"""Provider-free preprocessing pipeline conformance checks."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from research_machine.domain.errors import ValidationError


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_PIPELINE_FIELDS = {"pipeline_id", "purpose", "steps"}
_CONFORMANCE_RECORD_FIELDS = {
    "preprocessing_conformance_version",
    "pipeline_id",
    "registered_pipeline",
    "registered_pipeline_snapshot",
    "observed_pipeline",
    "observed_pipeline_snapshot",
    "step_results",
    "findings",
    "status",
    "scientific_evidence_eligible",
    "authorized_actions",
    "conclusion_ceiling",
}
_LEGACY_CONFORMANCE_RECORD_FIELDS = _CONFORMANCE_RECORD_FIELDS - {
    "registered_pipeline_snapshot",
    "observed_pipeline_snapshot",
}
_REGISTERED_SNAPSHOT_FIELDS = {"sha256", "size_bytes", "step_ids"}
_OBSERVED_SNAPSHOT_FIELDS = {"sha256", "size_bytes", "pipeline_id", "step_ids"}
_STEP_FIELDS = {
    "step_id",
    "operation",
    "parameters",
    "input_artifacts",
    "output_artifacts",
    "implementation_sha256",
}
_ARTIFACT_FIELDS = {"artifact_id", "sha256", "media_type", "role"}


def _text(value: Any, field: str, *, optional: bool = False) -> str:
    if optional and value in (None, ""):
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"preprocessing {field} must be non-empty text")
    if value != value.strip():
        raise ValidationError(
            f"preprocessing {field} must be canonical without surrounding whitespace"
        )
    return value


def _stable_identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _IDENTIFIER.fullmatch(text):
        raise ValidationError(f"preprocessing {field} must be a stable lowercase identifier")
    return text


def _sha256(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or set(text) - set("0123456789abcdef"):
        raise ValidationError(f"preprocessing {field} must be a lowercase SHA-256")
    return text


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"preprocessing {field} must be a non-negative integer")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise ValidationError(f"preprocessing {label} missing fields: " + ", ".join(missing))
    if unknown:
        raise ValidationError(f"preprocessing {label} has unknown fields: " + ", ".join(unknown))


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _load_json_object_and_sha256(path: Path, label: str) -> tuple[dict[str, Any], bytes, str]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ValidationError(f"{label} is not a file: {source}")
    try:
        content = source.read_bytes()
        value = json.loads(
            content,
            parse_constant=_reject_nonfinite_json,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"{label} is not strict valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value, content, hashlib.sha256(content).hexdigest()


def _stable_id_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"preprocessing {field} must be a non-empty array")
    normalized = [
        _stable_identifier(item, f"{field} item")
        for item in value
    ]
    if len(set(normalized)) != len(normalized):
        raise ValidationError(f"preprocessing {field} must not contain duplicates")
    return normalized


def _verify_snapshot(
    value: Any,
    label: str,
    *,
    observed: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"preprocessing {label} must be an object")
    _exact_fields(
        value,
        _OBSERVED_SNAPSHOT_FIELDS if observed else _REGISTERED_SNAPSHOT_FIELDS,
        label,
    )
    snapshot: dict[str, Any] = {
        "sha256": _sha256(value["sha256"], f"{label}.sha256"),
        "size_bytes": _nonnegative_int(value["size_bytes"], f"{label}.size_bytes"),
        "step_ids": _stable_id_list(value["step_ids"], f"{label}.step_ids"),
    }
    if observed:
        snapshot["pipeline_id"] = _stable_identifier(
            value["pipeline_id"], f"{label}.pipeline_id"
        )
    return snapshot


def _verify_step_results(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValidationError("preprocessing step_results must be a non-empty array")
    results: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        label = f"step_results[{index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"preprocessing {label} must be an object")
        _exact_fields(item, {"step_id", "status", "differences"}, label)
        step_id = _stable_identifier(item["step_id"], f"{label}.step_id")
        status = _text(item["status"], f"{label}.status")
        if status not in {"passed", "failed"}:
            raise ValidationError(f"preprocessing {label}.status is unsupported")
        differences = item["differences"]
        if not isinstance(differences, list):
            raise ValidationError(f"preprocessing {label}.differences must be an array")
        normalized_differences = [
            _text(difference, f"{label}.differences item")
            for difference in differences
        ]
        if len(set(normalized_differences)) != len(normalized_differences):
            raise ValidationError(f"preprocessing {label}.differences must not contain duplicates")
        if status == "passed" and normalized_differences:
            raise ValidationError(f"preprocessing {label} passed with differences")
        if status == "failed" and not normalized_differences:
            raise ValidationError(f"preprocessing {label} failed without differences")
        results.append({
            "step_id": step_id,
            "status": status,
            "differences": normalized_differences,
        })
    return results


def _verify_findings(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValidationError("preprocessing findings must be an array")
    findings: list[dict[str, str]] = []
    for index, item in enumerate(value):
        label = f"findings[{index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"preprocessing {label} must be an object")
        allowed = {"severity", "code", "message", "step_id"}
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise ValidationError(
                f"preprocessing {label} has unknown fields: " + ", ".join(unknown)
            )
        missing = sorted({"severity", "code", "message"} - set(item))
        if missing:
            raise ValidationError(
                f"preprocessing {label} missing fields: " + ", ".join(missing)
            )
        severity = _text(item["severity"], f"{label}.severity")
        if severity not in {"error", "warning"}:
            raise ValidationError(f"preprocessing {label}.severity is unsupported")
        finding = {
            "severity": severity,
            "code": _text(item["code"], f"{label}.code"),
            "message": _text(item["message"], f"{label}.message"),
        }
        if "step_id" in item:
            finding["step_id"] = _stable_identifier(item["step_id"], f"{label}.step_id")
        findings.append(finding)
    return findings


def _pipeline_step_ids(pipeline: dict[str, Any]) -> list[str]:
    return [step["step_id"] for step in pipeline["steps"]]


def _json_safe(value: Any, field: str) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError(f"preprocessing {field} must contain only finite numbers")
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, str) and value != value.strip():
            raise ValidationError(
                f"preprocessing {field} text must be canonical without surrounding whitespace"
            )
        return value
    if isinstance(value, list):
        return [_json_safe(item, field) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not key.strip() or key != key.strip():
                raise ValidationError(
                    f"preprocessing {field} keys must be canonical non-empty text"
                )
            normalized[key] = _json_safe(item, field)
        return normalized
    raise ValidationError(f"preprocessing {field} must be JSON-compatible")


def _normalize_artifacts(value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"preprocessing {label} must be a non-empty array")
    artifacts: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, artifact in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(artifact, dict):
            raise ValidationError(f"preprocessing {item_label} must be an object")
        _exact_fields(artifact, _ARTIFACT_FIELDS, item_label)
        artifact_id = _stable_identifier(artifact["artifact_id"], f"{item_label}.artifact_id")
        if artifact_id in seen:
            raise ValidationError(f"preprocessing {label} artifact_id must be unique")
        seen.add(artifact_id)
        artifacts.append({
            "artifact_id": artifact_id,
            "sha256": _sha256(artifact["sha256"], f"{item_label}.sha256"),
            "media_type": _text(artifact["media_type"], f"{item_label}.media_type"),
            "role": _text(artifact["role"], f"{item_label}.role"),
        })
    return artifacts


def _normalize_pipeline(value: dict[str, Any], label: str) -> dict[str, Any]:
    _exact_fields(value, _PIPELINE_FIELDS, label)
    steps = value["steps"]
    if not isinstance(steps, list) or not steps:
        raise ValidationError(f"preprocessing {label}.steps must be a non-empty array")
    normalized_steps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, step in enumerate(steps):
        step_label = f"{label}.steps[{index}]"
        if not isinstance(step, dict):
            raise ValidationError(f"preprocessing {step_label} must be an object")
        _exact_fields(step, _STEP_FIELDS, step_label)
        step_id = _stable_identifier(step["step_id"], f"{step_label}.step_id")
        if step_id in seen:
            raise ValidationError(f"preprocessing {label}.steps step_id must be unique")
        seen.add(step_id)
        normalized_steps.append({
            "step_id": step_id,
            "operation": _text(step["operation"], f"{step_label}.operation"),
            "parameters": _json_safe(step["parameters"], f"{step_label}.parameters"),
            "input_artifacts": _normalize_artifacts(
                step["input_artifacts"], f"{step_label}.input_artifacts"
            ),
            "output_artifacts": _normalize_artifacts(
                step["output_artifacts"], f"{step_label}.output_artifacts"
            ),
            "implementation_sha256": _sha256(
                step["implementation_sha256"], f"{step_label}.implementation_sha256"
            ),
        })
    return {
        "pipeline_id": _stable_identifier(value["pipeline_id"], f"{label}.pipeline_id"),
        "purpose": _text(value["purpose"], f"{label}.purpose"),
        "steps": normalized_steps,
    }


def _finding(
    code: str,
    message: str,
    *,
    step_id: str | None = None,
    severity: str = "error",
) -> dict[str, str]:
    finding = {"severity": severity, "code": code, "message": message}
    if step_id:
        finding["step_id"] = step_id
    return finding


def _compare_pipelines(
    registered: dict[str, Any], observed: dict[str, Any]
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    findings: list[dict[str, str]] = []
    step_results: list[dict[str, Any]] = []
    if registered["pipeline_id"] != observed["pipeline_id"]:
        findings.append(_finding(
            "PIPELINE_ID_MISMATCH",
            "Observed preprocessing pipeline ID does not match the registered pipeline ID.",
        ))
    registered_ids = [step["step_id"] for step in registered["steps"]]
    observed_ids = [step["step_id"] for step in observed["steps"]]
    if registered_ids != observed_ids:
        findings.append(_finding(
            "STEP_ORDER_MISMATCH",
            "Observed preprocessing step IDs or order differ from the registered pipeline.",
        ))
    observed_by_id = {step["step_id"]: step for step in observed["steps"]}
    for registered_step in registered["steps"]:
        step_id = registered_step["step_id"]
        observed_step = observed_by_id.get(step_id)
        result: dict[str, Any] = {"step_id": step_id, "status": "passed", "differences": []}
        if observed_step is None:
            result["status"] = "failed"
            result["differences"].append("missing_step")
            findings.append(_finding(
                "STEP_MISSING",
                "A registered preprocessing step is absent from the observed pipeline.",
                step_id=step_id,
            ))
            step_results.append(result)
            continue
        comparisons = [
            ("operation", "STEP_OPERATION_MISMATCH"),
            ("parameters", "STEP_PARAMETERS_MISMATCH"),
            ("input_artifacts", "STEP_INPUT_ARTIFACTS_MISMATCH"),
            ("output_artifacts", "STEP_OUTPUT_ARTIFACTS_MISMATCH"),
            ("implementation_sha256", "STEP_IMPLEMENTATION_MISMATCH"),
        ]
        for field, code in comparisons:
            if observed_step[field] != registered_step[field]:
                result["status"] = "failed"
                result["differences"].append(field)
                findings.append(_finding(
                    code,
                    f"Observed preprocessing {field} differs from the registered step.",
                    step_id=step_id,
                ))
        step_results.append(result)
    registered_id_set = set(registered_ids)
    for observed_step in observed["steps"]:
        step_id = observed_step["step_id"]
        if step_id not in registered_id_set:
            step_results.append({
                "step_id": step_id,
                "status": "failed",
                "differences": ["extra_step"],
            })
            findings.append(_finding(
                "STEP_EXTRA",
                "The observed preprocessing pipeline includes a step that was not registered.",
                step_id=step_id,
            ))
    return findings, step_results


def _verify_retained_pipeline_comparison(
    record: dict[str, Any],
    *,
    pipeline_id: str,
    registered: dict[str, Any],
    observed: dict[str, Any],
    step_results: list[dict[str, Any]],
    findings: list[dict[str, str]],
    status: str,
) -> str:
    has_registered_snapshot = "registered_pipeline_snapshot" in record
    has_observed_snapshot = "observed_pipeline_snapshot" in record
    if has_registered_snapshot != has_observed_snapshot:
        raise ValidationError(
            "preprocessing conformance record must retain both pipeline snapshots"
        )
    if not has_registered_snapshot:
        return "legacy_missing"

    retained_registered = _normalize_pipeline(
        record["registered_pipeline_snapshot"],
        "registered_pipeline_snapshot",
    )
    retained_observed = _normalize_pipeline(
        record["observed_pipeline_snapshot"],
        "observed_pipeline_snapshot",
    )
    if retained_registered["pipeline_id"] != pipeline_id:
        raise ValidationError(
            "preprocessing conformance record retained registered pipeline ID mismatch"
        )
    if _pipeline_step_ids(retained_registered) != registered["step_ids"]:
        raise ValidationError(
            "preprocessing conformance record retained registered step IDs mismatch"
        )
    if retained_observed["pipeline_id"] != observed["pipeline_id"]:
        raise ValidationError(
            "preprocessing conformance record retained observed pipeline ID mismatch"
        )
    if _pipeline_step_ids(retained_observed) != observed["step_ids"]:
        raise ValidationError(
            "preprocessing conformance record retained observed step IDs mismatch"
        )

    replayed_findings, replayed_step_results = _compare_pipelines(
        retained_registered,
        retained_observed,
    )
    if step_results != replayed_step_results or findings != replayed_findings:
        raise ValidationError(
            "preprocessing conformance record disagrees with retained pipeline comparison"
        )
    replayed_status = (
        "preprocessing_conformance_failed"
        if replayed_findings
        else "preprocessing_conformance_passed"
    )
    if status != replayed_status:
        raise ValidationError(
            "preprocessing conformance record status disagrees with retained pipeline comparison"
        )
    return "verified"


def assess_preprocessing_conformance(
    registered_pipeline_file: Path,
    expected_registered_pipeline_sha256: str,
    observed_pipeline_file: Path,
    expected_observed_pipeline_sha256: str,
    output: Path,
) -> dict[str, Any]:
    """Compare observed preprocessing to a separately trusted registered pipeline."""
    expected_registered = _sha256(
        expected_registered_pipeline_sha256, "expected_registered_pipeline_sha256"
    )
    expected_observed = _sha256(
        expected_observed_pipeline_sha256, "expected_observed_pipeline_sha256"
    )
    registered_raw, registered_bytes, registered_sha256 = _load_json_object_and_sha256(
        registered_pipeline_file, "registered preprocessing pipeline"
    )
    if registered_sha256 != expected_registered:
        raise ValidationError(
            "registered preprocessing pipeline does not match expected_registered_pipeline_sha256"
        )
    observed_raw, observed_bytes, observed_sha256 = _load_json_object_and_sha256(
        observed_pipeline_file, "observed preprocessing pipeline"
    )
    if observed_sha256 != expected_observed:
        raise ValidationError(
            "observed preprocessing pipeline does not match expected_observed_pipeline_sha256"
        )
    registered = _normalize_pipeline(registered_raw, "registered")
    observed = _normalize_pipeline(observed_raw, "observed")
    findings, step_results = _compare_pipelines(registered, observed)
    status = "preprocessing_conformance_failed" if findings else "preprocessing_conformance_passed"
    record = {
        "preprocessing_conformance_version": 1,
        "pipeline_id": registered["pipeline_id"],
        "registered_pipeline": {
            "sha256": registered_sha256,
            "size_bytes": len(registered_bytes),
            "step_ids": _pipeline_step_ids(registered),
        },
        "registered_pipeline_snapshot": registered,
        "observed_pipeline": {
            "sha256": observed_sha256,
            "size_bytes": len(observed_bytes),
            "pipeline_id": observed["pipeline_id"],
            "step_ids": _pipeline_step_ids(observed),
        },
        "observed_pipeline_snapshot": observed,
        "step_results": step_results,
        "findings": findings,
        "status": status,
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Provider-free preprocessing conformance check only. It detects whether an "
            "observed preprocessing declaration matches the trusted registered pipeline, "
            "but it does not authenticate acquisition, prove implementation correctness, "
            "clear a protocol gate, register a dataset, or authorize scientific evidence."
        ),
    }
    encoded = (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()
    root = output.expanduser().resolve()
    if root.exists():
        raise ValidationError(f"preprocessing conformance output path already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-", dir=root.parent) as temporary:
        staging = Path(temporary) / root.name
        staging.mkdir()
        (staging / "preprocessing-conformance.json").write_bytes(encoded)
        try:
            os.replace(staging, root)
        except OSError as exc:
            raise ValidationError(
                f"could not publish preprocessing conformance atomically: {exc}"
            ) from exc
    return {
        "path": str(root),
        "pipeline_id": registered["pipeline_id"],
        "registered_pipeline_sha256": registered_sha256,
        "observed_pipeline_sha256": observed_sha256,
        "assessment_sha256": hashlib.sha256(encoded).hexdigest(),
        "status": status,
        "finding_count": len(findings),
        "scientific_evidence_eligible": False,
    }


def verify_preprocessing_conformance_record(
    record_file: Path,
    expected_record_sha256: str,
    *,
    expected_registered_pipeline_sha256: str | None = None,
    expected_observed_pipeline_sha256: str | None = None,
) -> dict[str, Any]:
    """Replay a retained preprocessing conformance record from current bytes."""
    expected_record = _sha256(expected_record_sha256, "expected_record_sha256")
    record, content, record_sha256 = _load_json_object_and_sha256(
        record_file, "preprocessing conformance record"
    )
    if record_sha256 != expected_record:
        raise ValidationError(
            "preprocessing conformance record does not match expected_record_sha256"
        )
    has_snapshots = (
        "registered_pipeline_snapshot" in record
        or "observed_pipeline_snapshot" in record
    )
    _exact_fields(
        record,
        _CONFORMANCE_RECORD_FIELDS
        if has_snapshots
        else _LEGACY_CONFORMANCE_RECORD_FIELDS,
        "conformance record",
    )
    if record["preprocessing_conformance_version"] != 1:
        raise ValidationError("preprocessing conformance record version is unsupported")
    pipeline_id = _stable_identifier(record["pipeline_id"], "record.pipeline_id")
    registered = _verify_snapshot(record["registered_pipeline"], "registered_pipeline")
    observed = _verify_snapshot(
        record["observed_pipeline"], "observed_pipeline", observed=True
    )
    if expected_registered_pipeline_sha256 is not None:
        expected_registered = _sha256(
            expected_registered_pipeline_sha256, "expected_registered_pipeline_sha256"
        )
        if registered["sha256"] != expected_registered:
            raise ValidationError(
                "preprocessing conformance record registered pipeline SHA-256 mismatch"
            )
    if expected_observed_pipeline_sha256 is not None:
        expected_observed = _sha256(
            expected_observed_pipeline_sha256, "expected_observed_pipeline_sha256"
        )
        if observed["sha256"] != expected_observed:
            raise ValidationError(
                "preprocessing conformance record observed pipeline SHA-256 mismatch"
            )
    step_results = _verify_step_results(record["step_results"])
    findings = _verify_findings(record["findings"])
    status = _text(record["status"], "record.status")
    if status not in {
        "preprocessing_conformance_passed",
        "preprocessing_conformance_failed",
    }:
        raise ValidationError("preprocessing conformance record status is unsupported")
    if type(record["scientific_evidence_eligible"]) is not bool:
        raise ValidationError(
            "preprocessing conformance record scientific_evidence_eligible must be boolean"
        )
    if record["scientific_evidence_eligible"] is not False:
        raise ValidationError(
            "preprocessing conformance record must remain non-evidentiary"
        )
    if record["authorized_actions"] != []:
        raise ValidationError(
            "preprocessing conformance record must not authorize actions"
        )
    _text(record["conclusion_ceiling"], "record.conclusion_ceiling")
    failed_steps = [item for item in step_results if item["status"] == "failed"]
    if status == "preprocessing_conformance_passed" and (findings or failed_steps):
        raise ValidationError(
            "passed preprocessing conformance record contains failures"
        )
    if status == "preprocessing_conformance_failed" and not (findings or failed_steps):
        raise ValidationError(
            "failed preprocessing conformance record lacks documented discrepancies"
        )
    finding_step_ids = {
        finding["step_id"] for finding in findings if "step_id" in finding
    }
    failed_step_ids = {item["step_id"] for item in failed_steps}
    undocumented_failed_steps = sorted(failed_step_ids - finding_step_ids)
    if undocumented_failed_steps:
        raise ValidationError(
            "preprocessing conformance record omits finding details for failed steps: "
            + ", ".join(undocumented_failed_steps)
        )
    comparison_replay = _verify_retained_pipeline_comparison(
        record,
        pipeline_id=pipeline_id,
        registered=registered,
        observed=observed,
        step_results=step_results,
        findings=findings,
        status=status,
    )
    return {
        "status": "preprocessing_conformance_record_verified",
        "record_sha256": record_sha256,
        "record_size_bytes": len(content),
        "record_status": status,
        "pipeline_id": pipeline_id,
        "registered_pipeline_sha256": registered["sha256"],
        "observed_pipeline_sha256": observed["sha256"],
        "observed_pipeline_id": observed["pipeline_id"],
        "step_ids": registered["step_ids"],
        "finding_count": len(findings),
        "comparison_replay": comparison_replay,
        "scientific_evidence_eligible": False,
    }
