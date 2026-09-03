"""Execute a frozen notebook while preserving partial output on failure.

This module is an optional executor adapter.  It deliberately does not enter
the application service or canonical-state dependency graph: it produces a
hashed notebook and a receipt that can later be included in a run record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from research_machine.executors.notebook_preflight import (
    preflight_notebook_dependencies,
)


class NotebookRuntime(Protocol):
    """Minimal execution surface, injectable for dependency-free tests."""

    def read(self, path: Path) -> Any: ...

    def execute(
        self,
        notebook: Any,
        *,
        working_directory: Path,
        timeout_seconds: int,
        kernel_name: str,
    ) -> None: ...

    def serialize(self, notebook: Any) -> str: ...


@dataclass(frozen=True)
class ExecutionReceipt:
    status: str
    source_path: str
    source_sha256: str
    output_path: str | None
    output_sha256: str | None
    started_at: str
    completed_at: str
    code_cells_started: int
    code_cells_completed: int
    error_cell_id: str | None
    error_type: str | None
    error_message: str | None
    kernel_name: str
    timeout_seconds: int
    working_directory: str


@dataclass(frozen=True)
class _DefaultRuntime:
    nbformat: Any
    notebook_client: Any

    def read(self, path: Path) -> Any:
        return self.nbformat.read(path, as_version=4)

    def execute(
        self,
        notebook: Any,
        *,
        working_directory: Path,
        timeout_seconds: int,
        kernel_name: str,
    ) -> None:
        client = self.notebook_client(
            notebook,
            timeout=timeout_seconds,
            kernel_name=kernel_name,
            allow_errors=False,
            resources={"metadata": {"path": str(working_directory)}},
        )
        client.execute()

    def serialize(self, notebook: Any) -> str:
        return self.nbformat.writes(notebook, version=4)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


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


def _notebook_counts(notebook: Any) -> tuple[int, int, str | None]:
    started = 0
    completed = 0
    error_cell_id: str | None = None
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code" or cell.get("execution_count") is None:
            continue
        started += 1
        has_error = any(
            output.get("output_type") == "error" for output in cell.get("outputs", [])
        )
        if has_error:
            if error_cell_id is None:
                error_cell_id = cell.get("id")
        else:
            completed += 1
    return started, completed, error_cell_id


def _load_default_runtime() -> NotebookRuntime:
    try:
        import nbformat
        from nbclient import NotebookClient
    except ImportError as exc:  # pragma: no cover - depends on optional environment
        raise RuntimeError(
            "protected notebook execution requires the 'notebook' extra: "
            "pip install 'research-machine[notebook]'"
        ) from exc
    return _DefaultRuntime(nbformat=nbformat, notebook_client=NotebookClient)


def execute_protected_notebook(
    source_path: Path,
    output_path: Path,
    *,
    result_path: Path | None = None,
    expected_source_sha256: str | None = None,
    dependency_manifest_path: Path | None = None,
    expected_dependency_manifest_sha256: str | None = None,
    dependency_hash_variable: str = "EXPECTED_HASHES",
    working_directory: Path | None = None,
    timeout_seconds: int = 600,
    kernel_name: str = "python3",
    runtime: NotebookRuntime | None = None,
    clock: Callable[[], str] = _utc_now,
) -> ExecutionReceipt:
    """Execute once and atomically preserve the notebook even when a cell fails.

    Existing outputs are rejected to keep a protected execution from silently
    overwriting an earlier result. Source-hash and optional static dependency-
    manifest mismatches are rejected before kernel execution and therefore
    produce no executed-notebook artifact.
    """

    source_path = source_path.resolve()
    output_path = output_path.resolve()
    result_path = result_path.resolve() if result_path is not None else None
    dependency_manifest_path = (
        dependency_manifest_path.resolve()
        if dependency_manifest_path is not None
        else None
    )
    working_directory = (
        working_directory.resolve()
        if working_directory is not None
        else source_path.parent
    )

    if source_path == output_path:
        raise ValueError("source and output paths must differ")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite output: {output_path}")
    if result_path is not None and result_path.exists():
        raise FileExistsError(f"refusing to overwrite receipt: {result_path}")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if (
        expected_dependency_manifest_sha256 is not None
        and dependency_manifest_path is None
    ):
        raise ValueError(
            "expected dependency manifest hash requires a dependency manifest"
        )

    source_bytes = source_path.read_bytes()
    source_sha256 = _sha256_bytes(source_bytes)
    if (
        expected_source_sha256 is not None
        and source_sha256 != expected_source_sha256.lower()
    ):
        raise ValueError(
            "source hash mismatch: "
            f"expected {expected_source_sha256.lower()}, observed {source_sha256}"
        )

    if dependency_manifest_path is not None:
        preflight = preflight_notebook_dependencies(
            source_path,
            dependency_manifest_path,
            workspace_root=working_directory,
            hash_variable=dependency_hash_variable,
            expected_source_sha256=expected_source_sha256,
            expected_manifest_sha256=expected_dependency_manifest_sha256,
        )
        if preflight.status != "passed":
            codes = ", ".join(
                str(finding["code"]) for finding in preflight.findings
            )
            raise ValueError(f"dependency preflight failed: {codes}")

    active_runtime = runtime or _load_default_runtime()
    notebook = active_runtime.read(source_path)
    started_at = clock()
    error: BaseException | None = None
    try:
        active_runtime.execute(
            notebook,
            working_directory=working_directory,
            timeout_seconds=timeout_seconds,
            kernel_name=kernel_name,
        )
    except BaseException as exc:  # preserve KeyboardInterrupt and cell failures too
        error = exc
    completed_at = clock()

    code_cells_started, code_cells_completed, error_cell_id = _notebook_counts(
        notebook
    )
    execution_metadata = {
        "status": "failed" if error is not None else "completed",
        "source_sha256": source_sha256,
        "started_at": started_at,
        "completed_at": completed_at,
        "code_cells_started": code_cells_started,
        "code_cells_completed": code_cells_completed,
        "error_cell_id": error_cell_id,
        "error_type": type(error).__name__ if error is not None else None,
        "error_message": str(error) if error is not None else None,
        "kernel_name": kernel_name,
        "timeout_seconds": timeout_seconds,
        "working_directory": str(working_directory),
    }
    notebook.setdefault("metadata", {})[
        "research_machine_execution"
    ] = execution_metadata

    output_bytes = active_runtime.serialize(notebook).encode("utf-8")
    _atomic_write(output_path, output_bytes)
    output_sha256 = _sha256_bytes(output_bytes)
    receipt = ExecutionReceipt(
        status=execution_metadata["status"],
        source_path=str(source_path),
        source_sha256=source_sha256,
        output_path=str(output_path),
        output_sha256=output_sha256,
        started_at=started_at,
        completed_at=completed_at,
        code_cells_started=code_cells_started,
        code_cells_completed=code_cells_completed,
        error_cell_id=error_cell_id,
        error_type=execution_metadata["error_type"],
        error_message=execution_metadata["error_message"],
        kernel_name=kernel_name,
        timeout_seconds=timeout_seconds,
        working_directory=str(working_directory),
    )
    if result_path is not None:
        _atomic_write(
            result_path,
            (json.dumps(asdict(receipt), indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute a frozen Jupyter notebook once and preserve partial output "
            "atomically when a cell fails."
        )
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--result-json", required=True, type=Path)
    parser.add_argument("--expect-source-sha256")
    parser.add_argument("--dependency-manifest", type=Path)
    parser.add_argument("--expect-dependency-manifest-sha256")
    parser.add_argument("--dependency-hash-variable", default="EXPECTED_HASHES")
    parser.add_argument("--working-directory", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--kernel-name", default="python3")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = execute_protected_notebook(
            args.source,
            args.output,
            result_path=args.result_json,
            expected_source_sha256=args.expect_source_sha256,
            dependency_manifest_path=args.dependency_manifest,
            expected_dependency_manifest_sha256=(
                args.expect_dependency_manifest_sha256
            ),
            dependency_hash_variable=args.dependency_hash_variable,
            working_directory=args.working_directory,
            timeout_seconds=args.timeout,
            kernel_name=args.kernel_name,
        )
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "pre_execution_failure", "error": str(exc)}))
        return 2
    print(json.dumps(asdict(receipt), indent=2, sort_keys=True))
    return 0 if receipt.status == "completed" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
