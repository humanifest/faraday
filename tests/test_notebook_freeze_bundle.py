"""Typed notebook runtime and freeze-input binding regressions."""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import pytest

from research_machine.application.commands import CreateProtocol
from research_machine.application.protocol_integrity import protocol_commitment
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import AnalysisMode, ProtocolKind
from research_machine.executors.notebook_freeze_bundle import (
    create_notebook_freeze_input_bundle,
    verify_notebook_freeze_input_bundle,
)
from research_machine.executors.notebook_preflight import (
    preflight_notebook_dependencies,
)
from research_machine.executors.runtime_preflight import (
    KernelProbeObservation,
    preflight_notebook_runtime,
)
from research_machine.interfaces.cli import main
from test_execution import CODE_HASH, prepared_service


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    return payload["result"]


def _formal_protocol_spec(hypothesis_id: str) -> dict:
    return asdict(CreateProtocol(
        experiment_id="b2lc-shaped-runtime-binding",
        title="B2L-C shaped prospective runtime binding",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis_id],
        primary_outcome="Bounded checker acceptance",
        protocol_kind=ProtocolKind.FORMAL,
        methodology="Replay one frozen source in the registered runtime.",
        inputs_required=[
            "Exact source notebook, dependency manifest, runtime receipt, and freeze-input bundle.",
        ],
        quality_requirements=["runtime-and-input-binding"],
        controls=["Replay the registered malformed input."],
        expected_outputs=["Checker transcript"],
        success_conditions=["The bounded registered check returns its expected value."],
        environment_requirements=["Typed no-analysis runtime receipt"],
        sample_size_or_stopping_rule="One frozen execution without retry.",
        failure_conditions=["Any frozen input or runtime binding differs."],
        safety_constraints=["No physical or human intervention."],
        analysis_code_hash=CODE_HASH,
    ))


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _passed_runtime_receipt(path: Path, working_directory: Path) -> str:
    observation = KernelProbeObservation(
        dependency_versions={
            "jupyter-client": "8.6.3",
            "nbclient": "0.10.2",
            "nbformat": "5.10.4",
        },
        kernel_spec_found=True,
        kernel_started=True,
        kernel_ready=True,
        smoke_cell_executed=True,
        marker_observed="RESEARCH_MACHINE_RUNTIME_PREFLIGHT_V1",
        observed_working_directory=str(working_directory),
        kernel_shutdown=True,
        findings=[],
    )
    preflight_notebook_runtime(
        path,
        working_directory=working_directory,
        probe=lambda **_: observation,
        clock=lambda: "2026-09-09T01:00:00Z",
    )
    return _sha256(path)


def _bundle_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, dict[str, str]]:
    dependency = tmp_path / "registered-specification.json"
    dependency.write_text('{"contract":"bounded"}\n')
    dependency_sha256 = _sha256(dependency)
    notebook = tmp_path / "frozen-source.ipynb"
    notebook.write_text(
        json.dumps({
            "cells": [{
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "EXPECTED_HASHES = ",
                    repr({dependency.name: dependency_sha256}),
                    "\n",
                ],
            }],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }, sort_keys=True) + "\n"
    )
    manifest = tmp_path / "notebook-dependencies.json"
    _write_json(manifest, {
        "schema_version": 1,
        "dependencies": [{
            "locator": dependency.name,
            "sha256": dependency_sha256,
        }],
    })
    static_receipt = tmp_path / "static-preflight.json"
    static_report = preflight_notebook_dependencies(
        notebook,
        manifest,
        workspace_root=tmp_path,
    )
    _write_json(static_receipt, asdict(static_report))
    receipt = tmp_path / "runtime-preflight.json"
    receipt_sha256 = _passed_runtime_receipt(receipt, tmp_path)
    receipt_payload = json.loads(receipt.read_text())
    requirement = {
        "receipt_sha256": receipt_sha256,
        "probe_id": receipt_payload["probe_id"],
        "interpreter_path": receipt_payload["interpreter_path"],
        "kernel_name": receipt_payload["kernel_name"],
        "working_directory": receipt_payload["working_directory"],
    }
    return notebook, manifest, static_receipt, receipt, requirement


def test_bundle_replays_every_underlying_input_and_detects_drift(
    tmp_path: Path,
) -> None:
    notebook, manifest, static_receipt, receipt, requirement = _bundle_inputs(tmp_path)
    bundle_path = tmp_path / "freeze-input-bundle.json"
    created = create_notebook_freeze_input_bundle(
        notebook,
        manifest,
        receipt,
        bundle_path,
        workspace_root=tmp_path,
        static_preflight_receipt_path=static_receipt,
    )
    assert created.kernel_started is False
    assert created.analysis_code_executed is False
    assert created.runtime_preflight_requirement == requirement
    assert created.static_preflight_receipt_path == str(static_receipt.resolve())
    assert created.static_preflight_receipt_sha256 == _sha256(static_receipt)
    bundle_sha256 = _sha256(bundle_path)
    assert verify_notebook_freeze_input_bundle(
        bundle_path, expected_sha256=bundle_sha256
    ).status == "passed"

    (tmp_path / "registered-specification.json").write_text("changed\n")
    with pytest.raises(ValueError, match="dependency replay failed"):
        verify_notebook_freeze_input_bundle(
            bundle_path, expected_sha256=bundle_sha256
        )


def test_bundle_tamper_and_failed_creation_fail_closed(tmp_path: Path) -> None:
    notebook, manifest, static_receipt, receipt, _ = _bundle_inputs(tmp_path)
    rejected = tmp_path / "rejected-bundle.json"
    (tmp_path / "registered-specification.json").write_text("drift\n")
    with pytest.raises(ValueError, match="dependency preflight failed"):
        create_notebook_freeze_input_bundle(
            notebook,
            manifest,
            receipt,
            rejected,
            workspace_root=tmp_path,
            static_preflight_receipt_path=static_receipt,
        )
    assert not rejected.exists()

    second = tmp_path / "second"
    second.mkdir()
    notebook, manifest, static_receipt, receipt, _ = _bundle_inputs(second)
    bundle_path = second / "freeze-input-bundle.json"
    create_notebook_freeze_input_bundle(
        notebook,
        manifest,
        receipt,
        bundle_path,
        workspace_root=second,
        static_preflight_receipt_path=static_receipt,
    )
    payload = json.loads(bundle_path.read_text())
    payload["runtime_preflight_requirement"]["unexpected"] = "field"
    _write_json(bundle_path, payload)
    with pytest.raises(ValueError, match="runtime requirement is not canonical"):
        verify_notebook_freeze_input_bundle(bundle_path)


def test_bundle_rejects_retained_static_preflight_receipt_tamper(
    tmp_path: Path,
) -> None:
    notebook, manifest, static_receipt, receipt, _ = _bundle_inputs(tmp_path)
    bundle_path = tmp_path / "freeze-input-bundle.json"
    create_notebook_freeze_input_bundle(
        notebook,
        manifest,
        receipt,
        bundle_path,
        workspace_root=tmp_path,
        static_preflight_receipt_path=static_receipt,
    )
    bundle_sha256 = _sha256(bundle_path)
    payload = json.loads(static_receipt.read_text())
    payload["status"] = "failed"
    _write_json(static_receipt, payload)

    with pytest.raises(ValueError, match="static preflight receipt hash mismatch"):
        verify_notebook_freeze_input_bundle(
            bundle_path,
            expected_sha256=bundle_sha256,
        )


def test_b2lc_shaped_prospective_protocol_binds_receipt_bundle_and_source(
    tmp_path: Path, capsys,
) -> None:
    workspace = tmp_path / "workspace"
    service, hypothesis_id = prepared_service(workspace)
    notebook, manifest, static_receipt, receipt, requirement = _bundle_inputs(tmp_path)
    bundle_path = tmp_path / "freeze-input-bundle.json"
    create_notebook_freeze_input_bundle(
        notebook,
        manifest,
        receipt,
        bundle_path,
        workspace_root=tmp_path,
        static_preflight_receipt_path=static_receipt,
    )
    bundle_sha256 = _sha256(bundle_path)
    spec = _formal_protocol_spec(hypothesis_id)
    spec["runtime_preflight_requirement"] = requirement
    spec["notebook_freeze_input_bundle_sha256"] = bundle_sha256
    spec_path = tmp_path / "protocol.json"
    _write_json(spec_path, spec)
    common = ["--workspace", str(workspace), "--json", "protocol"]
    bundle_args = ["--notebook-freeze-input-bundle", str(bundle_path)]
    ledger = workspace / "inquiries" / "formal" / "ledger.jsonl"
    ledger_before = ledger.read_bytes()

    assert main([*common, "preflight", "--spec-file", str(spec_path)]) == 2
    assert "requires --notebook-freeze-input-bundle" in capsys.readouterr().err
    assert ledger.read_bytes() == ledger_before
    assert main([
        *common, "preflight", "--spec-file", str(spec_path), *bundle_args,
    ]) == 0
    preflight = _result(capsys)
    assert preflight["status"] == "ready"
    assert preflight["would_append_event"] is False
    assert preflight["notebook_freeze_input_bundle_verification"]["status"] == "passed"
    assert preflight["runtime_preflight_verification"]["receipt_sha256"] == requirement["receipt_sha256"]
    assert ledger.read_bytes() == ledger_before

    assert main([*common, "create", "--spec-file", str(spec_path)]) == 0
    protocol_id = _result(capsys)["protocol_id"]
    with pytest.raises(ValidationError, match="requires a freeze-input bundle"):
        service.freeze_protocol(protocol_id)
    assert main([*common, "freeze", protocol_id, *bundle_args]) == 0
    frozen = _result(capsys)
    assert frozen["runtime_preflight_requirement"] == requirement
    assert frozen["notebook_freeze_input_bundle_sha256"] == bundle_sha256
    protocol = service.get_protocol(protocol_id)
    assert protocol_commitment(protocol) == protocol.protocol_hash
    assert protocol_commitment(replace(
        protocol,
        notebook_freeze_input_bundle_sha256="0" * 64,
    )) != protocol.protocol_hash
    assert service.verify_ledger()["valid"] is True


def test_prose_only_hashes_do_not_gain_runtime_binding_authority(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path / "workspace")
    notebook, manifest, static_receipt, receipt, _ = _bundle_inputs(tmp_path)
    bundle_path = tmp_path / "freeze-input-bundle.json"
    create_notebook_freeze_input_bundle(
        notebook,
        manifest,
        receipt,
        bundle_path,
        workspace_root=tmp_path,
        static_preflight_receipt_path=static_receipt,
    )
    spec = _formal_protocol_spec(hypothesis_id)
    spec["inputs_required"] = [
        f"Runtime preflight receipt SHA-256 {_sha256(receipt)}",
        f"Freeze-input bundle SHA-256 {_sha256(bundle_path)}",
    ]
    command = CreateProtocol(**spec)
    draft = service.create_protocol(command)

    with pytest.raises(ValidationError, match="prose digests have no binding authority"):
        service.freeze_protocol(draft.protocol_id)
    assert service.get_protocol(draft.protocol_id).inputs_required == spec["inputs_required"]
