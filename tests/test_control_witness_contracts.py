from __future__ import annotations

import copy
from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from research_machine.application.commands import CreateProtocol
from research_machine.application.policies import validate_protocol_freeze
from research_machine.application.protocol_integrity import protocol_commitment
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ControlDefinition,
    ControlWitnessContract,
    DatasetArtifact,
    ExperimentProtocol,
    MeasurementDefinition,
    MeasurementRole,
    QualityGateResult,
    QualityGateStatus,
    RunStatus,
)
from research_machine.interfaces.cli import _protocol_command
from research_machine.replication.package import verify_replication_package
from test_execution import frozen_formal_protocol, prepared_service, run_command
from test_replication_package import _refresh_packaged_file


def _measurement(
    measurement_id: str,
    role: MeasurementRole,
    target: str,
    observable: str,
) -> MeasurementDefinition:
    return MeasurementDefinition(
        measurement_id=measurement_id,
        role=role,
        registered_target=target,
        observable=observable,
        input_condition="Frozen synthetic control fixture",
        parameter_values={"fixture": "version 1"},
        evaluation_point="After the adverse intervention",
        convention="Positive values are residual margins above the registered baseline",
        aggregation="One scalar margin per fixture",
        tolerance="Compared exactly with the frozen scalar reference",
        expected_behavior="The invalid fixture has a nonpositive residual margin",
        temporal_role="not_applicable",
        scale_type="interval",
        unit="dimensionless",
    )


def _prepared_protocol(tmp_path: Path):
    service, hypothesis_id = prepared_service(tmp_path / "workspace")
    base = frozen_formal_protocol(service, hypothesis_id)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    witness_contract = ControlWitnessContract(
        intervention_id="invalid-proof-step-v1",
        measurement_id="invalid-proof-margin",
        comparator="lte",
        reference_value=0.0,
    )
    control = ControlDefinition(
        control_id="invalid-proof-control",
        registered_control=base.controls[0],
        family="adversarial",
        purpose="Expose acceptance of a deliberately invalid proof step.",
        expected_behavior="The signed residual margin is nonpositive.",
        evaluation_gate_id="proof-check",
        witness_contract=witness_contract,
    )
    draft = service.create_protocol(CreateProtocol(**{
        **values,
        "control_definitions": [control],
        "measurement_definitions": [
            _measurement(
                "primary-measurement",
                MeasurementRole.PRIMARY,
                base.primary_outcome,
                "Proof checker acceptance score",
            ),
            _measurement(
                witness_contract.measurement_id,
                MeasurementRole.CONTROL,
                control.registered_control,
                "Signed invalid-proof residual margin",
            ),
        ],
    }))
    return service, draft, control


def _witness(
    control: ControlDefinition,
    *,
    observed_value: int | float = -0.25,
    decision: bool = True,
) -> dict[str, object]:
    assert control.witness_contract is not None
    return {
        "control_id": control.control_id,
        "intervention_id": control.witness_contract.intervention_id,
        "measurement_id": control.witness_contract.measurement_id,
        "quantity": "Signed invalid-proof residual margin",
        "unit": "dimensionless",
        "comparator": control.witness_contract.comparator,
        "reference_value": control.witness_contract.reference_value,
        "observed_value": observed_value,
        "decision": decision,
    }


def _artifact(tmp_path: Path, selected: object) -> tuple[DatasetArtifact, str]:
    path = tmp_path / "control-witness.json"
    path.write_text(
        json.dumps(
            {"controls": {"invalid-proof-control": selected}},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return (
        DatasetArtifact(
            path.name,
            digest,
            path.stat().st_size,
            "application/json",
        ),
        digest,
    )


def _gate(
    control: ControlDefinition,
    digest: str,
    witness: object,
    *,
    matches_expected: bool = True,
) -> QualityGateResult:
    return QualityGateResult(
        "proof-check",
        QualityGateStatus.PASSED,
        "Synthetic control-witness evaluation.",
        details={
            "evidence_sha256": digest,
            "control_results": {
                control.control_id: {
                    "observed_behavior": "The synthetic signed margin was recorded.",
                    "interpretation": "Fixture-only scalar comparison.",
                    "matches_expected": matches_expected,
                    "evidence_sha256": digest,
                    "evidence_location": f"/controls/{control.control_id}",
                    "witness": witness,
                }
            },
        },
    )


def _record(
    service,
    protocol_id: str,
    control: ControlDefinition,
    tmp_path: Path,
    *,
    selected: object,
    retained_witness: object | None = None,
    matches_expected: bool = True,
):
    artifact, digest = _artifact(tmp_path, selected)
    return service.record_run(run_command(
        protocol_id,
        QualityGateStatus.PASSED,
        synthetic=True,
        artifact_root=str(tmp_path),
        output_artifacts=[artifact],
        quality_gates=[_gate(
            control,
            digest,
            selected if retained_witness is None else retained_witness,
            matches_expected=matches_expected,
        )],
    ))


def test_control_witness_roundtrips_changes_commitment_schema_cli_and_template(
    tmp_path: Path,
) -> None:
    service, draft, control = _prepared_protocol(tmp_path)
    payload = draft.to_dict()
    restored = ExperimentProtocol.from_dict(payload)
    assert restored.control_definitions == [control]
    assert restored.control_definitions[0].witness_contract == control.witness_contract

    legacy_control = replace(control, witness_contract=None)
    legacy_protocol = replace(draft, control_definitions=[legacy_control])
    assert "witness_contract" not in legacy_control.to_dict()
    assert "witness_contract" not in legacy_protocol.to_dict()["control_definitions"][0]
    assert protocol_commitment(draft) != protocol_commitment(legacy_protocol)

    spec = {
        field.name: payload[field.name]
        for field in fields(CreateProtocol)
        if field.name in payload
    }
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/protocol-command.schema.json").read_text()
    )
    jsonschema.validate(spec, schema)
    invalid_spec = copy.deepcopy(spec)
    invalid_spec["control_definitions"][0]["witness_contract"][
        "reference_value"
    ] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid_spec, schema)
    parsed = _protocol_command(spec)
    assert parsed.control_definitions == [control]

    frozen = service.freeze_protocol(draft.protocol_id)
    template = service.run_record_template(frozen.protocol_id)
    assert template["control_plan"] == [control.to_dict()]
    template_witness = template["record"]["quality_gates"][0]["details"][
        "control_results"
    ][control.control_id]["witness"]
    assert template_witness["intervention_id"] == "invalid-proof-step-v1"
    assert template_witness["quantity"] == "Signed invalid-proof residual margin"
    assert template_witness["observed_value"] == "<finite non-Boolean number>"


@pytest.mark.parametrize(
    ("contract_change", "message"),
    [
        ({"comparator": "approximately"}, "comparator is unsupported"),
        ({"reference_value": True}, "non-boolean finite number"),
        ({"reference_value": float("inf")}, "must be finite"),
        ({"reference_value": 10**1000}, "representable as a finite number"),
        ({"measurement_id": "missing-measurement"}, "one exact protocol measurement_id"),
        ({"measurement_id": "primary-measurement"}, "role control"),
        ({"intervention_id": " invalid-proof-step-v1 "}, "canonical"),
    ],
)
def test_control_witness_freeze_rejects_ambiguous_contracts(
    tmp_path: Path,
    contract_change: dict[str, object],
    message: str,
) -> None:
    _, draft, control = _prepared_protocol(tmp_path)
    assert control.witness_contract is not None
    changed = replace(control.witness_contract, **contract_change)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(
            draft,
            control_definitions=[replace(control, witness_contract=changed)],
        ))


def test_control_witness_measurement_must_target_registered_control(
    tmp_path: Path,
) -> None:
    _, draft, control = _prepared_protocol(tmp_path)
    measurements = [
        replace(measurement, registered_target=draft.primary_outcome)
        if measurement.measurement_id == "invalid-proof-margin"
        else measurement
        for measurement in draft.measurement_definitions
    ]

    with pytest.raises(ValidationError, match="every registered control"):
        validate_protocol_freeze(replace(draft, measurement_definitions=measurements))


def test_control_witness_rejects_bare_boolean_selected_evidence(tmp_path: Path) -> None:
    service, draft, control = _prepared_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)

    with pytest.raises(ValidationError, match="artifact-bound JSON object"):
        _record(
            service,
            frozen.protocol_id,
            control,
            tmp_path,
            selected=True,
            retained_witness=_witness(control),
        )


@pytest.mark.parametrize(
    ("mutation", "matches_expected", "message"),
    [
        ({"observed_value": True}, True, "non-boolean finite number"),
        ({"reference_value": 1.0}, True, "does not match the frozen protocol"),
        ({"intervention_id": "different-intervention"}, True, "does not match the frozen protocol"),
        ({"decision": False}, True, "decision does not match the frozen comparison"),
        ({}, False, "matches_expected does not match"),
    ],
)
def test_control_witness_recomputes_frozen_scalar_decision(
    tmp_path: Path,
    mutation: dict[str, object],
    matches_expected: bool,
    message: str,
) -> None:
    service, draft, control = _prepared_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    witness = {**_witness(control), **mutation}

    with pytest.raises(ValidationError, match=message):
        _record(
            service,
            frozen.protocol_id,
            control,
            tmp_path,
            selected=witness,
            matches_expected=matches_expected,
        )


def test_control_witness_must_equal_selected_artifact_mapping(tmp_path: Path) -> None:
    service, draft, control = _prepared_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    selected = _witness(control)
    retained = {**selected, "observed_value": -0.5}

    with pytest.raises(ValidationError, match="does not match its retained JSON evidence"):
        _record(
            service,
            frozen.protocol_id,
            control,
            tmp_path,
            selected=selected,
            retained_witness=retained,
        )


def test_adverse_control_witness_is_retained_and_exposed(tmp_path: Path) -> None:
    service, draft, control = _prepared_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    witness = _witness(control, observed_value=0.25, decision=False)
    run = _record(
        service,
        frozen.protocol_id,
        control,
        tmp_path,
        selected=witness,
        matches_expected=False,
    )

    assert run.status is RunStatus.COMPLETED
    retained = run.quality_gates[0].details["control_results"][control.control_id]
    expected_digest = hashlib.sha256(
        (json.dumps(witness, indent=2, sort_keys=True) + "\n").encode()
    ).hexdigest()
    assert retained["selected_value_sha256"] == expected_digest
    assert retained["witness"]["decision"] is False
    findings = {finding.code for finding in service.audit_rigor().findings}
    assert "CONTROL_WITNESS_ADVERSE" in findings
    synthesis = service.build_synthesis()["content"]
    assert "scalar witness observed `0.25` `lte` reference `0.0`" in synthesis
    assert "cannot prove that the producing code was not hardcoded" in synthesis
    assert "Compound controls must preregister one scalar margin" in synthesis


def test_unperformed_control_witness_remains_visible_in_rigor(tmp_path: Path) -> None:
    service, draft, _ = _prepared_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    run = service.record_run(run_command(
        frozen.protocol_id,
        QualityGateStatus.FAILED,
        synthetic=True,
        quality_gates=[QualityGateResult(
            "proof-check",
            QualityGateStatus.FAILED,
            "Synthetic witness evaluation did not complete.",
        )],
    ))

    assert run.status is RunStatus.INVALID
    findings = {finding.code for finding in service.audit_rigor().findings}
    assert "CONTROL_WITNESS_UNASSESSED" in findings


def test_replication_package_replays_control_witness_and_rejects_tamper(
    tmp_path: Path,
) -> None:
    service, draft, control = _prepared_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    witness = _witness(control)
    _record(
        service,
        frozen.protocol_id,
        control,
        tmp_path,
        selected=witness,
    )
    package = tmp_path / "package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])

    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    retained = runs[0]["quality_gates"][0]["details"]["control_results"][
        control.control_id
    ]
    retained["witness"]["observed_value"] = 0.25
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match="decision does not match"):
        verify_replication_package(package, commitment)
