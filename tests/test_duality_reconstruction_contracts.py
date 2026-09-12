from dataclasses import fields, replace
from fractions import Fraction
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
    DualityReconstructionContract,
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


def _prepared_duality_protocol(tmp_path):
    service, hypothesis = prepared_service(tmp_path / "workspace")
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    control = ControlDefinition(
        control_id="circular-reconstruction",
        registered_control=base.controls[0],
        family="adversarial",
        purpose=(
            "Reject a reconstruction whose definition depends on the object "
            "whose predicate will later be tested."
        ),
        expected_behavior=(
            "The declared reconstruction dependency closure excludes M-weighted."
        ),
        evaluation_gate_id="proof-check",
    )
    predicate = MathematicalPredicateContract(
        contract_id="weighted-pullback-psd",
        object_id="M-weighted",
        object_kind="quadratic_form",
        domain="Coordinates on V-primal",
        codomain="Exact rational scalars",
        quotient="No quotient in the two-dimensional fixture",
        construction="M-weighted = transpose(J) Riesz-map J",
        predicate="positive_semidefinite",
        predicate_definition=(
            "Every exact coordinate vector x has nonnegative x^T M-weighted x"
        ),
        adversarial_control_id=control.control_id,
        evaluation_gate_id="proof-check",
        derived_from_object_ids=["Riesz-map", "J"],
    )
    reconstruction = DualityReconstructionContract(
        contract_id="weighted-riesz-lift",
        predicate_contract_id=predicate.contract_id,
        primal_space_id="V-primal",
        dual_space_id="V-star",
        pairing_id="G-pairing",
        pairing_definition="G = diag(2, 3) in the registered source basis",
        reconstruction_map_id="Riesz-map",
        reconstruction_definition="Riesz-map(r) is the unique v with G(v,w)=r(w)",
        reconstruction_specification_sha256="a" * 64,
        basis_specification_sha256="b" * 64,
        quadrature_specification_sha256="c" * 64,
        source_status="engineering_assumption",
        source_refs=["fixture:weighted-two-dimensional-pairing-v1"],
        forbidden_dependency_object_ids=[predicate.object_id],
        circularity_control_id=control.control_id,
        evaluation_gate_id="proof-check",
    )
    draft = service.create_protocol(CreateProtocol(**{
        **values,
        "control_definitions": [control],
        "mathematical_predicate_contracts": [predicate],
        "duality_reconstruction_contracts": [reconstruction],
    }))
    return service, draft, predicate, reconstruction


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
        "observed_witness": "Both exact principal minors were nonnegative.",
        "interpretation": "Only M-weighted in the registered basis was assessed.",
    }


def _reconstruction_evidence(contract):
    return {
        "predicate_contract_id": contract.predicate_contract_id,
        "primal_space_id": contract.primal_space_id,
        "dual_space_id": contract.dual_space_id,
        "pairing_id": contract.pairing_id,
        "pairing_definition": contract.pairing_definition,
        "reconstruction_map_id": contract.reconstruction_map_id,
        "reconstruction_definition": contract.reconstruction_definition,
        "reconstruction_specification_sha256": (
            contract.reconstruction_specification_sha256
        ),
        "basis_specification_sha256": contract.basis_specification_sha256,
        "quadrature_specification_sha256": contract.quadrature_specification_sha256,
        "source_status": contract.source_status,
        "source_refs": list(contract.source_refs),
        "forbidden_dependency_object_ids": list(
            contract.forbidden_dependency_object_ids
        ),
        "transfer_map_id": contract.transfer_map_id,
        "transfer_specification_sha256": contract.transfer_specification_sha256,
        "observed_reconstruction_dependency_object_ids": [
            contract.primal_space_id,
            contract.dual_space_id,
            contract.pairing_id,
            contract.reconstruction_map_id,
        ],
        "assessment_status": "consistent_with_reconstruction_contract",
        "observed_witness": (
            "The exact Riesz solve transformed contravariantly under the "
            "registered nonorthogonal basis change."
        ),
        "interpretation": (
            "This checks the frozen pairing and dependency boundary, not the "
            "downstream predicate or a physical model."
        ),
    }


def _output(tmp_path, predicate, reconstruction):
    value = {
        "control": {"forbidden_dependency_observed": False},
        "predicate": _predicate_evidence(predicate),
        "reconstruction": _reconstruction_evidence(reconstruction),
    }
    path = tmp_path / "duality-output.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _gate(predicate, reconstruction, digest, *, reconstruction_mutation=None):
    reconstruction_result = {
        **_reconstruction_evidence(reconstruction),
        "evidence_sha256": digest,
        "evidence_location": "/reconstruction",
    }
    if reconstruction_mutation:
        reconstruction_result.update(reconstruction_mutation)
    return QualityGateResult(
        "proof-check",
        QualityGateStatus.PASSED,
        "Synthetic duality and reconstruction check.",
        details={
            "evidence_sha256": digest,
            "control_results": {
                reconstruction.circularity_control_id: {
                    "observed_behavior": (
                        "The dependency closure excluded the tested object."
                    ),
                    "interpretation": "Fixture-only circularity control.",
                    "matches_expected": True,
                    "evidence_sha256": digest,
                    "evidence_location": "/control",
                }
            },
            "mathematical_predicate_results": {
                predicate.contract_id: {
                    **_predicate_evidence(predicate),
                    "evidence_sha256": digest,
                    "evidence_location": "/predicate",
                }
            },
            "duality_reconstruction_results": {
                reconstruction.contract_id: reconstruction_result,
            },
        },
    )


def test_duality_contract_roundtrips_changes_commitment_template_and_schema(tmp_path):
    service, draft, _, contract = _prepared_duality_protocol(tmp_path)
    baseline = replace(draft, duality_reconstruction_contracts=[])
    frozen = service.freeze_protocol(draft.protocol_id)
    restored = ExperimentProtocol.from_dict(frozen.to_dict())
    assert restored.duality_reconstruction_contracts == [contract]
    assert protocol_commitment(frozen) != protocol_commitment(baseline)

    template = service.run_record_template(frozen.protocol_id)
    assert template["duality_reconstruction_plan"] == [contract.to_dict()]
    result = template["record"]["quality_gates"][0]["details"][
        "duality_reconstruction_results"
    ][contract.contract_id]
    assert result["pairing_id"] == "G-pairing"
    assert result["forbidden_dependency_object_ids"] == ["M-weighted"]

    payload = draft.to_dict()
    spec = {
        field.name: payload[field.name]
        for field in fields(CreateProtocol)
        if field.name in payload
    }
    schema_path = Path(__file__).parents[1] / "schemas" / "protocol-command.schema.json"
    jsonschema.validate(spec, json.loads(schema_path.read_text()))
    assert _protocol_command(spec).duality_reconstruction_contracts == [contract]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"pairing_id": "G-pairing "}, "canonical"),
        ({"predicate_contract_id": "missing"}, "exact mathematical predicate"),
        ({"dual_space_id": "V-primal"}, "distinguish primal and dual"),
        ({"source_status": "proved"}, "source_status is unsupported"),
        ({"transfer_map_id": "T"}, "supplied together"),
        ({"forbidden_dependency_object_ids": ["unrelated"]}, "linked predicate"),
        (
            {"forbidden_dependency_object_ids": ["M-weighted", "Riesz-map"]},
            "required dependencies",
        ),
    ],
)
def test_duality_contract_rejects_ambiguous_or_impossible_freezes(
    tmp_path, mutation, message
):
    _, draft, _, contract = _prepared_duality_protocol(tmp_path)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(
            draft,
            duality_reconstruction_contracts=[replace(contract, **mutation)],
        ))


def test_run_and_replication_reject_circular_reconstruction_dependency(tmp_path):
    service, draft, predicate, reconstruction = _prepared_duality_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    path, digest = _output(tmp_path, predicate, reconstruction)
    artifacts = [
        DatasetArtifact(path.name, digest, path.stat().st_size, "application/json")
    ]

    circular_dependencies = (
        _reconstruction_evidence(reconstruction)[
            "observed_reconstruction_dependency_object_ids"
        ]
        + [predicate.object_id]
    )
    with pytest.raises(ValidationError, match="depends on forbidden objects"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=artifacts,
            quality_gates=[_gate(
                predicate,
                reconstruction,
                digest,
                reconstruction_mutation={
                    "observed_reconstruction_dependency_object_ids": (
                        circular_dependencies
                    )
                },
            )],
        ))

    passed = service.record_run(run_command(
        frozen.protocol_id,
        QualityGateStatus.PASSED,
        synthetic=True,
        artifact_root=str(tmp_path),
        output_artifacts=artifacts,
        quality_gates=[_gate(predicate, reconstruction, digest)],
    ))
    assert passed.status is RunStatus.COMPLETED
    retained = passed.quality_gates[0].details[
        "duality_reconstruction_results"
    ][reconstruction.contract_id]
    assert retained["selected_value_sha256"]
    synthesis = service.build_synthesis()["content"]
    assert "Duality and reconstruction provenance" in synthesis
    assert reconstruction.pairing_id in synthesis

    package = tmp_path / "package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])
    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    result = runs[0]["quality_gates"][0]["details"][
        "duality_reconstruction_results"
    ][reconstruction.contract_id]
    result["observed_reconstruction_dependency_object_ids"].append(
        predicate.object_id
    )
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")
    with pytest.raises(ValidationError, match="depends on forbidden objects"):
        verify_replication_package(package, commitment)


def _matmul(left, right):
    return [
        [sum(a * b for a, b in zip(row, column)) for column in zip(*right)]
        for row in left
    ]


def _matvec(matrix, vector):
    return [sum(a * b for a, b in zip(row, vector)) for row in matrix]


def _transpose(matrix):
    return [list(column) for column in zip(*matrix)]


def _inverse_2x2(matrix):
    determinant = matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]
    return [
        [matrix[1][1] / determinant, -matrix[0][1] / determinant],
        [-matrix[1][0] / determinant, matrix[0][0] / determinant],
    ]


def test_weighted_riesz_lift_is_coordinate_covariant_but_naive_identification_is_not():
    """Cross-domain fixture: dual coordinates are not primal coordinates."""

    change = [[Fraction(1), Fraction(1)], [Fraction(0), Fraction(1)]]
    pairing = [[Fraction(2), Fraction(0)], [Fraction(0), Fraction(3)]]
    covector = [Fraction(1), Fraction(2)]

    transformed_covector = _matvec(_transpose(change), covector)
    transformed_pairing = _matmul(
        _matmul(_transpose(change), pairing), change
    )
    riesz_vector = _matvec(_inverse_2x2(pairing), covector)
    transformed_riesz_vector = _matvec(
        _inverse_2x2(transformed_pairing), transformed_covector
    )
    expected_transformed_vector = _matvec(_inverse_2x2(change), riesz_vector)

    assert transformed_riesz_vector == expected_transformed_vector
    assert transformed_covector != expected_transformed_vector
