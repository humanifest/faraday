from dataclasses import fields
import hashlib
import json

import pytest

from research_machine.application.commands import CreateProtocol, RecordEvidence
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    MeasurementDefinition,
    MeasurementRole,
    MeasurementValidityCheck,
    DatasetArtifact,
    EvidenceDirection,
    QualityGateResult,
    QualityGateStatus,
    ValidationTag,
)
from test_execution import frozen_formal_protocol, prepared_service, run_command


def _frozen_validity_protocol(tmp_path):
    service, hypothesis = prepared_service(tmp_path)
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    measurements = [
        MeasurementDefinition(
            measurement_id="primary-measurement",
            role=MeasurementRole.PRIMARY,
            registered_target=base.primary_outcome,
            observable="Registered checker acceptance score",
            input_condition="The frozen proof object",
            parameter_values={"checker": "registered version"},
            evaluation_point="After complete proof replay",
            convention="One denotes acceptance and zero rejection",
            aggregation="One result per proof object",
            tolerance="Exact checker output parsing",
            expected_behavior="Report acceptance or rejection without omission",
            data_column="acceptance",
            temporal_role="not_applicable",
            scale_type="binary",
            unit="acceptance indicator",
            admissible_values=["0", "1"],
            missing_value_codes=["<blank>"],
        ),
        MeasurementDefinition(
            measurement_id="control-measurement",
            role=MeasurementRole.CONTROL,
            registered_target=base.controls[0],
            observable="Invalid-proof checker transcript",
            input_condition="The registered invalid proof",
            parameter_values={"checker": "registered version"},
            evaluation_point="During control replay",
            convention="Retain the exact rejection transcript",
            aggregation="One transcript",
            tolerance="Exact transcript retention",
            expected_behavior="The invalid proof is rejected",
        ),
    ]
    check = MeasurementValidityCheck(
        check_id="checker-reference-agreement",
        measurement_id="primary-measurement",
        evidence_type="criterion",
        validity_claim="The acceptance measurement agrees with the independent checker transcript.",
        assessment_plan="Compare the parsed indicator with the retained transcript.",
        acceptance_criterion="The indicator and transcript agree exactly.",
        failure_response="Stop interpretation and repair the parser.",
        assessment_gate_id="measurement-validity-assessed",
    )
    draft = service.create_protocol(CreateProtocol(**{
        **values,
        "measurement_definitions": measurements,
        "measurement_validity_checks": [check],
        "quality_requirements": ["proof-check", "measurement-validity-assessed"],
    }))
    return service, service.freeze_protocol(draft.protocol_id), check


def _gates(check, *, gate_status=QualityGateStatus.PASSED, include_result=True):
    details = {"evidence_sha256": "c" * 64}
    if include_result:
        details["measurement_validity_results"] = {
            check.check_id: {
                "observed_diagnostic": "Parsed indicator and transcript agreed in the synthetic fixture.",
                "interpretation": "No fixture contradiction to the frozen validity claim was observed.",
                "assessment_status": (
                    "consistent_with_validity_claim"
                    if gate_status is QualityGateStatus.PASSED else
                    "inconclusive" if gate_status is QualityGateStatus.WARNING else
                    "contradicted_validity_claim"
                ),
                "evidence_type": check.evidence_type,
                "evidence_sha256": "c" * 64,
                "evidence_location": "/validity/checker-reference-agreement",
            }
        }
    return [
        QualityGateResult(
            "proof-check", QualityGateStatus.PASSED, "Synthetic proof check",
            details={"evidence_sha256": "c" * 64},
        ),
        QualityGateResult(
            check.assessment_gate_id, gate_status, "Synthetic validity assessment",
            details=details,
        ),
    ]


def test_run_template_and_intake_require_artifact_bound_validity_result(tmp_path):
    service, protocol, check = _frozen_validity_protocol(tmp_path)
    template = service.run_record_template(protocol.protocol_id)
    gate = next(
        item for item in template["record"]["quality_gates"]
        if item["gate_id"] == check.assessment_gate_id
    )
    result = gate["details"]["measurement_validity_results"][check.check_id]
    assert result["evidence_type"] == "criterion"
    assert "assessment_status" in result
    assert "selected_value_sha256" in result

    with pytest.raises(ValidationError, match="requires exact results"):
        service.record_run(run_command(
            protocol.protocol_id, QualityGateStatus.PASSED,
            quality_gates=_gates(check, include_result=False),
        ))

    contradictory = _gates(check)
    contradictory[1].details["measurement_validity_results"][check.check_id][
        "assessment_status"
    ] = "contradicted_validity_claim"
    with pytest.raises(ValidationError, match="passed measurement validity gate"):
        service.record_run(run_command(
            protocol.protocol_id, QualityGateStatus.PASSED,
            quality_gates=contradictory,
        ))

    output = tmp_path / "validity-output.json"
    output.write_text(
        '{"validity":{"checker-reference-agreement":{"acceptance":1}}}\n',
        encoding="utf-8",
    )
    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    bad_location_gates = _gates(check)
    for gate in bad_location_gates:
        gate.details["evidence_sha256"] = output_sha256
    bad_location_result = bad_location_gates[1].details[
        "measurement_validity_results"
    ][check.check_id]
    bad_location_result["evidence_sha256"] = output_sha256
    bad_location_result["evidence_location"] = "/validity/not-the-frozen-check"
    with pytest.raises(ValidationError, match="does not resolve"):
        service.record_run(run_command(
            protocol.protocol_id, QualityGateStatus.PASSED,
            quality_gates=bad_location_gates,
            artifact_root=str(tmp_path),
            output_artifacts=[DatasetArtifact(
                output.name,
                output_sha256,
                output.stat().st_size,
                "application/json",
            )],
        ))

    eligible_gates = _gates(check)
    for gate in eligible_gates:
        gate.details["evidence_sha256"] = output_sha256
    eligible_gates[1].details["measurement_validity_results"][check.check_id][
        "evidence_sha256"
    ] = output_sha256
    run = service.record_run(run_command(
        protocol.protocol_id, QualityGateStatus.PASSED,
        quality_gates=eligible_gates,
        artifact_root=str(tmp_path),
        output_artifacts=[DatasetArtifact(
            output.name,
            output_sha256,
            output.stat().st_size,
            "application/json",
        )],
    ))
    stored = next(
        item for item in run.quality_gates
        if item.gate_id == check.assessment_gate_id
    )
    assert stored.details["measurement_validity_results"][check.check_id][
        "assessment_status"
    ] == "consistent_with_validity_claim"
    selected_value = {"acceptance": 1}
    selected_value_sha256 = hashlib.sha256(
        (json.dumps(
            selected_value,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        ) + "\n").encode()
    ).hexdigest()
    assert stored.details["measurement_validity_results"][check.check_id][
        "selected_value_sha256"
    ] == selected_value_sha256
    synthesis = service.build_synthesis()["content"]
    assert "Measurement validity provenance" in synthesis
    assert "checker-reference-agreement" in synthesis
    assert "consistent_with_validity_claim" in synthesis
    assert selected_value_sha256 in synthesis
    assert "does not prove construct validity" in synthesis
    evidence = service.record_evidence(RecordEvidence(
        hypothesis_id=protocol.hypotheses_tested[0],
        direction=EvidenceDirection.INCONCLUSIVE,
        summary="Synthetic validity provenance fixture.",
        analysis_id="",
        run_id=run.run_id,
        uncertainty="No scientific inference from this fixture.",
        scope="Synthetic proof-check fixture only.",
        higher_level_conclusions_unsupported=[
            "No empirical, causal, mechanism, or general validity conclusion."
        ],
        validation_tags=[ValidationTag.CALIBRATION],
        exploratory=False,
    ))
    assert evidence.measurement_validity_check_ids == [check.check_id]
    assert check.check_id in service.build_synthesis()["content"]


def test_warning_and_failed_validity_gates_preserve_nonpassing_results(tmp_path):
    service, protocol, check = _frozen_validity_protocol(tmp_path)
    for status, expected in (
        (QualityGateStatus.WARNING, "inconclusive"),
        (QualityGateStatus.FAILED, "contradicted_validity_claim"),
    ):
        run = service.record_run(run_command(
            protocol.protocol_id, status,
            quality_gates=_gates(check, gate_status=status),
        ))
        result = next(
            item for item in run.quality_gates
            if item.gate_id == check.assessment_gate_id
        ).details["measurement_validity_results"][check.check_id]
        assert result["assessment_status"] == expected
        assert run.scientific_evidence_eligible is False
    codes = {item.code for item in service.audit_rigor().findings}
    assert "MEASUREMENT_VALIDITY_INCONCLUSIVE" in codes
    assert "MEASUREMENT_VALIDITY_CONTRADICTED" in codes
    synthesis = service.build_synthesis()["content"]
    assert "inconclusive" in synthesis
    assert "contradicted_validity_claim" in synthesis
