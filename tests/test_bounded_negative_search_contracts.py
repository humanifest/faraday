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
    BoundedNegativeSearchContract,
    BoundedSearchInterface,
    BoundedSearchQuery,
    ControlDefinition,
    DatasetArtifact,
    ExperimentProtocol,
    QualityGateResult,
    QualityGateStatus,
    RunStatus,
    ScreenedSearchCandidate,
)
from research_machine.interfaces.cli import _protocol_command
from research_machine.replication.package import verify_replication_package
from test_execution import frozen_formal_protocol, prepared_service, run_command
from test_replication_package import _refresh_packaged_file


_UNSUPPORTED = [
    "universal_absence",
    "mathematical_impossibility",
    "theorem_or_proof",
    "absence_outside_frozen_interfaces_queries_date_and_stop_rule",
]


def _prepared_search_protocol(tmp_path):
    service, hypothesis = prepared_service(tmp_path / "workspace")
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    omission = ControlDefinition(
        control_id="truncated-screening-record-control",
        registered_control="Remove the last screened candidate from a copied record",
        family="adversarial",
        purpose="Reject a plausible but truncated bounded-search record.",
        expected_behavior="Exact candidate coverage disagrees and the copied record is rejected.",
        evaluation_gate_id="proof-check",
    )
    interface = BoundedSearchInterface(
        interface_id="catalog-api-v1",
        database_name="Synthetic fixture catalog",
        interface_name="Deterministic fixture API",
        interface_version="v1 snapshot",
    )
    queries = [
        BoundedSearchQuery(
            query_id="query-1",
            interface_id=interface.interface_id,
            exact_query='title:"bounded widget" AND type:method',
        ),
        BoundedSearchQuery(
            query_id="query-2",
            interface_id=interface.interface_id,
            exact_query='abstract:"complete widget mapping"',
        ),
    ]
    candidates = [
        ScreenedSearchCandidate(
            candidate_id="candidate-context",
            source_id="fixture:record-17",
            query_ids=["query-1"],
            screening_decision="retained_context",
            retained_source_sha256="1" * 64,
        ),
        ScreenedSearchCandidate(
            candidate_id="candidate-excluded",
            source_id="fixture:record-23",
            query_ids=["query-1", "query-2"],
            screening_decision="excluded",
            exclusion_reason="The record describes hardware, not the registered mapping.",
        ),
    ]
    contract = BoundedNegativeSearchContract(
        contract_id="bounded-widget-method-search",
        search_question="Does the frozen catalog expose the registered complete widget mapping?",
        scope_inclusions=[
            "Records must define every input and output of the complete widget mapping."
        ],
        scope_exclusions=["Records that describe hardware without the mapping."],
        search_date="2026-09-12",
        interfaces=[interface],
        queries=queries,
        stop_rule=(
            "Execute both ordered queries once against the frozen interface and "
            "screen every returned unique source, stopping at 10 candidates."
        ),
        maximum_queries_to_execute=2,
        maximum_candidates_to_screen=10,
        screened_candidates=candidates,
        conclusion_ceiling="bounded_retrieval_record_only",
        higher_level_conclusions_unsupported=list(_UNSUPPORTED),
        adverse_omission_control_id=omission.control_id,
        evaluation_gate_id="proof-check",
    )
    draft = service.create_protocol(CreateProtocol(**{
        **values,
        "controls": [omission.registered_control],
        "control_definitions": [omission],
        "bounded_negative_search_contracts": [contract],
    }))
    return service, draft, contract


def _search_evidence(contract):
    return {
        "search_question": contract.search_question,
        "scope_inclusions": list(contract.scope_inclusions),
        "scope_exclusions": list(contract.scope_exclusions),
        "search_date": contract.search_date,
        "interfaces": [item.to_dict() for item in contract.interfaces],
        "queries": [item.to_dict() for item in contract.queries],
        "stop_rule": contract.stop_rule,
        "maximum_queries_to_execute": contract.maximum_queries_to_execute,
        "maximum_candidates_to_screen": contract.maximum_candidates_to_screen,
        "screened_candidates": [
            item.to_dict() for item in contract.screened_candidates
        ],
        "conclusion_ceiling": contract.conclusion_ceiling,
        "higher_level_conclusions_unsupported": list(
            contract.higher_level_conclusions_unsupported
        ),
        "observed_query_ids": [item.query_id for item in contract.queries],
        "observed_interface_ids": [
            item.interface_id for item in contract.interfaces
        ],
        "observed_screened_candidate_ids": [
            item.candidate_id for item in contract.screened_candidates
        ],
        "observed_retained_source_sha256s": {
            item.candidate_id: item.retained_source_sha256
            for item in contract.screened_candidates
            if item.screening_decision != "excluded"
        },
        "observed_exclusion_reasons": {
            item.candidate_id: item.exclusion_reason
            for item in contract.screened_candidates
            if item.screening_decision == "excluded"
        },
        "observed_stop_rule_satisfied": True,
        "observed_search_record_complete": True,
        "assessment_status": "consistent_with_bounded_search_contract",
        "observed_witness": (
            "Both exact queries and both candidate screening records were retained."
        ),
        "interpretation": (
            "No in-scope target was classified within the frozen bounds; this is "
            "not evidence of universal absence or impossibility."
        ),
    }


def _output(tmp_path, contract):
    value = {
        "control": {
            "observed_behavior": (
                "Removing candidate-excluded caused exact candidate-set disagreement."
            ),
            "interpretation": "The truncated fixture record was rejected.",
            "matches_expected": True,
        },
        "search": _search_evidence(contract),
    }
    path = tmp_path / "bounded-search-output.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), value


def _gate(contract, digest, value, *, result_mutation=None, control_match=True):
    result = {
        **value["search"],
        "evidence_sha256": digest,
        "evidence_location": "/search",
    }
    if result_mutation:
        result.update(result_mutation)
    return QualityGateResult(
        "proof-check",
        QualityGateStatus.PASSED,
        "Synthetic bounded negative-search record check.",
        details={
            "evidence_sha256": digest,
            "control_results": {
                contract.adverse_omission_control_id: {
                    **value["control"],
                    "matches_expected": control_match,
                    "evidence_sha256": digest,
                    "evidence_location": "/control",
                }
            },
            "bounded_negative_search_results": {contract.contract_id: result},
        },
    )


def test_bounded_search_roundtrips_changes_commitment_template_and_schema(tmp_path):
    service, draft, contract = _prepared_search_protocol(tmp_path)
    baseline = replace(draft, bounded_negative_search_contracts=[])
    frozen = service.freeze_protocol(draft.protocol_id)
    restored = ExperimentProtocol.from_dict(frozen.to_dict())
    assert restored.bounded_negative_search_contracts == [contract]
    assert protocol_commitment(frozen) != protocol_commitment(baseline)

    template = service.run_record_template(frozen.protocol_id)
    assert template["bounded_negative_search_plan"] == [contract.to_dict()]
    result = template["record"]["quality_gates"][0]["details"][
        "bounded_negative_search_results"
    ][contract.contract_id]
    assert result["observed_screened_candidate_ids"] == []
    assert result["observed_search_record_complete"] is None

    payload = draft.to_dict()
    spec = {
        field.name: payload[field.name]
        for field in fields(CreateProtocol)
        if field.name in payload
    }
    schema_path = Path(__file__).parents[1] / "schemas" / "protocol-command.schema.json"
    jsonschema.validate(spec, json.loads(schema_path.read_text()))
    parsed = _protocol_command(spec)
    assert parsed.bounded_negative_search_contracts == [contract]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"search_date": "2026-02-30"}, "exact YYYY-MM-DD"),
        ({"scope_inclusions": []}, "at least one scope inclusion"),
        ({"maximum_queries_to_execute": 1}, "queries exceed"),
        ({"conclusion_ceiling": "theorem"}, "must remain"),
        ({"higher_level_conclusions_unsupported": []}, "explicitly reject"),
        ({"adverse_omission_control_id": "missing"}, "exact adverse omission"),
    ],
)
def test_bounded_search_rejects_ambiguous_or_unbounded_freezes(
    tmp_path, mutation, message
):
    _, draft, contract = _prepared_search_protocol(tmp_path)
    with pytest.raises(ValidationError, match=message):
        validate_protocol_freeze(replace(
            draft,
            bounded_negative_search_contracts=[replace(contract, **mutation)],
        ))


def test_screening_decisions_require_hashes_or_exclusion_reasons(tmp_path):
    _, draft, contract = _prepared_search_protocol(tmp_path)
    retained = contract.screened_candidates[0]
    excluded = contract.screened_candidates[1]
    with pytest.raises(ValidationError, match="retained_source_sha256"):
        validate_protocol_freeze(replace(
            draft,
            bounded_negative_search_contracts=[replace(
                contract,
                screened_candidates=[
                    replace(retained, retained_source_sha256=""), excluded
                ],
            )],
        ))
    with pytest.raises(ValidationError, match="exclusion_reason"):
        validate_protocol_freeze(replace(
            draft,
            bounded_negative_search_contracts=[replace(
                contract,
                screened_candidates=[retained, replace(excluded, exclusion_reason="")],
            )],
        ))


def test_run_and_replication_reject_truncated_screening_record(tmp_path):
    service, draft, contract = _prepared_search_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    path, digest, value = _output(tmp_path, contract)
    artifacts = [
        DatasetArtifact(path.name, digest, path.stat().st_size, "application/json")
    ]
    truncated = {"observed_screened_candidate_ids": ["candidate-context"]}
    with pytest.raises(ValidationError, match="observed candidate set"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=artifacts,
            quality_gates=[_gate(
                contract, digest, value, result_mutation=truncated
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
        "bounded_negative_search_results"
    ][contract.contract_id]
    assert retained["selected_value_sha256"]
    synthesis = service.build_synthesis()["content"]
    assert "Bounded negative searches" in synthesis
    assert "not a theorem" in synthesis

    package = tmp_path / "package"
    exported = service.export_replication_package(frozen.protocol_id, str(package))
    verify_replication_package(package, exported["package_manifest_sha256"])
    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    result = runs[0]["quality_gates"][0]["details"][
        "bounded_negative_search_results"
    ][contract.contract_id]
    result["observed_screened_candidate_ids"] = ["candidate-context"]
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")
    with pytest.raises(ValidationError, match="observed candidate set"):
        verify_replication_package(package, commitment)


def test_run_rejects_changed_retained_hash_and_failed_adverse_control(tmp_path):
    service, draft, contract = _prepared_search_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    path, digest, value = _output(tmp_path, contract)
    artifacts = [
        DatasetArtifact(path.name, digest, path.stat().st_size, "application/json")
    ]
    with pytest.raises(ValidationError, match="retained-source hashes"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=artifacts,
            quality_gates=[_gate(
                contract,
                digest,
                value,
                result_mutation={
                    "observed_retained_source_sha256s": {
                        "candidate-context": "f" * 64
                    }
                },
            )],
        ))
    with pytest.raises(ValidationError, match="omission/truncation control"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=artifacts,
            quality_gates=[_gate(
                contract, digest, value, control_match=False
            )],
        ))


def test_artifact_selected_search_json_must_match_submitted_result(tmp_path):
    service, draft, contract = _prepared_search_protocol(tmp_path)
    frozen = service.freeze_protocol(draft.protocol_id)
    path, digest, value = _output(tmp_path, contract)
    artifacts = [
        DatasetArtifact(path.name, digest, path.stat().st_size, "application/json")
    ]
    with pytest.raises(ValidationError, match="retained typed JSON evidence"):
        service.record_run(run_command(
            frozen.protocol_id,
            QualityGateStatus.PASSED,
            synthetic=True,
            artifact_root=str(tmp_path),
            output_artifacts=artifacts,
            quality_gates=[_gate(
                contract,
                digest,
                value,
                result_mutation={"observed_witness": "A rewritten witness."},
            )],
        ))
