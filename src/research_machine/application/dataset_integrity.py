"""Registration-time verification and current-byte replay for protected datasets."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Sequence

from research_machine.application.artifact_integrity import verify_run_artifacts
from research_machine.application.policies import require_canonical_text
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import DatasetArtifact, DatasetManifest, ExperimentProtocol


_SCOPE = "registered observation bytes under the supplied local artifact root"


def dataset_payload_sha256(dataset: DatasetManifest) -> str:
    """Commit the immutable dataset while excluding the commitment itself."""
    payload = dataset.to_dict()
    metadata = dict(payload.get("metadata", {}))
    metadata.pop("dataset_payload_sha256", None)
    payload["metadata"] = metadata
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def validate_dataset_payload_commitment(dataset: DatasetManifest) -> str:
    retained = dataset.metadata.get("dataset_payload_sha256")
    if not isinstance(retained, str) or retained != dataset_payload_sha256(dataset):
        raise ValidationError(
            f"dataset {dataset.dataset_id} payload no longer matches its service-generated commitment"
        )
    return retained


def _integrity(
    artifacts: Sequence[DatasetArtifact], artifact_root: str, actor: str
) -> dict[str, object]:
    report = verify_run_artifacts(
        artifacts,
        artifact_root=artifact_root,
        actor=actor,
        analysis_code_hash="",
        run_metadata={},
        attestation_schema_path=None,
        expected_attestation_schema_sha256=None,
    )
    if report.status != "passed":
        raise ValidationError(
            "dataset artifact verification failed: "
            + ", ".join(item["code"] for item in report.findings)
        )
    return report.to_dict()


def _timestamp(value: str, field_name: str) -> str:
    timestamp = require_canonical_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be valid ISO-8601") from exc
    if parsed.utcoffset() is None:
        raise ValidationError(f"{field_name} must include a UTC offset")
    return timestamp


def verify_dataset_artifacts(
    artifacts: Sequence[DatasetArtifact],
    artifact_root: str,
    *,
    actor: str,
    verified_at: str,
    protocol_hash: str | None,
) -> dict[str, object]:
    """Verify protected observation bytes and create a replayable receipt."""
    root = str(
        Path(require_canonical_text(artifact_root, "artifact root"))
        .expanduser()
        .resolve()
    )
    verifier = require_canonical_text(actor, "verification actor")
    timestamp = _timestamp(verified_at, "verification time")
    return {
        "verification_version": 1,
        "verified_at": timestamp,
        "verified_by": verifier,
        "dataset_artifact_root": root,
        "protocol_hash": protocol_hash,
        "artifact_integrity": _integrity(artifacts, root, verifier),
        "scope": _SCOPE,
        "scientific_interpretation_verified": False,
    }


def reverify_dataset_artifacts(
    dataset: DatasetManifest, protocol: ExperimentProtocol
) -> dict[str, object]:
    """Recompute a protected dataset receipt from retained structure and bytes."""
    receipt = dataset.metadata.get("dataset_artifact_verification")
    if not isinstance(receipt, dict):
        raise ValidationError(
            f"dataset {dataset.dataset_id} lacks service-generated artifact verification"
        )
    root = require_canonical_text(
        receipt.get("dataset_artifact_root"), "dataset artifact root"
    )
    actor = require_canonical_text(receipt.get("verified_by"), "verification actor")
    verified_at = _timestamp(receipt.get("verified_at"), "verification time")
    expected = {
        "verification_version": 1,
        "verified_at": verified_at,
        "verified_by": actor,
        "dataset_artifact_root": str(Path(root).expanduser().resolve()),
        "protocol_hash": protocol.protocol_hash,
        "artifact_integrity": _integrity(dataset.artifacts, root, actor),
        "scope": _SCOPE,
        "scientific_interpretation_verified": False,
    }
    if receipt != expected:
        raise ValidationError(
            f"dataset {dataset.dataset_id} artifact verification no longer reproduces exactly"
        )
    return expected
