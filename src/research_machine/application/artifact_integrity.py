"""Verify local run artifacts and replication attestations before recording."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from research_machine.application.json_schema_profile import (
    AttestationSchemaProfileError,
    validate_attestation_schema,
)
from research_machine.domain.models import DatasetArtifact


_PROFILE = "local-run-artifacts-attestation-and-external-freeze-v2"


@dataclass(frozen=True)
class ArtifactObservation:
    locator: str
    expected_sha256: str
    observed_sha256: str | None
    expected_size_bytes: int | None
    observed_size_bytes: int | None
    status: str


@dataclass(frozen=True)
class ArtifactIntegrityReport:
    status: str
    verification_profile: str
    artifact_count: int
    artifact_set_sha256: str
    all_artifacts_match: bool
    attestation_required: bool
    attestation_schema_sha256: str | None
    attestation_schema_matches_commitment: bool | None
    attestation_schema_valid: bool | None
    attestation_consistent: bool | None
    findings: list[dict[str, Any]]
    artifacts: list[ArtifactObservation]
    conclusion_ceiling: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finding(code: str, message: str, **details: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {"code": code, "message": message}
    if details:
        finding["details"] = details
    return finding


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _artifact_set_sha256(artifacts: Sequence[DatasetArtifact]) -> str:
    content = json.dumps(
        [artifact.to_dict() for artifact in artifacts],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _sha256_bytes(content)


def _safe_artifact_path(
    root: Path, locator: str
) -> tuple[Path | None, dict[str, Any] | None]:
    locator_path = Path(locator)
    if locator_path.is_absolute():
        return None, _finding(
            "ARTIFACT_LOCATOR_ABSOLUTE",
            "artifact locator must be relative to the supplied artifact root",
            locator=locator,
        )
    if not locator_path.parts or ".." in locator_path.parts:
        return None, _finding(
            "ARTIFACT_LOCATOR_UNSAFE",
            "artifact locator must not be empty or contain a parent traversal",
            locator=locator,
        )
    candidate = root.joinpath(locator_path)
    current = root
    for part in locator_path.parts:
        current = current / part
        if current.is_symlink():
            return None, _finding(
                "ARTIFACT_SYMLINK_REJECTED",
                "artifact locators must not traverse symbolic links",
                locator=locator,
            )
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None, _finding(
            "ARTIFACT_ESCAPES_ROOT",
            "artifact locator resolves outside the supplied artifact root",
            locator=locator,
        )
    return resolved, None


def _observe_artifact(
    root: Path, artifact: DatasetArtifact
) -> tuple[ArtifactObservation, bytes | None, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    resolved, unsafe = _safe_artifact_path(root, artifact.locator)
    if unsafe is not None:
        findings.append(unsafe)
        return (
            ArtifactObservation(
                locator=artifact.locator,
                expected_sha256=artifact.sha256,
                observed_sha256=None,
                expected_size_bytes=artifact.size_bytes,
                observed_size_bytes=None,
                status="unsafe_locator",
            ),
            None,
            findings,
        )
    assert resolved is not None
    if not resolved.exists():
        findings.append(
            _finding(
                "ARTIFACT_MISSING",
                "declared output artifact does not exist",
                locator=artifact.locator,
            )
        )
        status = "missing"
        content = None
    elif not resolved.is_file():
        findings.append(
            _finding(
                "ARTIFACT_NOT_REGULAR_FILE",
                "declared output artifact is not a regular file",
                locator=artifact.locator,
            )
        )
        status = "not_file"
        content = None
    else:
        try:
            content = resolved.read_bytes()
        except OSError as exc:
            findings.append(
                _finding(
                    "ARTIFACT_READ_FAILED",
                    "declared output artifact could not be read",
                    locator=artifact.locator,
                    error=str(exc),
                )
            )
            status = "read_failed"
            content = None
        else:
            observed_hash = _sha256_bytes(content)
            observed_size = len(content)
            hash_matches = observed_hash == artifact.sha256
            size_matches = (
                artifact.size_bytes is None
                or observed_size == artifact.size_bytes
            )
            if not hash_matches:
                findings.append(
                    _finding(
                        "ARTIFACT_HASH_MISMATCH",
                        "artifact bytes do not match the declared SHA-256",
                        locator=artifact.locator,
                        expected_sha256=artifact.sha256,
                        observed_sha256=observed_hash,
                    )
                )
            if not size_matches:
                findings.append(
                    _finding(
                        "ARTIFACT_SIZE_MISMATCH",
                        "artifact bytes do not match the declared size",
                        locator=artifact.locator,
                        expected_size_bytes=artifact.size_bytes,
                        observed_size_bytes=observed_size,
                    )
                )
            status = "passed" if hash_matches and size_matches else "mismatch"
            return (
                ArtifactObservation(
                    locator=artifact.locator,
                    expected_sha256=artifact.sha256,
                    observed_sha256=observed_hash,
                    expected_size_bytes=artifact.size_bytes,
                    observed_size_bytes=observed_size,
                    status=status,
                ),
                content,
                findings,
            )
    return (
        ArtifactObservation(
            locator=artifact.locator,
            expected_sha256=artifact.sha256,
            observed_sha256=None,
            expected_size_bytes=artifact.size_bytes,
            observed_size_bytes=None,
            status=status,
        ),
        content,
        findings,
    )


def _load_json_object(
    content: bytes, *, label: str, code_prefix: str = "ATTESTATION"
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        value = json.loads(
            content,
            parse_constant=_reject_nonfinite_json,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return None, _finding(
            f"{code_prefix}_JSON_INVALID",
            f"{label} is not valid JSON",
            error=str(exc),
        )
    if not isinstance(value, dict):
        return None, _finding(
            f"{code_prefix}_JSON_NOT_OBJECT",
            f"{label} must contain a JSON object",
        )
    return value, None


def _core_attestation_findings(
    attestation: dict[str, Any],
    *,
    actor: str,
    analysis_code_hash: str,
    run_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    independence = run_metadata.get("replication_independence")
    if not isinstance(independence, dict):
        return [
            _finding(
                "REPLICATION_INDEPENDENCE_METADATA_MISSING",
                "attestation cross-check requires replication_independence metadata",
            )
        ]

    comparisons = [
        ("executor_identity", actor),
        ("design", independence.get("design")),
        (
            "prior_implementation_accessed",
            independence.get("prior_implementation_accessed"),
        ),
        (
            "contamination_disclosures",
            independence.get("contamination_disclosures"),
        ),
    ]
    attestation_code_hash = attestation.get(
        "analysis_code_hash", attestation.get("analysis_code_sha256")
    )
    comparisons.append(("analysis_code_hash", analysis_code_hash))
    observed_values = {
        **attestation,
        "analysis_code_hash": attestation_code_hash,
    }
    replicated_run_id = run_metadata.get("replicates_run_id")
    if "target_run_id" in attestation or replicated_run_id is not None:
        comparisons.append(("target_run_id", replicated_run_id))
    for field_name, expected in comparisons:
        observed = observed_values.get(field_name)
        if observed != expected:
            findings.append(
                _finding(
                    "ATTESTATION_RUN_METADATA_MISMATCH",
                    "attestation does not agree with the run record",
                    field=field_name,
                    expected=expected,
                    observed=observed,
                )
            )

    declared_dimensions = independence.get("independence_dimensions")
    attested_dimensions = attestation.get("independence_dimensions")
    if (
        not isinstance(declared_dimensions, list)
        or not isinstance(attested_dimensions, list)
        or set(declared_dimensions) != set(attested_dimensions)
    ):
        findings.append(
            _finding(
                "ATTESTATION_RUN_METADATA_MISMATCH",
                "attested independence dimensions do not match the run record",
                field="independence_dimensions",
                expected=declared_dimensions,
                observed=attested_dimensions,
            )
        )

    manifest = attestation.get("allowed_input_manifest")
    allowed_inputs = independence.get("allowed_inputs")
    if not isinstance(manifest, dict) or not isinstance(allowed_inputs, list) or not any(
        isinstance(item, dict)
        and item.get("locator") == manifest.get("locator")
        and item.get("sha256") == manifest.get("sha256")
        for item in allowed_inputs
    ):
        findings.append(
            _finding(
                "ATTESTATION_ALLOWED_INPUT_MISMATCH",
                "attested input manifest is absent from the run's allowed-input list",
                observed=manifest,
            )
        )
    return findings


def _external_freeze_findings(
    *,
    artifacts: Sequence[DatasetArtifact],
    artifact_contents: dict[str, bytes],
    analysis_code_hash: str,
    run_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    external = run_metadata.get("external_protocol_freeze")
    if external is None:
        return []
    if not isinstance(external, dict):
        return [
            _finding(
                "EXTERNAL_FREEZE_METADATA_INVALID",
                "external_protocol_freeze must be an object",
            )
        ]
    locators_and_roles = (
        (external.get("protocol_artifact"), "external_frozen_protocol"),
        (external.get("analysis_source_artifact"), "analysis_source"),
        (external.get("freeze_manifest_artifact"), "external_freeze_manifest"),
    )
    findings: list[dict[str, Any]] = []
    matched: dict[str, DatasetArtifact] = {}
    for locator, role in locators_and_roles:
        matches = [
            artifact
            for artifact in artifacts
            if artifact.locator == locator
            and artifact.metadata.get("artifact_role") == role
        ]
        if len(matches) != 1:
            findings.append(
                _finding(
                    "EXTERNAL_FREEZE_ARTIFACT_NOT_UNIQUE",
                    "exactly one external-freeze artifact must match its locator and role",
                    locator=locator,
                    role=role,
                    matches=len(matches),
                )
            )
        elif isinstance(locator, str):
            matched[locator] = matches[0]
    manifest_locator = external.get("freeze_manifest_artifact")
    if not isinstance(manifest_locator, str) or manifest_locator not in artifact_contents:
        return findings
    manifest, manifest_error = _load_json_object(
        artifact_contents[manifest_locator],
        label="external freeze manifest",
        code_prefix="EXTERNAL_FREEZE_MANIFEST",
    )
    if manifest_error is not None:
        findings.append(manifest_error)
        return findings

    comparisons = (
        (
            "frozen_at",
            external.get("declared_frozen_at"),
            "EXTERNAL_FREEZE_TIME_MISMATCH",
        ),
        (
            "analysis_code_sha256",
            analysis_code_hash,
            "EXTERNAL_FREEZE_ANALYSIS_HASH_MISMATCH",
        ),
    )
    for field_name, expected, code in comparisons:
        observed = manifest.get(field_name)
        if observed != expected:
            findings.append(
                _finding(
                    code,
                    "external freeze manifest conflicts with the proposed run",
                    field=field_name,
                    expected=expected,
                    observed=observed,
                )
            )
    if manifest.get("scientific_execution_count_at_freeze") != 0:
        findings.append(
            _finding(
                "EXTERNAL_FREEZE_EXECUTION_COUNT_INVALID",
                "external freeze manifest must declare zero scientific executions at freeze",
                observed=manifest.get("scientific_execution_count_at_freeze"),
            )
        )

    manifest_artifacts = manifest.get("artifacts")
    if not isinstance(manifest_artifacts, list):
        findings.append(
            _finding(
                "EXTERNAL_FREEZE_ARTIFACT_LIST_INVALID",
                "external freeze manifest must contain an artifacts array",
            )
        )
        return findings
    for metadata_field in ("protocol_artifact", "analysis_source_artifact"):
        locator = external.get(metadata_field)
        if not isinstance(locator, str) or locator not in matched:
            continue
        artifact = matched[locator]
        if not any(
            isinstance(item, dict)
            and item.get("locator") == locator
            and item.get("sha256") == artifact.sha256
            for item in manifest_artifacts
        ):
            findings.append(
                _finding(
                    "EXTERNAL_FREEZE_ARTIFACT_COMMITMENT_MISSING",
                    "external freeze manifest does not commit to a required artifact",
                    locator=locator,
                    expected_sha256=artifact.sha256,
                )
            )
    protocol_locator = external.get("protocol_artifact")
    if isinstance(protocol_locator, str) and protocol_locator in matched:
        expected_protocol_hash = matched[protocol_locator].sha256
        if manifest.get("protocol_sha256") != expected_protocol_hash:
            findings.append(
                _finding(
                    "EXTERNAL_FREEZE_PROTOCOL_HASH_MISMATCH",
                    "external freeze manifest top-level protocol hash is inconsistent",
                    expected_sha256=expected_protocol_hash,
                    observed_sha256=manifest.get("protocol_sha256"),
                )
            )
    return findings


def verify_run_artifacts(
    artifacts: Sequence[DatasetArtifact],
    *,
    artifact_root: str | None,
    actor: str,
    analysis_code_hash: str,
    run_metadata: dict[str, Any],
    attestation_schema_path: str | None,
    expected_attestation_schema_sha256: str | None,
) -> ArtifactIntegrityReport:
    """Verify artifact bytes, a pinned schema, and core attestation consistency."""

    findings: list[dict[str, Any]] = []
    observations: list[ArtifactObservation] = []
    artifact_contents: dict[str, bytes] = {}
    independence = run_metadata.get("replication_independence")
    attestation_required = isinstance(independence, dict)
    schema_hash: str | None = None
    schema_matches: bool | None = None
    schema_valid: bool | None = None
    attestation_consistent: bool | None = None

    if artifact_root is None:
        findings.append(
            _finding(
                "ARTIFACT_ROOT_REQUIRED",
                "a local artifact root is required for integrity verification",
            )
        )
    else:
        root = Path(artifact_root).expanduser().resolve()
        if not root.is_dir():
            findings.append(
                _finding(
                    "ARTIFACT_ROOT_INVALID",
                    "artifact root must be an existing directory",
                )
            )
        else:
            for artifact in artifacts:
                observation, content, artifact_findings = _observe_artifact(
                    root, artifact
                )
                observations.append(observation)
                findings.extend(artifact_findings)
                if content is not None and observation.status == "passed":
                    artifact_contents[artifact.locator] = content

    findings.extend(
        _external_freeze_findings(
            artifacts=artifacts,
            artifact_contents=artifact_contents,
            analysis_code_hash=analysis_code_hash,
            run_metadata=run_metadata,
        )
    )

    schema: dict[str, Any] | None = None
    if attestation_required:
        if attestation_schema_path is None:
            findings.append(
                _finding(
                    "ATTESTATION_SCHEMA_REQUIRED",
                    "independent replication requires a local attestation schema",
                )
            )
        if expected_attestation_schema_sha256 is None:
            findings.append(
                _finding(
                    "ATTESTATION_SCHEMA_COMMITMENT_REQUIRED",
                    "independent replication requires the expected schema SHA-256",
                )
            )
    if attestation_schema_path is not None:
        schema_path = Path(attestation_schema_path).expanduser().resolve()
        try:
            schema_content = schema_path.read_bytes()
        except OSError as exc:
            findings.append(
                _finding(
                    "ATTESTATION_SCHEMA_READ_FAILED",
                    "attestation schema could not be read",
                    error=str(exc),
                )
            )
        else:
            schema_hash = _sha256_bytes(schema_content)
            schema_matches = schema_hash == expected_attestation_schema_sha256
            if not schema_matches:
                findings.append(
                    _finding(
                        "ATTESTATION_SCHEMA_HASH_MISMATCH",
                        "attestation schema bytes do not match the expected SHA-256",
                        expected_sha256=expected_attestation_schema_sha256,
                        observed_sha256=schema_hash,
                    )
                )
            schema_value, schema_error = _load_json_object(
                schema_content,
                label="attestation schema",
                code_prefix="ATTESTATION_SCHEMA",
            )
            if schema_error is not None:
                findings.append(schema_error)
            else:
                schema = schema_value
    elif expected_attestation_schema_sha256 is not None and not attestation_required:
        findings.append(
            _finding(
                "ATTESTATION_SCHEMA_REQUIRED",
                "a schema path is required when a schema commitment is supplied",
            )
        )

    if attestation_required:
        assert isinstance(independence, dict)
        attestation_locator = independence.get("attestation_artifact")
        matching = [
            artifact
            for artifact in artifacts
            if artifact.locator == attestation_locator
            and artifact.metadata.get("artifact_role")
            == "independence_attestation"
        ]
        if len(matching) != 1:
            findings.append(
                _finding(
                    "ATTESTATION_ARTIFACT_NOT_UNIQUE",
                    "exactly one declared artifact must match the attestation locator and role",
                    locator=attestation_locator,
                    matches=len(matching),
                )
            )
        elif attestation_locator in artifact_contents:
            attestation, attestation_error = _load_json_object(
                artifact_contents[attestation_locator], label="attestation artifact"
            )
            if attestation_error is not None:
                findings.append(attestation_error)
            elif schema is not None and schema_matches:
                try:
                    schema_errors = validate_attestation_schema(attestation, schema)
                except AttestationSchemaProfileError as exc:
                    findings.append(
                        _finding(
                            "ATTESTATION_SCHEMA_UNSUPPORTED",
                            "attestation schema exceeds the fail-closed supported profile",
                            error=str(exc),
                        )
                    )
                    schema_valid = False
                else:
                    schema_valid = not schema_errors
                    for error in schema_errors:
                        findings.append(
                            _finding(
                                "ATTESTATION_SCHEMA_VIOLATION",
                                "attestation does not satisfy the pinned schema",
                                error=error,
                            )
                        )
                before_core = len(findings)
                findings.extend(
                    _core_attestation_findings(
                        attestation,
                        actor=actor,
                        analysis_code_hash=analysis_code_hash,
                        run_metadata=run_metadata,
                    )
                )
                attestation_consistent = len(findings) == before_core

    all_artifacts_match = len(observations) == len(artifacts) and all(
        observation.status == "passed" for observation in observations
    )
    status = "passed" if not findings else "failed"
    return ArtifactIntegrityReport(
        status=status,
        verification_profile=_PROFILE,
        artifact_count=len(artifacts),
        artifact_set_sha256=_artifact_set_sha256(artifacts),
        all_artifacts_match=all_artifacts_match,
        attestation_required=attestation_required,
        attestation_schema_sha256=schema_hash,
        attestation_schema_matches_commitment=schema_matches,
        attestation_schema_valid=schema_valid,
        attestation_consistent=attestation_consistent,
        findings=findings,
        artifacts=observations,
        conclusion_ceiling=(
            "Local byte, external-freeze, pinned-schema, and record-consistency "
            "preflight only. "
            "A pass does not authenticate the attester, prove independence, "
            "cryptographically prove chronology, validate the scientific execution, "
            "or establish any conclusion."
        ),
    )
