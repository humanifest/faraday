from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import pytest

from research_machine.application.commands import (
    CreateInquiry,
    CreateProtocol,
    ProposeHypothesis,
    RegisterDataset,
    RecordRun,
)
from research_machine.application.service import ResearchService
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.domain.models import (
    AnalysisMode,
    DatasetArtifact,
    DatasetManifest,
    DatasetRole,
    ProtocolKind,
    QualityGateResult,
    QualityGateStatus,
)
from research_machine.domain.errors import ValidationError
from research_machine.measurement.instrument import assess_temporal_order
from research_machine.measurement.preprocessing import assess_preprocessing_conformance
from research_machine.replication.package import verify_replication_package
from research_machine.interfaces.cli import main


def _tiny_v1_replication_package(root: Path) -> tuple[Path, str]:
    package = root / "package"
    package.mkdir()
    expected_files = {"protocol.json", "datasets.json", "runs.json", "INSTRUCTIONS.md"}
    file_hashes: dict[str, str] = {}
    for name in expected_files:
        path = package / name
        path.write_text(f"synthetic fixture {name}\n", encoding="utf-8")
        file_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = package / "package-manifest.json"
    manifest_path.write_text(
        json.dumps({"package_version": 1, "files": file_hashes}),
        encoding="utf-8",
    )
    return package, hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _after_registration_times(registration_timestamp: str) -> tuple[str, str]:
    registered = datetime.fromisoformat(
        registration_timestamp.replace("Z", "+00:00")
    )
    started = registered + timedelta(minutes=1)
    completed = registered + timedelta(minutes=2)
    return (
        started.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        completed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _pipeline(*, smoothing_window: int = 5) -> dict:
    return {
        "pipeline_id": "registered-pipeline",
        "purpose": "Synthetic fixture for package preprocessing conformance.",
        "steps": [
            {
                "step_id": "load-raw",
                "operation": "read fixture bytes",
                "parameters": {"encoding": "utf-8"},
                "input_artifacts": [{
                    "artifact_id": "raw-input",
                    "sha256": "1" * 64,
                    "media_type": "text/csv",
                    "role": "raw observation fixture",
                }],
                "output_artifacts": [{
                    "artifact_id": "loaded-table",
                    "sha256": "2" * 64,
                    "media_type": "application/json",
                    "role": "loaded table fixture",
                }],
                "implementation_sha256": "3" * 64,
            },
            {
                "step_id": "smooth-signal",
                "operation": "moving average",
                "parameters": {"window": smoothing_window, "edge_policy": "drop"},
                "input_artifacts": [{
                    "artifact_id": "loaded-table",
                    "sha256": "2" * 64,
                    "media_type": "application/json",
                    "role": "loaded table fixture",
                }],
                "output_artifacts": [{
                    "artifact_id": "smoothed-table",
                    "sha256": "4" * 64,
                    "media_type": "application/json",
                    "role": "preprocessed table fixture",
                }],
                "implementation_sha256": "5" * 64,
            },
        ],
    }


def _temporal_order_spec() -> dict:
    return {
        "assessment_id": "temporal-order",
        "order_checks": [
            {
                "check_id": "state-before-sound",
                "first_event_id": "state-event",
                "second_event_id": "sound-event",
                "expected_relation": "first_precedes_second",
                "minimum_separation": {"duration": 1, "unit": "ms"},
                "maximum_separation": {"duration": 20, "unit": "ms"},
                "scientific_question": "Synthetic fixture for temporal ordering.",
            }
        ],
    }


def _stream_timing_assessment_record() -> dict:
    return {
        "stream_timing_assessment_version": 1,
        "assessment_id": "stream-timing",
        "inspection": {
            "sha256": "1" * 64,
            "size_bytes": 100,
            "stream_count": 1,
            "temporal_metadata_status": "proposed_unverified",
        },
        "specification": {
            "sha256": "2" * 64,
            "size_bytes": 100,
            "lag_window": {
                "duration": 1,
                "unit": "ms",
                "seconds": 0.001,
                "basis": "Synthetic fixture lag window.",
            },
            "maximum_uncertainty_fraction": 0.25,
        },
        "required_streams": [{
            "stream_id": "stream-main",
            "channel": "main",
            "purpose": "Primary synchronized signal fixture.",
            "observed_channel": "main",
            "status": "present",
        }],
        "events": [{
            "event_id": "state-event",
            "stream_id": "stream-main",
            "event_time": "2026-09-06T12:00:03.000000Z",
            "status": "assessed",
            "clock_uncertainty_seconds": 0.00005,
            "uncertainty_fraction_of_lag_window": 0.05,
            "overlapping_missing_intervals": [],
        }],
        "findings": [],
        "status": "timing_feasibility_passed",
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Provider-free timing feasibility review from a trusted inspection record only."
        ),
    }


def _temporal_timing_assessment() -> dict:
    return {
        "stream_timing_assessment_version": 1,
        "status": "timing_feasibility_passed",
        "events": [
            {
                "event_id": "state-event",
                "stream_id": "stream-main",
                "event_time": "2026-09-06T12:00:03.000000Z",
                "status": "assessed",
                "clock_uncertainty_seconds": 0.00005,
                "overlapping_missing_intervals": [],
            },
            {
                "event_id": "sound-event",
                "stream_id": "stream-main",
                "event_time": "2026-09-06T12:00:03.010000Z",
                "status": "assessed",
                "clock_uncertainty_seconds": 0.00005,
                "overlapping_missing_intervals": [],
            },
        ],
        "scientific_evidence_eligible": False,
    }


def _write_json(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refresh_packaged_file(package: Path, name: str) -> str:
    manifest_path = package / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][name] = hashlib.sha256((package / name).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def test_nested_locator_redaction_does_not_mutate_source():
    from research_machine.replication.package import _redact_artifact_locators
    source = {"metadata": {"custody": [{"locator": "/private/fixture.csv", "sha256": "a" * 64}]},
              "custody_artifact_root": "/private/custody",
              "run_attestation_schema_path": "/private/schema.json",
              "review_artifact_locator": "/private/review.pdf",
              "summary": "Free text still requires review"}
    redacted = _redact_artifact_locators(source)
    assert redacted["metadata"]["custody"][0]["locator"].startswith("[redacted:")
    assert redacted["metadata"]["custody"][0]["sha256"] == "a" * 64
    assert source["metadata"]["custody"][0]["locator"] == "/private/fixture.csv"
    assert redacted["custody_artifact_root"].startswith("[redacted:")
    assert redacted["run_attestation_schema_path"].startswith("[redacted:")
    assert redacted["review_artifact_locator"].startswith("[redacted:")
    assert source["review_artifact_locator"] == "/private/review.pdf"
    assert redacted["summary"] == source["summary"]


@pytest.mark.parametrize("expected", ["A" * 64, "0" * 63, " " + "0" * 64])
def test_replication_verify_rejects_noncanonical_expected_manifest_hash(
    tmp_path: Path, expected: str
) -> None:
    package, _ = _tiny_v1_replication_package(tmp_path)

    with pytest.raises(
        ValidationError,
        match="expected manifest SHA-256 must be 64 lowercase hex characters",
    ):
        verify_replication_package(package, expected)


@pytest.mark.parametrize("expected", ["A" * 64, "0" * 63, " " + "0" * 64])
def test_replication_verify_rejects_noncanonical_manifest_file_hash(
    tmp_path: Path, expected: str
) -> None:
    package, _ = _tiny_v1_replication_package(tmp_path)
    manifest_path = package / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["runs.json"] = expected
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(
        ValidationError,
        match="manifest file hash for runs.json must be 64 lowercase hex characters",
    ):
        verify_replication_package(package, commitment)


@pytest.mark.parametrize("mutation", [
    "file", "manifest", "missing", "extra", "symlink", "traversal",
    "privacy_mode", "locator_policy", "limitations", "ethics_summary",
    "instructions", "dataset_summary", "dataset_cycle", "run_eligibility",
    "blank_prerequisite", "padded_prerequisite", "quality_gate_duplicate_after_trim",
    "protocol_gate_duplicate", "protocol_gate_padded",
])
def test_metadata_only_replication_package_requires_frozen_protocol(tmp_path: Path, mutation, capsys) -> None:
    service = ResearchService(FileSystemRepository(tmp_path / "workspace"), actor="test")
    service.init_workspace()
    inquiry = service.create_inquiry(CreateInquiry("Test", "Question", "test"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Statement", observable_prediction="Prediction", null_model="Null",
        falsification_conditions=["Failure"],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test", title="Test", analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id], primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL, methodology="Method", quality_requirements=["gate"],
        controls=["control"], expected_outputs=["output"], success_conditions=["success"],
        environment_requirements=["environment"], sample_size_or_stopping_rule="one",
        failure_conditions=["failure"], safety_constraints=["safe"], analysis_code_hash="a" * 64,
    ))
    frozen = service.freeze_protocol(protocol.protocol_id)
    dataset = service.register_dataset(RegisterDataset(
        name="Synthetic observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("observations.csv", "d" * 64)],
        protocol_id=frozen.protocol_id,
        synthetic=True,
        quality_attestations=["Synthetic package fixture."],
    ))
    output = tmp_path / "result.json"
    output.write_text('{"result":"passed"}\n', encoding="utf-8")
    output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    started_at, completed_at = _after_registration_times(
        frozen.registration_timestamp
    )
    service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at=started_at,
        completed_at=completed_at,
        analysis_code_hash="a" * 64,
        environment_hash="e" * 64,
        output_artifacts=[DatasetArtifact(
            "result.json", output_hash, output.stat().st_size, "application/json"
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "gate", QualityGateStatus.PASSED, "Synthetic package fixture passed.",
            details={"evidence_sha256": output_hash},
        )],
        summary="Synthetic package fixture.",
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared", "deviations": [],
        }},
    ))
    exported = service.export_replication_package(frozen.protocol_id, str(tmp_path / "package"))
    assert exported["package_version"] == 2
    assert exported["verification_contract"] == "replication_package_v2_guardrails"
    assert exported["privacy_mode"] == "metadata_only"
    assert exported["artifact_locator_policy"] == "redacted"
    assert (tmp_path / "package" / "package-manifest.json").is_file()
    package = tmp_path / "package"
    manifest = json.loads((package / "package-manifest.json").read_text())
    assert manifest["package_version"] == 2
    assert manifest["ethics_review_event_ids"] == []
    assert manifest["latest_recorded_ethics_status"] == "not_applicable"
    assert manifest["replication_ethics_authorized"] is False
    assert json.loads((package / "ethics-review-events.json").read_text()) == []
    commitment = exported["package_manifest_sha256"]
    verified = verify_replication_package(package, commitment)
    assert verified["verification_scope"] == "package_file_integrity"
    assert verified["package_version"] == 2
    assert verified["verification_contract"] == "replication_package_v2_guardrails"
    assert verified["scientific_evidence_eligible"] is False
    assert "ethics-review-events.json" in verified["verified_files"]
    assert main(["--json", "replication", "verify", "--package", str(package),
                 "--expected-manifest-sha256", commitment]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == verified
    if mutation == "file":
        (package / "runs.json").write_text("tampered")
    elif mutation == "manifest":
        with (package / "package-manifest.json").open("a") as handle:
            handle.write(" ")
    elif mutation == "missing":
        (package / "runs.json").unlink()
    elif mutation == "extra":
        (package / "unlisted.txt").write_text("unlisted fixture")
    elif mutation == "symlink":
        (package / "runs.json").unlink()
        (package / "runs.json").symlink_to(package / "datasets.json")
    elif mutation == "traversal":
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["../outside"] = "a" * 64
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "privacy_mode":
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["privacy_mode"] = "raw_data_included"
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "locator_policy":
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["artifact_locator_policy"] = "trust_sender_summary"
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "limitations":
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["limitations"] = ["This package verifies successful replication."]
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "instructions":
        instructions_path = package / "INSTRUCTIONS.md"
        instructions_path.write_text(
            "# Independent replication instructions\n\n"
            "This package is ready to use as evidence.\n",
            encoding="utf-8",
        )
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["INSTRUCTIONS.md"] = hashlib.sha256(
            instructions_path.read_bytes()
        ).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "ethics_summary":
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["latest_recorded_ethics_status"] = "suspended"
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "dataset_summary":
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["dataset_ids"] = ["invented-dataset"]
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "dataset_cycle":
        datasets_path = package / "datasets.json"
        cycle = DatasetManifest(
            dataset_id="cycle-dataset",
            name="Synthetic cycle",
            role=DatasetRole.CONFIRMATORY,
            created_at="2026-09-01T00:00:00Z",
            artifacts=[DatasetArtifact("cycle.csv", "c" * 64)],
            source_dataset_ids=["cycle-dataset"],
            protocol_id=frozen.protocol_id,
            synthetic=True,
        )
        datasets_path.write_text(json.dumps([cycle.to_dict()], indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["dataset_ids"] = [cycle.dataset_id]
        manifest["files"]["datasets.json"] = hashlib.sha256(datasets_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "run_eligibility":
        runs_path = package / "runs.json"
        runs = json.loads(runs_path.read_text())
        runs[0]["synthetic"] = True
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["runs.json"] = hashlib.sha256(runs_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "blank_prerequisite":
        runs_path = package / "runs.json"
        runs = json.loads(runs_path.read_text())
        runs[0]["quality_gates"][0]["details"]["prerequisite_gate_ids"] = [" "]
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["runs.json"] = hashlib.sha256(runs_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "padded_prerequisite":
        runs_path = package / "runs.json"
        runs = json.loads(runs_path.read_text())
        source_gate = dict(runs[0]["quality_gates"][0])
        source_gate["gate_id"] = "source-check"
        source_gate["summary"] = "Source gate passed."
        runs[0]["quality_gates"][0]["details"]["prerequisite_gate_ids"] = [
            " source-check"
        ]
        runs[0]["quality_gates"].append(source_gate)
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["runs.json"] = hashlib.sha256(runs_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "quality_gate_duplicate_after_trim":
        runs_path = package / "runs.json"
        runs = json.loads(runs_path.read_text())
        duplicate = dict(runs[0]["quality_gates"][0])
        duplicate["gate_id"] = f" {duplicate['gate_id']} "
        runs[0]["quality_gates"].append(duplicate)
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["runs.json"] = hashlib.sha256(runs_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "protocol_gate_duplicate":
        protocol_path = package / "protocol.json"
        protocol_record = json.loads(protocol_path.read_text())
        protocol_record["quality_requirements"].append(protocol_record["quality_requirements"][0])
        protocol_path.write_text(json.dumps(protocol_record, indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["protocol.json"] = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    else:
        protocol_path = package / "protocol.json"
        protocol_record = json.loads(protocol_path.read_text())
        protocol_record["quality_requirements"][0] = f" {protocol_record['quality_requirements'][0]} "
        protocol_path.write_text(json.dumps(protocol_record, indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["protocol.json"] = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValidationError):
        verify_replication_package(package, commitment)
    assert service.verify_ledger()["valid"] is True


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("declared_failed", "passed preprocessing gate"),
        ("warning_gate", "must be passed or failed"),
        ("missing_field", "preprocessing_conformance fields are invalid"),
        ("bad_observed_hash", "observed_pipeline_sha256 must be 64 lowercase hex characters"),
        ("protocol_mismatch", "does not match frozen protocol preprocessing_pipeline"),
    ],
)
def test_replication_package_verifies_preprocessing_conformance_gate_metadata(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    workspace = tmp_path / "workspace"
    service = ResearchService(FileSystemRepository(workspace), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Test", "Question", "test"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Statement", observable_prediction="Prediction", null_model="Null",
        falsification_conditions=["Failure"],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    registered = tmp_path / "registered-pipeline.json"
    observed = tmp_path / "observed-pipeline.json"
    registered_sha256 = _write_json(registered, _pipeline())
    observed_sha256 = _write_json(observed, _pipeline())
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test", title="Test", analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id], primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL, methodology="Method", quality_requirements=["gate"],
        controls=["control"], expected_outputs=["output"], success_conditions=["success"],
        environment_requirements=["environment"], sample_size_or_stopping_rule="one",
        failure_conditions=["failure"], safety_constraints=["safe"], analysis_code_hash="a" * 64,
        preprocessing_pipeline=registered_sha256,
    ))
    frozen = service.freeze_protocol(protocol.protocol_id)
    service.register_dataset(RegisterDataset(
        name="Synthetic observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("observations.csv", "d" * 64)],
        protocol_id=frozen.protocol_id,
        synthetic=True,
        quality_attestations=["Synthetic package fixture."],
    ))
    conformance = assess_preprocessing_conformance(
        registered,
        registered_sha256,
        observed,
        observed_sha256,
        tmp_path / "preprocessing-conformance",
    )
    record = Path(conformance["path"]) / "preprocessing-conformance.json"
    record_locator = str(record.relative_to(tmp_path))
    started_at, completed_at = _after_registration_times(
        frozen.registration_timestamp
    )
    service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at=started_at,
        completed_at=completed_at,
        analysis_code_hash="a" * 64,
        environment_hash="e" * 64,
        output_artifacts=[DatasetArtifact(
            record_locator,
            conformance["assessment_sha256"],
            record.stat().st_size,
            "application/json",
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "gate",
            QualityGateStatus.PASSED,
            "Synthetic preprocessing conformance fixture passed.",
            details={
                "evidence_sha256": conformance["assessment_sha256"],
                "preprocessing_conformance": {
                    "locator": record_locator,
                    "sha256": conformance["assessment_sha256"],
                    "status": "preprocessing_conformance_passed",
                    "registered_pipeline_sha256": registered_sha256,
                    "observed_pipeline_sha256": observed_sha256,
                },
            },
        )],
        summary="Synthetic package fixture.",
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared", "deviations": [],
        }},
    ))
    exported = service.export_replication_package(
        frozen.protocol_id,
        str(tmp_path / "package"),
    )
    package = tmp_path / "package"
    verify_replication_package(package, exported["package_manifest_sha256"])

    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    gate = runs[0]["quality_gates"][0]
    if mutation == "declared_failed":
        gate["details"]["preprocessing_conformance"]["status"] = (
            "preprocessing_conformance_failed"
        )
    elif mutation == "warning_gate":
        gate["status"] = "warning"
    elif mutation == "missing_field":
        del gate["details"]["preprocessing_conformance"]["observed_pipeline_sha256"]
    elif mutation == "bad_observed_hash":
        gate["details"]["preprocessing_conformance"]["observed_pipeline_sha256"] = (
            "not-a-hash"
        )
    elif mutation == "protocol_mismatch":
        protocol_path = package / "protocol.json"
        protocol_record = json.loads(protocol_path.read_text())
        protocol_record["preprocessing_pipeline"] = "0" * 64
        protocol_path.write_text(json.dumps(protocol_record, indent=2, sort_keys=True) + "\n")
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        commitment = _refresh_packaged_file(package, "protocol.json")
    if mutation != "protocol_mismatch":
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match=message):
        verify_replication_package(package, commitment)


def test_replication_package_verifies_stream_timing_gate_metadata(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    service = ResearchService(FileSystemRepository(workspace), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Test", "Question", "test"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Statement", observable_prediction="Prediction", null_model="Null",
        falsification_conditions=["Failure"],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test", title="Test", analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id], primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL, methodology="Method", quality_requirements=["gate"],
        controls=["control"], expected_outputs=["output"], success_conditions=["success"],
        environment_requirements=["environment"], sample_size_or_stopping_rule="one",
        failure_conditions=["failure"], safety_constraints=["safe"], analysis_code_hash="a" * 64,
    ))
    frozen = service.freeze_protocol(protocol.protocol_id)
    service.register_dataset(RegisterDataset(
        name="Synthetic observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("observations.csv", "d" * 64)],
        protocol_id=frozen.protocol_id,
        synthetic=True,
        quality_attestations=["Synthetic package fixture."],
    ))
    record_path = tmp_path / "stream-timing-assessment.json"
    record = _stream_timing_assessment_record()
    record_sha256 = _write_json(record_path, record)
    started_at, completed_at = _after_registration_times(
        frozen.registration_timestamp
    )
    service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at=started_at,
        completed_at=completed_at,
        analysis_code_hash="a" * 64,
        environment_hash="e" * 64,
        output_artifacts=[DatasetArtifact(
            record_path.name,
            record_sha256,
            record_path.stat().st_size,
            "application/json",
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "gate",
            QualityGateStatus.PASSED,
            "Synthetic stream-timing fixture passed.",
            details={
                "evidence_sha256": record_sha256,
                "stream_timing_assessment": {
                    "locator": record_path.name,
                    "sha256": record_sha256,
                    "status": "timing_feasibility_passed",
                    "inspection_sha256": record["inspection"]["sha256"],
                    "specification_sha256": record["specification"]["sha256"],
                },
            },
        )],
        summary="Synthetic package fixture.",
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared", "deviations": [],
        }},
    ))
    exported = service.export_replication_package(
        frozen.protocol_id,
        str(tmp_path / "package"),
    )
    package = tmp_path / "package"
    verify_replication_package(package, exported["package_manifest_sha256"])

    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    runs[0]["quality_gates"][0]["details"]["stream_timing_assessment"][
        "status"
    ] = "timing_feasibility_failed"
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match="passed stream-timing gate"):
        verify_replication_package(package, commitment)


def test_replication_package_verifies_temporal_order_gate_metadata(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    service = ResearchService(FileSystemRepository(workspace), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Test", "Question", "test"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Statement", observable_prediction="Prediction", null_model="Null",
        falsification_conditions=["Failure"],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test", title="Test", analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id], primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL, methodology="Method", quality_requirements=["gate"],
        controls=["control"], expected_outputs=["output"], success_conditions=["success"],
        environment_requirements=["environment"], sample_size_or_stopping_rule="one",
        failure_conditions=["failure"], safety_constraints=["safe"], analysis_code_hash="a" * 64,
    ))
    frozen = service.freeze_protocol(protocol.protocol_id)
    service.register_dataset(RegisterDataset(
        name="Synthetic observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("observations.csv", "d" * 64)],
        protocol_id=frozen.protocol_id,
        synthetic=True,
        quality_attestations=["Synthetic package fixture."],
    ))
    timing = tmp_path / "timing-assessment.json"
    spec = tmp_path / "temporal-order-spec.json"
    timing_sha256 = _write_json(timing, _temporal_timing_assessment())
    specification_sha256 = _write_json(spec, _temporal_order_spec())
    assessment = assess_temporal_order(
        timing,
        timing_sha256,
        spec,
        tmp_path / "temporal-order",
    )
    record = Path(assessment["path"]) / "temporal-order-assessment.json"
    record_locator = str(record.relative_to(tmp_path))
    started_at, completed_at = _after_registration_times(
        frozen.registration_timestamp
    )
    service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at=started_at,
        completed_at=completed_at,
        analysis_code_hash="a" * 64,
        environment_hash="e" * 64,
        output_artifacts=[DatasetArtifact(
            record_locator,
            assessment["assessment_sha256"],
            record.stat().st_size,
            "application/json",
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "gate",
            QualityGateStatus.PASSED,
            "Synthetic temporal-order fixture passed.",
            details={
                "evidence_sha256": assessment["assessment_sha256"],
                "temporal_order_assessment": {
                    "locator": record_locator,
                    "sha256": assessment["assessment_sha256"],
                    "status": "temporal_order_passed",
                    "timing_assessment_sha256": timing_sha256,
                    "specification_sha256": specification_sha256,
                },
            },
        )],
        summary="Synthetic package fixture.",
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared", "deviations": [],
        }},
    ))
    exported = service.export_replication_package(
        frozen.protocol_id,
        str(tmp_path / "package"),
    )
    package = tmp_path / "package"
    verify_replication_package(package, exported["package_manifest_sha256"])

    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    runs[0]["quality_gates"][0]["details"]["temporal_order_assessment"][
        "status"
    ] = "temporal_order_failed"
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match="passed temporal-order gate"):
        verify_replication_package(package, commitment)


def test_included_locator_package_replays_protocol_hash(tmp_path: Path) -> None:
    service = ResearchService(FileSystemRepository(tmp_path / "workspace"), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Test", "Question", "test"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Statement", observable_prediction="Prediction", null_model="Null",
        falsification_conditions=["Failure"],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test", title="Test", analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id], primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL, methodology="Method", quality_requirements=["gate"],
        controls=["control"], expected_outputs=["output"], success_conditions=["success"],
        environment_requirements=["environment"], sample_size_or_stopping_rule="one",
        failure_conditions=["failure"], safety_constraints=["safe"], analysis_code_hash="a" * 64,
    ))
    frozen = service.freeze_protocol(protocol.protocol_id)
    dataset = service.register_dataset(RegisterDataset(
        name="Synthetic observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("observations.csv", "d" * 64)],
        protocol_id=frozen.protocol_id,
        synthetic=True,
        quality_attestations=["Synthetic package fixture."],
    ))
    output = tmp_path / "result.json"
    output.write_text('{"result":"passed"}\n', encoding="utf-8")
    output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    started_at, completed_at = _after_registration_times(
        frozen.registration_timestamp
    )
    recorded = service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at=started_at,
        completed_at=completed_at,
        analysis_code_hash="a" * 64,
        environment_hash="e" * 64,
        output_artifacts=[DatasetArtifact(
            "result.json", output_hash, output.stat().st_size, "application/json"
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "gate", QualityGateStatus.PASSED, "Synthetic package fixture passed.",
            details={"evidence_sha256": output_hash},
        )],
        summary="Synthetic package fixture.",
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared", "deviations": [],
        }},
    ))
    package = tmp_path / "included-locators-package"
    exported = service.export_replication_package(
        frozen.protocol_id, str(package), include_locators=True
    )
    verify_replication_package(package, exported["package_manifest_sha256"])

    datasets_path = package / "datasets.json"
    datasets = json.loads(datasets_path.read_text())
    assert datasets[0]["dataset_id"] == dataset.dataset_id
    datasets[0]["name"] = "Tampered dataset identity"
    datasets_path.write_text(json.dumps(datasets, indent=2, sort_keys=True) + "\n")
    manifest_path = package / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["datasets.json"] = hashlib.sha256(datasets_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="dataset .* payload"):
        verify_replication_package(package, commitment)

    package = tmp_path / "included-locators-protocol-package"
    exported = service.export_replication_package(
        frozen.protocol_id, str(package), include_locators=True
    )
    verify_replication_package(package, exported["package_manifest_sha256"])
    protocol_path = package / "protocol.json"
    protocol_record = json.loads(protocol_path.read_text())
    protocol_record["title"] = "Tampered after package export"
    protocol_path.write_text(json.dumps(protocol_record, indent=2, sort_keys=True) + "\n")
    manifest_path = package / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["protocol.json"] = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="protocol content"):
        verify_replication_package(package, commitment)

    package = tmp_path / "included-locators-run-package"
    exported = service.export_replication_package(
        frozen.protocol_id, str(package), include_locators=True
    )
    verify_replication_package(package, exported["package_manifest_sha256"])
    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    assert runs[0]["run_id"] == recorded.run_id
    runs[0]["summary"] = "Tampered after package export"
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    manifest_path = package / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["runs.json"] = hashlib.sha256(runs_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="run .* payload"):
        verify_replication_package(package, commitment)
