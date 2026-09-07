"""Current-byte replay for runs that may support scientific evidence."""

from __future__ import annotations

import hashlib
import json

from research_machine.application.artifact_integrity import verify_run_artifacts
from research_machine.application.policies import require_canonical_text, require_sha256
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import ResearchRun


def run_payload_sha256(run: ResearchRun) -> str:
    """Commit the immutable run while excluding the commitment itself."""
    payload = run.to_dict()
    metadata = dict(payload.get("metadata", {}))
    metadata.pop("run_payload_sha256", None)
    payload["metadata"] = metadata
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def validate_run_payload_commitment(run: ResearchRun) -> str:
    retained = run.metadata.get("run_payload_sha256")
    if not isinstance(retained, str) or retained != run_payload_sha256(run):
        raise ValidationError(
            f"run {run.run_id} payload no longer matches its service-generated commitment"
        )
    return retained


def reverify_run_artifacts(run: ResearchRun) -> dict[str, object]:
    """Recompute a run's retained artifact receipt from its current output bytes."""
    retained = run.metadata.get("artifact_integrity")
    if not isinstance(retained, dict) or retained.get("status") != "passed":
        raise ValidationError(
            f"run {run.run_id} lacks passed service-generated artifact integrity"
        )
    root = require_canonical_text(
        run.metadata.get("run_artifact_root"), "run artifact root"
    )
    schema_path = run.metadata.get("run_attestation_schema_path")
    if schema_path is not None:
        schema_path = require_canonical_text(
            schema_path, "run attestation schema path"
        )
    schema_sha256 = run.metadata.get("expected_attestation_schema_sha256")
    if schema_sha256 is not None:
        schema_sha256 = require_sha256(
            schema_sha256, "expected attestation schema SHA-256"
        )
    report = verify_run_artifacts(
        run.output_artifacts,
        artifact_root=root,
        actor=run.executed_by,
        analysis_code_hash=run.analysis_code_hash,
        run_metadata=run.metadata,
        attestation_schema_path=schema_path,
        expected_attestation_schema_sha256=schema_sha256,
    )
    if report.status != "passed":
        raise ValidationError(
            f"run {run.run_id} artifact verification failed: "
            + ", ".join(item["code"] for item in report.findings)
        )
    current = report.to_dict()
    if current != retained:
        raise ValidationError(
            f"run {run.run_id} artifact verification no longer reproduces exactly"
        )
    return current
