from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import pytest

from research_machine.design.causal import audit_causal_identification
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
    AnalysisContract,
    CanaryTargetPlan,
    ClaimLevel,
    ConclusionContract,
    ControlDefinition,
    DatasetArtifact,
    DatasetManifest,
    DatasetRole,
    EvidenceDirection,
    MeasurementDefinition,
    MeasurementRole,
    MeasurementValidityCheck,
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


def _canonical_payload_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _instrument_inspection_record() -> dict:
    source_sha256 = "1" * 64
    implementation_sha256 = "2" * 64
    return {
        "instrument_inspection_version": 1,
        "adapter": {
            "addon_id": "fixture_instrument",
            "addon_version": "1.0.0",
            "adapter_id": "fixture_scope",
            "authority": "acquisition_metadata_proposal_only",
            "implementation": {
                "locator": "research_addon.py",
                "sha256": implementation_sha256,
                "size_bytes": 100,
            },
        },
        "source": {
            "locator": "capture.bin",
            "sha256": source_sha256,
            "size_bytes": 8,
            "media_type": "application/octet-stream",
        },
        "config": {
            "captured_at": "2026-09-06T12:00:00Z",
            "instrument_identifier": "scope-fixture-01",
        },
        "proposed_raw_source": {
            "locator": "capture.bin",
            "sha256": source_sha256,
            "captured_at": "2026-09-06T12:00:00Z",
            "acquisition_method": "Synthetic fixture acquisition.",
        },
        "instrument": {
            "identifier": "scope-fixture-01",
            "model": "Fixture scope",
            "firmware_version": "",
            "captured_at_basis": "device_metadata",
            "native_metadata": {"fixture": True},
        },
        "temporal_metadata": {
            "status": "proposed_unverified",
            "stream_count": 1,
            "limitations": [
                "Synthetic fixture stream timing remains unverified.",
            ],
        },
        "streams": [{
            "stream_id": "stream-main",
            "source_device": "scope-fixture-01",
            "channel": "main",
            "sample_rate_hz": 256,
            "clock_source": "device clock",
            "start_time": "2026-09-06T12:00:00Z",
            "clock_drift": {
                "estimate": 0.2,
                "uncertainty": 0.05,
                "unit": "ms",
                "basis": "manufacturer sidecar",
            },
            "missing_intervals": [{
                "start_time": "2026-09-06T12:00:01Z",
                "end_time": "2026-09-06T12:00:02Z",
                "reason": "Dropped packet fixture",
            }],
            "calibration_record": "clock-sync-record-1",
            "quality_flags": ["synthetic-fixture"],
            "raw_file_sha256": source_sha256,
            "conversion_code_sha256": implementation_sha256,
        }],
        "warnings": ["Synthetic adapter fixture."],
        "status": "inspection_recorded",
        "scientific_evidence_eligible": False,
        "authorized_actions": [],
        "conclusion_ceiling": (
            "Adapter-proposed acquisition metadata bound to core-hashed source bytes. "
            "No calibration, quality gate, custody chain, dataset, or evidence is approved."
        ),
    }


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
    "dataset_unredacted_locator", "dataset_duplicate_digest",
    "dataset_padded_locator", "dataset_bad_hash", "dataset_negative_size",
    "dataset_bad_metadata", "dataset_padded_media_type",
    "protocol_id_padded_everywhere", "manifest_dataset_id_padded",
    "dataset_id_padded_everywhere", "run_id_padded_everywhere",
    "run_dataset_id_padded",
    "protocol_gate_duplicate", "protocol_gate_padded", "output_unredacted_locator",
    "output_duplicate_digest", "output_padded_locator", "output_bad_hash",
    "output_negative_size", "output_bad_metadata", "output_padded_media_type",
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
        dataset_ids=[dataset.dataset_id],
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
    elif mutation == "protocol_id_padded_everywhere":
        protocol_path = package / "protocol.json"
        datasets_path = package / "datasets.json"
        runs_path = package / "runs.json"
        manifest_path = package / "package-manifest.json"
        protocol_record = json.loads(protocol_path.read_text())
        datasets = json.loads(datasets_path.read_text())
        runs = json.loads(runs_path.read_text())
        manifest = json.loads(manifest_path.read_text())
        padded = f" {protocol_record['protocol_id']} "
        protocol_record["protocol_id"] = padded
        manifest["protocol"]["protocol_id"] = padded
        datasets[0]["protocol_id"] = padded
        runs[0]["protocol_id"] = padded
        protocol_path.write_text(json.dumps(protocol_record, indent=2, sort_keys=True) + "\n")
        datasets_path.write_text(json.dumps(datasets, indent=2, sort_keys=True) + "\n")
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        manifest["files"]["protocol.json"] = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
        manifest["files"]["datasets.json"] = hashlib.sha256(datasets_path.read_bytes()).hexdigest()
        manifest["files"]["runs.json"] = hashlib.sha256(runs_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "manifest_dataset_id_padded":
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["dataset_ids"] = [f" {manifest['dataset_ids'][0]} "]
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "dataset_id_padded_everywhere":
        datasets_path = package / "datasets.json"
        runs_path = package / "runs.json"
        manifest_path = package / "package-manifest.json"
        datasets = json.loads(datasets_path.read_text())
        runs = json.loads(runs_path.read_text())
        manifest = json.loads(manifest_path.read_text())
        padded = f" {datasets[0]['dataset_id']} "
        datasets[0]["dataset_id"] = padded
        runs[0]["dataset_ids"] = [padded]
        manifest["dataset_ids"] = [padded]
        datasets_path.write_text(json.dumps(datasets, indent=2, sort_keys=True) + "\n")
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        manifest["files"]["datasets.json"] = hashlib.sha256(datasets_path.read_bytes()).hexdigest()
        manifest["files"]["runs.json"] = hashlib.sha256(runs_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "run_id_padded_everywhere":
        runs_path = package / "runs.json"
        manifest_path = package / "package-manifest.json"
        runs = json.loads(runs_path.read_text())
        manifest = json.loads(manifest_path.read_text())
        padded = f" {runs[0]['run_id']} "
        runs[0]["run_id"] = padded
        manifest["run_ids"] = [padded]
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        manifest["files"]["runs.json"] = hashlib.sha256(runs_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation == "run_dataset_id_padded":
        runs_path = package / "runs.json"
        runs = json.loads(runs_path.read_text())
        runs[0]["dataset_ids"] = [f" {runs[0]['dataset_ids'][0]} "]
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["runs.json"] = hashlib.sha256(runs_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
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
        runs[0]["synthetic"] = False
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
    elif mutation in {
        "dataset_unredacted_locator",
        "dataset_duplicate_digest",
        "dataset_padded_locator",
        "dataset_bad_hash",
        "dataset_negative_size",
        "dataset_bad_metadata",
        "dataset_padded_media_type",
    }:
        datasets_path = package / "datasets.json"
        datasets = json.loads(datasets_path.read_text())
        artifact = datasets[0]["artifacts"][0]
        if mutation == "dataset_unredacted_locator":
            artifact["locator"] = "observations.csv"
        elif mutation == "dataset_duplicate_digest":
            duplicate = dict(artifact)
            duplicate["locator"] = "duplicate-digest.csv"
            datasets[0]["artifacts"].append(duplicate)
        elif mutation == "dataset_padded_locator":
            artifact["locator"] = f" {artifact['locator']} "
        elif mutation == "dataset_bad_hash":
            artifact["sha256"] = "A" * 64
        elif mutation == "dataset_negative_size":
            artifact["size_bytes"] = -1
        elif mutation == "dataset_bad_metadata":
            artifact["metadata"] = []
        elif mutation == "dataset_padded_media_type":
            artifact["media_type"] = f" {artifact['media_type']} "
        datasets_path.write_text(json.dumps(datasets, indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["datasets.json"] = hashlib.sha256(datasets_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    elif mutation in {
        "output_unredacted_locator",
        "output_duplicate_digest",
        "output_padded_locator",
        "output_bad_hash",
        "output_negative_size",
        "output_bad_metadata",
        "output_padded_media_type",
    }:
        runs_path = package / "runs.json"
        runs = json.loads(runs_path.read_text())
        artifact = runs[0]["output_artifacts"][0]
        if mutation == "output_unredacted_locator":
            artifact["locator"] = "result.json"
        elif mutation == "output_duplicate_digest":
            duplicate = dict(artifact)
            duplicate["locator"] = "duplicate-digest.json"
            runs[0]["output_artifacts"].append(duplicate)
        elif mutation == "output_padded_locator":
            artifact["locator"] = f" {artifact['locator']} "
        elif mutation == "output_bad_hash":
            artifact["sha256"] = "A" * 64
        elif mutation == "output_negative_size":
            artifact["size_bytes"] = -1
        elif mutation == "output_bad_metadata":
            artifact["metadata"] = []
        elif mutation == "output_padded_media_type":
            artifact["media_type"] = f" {artifact['media_type']} "
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


def test_replication_package_rejects_padded_lineage_source_ids(
    tmp_path: Path,
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path / "workspace"), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Test", "Question", "test"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Statement",
        observable_prediction="Prediction",
        null_model="Null",
        falsification_conditions=["Failure"],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test",
        title="Test",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id],
        primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL,
        methodology="Method",
        quality_requirements=["gate"],
        controls=["control"],
        expected_outputs=["output"],
        success_conditions=["success"],
        environment_requirements=["environment"],
        sample_size_or_stopping_rule="one",
        failure_conditions=["failure"],
        safety_constraints=["safe"],
        analysis_code_hash="a" * 64,
    ))
    frozen = service.freeze_protocol(protocol.protocol_id)
    source = service.register_dataset(RegisterDataset(
        name="Synthetic source observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("source.csv", "c" * 64)],
        protocol_id=frozen.protocol_id,
        synthetic=True,
        quality_attestations=["Synthetic package fixture."],
    ))
    derived = service.register_dataset(RegisterDataset(
        name="Synthetic derived observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("derived.csv", "d" * 64)],
        source_dataset_ids=[source.dataset_id],
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
        dataset_ids=[derived.dataset_id],
        output_artifacts=[DatasetArtifact(
            "result.json",
            output_hash,
            output.stat().st_size,
            "application/json",
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "gate",
            QualityGateStatus.PASSED,
            "Synthetic package fixture passed.",
            details={"evidence_sha256": output_hash},
        )],
        summary="Synthetic package fixture.",
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared",
            "deviations": [],
        }},
    ))
    exported = service.export_replication_package(
        frozen.protocol_id,
        str(tmp_path / "package"),
    )
    package = tmp_path / "package"
    verify_replication_package(package, exported["package_manifest_sha256"])

    datasets_path = package / "datasets.json"
    datasets = json.loads(datasets_path.read_text())
    for dataset in datasets:
        if dataset["dataset_id"] == derived.dataset_id:
            dataset["source_dataset_ids"] = [f" {source.dataset_id} "]
            break
    else:
        raise AssertionError("derived fixture dataset was not exported")
    datasets_path.write_text(json.dumps(datasets, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "datasets.json")

    with pytest.raises(ValidationError, match="source_dataset_ids item"):
        verify_replication_package(package, commitment)


def test_redacted_replication_package_allows_multiple_artifacts(
    tmp_path: Path,
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path / "workspace"), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Test", "Question", "test"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Statement",
        observable_prediction="Prediction",
        null_model="Null",
        falsification_conditions=["Failure"],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test",
        title="Test",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id],
        primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL,
        methodology="Method",
        quality_requirements=["gate"],
        controls=["control"],
        expected_outputs=["primary result", "diagnostic result"],
        success_conditions=["success"],
        environment_requirements=["environment"],
        sample_size_or_stopping_rule="one",
        failure_conditions=["failure"],
        safety_constraints=["safe"],
        analysis_code_hash="a" * 64,
    ))
    frozen = service.freeze_protocol(protocol.protocol_id)
    dataset = service.register_dataset(RegisterDataset(
        name="Synthetic observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[
            DatasetArtifact("observations.csv", "d" * 64),
            DatasetArtifact("observations-sidecar.json", "c" * 64),
        ],
        protocol_id=frozen.protocol_id,
        synthetic=True,
        quality_attestations=["Synthetic package fixture."],
    ))
    primary_output = tmp_path / "primary-result.json"
    diagnostic_output = tmp_path / "diagnostic-result.json"
    primary_output.write_text('{"primary":"passed"}\n', encoding="utf-8")
    diagnostic_output.write_text('{"diagnostic":"retained"}\n', encoding="utf-8")
    primary_hash = hashlib.sha256(primary_output.read_bytes()).hexdigest()
    diagnostic_hash = hashlib.sha256(diagnostic_output.read_bytes()).hexdigest()
    started_at, completed_at = _after_registration_times(
        frozen.registration_timestamp
    )
    service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at=started_at,
        completed_at=completed_at,
        analysis_code_hash="a" * 64,
        environment_hash="e" * 64,
        dataset_ids=[dataset.dataset_id],
        output_artifacts=[
            DatasetArtifact(
                primary_output.name,
                primary_hash,
                primary_output.stat().st_size,
                "application/json",
            ),
            DatasetArtifact(
                diagnostic_output.name,
                diagnostic_hash,
                diagnostic_output.stat().st_size,
                "application/json",
            ),
        ],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "gate",
            QualityGateStatus.PASSED,
            "Synthetic package fixture passed.",
            details={"evidence_sha256": primary_hash},
        )],
        summary="Synthetic package fixture with multiple outputs.",
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared",
            "deviations": [],
        }},
    ))
    exported = service.export_replication_package(
        frozen.protocol_id,
        str(tmp_path / "package"),
    )
    package = tmp_path / "package"
    verified = verify_replication_package(package, exported["package_manifest_sha256"])
    packaged_datasets = json.loads((package / "datasets.json").read_text())
    packaged_runs = json.loads((package / "runs.json").read_text())
    dataset_artifacts = packaged_datasets[0]["artifacts"]
    output_artifacts = packaged_runs[0]["output_artifacts"]
    assert verified["status"] == "passed"
    assert [item["locator"] for item in dataset_artifacts] == [
        "[redacted: obtain from authorized source]",
        "[redacted: obtain from authorized source]",
    ]
    assert {item["sha256"] for item in dataset_artifacts} == {"d" * 64, "c" * 64}
    assert [item["locator"] for item in output_artifacts] == [
        "[redacted: obtain from authorized source]",
        "[redacted: obtain from authorized source]",
    ]
    assert {item["sha256"] for item in output_artifacts} == {primary_hash, diagnostic_hash}


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


def test_replication_package_verifies_instrument_inspection_gate_metadata(
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
    record_path = tmp_path / "instrument-inspection.json"
    record = _instrument_inspection_record()
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
            "Synthetic instrument-inspection fixture was retained.",
            details={
                "evidence_sha256": record_sha256,
                "instrument_inspection": {
                    "locator": record_path.name,
                    "sha256": record_sha256,
                    "status": "inspection_recorded",
                    "source_sha256": record["source"]["sha256"],
                    "config_sha256": _canonical_payload_sha256(record["config"]),
                    "implementation_sha256": record["adapter"]["implementation"]["sha256"],
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
    runs[0]["quality_gates"][0]["details"]["instrument_inspection"][
        "status"
    ] = "inspection_failed"
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match="status is unsupported"):
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


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_assessment", "structured canary_target_assessment"),
        ("assignment_mismatch", "assignment artifact disagrees"),
        ("unknown_comparator", "comparator targets are not in the frozen candidate set"),
        ("revealed_as_comparator", "must not include the revealed target"),
        ("padded_status", "assessment_status must be canonical"),
        ("bad_status", "assessment_status is unsupported"),
        ("wrong_evidence", "is not a declared output artifact"),
        ("gate_evidence_mismatch", "does not match gate evidence"),
        ("wrong_gate", "is not bound to the frozen canary gate"),
    ],
)
def test_replication_package_verifies_canary_target_gate_metadata(
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
    plan = CanaryTargetPlan(
        plan_id="masked-canary-plan",
        candidate_target_ids=["actual-state", "delayed-replay", "silent-marker"],
        seed_commitment_sha256="1" * 64,
        assignment_artifact_sha256="2" * 64,
        masking_plan="Synthetic package fixture masking plan.",
        ethical_disclosure="Synthetic package fixture disclosure.",
        assessment_gate_id="canary-target-assessed",
    )
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test", title="Test", analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id], primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL, methodology="Method",
        quality_requirements=["canary-target-assessed"],
        controls=["control"], expected_outputs=["output"], success_conditions=["success"],
        environment_requirements=["environment"], sample_size_or_stopping_rule="one",
        failure_conditions=["failure"], safety_constraints=["safe"], analysis_code_hash="a" * 64,
        canary_target_plan=plan,
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
    record_path = tmp_path / "canary-output.json"
    record_sha256 = _write_json(
        record_path,
        {
            "canary": {
                "comparison": {
                    "revealed_target_id": "actual-state",
                    "status": "follows_comparator_or_decoy",
                }
            }
        },
    )
    alternate_path = tmp_path / "alternate-canary-output.json"
    alternate_sha256 = _write_json(
        alternate_path,
        {"canary": {"comparison": {"status": "alternate-fixture"}}},
    )
    started_at, completed_at = _after_registration_times(
        frozen.registration_timestamp
    )
    service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at=started_at,
        completed_at=completed_at,
        analysis_code_hash="a" * 64,
        environment_hash="e" * 64,
        output_artifacts=[
            DatasetArtifact(
                record_path.name,
                record_sha256,
                record_path.stat().st_size,
                "application/json",
            ),
            DatasetArtifact(
                alternate_path.name,
                alternate_sha256,
                alternate_path.stat().st_size,
                "application/json",
            ),
        ],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "canary-target-assessed",
            QualityGateStatus.PASSED,
            "Synthetic canary target fixture retained.",
            details={
                "evidence_sha256": record_sha256,
                "canary_target_assessment": {
                    "plan_id": "masked-canary-plan",
                    "assignment_artifact_sha256": "2" * 64,
                    "revealed_target_id": "actual-state",
                    "comparator_target_ids": ["delayed-replay"],
                    "assessment_status": "follows_comparator_or_decoy",
                    "observed_pattern": "The synthetic fixture followed the comparator target.",
                    "interpretation": "Bounded fixture interpretation; no mechanism or intent claim.",
                    "evidence_sha256": record_sha256,
                    "evidence_location": "/canary/comparison",
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
    assessment = gate["details"]["canary_target_assessment"]
    if mutation == "missing_assessment":
        del gate["details"]["canary_target_assessment"]
    elif mutation == "assignment_mismatch":
        assessment["assignment_artifact_sha256"] = "3" * 64
    elif mutation == "unknown_comparator":
        assessment["comparator_target_ids"] = ["unknown-target"]
    elif mutation == "revealed_as_comparator":
        assessment["comparator_target_ids"] = ["actual-state"]
    elif mutation == "padded_status":
        assessment["assessment_status"] = " follows_comparator_or_decoy"
    elif mutation == "bad_status":
        assessment["assessment_status"] = "confirmed"
    elif mutation == "wrong_evidence":
        assessment["evidence_sha256"] = "f" * 64
    elif mutation == "gate_evidence_mismatch":
        gate["details"]["evidence_sha256"] = runs[0]["output_artifacts"][1]["sha256"]
    elif mutation == "wrong_gate":
        gate["gate_id"] = "other-gate"
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match=message):
        verify_replication_package(package, commitment)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_disclosure", "requires protocol_deviation_disclosure"),
        ("missing_field", "fields are invalid"),
        ("bad_status", "status is invalid"),
        ("missing_auto", "automatic_evidence_eligible must be a boolean"),
        ("wrong_auto", "eligibility disagrees with status"),
        ("status_disagrees", "status disagrees with deviations"),
        ("missing_deviation_field", "exact documented fields"),
        ("duplicate_deviation", "repeats protocol deviation_id"),
        ("bad_timing", "timing is invalid"),
        ("bad_impact", "potential_impact is invalid"),
        ("padded_stage", "stage must be canonical"),
        ("unbound_evidence", "must reference a run output artifact"),
        ("blank_location", "evidence_location must not be empty"),
        ("rewritten_boundary", "boundary is invalid"),
    ],
)
def test_replication_package_verifies_protocol_deviation_disclosure(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path / "workspace"), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Test", "Question", "test"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Statement", observable_prediction="Prediction", null_model="Null",
        falsification_conditions=["Failure"],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test",
        title="Test",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id],
        primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL,
        methodology="Method",
        quality_requirements=["gate"],
        controls=["control"],
        expected_outputs=["output"],
        success_conditions=["success"],
        environment_requirements=["environment"],
        sample_size_or_stopping_rule="one",
        failure_conditions=["failure"],
        safety_constraints=["safe"],
        analysis_code_hash="a" * 64,
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
    output = tmp_path / "deviation-output.json"
    output.write_text('{"deviation":{"solver_tolerance":"loose"}}\n', encoding="utf-8")
    output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    disclosure = {
        "status": "deviations_declared",
        "deviations": [{
            "deviation_id": "dev-1",
            "stage": "analysis",
            "frozen_commitment": "Use the registered solver tolerance.",
            "actual_method": "Used a looser tolerance after convergence failed.",
            "reason": "The registered tolerance did not converge.",
            "timing": "after_results_seen",
            "potential_impact": "potentially_material",
            "corrective_action": "Repeat both tolerances and report all results.",
            "evidence_sha256": output_hash,
            "evidence_location": "/deviation/solver_tolerance",
        }],
    }
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
            output.name,
            output_hash,
            output.stat().st_size,
            "application/json",
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "gate",
            QualityGateStatus.PASSED,
            "Synthetic package fixture passed.",
            details={"evidence_sha256": output_hash},
        )],
        summary="Synthetic package fixture with a declared deviation.",
        metadata={"protocol_deviation_disclosure": disclosure},
    ))
    exported = service.export_replication_package(
        frozen.protocol_id,
        str(tmp_path / "package"),
    )
    package = tmp_path / "package"
    verify_replication_package(package, exported["package_manifest_sha256"])

    runs_path = package / "runs.json"
    runs = json.loads(runs_path.read_text())
    disclosure = runs[0]["metadata"]["protocol_deviation_disclosure"]
    deviation = disclosure["deviations"][0]
    if mutation == "missing_disclosure":
        del runs[0]["metadata"]["protocol_deviation_disclosure"]
    elif mutation == "missing_field":
        del disclosure["interpretation_boundary"]
    elif mutation == "bad_status":
        disclosure["status"] = "resolved"
    elif mutation == "missing_auto":
        del disclosure["automatic_evidence_eligible"]
    elif mutation == "wrong_auto":
        disclosure["automatic_evidence_eligible"] = True
    elif mutation == "status_disagrees":
        disclosure["status"] = "no_deviations_declared"
        disclosure["automatic_evidence_eligible"] = True
    elif mutation == "missing_deviation_field":
        del deviation["actual_method"]
    elif mutation == "duplicate_deviation":
        disclosure["deviations"].append(dict(deviation))
    elif mutation == "bad_timing":
        deviation["timing"] = "after_reassuring_results"
    elif mutation == "bad_impact":
        deviation["potential_impact"] = "beneficial"
    elif mutation == "padded_stage":
        deviation["stage"] = " analysis"
    elif mutation == "unbound_evidence":
        deviation["evidence_sha256"] = "f" * 64
    elif mutation == "blank_location":
        deviation["evidence_location"] = ""
    elif mutation == "rewritten_boundary":
        disclosure["interpretation_boundary"] = "No deviations means the run followed the protocol."
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match=message):
        verify_replication_package(package, commitment)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_check", "requires sample_size_plan_check"),
        ("stripped_to_status", "fields are invalid"),
        ("forged_pass", "no longer matches"),
        ("altered_required_count", "no longer matches"),
        ("altered_observed_attrition", "no longer matches"),
        ("rewritten_attrition_result", "no longer matches"),
        ("rewritten_precision_result", "no longer matches"),
        ("rewritten_variance_result", "no longer matches"),
        ("padded_strategy", "strategy must be canonical"),
        ("bad_specification_hash", "specification_sha256 must be 64 lowercase"),
        ("claims_interpretation_verified", "must not verify scientific interpretation"),
    ],
)
def test_replication_package_verifies_sample_size_plan_check_metadata(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path / "workspace"), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Test", "Question", "test"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Statement",
        observable_prediction="Prediction",
        null_model="Null",
        falsification_conditions=["Failure"],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    planning_input = {
        "strategy": "power",
        "specification": {
            "study_design": "independent_groups",
            "smallest_effect_size_of_interest": 0.5,
            "assumed_standard_deviation": 1.0,
            "alpha": 0.05,
            "target_power": 0.8,
            "alternative": "two_sided",
            "anticipated_attrition_fraction": 0.1,
        },
        "justification": (
            "Synthetic fixture planning receipt for package verification."
        ),
    }
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test",
        title="Test",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id],
        primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL,
        methodology="Method",
        quality_requirements=["integrity"],
        controls=["control"],
        expected_outputs=["output"],
        success_conditions=["success"],
        environment_requirements=["environment"],
        sample_size_or_stopping_rule=(
            "Enroll according to the machine-recomputed planning receipt."
        ),
        sample_size_plan=planning_input,
        failure_conditions=["failure"],
        safety_constraints=["safe"],
        analysis_code_hash="a" * 64,
    ))
    frozen = service.freeze_protocol(protocol.protocol_id)
    output = tmp_path / "sample-plan-output.json"
    output.write_text('{"result":"complete"}\n', encoding="utf-8")
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
            output.name,
            output_hash,
            output.stat().st_size,
            "application/json",
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(
            "integrity",
            QualityGateStatus.PASSED,
            "Synthetic package fixture passed.",
            details={"evidence_sha256": output_hash},
        )],
        summary="Synthetic package fixture with an unbound planning check.",
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared",
            "deviations": [],
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
    check = runs[0]["metadata"]["sample_size_plan_check"]
    if mutation == "missing_check":
        del runs[0]["metadata"]["sample_size_plan_check"]
    elif mutation == "stripped_to_status":
        runs[0]["metadata"]["sample_size_plan_check"] = {"status": "passed"}
    elif mutation == "forged_pass":
        check["status"] = "passed"
        check["execution_information_check_verified"] = True
        runs[0]["scientific_evidence_eligible"] = True
    elif mutation == "altered_required_count":
        check["required_analyzable_units_per_group"] += 1
    elif mutation == "altered_observed_attrition":
        check["observed_excluded_fraction"] = 0.0
    elif mutation == "rewritten_attrition_result":
        check["attrition_achievement"] = {
            "status": "within_assumption",
            "anticipated_attrition_fraction": 0.1,
            "observed_excluded_fraction": 0.0,
            "scientific_interpretation_verified": True,
        }
    elif mutation == "rewritten_precision_result":
        check["precision_achievement"]["reason"] = (
            "Planning precision was achieved."
        )
    elif mutation == "rewritten_variance_result":
        check["variance_assumption"]["status"] = (
            "observed_no_preregistered_tolerance"
        )
    elif mutation == "padded_strategy":
        check["strategy"] = f" {check['strategy']}"
    elif mutation == "bad_specification_hash":
        check["specification_sha256"] = "A" * 64
    elif mutation == "claims_interpretation_verified":
        check["scientific_interpretation_verified"] = True
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match=message):
        verify_replication_package(package, commitment)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_results", "requires exact evaluations"),
        ("missing_control", "requires exact evaluations"),
        ("extra_control", "requires exact evaluations"),
        ("missing_field", "requires an exact evaluation"),
        ("non_boolean_match", "matches_expected must be a boolean"),
        ("unbound_evidence", "must reference a run output artifact"),
        ("blank_location", "evidence_location must be nonempty text"),
    ],
)
def test_replication_package_verifies_control_gate_metadata(
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
    control = ControlDefinition(
        "negative-1",
        "Negative control",
        "negative",
        "Detect false acceptance.",
        "No effect estimate should clear the fixture rule.",
        "control-gate",
    )
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test", title="Test", analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id], primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL, methodology="Method",
        quality_requirements=["control-gate"],
        controls=["Negative control"], control_definitions=[control],
        expected_outputs=["output"], success_conditions=["success"],
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
    record_path = tmp_path / "control-output.json"
    record_sha256 = _write_json(
        record_path,
        {"controls": {"negative-1": {"matches_expected": True}}},
    )
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
            "control-gate",
            QualityGateStatus.PASSED,
            "Synthetic control fixture was evaluated.",
            details={
                "evidence_sha256": record_sha256,
                "control_results": {
                    "negative-1": {
                        "observed_behavior": "The synthetic negative control did not clear the fixture rule.",
                        "interpretation": "Fixture-only control interpretation.",
                        "matches_expected": True,
                        "evidence_sha256": record_sha256,
                        "evidence_location": "/controls/negative-1",
                    }
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
    results = gate["details"]["control_results"]
    if mutation == "missing_results":
        del gate["details"]["control_results"]
    elif mutation == "missing_control":
        del results["negative-1"]
    elif mutation == "extra_control":
        results["unregistered-control"] = dict(results["negative-1"])
    elif mutation == "missing_field":
        del results["negative-1"]["interpretation"]
    elif mutation == "non_boolean_match":
        results["negative-1"]["matches_expected"] = "true"
    elif mutation == "unbound_evidence":
        results["negative-1"]["evidence_sha256"] = "f" * 64
    elif mutation == "blank_location":
        results["negative-1"]["evidence_location"] = ""
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match=message):
        verify_replication_package(package, commitment)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_results", "requires exact results"),
        ("missing_check", "requires exact results"),
        ("extra_check", "requires exact results"),
        ("missing_field", "documented fields"),
        ("wrong_evidence_type", "evidence_type does not match"),
        ("wrong_status", "passed measurement validity gate requires"),
        ("padded_status", "assessment_status must be canonical"),
        ("unbound_evidence", "must reference a run output artifact"),
        ("blank_diagnostic", "observed_diagnostic must be nonempty text"),
    ],
)
def test_replication_package_verifies_measurement_validity_gate_metadata(
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
    measurement = MeasurementDefinition(
        measurement_id="primary-measurement",
        role=MeasurementRole.PRIMARY,
        registered_target="Outcome",
        observable="Synthetic acceptance indicator",
        input_condition="Synthetic fixture input.",
        parameter_values={"parser": "fixture"},
        evaluation_point="After fixture replay.",
        convention="One indicates acceptance and zero indicates rejection.",
        aggregation="One value per fixture unit.",
        tolerance="Exact JSON value.",
        expected_behavior="Retain the fixture indicator.",
        data_column="acceptance",
        temporal_role="not_applicable",
        scale_type="binary",
        unit="indicator",
        admissible_values=["0", "1"],
        missing_value_codes=["<blank>"],
    )
    control_measurement = MeasurementDefinition(
        measurement_id="control-measurement",
        role=MeasurementRole.CONTROL,
        registered_target="Control",
        observable="Synthetic control transcript",
        input_condition="Synthetic control input.",
        parameter_values={"parser": "fixture"},
        evaluation_point="During fixture replay.",
        convention="Retain the control transcript.",
        aggregation="One transcript.",
        tolerance="Exact retained text.",
        expected_behavior="The control transcript is retained.",
    )
    check = MeasurementValidityCheck(
        check_id="checker-reference-agreement",
        measurement_id="primary-measurement",
        evidence_type="criterion",
        validity_claim="The parsed indicator agrees with the retained checker transcript.",
        assessment_plan="Compare the JSON indicator with the retained transcript.",
        acceptance_criterion="The indicator and transcript agree exactly.",
        failure_response="Stop interpretation and repair the parser.",
        assessment_gate_id="measurement-validity-assessed",
    )
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test", title="Test", analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id], primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL, methodology="Method",
        quality_requirements=["proof-check", "measurement-validity-assessed"],
        controls=["Control"], expected_outputs=["output"], success_conditions=["success"],
        environment_requirements=["environment"], sample_size_or_stopping_rule="one",
        failure_conditions=["failure"], safety_constraints=["safe"], analysis_code_hash="a" * 64,
        measurement_definitions=[measurement, control_measurement],
        measurement_validity_checks=[check],
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
    record_path = tmp_path / "validity-output.json"
    record_sha256 = _write_json(
        record_path,
        {"validity": {"checker-reference-agreement": {"acceptance": 1}}},
    )
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
        quality_gates=[
            QualityGateResult(
                "proof-check",
                QualityGateStatus.PASSED,
                "Synthetic proof fixture passed.",
                details={"evidence_sha256": record_sha256},
            ),
            QualityGateResult(
                "measurement-validity-assessed",
                QualityGateStatus.PASSED,
                "Synthetic validity fixture passed.",
                details={
                    "evidence_sha256": record_sha256,
                    "measurement_validity_results": {
                        "checker-reference-agreement": {
                            "observed_diagnostic": "The parsed indicator matched the transcript.",
                            "interpretation": "Fixture consistency only; no validity proof.",
                            "assessment_status": "consistent_with_validity_claim",
                            "evidence_type": "criterion",
                            "evidence_sha256": record_sha256,
                            "evidence_location": "/validity/checker-reference-agreement",
                        }
                    },
                },
            ),
        ],
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
    gate = next(
        item for item in runs[0]["quality_gates"]
        if item["gate_id"] == "measurement-validity-assessed"
    )
    results = gate["details"]["measurement_validity_results"]
    result = results["checker-reference-agreement"]
    if mutation == "missing_results":
        del gate["details"]["measurement_validity_results"]
    elif mutation == "missing_check":
        del results["checker-reference-agreement"]
    elif mutation == "extra_check":
        results["invented-check"] = dict(result)
    elif mutation == "missing_field":
        del result["interpretation"]
    elif mutation == "wrong_evidence_type":
        result["evidence_type"] = "attestation"
    elif mutation == "wrong_status":
        result["assessment_status"] = "inconclusive"
    elif mutation == "padded_status":
        result["assessment_status"] = " consistent_with_validity_claim"
    elif mutation == "unbound_evidence":
        result["evidence_sha256"] = "f" * 64
    elif mutation == "blank_diagnostic":
        result["observed_diagnostic"] = ""
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match=message):
        verify_replication_package(package, commitment)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_result", "requires one exact result"),
        ("missing_field", "requires one exact result"),
        ("wrong_kind", "assessment_kind does not match"),
        ("wrong_status", "passed missingness assessment gate requires"),
        ("padded_status", "assessment_status must be canonical"),
        ("bad_status", "unsupported assessment_status"),
        ("unbound_evidence", "must reference a run output artifact"),
        ("blank_interpretation", "interpretation must be nonempty text"),
    ],
)
def test_replication_package_verifies_missingness_gate_metadata(
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
        primary_estimand="Mean outcome difference, group a minus group b.",
        contrast_definition="group a minus group b",
        contrast_groups=["a", "b"],
        expected_effect_direction="positive",
        falsification_conditions=["Failure"],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    measurement = MeasurementDefinition(
        measurement_id="primary-measurement",
        role=MeasurementRole.PRIMARY,
        registered_target="Outcome",
        observable="Synthetic outcome value",
        input_condition="Synthetic fixture input.",
        parameter_values={"parser": "fixture"},
        evaluation_point="Registered fixture endpoint.",
        convention="Higher is larger.",
        aggregation="Mean by registered group.",
        tolerance="Exact JSON value.",
        expected_behavior="Retain the fixture outcome.",
        data_column="outcome",
        temporal_role="not_applicable",
        scale_type="interval",
        unit="fixture units",
        valid_min=0.0,
        valid_max=100.0,
        missing_value_codes=["<blank>"],
    )
    control_measurement = MeasurementDefinition(
        measurement_id="control-measurement",
        role=MeasurementRole.CONTROL,
        registered_target="Control",
        observable="Synthetic control transcript",
        input_condition="Synthetic control input.",
        parameter_values={"parser": "fixture"},
        evaluation_point="During fixture replay.",
        convention="Retain the control transcript.",
        aggregation="One transcript.",
        tolerance="Exact retained text.",
        expected_behavior="The control transcript is retained.",
    )
    control = ControlDefinition(
        "reference-1",
        "Control",
        "reference",
        "Keep a control measurement visible.",
        "The control transcript is retained.",
        "control-gate",
    )
    analysis = AnalysisContract(
        primary_hypothesis_id=hypothesis.hypothesis_id,
        primary_measurement_id="primary-measurement",
        method="independent_mean_difference_ci",
        outcome_column="outcome",
        group_column="group",
        groups=["a", "b"],
        estimand="Mean outcome difference, group a minus group b.",
        missing_data_policy="complete_case",
        assignment_type="observational",
        effect_estimate_path="/result/mean_difference_first_minus_second",
        uncertainty_path="/result/confidence_interval",
        null_value=0.0,
        support_rule="interval_excludes_null",
        minimum_analyzable_units=2,
        maximum_excluded_fraction=0.25,
        maximum_group_excluded_fraction_difference=0.25,
        missingness_assumption="Excluded records do not materially distort the contrast.",
        missingness_assessment_plan="Inspect total and group-specific exclusions before interpretation.",
        missingness_failure_response="Stop primary interpretation.",
        missingness_assessment_kind="empirical_diagnostic",
        missingness_assessment_gate_id="missingness-assessed",
        confidence_level=0.95,
        contrast_definition="group a minus group b",
        contrast_groups=["a", "b"],
    )
    conclusion = ConclusionContract(
        primary_hypothesis_id=hypothesis.hypothesis_id,
        decision_rule="interval_and_practical_significance",
        smallest_effect_size_of_interest=1.0,
        effect_scale="mean_difference_first_minus_second",
        effect_unit="fixture units",
        population="Synthetic package fixture units.",
        setting="Synthetic package fixture setting.",
        time_window="Registered fixture endpoint.",
        non_supporting_direction=EvidenceDirection.INCONCLUSIVE,
        permitted_claim_level=ClaimLevel.STATISTICAL_ASSOCIATION,
        higher_level_conclusions_unsupported=[
            "No mechanism, causal direction, or out-of-scope generalization."
        ],
    )
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test", title="Test", analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id], primary_outcome="Outcome",
        protocol_kind=ProtocolKind.OBSERVATIONAL, methodology="Method",
        quality_requirements=["proof-check", "control-gate", "missingness-assessed"],
        controls=["Control"], control_definitions=[control],
        expected_outputs=["output"], success_conditions=["success"],
        environment_requirements=["environment"], sample_size_or_stopping_rule="one",
        sampling_unit="synthetic participant",
        independent_unit="synthetic participant",
        repeated_measures=False,
        analysis_design="independent_groups",
        unit_id_column="participant_id",
        preprocessing_pipeline="Parse the synthetic fixture table without exclusions beyond complete-case handling.",
        statistical_model="Independent mean-difference confidence interval over the registered fixture groups.",
        multiple_testing_policy="Single registered primary contrast; no multiplicity adjustment.",
        missing_data_policy="Complete-case handling with registered missingness assessment gate.",
        failure_conditions=["failure"], safety_constraints=["safe"], analysis_code_hash="a" * 64,
        measurement_definitions=[measurement, control_measurement],
        analysis_contract=analysis,
        conclusion_contract=conclusion,
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
    record_path = tmp_path / "missingness-output.json"
    record_sha256 = _write_json(
        record_path,
        {"missingness": {"exclusion_report": {"excluded_fraction": 0.0}}},
    )
    started_at, completed_at = _after_registration_times(
        frozen.registration_timestamp
    )
    service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at=started_at,
        completed_at=completed_at,
        analysis_code_hash="a" * 64,
        environment_hash="e" * 64,
        dataset_ids=[dataset.dataset_id],
        output_artifacts=[DatasetArtifact(
            record_path.name,
            record_sha256,
            record_path.stat().st_size,
            "application/json",
        )],
        artifact_root=str(tmp_path),
        quality_gates=[
            QualityGateResult(
                "proof-check",
                QualityGateStatus.PASSED,
                "Synthetic proof fixture passed.",
                details={"evidence_sha256": record_sha256},
            ),
            QualityGateResult(
                "control-gate",
                QualityGateStatus.PASSED,
                "Synthetic control fixture was retained.",
                details={
                    "evidence_sha256": record_sha256,
                    "control_results": {
                        "reference-1": {
                            "observed_behavior": "The synthetic control transcript was retained.",
                            "interpretation": "Fixture-only control interpretation.",
                            "matches_expected": True,
                            "evidence_sha256": record_sha256,
                            "evidence_location": "/controls/reference-1",
                        }
                    },
                },
            ),
            QualityGateResult(
                "missingness-assessed",
                QualityGateStatus.PASSED,
                "Synthetic missingness fixture passed.",
                details={
                    "evidence_sha256": record_sha256,
                    "missingness_assessment_result": {
                        "observed_diagnostic": "Synthetic exclusion report reviewed.",
                        "interpretation": "No fixture contradiction to the assumption was encoded.",
                        "assessment_status": "consistent_with_assumption",
                        "assessment_kind": "empirical_diagnostic",
                        "evidence_sha256": record_sha256,
                        "evidence_location": "/missingness/exclusion_report",
                    },
                },
            ),
        ],
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
    gate = next(
        item for item in runs[0]["quality_gates"]
        if item["gate_id"] == "missingness-assessed"
    )
    result = gate["details"]["missingness_assessment_result"]
    if mutation == "missing_result":
        del gate["details"]["missingness_assessment_result"]
    elif mutation == "missing_field":
        del result["interpretation"]
    elif mutation == "wrong_kind":
        result["assessment_kind"] = "substantive_judgment"
    elif mutation == "wrong_status":
        result["assessment_status"] = "inconclusive"
    elif mutation == "padded_status":
        result["assessment_status"] = " consistent_with_assumption"
    elif mutation == "bad_status":
        result["assessment_status"] = "proven_ignorable"
    elif mutation == "unbound_evidence":
        result["evidence_sha256"] = "f" * 64
    elif mutation == "blank_interpretation":
        result["interpretation"] = ""
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match=message):
        verify_replication_package(package, commitment)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_results", "requires exact results"),
        ("missing_category", "requires exact results"),
        ("extra_category", "requires exact results"),
        ("missing_field", "requires an exact result"),
        ("wrong_kind", "assessment_kind does not match"),
        ("padded_status", "assessment_status must be canonical"),
        ("bad_status", "unsupported assessment_status"),
        ("unbound_evidence", "must reference a run output artifact"),
        ("blank_location", "evidence_location must be nonempty text"),
        ("passed_contradiction", "passed causal assessment gate"),
        ("warning_without_inconclusive", "warning causal assessment gate"),
        ("failed_without_contradiction", "failed causal assessment gate"),
    ],
)
def test_replication_package_verifies_causal_assumption_gate_metadata(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    workspace = tmp_path / "workspace"
    service = ResearchService(FileSystemRepository(workspace), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Test", "Question", "test"))
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Treatment changes the registered outcome.",
        observable_prediction="The adjusted treatment-minus-control interval excludes zero.",
        null_model="The adjusted treatment-minus-control effect is zero.",
        primary_estimand="Mean outcome difference, treatment minus control.",
        contrast_definition="treatment minus control",
        contrast_groups=["treatment", "control"],
        expected_effect_direction="two_sided",
        falsification_conditions=["The registered interval remains compatible with the null."],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    assumptions = [
        {
            "category": category,
            "statement": f"Synthetic {category} assumption.",
            "assessment_kind": "design_record_review",
            "assessment_plan": f"Inspect registered diagnostics for {category}.",
            "failure_response": f"Stop causal interpretation if {category} is contradicted.",
            "assessment_gate_id": "causal-assumptions-assessed",
        }
        for category in (
            "positivity",
            "consistency",
            "interference",
            "temporal_order",
            "measurement_validity",
            "selection_bias",
            "exchangeability",
        )
    ]
    graph = {
        "nodes": [
            {"id": "treatment", "observed": True},
            {"id": "outcome", "observed": True},
            {"id": "baseline", "observed": True},
        ],
        "edges": [
            {"cause": "baseline", "effect": "treatment"},
            {"cause": "baseline", "effect": "outcome"},
            {"cause": "treatment", "effect": "outcome"},
        ],
        "exposure": "treatment",
        "outcome": "outcome",
        "proposed_adjustment_set": ["baseline"],
        "assignment_type": "observational",
        "assumptions": assumptions,
        "causal_estimand": {
            "target_hypothesis_id": hypothesis.hypothesis_id,
            "description": "Mean outcome difference, treatment minus control.",
            "population": "Synthetic package fixture units.",
            "exposure_strategies": ["assign treatment", "assign control"],
            "outcome_variable": "outcome",
            "time_zero": "At synthetic fixture assignment.",
            "outcome_time": "At the registered synthetic endpoint.",
            "contrast": "Treatment minus control.",
            "summary_measure": "Population mean difference.",
            "intercurrent_events_policy": "Retain all assigned eligible units and report missing outcomes.",
        },
    }
    audit = audit_causal_identification(graph)
    measurement = MeasurementDefinition(
        measurement_id="primary-measurement",
        role=MeasurementRole.PRIMARY,
        registered_target="outcome",
        observable="Synthetic outcome value",
        input_condition="Synthetic fixture rows.",
        parameter_values={"parser": "fixture"},
        evaluation_point="Registered synthetic endpoint.",
        convention="Higher is larger.",
        aggregation="Mean by registered exposure group.",
        tolerance="Exact JSON fixture value.",
        expected_behavior="Retain the fixture outcome regardless of direction.",
        data_column="outcome",
        temporal_role="post_exposure",
        scale_type="interval",
        unit="fixture units",
        valid_min=0.0,
        valid_max=100.0,
        missing_value_codes=["<blank>"],
    )
    exposure = MeasurementDefinition(
        measurement_id="exposure-measurement",
        role=MeasurementRole.EXPOSURE,
        registered_target="treatment",
        observable="Synthetic exposure group label",
        input_condition="At fixture assignment.",
        parameter_values={"levels": "treatment, control"},
        evaluation_point="At synthetic fixture assignment.",
        convention="treatment is contrasted against control.",
        aggregation="One label per synthetic participant.",
        tolerance="Exact registered label.",
        expected_behavior="Both registered groups remain reportable.",
        data_column="treatment",
        temporal_role="at_exposure",
        scale_type="nominal",
        unit="category",
        admissible_values=["treatment", "control"],
        missing_value_codes=["<blank>"],
    )
    covariate = MeasurementDefinition(
        measurement_id="baseline-measurement",
        role=MeasurementRole.COVARIATE,
        registered_target="baseline",
        observable="Synthetic baseline score",
        input_condition="Before synthetic exposure assignment.",
        parameter_values={"parser": "fixture"},
        evaluation_point="Registered synthetic baseline.",
        convention="Higher is larger.",
        aggregation="One score per synthetic participant.",
        tolerance="Exact fixture value.",
        expected_behavior="Retain the baseline score regardless of outcome direction.",
        data_column="baseline",
        temporal_role="pre_exposure",
        scale_type="interval",
        unit="fixture units",
        valid_min=0.0,
        valid_max=100.0,
        missing_value_codes=["<blank>"],
    )
    control_measurement = MeasurementDefinition(
        measurement_id="control-measurement",
        role=MeasurementRole.CONTROL,
        registered_target="Reference control",
        observable="Synthetic control transcript",
        input_condition="Synthetic control fixture rows.",
        parameter_values={"parser": "fixture"},
        evaluation_point="During fixture replay.",
        convention="Retain the control transcript.",
        aggregation="One transcript.",
        tolerance="Exact retained text.",
        expected_behavior="The control transcript is retained.",
    )
    control = ControlDefinition(
        "reference-1",
        "Reference control",
        "reference",
        "Keep a control measurement visible.",
        "The control transcript is retained.",
        "control-gate",
    )
    analysis = AnalysisContract(
        primary_hypothesis_id=hypothesis.hypothesis_id,
        primary_measurement_id="primary-measurement",
        method="adjusted_linear_effect",
        outcome_column="outcome",
        group_column="treatment",
        groups=["treatment", "control"],
        adjustment_columns=["baseline"],
        estimand="Mean outcome difference, treatment minus control.",
        missing_data_policy="complete_case",
        assignment_type="observational",
        effect_estimate_path="/result/adjusted_mean_difference_first_minus_second",
        uncertainty_path="/result/robust_confidence_interval",
        null_value=0.0,
        support_rule="interval_excludes_null",
        minimum_analyzable_units=2,
        maximum_excluded_fraction=0.25,
        maximum_group_excluded_fraction_difference=0.25,
        missingness_assumption="Excluded records do not materially distort the registered contrast.",
        missingness_assessment_plan="Inspect total and group-specific exclusions before interpretation.",
        missingness_failure_response="Stop primary interpretation if missingness is not defensible.",
        missingness_assessment_kind="empirical_diagnostic",
        missingness_assessment_gate_id="missingness-assessed",
        confidence_level=0.95,
        contrast_definition="treatment minus control",
        contrast_groups=["treatment", "control"],
    )
    conclusion = ConclusionContract(
        primary_hypothesis_id=hypothesis.hypothesis_id,
        decision_rule="interval_and_practical_significance",
        smallest_effect_size_of_interest=1.0,
        effect_scale="adjusted_mean_difference_first_minus_second",
        effect_unit="fixture units",
        population="Synthetic package fixture units.",
        setting="Synthetic package fixture setting.",
        time_window="Registered synthetic endpoint.",
        non_supporting_direction=EvidenceDirection.INCONCLUSIVE,
        permitted_claim_level=ClaimLevel.CAUSAL_DIRECTION,
        higher_level_conclusions_unsupported=[
            "No mechanism, adaptation, intent, or out-of-scope generalization."
        ],
    )
    protocol = service.create_protocol(CreateProtocol(
        experiment_id="test-causal-package",
        title="Synthetic causal package fixture",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis.hypothesis_id],
        primary_outcome="outcome",
        protocol_kind=ProtocolKind.OBSERVATIONAL,
        methodology="Synthetic causal package fixture; not a scientific study.",
        quality_requirements=[
            "control-gate",
            "causal-assumptions-assessed",
            "missingness-assessed",
        ],
        controls=["Reference control"],
        control_definitions=[control],
        expected_outputs=["causal diagnostics"],
        success_conditions=["Synthetic fixture runs to completion."],
        environment_requirements=["Synthetic fixture environment."],
        sample_size_or_stopping_rule="Synthetic fixed fixture rows.",
        sampling_unit="synthetic participant",
        independent_unit="synthetic participant",
        repeated_measures=False,
        analysis_design="independent_groups",
        unit_id_column="participant_id",
        preprocessing_pipeline="Parse the synthetic fixture table.",
        statistical_model="Covariate-adjusted treatment-minus-control contrast.",
        multiple_testing_policy="Single registered primary contrast.",
        missing_data_policy="Complete-case handling with registered diagnostics.",
        failure_conditions=["Stop causal interpretation if required gates fail."],
        safety_constraints=["Synthetic fixture only."],
        analysis_code_hash="a" * 64,
        measurement_definitions=[
            measurement,
            exposure,
            covariate,
            control_measurement,
        ],
        analysis_contract=analysis,
        conclusion_contract=conclusion,
        causal_claim=True,
        causal_identification=graph,
    ))
    frozen = service.freeze_protocol(protocol.protocol_id)
    dataset = service.register_dataset(RegisterDataset(
        name="Synthetic causal observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("observations.csv", "d" * 64)],
        protocol_id=frozen.protocol_id,
        synthetic=True,
        quality_attestations=["Synthetic causal package fixture."],
    ))
    record_path = tmp_path / "causal-output.json"
    record_sha256 = _write_json(
        record_path,
        {
            "diagnostics": {
                category: {"status": "consistent_with_assumption"}
                for category in (
                    "positivity",
                    "consistency",
                    "interference",
                    "temporal_order",
                    "measurement_validity",
                    "selection_bias",
                    "exchangeability",
                )
            },
            "missingness": {"excluded_fraction": 0.0},
            "controls": {"reference-1": {"matches_expected": True}},
        },
    )
    causal_results = {
        item["category"]: {
            "observed_diagnostic": f"Synthetic diagnostic reviewed for {item['category']}.",
            "interpretation": "No fixture contradiction was encoded.",
            "assessment_status": "consistent_with_assumption",
            "assessment_kind": item["assessment_kind"],
            "evidence_sha256": record_sha256,
            "evidence_location": f"/diagnostics/{item['category']}",
        }
        for item in audit["assumption_register"]
    }
    started_at, completed_at = _after_registration_times(
        frozen.registration_timestamp
    )
    service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at=started_at,
        completed_at=completed_at,
        analysis_code_hash="a" * 64,
        environment_hash="e" * 64,
        dataset_ids=[dataset.dataset_id],
        output_artifacts=[DatasetArtifact(
            record_path.name,
            record_sha256,
            record_path.stat().st_size,
            "application/json",
        )],
        artifact_root=str(tmp_path),
        quality_gates=[
            QualityGateResult(
                "control-gate",
                QualityGateStatus.PASSED,
                "Synthetic control fixture was retained.",
                details={
                    "evidence_sha256": record_sha256,
                    "control_results": {
                        "reference-1": {
                            "observed_behavior": "The synthetic control transcript was retained.",
                            "interpretation": "Fixture-only control interpretation.",
                            "matches_expected": True,
                            "evidence_sha256": record_sha256,
                            "evidence_location": "/controls/reference-1",
                        }
                    },
                },
            ),
            QualityGateResult(
                "causal-assumptions-assessed",
                QualityGateStatus.PASSED,
                "Synthetic causal assumptions reviewed.",
                details={
                    "evidence_sha256": record_sha256,
                    "causal_assumption_results": causal_results,
                },
            ),
            QualityGateResult(
                "missingness-assessed",
                QualityGateStatus.PASSED,
                "Synthetic missingness fixture passed.",
                details={
                    "evidence_sha256": record_sha256,
                    "missingness_assessment_result": {
                        "observed_diagnostic": "Synthetic exclusion report reviewed.",
                        "interpretation": "No fixture contradiction to the assumption was encoded.",
                        "assessment_status": "consistent_with_assumption",
                        "assessment_kind": "empirical_diagnostic",
                        "evidence_sha256": record_sha256,
                        "evidence_location": "/missingness",
                    },
                },
            ),
        ],
        summary="Synthetic causal package fixture.",
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
    gate = next(
        item for item in runs[0]["quality_gates"]
        if item["gate_id"] == "causal-assumptions-assessed"
    )
    results = gate["details"]["causal_assumption_results"]
    positivity = results["positivity"]
    if mutation == "missing_results":
        del gate["details"]["causal_assumption_results"]
    elif mutation == "missing_category":
        del results["positivity"]
    elif mutation == "extra_category":
        results["invented_assumption"] = dict(positivity)
    elif mutation == "missing_field":
        del positivity["interpretation"]
    elif mutation == "wrong_kind":
        positivity["assessment_kind"] = "empirical_diagnostic"
    elif mutation == "padded_status":
        positivity["assessment_status"] = " consistent_with_assumption"
    elif mutation == "bad_status":
        positivity["assessment_status"] = "verified_assumption"
    elif mutation == "unbound_evidence":
        positivity["evidence_sha256"] = "f" * 64
    elif mutation == "blank_location":
        positivity["evidence_location"] = ""
    elif mutation == "passed_contradiction":
        positivity["assessment_status"] = "contradicted_assumption"
    elif mutation == "warning_without_inconclusive":
        gate["status"] = "warning"
    elif mutation == "failed_without_contradiction":
        gate["status"] = "failed"
    runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
    commitment = _refresh_packaged_file(package, "runs.json")

    with pytest.raises(ValidationError, match=message):
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
