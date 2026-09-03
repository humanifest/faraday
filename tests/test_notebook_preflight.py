import hashlib
import json
from pathlib import Path

import pytest

from research_machine.executors.notebook_preflight import (
    NotebookPreflightInputError,
    main,
    preflight_notebook_dependencies,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_notebook(
    path: Path,
    hashes: dict[str, str],
    *,
    execution_count: int | None = None,
    outputs: list[dict[str, object]] | None = None,
    assignment: str | None = None,
) -> None:
    mapping = assignment or f"EXPECTED_HASHES = {hashes!r}\n"
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": execution_count,
                "id": "dependency-preflight",
                "metadata": {},
                "outputs": outputs or [],
                "source": [mapping],
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(notebook))


def _write_manifest(path: Path, hashes: dict[str, str]) -> None:
    manifest = {
        "schema_version": 1,
        "dependencies": [
            {"locator": locator, "sha256": sha256}
            for locator, sha256 in hashes.items()
        ],
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def test_three_way_preflight_passes_without_kernel(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dependency = workspace / "input.bin"
    dependency.write_bytes(b"fixed input")
    external = tmp_path / "external.bin"
    external.write_bytes(b"fixed sibling input")
    hashes = {
        "input.bin": _sha256(dependency),
        "../external.bin": _sha256(external),
    }
    source = workspace / "source.ipynb"
    manifest = workspace / "dependencies.json"
    _write_notebook(source, hashes)
    _write_manifest(manifest, hashes)

    report = preflight_notebook_dependencies(
        source,
        manifest,
        workspace_root=workspace,
        expected_source_sha256=_sha256(source),
        expected_manifest_sha256=_sha256(manifest),
    )

    assert report.status == "passed"
    assert report.dependency_count == 2
    assert report.source_clean
    assert report.manifest_matches_notebook
    assert report.files_match_manifest
    assert not report.kernel_started
    assert report.findings == []
    assert {item.status for item in report.dependencies} == {"passed"}


def test_notebook_literal_typo_is_reported_even_when_files_match_manifest(
    tmp_path: Path,
) -> None:
    dependency = tmp_path / "input.bin"
    dependency.write_bytes(b"fixed input")
    hashes = {"input.bin": _sha256(dependency)}
    source = tmp_path / "source.ipynb"
    manifest = tmp_path / "dependencies.json"
    _write_notebook(source, {"input.bin": "0" * 64})
    _write_manifest(manifest, hashes)

    report = preflight_notebook_dependencies(
        source, manifest, workspace_root=tmp_path
    )

    assert report.status == "failed"
    assert not report.manifest_matches_notebook
    assert report.files_match_manifest
    assert [finding["code"] for finding in report.findings] == [
        "EMBEDDED_HASH_MISMATCH"
    ]
    details = report.findings[0]["details"]
    assert details["manifest_sha256"] == hashes["input.bin"]
    assert details["notebook_sha256"] == "0" * 64


def test_dependency_drift_is_reported_when_manifest_and_notebook_agree(
    tmp_path: Path,
) -> None:
    dependency = tmp_path / "input.bin"
    dependency.write_bytes(b"registered")
    hashes = {"input.bin": _sha256(dependency)}
    source = tmp_path / "source.ipynb"
    manifest = tmp_path / "dependencies.json"
    _write_notebook(source, hashes)
    _write_manifest(manifest, hashes)
    dependency.write_bytes(b"changed")

    report = preflight_notebook_dependencies(
        source, manifest, workspace_root=tmp_path
    )

    assert report.status == "failed"
    assert report.manifest_matches_notebook
    assert not report.files_match_manifest
    assert [finding["code"] for finding in report.findings] == [
        "DEPENDENCY_HASH_MISMATCH"
    ]
    assert report.dependencies[0].status == "hash_mismatch"


def test_dirty_source_notebook_fails_closed(tmp_path: Path) -> None:
    dependency = tmp_path / "input.bin"
    dependency.write_bytes(b"fixed")
    hashes = {"input.bin": _sha256(dependency)}
    source = tmp_path / "source.ipynb"
    manifest = tmp_path / "dependencies.json"
    _write_notebook(
        source,
        hashes,
        execution_count=1,
        outputs=[{"output_type": "stream", "name": "stdout", "text": ["old\n"]}],
    )
    _write_manifest(manifest, hashes)

    report = preflight_notebook_dependencies(
        source, manifest, workspace_root=tmp_path
    )

    assert report.status == "failed"
    assert not report.source_clean
    assert report.findings[0]["code"] == "SOURCE_NOTEBOOK_NOT_CLEAN"


@pytest.mark.parametrize(
    "assignment",
    [
        "EXPECTED_HASHES = make_hashes()\n",
        "if True:\n    EXPECTED_HASHES = {'input.bin': '0' * 64}\n",
        "EXPECTED_HASHES = {'input.bin': '0' * 64}\nEXPECTED_HASHES = {}\n",
    ],
)
def test_dynamic_nested_or_reassigned_hash_mapping_is_rejected(
    tmp_path: Path, assignment: str
) -> None:
    dependency = tmp_path / "input.bin"
    dependency.write_bytes(b"fixed")
    hashes = {"input.bin": _sha256(dependency)}
    source = tmp_path / "source.ipynb"
    manifest = tmp_path / "dependencies.json"
    _write_notebook(source, hashes, assignment=assignment)
    _write_manifest(manifest, hashes)

    with pytest.raises(NotebookPreflightInputError):
        preflight_notebook_dependencies(source, manifest, workspace_root=tmp_path)


def test_duplicate_manifest_locator_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.ipynb"
    manifest = tmp_path / "dependencies.json"
    _write_notebook(source, {"input.bin": "0" * 64})
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dependencies": [
                    {"locator": "input.bin", "sha256": "0" * 64},
                    {"locator": "input.bin", "sha256": "0" * 64},
                ],
            }
        )
    )

    with pytest.raises(NotebookPreflightInputError, match="duplicate"):
        preflight_notebook_dependencies(source, manifest, workspace_root=tmp_path)


def test_two_locators_for_one_resolved_path_fail_closed(tmp_path: Path) -> None:
    dependency = tmp_path / "input.bin"
    dependency.write_bytes(b"fixed")
    digest = _sha256(dependency)
    hashes = {"input.bin": digest, "subdir/../input.bin": digest}
    source = tmp_path / "source.ipynb"
    manifest = tmp_path / "dependencies.json"
    _write_notebook(source, hashes)
    _write_manifest(manifest, hashes)

    report = preflight_notebook_dependencies(
        source, manifest, workspace_root=tmp_path
    )

    assert report.status == "failed"
    assert report.manifest_matches_notebook
    assert report.files_match_manifest
    assert [finding["code"] for finding in report.findings] == [
        "DEPENDENCY_PATH_ALIAS"
    ]


def test_cli_writes_failure_report_and_refuses_to_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dependency = tmp_path / "input.bin"
    dependency.write_bytes(b"fixed")
    hashes = {"input.bin": _sha256(dependency)}
    source = tmp_path / "source.ipynb"
    manifest = tmp_path / "dependencies.json"
    result = tmp_path / "preflight.json"
    _write_notebook(source, {"input.bin": "0" * 64})
    _write_manifest(manifest, hashes)

    exit_code = main(
        [
            str(source),
            "--manifest",
            str(manifest),
            "--workspace-root",
            str(tmp_path),
            "--result-json",
            str(result),
        ]
    )

    assert exit_code == 1
    assert json.loads(result.read_text())["status"] == "failed"
    assert json.loads(capsys.readouterr().out)["kernel_started"] is False
    assert main(
        [
            str(source),
            "--manifest",
            str(manifest),
            "--workspace-root",
            str(tmp_path),
            "--result-json",
            str(result),
        ]
    ) == 2
    second_output = json.loads(capsys.readouterr().out)
    assert second_output["code"] == "REPORT_ALREADY_EXISTS"
    assert second_output["kernel_started"] is False
    assert "refusing to overwrite" in second_output["error"]


def test_cli_preserves_malformed_mapping_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dependency = tmp_path / "input.bin"
    dependency.write_bytes(b"fixed")
    hashes = {"input.bin": _sha256(dependency)}
    source = tmp_path / "source.ipynb"
    manifest = tmp_path / "dependencies.json"
    result = tmp_path / "malformed-preflight.json"
    _write_notebook(
        source,
        hashes,
        assignment="EXPECTED_HASHES = {'input.bin': '0' * 64}\n",
    )
    _write_manifest(manifest, hashes)

    exit_code = main(
        [
            str(source),
            "--manifest",
            str(manifest),
            "--workspace-root",
            str(tmp_path),
            "--result-json",
            str(result),
        ]
    )

    assert exit_code == 2
    persisted = json.loads(result.read_text())
    assert persisted["code"] == "PREFLIGHT_INPUT_INVALID"
    assert persisted["kernel_started"] is False
    assert "string literals" in persisted["error"]
    assert json.loads(capsys.readouterr().out) == persisted
