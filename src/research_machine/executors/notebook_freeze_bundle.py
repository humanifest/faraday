"""Build and verify a typed, non-scientific notebook freeze-input bundle."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from research_machine.executors.notebook_preflight import (
    _atomic_write,
    _validate_sha256,
    NotebookPreflightReport,
    preflight_notebook_dependencies,
)
from research_machine.executors.runtime_preflight import (
    verify_runtime_preflight_report,
)


_SCHEMA_VERSION = 1
_BUNDLE_ID = "research-machine-notebook-freeze-input-bundle-v1"
_CONCLUSION_CEILING = (
    "Notebook freeze-input integrity bundle only. A verified bundle does not "
    "execute analysis, guarantee later runtime availability, validate a method "
    "or result, establish chronology, or create scientific evidence."
)


@dataclass(frozen=True)
class NotebookFreezeInputBundle:
    schema_version: int
    bundle_id: str
    status: str
    source_path: str
    source_sha256: str
    dependency_manifest_path: str
    dependency_manifest_sha256: str
    workspace_root: str
    dependency_hash_variable: str
    dependency_count: int
    static_preflight_receipt_path: str
    static_preflight_receipt_sha256: str
    runtime_preflight_receipt_path: str
    runtime_preflight_requirement: dict[str, str]
    source_clean: bool
    manifest_matches_notebook: bool
    files_match_manifest: bool
    kernel_started: bool
    analysis_code_executed: bool
    network_access_requested: bool
    conclusion_ceiling: str


@dataclass(frozen=True)
class NotebookFreezeInputBundleVerification:
    status: str
    bundle_path: str
    bundle_sha256: str
    bundle_size_bytes: int
    bundle_id: str
    source_path: str
    source_sha256: str
    dependency_manifest_path: str
    dependency_manifest_sha256: str
    workspace_root: str
    dependency_hash_variable: str
    dependency_count: int
    static_preflight_receipt_path: str
    static_preflight_receipt_sha256: str
    runtime_preflight_receipt_path: str
    runtime_preflight_requirement: dict[str, str]
    source_clean: bool
    manifest_matches_notebook: bool
    files_match_manifest: bool
    kernel_started: bool
    analysis_code_executed: bool
    network_access_requested: bool
    conclusion_ceiling: str


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_bytes(bundle: NotebookFreezeInputBundle) -> bytes:
    return (
        json.dumps(asdict(bundle), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _runtime_requirement(verification: Any) -> dict[str, str]:
    return {
        "receipt_sha256": verification.receipt_sha256,
        "probe_id": verification.probe_id,
        "interpreter_path": verification.interpreter_path,
        "kernel_name": verification.kernel_name,
        "working_directory": verification.working_directory,
    }


def _verify_static_preflight_receipt(
    receipt_path: Path,
    *,
    expected_sha256: str | None,
    recomputed: NotebookPreflightReport,
) -> tuple[str, str]:
    receipt_path = receipt_path.resolve()
    content = receipt_path.read_bytes()
    observed_sha256 = _sha256(content)
    if expected_sha256 is not None:
        expected_sha256 = _validate_sha256(
            expected_sha256,
            label="expected static preflight receipt sha256",
        )
        if observed_sha256 != expected_sha256:
            raise ValueError(
                "static preflight receipt hash mismatch: "
                f"expected {expected_sha256}, observed {observed_sha256}"
            )
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"static preflight receipt is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("static preflight receipt must be a JSON object")
    expected_fields = set(NotebookPreflightReport.__dataclass_fields__)
    if set(payload) != expected_fields:
        raise ValueError("static preflight receipt fields are not canonical")
    if payload != asdict(recomputed):
        raise ValueError(
            "static preflight receipt disagrees with current source, manifest, "
            "dependency, or preflight semantics"
        )
    if (
        payload.get("status") != "passed"
        or payload.get("source_clean") is not True
        or payload.get("manifest_matches_notebook") is not True
        or payload.get("files_match_manifest") is not True
        or payload.get("kernel_started") is not False
        or payload.get("findings") != []
    ):
        raise ValueError("static preflight receipt did not pass")
    return str(receipt_path), observed_sha256


def create_notebook_freeze_input_bundle(
    source_path: Path,
    dependency_manifest_path: Path,
    runtime_preflight_receipt_path: Path,
    result_path: Path,
    *,
    workspace_root: Path,
    static_preflight_receipt_path: Path,
    dependency_hash_variable: str = "EXPECTED_HASHES",
    expected_source_sha256: str | None = None,
    expected_dependency_manifest_sha256: str | None = None,
    expected_static_preflight_receipt_sha256: str | None = None,
    expected_runtime_preflight_receipt_sha256: str | None = None,
) -> NotebookFreezeInputBundle:
    """Verify all underlying inputs and atomically write one canonical bundle."""
    result_path = result_path.resolve()
    if result_path.exists():
        raise FileExistsError(f"refusing to overwrite freeze-input bundle: {result_path}")
    preflight = preflight_notebook_dependencies(
        source_path,
        dependency_manifest_path,
        workspace_root=workspace_root,
        hash_variable=dependency_hash_variable,
        expected_source_sha256=expected_source_sha256,
        expected_manifest_sha256=expected_dependency_manifest_sha256,
    )
    if preflight.status != "passed":
        codes = ", ".join(item["code"] for item in preflight.findings)
        raise ValueError(f"notebook dependency preflight failed: {codes}")
    static_receipt_path, static_receipt_sha256 = (
        _verify_static_preflight_receipt(
            static_preflight_receipt_path,
            expected_sha256=expected_static_preflight_receipt_sha256,
            recomputed=preflight,
        )
    )
    runtime = verify_runtime_preflight_report(
        runtime_preflight_receipt_path,
        expected_sha256=expected_runtime_preflight_receipt_sha256,
    )
    bundle = NotebookFreezeInputBundle(
        schema_version=_SCHEMA_VERSION,
        bundle_id=_BUNDLE_ID,
        status="passed",
        source_path=preflight.source_path,
        source_sha256=preflight.source_sha256,
        dependency_manifest_path=preflight.manifest_path,
        dependency_manifest_sha256=preflight.manifest_sha256,
        workspace_root=preflight.workspace_root,
        dependency_hash_variable=preflight.hash_variable,
        dependency_count=preflight.dependency_count,
        static_preflight_receipt_path=static_receipt_path,
        static_preflight_receipt_sha256=static_receipt_sha256,
        runtime_preflight_receipt_path=runtime.receipt_path,
        runtime_preflight_requirement=_runtime_requirement(runtime),
        source_clean=preflight.source_clean,
        manifest_matches_notebook=preflight.manifest_matches_notebook,
        files_match_manifest=preflight.files_match_manifest,
        kernel_started=False,
        analysis_code_executed=False,
        network_access_requested=False,
        conclusion_ceiling=_CONCLUSION_CEILING,
    )
    _atomic_write(result_path, _canonical_bytes(bundle))
    return bundle


def verify_notebook_freeze_input_bundle(
    bundle_path: Path,
    *,
    expected_sha256: str | None = None,
) -> NotebookFreezeInputBundleVerification:
    """Authenticate the bundle and re-verify every underlying current byte."""
    bundle_path = bundle_path.resolve()
    content = bundle_path.read_bytes()
    observed_sha256 = _sha256(content)
    if expected_sha256 is not None:
        expected_sha256 = _validate_sha256(
            expected_sha256, label="expected freeze-input bundle sha256"
        )
        if observed_sha256 != expected_sha256:
            raise ValueError(
                "freeze-input bundle hash mismatch: "
                f"expected {expected_sha256}, observed {observed_sha256}"
            )
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"freeze-input bundle is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("freeze-input bundle must be a JSON object")
    expected_fields = set(NotebookFreezeInputBundle.__dataclass_fields__)
    if set(payload) != expected_fields:
        missing = sorted(expected_fields - set(payload))
        unexpected = sorted(set(payload) - expected_fields)
        raise ValueError(
            "freeze-input bundle fields are not canonical: "
            f"missing={missing}; unexpected={unexpected}"
        )
    try:
        bundle = NotebookFreezeInputBundle(**payload)
    except TypeError as exc:
        raise ValueError(f"freeze-input bundle has invalid fields: {exc}") from exc
    if _canonical_bytes(bundle) != content:
        raise ValueError("freeze-input bundle bytes are not canonically encoded")
    if (
        bundle.schema_version != _SCHEMA_VERSION
        or bundle.bundle_id != _BUNDLE_ID
        or bundle.status != "passed"
    ):
        raise ValueError("freeze-input bundle uses an unsupported contract")
    for field_name in (
        "source_path",
        "dependency_manifest_path",
        "workspace_root",
        "static_preflight_receipt_path",
        "runtime_preflight_receipt_path",
    ):
        value = getattr(bundle, field_name)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f"freeze-input bundle {field_name} must be absolute")
        if str(Path(value).resolve()) != value:
            raise ValueError(f"freeze-input bundle {field_name} must be canonical")
    for field_name in (
        "source_sha256",
        "dependency_manifest_sha256",
        "static_preflight_receipt_sha256",
    ):
        _validate_sha256(getattr(bundle, field_name), label=field_name)
    if not isinstance(bundle.dependency_hash_variable, str) or not bundle.dependency_hash_variable.isidentifier():
        raise ValueError("freeze-input bundle dependency hash variable is invalid")
    if (
        not isinstance(bundle.dependency_count, int)
        or isinstance(bundle.dependency_count, bool)
        or bundle.dependency_count < 1
    ):
        raise ValueError("freeze-input bundle dependency count must be positive")
    runtime_requirement_fields = {
        "receipt_sha256",
        "probe_id",
        "interpreter_path",
        "kernel_name",
        "working_directory",
    }
    runtime_requirement = bundle.runtime_preflight_requirement
    if (
        not isinstance(runtime_requirement, dict)
        or set(runtime_requirement) != runtime_requirement_fields
        or any(not isinstance(value, str) for value in runtime_requirement.values())
    ):
        raise ValueError("freeze-input bundle runtime requirement is not canonical")
    _validate_sha256(
        runtime_requirement["receipt_sha256"],
        label="runtime_preflight_requirement.receipt_sha256",
    )
    required_true = (
        "source_clean",
        "manifest_matches_notebook",
        "files_match_manifest",
    )
    if any(getattr(bundle, field) is not True for field in required_true):
        raise ValueError("freeze-input bundle lacks a required passed integrity flag")
    required_false = (
        "kernel_started",
        "analysis_code_executed",
        "network_access_requested",
    )
    if any(getattr(bundle, field) is not False for field in required_false):
        raise ValueError("freeze-input bundle violates its no-execution boundary")
    if bundle.conclusion_ceiling != _CONCLUSION_CEILING:
        raise ValueError("freeze-input bundle conclusion ceiling was altered")

    preflight = preflight_notebook_dependencies(
        Path(bundle.source_path),
        Path(bundle.dependency_manifest_path),
        workspace_root=Path(bundle.workspace_root),
        hash_variable=bundle.dependency_hash_variable,
        expected_source_sha256=bundle.source_sha256,
        expected_manifest_sha256=bundle.dependency_manifest_sha256,
    )
    if preflight.status != "passed":
        codes = ", ".join(item["code"] for item in preflight.findings)
        raise ValueError(f"freeze-input bundle dependency replay failed: {codes}")
    if preflight.dependency_count != bundle.dependency_count:
        raise ValueError("freeze-input bundle dependency count changed")
    _verify_static_preflight_receipt(
        Path(bundle.static_preflight_receipt_path),
        expected_sha256=bundle.static_preflight_receipt_sha256,
        recomputed=preflight,
    )
    runtime = verify_runtime_preflight_report(
        Path(bundle.runtime_preflight_receipt_path),
        expected_sha256=runtime_requirement["receipt_sha256"],
    )
    if _runtime_requirement(runtime) != runtime_requirement:
        raise ValueError("freeze-input bundle runtime requirement changed")
    return NotebookFreezeInputBundleVerification(
        status="passed",
        bundle_path=str(bundle_path),
        bundle_sha256=observed_sha256,
        bundle_size_bytes=len(content),
        bundle_id=bundle.bundle_id,
        source_path=bundle.source_path,
        source_sha256=bundle.source_sha256,
        dependency_manifest_path=bundle.dependency_manifest_path,
        dependency_manifest_sha256=bundle.dependency_manifest_sha256,
        workspace_root=bundle.workspace_root,
        dependency_hash_variable=bundle.dependency_hash_variable,
        dependency_count=bundle.dependency_count,
        static_preflight_receipt_path=bundle.static_preflight_receipt_path,
        static_preflight_receipt_sha256=bundle.static_preflight_receipt_sha256,
        runtime_preflight_receipt_path=bundle.runtime_preflight_receipt_path,
        runtime_preflight_requirement=dict(bundle.runtime_preflight_requirement),
        source_clean=bundle.source_clean,
        manifest_matches_notebook=bundle.manifest_matches_notebook,
        files_match_manifest=bundle.files_match_manifest,
        kernel_started=bundle.kernel_started,
        analysis_code_executed=bundle.analysis_code_executed,
        network_access_requested=bundle.network_access_requested,
        conclusion_ceiling=bundle.conclusion_ceiling,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify a typed notebook freeze-input bundle."
    )
    commands = parser.add_subparsers(dest="action", required=True)
    create = commands.add_parser("create")
    create.add_argument("source", type=Path)
    create.add_argument("--manifest", required=True, type=Path)
    create.add_argument("--workspace-root", required=True, type=Path)
    create.add_argument("--static-preflight-receipt", required=True, type=Path)
    create.add_argument("--runtime-preflight-receipt", required=True, type=Path)
    create.add_argument("--result-json", required=True, type=Path)
    create.add_argument("--hash-variable", default="EXPECTED_HASHES")
    create.add_argument("--expect-source-sha256")
    create.add_argument("--expect-manifest-sha256")
    create.add_argument("--expect-static-preflight-receipt-sha256")
    create.add_argument("--expect-runtime-preflight-receipt-sha256")
    verify = commands.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    verify.add_argument("--expect-bundle-sha256")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "create":
            bundle = create_notebook_freeze_input_bundle(
                args.source,
                args.manifest,
                args.runtime_preflight_receipt,
                args.result_json,
                workspace_root=args.workspace_root,
                static_preflight_receipt_path=args.static_preflight_receipt,
                dependency_hash_variable=args.hash_variable,
                expected_source_sha256=args.expect_source_sha256,
                expected_dependency_manifest_sha256=args.expect_manifest_sha256,
                expected_static_preflight_receipt_sha256=(
                    args.expect_static_preflight_receipt_sha256
                ),
                expected_runtime_preflight_receipt_sha256=(
                    args.expect_runtime_preflight_receipt_sha256
                ),
            )
            content = args.result_json.resolve().read_bytes()
            payload: dict[str, Any] = {
                **asdict(bundle),
                "bundle_path": str(args.result_json.resolve()),
                "bundle_sha256": _sha256(content),
                "bundle_size_bytes": len(content),
            }
        else:
            payload = asdict(
                verify_notebook_freeze_input_bundle(
                    args.bundle,
                    expected_sha256=args.expect_bundle_sha256,
                )
            )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "input_error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "kernel_started": False,
                    "analysis_code_executed": False,
                    "conclusion_ceiling": _CONCLUSION_CEILING,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
