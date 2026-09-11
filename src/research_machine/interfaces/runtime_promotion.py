"""Read-only, manifest-driven checks before promoting a Faraday runtime."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ResearchMachineError
from research_machine.executors.notebook_freeze_bundle import (
    verify_notebook_freeze_input_bundle,
)
from research_machine.interfaces.cli import (
    _RUN_FIELDS,
    _read_json_object_and_hash,
    _reject_duplicate_json_keys,
    _reject_nonfinite_json,
    _run_command,
)


_CONTRACT_ID = "research-machine-runtime-promotion-audit-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,95}")
_RUNTIME_SOURCE_RELATIVE_PATH = Path(
    "src/research_machine/interfaces/runtime_promotion.py"
)
_MANIFEST_FIELDS = {
    "schema_version",
    "runtime_repository",
    "expected_runtime_revision",
    "expected_runtime_clean",
    "workspace",
    "representative_run",
    "notebook_freeze_bundle",
}
_WORKSPACE_FIELDS = {
    "path",
    "inquiry_id",
    "expected_ledger_head_sha256",
    "expected_conclusion_ceiling",
}
_RUN_FIELDS_IN_MANIFEST = {
    "record_path",
    "expected_record_sha256",
    "expected_preflight_status",
    "expected_record_status_if_submitted",
    "expected_effective_evidence_eligibility",
    "artifact_root",
    "attestation_schema_path",
    "expected_attestation_schema_sha256",
}
_BUNDLE_FIELDS = {"path", "expected_sha256"}
_CONCLUSION_CEILING = (
    "Runtime-promotion process audit only. A pass reports agreement with one "
    "hash-bound manifest and current local bytes. It does not establish "
    "scientific validity, execution truth, chronology, independence, or "
    "evidence eligibility beyond the representative preflight prediction."
)


def _require_object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _require_exact_fields(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    field_name: str,
) -> None:
    missing = sorted(required - set(value))
    unexpected = sorted(set(value) - required - optional)
    if missing or unexpected:
        raise ValueError(
            f"{field_name} fields are not canonical: "
            f"missing={missing}; unexpected={unexpected}"
        )


def _require_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be 64 lowercase hexadecimal characters"
        )
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be nonempty text")
    if value != value.strip():
        raise ValueError(f"{field_name} must be canonical")
    return value


def _require_path(value: Any, field_name: str) -> Path:
    text = _require_text(value, field_name)
    path = Path(text)
    if not path.is_absolute():
        raise ValueError(f"{field_name} must be absolute")
    resolved = path.resolve()
    if str(resolved) != text:
        raise ValueError(f"{field_name} must be a canonical absolute path")
    return resolved


def _load_manifest(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[dict[str, Any], str, int]:
    expected_sha256 = _require_sha256(expected_sha256, "expected manifest sha256")
    path = path.resolve()
    try:
        content = path.read_bytes()
        manifest = json.loads(
            content,
            parse_constant=_reject_nonfinite_json,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            f"could not read runtime-promotion manifest {path}: {exc}"
        ) from exc
    observed_sha256 = hashlib.sha256(content).hexdigest()
    if observed_sha256 != expected_sha256:
        raise ValueError(
            "runtime-promotion manifest hash mismatch: "
            f"expected {expected_sha256}, observed {observed_sha256}"
        )
    manifest = _require_object(manifest, "runtime-promotion manifest")
    _require_exact_fields(
        manifest,
        required=_MANIFEST_FIELDS - {"notebook_freeze_bundle"},
        optional={"notebook_freeze_bundle"},
        field_name="runtime-promotion manifest",
    )
    if (
        not isinstance(manifest["schema_version"], int)
        or isinstance(manifest["schema_version"], bool)
        or manifest["schema_version"] != 1
    ):
        raise ValueError("runtime-promotion manifest schema_version must be 1")
    _require_path(manifest["runtime_repository"], "runtime_repository")
    revision = manifest["expected_runtime_revision"]
    if not isinstance(revision, str) or _GIT_REVISION.fullmatch(revision) is None:
        raise ValueError(
            "expected_runtime_revision must be 40 or 64 lowercase hexadecimal "
            "characters"
        )
    if manifest["expected_runtime_clean"] is not True:
        raise ValueError("expected_runtime_clean must be true for runtime promotion")

    workspace = _require_object(manifest["workspace"], "workspace")
    _require_exact_fields(
        workspace,
        required=_WORKSPACE_FIELDS,
        field_name="workspace",
    )
    _require_path(workspace["path"], "workspace.path")
    inquiry_id = _require_text(workspace["inquiry_id"], "workspace.inquiry_id")
    if _SAFE_ID.fullmatch(inquiry_id) is None:
        raise ValueError("workspace.inquiry_id is not a canonical inquiry ID")
    _require_sha256(
        workspace["expected_ledger_head_sha256"],
        "workspace.expected_ledger_head_sha256",
    )
    _require_text(
        workspace["expected_conclusion_ceiling"],
        "workspace.expected_conclusion_ceiling",
    )

    representative = _require_object(
        manifest["representative_run"], "representative_run"
    )
    required_run_fields = _RUN_FIELDS_IN_MANIFEST - {
        "artifact_root",
        "attestation_schema_path",
        "expected_attestation_schema_sha256",
    }
    _require_exact_fields(
        representative,
        required=required_run_fields,
        optional=_RUN_FIELDS_IN_MANIFEST - required_run_fields,
        field_name="representative_run",
    )
    _require_path(representative["record_path"], "representative_run.record_path")
    _require_sha256(
        representative["expected_record_sha256"],
        "representative_run.expected_record_sha256",
    )
    expected_preflight_status = representative["expected_preflight_status"]
    if (
        not isinstance(expected_preflight_status, str)
        or expected_preflight_status not in {"ready", "would_record_invalid"}
    ):
        raise ValueError(
            "representative_run.expected_preflight_status must be ready or "
            "would_record_invalid"
        )
    expected_record_status = representative["expected_record_status_if_submitted"]
    if (
        not isinstance(expected_record_status, str)
        or expected_record_status not in {"completed", "invalid"}
    ):
        raise ValueError(
            "representative_run.expected_record_status_if_submitted must be "
            "completed or invalid"
        )
    if not isinstance(
        representative["expected_effective_evidence_eligibility"], bool
    ):
        raise ValueError(
            "representative_run.expected_effective_evidence_eligibility must "
            "be boolean"
        )
    if "artifact_root" in representative:
        _require_path(
            representative["artifact_root"], "representative_run.artifact_root"
        )
    attestation_fields = {
        "attestation_schema_path",
        "expected_attestation_schema_sha256",
    }
    present_attestation_fields = attestation_fields & set(representative)
    if present_attestation_fields and present_attestation_fields != attestation_fields:
        raise ValueError(
            "representative_run attestation schema path and digest must be "
            "supplied together"
        )
    if present_attestation_fields:
        _require_path(
            representative["attestation_schema_path"],
            "representative_run.attestation_schema_path",
        )
        _require_sha256(
            representative["expected_attestation_schema_sha256"],
            "representative_run.expected_attestation_schema_sha256",
        )

    if "notebook_freeze_bundle" in manifest:
        bundle = _require_object(
            manifest["notebook_freeze_bundle"], "notebook_freeze_bundle"
        )
        _require_exact_fields(
            bundle,
            required=_BUNDLE_FIELDS,
            field_name="notebook_freeze_bundle",
        )
        _require_path(bundle["path"], "notebook_freeze_bundle.path")
        _require_sha256(
            bundle["expected_sha256"],
            "notebook_freeze_bundle.expected_sha256",
        )
    return manifest, observed_sha256, len(content)


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        [
            "git",
            "-c",
            "color.ui=false",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repository),
            *arguments,
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        env=environment,
    )


def _current_runtime_source() -> Path:
    return Path(__file__).resolve()


def _runtime_check(
    manifest: dict[str, Any],
    *,
    runtime_source_path: Path,
) -> dict[str, Any]:
    repository = Path(manifest["runtime_repository"])
    expected_revision = manifest["expected_runtime_revision"]
    expected_source_path = repository / _RUNTIME_SOURCE_RELATIVE_PATH
    runtime_source_path = runtime_source_path.resolve()
    source_path_matches = (
        runtime_source_path == expected_source_path
        and runtime_source_path.is_file()
        and not expected_source_path.is_symlink()
    )
    try:
        revision = _git(repository, "rev-parse", "--verify", "HEAD^{commit}")
        status = _git(
            repository,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        )
        try:
            _git(
                repository,
                "ls-files",
                "--error-unmatch",
                str(_RUNTIME_SOURCE_RELATIVE_PATH),
            )
            runtime_source_tracked = True
        except subprocess.CalledProcessError:
            runtime_source_tracked = False
        observed_revision = revision.stdout.decode("ascii").strip()
        dirty_entries = [
            line.decode("utf-8", errors="backslashreplace")
            for line in status.stdout.splitlines()
            if line
        ]
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        return {
            "status": "failed",
            "expected_revision": expected_revision,
            "expected_clean": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    observed_clean = not dirty_entries
    passed = (
        observed_revision == expected_revision
        and observed_clean
        and source_path_matches
        and runtime_source_tracked
    )
    return {
        "status": "passed" if passed else "failed",
        "expected_revision": expected_revision,
        "observed_revision": observed_revision,
        "expected_clean": True,
        "observed_clean": observed_clean,
        "dirty_entry_count": len(dirty_entries),
        "dirty_entries": dirty_entries,
        "expected_runtime_source_path": str(expected_source_path),
        "observed_runtime_source_path": str(runtime_source_path),
        "runtime_source_path_matches": source_path_matches,
        "runtime_source_tracked": runtime_source_tracked,
    }


def _workspace_check(manifest: dict[str, Any]) -> dict[str, Any]:
    spec = manifest["workspace"]
    repository = FileSystemRepository(spec["path"])
    service = ResearchService(repository, actor="runtime-promotion-audit")
    try:
        ledger = service.verify_ledger(spec["inquiry_id"])
        audit = service.audit_rigor(spec["inquiry_id"], fail_on="never")
    except (ResearchMachineError, OSError, ValueError) as exc:
        return {
            "status": "failed",
            "expected_ledger_head_sha256": spec[
                "expected_ledger_head_sha256"
            ],
            "expected_conclusion_ceiling": spec[
                "expected_conclusion_ceiling"
            ],
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    severity_counts = Counter(finding.severity.value for finding in audit.findings)
    passed = (
        ledger.get("valid") is True
        and ledger.get("head_hash") == spec["expected_ledger_head_sha256"]
        and audit.structurally_valid is True
        and audit.conclusion_ceiling == spec["expected_conclusion_ceiling"]
    )
    return {
        "status": "passed" if passed else "failed",
        "ledger_valid": ledger.get("valid"),
        "ledger_event_count": ledger.get("events"),
        "expected_ledger_head_sha256": spec["expected_ledger_head_sha256"],
        "observed_ledger_head_sha256": ledger.get("head_hash"),
        "structurally_valid": audit.structurally_valid,
        "expected_conclusion_ceiling": spec["expected_conclusion_ceiling"],
        "observed_conclusion_ceiling": audit.conclusion_ceiling,
        "rigor_finding_counts": {
            severity: severity_counts.get(severity, 0)
            for severity in ("error", "warning", "info")
        },
    }


def _representative_run_check(manifest: dict[str, Any]) -> dict[str, Any]:
    workspace = manifest["workspace"]
    spec = manifest["representative_run"]
    record_path = Path(spec["record_path"])
    expected_record_sha256 = spec["expected_record_sha256"]
    try:
        value, observed_sha256, size_bytes = _read_json_object_and_hash(
            record_path,
            allowed_fields=_RUN_FIELDS,
            label="representative run",
        )
    except (OSError, ValueError) as exc:
        return {
            "status": "failed",
            "expected_record_sha256": expected_record_sha256,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    base = {
        "record_path": str(record_path),
        "expected_record_sha256": expected_record_sha256,
        "observed_record_sha256": observed_sha256,
        "record_size_bytes": size_bytes,
        "expected_preflight_status": spec["expected_preflight_status"],
        "expected_record_status_if_submitted": spec[
            "expected_record_status_if_submitted"
        ],
        "expected_effective_evidence_eligibility": spec[
            "expected_effective_evidence_eligibility"
        ],
    }
    if observed_sha256 != expected_record_sha256:
        return {**base, "status": "failed", "preflight_skipped": True}
    artifact_root = (
        Path(spec["artifact_root"]) if "artifact_root" in spec else None
    )
    attestation_schema = (
        Path(spec["attestation_schema_path"])
        if "attestation_schema_path" in spec
        else None
    )
    try:
        command = _run_command(
            value,
            artifact_root=artifact_root,
            attestation_schema=attestation_schema,
            expected_attestation_schema_sha256=spec.get(
                "expected_attestation_schema_sha256"
            ),
        )
        service = ResearchService(
            FileSystemRepository(workspace["path"]),
            actor="runtime-promotion-audit",
        )
        preflight = service.preflight_run(command, workspace["inquiry_id"])
    except (ResearchMachineError, OSError, ValueError) as exc:
        return {
            **base,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    observed_record_status = (
        preflight.record_status_if_submitted.value
        if preflight.record_status_if_submitted is not None
        else None
    )
    passed = (
        preflight.would_append_event is False
        and preflight.status == spec["expected_preflight_status"]
        and observed_record_status
        == spec["expected_record_status_if_submitted"]
        and preflight.scientific_evidence_eligible_if_submitted
        is spec["expected_effective_evidence_eligibility"]
    )
    return {
        **base,
        "status": "passed" if passed else "failed",
        "observed_preflight_status": preflight.status,
        "observed_record_status_if_submitted": observed_record_status,
        "observed_effective_evidence_eligibility": (
            preflight.scientific_evidence_eligible_if_submitted
        ),
        "would_append_event": preflight.would_append_event,
        "requested_run_id_conflicts": preflight.requested_run_id_conflicts,
        "exact_quality_gate_set": preflight.exact_quality_gate_set,
        "quality_gate_order_matches_protocol": (
            preflight.quality_gate_order_matches_protocol
        ),
    }


def _bundle_check(manifest: dict[str, Any]) -> dict[str, Any]:
    spec = manifest.get("notebook_freeze_bundle")
    if spec is None:
        return {"status": "not_requested"}
    try:
        verification = verify_notebook_freeze_input_bundle(
            Path(spec["path"]),
            expected_sha256=spec["expected_sha256"],
        )
    except (OSError, ValueError) as exc:
        return {
            "status": "failed",
            "expected_sha256": spec["expected_sha256"],
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    return {
        "status": "passed",
        "expected_sha256": spec["expected_sha256"],
        "observed_sha256": verification.bundle_sha256,
        "dependency_count": verification.dependency_count,
        "source_sha256": verification.source_sha256,
        "static_preflight_receipt_sha256": (
            verification.static_preflight_receipt_sha256
        ),
        "runtime_preflight_receipt_sha256": (
            verification.runtime_preflight_requirement["receipt_sha256"]
        ),
    }


def audit_runtime_promotion(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
    _runtime_source_path: Path | None = None,
) -> dict[str, Any]:
    """Run all manifest-pinned checks without writing the target workspace."""
    manifest_path = manifest_path.resolve()
    manifest, manifest_sha256, manifest_size_bytes = _load_manifest(
        manifest_path,
        expected_sha256=expected_manifest_sha256,
    )
    checks = {
        "runtime_revision_and_cleanliness": _runtime_check(
            manifest,
            runtime_source_path=(
                _runtime_source_path or _current_runtime_source()
            ),
        ),
        "workspace": _workspace_check(manifest),
        "representative_run": _representative_run_check(manifest),
        "notebook_freeze_bundle": _bundle_check(manifest),
    }
    passed = all(
        check["status"] in {"passed", "not_requested"}
        for check in checks.values()
    )
    return {
        "contract_id": _CONTRACT_ID,
        "status": "passed" if passed else "failed",
        "manifest_expectations_met": passed,
        "promotion_authorized": False,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "manifest_size_bytes": manifest_size_bytes,
        "checks": checks,
        "target_workspace_modified": False,
        "scientific_validity_interpreted": False,
        "conclusion_ceiling": _CONCLUSION_CEILING,
    }
