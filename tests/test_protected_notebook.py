import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from research_machine.executors.protected_notebook import (
    execute_protected_notebook,
    main,
)


class FakeRuntime:
    def __init__(self, executed_notebook, error=None):
        self.executed_notebook = executed_notebook
        self.error = error
        self.execute_calls = 0

    def read(self, path: Path):
        return json.loads(path.read_text())

    def execute(self, notebook, **kwargs):
        self.execute_calls += 1
        notebook.clear()
        notebook.update(deepcopy(self.executed_notebook))
        if self.error is not None:
            raise self.error

    def serialize(self, notebook):
        return json.dumps(notebook, sort_keys=True)


def source_notebook():
    return {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "id": "first",
                "metadata": {},
                "outputs": [],
                "source": ["print('first')"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "id": "second",
                "metadata": {},
                "outputs": [],
                "source": ["raise RuntimeError('boom')"],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def failed_notebook():
    notebook = source_notebook()
    notebook["cells"][0]["execution_count"] = 1
    notebook["cells"][0]["outputs"] = [
        {"output_type": "stream", "name": "stdout", "text": ["first\n"]}
    ]
    notebook["cells"][1]["execution_count"] = 2
    notebook["cells"][1]["outputs"] = [
        {
            "output_type": "error",
            "ename": "RuntimeError",
            "evalue": "boom",
            "traceback": ["RuntimeError: boom"],
        }
    ]
    return notebook


def test_failure_atomically_preserves_partial_notebook_and_receipt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.ipynb"
    output = tmp_path / "executed.ipynb"
    result = tmp_path / "receipt.json"
    source.write_text(json.dumps(source_notebook()))
    source_bytes = source.read_bytes()
    times = iter(["2026-09-03T01:00:00Z", "2026-09-03T01:00:01Z"])
    runtime = FakeRuntime(failed_notebook(), RuntimeError("boom"))

    receipt = execute_protected_notebook(
        source,
        output,
        result_path=result,
        expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        runtime=runtime,
        clock=lambda: next(times),
    )

    assert source.read_bytes() == source_bytes
    assert receipt.status == "failed"
    assert receipt.code_cells_started == 2
    assert receipt.code_cells_completed == 1
    assert receipt.error_cell_id == "second"
    assert receipt.error_type == "RuntimeError"
    assert receipt.output_sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    preserved = json.loads(output.read_text())
    assert preserved["cells"][0]["outputs"][0]["text"] == ["first\n"]
    assert preserved["cells"][1]["outputs"][0]["evalue"] == "boom"
    assert preserved["metadata"]["research_machine_execution"]["status"] == "failed"
    assert json.loads(result.read_text())["output_sha256"] == receipt.output_sha256


def test_success_is_preserved_with_completed_receipt(tmp_path: Path) -> None:
    source = tmp_path / "source.ipynb"
    output = tmp_path / "executed.ipynb"
    result = tmp_path / "receipt.json"
    completed = source_notebook()
    completed["cells"] = completed["cells"][:1]
    completed["cells"][0]["execution_count"] = 1
    completed["cells"][0]["outputs"] = [
        {"output_type": "stream", "name": "stdout", "text": ["first\n"]}
    ]
    source.write_text(json.dumps({**source_notebook(), "cells": source_notebook()["cells"][:1]}))
    runtime = FakeRuntime(completed)

    receipt = execute_protected_notebook(
        source,
        output,
        result_path=result,
        runtime=runtime,
        clock=lambda: "2026-09-03T01:00:00Z",
    )

    assert receipt.status == "completed"
    assert receipt.code_cells_started == 1
    assert receipt.code_cells_completed == 1
    assert receipt.error_cell_id is None
    assert output.exists()
    assert result.exists()


def test_hash_mismatch_rejects_before_runtime_or_output(tmp_path: Path) -> None:
    source = tmp_path / "source.ipynb"
    output = tmp_path / "executed.ipynb"
    source.write_text(json.dumps(source_notebook()))
    runtime = FakeRuntime(failed_notebook(), RuntimeError("must not run"))

    with pytest.raises(ValueError, match="source hash mismatch"):
        execute_protected_notebook(
            source,
            output,
            expected_source_sha256="0" * 64,
            runtime=runtime,
        )

    assert runtime.execute_calls == 0
    assert not output.exists()


def test_dependency_preflight_rejects_before_runtime_or_output(
    tmp_path: Path,
) -> None:
    dependency = tmp_path / "input.bin"
    dependency.write_bytes(b"registered")
    expected_dependency_hash = hashlib.sha256(dependency.read_bytes()).hexdigest()
    source = tmp_path / "source.ipynb"
    output = tmp_path / "executed.ipynb"
    manifest = tmp_path / "dependencies.json"
    notebook = source_notebook()
    notebook["cells"][0]["source"] = [
        f"EXPECTED_HASHES = {{'input.bin': {'0' * 64!r}}}\n"
    ]
    source.write_text(json.dumps(notebook))
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dependencies": [
                    {
                        "locator": "input.bin",
                        "sha256": expected_dependency_hash,
                    }
                ],
            }
        )
    )
    runtime = FakeRuntime(failed_notebook(), RuntimeError("must not run"))

    with pytest.raises(ValueError, match="EMBEDDED_HASH_MISMATCH"):
        execute_protected_notebook(
            source,
            output,
            dependency_manifest_path=manifest,
            working_directory=tmp_path,
            runtime=runtime,
        )

    assert runtime.execute_calls == 0
    assert not output.exists()


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "source.ipynb"
    output = tmp_path / "executed.ipynb"
    source.write_text(json.dumps(source_notebook()))
    output.write_text("immutable")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        execute_protected_notebook(
            source,
            output,
            runtime=FakeRuntime(failed_notebook()),
        )

    assert output.read_text() == "immutable"


def test_cli_pre_execution_runtime_failure_writes_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.ipynb"
    output = tmp_path / "executed.ipynb"
    result = tmp_path / "receipt.json"
    source.write_text(json.dumps(source_notebook()))

    def missing_runtime():
        raise RuntimeError("notebook runtime deliberately unavailable")

    monkeypatch.setattr(
        "research_machine.executors.protected_notebook._load_default_runtime",
        missing_runtime,
    )

    exit_code = main(
        [str(source), str(output), "--result-json", str(result)]
    )

    assert exit_code == 2
    assert not output.exists()
    report = json.loads(result.read_text())
    assert report["status"] == "pre_execution_failure"
    assert report["error_type"] == "RuntimeError"
    assert report["kernel_started"] is False
    assert report["code_cells_started"] == 0
    assert report["receipt_written"] is True
    assert report["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_cli_pre_execution_failure_never_overwrites_existing_receipt(
    tmp_path: Path,
) -> None:
    missing_source = tmp_path / "missing.ipynb"
    output = tmp_path / "executed.ipynb"
    result = tmp_path / "receipt.json"
    result.write_text("immutable")

    exit_code = main(
        [str(missing_source), str(output), "--result-json", str(result)]
    )

    assert exit_code == 2
    assert result.read_text() == "immutable"
    assert not output.exists()


def test_real_nbclient_preserves_error_output_when_explicitly_enabled(
    tmp_path: Path,
) -> None:
    if os.environ.get("RESEARCH_MACHINE_NOTEBOOK_INTEGRATION") != "1":
        pytest.skip("set RESEARCH_MACHINE_NOTEBOOK_INTEGRATION=1 for kernel test")
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbclient")
    source = tmp_path / "source.ipynb"
    output = tmp_path / "executed.ipynb"
    result = tmp_path / "receipt.json"
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell("value = 41; print(value)"),
            nbformat.v4.new_code_cell("raise RuntimeError('preserved failure')"),
        ]
    )
    nbformat.write(notebook, source)

    receipt = execute_protected_notebook(
        source,
        output,
        result_path=result,
        working_directory=tmp_path,
        timeout_seconds=60,
    )

    assert receipt.status == "failed"
    assert receipt.code_cells_started == 2
    assert receipt.code_cells_completed == 1
    preserved = nbformat.read(output, as_version=4)
    assert preserved.cells[0].outputs[0]["text"] == "41\n"
    assert preserved.cells[1].outputs[0]["output_type"] == "error"
    assert preserved.cells[1].outputs[0]["evalue"] == "preserved failure"
    assert json.loads(result.read_text())["status"] == "failed"
