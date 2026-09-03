"""Statically validate notebook dependencies without starting a kernel."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class NotebookPreflightInputError(ValueError):
    """Raised when the source or manifest cannot be interpreted safely."""


@dataclass(frozen=True)
class DependencyObservation:
    locator: str
    expected_sha256: str
    observed_sha256: str | None
    resolved_path: str
    status: str


@dataclass(frozen=True)
class NotebookPreflightReport:
    status: str
    source_path: str
    source_sha256: str
    manifest_path: str
    manifest_sha256: str
    workspace_root: str
    hash_variable: str
    dependency_count: int
    source_clean: bool
    manifest_matches_notebook: bool
    files_match_manifest: bool
    kernel_started: bool
    findings: list[dict[str, Any]]
    dependencies: list[DependencyObservation]


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _validate_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise NotebookPreflightInputError(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return value


def _load_json_object(content: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NotebookPreflightInputError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise NotebookPreflightInputError(f"{label} must be a JSON object")
    return value


def _load_manifest(content: bytes) -> dict[str, str]:
    manifest = _load_json_object(content, label="dependency manifest")
    unexpected = set(manifest) - {"schema_version", "dependencies"}
    if unexpected:
        raise NotebookPreflightInputError(
            "dependency manifest has unexpected fields: "
            + ", ".join(sorted(unexpected))
        )
    if manifest.get("schema_version") != 1:
        raise NotebookPreflightInputError(
            "dependency manifest schema_version must be 1"
        )
    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise NotebookPreflightInputError(
            "dependency manifest dependencies must be a nonempty array"
        )

    result: dict[str, str] = {}
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict):
            raise NotebookPreflightInputError(
                f"dependency {index} must be a JSON object"
            )
        unexpected_dependency = set(dependency) - {"locator", "sha256"}
        missing_dependency = {"locator", "sha256"} - set(dependency)
        if unexpected_dependency or missing_dependency:
            details = []
            if missing_dependency:
                details.append("missing " + ", ".join(sorted(missing_dependency)))
            if unexpected_dependency:
                details.append(
                    "unexpected " + ", ".join(sorted(unexpected_dependency))
                )
            raise NotebookPreflightInputError(
                f"dependency {index} has invalid fields: {'; '.join(details)}"
            )
        locator = dependency["locator"]
        if not isinstance(locator, str) or not locator.strip():
            raise NotebookPreflightInputError(
                f"dependency {index} locator must be a nonempty string"
            )
        if Path(locator).is_absolute():
            raise NotebookPreflightInputError(
                f"dependency {index} locator must be relative: {locator}"
            )
        if locator in result:
            raise NotebookPreflightInputError(
                f"duplicate dependency locator: {locator}"
            )
        result[locator] = _validate_sha256(
            dependency["sha256"], label=f"dependency {index} sha256"
        )
    return result


def _cell_source(cell: dict[str, Any], *, index: int) -> str:
    source = cell.get("source", "")
    if isinstance(source, str):
        return source
    if isinstance(source, list) and all(isinstance(line, str) for line in source):
        return "".join(source)
    raise NotebookPreflightInputError(
        f"notebook code cell {index} source must be a string or string array"
    )


def _source_is_clean(notebook: dict[str, Any]) -> bool:
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise NotebookPreflightInputError("notebook cells must be an array")
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            raise NotebookPreflightInputError(
                f"notebook cell {index} must be an object"
            )
        if cell.get("cell_type") != "code":
            continue
        outputs = cell.get("outputs", [])
        if not isinstance(outputs, list):
            raise NotebookPreflightInputError(
                f"notebook code cell {index} outputs must be an array"
            )
        if cell.get("execution_count") is not None or outputs:
            return False
    return True


def _extract_literal_hashes(
    notebook: dict[str, Any], *, hash_variable: str
) -> dict[str, str]:
    if not hash_variable.isidentifier():
        raise NotebookPreflightInputError(
            f"hash variable is not a Python identifier: {hash_variable}"
        )
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise NotebookPreflightInputError("notebook cells must be an array")

    canonical_values: list[ast.expr] = []
    writes: list[tuple[int, int | None]] = []
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = _cell_source(cell, index=index)
        try:
            module = ast.parse(source, filename=f"notebook-cell-{index}")
        except SyntaxError as exc:
            raise NotebookPreflightInputError(
                f"notebook code cell {index} is not static Python: {exc.msg}"
            ) from exc

        for node in ast.walk(module):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Store)
                and node.id == hash_variable
            ):
                writes.append((index, getattr(node, "lineno", None)))

        for statement in module.body:
            if isinstance(statement, ast.Assign):
                target_names = [
                    target.id
                    for target in statement.targets
                    if isinstance(target, ast.Name)
                ]
                if hash_variable in target_names:
                    if len(statement.targets) != 1:
                        raise NotebookPreflightInputError(
                            f"{hash_variable} must have one assignment target"
                        )
                    canonical_values.append(statement.value)
            elif (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.target.id == hash_variable
            ):
                if statement.value is None:
                    raise NotebookPreflightInputError(
                        f"{hash_variable} annotated assignment has no value"
                    )
                canonical_values.append(statement.value)

    if len(writes) != 1 or len(canonical_values) != 1:
        raise NotebookPreflightInputError(
            f"notebook must contain exactly one top-level literal assignment to "
            f"{hash_variable}; found {len(writes)} writes and "
            f"{len(canonical_values)} top-level assignments"
        )
    value_node = canonical_values[0]
    if not isinstance(value_node, ast.Dict):
        raise NotebookPreflightInputError(f"{hash_variable} must be a literal dict")
    try:
        keys = [ast.literal_eval(key) for key in value_node.keys]
        values = [ast.literal_eval(value) for value in value_node.values]
    except (TypeError, ValueError) as exc:
        raise NotebookPreflightInputError(
            f"{hash_variable} keys and values must be string literals"
        ) from exc
    if not keys:
        raise NotebookPreflightInputError(f"{hash_variable} must not be empty")
    if not all(isinstance(key, str) for key in keys) or not all(
        isinstance(value, str) for value in values
    ):
        raise NotebookPreflightInputError(
            f"{hash_variable} keys and values must be string literals"
        )
    if len(set(keys)) != len(keys):
        raise NotebookPreflightInputError(
            f"{hash_variable} contains duplicate dependency locators"
        )

    result: dict[str, str] = {}
    for index, (locator, value) in enumerate(zip(keys, values, strict=True)):
        if Path(locator).is_absolute():
            raise NotebookPreflightInputError(
                f"{hash_variable} locator must be relative: {locator}"
            )
        result[locator] = _validate_sha256(
            value, label=f"{hash_variable} value {index}"
        )
    return result


def _finding(code: str, message: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "message": message}
    if details:
        result["details"] = details
    return result


def preflight_notebook_dependencies(
    source_path: Path,
    manifest_path: Path,
    *,
    workspace_root: Path,
    hash_variable: str = "EXPECTED_HASHES",
    expected_source_sha256: str | None = None,
    expected_manifest_sha256: str | None = None,
) -> NotebookPreflightReport:
    """Compare a manifest, a literal notebook mapping, and actual file bytes."""

    source_path = source_path.resolve()
    manifest_path = manifest_path.resolve()
    workspace_root = workspace_root.resolve()
    source_bytes = source_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    source_sha256 = _sha256_bytes(source_bytes)
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    manifest_hashes = _load_manifest(manifest_bytes)
    notebook = _load_json_object(source_bytes, label="notebook source")
    source_clean = _source_is_clean(notebook)
    embedded_hashes = _extract_literal_hashes(
        notebook, hash_variable=hash_variable
    )

    findings: list[dict[str, Any]] = []
    if expected_source_sha256 is not None:
        expected_source_sha256 = _validate_sha256(
            expected_source_sha256.lower(), label="expected source sha256"
        )
        if source_sha256 != expected_source_sha256:
            findings.append(
                _finding(
                    "SOURCE_HASH_MISMATCH",
                    "notebook source bytes do not match the expected hash",
                    expected_sha256=expected_source_sha256,
                    observed_sha256=source_sha256,
                )
            )
    if expected_manifest_sha256 is not None:
        expected_manifest_sha256 = _validate_sha256(
            expected_manifest_sha256.lower(), label="expected manifest sha256"
        )
        if manifest_sha256 != expected_manifest_sha256:
            findings.append(
                _finding(
                    "MANIFEST_HASH_MISMATCH",
                    "dependency manifest bytes do not match the expected hash",
                    expected_sha256=expected_manifest_sha256,
                    observed_sha256=manifest_sha256,
                )
            )
    if not source_clean:
        findings.append(
            _finding(
                "SOURCE_NOTEBOOK_NOT_CLEAN",
                "source notebook contains an execution count or output",
            )
        )

    manifest_locators = set(manifest_hashes)
    embedded_locators = set(embedded_hashes)
    for locator in sorted(manifest_locators - embedded_locators):
        findings.append(
            _finding(
                "DEPENDENCY_MISSING_FROM_NOTEBOOK",
                "manifest dependency is absent from the notebook hash mapping",
                locator=locator,
                manifest_sha256=manifest_hashes[locator],
            )
        )
    for locator in sorted(embedded_locators - manifest_locators):
        findings.append(
            _finding(
                "UNDECLARED_NOTEBOOK_DEPENDENCY",
                "notebook hash mapping contains a dependency absent from the manifest",
                locator=locator,
                notebook_sha256=embedded_hashes[locator],
            )
        )
    for locator in sorted(manifest_locators & embedded_locators):
        if manifest_hashes[locator] != embedded_hashes[locator]:
            findings.append(
                _finding(
                    "EMBEDDED_HASH_MISMATCH",
                    "notebook hash literal differs from the dependency manifest",
                    locator=locator,
                    manifest_sha256=manifest_hashes[locator],
                    notebook_sha256=embedded_hashes[locator],
                )
            )

    observations: list[DependencyObservation] = []
    resolved_locators: dict[Path, str] = {}
    for locator, expected_sha256 in manifest_hashes.items():
        resolved_path = (workspace_root / locator).resolve()
        prior_locator = resolved_locators.get(resolved_path)
        if prior_locator is not None:
            findings.append(
                _finding(
                    "DEPENDENCY_PATH_ALIAS",
                    "two dependency locators resolve to the same path",
                    first_locator=prior_locator,
                    second_locator=locator,
                    resolved_path=str(resolved_path),
                )
            )
        else:
            resolved_locators[resolved_path] = locator
        if not resolved_path.exists():
            status = "missing"
            observed_sha256 = None
            findings.append(
                _finding(
                    "DEPENDENCY_MISSING",
                    "declared dependency does not exist",
                    locator=locator,
                    resolved_path=str(resolved_path),
                )
            )
        elif not resolved_path.is_file():
            status = "not_file"
            observed_sha256 = None
            findings.append(
                _finding(
                    "DEPENDENCY_NOT_FILE",
                    "declared dependency is not a regular file",
                    locator=locator,
                    resolved_path=str(resolved_path),
                )
            )
        else:
            observed_sha256 = _sha256_file(resolved_path)
            if observed_sha256 == expected_sha256:
                status = "passed"
            else:
                status = "hash_mismatch"
                findings.append(
                    _finding(
                        "DEPENDENCY_HASH_MISMATCH",
                        "dependency bytes do not match the manifest hash",
                        locator=locator,
                        resolved_path=str(resolved_path),
                        expected_sha256=expected_sha256,
                        observed_sha256=observed_sha256,
                    )
                )
        observations.append(
            DependencyObservation(
                locator=locator,
                expected_sha256=expected_sha256,
                observed_sha256=observed_sha256,
                resolved_path=str(resolved_path),
                status=status,
            )
        )

    manifest_matches_notebook = manifest_hashes == embedded_hashes
    files_match_manifest = all(item.status == "passed" for item in observations)
    return NotebookPreflightReport(
        status="passed" if not findings else "failed",
        source_path=str(source_path),
        source_sha256=source_sha256,
        manifest_path=str(manifest_path),
        manifest_sha256=manifest_sha256,
        workspace_root=str(workspace_root),
        hash_variable=hash_variable,
        dependency_count=len(manifest_hashes),
        source_clean=source_clean,
        manifest_matches_notebook=manifest_matches_notebook,
        files_match_manifest=files_match_manifest,
        kernel_started=False,
        findings=findings,
        dependencies=observations,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Statically compare a notebook dependency manifest, a literal hash "
            "mapping in the source notebook, and actual file bytes."
        )
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--hash-variable", default="EXPECTED_HASHES")
    parser.add_argument("--expect-source-sha256")
    parser.add_argument("--expect-manifest-sha256")
    parser.add_argument("--result-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result_path = args.result_json.resolve() if args.result_json is not None else None
    if result_path is not None and result_path.exists():
        print(
            json.dumps(
                {
                    "status": "preflight_input_error",
                    "code": "REPORT_ALREADY_EXISTS",
                    "kernel_started": False,
                    "error": f"refusing to overwrite preflight report: {result_path}",
                }
            )
        )
        return 2

    exit_code: int
    try:
        report = preflight_notebook_dependencies(
            args.source,
            args.manifest,
            workspace_root=args.workspace_root,
            hash_variable=args.hash_variable,
            expected_source_sha256=args.expect_source_sha256,
            expected_manifest_sha256=args.expect_manifest_sha256,
        )
        payload: dict[str, Any] = asdict(report)
        exit_code = 0 if report.status == "passed" else 1
    except FileNotFoundError as exc:
        payload = {
            "status": "preflight_input_error",
            "code": "INPUT_FILE_MISSING",
            "kernel_started": False,
            "error": str(exc),
        }
        exit_code = 2
    except NotebookPreflightInputError as exc:
        payload = {
            "status": "preflight_input_error",
            "code": "PREFLIGHT_INPUT_INVALID",
            "kernel_started": False,
            "error": str(exc),
        }
        exit_code = 2
    except OSError as exc:
        payload = {
            "status": "preflight_input_error",
            "code": "PREFLIGHT_IO_ERROR",
            "kernel_started": False,
            "error": str(exc),
        }
        exit_code = 2

    output = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if result_path is not None:
        try:
            _atomic_write(result_path, output)
        except OSError as exc:
            write_error = {
                "status": "preflight_input_error",
                "code": "PREFLIGHT_IO_ERROR",
                "kernel_started": False,
                "error": str(exc),
            }
            print(json.dumps(write_error))
            return 2
    print(output.decode("utf-8"), end="")
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
