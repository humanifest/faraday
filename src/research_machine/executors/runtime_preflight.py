"""Probe a Jupyter runtime without loading or executing an analysis notebook."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


_PROBE_ID = "research-machine-runtime-preflight-v1"
_MARKER = "RESEARCH_MACHINE_RUNTIME_PREFLIGHT_V1"
_SMOKE_CODE = (
    "import json, os\n"
    f"print(json.dumps({{'marker': {_MARKER!r}, 'cwd': os.getcwd()}}, "
    "sort_keys=True))\n"
)
_SMOKE_CODE_SHA256 = hashlib.sha256(_SMOKE_CODE.encode("utf-8")).hexdigest()
_CONCLUSION_CEILING = (
    "Runtime capability check only. A pass does not authenticate an analysis "
    "source or dependency, predict later availability, validate a method or "
    "result, or create scientific evidence."
)


@dataclass(frozen=True)
class KernelProbeObservation:
    """Low-level runtime observation, injectable for deterministic tests."""

    dependency_versions: dict[str, str]
    kernel_spec_found: bool
    kernel_started: bool
    kernel_ready: bool
    smoke_cell_executed: bool
    marker_observed: str | None
    observed_working_directory: str | None
    kernel_shutdown: bool
    findings: list[dict[str, Any]]


@dataclass(frozen=True)
class RuntimePreflightReport:
    schema_version: int
    probe_id: str
    status: str
    started_at: str
    completed_at: str
    interpreter_path: str
    python_version: str
    kernel_name: str
    timeout_seconds: int
    working_directory: str
    required_distributions: list[str]
    dependency_versions: dict[str, str]
    kernel_spec_found: bool
    kernel_started: bool
    kernel_ready: bool
    smoke_cell_executed: bool
    marker_verified: bool
    working_directory_verified: bool
    kernel_shutdown: bool
    smoke_code_sha256: str
    analysis_source_loaded: bool
    analysis_code_executed: bool
    network_access_requested: bool
    findings: list[dict[str, Any]]
    conclusion_ceiling: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finding(code: str, message: str, **details: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "message": message}
    if details:
        value["details"] = details
    return value


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("runtime preflight exceeded its timeout")
    return remaining


def _message_for(
    getter: Callable[..., dict[str, Any]],
    message_id: str,
    *,
    deadline: float,
) -> dict[str, Any]:
    while True:
        message = getter(timeout=_remaining_seconds(deadline))
        if message.get("parent_header", {}).get("msg_id") == message_id:
            return message


def _runtime_versions() -> dict[str, str]:
    return {
        distribution: importlib.metadata.version(distribution)
        for distribution in ("jupyter-client", "nbclient", "nbformat")
    }


def _probe_runtime(
    *, kernel_name: str, working_directory: Path, timeout_seconds: int
) -> KernelProbeObservation:
    """Start one kernel and execute only the fixed generated marker cell."""
    try:
        from jupyter_client import KernelManager
        from jupyter_client.kernelspec import KernelSpecManager

        versions = _runtime_versions()
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        return KernelProbeObservation(
            dependency_versions={},
            kernel_spec_found=False,
            kernel_started=False,
            kernel_ready=False,
            smoke_cell_executed=False,
            marker_observed=None,
            observed_working_directory=None,
            kernel_shutdown=False,
            findings=[
                _finding(
                    "RUNTIME_DEPENDENCY_UNAVAILABLE",
                    "the fixed notebook runtime dependencies are unavailable",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            ],
        )

    try:
        KernelSpecManager().get_kernel_spec(kernel_name)
    except BaseException as exc:
        return KernelProbeObservation(
            dependency_versions=versions,
            kernel_spec_found=False,
            kernel_started=False,
            kernel_ready=False,
            smoke_cell_executed=False,
            marker_observed=None,
            observed_working_directory=None,
            kernel_shutdown=False,
            findings=[
                _finding(
                    "KERNEL_SPEC_UNAVAILABLE",
                    "the requested Jupyter kernel specification is unavailable",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            ],
        )

    manager = KernelManager(kernel_name=kernel_name)
    client: Any | None = None
    kernel_started = False
    kernel_ready = False
    smoke_cell_executed = False
    marker_observed: str | None = None
    observed_working_directory: str | None = None
    kernel_shutdown = False
    findings: list[dict[str, Any]] = []
    phase = "kernel_start"
    deadline = time.monotonic() + timeout_seconds
    try:
        manager.start_kernel(cwd=str(working_directory))
        kernel_started = True
        phase = "kernel_ready"
        client = manager.client()
        client.start_channels()
        client.wait_for_ready(timeout=_remaining_seconds(deadline))
        kernel_ready = True

        phase = "smoke_cell"
        message_id = client.execute(
            _SMOKE_CODE,
            silent=False,
            store_history=False,
            allow_stdin=False,
            stop_on_error=True,
        )
        shell_reply = _message_for(
            client.get_shell_msg, message_id, deadline=deadline
        )
        stdout_parts: list[str] = []
        error_content: dict[str, Any] | None = None
        while True:
            message = _message_for(
                client.get_iopub_msg, message_id, deadline=deadline
            )
            message_type = message.get("msg_type")
            content = message.get("content", {})
            if message_type == "stream" and content.get("name") == "stdout":
                stdout_parts.append(str(content.get("text", "")))
            elif message_type == "error":
                error_content = content
            elif message_type == "status" and content.get("execution_state") == "idle":
                break

        reply_status = shell_reply.get("content", {}).get("status")
        if reply_status != "ok" or error_content is not None:
            findings.append(
                _finding(
                    "SMOKE_CELL_FAILED",
                    "the fixed generated smoke cell did not complete successfully",
                    reply_status=reply_status,
                    error_name=(error_content or {}).get("ename"),
                    error_value=(error_content or {}).get("evalue"),
                )
            )
        else:
            smoke_cell_executed = True
            decoded: dict[str, Any] | None = None
            for line in "".join(stdout_parts).splitlines():
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict) and candidate.get("marker") == _MARKER:
                    decoded = candidate
            if decoded is None:
                findings.append(
                    _finding(
                        "SMOKE_OUTPUT_INVALID",
                        "the fixed marker was absent from smoke-cell output",
                    )
                )
            else:
                marker_observed = str(decoded.get("marker"))
                observed_working_directory = str(decoded.get("cwd"))
                if Path(observed_working_directory).resolve() != working_directory:
                    findings.append(
                        _finding(
                            "WORKING_DIRECTORY_MISMATCH",
                            "the kernel did not use the requested working directory",
                            expected=str(working_directory),
                            observed=observed_working_directory,
                        )
                    )
    except BaseException as exc:
        code = {
            "kernel_start": "KERNEL_START_FAILED",
            "kernel_ready": "KERNEL_NOT_READY",
            "smoke_cell": "SMOKE_CELL_FAILED",
        }[phase]
        findings.append(
            _finding(
                code,
                "the Jupyter runtime probe failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        )
    finally:
        if kernel_started:
            try:
                manager.shutdown_kernel(now=True)
                kernel_shutdown = True
            except BaseException as exc:
                findings.append(
                    _finding(
                        "KERNEL_SHUTDOWN_FAILED",
                        "the preflight kernel could not be shut down cleanly",
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                )
        if client is not None:
            try:
                client.stop_channels()
            except BaseException:
                pass

    return KernelProbeObservation(
        dependency_versions=versions,
        kernel_spec_found=True,
        kernel_started=kernel_started,
        kernel_ready=kernel_ready,
        smoke_cell_executed=smoke_cell_executed,
        marker_observed=marker_observed,
        observed_working_directory=observed_working_directory,
        kernel_shutdown=kernel_shutdown,
        findings=findings,
    )


def preflight_notebook_runtime(
    result_path: Path,
    *,
    working_directory: Path,
    timeout_seconds: int = 30,
    kernel_name: str = "python3",
    probe: Callable[..., KernelProbeObservation] | None = None,
    clock: Callable[[], str] = _utc_now,
) -> RuntimePreflightReport:
    """Run and persist a fixed no-analysis runtime probe exactly once."""
    result_path = result_path.resolve()
    working_directory = working_directory.resolve()
    if result_path.exists():
        raise FileExistsError(
            f"refusing to overwrite runtime preflight report: {result_path}"
        )
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if not kernel_name.strip():
        raise ValueError("kernel_name must be nonempty")
    if not working_directory.is_dir():
        raise ValueError(
            f"working_directory must be an existing directory: {working_directory}"
        )

    started_at = clock()
    active_probe = probe or _probe_runtime
    observation = active_probe(
        kernel_name=kernel_name,
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
    )
    completed_at = clock()
    marker_verified = observation.marker_observed == _MARKER
    working_directory_verified = False
    if observation.observed_working_directory is not None:
        working_directory_verified = (
            Path(observation.observed_working_directory).resolve()
            == working_directory
        )
    passed = (
        not observation.findings
        and observation.kernel_spec_found
        and observation.kernel_started
        and observation.kernel_ready
        and observation.smoke_cell_executed
        and marker_verified
        and working_directory_verified
        and observation.kernel_shutdown
    )
    report = RuntimePreflightReport(
        schema_version=1,
        probe_id=_PROBE_ID,
        status="passed" if passed else "failed",
        started_at=started_at,
        completed_at=completed_at,
        interpreter_path=str(Path(sys.executable).resolve()),
        python_version=platform.python_version(),
        kernel_name=kernel_name,
        timeout_seconds=timeout_seconds,
        working_directory=str(working_directory),
        required_distributions=["jupyter-client", "nbclient", "nbformat"],
        dependency_versions=observation.dependency_versions,
        kernel_spec_found=observation.kernel_spec_found,
        kernel_started=observation.kernel_started,
        kernel_ready=observation.kernel_ready,
        smoke_cell_executed=observation.smoke_cell_executed,
        marker_verified=marker_verified,
        working_directory_verified=working_directory_verified,
        kernel_shutdown=observation.kernel_shutdown,
        smoke_code_sha256=_SMOKE_CODE_SHA256,
        analysis_source_loaded=False,
        analysis_code_executed=False,
        network_access_requested=False,
        findings=observation.findings,
        conclusion_ceiling=_CONCLUSION_CEILING,
    )
    _atomic_write(
        result_path,
        (json.dumps(asdict(report), indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Start a Jupyter kernel and run one fixed generated marker cell "
            "without reading or executing an analysis notebook."
        )
    )
    parser.add_argument("--result-json", required=True, type=Path)
    parser.add_argument("--working-directory", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--kernel-name", default="python3")
    return parser


def _input_error_payload(
    error: BaseException, *, kernel_name: str, timeout_seconds: int
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "probe_id": _PROBE_ID,
        "status": "preflight_input_error",
        "code": "RUNTIME_PREFLIGHT_INPUT_INVALID",
        "kernel_name": kernel_name,
        "timeout_seconds": timeout_seconds,
        "kernel_started": False,
        "analysis_source_loaded": False,
        "analysis_code_executed": False,
        "network_access_requested": False,
        "error_type": type(error).__name__,
        "error": str(error),
        "conclusion_ceiling": _CONCLUSION_CEILING,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result_path = args.result_json.resolve()
    if result_path.exists():
        payload = _input_error_payload(
            FileExistsError(
                f"refusing to overwrite runtime preflight report: {result_path}"
            ),
            kernel_name=args.kernel_name,
            timeout_seconds=args.timeout,
        )
        payload["code"] = "REPORT_ALREADY_EXISTS"
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2

    try:
        report = preflight_notebook_runtime(
            result_path,
            working_directory=args.working_directory,
            timeout_seconds=args.timeout,
            kernel_name=args.kernel_name,
        )
        payload: dict[str, Any] = asdict(report)
        exit_code = 0 if report.status == "passed" else 1
    except (OSError, RuntimeError, ValueError) as exc:
        payload = _input_error_payload(
            exc,
            kernel_name=args.kernel_name,
            timeout_seconds=args.timeout,
        )
        try:
            _atomic_write(
                result_path,
                (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(
                    "utf-8"
                ),
            )
        except OSError as write_error:
            payload["code"] = "RUNTIME_PREFLIGHT_IO_ERROR"
            payload["receipt_written"] = False
            payload["receipt_error"] = str(write_error)
        exit_code = 2

    print(json.dumps(payload, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
