from __future__ import annotations

from pathlib import Path
import hashlib
import json
import pytest

from research_machine.application.commands import (
    CreateInquiry,
    CreateProtocol,
    ProposeHypothesis,
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


@pytest.mark.parametrize("mutation", ["file", "manifest", "missing", "extra", "symlink", "traversal", "ethics_summary", "dataset_summary", "dataset_cycle", "run_eligibility"])
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
    output = tmp_path / "result.json"
    output.write_text('{"result":"passed"}\n', encoding="utf-8")
    output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    service.record_run(RecordRun(
        protocol_id=frozen.protocol_id,
        started_at="2026-09-07T02:00:00Z",
        completed_at="2026-09-07T02:01:00Z",
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
    else:
        runs_path = package / "runs.json"
        runs = json.loads(runs_path.read_text())
        runs[0]["synthetic"] = True
        runs_path.write_text(json.dumps(runs, indent=2, sort_keys=True) + "\n")
        manifest_path = package / "package-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["runs.json"] = hashlib.sha256(runs_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        commitment = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValidationError):
        verify_replication_package(package, commitment)
    assert service.verify_ledger()["valid"] is True
