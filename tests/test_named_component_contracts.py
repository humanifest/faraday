from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import pytest
import jsonschema

from research_machine.application.commands import CreateProtocol
from research_machine.application.policies import validate_protocol_freeze
from research_machine.application.protocol_integrity import protocol_commitment
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ControlDefinition,
    DatasetArtifact,
    ExperimentProtocol,
    MeasurementDefinition,
    MeasurementRole,
    NamedComponentContract,
    QualityGateResult,
    QualityGateStatus,
    RunStatus,
)
from research_machine.replication.package import verify_replication_package
from research_machine.interfaces.cli import _protocol_command
from test_execution import frozen_formal_protocol, prepared_service, run_command
from test_replication_package import _refresh_packaged_file


def _measurement(measurement_id, role, target):
    return MeasurementDefinition(
        measurement_id=measurement_id,
        role=role,
        registered_target=target,
        observable="Named component values",
        input_condition="Frozen synthetic component fixture",
        parameter_values={"fixture": "version 1"},
        evaluation_point="After component extraction",
        convention="Component IDs are exact and case-sensitive",
        aggregation="One vector per fixture",
        tolerance="Exact identifier and index equality",
        expected_behavior="The named subset is invariant to component reordering",
    )


def _prepared_named_component_protocol(tmp_path):
    service, hypothesis = prepared_service(tmp_path / "workspace")
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    control = ControlDefinition(
        control_id="relabel-components",
        registered_control=base.controls[0],
        family="adversarial",
        purpose="Detect accidental positional component selection.",
        expected_behavior="The same named subset is recovered after reordering.",
        evaluation_gate_id="proof-check",
    )
    contract = NamedComponentContract(
        contract_id="named-edge-subset",
        measurement_id="primary-measurement",
        component_ids=["edge-a", "decoy-x", "edge-b", "decoy-y"],
        selected_component_ids=["edge-a", "edge-b"],
        relabeled_component_ids=["decoy-x", "edge-b", "decoy-y", "edge-a"],
        relabeling_control_id=control.control_id,
        evaluation_gate_id="proof-check",
    )
    draft = service.create_protocol(CreateProtocol(**{
        **values,
        "control_definitions": [control],
        "measurement_definitions": [
            _measurement(
                "primary-measurement", MeasurementRole.PRIMARY,
                base.primary_outcome,
            ),
            _measurement(
                "control-measurement", MeasurementRole.CONTROL,
                base.controls[0],
            ),
        ],
        "named_component_contracts": [contract],
    }))
    return service, draft, contract, control


def _output(tmp_path, *, positional=False):
    path = tmp_path / (
        "component-output-positional.json" if positional else "component-output.json"
    )
    relabeled_indices = [0, 2] if positional else [3, 1]
    relabeled_selected = (
        ["decoy-x", "decoy-y"] if positional else ["edge-a", "edge-b"]
    )
    path.write_text(json.dumps({
        "named_component": {
            "source_component_ids": ["edge-a", "decoy-x", "edge-b", "decoy-y"],
            "source_selection_indices": [0, 2],
            "relabeled_component_ids": [
                "decoy-x", "edge-b", "decoy-y", "edge-a",
            ],
            "relabeled_selection_indices": relabeled_indices,
            "source_selected_component_ids": ["edge-a", "edge-b"],
            "relabeled_selected_component_ids": relabeled_selected,
        },
        "control": {"fixture": "retained"},
    }) + "\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest


def _gate(contract, digest, *, status=QualityGateStatus.PASSED, positional=False):
    relabeled_indices = [0, 2] if positional else [3, 1]
    relabeled_selected = (
        ["decoy-x", "decoy-y"] if positional else ["edge-a", "edge-b"]
    )
    matches_expected = status is QualityGateStatus.PASSED
    return QualityGateResult(
        "proof-check",
        status,
        "Synthetic named-component invariant evaluation.",
        details={
            **({"evidence_sha256": digest} if status is QualityGateStatus.PASSED else {}),
            "control_results": {
                "relabel-components": {
                    "observed_behavior": "The synthetic relabeling was evaluated.",
                    "interpretation": "Fixture-only metamorphic control.",
                    "matches_expected": matches_expected,
                    "evidence_sha256": digest,
                    "evidence_location": "/control",
                }
            },
            "named_component_results": {
                contract.contract_id: {
                    "source_component_ids": list(contract.component_ids),
                    "source_selection_indices": [0, 2],
                    "relabeled_component_ids": list(contract.relabeled_component_ids),
                    "relabeled_selection_indices": relabeled_indices,
                    "source_selected_component_ids": ["edge-a", "edge-b"],
                    "relabeled_selected_component_ids": relabeled_selected,
                    "assessment_status": (
                        "consistent_with_named_selection"
                        if status is QualityGateStatus.PASSED
                        else "inconclusive"
                        if status is QualityGateStatus.WARNING
                        else "contradicted_named_selection"
                    ),
                    "observed_behavior": "Both frozen component orders were evaluated.",
                    "interpretation": "Only the registered name-selection invariant was assessed.",
                    "evidence_sha256": digest,
                    "evidence_location": "/named_component",
                }
            },
        },
    )


def test_named_component_contract_roundtrips_changes_commitment_and_templates(tmp_path):
    service, draft, contract, _ = _prepared_named_component_protocol(tmp_path)
    baseline = replace(draft, named_component_contracts=[])
    frozen = service.freeze_protocol(draft.protocol_id)
    restored = ExperimentProtocol.from_dict(frozen.to_dict())
    assert restored.named_component_contracts == [contract]
    assert protocol_commitment(frozen) != protocol_commitment(baseline)

    template = service.run_record_template(frozen.protocol_id)
    assert template["named_component_plan"] == [contract.to_dict()]
    result = template["record"]["quality_gates"][0]["details"][
        "named_component_results"
    ][contract.contract_id]
    assert result["source_selection_indices"] == [0, 2]
    assert result["relabeled_selection_indices"] == [3, 1]


def test_named_component_contract_is_accepted_by_published_schema_and_cli(tmp_path):
    _, draft, contract, _ = _prepared_named_component_protocol(tmp_path)
    payload = draft.to_dict()
    spec = {
        field.name: payload[field.name]
        for field in fields(CreateProtocol)
        if field.name in payload
    }
    schema_path = Path(__file__).parents[1] / "schemas" / "protocol-command.schema.json"
    jsonschema.validate(spec, json.loads(schema_path.read_text()))
    parsed = _protocol_command(spec)
    assert parsed.named_component_contracts == [contract]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"measurement_id": "missing"}, "exact protocol measurement_id"),
        ({"component_ids": ["edge-a", "edge-a"]}, "duplicates"),
        ({"selected_component_ids": ["missing"]}, "must name frozen"),
        ({"relabeled_component_ids": ["edge-a", "edge-b"]}, "exact permutation"),
        (
            {
                "selected_component_ids": ["edge-a"],
                "relabeled_component_ids": [
                    "edge-a", "decoy-y", "edge-b", "decoy-x",
                ],
            },
            "must change a selected component index",
        ),
        ({"relabeling_control_id": "missing"}, "exact relabeling control_id"),
    ],
)
def test_named_component_contract_rejects_ambiguous_or_nondiscriminating_forms(
    tmp_path, mutation, message
):
    _, draft, contract, _ = _prepared_named_component_protocol(tmp_path)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(
            draft,
            named_component_contracts=[replace(contract, **mutation)],
        ))


def test_named_component_contract_requires_matching_adversarial_control(tmp_path):
    _, draft, contract, control = _prepared_named_component_protocol(tmp_path)
    with pytest.raises(ValidationError, match="must be adversarial"):
        validate_protocol_freeze(replace(
            draft,
            control_definitions=[replace(control, family="reference")],
        ))
    with pytest.raises(ValidationError, match="share an evaluation gate"):
        validate_protocol_freeze(replace(
            draft,
            named_component_contracts=[replace(
                contract, evaluation_gate_id="other-gate"
            )],
            quality_requirements=["proof-check", "other-gate"],
        ))


def test_named_selection_passes_but_positional_selection_must_be_recorded_as_failure(
    tmp_path,
):
    service, draft, contract, _ = _prepared_named_component_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    path, digest = _output(tmp_path)
    artifacts = [DatasetArtifact(
        path.name, digest, path.stat().st_size, "application/json"
    )]

    missing_results_gate = _gate(contract, digest)
    missing_results_gate.details.pop("named_component_results")
    with pytest.raises(ValidationError, match="requires exact results"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=artifacts,
            quality_gates=[missing_results_gate],
        ))

    passed = service.record_run(run_command(
        frozen.protocol_id,
        QualityGateStatus.PASSED,
        synthetic=True,
        artifact_root=str(tmp_path),
        output_artifacts=artifacts,
        quality_gates=[_gate(contract, digest)],
    ))
    assert passed.status is RunStatus.COMPLETED
    retained_mapping = json.loads(path.read_text())["named_component"]
    expected_selected_value_sha256 = hashlib.sha256(json.dumps(
        retained_mapping,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    ).encode() + b"\n").hexdigest()
    assert passed.quality_gates[0].details["named_component_results"][
        contract.contract_id
    ]["selected_value_sha256"] == expected_selected_value_sha256

    positional_path, positional_digest = _output(tmp_path, positional=True)
    positional_artifacts = [DatasetArtifact(
        positional_path.name,
        positional_digest,
        positional_path.stat().st_size,
        "application/json",
    )]

    with pytest.raises(ValidationError, match="retained JSON mapping evidence"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=positional_artifacts,
            quality_gates=[_gate(contract, positional_digest)],
        ))

    with pytest.raises(ValidationError, match="by position"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=positional_artifacts,
            quality_gates=[_gate(contract, positional_digest, positional=True)],
        ))

    failed = service.record_run(run_command(
        frozen.protocol_id,
        QualityGateStatus.FAILED,
        synthetic=True,
        artifact_root=str(tmp_path),
        output_artifacts=positional_artifacts,
        quality_gates=[_gate(
            contract,
            positional_digest,
            status=QualityGateStatus.FAILED,
            positional=True,
        )],
    ))
    assert failed.status is RunStatus.INVALID
    recorded = failed.quality_gates[0].details["named_component_results"][
        contract.contract_id
    ]
    assert recorded["assessment_status"] == "contradicted_named_selection"
    assert recorded["relabeled_selected_component_ids"] == ["decoy-x", "decoy-y"]
    codes = {item.code for item in service.audit_rigor().findings}
    assert "NAMED_COMPONENT_SELECTION_CONTRADICTED" in codes
    synthesis = service.build_synthesis()["content"]
    assert "Named-component selection provenance" in synthesis
    assert "does not validate component meaning" in synthesis


def test_replication_verifier_replays_named_component_invariant(tmp_path):
    service, draft, contract, _ = _prepared_named_component_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    path, digest = _output(tmp_path)
    service.record_run(run_command(
        frozen.protocol_id,
        QualityGateStatus.PASSED,
        synthetic=True,
        artifact_root=str(tmp_path),
        output_artifacts=[DatasetArtifact(
            path.name, digest, path.stat().st_size, "application/json"
        )],
        quality_gates=[_gate(contract, digest)],
    ))
    package = tmp_path / "package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])

    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    result = runs[0]["quality_gates"][0]["details"]["named_component_results"][
        contract.contract_id
    ]
    result["relabeled_selection_indices"] = [0, 2]
    result["relabeled_selected_component_ids"] = ["decoy-x", "decoy-y"]
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match="by position"):
        verify_replication_package(package, commitment)
