from __future__ import annotations

import pytest
import hashlib
import json

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import CalibrationCriterion
from research_machine.measurement.custody import validate_measurement_custody


def test_registration_rejects_unrelated_receipt_without_writing(tmp_path, capsys):
    # Synthetic artifacts exercise custody binding, not scientific evidence.
    from research_machine.application.commands import CreateProtocol, RegisterDataset
    from research_machine.domain.models import AnalysisMode, CalibrationCriterion, DatasetArtifact, DatasetRole, ProtocolKind
    from test_execution import prepared_service

    service, hypothesis_id = prepared_service(tmp_path)
    draft = service.create_protocol(CreateProtocol(
        experiment_id="custody-binding", title="Custody binding",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis_id], primary_outcome="Result",
        protocol_kind=ProtocolKind.FORMAL, methodology="Synthetic custody fixture",
        quality_requirements=["clock-sync"], controls=["Invalid input"],
        expected_outputs=["Result"], success_conditions=["Report result"],
        environment_requirements=["Fixture"], sample_size_or_stopping_rule="One fixture",
        failure_conditions=["Broken chain"], safety_constraints=["Synthetic only"],
        analysis_code_hash="c" * 64, measurement_custody_requirements=["clock-sync"],
        calibration_acceptance_criteria=[CalibrationCriterion(
            "clock-residual", "clock", "absolute clock residual", "ms",
            "Keep synchronization error below the registered event-resolution limit.",
            upper_bound=1.0,
        )],
    ))
    protocol = service.freeze_protocol(draft.protocol_id)
    ledger = next(tmp_path.rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    template = service.measurement_custody_template(protocol.protocol_id)
    assert template["template_only"] is True
    assert template["would_register_dataset"] is False
    assert template["protocol_hash"] == protocol.protocol_hash
    assert template["frozen_calibration_criteria"] == [
        protocol.calibration_acceptance_criteria[0].to_dict()
    ]
    assert [item["gate_id"] for item in template["receipt"]["quality_gates"]] == ["clock-sync"]
    assert template["receipt"]["quality_gates"][0]["status"] == "skipped"
    assert ledger.read_bytes() == before
    from research_machine.interfaces.cli import main
    import json
    assert main(["--workspace", str(tmp_path), "--json", "measurement", "template",
                 "--protocol", protocol.protocol_id]) == 0
    cli_template = json.loads(capsys.readouterr().out)["result"]
    assert cli_template["protocol_hash"] == protocol.protocol_hash
    assert cli_template["template_only"] is True
    assert ledger.read_bytes() == before
    receipt = _materialize_receipt(tmp_path)
    receipt_file = tmp_path / "custody-receipt.json"
    receipt_file.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    receipt_sha256 = hashlib.sha256(receipt_file.read_bytes()).hexdigest()
    custody_record = tmp_path / "custody-record"
    assert main([
        "--workspace", str(tmp_path), "--json", "measurement", "record",
        "--protocol", protocol.protocol_id,
        "--receipt-file", str(receipt_file),
        "--expected-receipt-sha256", receipt_sha256,
        "--artifact-root", str(tmp_path),
        "--output", str(custody_record),
    ]) == 0
    recorded_result = json.loads(capsys.readouterr().out)["result"]
    assert recorded_result["status"] == "custody_recorded"
    assert recorded_result["scientific_evidence_eligible"] is False
    record = json.loads(
        (custody_record / "measurement-custody-record.json").read_text()
    )
    assert record["protocol_hash"] == protocol.protocol_hash
    assert record["receipt_input"] == {
        "sha256": receipt_sha256,
        "size_bytes": receipt_file.stat().st_size,
    }
    assert record["required_gate_ids"] == ["clock-sync"]
    assert record["artifact_integrity"]["all_artifacts_match"] is True
    assert record["scientific_evidence_eligible"] is False
    assert ledger.read_bytes() == before
    record_file = custody_record / "measurement-custody-record.json"
    assert main([
        "--workspace", str(tmp_path), "--json", "measurement", "verify-record",
        "--protocol", protocol.protocol_id,
        "--record-file", str(record_file),
        "--expected-record-sha256", recorded_result["custody_record_sha256"],
        "--receipt-file", str(receipt_file),
        "--artifact-root", str(tmp_path),
    ]) == 0
    verification = json.loads(capsys.readouterr().out)["result"]
    assert verification["status"] == "custody_record_verified"
    assert verification["protocol_hash"] == protocol.protocol_hash
    assert verification["scientific_evidence_eligible"] is False
    forged = dict(record)
    forged["required_gate_ids"] = ["post-hoc-gate"]
    forged_file = tmp_path / "forged-custody-record.json"
    forged_file.write_text(json.dumps(forged, indent=2, sort_keys=True) + "\n")
    forged_sha256 = hashlib.sha256(forged_file.read_bytes()).hexdigest()
    assert main([
        "--workspace", str(tmp_path), "--json", "measurement", "verify-record",
        "--protocol", protocol.protocol_id,
        "--record-file", str(forged_file),
        "--expected-record-sha256", forged_sha256,
        "--receipt-file", str(receipt_file),
        "--artifact-root", str(tmp_path),
    ]) == 2
    assert "required gates differ" in capsys.readouterr().err
    assert main([
        "--workspace", str(tmp_path), "--json", "measurement", "record",
        "--protocol", protocol.protocol_id,
        "--receipt-file", str(receipt_file),
        "--expected-receipt-sha256", receipt_sha256,
        "--artifact-root", str(tmp_path),
        "--output", str(custody_record),
    ]) == 2
    assert "already exists" in capsys.readouterr().err
    wrong_hash_record = tmp_path / "wrong-hash-custody-record"
    assert main([
        "--workspace", str(tmp_path), "--json", "measurement", "record",
        "--protocol", protocol.protocol_id,
        "--receipt-file", str(receipt_file),
        "--expected-receipt-sha256", "f" * 64,
        "--artifact-root", str(tmp_path),
        "--output", str(wrong_hash_record),
    ]) == 2
    assert "does not match expected_receipt_sha256" in capsys.readouterr().err
    assert not wrong_hash_record.exists()
    derived_hash = receipt["transformations"][0]["output_sha256"]
    with pytest.raises(ValidationError, match="cover exactly"):
        service.register_dataset(RegisterDataset(
            name="Unrelated", role=DatasetRole.CONFIRMATORY,
            artifacts=[DatasetArtifact("unrelated.json", "d" * 64)],
            protocol_id=protocol.protocol_id, synthetic=True,
            metadata={"measurement_custody": receipt},
            custody_artifact_root=str(tmp_path),
        ))
    assert ledger.read_bytes() == before
    assert service.list_datasets() == []
    (tmp_path / "calibration-result.json").write_bytes(b"tampered")
    rejected_record = tmp_path / "tampered-custody-record"
    assert main([
        "--workspace", str(tmp_path), "--json", "measurement", "record",
        "--protocol", protocol.protocol_id,
        "--receipt-file", str(receipt_file),
        "--expected-receipt-sha256", receipt_sha256,
        "--artifact-root", str(tmp_path),
        "--output", str(rejected_record),
    ]) == 2
    assert "custody artifact verification failed" in capsys.readouterr().err
    assert not rejected_record.exists()
    with pytest.raises(ValidationError, match="custody artifact verification failed"):
        service.register_dataset(RegisterDataset(
            name="Tampered support", role=DatasetRole.CONFIRMATORY,
            artifacts=[DatasetArtifact("derived.json", derived_hash)],
            protocol_id=protocol.protocol_id, synthetic=True,
            metadata={"measurement_custody": receipt},
            custody_artifact_root=str(tmp_path),
        ))
    assert ledger.read_bytes() == before
    assert service.list_datasets() == []
    (tmp_path / "calibration-result.json").write_bytes(b'{"synthetic": true}')
    accepted = service.register_dataset(RegisterDataset(
        name="Bound fixture", role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("derived.json", derived_hash)],
        protocol_id=protocol.protocol_id, synthetic=True,
        metadata={"measurement_custody": receipt},
        custody_artifact_root=str(tmp_path),
    ))
    assert accepted.synthetic
    verification = accepted.metadata["measurement_custody_verification"]
    assert verification["custody_receipt_sha256"]
    assert verification["protocol_hash"] == protocol.protocol_hash
    assert verification["custody_artifact_root"] == str(tmp_path.resolve())
    assert verification["artifact_integrity"]["all_artifacts_match"] is True
    assert service.verify_ledger()
    (tmp_path / "extract.py").write_bytes(b"# implementation changed after registration\n")
    with pytest.raises(ValidationError, match="custody artifact verification failed"):
        service.show_inquiry()
    with pytest.raises(ValidationError, match="custody artifact verification failed"):
        service._validate_run_datasets(protocol, [accepted])


def _receipt() -> dict:
    raw, derived = "a" * 64, "b" * 64
    return {
        "receipt_id": "mc-001",
        "evidence_artifacts": [{"locator": "calibration-result.json", "sha256": "e" * 64}],
        "raw_sources": [{"locator": "capture.bin", "sha256": raw, "captured_at": "2026-09-04T00:00:00Z", "acquisition_method": "instrument export"}],
        "transformations": [{"transformation_id": "events", "version": "1", "performed_at": "2026-09-04T00:01:00Z", "implementation_locator": "extract.py", "implementation_sha256": "c" * 64, "input_sha256": raw, "output_locator": "derived.json", "output_sha256": derived}],
        "calibrations": [{"calibration_id": "clock", "reference": "GPS", "performed_at": "2026-09-04T00:00:00Z", "result": "residual = 0.4 ms", "status": "passed", "criterion_id": "clock-residual", "observed_value": 0.4, "observed_unit": "ms", "evidence_sha256": "e" * 64}],
        "quality_gates": [{"gate_id": "clock-sync", "status": "passed", "evaluated_at": "2026-09-04T00:02:00Z", "summary": "clock alignment passed", "evidence_sha256": "e" * 64, "prerequisite_calibration_ids": ["clock"], "prerequisite_artifact_sha256s": [derived]}],
        "derived_observations": [{"observation_id": "event", "definition": "detected event", "derived_at": "2026-09-04T00:01:00Z", "source_output_sha256": derived, "quality_gate_ids": ["clock-sync"]}],
    }


def _materialize_receipt(root) -> dict:
    receipt = _receipt()
    raw = root / "capture.bin"
    raw.write_bytes(b"synthetic raw fixture")
    evidence = root / "calibration-result.json"
    evidence.write_bytes(b'{"synthetic": true}')
    implementation = root / "extract.py"
    implementation.write_bytes(b"# synthetic transformation fixture\n")
    derived = root / "derived.json"
    derived.write_bytes(b'{"synthetic": "derived"}')
    raw_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
    evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
    receipt["raw_sources"][0]["sha256"] = raw_hash
    receipt["transformations"][0]["input_sha256"] = raw_hash
    receipt["evidence_artifacts"][0]["sha256"] = evidence_hash
    receipt["calibrations"][0]["evidence_sha256"] = evidence_hash
    receipt["quality_gates"][0]["evidence_sha256"] = evidence_hash
    receipt["transformations"][0]["implementation_sha256"] = hashlib.sha256(implementation.read_bytes()).hexdigest()
    receipt["transformations"][0]["output_sha256"] = hashlib.sha256(derived.read_bytes()).hexdigest()
    receipt["derived_observations"][0]["source_output_sha256"] = receipt["transformations"][0]["output_sha256"]
    receipt["quality_gates"][0]["prerequisite_artifact_sha256s"] = [receipt["transformations"][0]["output_sha256"]]
    return receipt


def test_protected_custody_requires_byte_verification_without_writing(tmp_path):
    from research_machine.application.commands import CreateProtocol, RegisterDataset
    from research_machine.domain.models import AnalysisMode, CalibrationCriterion, DatasetArtifact, DatasetRole, ProtocolKind
    from test_execution import prepared_service
    service, hypothesis_id = prepared_service(tmp_path)
    draft = service.create_protocol(CreateProtocol(
        experiment_id="custody-required", title="Custody required",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis_id], primary_outcome="Result",
        protocol_kind=ProtocolKind.FORMAL, methodology="Synthetic custody fixture",
        quality_requirements=["clock-sync"], controls=["Invalid input"],
        expected_outputs=["Result"], success_conditions=["Report result"],
        environment_requirements=["Fixture"], sample_size_or_stopping_rule="One fixture",
        failure_conditions=["Broken chain"], safety_constraints=["Synthetic only"],
        analysis_code_hash="c" * 64, measurement_custody_requirements=["clock-sync"],
        calibration_acceptance_criteria=[CalibrationCriterion(
            "clock-residual", "clock", "absolute clock residual", "ms",
            "Keep synchronization error below the registered event-resolution limit.",
            upper_bound=1.0,
        )],
    ))
    protocol = service.freeze_protocol(draft.protocol_id)
    ledger = next(tmp_path.rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    with pytest.raises(ValidationError, match="custody_artifact_root"):
        service.register_dataset(RegisterDataset(
            name="Unverified", role=DatasetRole.CONFIRMATORY,
            artifacts=[DatasetArtifact("derived.json", "b" * 64)],
            protocol_id=protocol.protocol_id, synthetic=True,
            metadata={"measurement_custody": _receipt()},
        ))
    assert ledger.read_bytes() == before
    assert service.list_datasets() == []


def test_custody_verification_record_cannot_be_self_asserted(tmp_path):
    from research_machine.application.commands import RegisterDataset
    from research_machine.domain.models import DatasetArtifact, DatasetRole
    from test_execution import prepared_service
    service, _ = prepared_service(tmp_path)
    ledger = next(tmp_path.rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    with pytest.raises(ValidationError, match="service-generated"):
        service.register_dataset(RegisterDataset(
            name="Forged verification", role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("derived.json", "b" * 64)], synthetic=True,
            metadata={"measurement_custody_verification": {"status": "passed"}},
        ))
    assert ledger.read_bytes() == before
    assert service.list_datasets() == []


@pytest.mark.parametrize("failure", [None, "duplicate_transform", "duplicate_observation", "null", "unrelated"])
def test_optional_custody_is_validated_at_exploratory_registration(tmp_path, failure):
    from research_machine.application.commands import RegisterDataset
    from research_machine.domain.models import DatasetArtifact, DatasetRole
    from test_execution import prepared_service
    service, _ = prepared_service(tmp_path)
    receipt = _receipt()
    if failure == "duplicate_transform":
        receipt["transformations"].append(dict(receipt["transformations"][0]))
    elif failure == "duplicate_observation":
        receipt["derived_observations"].append(dict(receipt["derived_observations"][0]))
    elif failure == "null":
        receipt = None
    command = RegisterDataset(name="Synthetic optional custody", role=DatasetRole.EXPLORATORY,
        synthetic=True, artifacts=[DatasetArtifact("fixture.json", ("d" if failure == "unrelated" else "b") * 64)],
        metadata={"measurement_custody": receipt})
    ledger = next(tmp_path.rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    if failure:
        with pytest.raises(ValidationError):
            service.register_dataset(command)
        assert ledger.read_bytes() == before
        assert service.list_datasets() == []
    else:
        assert service.register_dataset(command).metadata["measurement_custody"] == receipt
    assert service.verify_ledger()["valid"]


def test_custody_receipt_requires_lineage_calibration_and_required_gates() -> None:
    assert validate_measurement_custody(_receipt(), ["clock-sync"])["receipt_id"] == "mc-001"
    with pytest.raises(ValidationError, match="required_gate_ids must be canonical"):
        validate_measurement_custody(_receipt(), [" clock-sync "])
    with pytest.raises(ValidationError, match="missing required gates"):
        validate_measurement_custody(_receipt(), ["sensor-validity"])
    with pytest.raises(ValidationError, match="required_gate_ids must be unique"):
        validate_measurement_custody(_receipt(), ["clock-sync", "clock-sync"])


def _clock_criterion() -> CalibrationCriterion:
    return CalibrationCriterion(
        "clock-residual", "clock", "absolute clock residual", "ms",
        "Keep synchronization error below the registered event-resolution limit.",
        lower_bound=0.0, upper_bound=1.0,
    )


def test_custody_computes_calibration_acceptance_against_frozen_bounds() -> None:
    receipt = _receipt()
    assert validate_measurement_custody(
        receipt, ["clock-sync"], [_clock_criterion()]
    ) == receipt
    padded = CalibrationCriterion(
        " clock-residual ", " clock ", "absolute clock residual", "ms",
        "Keep synchronization error below the registered event-resolution limit.",
        lower_bound=0.0, upper_bound=1.0,
    )
    with pytest.raises(ValidationError, match="calibration criterion calibration_id must be canonical"):
        validate_measurement_custody(receipt, ["clock-sync"], [padded])
    receipt["calibrations"][0]["observed_value"] = 1.01
    with pytest.raises(ValidationError, match="frozen upper bound"):
        validate_measurement_custody(receipt, ["clock-sync"], [_clock_criterion()])


def test_required_calibration_criteria_ids_must_be_canonical_and_unique() -> None:
    padded = CalibrationCriterion(
        "other-clock-residual", " clock ", "absolute clock residual", "ms",
        "A padded duplicate cannot become a second frozen calibration.",
        lower_bound=0.0, upper_bound=1.0,
    )
    with pytest.raises(ValidationError, match="calibration criterion calibration_id must be canonical"):
        validate_measurement_custody(_receipt(), ["clock-sync"], [_clock_criterion(), padded])
    duplicate = CalibrationCriterion(
        "other-clock-residual", "clock", "absolute clock residual", "ms",
        "A duplicate cannot become a second frozen calibration.",
        lower_bound=0.0, upper_bound=1.0,
    )
    with pytest.raises(ValidationError, match="required calibration criteria"):
        validate_measurement_custody(_receipt(), ["clock-sync"], [_clock_criterion(), duplicate])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda receipt: receipt.update({"receipt_id": " mc-001 "}), "receipt_id"),
        (lambda receipt: receipt["evidence_artifacts"][0].update({"locator": " calibration-result.json "}), "evidence artifact locator"),
        (lambda receipt: receipt["raw_sources"][0].update({"locator": " capture.bin "}), "raw_sources\\[0\\].locator"),
        (lambda receipt: receipt["raw_sources"][0].update({"acquisition_method": " instrument export "}), "raw_sources\\[0\\].acquisition_method"),
        (lambda receipt: receipt["transformations"][0].update({"version": " 1 "}), "transformations\\[0\\].version"),
        (lambda receipt: receipt["transformations"][0].update({"implementation_locator": " extract.py "}), "transformations\\[0\\].implementation_locator"),
        (lambda receipt: receipt["transformations"][0].update({"output_locator": " derived.json "}), "transformations\\[0\\].output_locator"),
        (lambda receipt: receipt["calibrations"][0].update({"reference": " GPS "}), "calibration.reference"),
        (lambda receipt: receipt["calibrations"][0].update({"result": " residual = 0.4 ms "}), "calibration.result"),
        (lambda receipt: receipt["quality_gates"][0].update({"summary": " clock alignment passed "}), "quality gate clock-sync summary"),
        (lambda receipt: receipt["derived_observations"][0].update({"definition": " detected event "}), "derived observation definition"),
    ],
)
def test_custody_retained_text_fields_must_be_canonical(mutate, message) -> None:
    receipt = _receipt()
    mutate(receipt)
    with pytest.raises(ValidationError, match=message):
        validate_measurement_custody(receipt)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("observed_unit", "seconds", "observed_unit"),
        ("criterion_id", "post-hoc-threshold", "frozen criterion"),
        ("criterion_id", " clock-residual ", "criterion_id must be canonical"),
        ("observed_value", float("nan"), "finite number"),
    ],
)
def test_custody_rejects_calibration_that_does_not_match_frozen_criterion(field, value, message) -> None:
    receipt = _receipt()
    receipt["calibrations"][0][field] = value
    with pytest.raises(ValidationError, match=message):
        validate_measurement_custody(receipt, ["clock-sync"], [_clock_criterion()])


@pytest.mark.parametrize(
    "section,key",
    [
        ("transformations", "transformation_id"),
        ("calibrations", "calibration_id"),
        ("quality_gates", "gate_id"),
        ("derived_observations", "observation_id"),
    ],
)
@pytest.mark.parametrize("padding", ["", " "])
def test_custody_identifiers_must_be_canonical_and_unambiguous(section, key, padding):
    receipt = _receipt()
    duplicate = dict(receipt[section][0])
    duplicate[key] = padding + duplicate[key] + padding
    if section == "transformations":
        duplicate["version"] = "2"
        duplicate["input_sha256"] = "b" * 64
        duplicate["output_sha256"] = "d" * 64
    elif section == "derived_observations":
        duplicate["definition"] = "A different derived measurement"
    elif section == "calibrations":
        duplicate["reference"] = "A different traceable reference"
    else:
        duplicate["summary"] = "A different quality gate assessment"
    receipt[section].append(duplicate)
    expected = f"{key} must be unique" if not padding else f"{key} must be canonical"
    with pytest.raises(ValidationError, match=expected):
        validate_measurement_custody(receipt)
    duplicate[key] = "distinct-step-or-observation"
    assert validate_measurement_custody(receipt) == receipt


def test_custody_receipt_rejects_untraceable_derived_observation() -> None:
    receipt = _receipt()
    receipt["derived_observations"][0]["source_output_sha256"] = "d" * 64
    with pytest.raises(ValidationError, match="transformation output"):
        validate_measurement_custody(receipt)


@pytest.mark.parametrize("section,field", [("raw_sources", "captured_at"), ("calibrations", "performed_at")])
@pytest.mark.parametrize("value", ["yesterday", "2026-09-04", "2026-09-04T12:00:00", "2026-13-04T00:00:00Z"])
def test_custody_requires_usable_timestamp_offsets(section, field, value):
    receipt = _receipt()
    receipt[section][0][field] = value
    with pytest.raises(ValidationError, match="UTC offset"):
        validate_measurement_custody(receipt)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("transformations", "performed_at", "2026-09-03T23:59:59Z", "predates availability"),
        ("quality_gates", "evaluated_at", "2026-09-03T23:59:59Z", "predates a calibration"),
        ("derived_observations", "derived_at", "2026-09-04T00:00:59Z", "predates its transformation"),
    ],
)
def test_custody_rejects_impossible_prerequisite_chronology(section, field, value, message):
    receipt = _receipt()
    receipt[section][0][field] = value
    with pytest.raises(ValidationError, match=message):
        validate_measurement_custody(receipt)


@pytest.mark.parametrize(
    ("section", "field"),
    [("transformations", "performed_at"), ("quality_gates", "evaluated_at"),
     ("derived_observations", "derived_at")],
)
def test_custody_requires_timestamps_for_every_derived_stage(section, field):
    receipt = _receipt()
    del receipt[section][0][field]
    with pytest.raises(ValidationError, match=field):
        validate_measurement_custody(receipt)


@pytest.mark.parametrize("value", ["2026-09-04T00:00:00Z", "2026-09-03T20:00:00-04:00"])
def test_custody_preserves_timestamp_representation(value):
    receipt = _receipt()
    receipt["raw_sources"][0]["captured_at"] = value
    assert validate_measurement_custody(receipt)["raw_sources"][0]["captured_at"] == value


@pytest.mark.parametrize("section", ["calibrations", "quality_gates"])
def test_passed_labels_require_listed_evidence(section):
    receipt = _receipt()
    receipt[section][0]["evidence_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="listed evidence artifact"):
        validate_measurement_custody(receipt)


def test_gate_cannot_cite_missing_calibration():
    receipt = _receipt()
    receipt["quality_gates"][0]["prerequisite_calibration_ids"] = ["missing"]
    with pytest.raises(ValidationError, match="unavailable calibration"):
        validate_measurement_custody(receipt)


def test_gate_calibration_prerequisites_must_be_canonical_and_unique():
    receipt = _receipt()
    receipt["quality_gates"][0]["prerequisite_calibration_ids"] = [" clock "]
    with pytest.raises(ValidationError, match="prerequisite_calibration_ids item must be canonical"):
        validate_measurement_custody(receipt)
    receipt["quality_gates"][0]["prerequisite_calibration_ids"] = ["clock", "clock"]
    with pytest.raises(ValidationError, match="duplicate calibration prerequisites"):
        validate_measurement_custody(receipt)


def test_derived_observation_gate_references_must_be_canonical_and_unique():
    receipt = _receipt()
    receipt["derived_observations"][0]["quality_gate_ids"] = [" clock-sync "]
    with pytest.raises(ValidationError, match="quality_gate_ids item must be canonical"):
        validate_measurement_custody(receipt)
    receipt["derived_observations"][0]["quality_gate_ids"] = ["clock-sync", "clock-sync"]
    with pytest.raises(ValidationError, match="duplicate quality_gate_ids"):
        validate_measurement_custody(receipt)


@pytest.mark.parametrize("failure", ["missing_artifact_list", "unknown_artifact", "observation_gate", "gate_does_not_cover_output"])
def test_measurement_gates_must_clear_the_exact_derived_artifact(failure):
    receipt = _receipt()
    if failure == "missing_artifact_list":
        del receipt["quality_gates"][0]["prerequisite_artifact_sha256s"]
    elif failure == "unknown_artifact":
        receipt["quality_gates"][0]["prerequisite_artifact_sha256s"] = ["f" * 64]
    elif failure == "observation_gate":
        receipt["derived_observations"][0]["quality_gate_ids"] = ["unreviewed-gate"]
    else:
        raw_hash = receipt["raw_sources"][0]["sha256"]
        receipt["quality_gates"][0]["prerequisite_artifact_sha256s"] = [raw_hash]
    with pytest.raises(ValidationError):
        validate_measurement_custody(receipt)


@pytest.mark.parametrize("failure", [None, "tampered", "implementation", "output", "missing", "traversal", "symlink"])
def test_cli_verifies_complete_transformation_chain_bytes(tmp_path, capsys, failure):
    import hashlib
    import json
    from research_machine.interfaces.cli import main

    receipt = _materialize_receipt(tmp_path)
    raw = tmp_path / "capture.bin"
    evidence = tmp_path / "calibration-result.json"
    if failure == "tampered":
        evidence.write_bytes(b"changed")
    elif failure == "implementation":
        (tmp_path / "extract.py").write_bytes(b"# changed implementation\n")
    elif failure == "output":
        (tmp_path / "derived.json").write_bytes(b'{"changed": true}')
    elif failure == "missing":
        evidence.unlink()
    elif failure == "traversal":
        receipt["evidence_artifacts"][0]["locator"] = "../outside.json"
    elif failure == "symlink":
        evidence.unlink()
        evidence.symlink_to(raw)
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    status = main(["--json", "measurement", "validate", "--receipt-file", str(path),
                   "--artifact-root", str(tmp_path)])
    captured = capsys.readouterr()
    if failure:
        assert status == 2
        assert "custody artifact verification failed" in captured.err
    else:
        assert status == 0
        result = json.loads(captured.out)["result"]
        assert result["artifact_integrity"]["artifact_count"] == 4
        assert result["artifact_integrity"]["all_artifacts_match"] is True
        assert result["scientific_evidence_eligible"] is False
