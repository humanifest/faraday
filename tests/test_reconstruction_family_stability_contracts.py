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
    ReconstructionFamilyStabilityContract,
    RunStatus,
)
from research_machine.interfaces.cli import _protocol_command
from research_machine.replication.package import verify_replication_package
from test_execution import frozen_formal_protocol, prepared_service, run_command
from test_replication_package import _refresh_packaged_file


def _prepared_family_protocol(tmp_path):
    service, hypothesis = prepared_service(tmp_path / "workspace")
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    circular = ControlDefinition(
        control_id="circular-reconstruction",
        registered_control=base.controls[0],
        family="adversarial",
        purpose="Reject downstream-object dependence in the reconstruction.",
        expected_behavior="The dependency closure excludes M-weighted.",
        evaluation_gate_id="proof-check",
    )
    collapsing = ControlDefinition(
        control_id="collapsing-invertible-family",
        registered_control="Individually invertible diagonal maps with h decreasing",
        family="adversarial",
        purpose="Reject finite invertibility as a substitute for family stability.",
        expected_behavior="The family fails the registered uniform lower bound.",
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
        predicate_definition="Every exact coordinate vector has nonnegative value",
        adversarial_control_id=circular.control_id,
        evaluation_gate_id="proof-check",
        derived_from_object_ids=["Riesz-map", "J"],
    )
    reconstruction = DualityReconstructionContract(
        contract_id="weighted-riesz-lift",
        predicate_contract_id=predicate.contract_id,
        primal_space_id="V-primal",
        dual_space_id="V-star",
        pairing_id="G-pairing",
        pairing_definition="G_h is the registered positive diagonal pairing",
        reconstruction_map_id="Riesz-map",
        reconstruction_definition="Solve G_h v = r at each frozen resolution",
        reconstruction_specification_sha256="a" * 64,
        basis_specification_sha256="b" * 64,
        quadrature_specification_sha256="c" * 64,
        source_status="engineering_assumption",
        source_refs=["fixture:weighted-resolution-family-v1"],
        forbidden_dependency_object_ids=[predicate.object_id],
        circularity_control_id=circular.control_id,
        evaluation_gate_id="proof-check",
        transfer_map_id="T-h2-h1",
        transfer_specification_sha256="d" * 64,
    )
    family = ReconstructionFamilyStabilityContract(
        contract_id="weighted-riesz-family-stability",
        duality_reconstruction_contract_id=reconstruction.contract_id,
        resolution_family_id="weighted-two-resolution-family",
        resolution_ids=["h-1", "h-1/2"],
        primal_norm_id="euclidean-primal-norm",
        dual_norm_id="euclidean-dual-norm",
        norm_specification_sha256="2" * 64,
        stability_statistic="smallest_singular_value",
        stability_comparator="greater_than_or_equal",
        stability_threshold=0.4,
        stability_specification_sha256="3" * 64,
        family_specification_sha256="e" * 64,
        test_family_span_id="full-two-coordinate-span",
        test_family_specification_sha256="f" * 64,
        forward_cross_projection_id="project-h1-to-h1/2",
        reverse_cross_projection_id="project-h1/2-to-h1",
        cross_projection_specification_sha256="1" * 64,
        cross_projection_error_threshold=0.01,
        transfer_map_ids=[reconstruction.transfer_map_id],
        transfer_specification_sha256=reconstruction.transfer_specification_sha256,
        adverse_family_control_id=collapsing.control_id,
        adverse_family_specification_sha256="4" * 64,
        evaluation_gate_id="proof-check",
    )
    draft = service.create_protocol(CreateProtocol(**{
        **values,
        "controls": [base.controls[0], collapsing.registered_control],
        "control_definitions": [circular, collapsing],
        "mathematical_predicate_contracts": [predicate],
        "duality_reconstruction_contracts": [reconstruction],
        "reconstruction_family_stability_contracts": [family],
    }))
    return service, draft, predicate, reconstruction, family, circular, collapsing


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
        "interpretation": "Only the frozen fixture object was assessed.",
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
        "reconstruction_specification_sha256": contract.reconstruction_specification_sha256,
        "basis_specification_sha256": contract.basis_specification_sha256,
        "quadrature_specification_sha256": contract.quadrature_specification_sha256,
        "source_status": contract.source_status,
        "source_refs": list(contract.source_refs),
        "forbidden_dependency_object_ids": list(contract.forbidden_dependency_object_ids),
        "transfer_map_id": contract.transfer_map_id,
        "transfer_specification_sha256": contract.transfer_specification_sha256,
        "observed_reconstruction_dependency_object_ids": [
            contract.primal_space_id,
            contract.dual_space_id,
            contract.pairing_id,
            contract.reconstruction_map_id,
            contract.transfer_map_id,
        ],
        "assessment_status": "consistent_with_reconstruction_contract",
        "observed_witness": "The registered exact solves used only frozen dependencies.",
        "interpretation": "This does not establish family stability.",
    }


def _family_evidence(contract, *, stability_values=None):
    return {
        "duality_reconstruction_contract_id": contract.duality_reconstruction_contract_id,
        "resolution_family_id": contract.resolution_family_id,
        "resolution_ids": list(contract.resolution_ids),
        "primal_norm_id": contract.primal_norm_id,
        "dual_norm_id": contract.dual_norm_id,
        "norm_specification_sha256": contract.norm_specification_sha256,
        "stability_statistic": contract.stability_statistic,
        "stability_comparator": contract.stability_comparator,
        "stability_threshold": contract.stability_threshold,
        "stability_specification_sha256": contract.stability_specification_sha256,
        "family_specification_sha256": contract.family_specification_sha256,
        "test_family_span_id": contract.test_family_span_id,
        "test_family_specification_sha256": contract.test_family_specification_sha256,
        "forward_cross_projection_id": contract.forward_cross_projection_id,
        "reverse_cross_projection_id": contract.reverse_cross_projection_id,
        "cross_projection_specification_sha256": contract.cross_projection_specification_sha256,
        "cross_projection_error_threshold": contract.cross_projection_error_threshold,
        "transfer_map_ids": list(contract.transfer_map_ids),
        "transfer_specification_sha256": contract.transfer_specification_sha256,
        "adverse_family_specification_sha256": contract.adverse_family_specification_sha256,
        "observed_resolution_ids": list(contract.resolution_ids),
        "observed_stability_values": stability_values or {"h-1": 0.5, "h-1/2": 0.5},
        "observed_forward_cross_projection_error": 0.0,
        "observed_reverse_cross_projection_error": 0.0,
        "assessment_status": "consistent_with_family_stability_contract",
        "observed_witness": "Both resolutions met the bound and both cross-projections agreed.",
        "interpretation": "Only the frozen two-resolution family was assessed.",
    }


def _control_evidence(observed, interpretation):
    return {
        "observed_behavior": observed,
        "interpretation": interpretation,
        "matches_expected": True,
    }


def _output(tmp_path, predicate, reconstruction, family):
    value = {
        "controls": {
            "circular": _control_evidence(
                "The dependency closure excluded M-weighted.",
                "Fixture-only circularity control.",
            ),
            "adverse": _control_evidence(
                "The collapsing invertible family failed the lower bound.",
                "Finite invertibility did not mask loss of uniform stability.",
            ),
        },
        "predicate": _predicate_evidence(predicate),
        "reconstruction": _reconstruction_evidence(reconstruction),
        "family": _family_evidence(family),
    }
    path = tmp_path / "family-output.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), value


def _gate(predicate, reconstruction, family, digest, value, *, family_mutation=None):
    family_result = {
        **value["family"],
        "evidence_sha256": digest,
        "evidence_location": "/family",
    }
    if family_mutation:
        family_result.update(family_mutation)
    controls = {
        "circular-reconstruction": {
            **value["controls"]["circular"],
            "evidence_sha256": digest,
            "evidence_location": "/controls/circular",
        },
        "collapsing-invertible-family": {
            **value["controls"]["adverse"],
            "evidence_sha256": digest,
            "evidence_location": "/controls/adverse",
        },
    }
    return QualityGateResult(
        "proof-check",
        QualityGateStatus.PASSED,
        "Synthetic reconstruction family stability check.",
        details={
            "evidence_sha256": digest,
            "control_results": controls,
            "mathematical_predicate_results": {
                predicate.contract_id: {
                    **value["predicate"],
                    "evidence_sha256": digest,
                    "evidence_location": "/predicate",
                }
            },
            "duality_reconstruction_results": {
                reconstruction.contract_id: {
                    **value["reconstruction"],
                    "evidence_sha256": digest,
                    "evidence_location": "/reconstruction",
                }
            },
            "reconstruction_family_stability_results": {
                family.contract_id: family_result,
            },
        },
    )


def test_family_contract_roundtrips_changes_commitment_template_and_schema(tmp_path):
    service, draft, _, _, contract, _, _ = _prepared_family_protocol(tmp_path)
    baseline = replace(draft, reconstruction_family_stability_contracts=[])
    frozen = service.freeze_protocol(draft.protocol_id)
    restored = ExperimentProtocol.from_dict(frozen.to_dict())
    assert restored.reconstruction_family_stability_contracts == [contract]
    assert protocol_commitment(frozen) != protocol_commitment(baseline)

    template = service.run_record_template(frozen.protocol_id)
    assert template["reconstruction_family_stability_plan"] == [contract.to_dict()]
    result = template["record"]["quality_gates"][0]["details"][
        "reconstruction_family_stability_results"
    ][contract.contract_id]
    assert result["resolution_ids"] == ["h-1", "h-1/2"]
    assert result["observed_stability_values"] == {}

    payload = draft.to_dict()
    spec = {
        field.name: payload[field.name]
        for field in fields(CreateProtocol)
        if field.name in payload
    }
    schema_path = Path(__file__).parents[1] / "schemas" / "protocol-command.schema.json"
    jsonschema.validate(spec, json.loads(schema_path.read_text()))
    parsed = _protocol_command(spec)
    assert parsed.reconstruction_family_stability_contracts == [contract]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"duality_reconstruction_contract_id": "missing"}, "exact duality"),
        ({"resolution_ids": ["h-1"]}, "at least two"),
        ({"dual_norm_id": "euclidean-primal-norm"}, "distinguish primal and dual"),
        ({"stability_statistic": "determinant"}, "statistic is unsupported"),
        ({"stability_comparator": "less_than_or_equal"}, "must be greater_than_or_equal"),
        ({"stability_threshold": -0.1}, "finite and nonnegative"),
        ({"reverse_cross_projection_id": "project-h1-to-h1/2"}, "distinct forward"),
        ({"transfer_map_ids": []}, "at least one transfer"),
        ({"transfer_map_ids": ["unrelated"]}, "must include"),
        ({"adverse_family_control_id": "missing"}, "exact adverse family"),
    ],
)
def test_family_contract_rejects_ambiguous_or_incomplete_freezes(
    tmp_path, mutation, message
):
    _, draft, _, _, contract, _, _ = _prepared_family_protocol(tmp_path)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(
            draft,
            reconstruction_family_stability_contracts=[
                replace(contract, **mutation)
            ],
        ))


def test_run_and_replication_reject_below_threshold_family_result(tmp_path):
    service, draft, predicate, reconstruction, family, _, _ = (
        _prepared_family_protocol(tmp_path)
    )
    frozen = service.freeze_protocol(draft.protocol_id)
    path, digest, value = _output(tmp_path, predicate, reconstruction, family)
    artifacts = [
        DatasetArtifact(path.name, digest, path.stat().st_size, "application/json")
    ]
    mutation = {"observed_stability_values": {"h-1": 0.5, "h-1/2": 0.25}}
    with pytest.raises(ValidationError, match="violates its frozen stability"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=artifacts,
            quality_gates=[_gate(
                predicate,
                reconstruction,
                family,
                digest,
                value,
                family_mutation=mutation,
            )],
        ))

    passed = service.record_run(run_command(
        frozen.protocol_id,
        QualityGateStatus.PASSED,
        synthetic=True,
        artifact_root=str(tmp_path),
        output_artifacts=artifacts,
        quality_gates=[_gate(
            predicate, reconstruction, family, digest, value
        )],
    ))
    assert passed.status is RunStatus.COMPLETED
    retained = passed.quality_gates[0].details[
        "reconstruction_family_stability_results"
    ][family.contract_id]
    assert retained["selected_value_sha256"]
    synthesis = service.build_synthesis()["content"]
    assert "Reconstruction family stability" in synthesis
    assert family.resolution_family_id in synthesis

    package = tmp_path / "package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])
    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    result = runs[0]["quality_gates"][0]["details"][
        "reconstruction_family_stability_results"
    ][family.contract_id]
    result["observed_stability_values"]["h-1/2"] = 0.25
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")
    with pytest.raises(ValidationError, match="violates its frozen stability"):
        verify_replication_package(package, commitment)


def test_individually_invertible_family_can_lose_uniform_stability():
    """Non-physics fixture: every diagonal map is invertible, but not uniformly."""

    resolutions = [Fraction(1, 1), Fraction(1, 2), Fraction(1, 4)]
    determinants = [h for h in resolutions]
    smallest_singular_values = [h for h in resolutions]
    inverse_norms = [Fraction(1, h) for h in resolutions]

    assert all(determinant != 0 for determinant in determinants)
    assert smallest_singular_values == resolutions
    assert inverse_norms == [Fraction(1), Fraction(2), Fraction(4)]
    assert smallest_singular_values[-1] < Fraction(2, 5)
