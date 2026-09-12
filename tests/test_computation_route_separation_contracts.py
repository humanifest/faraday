from dataclasses import fields, replace
import ast
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from research_machine.application.commands import CreateProtocol
from research_machine.application.policies import (
    analysis_implementation_bundle_sha256,
    validate_analysis_implementation_bundle_contracts,
    validate_computation_route_separation_gate_metadata,
    validate_protocol_freeze,
)
from research_machine.application.protocol_integrity import protocol_commitment
from research_machine.application.rigor import audit_research_state
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisImplementationBundleContract,
    AnalysisImplementationMember,
    ComputationRouteSeparationContract,
    ControlDefinition,
    CrossRouteDependencyEdge,
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


def _bundle(bundle_id, entrypoint, members):
    return AnalysisImplementationBundleContract(
        contract_id=bundle_id,
        analysis_code_hash="a" * 64,
        entrypoint_locators=[entrypoint],
        members=members,
        bundle_sha256=analysis_implementation_bundle_sha256(members),
        closure_method="static_plus_runtime_trace",
        closure_specification_sha256="1" * 64,
        closure_limitations=[
            "The frozen static and runtime methods cover only exercised Python paths."
        ],
        allowed_external_dependency_ids=["python-standard-library"],
        external_dependency_specification_sha256="2" * 64,
        observed_member_receipt_specification_sha256="3" * 64,
        adverse_omission_control_id="shared-helper-control",
        evaluation_gate_id="proof-check",
    )


def _prepared_route_protocol(tmp_path):
    service, hypothesis = prepared_service(tmp_path / "workspace")
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    control = ControlDefinition(
        control_id="shared-helper-control",
        registered_control=base.controls[0],
        family="adversarial",
        purpose=(
            "Require a deliberately shared undeclared solver to violate the "
            "two-route separation boundary."
        ),
        expected_behavior=(
            "Both static and runtime receipts expose shared_solver.py and reject "
            "the nominally separate routes."
        ),
        evaluation_gate_id="proof-check",
    )
    predicate = MathematicalPredicateContract(
        contract_id="route-output-agreement",
        object_id="route-a-output",
        object_kind="custom",
        domain="Aligned shared-input result pairs",
        codomain="Nonnegative real discrepancy",
        quotient="No quotient; compare the frozen aligned result pair",
        construction="Apply the frozen norm to aligned route outputs",
        predicate="equivalent",
        predicate_definition=(
            "The frozen route-output discrepancy satisfies the registered comparator."
        ),
        adversarial_control_id=control.control_id,
        evaluation_gate_id="proof-check",
        comparison_object_ids=["route-b-output"],
        equivalence_conditions=[
            "Both routes consume the exact same approved shared input object.",
            "The frozen alignment, norm, unit, comparator, and tolerance are used.",
        ],
    )
    shared = AnalysisImplementationMember(
        "analysis/shared_fixture.py", "approved shared input fixture", "4" * 64, 11
    )
    route_a = AnalysisImplementationMember(
        "analysis/route_a.py", "route A entrypoint", "5" * 64, 17
    )
    route_b = AnalysisImplementationMember(
        "analysis/route_b.py", "route B entrypoint", "6" * 64, 19
    )
    bundle_a = _bundle(
        "bundle-route-a", "analysis/route_a.py", [route_a, shared]
    )
    bundle_b = _bundle(
        "bundle-route-b", "analysis/route_b.py", [route_b, shared]
    )
    contract = ComputationRouteSeparationContract(
        contract_id="two-route-comparison",
        comparison_predicate_contract_id=predicate.contract_id,
        route_ids=["route-a", "route-b"],
        implementation_bundle_contract_ids=[
            bundle_a.contract_id,
            bundle_b.contract_id,
        ],
        approved_shared_input_object_ids=["shared-fixture-v1"],
        approved_shared_member_locators=["analysis/shared_fixture.py"],
        forbidden_cross_route_dependency_edges=[
            CrossRouteDependencyEdge(
                "route-a", "route-b", "analysis/route_b.py"
            ),
            CrossRouteDependencyEdge(
                "route-b", "route-a", "analysis/route_a.py"
            ),
        ],
        comparison_domain=predicate.domain,
        comparison_domain_specification_sha256="7" * 64,
        alignment_specification_sha256="8" * 64,
        norm_id="absolute-difference",
        norm_specification_sha256="9" * 64,
        comparison_unit="dimensionless fixture units",
        comparison_comparator="less_than_or_equal",
        comparison_tolerance=1e-12,
        static_separation_method="static_import_graph",
        static_separation_specification_sha256="a" * 64,
        runtime_separation_method="runtime_import_trace",
        runtime_separation_specification_sha256="b" * 64,
        separation_limitations=[
            "Static inspection may miss generated or reflective dependencies.",
            "Runtime tracing covers only the frozen primary and adverse paths.",
        ],
        adverse_shared_helper_control_id=control.control_id,
        evaluation_gate_id="proof-check",
    )
    draft = service.create_protocol(CreateProtocol(**{
        **values,
        "control_definitions": [control],
        "mathematical_predicate_contracts": [predicate],
        "analysis_implementation_bundle_contracts": [bundle_a, bundle_b],
        "computation_route_separation_contracts": [contract],
    }))
    return service, draft, contract, predicate, [bundle_a, bundle_b]


def _predicate_evidence(predicate, status="consistent_with_predicate"):
    return {
        "object_id": predicate.object_id,
        "object_kind": predicate.object_kind,
        "domain": predicate.domain,
        "codomain": predicate.codomain,
        "quotient": predicate.quotient,
        "construction": predicate.construction,
        "predicate": predicate.predicate,
        "predicate_definition": predicate.predicate_definition,
        "derived_from_object_ids": list(predicate.derived_from_object_ids),
        "comparison_object_ids": list(predicate.comparison_object_ids),
        "equivalence_conditions": list(predicate.equivalence_conditions),
        "assessment_status": status,
        "observed_witness": "The frozen discrepancy and comparator were evaluated.",
        "interpretation": "Agreement is conditional on the frozen comparison choices.",
    }


def _bundle_evidence(bundle, status="consistent_with_implementation_bundle_contract"):
    return {
        "analysis_code_hash": bundle.analysis_code_hash,
        "entrypoint_locators": list(bundle.entrypoint_locators),
        "members": [member.to_dict() for member in bundle.members],
        "bundle_sha256": bundle.bundle_sha256,
        "closure_method": bundle.closure_method,
        "closure_specification_sha256": bundle.closure_specification_sha256,
        "closure_limitations": list(bundle.closure_limitations),
        "allowed_external_dependency_ids": list(bundle.allowed_external_dependency_ids),
        "external_dependency_specification_sha256": (
            bundle.external_dependency_specification_sha256
        ),
        "observed_member_receipt_specification_sha256": (
            bundle.observed_member_receipt_specification_sha256
        ),
        "observed_entrypoint_locators": list(bundle.entrypoint_locators),
        "observed_member_locators": [member.locator for member in bundle.members],
        "observed_member_sha256s": {
            member.locator: member.sha256 for member in bundle.members
        },
        "observed_bundle_sha256": bundle.bundle_sha256,
        "observed_closure_method": bundle.closure_method,
        "observed_external_dependency_ids": list(
            bundle.allowed_external_dependency_ids
        ),
        "observed_closure_complete": True,
        "assessment_status": status,
        "observed_witness": "The frozen member surface matched the receipt.",
        "interpretation": "This is byte and bounded-closure consistency only.",
    }


def _route_evidence(contract, **overrides):
    value = {
        key: child
        for key, child in contract.to_dict().items()
        if key not in {
            "contract_id",
            "adverse_shared_helper_control_id",
            "evaluation_gate_id",
        }
    }
    value.update({
        "observed_route_ids": list(contract.route_ids),
        "observed_implementation_bundle_contract_ids": list(
            contract.implementation_bundle_contract_ids
        ),
        "observed_shared_input_object_ids": list(
            contract.approved_shared_input_object_ids
        ),
        "observed_static_shared_member_locators": list(
            contract.approved_shared_member_locators
        ),
        "observed_runtime_shared_member_locators": list(
            contract.approved_shared_member_locators
        ),
        "observed_static_dependency_edges": [],
        "observed_runtime_dependency_edges": [],
        "observed_static_receipt_complete": True,
        "observed_runtime_receipt_complete": True,
        "static_separation_satisfied": True,
        "runtime_separation_satisfied": True,
        "observed_comparison_value": 0.0,
        "comparison_satisfied": True,
        "assessment_status": "consistent_with_route_separation_contract",
        "observed_witness": (
            "The declared route surfaces shared only the approved fixture member."
        ),
        "interpretation": (
            "Declared code-level separation only; no reasoning or correctness claim."
        ),
    })
    value.update(overrides)
    return value


def _output_and_gate(tmp_path, contract, predicate, bundles, **route_overrides):
    control = {
        "observed_behavior": "The hidden shared-solver adverse fixture was detected.",
        "interpretation": "This control tests only the declared route boundary.",
        "matches_expected": True,
    }
    predicate_value = _predicate_evidence(predicate)
    bundle_values = {
        bundle.contract_id: _bundle_evidence(bundle) for bundle in bundles
    }
    route_value = _route_evidence(contract, **route_overrides)
    payload = {
        "control": control,
        "predicate": predicate_value,
        "bundles": bundle_values,
        "route": route_value,
    }
    path = tmp_path / "route-separation-output.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    control_result = {
        **control,
        "evidence_sha256": digest,
        "evidence_location": "/control",
    }
    gate = QualityGateResult(
        "proof-check",
        QualityGateStatus.PASSED,
        "Synthetic two-route code-separation receipt.",
        details={
            "evidence_sha256": digest,
            "control_results": {"shared-helper-control": control_result},
            "mathematical_predicate_results": {
                predicate.contract_id: {
                    **predicate_value,
                    "evidence_sha256": digest,
                    "evidence_location": "/predicate",
                }
            },
            "analysis_implementation_bundle_results": {
                bundle.contract_id: {
                    **bundle_values[bundle.contract_id],
                    "evidence_sha256": digest,
                    "evidence_location": f"/bundles/{bundle.contract_id}",
                }
                for bundle in bundles
            },
            "computation_route_separation_results": {
                contract.contract_id: {
                    **route_value,
                    "evidence_sha256": digest,
                    "evidence_location": "/route",
                }
            },
        },
    )
    return path, digest, gate


def test_route_contract_roundtrips_changes_commitment_template_and_schema(tmp_path):
    service, draft, contract, _, _ = _prepared_route_protocol(tmp_path)
    baseline = replace(draft, computation_route_separation_contracts=[])
    frozen = service.freeze_protocol(draft.protocol_id)
    restored = ExperimentProtocol.from_dict(frozen.to_dict())
    assert restored.computation_route_separation_contracts == [contract]
    assert protocol_commitment(frozen) != protocol_commitment(baseline)

    template = service.run_record_template(frozen.protocol_id)
    assert template["computation_route_separation_plan"] == [contract.to_dict()]
    result = template["record"]["quality_gates"][0]["details"][
        "computation_route_separation_results"
    ][contract.contract_id]
    assert result["observed_route_ids"] == []
    assert result["comparison_satisfied"] is None

    payload = draft.to_dict()
    spec = {
        field.name: payload[field.name]
        for field in fields(CreateProtocol)
        if field.name in payload
    }
    schema_path = Path(__file__).parents[1] / "schemas" / "protocol-command.schema.json"
    jsonschema.validate(spec, json.loads(schema_path.read_text()))
    parsed = _protocol_command(spec)
    assert parsed.computation_route_separation_contracts == [contract]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"route_ids": ["route-a"]}, "exactly two distinct route IDs"),
        (
            {"implementation_bundle_contract_ids": ["bundle-route-a"]},
            "exactly two distinct implementation bundle",
        ),
        ({"approved_shared_input_object_ids": []}, "at least one approved shared"),
        ({"approved_shared_member_locators": []}, "exactly equal"),
        ({"forbidden_cross_route_dependency_edges": []}, "exactly cover"),
        ({"comparison_domain": "Wrong domain"}, "must match"),
        ({"comparison_comparator": "approximately"}, "unsupported"),
        ({"comparison_tolerance": float("nan")}, "finite and nonnegative"),
        ({"static_separation_method": "manual_claim"}, "unsupported"),
        ({"runtime_separation_method": "manual_claim"}, "unsupported"),
        ({"separation_limitations": []}, "declare limitations"),
        ({"adverse_shared_helper_control_id": "missing"}, "exact adverse"),
    ],
)
def test_route_contract_rejects_ambiguous_or_incomplete_freezes(
    tmp_path, mutation, message
):
    _, draft, contract, _, _ = _prepared_route_protocol(tmp_path)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(
            draft,
            computation_route_separation_contracts=[
                replace(contract, **mutation)
            ],
        ))


def _fixture_member(path, locator, role):
    return AnalysisImplementationMember(
        locator=locator,
        role=role,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size,
    )


def test_hidden_shared_solver_passes_each_bundle_but_route_contract_rejects(tmp_path):
    _, draft, contract, _, bundles = _prepared_route_protocol(tmp_path)
    fixture_root = Path(__file__).parent / "fixtures" / "computation_routes"
    imported_by_route = {}
    for route_name in ("route_a", "route_b"):
        tree = ast.parse((fixture_root / f"{route_name}.py").read_text())
        imported_by_route[route_name] = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
    assert "shared_solver" in imported_by_route["route_a"]
    assert "shared_solver" in imported_by_route["route_b"]

    shared_fixture = _fixture_member(
        fixture_root / "shared_fixture.py",
        "analysis/shared_fixture.py",
        "approved shared input fixture",
    )
    hidden_solver = _fixture_member(
        fixture_root / "shared_solver.py",
        "analysis/shared_solver.py",
        "undeclared shared solver",
    )
    hidden_bundles = []
    for original, route_name in zip(bundles, ("route_a", "route_b")):
        route_member = _fixture_member(
            fixture_root / f"{route_name}.py",
            f"analysis/{route_name}.py",
            f"{route_name} entrypoint",
        )
        members = sorted(
            [route_member, shared_fixture, hidden_solver],
            key=lambda member: member.locator,
        )
        hidden_bundles.append(replace(
            original,
            entrypoint_locators=[route_member.locator],
            members=members,
            bundle_sha256=analysis_implementation_bundle_sha256(members),
        ))
    bundle_only = replace(
        draft,
        analysis_implementation_bundle_contracts=hidden_bundles,
        computation_route_separation_contracts=[],
    )
    validate_analysis_implementation_bundle_contracts(bundle_only)

    hidden_contract = replace(
        contract,
        implementation_bundle_contract_ids=[
            bundle.contract_id for bundle in hidden_bundles
        ],
    )
    with pytest.raises(ValidationError, match="exactly equal.*shared member surface"):
        validate_protocol_freeze(replace(
            draft,
            analysis_implementation_bundle_contracts=hidden_bundles,
            computation_route_separation_contracts=[hidden_contract],
        ))


def test_approved_shared_member_requires_identical_bytes_in_both_bundles(tmp_path):
    _, draft, contract, _, bundles = _prepared_route_protocol(tmp_path)
    changed_members = [
        replace(member, sha256="c" * 64)
        if member.locator == "analysis/shared_fixture.py"
        else member
        for member in bundles[1].members
    ]
    changed_bundle = replace(
        bundles[1],
        members=changed_members,
        bundle_sha256=analysis_implementation_bundle_sha256(changed_members),
    )
    changed_bundles = [bundles[0], changed_bundle]
    validate_analysis_implementation_bundle_contracts(replace(
        draft,
        analysis_implementation_bundle_contracts=changed_bundles,
        computation_route_separation_contracts=[],
    ))
    with pytest.raises(ValidationError, match="identical byte hashes and sizes"):
        validate_protocol_freeze(replace(
            draft,
            analysis_implementation_bundle_contracts=changed_bundles,
            computation_route_separation_contracts=[contract],
        ))


def test_run_and_replication_replay_route_separation_receipt(tmp_path):
    service, draft, contract, predicate, bundles = _prepared_route_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    path, digest, gate = _output_and_gate(
        tmp_path, contract, predicate, bundles
    )
    artifacts = [
        DatasetArtifact(path.name, digest, path.stat().st_size, "application/json")
    ]
    passed = service.record_run(run_command(
        frozen.protocol_id,
        QualityGateStatus.PASSED,
        synthetic=True,
        artifact_root=str(tmp_path),
        output_artifacts=artifacts,
        quality_gates=[gate],
    ))
    assert passed.status is RunStatus.COMPLETED
    retained = passed.quality_gates[0].details[
        "computation_route_separation_results"
    ][contract.contract_id]
    assert retained["selected_value_sha256"]
    synthesis = service.build_synthesis()["content"]
    assert "Computation route separation" in synthesis
    assert "does not establish independent reasoning" in synthesis

    contradicted_details = json.loads(json.dumps(passed.quality_gates[0].details))
    contradicted_result = contradicted_details[
        "computation_route_separation_results"
    ][contract.contract_id]
    contradicted_result["observed_static_shared_member_locators"].append(
        "analysis/shared_solver.py"
    )
    contradicted_result["static_separation_satisfied"] = False
    contradicted_result[
        "assessment_status"
    ] = "contradicted_route_separation_contract"
    contradicted_run = replace(
        passed,
        run_id="synthetic-contradicted-route",
        status=RunStatus.INVALID,
        quality_gates=[replace(
            passed.quality_gates[0],
            status=QualityGateStatus.FAILED,
            details=contradicted_details,
        )],
    )
    audit = audit_research_state(
        inquiry=service.repository.load_inquiry("formal"),
        questions=service.repository.load_questions("formal"),
        claims=service.repository.load_claims("formal"),
        hypotheses=service.repository.list_hypotheses("formal"),
        evidence=[],
        datasets=[],
        protocols=[frozen],
        runs=[contradicted_run],
    )
    assert "COMPUTATION_ROUTE_SEPARATION_CONTRADICTED" in {
        finding.code for finding in audit.findings
    }

    package = tmp_path / "package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])
    packaged_protocol = json.loads((package / "protocol.json").read_text())
    edge = packaged_protocol["computation_route_separation_contracts"][0][
        "forbidden_cross_route_dependency_edges"
    ][0]
    assert edge["dependency_member_locator"] == "analysis/route_b.py"

    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    result = runs[0]["quality_gates"][0]["details"][
        "computation_route_separation_results"
    ][contract.contract_id]
    result["observed_runtime_shared_member_locators"].append(
        "analysis/shared_solver.py"
    )
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")
    with pytest.raises(ValidationError, match="runtime_separation_satisfied"):
        verify_replication_package(package, commitment)


def test_output_disagreement_is_not_mislabeled_as_execution_failure(tmp_path):
    _, draft, contract, predicate, bundles = _prepared_route_protocol(tmp_path)
    path, digest, gate = _output_and_gate(
        tmp_path,
        contract,
        predicate,
        bundles,
        observed_comparison_value=0.25,
        comparison_satisfied=False,
    )
    assert path.exists()
    validate_computation_route_separation_gate_metadata(
        protocol=draft,
        gate=gate,
        output_hashes={digest},
    )


def test_passed_route_gate_rejects_hidden_shared_runtime_helper(tmp_path):
    _, draft, contract, predicate, bundles = _prepared_route_protocol(tmp_path)
    _, digest, gate = _output_and_gate(
        tmp_path,
        contract,
        predicate,
        bundles,
        observed_runtime_shared_member_locators=[
            "analysis/shared_fixture.py",
            "analysis/shared_solver.py",
        ],
    )
    with pytest.raises(ValidationError, match="runtime_separation_satisfied"):
        validate_computation_route_separation_gate_metadata(
            protocol=draft,
            gate=gate,
            output_hashes={digest},
        )


def test_passed_route_gate_rejects_forbidden_runtime_edge(tmp_path):
    _, draft, contract, predicate, bundles = _prepared_route_protocol(tmp_path)
    _, digest, gate = _output_and_gate(
        tmp_path,
        contract,
        predicate,
        bundles,
        observed_runtime_dependency_edges=[
            contract.forbidden_cross_route_dependency_edges[0].to_dict()
        ],
    )
    with pytest.raises(ValidationError, match="runtime_separation_satisfied"):
        validate_computation_route_separation_gate_metadata(
            protocol=draft,
            gate=gate,
            output_hashes={digest},
        )


def test_failed_route_gate_preserves_hidden_shared_helper_contradiction(tmp_path):
    _, draft, contract, predicate, bundles = _prepared_route_protocol(tmp_path)
    _, digest, passed_gate = _output_and_gate(
        tmp_path,
        contract,
        predicate,
        bundles,
        observed_runtime_shared_member_locators=[
            "analysis/shared_fixture.py",
            "analysis/shared_solver.py",
        ],
        runtime_separation_satisfied=False,
        assessment_status="contradicted_route_separation_contract",
    )
    failed_gate = replace(passed_gate, status=QualityGateStatus.FAILED)
    validate_computation_route_separation_gate_metadata(
        protocol=draft,
        gate=failed_gate,
        output_hashes={digest},
    )


def test_route_gate_recomputes_comparison_decision(tmp_path):
    _, draft, contract, predicate, bundles = _prepared_route_protocol(tmp_path)
    _, digest, gate = _output_and_gate(
        tmp_path,
        contract,
        predicate,
        bundles,
        observed_comparison_value=0.25,
        comparison_satisfied=True,
    )
    with pytest.raises(ValidationError, match="comparison_satisfied"):
        validate_computation_route_separation_gate_metadata(
            protocol=draft,
            gate=gate,
            output_hashes={digest},
        )
