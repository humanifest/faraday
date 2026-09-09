from dataclasses import replace

import pytest

from research_machine.application.policies import (
    validate_evidence_annotations,
    validate_protocol_freeze,
)
from research_machine.application.service import _protocol_commitment
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ControlDefinition,
    EvidenceDirection,
    ExperimentProtocol,
    ValidationTag,
)
from test_ethics_gate import _human_protocol


@pytest.mark.parametrize("kind", ["observational", "experimental"])
def test_empirical_freeze_cannot_omit_structured_controls(kind):
    from research_machine.domain.models import ProtocolKind
    protocol = _human_protocol(human_subjects=False, protocol_kind=ProtocolKind(kind), control_definitions=[])
    with pytest.raises(ValidationError, match="control_definitions"):
        validate_protocol_freeze(protocol)


def test_protocol_schema_and_cli_cover_same_fields():
    import json
    from pathlib import Path
    from research_machine.interfaces.cli import _PROTOCOL_FIELDS
    schema = json.loads((Path(__file__).parents[1] / "schemas/protocol-command.schema.json").read_text())
    assert set(schema["properties"]) == _PROTOCOL_FIELDS


@pytest.mark.parametrize(
    ("passed", "failed", "message"),
    [
        (["Registered negative", " Registered negative "], [], "duplicates"),
        (["Registered negative"], [" Registered negative "], "passed and failed"),
    ],
)
def test_evidence_control_disclosures_are_an_exact_partition(passed, failed, message):
    with pytest.raises(ValidationError, match=message):
        validate_evidence_annotations(
            direction=EvidenceDirection.INCONCLUSIVE,
            scope="Synthetic fixture scope",
            uncertainty="No scientific inference",
            controls_passed=passed,
            controls_failed=failed,
            higher_level_conclusions_unsupported=["No empirical conclusion"],
            validation_tags=[ValidationTag.CALIBRATION],
        )


@pytest.mark.parametrize("invalid", [False, True])
def test_control_definition_cli_registration_and_freeze(tmp_path, capsys, invalid):
    import json
    from dataclasses import fields
    from research_machine.application.commands import CreateProtocol
    from research_machine.interfaces.cli import main
    from test_execution import prepared_service

    service, hypothesis = prepared_service(tmp_path / "workspace")
    protocol = _protocol()
    values = protocol.to_dict()
    spec = {field.name: values[field.name] for field in fields(CreateProtocol)}
    spec["hypotheses_tested"] = [hypothesis]
    if invalid:
        spec["control_definitions"][0]["evaluation_gate_id"] = "unregistered-gate"
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(spec))
    common = ["--workspace", str(tmp_path / "workspace"), "--json", "protocol"]
    assert main([*common, "create", "--spec-file", str(path)]) == 0
    created = json.loads(capsys.readouterr().out)["result"]
    ledger = next((tmp_path / "workspace").rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    status = main([*common, "freeze", created["protocol_id"]])
    captured = capsys.readouterr()
    if invalid:
        assert status == 2
        assert "required protocol quality gate" in captured.err
        assert ledger.read_bytes() == before
    else:
        assert status == 0
        frozen = service.get_protocol(created["protocol_id"])
        assert frozen.control_definitions == protocol.control_definitions
        assert _protocol_commitment(frozen) == frozen.protocol_hash
    assert service.verify_ledger()["valid"]


def _protocol():
    return _human_protocol(human_subjects=False, control_definitions=[ControlDefinition(
        "negative-1", "Control condition", "negative", "Detect background signal",
        "No intervention-associated signal expected", "integrity",
    )])


def test_control_definition_roundtrips_and_changes_commitment():
    protocol = _protocol()
    validate_protocol_freeze(protocol)
    restored = ExperimentProtocol.from_dict(protocol.to_dict())
    assert restored.control_definitions == protocol.control_definitions
    changed = replace(protocol, control_definitions=[replace(protocol.control_definitions[0], family="sham")])
    assert _protocol_commitment(changed) != _protocol_commitment(protocol)


@pytest.mark.parametrize("field", ["control_id", "registered_control"])
def test_control_definition_identity_rejects_duplicate_entries(field):
    protocol = _protocol()
    duplicate = replace(protocol.control_definitions[0])
    if field == "control_id":
        duplicate = replace(
            duplicate,
            control_id=protocol.control_definitions[0].control_id,
            registered_control="Distinct control condition",
        )
        controls = [protocol.controls[0], "Distinct control condition"]
    else:
        duplicate = replace(
            duplicate,
            control_id="distinct-control-id",
            registered_control=protocol.control_definitions[0].registered_control,
        )
        controls = list(protocol.controls)
    with pytest.raises(ValidationError, match="duplicate control definition"):
        validate_protocol_freeze(replace(
            protocol,
            controls=controls,
            control_definitions=[protocol.control_definitions[0], duplicate],
        ))


def test_control_definitions_must_follow_registered_control_order_at_freeze():
    negative = ControlDefinition(
        "negative-1", "Blank sample", "negative", "Detect contamination",
        "No signal should appear", "integrity",
    )
    reference = ControlDefinition(
        "reference-1", "Reference sample", "reference", "Bound sensitivity",
        "Known reference signal should appear", "integrity",
    )
    protocol = _human_protocol(
        human_subjects=False,
        controls=["Blank sample", "Reference sample"],
        control_definitions=[reference, negative],
    )
    with pytest.raises(ValidationError, match="registered controls in order"):
        validate_protocol_freeze(protocol)


@pytest.mark.parametrize(
    "field",
    ["control_id", "registered_control", "evaluation_gate_id"],
)
def test_control_definition_handles_must_be_canonical_at_freeze(field):
    protocol = _protocol()
    control = replace(
        protocol.control_definitions[0],
        **{field: getattr(protocol.control_definitions[0], field) + " "},
    )
    with pytest.raises(ValidationError, match="canonical"):
        validate_protocol_freeze(
            replace(protocol, control_definitions=[control])
        )


@pytest.mark.parametrize(
    "field",
    ["family", "purpose", "expected_behavior"],
)
def test_control_definition_semantics_must_be_canonical_at_freeze(field):
    protocol = _protocol()
    control = replace(
        protocol.control_definitions[0],
        **{field: " " + getattr(protocol.control_definitions[0], field) + " "},
    )
    with pytest.raises(
        ValidationError,
        match=f"control definition {field} must be canonical",
    ):
        validate_protocol_freeze(
            replace(protocol, control_definitions=[control])
        )


def test_registered_control_names_must_be_canonical_at_freeze():
    protocol = _protocol()
    with pytest.raises(ValidationError, match="protocol controls"):
        validate_protocol_freeze(
            replace(protocol, controls=[protocol.controls[0] + " "])
        )


@pytest.mark.parametrize("change", [
    {"family": "unknown"}, {"registered_control": "unregistered"},
    {"evaluation_gate_id": "not-required"}, {"purpose": ""},
])
def test_incomplete_or_unbound_controls_cannot_freeze(change):
    protocol = _protocol()
    protocol = replace(protocol, control_definitions=[replace(protocol.control_definitions[0], **change)])
    with pytest.raises(ValidationError):
        validate_protocol_freeze(protocol)


@pytest.mark.parametrize(
    "case", ["expected", "unexpected", "missing", "unbound", "unlocated", "extra", "failed"]
)
def test_recorded_control_evaluations_require_evidence_not_favorable_results(tmp_path, case):
    from dataclasses import fields
    from research_machine.application.commands import CreateProtocol
    from research_machine.domain.models import QualityGateResult, QualityGateStatus, RunStatus
    from test_execution import prepared_service, frozen_formal_protocol, run_command

    service, hypothesis = prepared_service(tmp_path)
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    control = ControlDefinition("negative-1", base.controls[0], "negative",
        "Detect false acceptance", "Invalid derivation is rejected", "proof-check")
    draft = service.create_protocol(CreateProtocol(**{**values, "control_definitions": [control]}))
    frozen = service.freeze_protocol(draft.protocol_id)
    template_ledger = next(tmp_path.rglob("ledger.jsonl"))
    template_before = template_ledger.read_bytes()
    template = service.run_record_template(frozen.protocol_id)
    assert template["control_plan"] == [control.to_dict()]
    template_gate = template["record"]["quality_gates"][0]
    assert template_gate["status"] == "skipped"
    blank = template_gate["details"]["control_results"][control.control_id]
    assert blank["observed_behavior"] == ""
    assert blank["interpretation"] == ""
    assert blank["matches_expected"] is None
    assert "evidence_location" in blank
    assert template_ledger.read_bytes() == template_before
    evaluation = {"observed_behavior": "Synthetic checker outcome", "interpretation": "Fixture only",
        "matches_expected": case != "unexpected", "evidence_sha256": "d" * 64 if case == "unbound" else "c" * 64,
        "evidence_location": "" if case == "unlocated" else "/controls/negative-1"}
    details = {} if case == "failed" else {"evidence_sha256": "c" * 64}
    if case not in {"missing", "failed"}:
        details["control_results"] = {"negative-1": evaluation}
        if case == "extra":
            details["control_results"]["unregistered-control"] = dict(evaluation)
    gate_status = QualityGateStatus.FAILED if case == "failed" else QualityGateStatus.PASSED
    command = run_command(frozen.protocol_id, gate_status, synthetic=True,
        quality_gates=[QualityGateResult("proof-check", gate_status, "Fixture evaluation", details=details)])
    ledger = next(tmp_path.rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    if case in {"missing", "unbound", "unlocated", "extra"}:
        with pytest.raises(ValidationError, match="control"):
            service.record_run(command)
        assert ledger.read_bytes() == before
    else:
        run = service.record_run(command)
        assert run.synthetic is True
        if case == "failed":
            assert run.status is RunStatus.INVALID
        else:
            assert run.quality_gates[0].details["control_results"]["negative-1"]["matches_expected"] is (case == "expected")
            synthesis = service.build_synthesis()["content"]
            assert "Control evaluation provenance" in synthesis
            assert "`/controls/negative-1`" in synthesis
            expected_disposition = (
                "matched expected behavior" if case == "expected"
                else "did not match expected behavior"
            )
            assert expected_disposition in synthesis
    assert service.verify_ledger()["valid"]


@pytest.mark.parametrize("disclosure", ["omitted", "contradictory", "disclosed"])
def test_evidence_cannot_hide_an_unexpected_control(tmp_path, disclosure):
    from dataclasses import fields
    from research_machine.application.commands import CreateProtocol, RecordEvidence
    from research_machine.domain.models import AnalysisMode, EvidenceDirection, QualityGateResult, QualityGateStatus, ValidationTag
    from test_execution import prepared_service, frozen_formal_protocol, run_command

    service, hypothesis = prepared_service(tmp_path)
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    control = ControlDefinition("negative-1", base.controls[0], "negative", "Detect false acceptance",
                                "Invalid derivation is rejected", "proof-check")
    draft = service.create_protocol(CreateProtocol(**{**values, "analysis_mode": AnalysisMode.EXPLORATORY,
                                                     "control_definitions": [control]}))
    protocol = service.freeze_protocol(draft.protocol_id)
    gate = QualityGateResult("proof-check", QualityGateStatus.PASSED, "Synthetic evaluation",
        details={"evidence_sha256": "c" * 64,
            "control_results": {"negative-1": {"observed_behavior": "Unexpected fixture result",
            "interpretation": "Fixture only; investigation required", "matches_expected": False,
            "evidence_sha256": "c" * 64, "evidence_location": "/controls/negative-1"}}})
    run = service.record_run(run_command(protocol.protocol_id, QualityGateStatus.PASSED,
                                        synthetic=True, quality_gates=[gate]))
    command = RecordEvidence(hypothesis_id=hypothesis, direction=EvidenceDirection.WEAKENS,
        summary="Synthetic plumbing test", run_id=run.run_id, analysis_id="", scope="Fixture only",
        uncertainty="No scientific inference", higher_level_conclusions_unsupported=["No empirical conclusion"],
        validation_tags=[ValidationTag.CALIBRATION], exploratory=True,
        controls_failed=[] if disclosure == "omitted" else [control.registered_control],
        controls_passed=[control.registered_control] if disclosure == "contradictory" else [])
    ledger = next(tmp_path.rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    if disclosure != "disclosed":
        with pytest.raises(ValidationError):
            service.record_evidence(command)
        assert ledger.read_bytes() == before
    else:
        evidence = service.record_evidence(command)
        assert evidence.controls_failed == [control.registered_control]
        assert evidence.scientific_evidence_eligible is False
    assert service.verify_ledger()["valid"]


@pytest.mark.parametrize(
    "passed,failed",
    [([], []), (["Invented control"], []), (["Registered negative", "Registered negative"], [])],
)
def test_evidence_must_exactly_account_for_successful_frozen_controls(
    tmp_path, passed, failed
):
    from dataclasses import fields
    from research_machine.application.commands import CreateProtocol, RecordEvidence
    from research_machine.domain.models import (
        AnalysisMode, EvidenceDirection, QualityGateResult, QualityGateStatus,
        ValidationTag,
    )
    from test_execution import prepared_service, frozen_formal_protocol, run_command

    service, hypothesis = prepared_service(tmp_path)
    base = frozen_formal_protocol(service, hypothesis)
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    control = ControlDefinition(
        "negative-1", "Registered negative", "negative", "Detect false acceptance",
        "Invalid derivation is rejected", "proof-check",
    )
    protocol = service.freeze_protocol(service.create_protocol(CreateProtocol(**{
        **values, "analysis_mode": AnalysisMode.EXPLORATORY,
        "controls": [control.registered_control], "control_definitions": [control],
    })).protocol_id)
    gate = QualityGateResult(
        "proof-check", QualityGateStatus.PASSED, "Synthetic evaluation",
        details={"evidence_sha256": "c" * 64, "control_results": {
            "negative-1": {
                "observed_behavior": "Registered synthetic rejection",
                "interpretation": "Fixture only",
                "matches_expected": True,
                "evidence_sha256": "c" * 64,
                "evidence_location": "/controls/negative-1",
            }
        }},
    )
    run = service.record_run(run_command(
        protocol.protocol_id, QualityGateStatus.PASSED,
        synthetic=True, quality_gates=[gate],
    ))
    command = RecordEvidence(
        hypothesis_id=hypothesis, direction=EvidenceDirection.INCONCLUSIVE,
        summary="Synthetic plumbing test", run_id=run.run_id, analysis_id="",
        scope="Fixture only", uncertainty="No scientific inference",
        higher_level_conclusions_unsupported=["No empirical conclusion"],
        validation_tags=[ValidationTag.CALIBRATION], exploratory=True,
        controls_passed=passed, controls_failed=failed,
    )
    with pytest.raises(ValidationError, match="control"):
        service.record_evidence(command)
    exact = service.record_evidence(RecordEvidence(**{
        **command.__dict__, "controls_passed": [control.registered_control],
    }))
    assert exact.controls_passed == [control.registered_control]
    assert exact.controls_failed == []
    assert service.verify_ledger()["valid"]
