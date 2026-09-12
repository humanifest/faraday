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
    DatasetArtifact,
    ExperimentProtocol,
    MathematicalPredicateContract,
    QualityGateResult,
    QualityGateStatus,
    RunStatus,
)
from research_machine.interfaces.cli import _protocol_command
from research_machine.replication.package import verify_replication_package
from test_execution import frozen_formal_protocol, prepared_service, run_command
from test_replication_package import _refresh_packaged_file


def _prepared_predicate_protocol(tmp_path):
    service, hypothesis = prepared_service(tmp_path / "workspace")
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    control = ControlDefinition(
        control_id="wrong-object-attribution",
        registered_control=base.controls[0],
        family="adversarial",
        purpose="Reject attributing a pullback predicate to its source operator.",
        expected_behavior="The substituted source object ID is rejected.",
        evaluation_gate_id="proof-check",
    )
    contract = MathematicalPredicateContract(
        contract_id="pullback-psd",
        object_id="M-pullback",
        object_kind="quadratic_form",
        domain="Gauge-fixed coordinate space Y",
        codomain="Real scalars",
        quotient="No quotient; the declared gauge-fixed coordinate chart is used",
        construction="M-pullback = transpose(J-residual) D-residual J-residual",
        predicate="positive_semidefinite",
        predicate_definition="Every vector y in Y has y^T M-pullback y greater than or equal to zero",
        adversarial_control_id=control.control_id,
        evaluation_gate_id="proof-check",
        derived_from_object_ids=["D-residual", "J-residual"],
    )
    draft = service.create_protocol(CreateProtocol(**{
        **values,
        "control_definitions": [control],
        "mathematical_predicate_contracts": [contract],
    }))
    return service, draft, contract


def _predicate_evidence(contract):
    return {
        "object_id": contract.object_id,
        "object_kind": contract.object_kind,
        "domain": contract.domain,
        "codomain": contract.codomain,
        "quotient": contract.quotient,
        "construction": contract.construction,
        "predicate": contract.predicate,
        "predicate_definition": contract.predicate_definition,
        "derived_from_object_ids": list(contract.derived_from_object_ids),
        "comparison_object_ids": list(contract.comparison_object_ids),
        "equivalence_conditions": list(contract.equivalence_conditions),
        "assessment_status": "consistent_with_predicate",
        "observed_witness": "All exact principal-minor checks were nonnegative.",
        "interpretation": "Only the frozen pullback form was assessed.",
    }


def _output(tmp_path, contract):
    path = tmp_path / "predicate-output.json"
    path.write_text(
        json.dumps({"predicate": _predicate_evidence(contract)}) + "\n",
        encoding="utf-8",
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _gate(contract, digest, *, result_mutation=None):
    result = {
        **_predicate_evidence(contract),
        "evidence_sha256": digest,
        "evidence_location": "/predicate",
    }
    if result_mutation:
        result.update(result_mutation)
    return QualityGateResult(
        "proof-check",
        QualityGateStatus.PASSED,
        "Synthetic mathematical-predicate attribution check.",
        details={
            "evidence_sha256": digest,
            "control_results": {
                "wrong-object-attribution": {
                    "observed_behavior": "The wrong-object substitution was rejected.",
                    "interpretation": "Fixture-only attribution control.",
                    "matches_expected": True,
                    "evidence_sha256": digest,
                    "evidence_location": "/predicate",
                }
            },
            "mathematical_predicate_results": {
                contract.contract_id: result,
            },
        },
    )


def test_predicate_contract_roundtrips_changes_commitment_template_and_schema(tmp_path):
    service, draft, contract = _prepared_predicate_protocol(tmp_path)
    baseline = replace(draft, mathematical_predicate_contracts=[])
    frozen = service.freeze_protocol(draft.protocol_id)
    restored = ExperimentProtocol.from_dict(frozen.to_dict())
    assert restored.mathematical_predicate_contracts == [contract]
    assert protocol_commitment(frozen) != protocol_commitment(baseline)

    template = service.run_record_template(frozen.protocol_id)
    assert template["mathematical_predicate_plan"] == [contract.to_dict()]
    result = template["record"]["quality_gates"][0]["details"][
        "mathematical_predicate_results"
    ][contract.contract_id]
    assert result["object_id"] == "M-pullback"
    assert result["derived_from_object_ids"] == ["D-residual", "J-residual"]

    payload = draft.to_dict()
    spec = {
        field.name: payload[field.name]
        for field in fields(CreateProtocol)
        if field.name in payload
    }
    schema_path = Path(__file__).parents[1] / "schemas" / "protocol-command.schema.json"
    jsonschema.validate(spec, json.loads(schema_path.read_text()))
    assert _protocol_command(spec).mathematical_predicate_contracts == [contract]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"object_id": "M-pullback "}, "canonical"),
        ({"object_id": "D-residual"}, "derive from itself"),
        ({"object_kind": "residual"}, "requires a form"),
        ({"adversarial_control_id": "missing"}, "exact adversarial control_id"),
    ],
)
def test_predicate_contract_rejects_ambiguous_attribution(
    tmp_path, mutation, message
):
    _, draft, contract = _prepared_predicate_protocol(tmp_path)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(
            draft,
            mathematical_predicate_contracts=[replace(contract, **mutation)],
        ))


def test_equivalence_requires_one_comparator_and_explicit_conditions(tmp_path):
    _, draft, contract = _prepared_predicate_protocol(tmp_path)
    equivalent = replace(
        contract,
        object_id="route-rtd",
        object_kind="linear_map",
        domain="Regional gauge-fixed histories",
        codomain="Regional residual dual",
        construction="Reduce then discretize",
        predicate="equivalent",
        predicate_definition="The two maps agree on their declared common domain",
        derived_from_object_ids=[],
    )
    with pytest.raises(ValidationError, match="exactly one comparison object"):
        validate_protocol_freeze(replace(
            draft,
            mathematical_predicate_contracts=[equivalent],
        ))
    valid = replace(
        equivalent,
        comparison_object_ids=["route-dtr"],
        equivalence_conditions=[
            "Both maps have the same declared domain and codomain",
            "The registered identity intertwiner commutes with both maps",
        ],
    )
    validate_protocol_freeze(replace(
        draft,
        mathematical_predicate_contracts=[valid],
    ))


def test_run_and_replication_reject_wrong_object_attribution(tmp_path):
    service, draft, contract = _prepared_predicate_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    path, digest = _output(tmp_path, contract)
    artifacts = [
        DatasetArtifact(path.name, digest, path.stat().st_size, "application/json")
    ]

    with pytest.raises(ValidationError, match="object_id does not match"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=artifacts,
            quality_gates=[_gate(
                contract, digest, result_mutation={"object_id": "D-residual"}
            )],
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
    assert passed.quality_gates[0].details["mathematical_predicate_results"][
        contract.contract_id
    ]["selected_value_sha256"]

    package = tmp_path / "package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])
    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    runs[0]["quality_gates"][0]["details"]["mathematical_predicate_results"][
        contract.contract_id
    ]["object_id"] = "D-residual"
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")
    with pytest.raises(ValidationError, match="object_id does not match"):
        verify_replication_package(package, commitment)
