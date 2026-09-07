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
    "protocol_gate_duplicate_after_trim",
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
    else:
        protocol_path = package / "protocol.json"
        protocol_record = json.loads(protocol_path.read_text())
        protocol_record["quality_requirements"].append(
            f" {protocol_record['quality_requirements'][0]} "
        )
        protocol_path.write_text(json.dumps(protocol_record, indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["protocol.json"] = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValidationError):
        verify_replication_package(package, commitment)
    assert service.verify_ledger()["valid"] is True


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
