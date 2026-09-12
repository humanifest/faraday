from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from research_machine.application.commands import CreateProtocol
from research_machine.application.policies import (
    analysis_implementation_bundle_sha256,
    validate_protocol_freeze,
)
from research_machine.application.protocol_integrity import protocol_commitment
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisImplementationBundleContract,
    AnalysisImplementationMember,
    ControlDefinition,
    DatasetArtifact,
    ExperimentProtocol,
    QualityGateResult,
    QualityGateStatus,
    RunStatus,
)
from research_machine.interfaces.cli import _protocol_command
from research_machine.replication.package import verify_replication_package
from test_execution import frozen_formal_protocol, prepared_service, run_command
from test_replication_package import _refresh_packaged_file


def _prepared_bundle_protocol(tmp_path):
    service, hypothesis = prepared_service(tmp_path / "workspace")
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    omission = ControlDefinition(
        control_id="omitted-helper-control",
        registered_control="Omit an imported helper from the declared member set",
        family="adversarial",
        purpose="Reject self-consistent but incomplete implementation manifests.",
        expected_behavior="Observed closure contains the omitted helper and rejects the manifest.",
        evaluation_gate_id="proof-check",
    )
    members = [
        AnalysisImplementationMember(
            locator="analysis/helper.py",
            role="imported helper",
            sha256="1" * 64,
            size_bytes=17,
        ),
        AnalysisImplementationMember(
            locator="analysis/main.py",
            role="registered entrypoint",
            sha256="2" * 64,
            size_bytes=29,
        ),
    ]
    contract = AnalysisImplementationBundleContract(
        contract_id="formal-analysis-code-surface",
        analysis_code_hash=base.analysis_code_hash,
        entrypoint_locators=["analysis/main.py"],
        members=members,
        bundle_sha256=analysis_implementation_bundle_sha256(members),
        closure_method="static_plus_runtime_trace",
        closure_specification_sha256="3" * 64,
        closure_limitations=[
            "The runtime trace covers only the frozen adverse and primary paths."
        ],
        allowed_external_dependency_ids=["python-standard-library"],
        external_dependency_specification_sha256="4" * 64,
        observed_member_receipt_specification_sha256="5" * 64,
        adverse_omission_control_id=omission.control_id,
        evaluation_gate_id="proof-check",
    )
    draft = service.create_protocol(CreateProtocol(**{
        **values,
        "controls": [omission.registered_control],
        "control_definitions": [omission],
        "analysis_implementation_bundle_contracts": [contract],
    }))
    return service, draft, contract, omission


def _bundle_evidence(contract):
    return {
        "analysis_code_hash": contract.analysis_code_hash,
        "entrypoint_locators": list(contract.entrypoint_locators),
        "members": [member.to_dict() for member in contract.members],
        "bundle_sha256": contract.bundle_sha256,
        "closure_method": contract.closure_method,
        "closure_specification_sha256": contract.closure_specification_sha256,
        "closure_limitations": list(contract.closure_limitations),
        "allowed_external_dependency_ids": list(
            contract.allowed_external_dependency_ids
        ),
        "external_dependency_specification_sha256": (
            contract.external_dependency_specification_sha256
        ),
        "observed_member_receipt_specification_sha256": (
            contract.observed_member_receipt_specification_sha256
        ),
        "observed_entrypoint_locators": list(contract.entrypoint_locators),
        "observed_member_locators": [
            member.locator for member in contract.members
        ],
        "observed_member_sha256s": {
            member.locator: member.sha256 for member in contract.members
        },
        "observed_bundle_sha256": contract.bundle_sha256,
        "observed_closure_method": contract.closure_method,
        "observed_external_dependency_ids": list(
            contract.allowed_external_dependency_ids
        ),
        "observed_closure_complete": True,
        "assessment_status": "consistent_with_implementation_bundle_contract",
        "observed_witness": "Static and runtime member sets matched the frozen manifest.",
        "interpretation": "Byte and declared closure match only; semantic correctness is not inferred.",
    }


def _output(tmp_path, contract):
    value = {
        "control": {
            "observed_behavior": "Removing helper.py caused exact member-set disagreement.",
            "interpretation": "The omitted-helper adverse case was rejected.",
            "matches_expected": True,
        },
        "bundle": _bundle_evidence(contract),
    }
    path = tmp_path / "implementation-bundle-output.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), value


def _gate(contract, digest, value, *, result_mutation=None):
    result = {
        **value["bundle"],
        "evidence_sha256": digest,
        "evidence_location": "/bundle",
    }
    if result_mutation:
        result.update(result_mutation)
    return QualityGateResult(
        "proof-check",
        QualityGateStatus.PASSED,
        "Synthetic analysis implementation bundle check.",
        details={
            "evidence_sha256": digest,
            "control_results": {
                "omitted-helper-control": {
                    **value["control"],
                    "evidence_sha256": digest,
                    "evidence_location": "/control",
                }
            },
            "analysis_implementation_bundle_results": {
                contract.contract_id: result,
            },
        },
    )


def test_bundle_contract_roundtrips_changes_commitment_template_and_schema(tmp_path):
    service, draft, contract, _ = _prepared_bundle_protocol(tmp_path)
    baseline = replace(draft, analysis_implementation_bundle_contracts=[])
    frozen = service.freeze_protocol(draft.protocol_id)
    restored = ExperimentProtocol.from_dict(frozen.to_dict())
    assert restored.analysis_implementation_bundle_contracts == [contract]
    assert protocol_commitment(frozen) != protocol_commitment(baseline)

    template = service.run_record_template(frozen.protocol_id)
    assert template["analysis_implementation_bundle_plan"] == [contract.to_dict()]
    result = template["record"]["quality_gates"][0]["details"][
        "analysis_implementation_bundle_results"
    ][contract.contract_id]
    assert result["observed_member_locators"] == []
    assert result["observed_closure_complete"] is None

    payload = draft.to_dict()
    spec = {
        field.name: payload[field.name]
        for field in fields(CreateProtocol)
        if field.name in payload
    }
    schema_path = Path(__file__).parents[1] / "schemas" / "protocol-command.schema.json"
    jsonschema.validate(spec, json.loads(schema_path.read_text()))
    parsed = _protocol_command(spec)
    assert parsed.analysis_implementation_bundle_contracts == [contract]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"analysis_code_hash": "f" * 64}, "protocol analysis_code_hash"),
        ({"entrypoint_locators": ["analysis/missing.py"]}, "entrypoints must be exact"),
        ({"members": []}, "at least one member"),
        ({"closure_method": "manual_claim"}, "closure_method is unsupported"),
        ({"closure_limitations": []}, "declare closure limitations"),
        ({"bundle_sha256": "f" * 64}, "does not match its complete frozen"),
        ({"adverse_omission_control_id": "missing"}, "exact adverse omission"),
    ],
)
def test_bundle_contract_rejects_ambiguous_or_incomplete_freezes(
    tmp_path, mutation, message
):
    _, draft, contract, _ = _prepared_bundle_protocol(tmp_path)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(
            draft,
            analysis_implementation_bundle_contracts=[
                replace(contract, **mutation)
            ],
        ))


def test_run_and_replication_reject_incomplete_observed_member_set(tmp_path):
    service, draft, contract, _ = _prepared_bundle_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    path, digest, value = _output(tmp_path, contract)
    artifacts = [
        DatasetArtifact(path.name, digest, path.stat().st_size, "application/json")
    ]
    incomplete = {
        "observed_member_locators": ["analysis/main.py"],
    }
    with pytest.raises(ValidationError, match="observed member set"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=artifacts,
            quality_gates=[_gate(
                contract, digest, value, result_mutation=incomplete
            )],
        ))

    passed = service.record_run(run_command(
        frozen.protocol_id,
        QualityGateStatus.PASSED,
        synthetic=True,
        artifact_root=str(tmp_path),
        output_artifacts=artifacts,
        quality_gates=[_gate(contract, digest, value)],
    ))
    assert passed.status is RunStatus.COMPLETED
    retained = passed.quality_gates[0].details[
        "analysis_implementation_bundle_results"
    ][contract.contract_id]
    assert retained["selected_value_sha256"]
    synthesis = service.build_synthesis()["content"]
    assert "Analysis implementation bundles" in synthesis
    assert contract.contract_id in synthesis

    package = tmp_path / "package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])
    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    result = runs[0]["quality_gates"][0]["details"][
        "analysis_implementation_bundle_results"
    ][contract.contract_id]
    result["observed_member_locators"] = ["analysis/main.py"]
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")
    with pytest.raises(ValidationError, match="observed member set"):
        verify_replication_package(package, commitment)


def test_omitted_helper_can_evade_a_submitter_defined_scalar_manifest():
    main = AnalysisImplementationMember(
        "analysis/main.py", "entrypoint", "a" * 64, 10
    )
    helper = AnalysisImplementationMember(
        "analysis/helper.py", "helper", "b" * 64, 10
    )
    declared_only = analysis_implementation_bundle_sha256([main])
    changed_helper = replace(helper, sha256="c" * 64)

    assert analysis_implementation_bundle_sha256([main]) == declared_only
    assert analysis_implementation_bundle_sha256([helper, main]) != (
        analysis_implementation_bundle_sha256([changed_helper, main])
    )
