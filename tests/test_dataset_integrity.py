from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import pytest

from research_machine.application.commands import CreateProtocol, RecordRun, RegisterDataset
from research_machine.application.dataset_integrity import (
    dataset_payload_sha256,
    reverify_dataset_artifacts,
    validate_protected_dataset_lineage_closure,
    verify_dataset_artifacts,
)
from research_machine.application.rigor import audit_research_state
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisMode,
    DatasetArtifact,
    DatasetManifest,
    DatasetRole,
    ExperimentProtocol,
    Inquiry,
    ProtocolKind,
    ProtocolStatus,
    QualityGateResult,
    QualityGateStatus,
)
from research_machine.reporting.synthesis import build_synthesis
from test_ethics_gate import _human_protocol
from test_execution import prepared_service


def _protected_protocol(tmp_path: Path):
    service, hypothesis_id = prepared_service(tmp_path)
    base = _human_protocol(
        human_subjects=False,
        hypotheses_tested=[hypothesis_id],
    )
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    draft = service.create_protocol(CreateProtocol(**values))
    return service, service.freeze_protocol(draft.protocol_id)


def _artifact(path: Path) -> DatasetArtifact:
    return DatasetArtifact(
        path.name,
        hashlib.sha256(path.read_bytes()).hexdigest(),
        path.stat().st_size,
        "text/csv",
    )


def _reseal_dataset_record(path: Path, **updates: object) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(updates)
    record.setdefault("metadata", {}).pop("dataset_payload_sha256", None)
    record["metadata"]["dataset_payload_sha256"] = dataset_payload_sha256(
        DatasetManifest.from_dict(record)
    )
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_audit_and_synthesis_expose_protected_lineage_mismatch() -> None:
    inquiry = Inquiry(
        inquiry_id="lineage",
        title="Lineage",
        initial_statement="Can protected lineage be laundered?",
        created_at="2026-09-09T00:00:00Z",
        decision_to_support="Whether protected observations remain protocol-closed.",
        minimum_evidence="A structural audit that rejects cross-boundary ancestry.",
        decision_change_criteria=["Stop if a protected derivative crosses protocols."],
        decision_owner="project-owner",
    )
    protocol = ExperimentProtocol(
        protocol_id="protocol-v1",
        protocol_family_id="protocol",
        version=1,
        experiment_id="lineage-test",
        title="Lineage test",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[],
        primary_outcome="Outcome",
        created_at="2026-09-09T00:00:00Z",
        created_by="test",
        protocol_kind=ProtocolKind.OBSERVATIONAL,
        quality_requirements=["gate"],
        controls=["control"],
        sample_size_or_stopping_rule="one synthetic fixture",
        status=ProtocolStatus.FROZEN,
    )
    source = DatasetManifest(
        dataset_id="source-dataset",
        name="Source dataset",
        role=DatasetRole.EXPLORATORY,
        created_at="2026-09-09T00:00:00Z",
        artifacts=[DatasetArtifact("source.csv", "c" * 64)],
        protocol_id="other-protocol-v1",
        synthetic=True,
    )
    derived = DatasetManifest(
        dataset_id="derived-dataset",
        name="Derived dataset",
        role=DatasetRole.CONFIRMATORY,
        created_at="2026-09-09T00:00:00Z",
        artifacts=[DatasetArtifact("derived.csv", "d" * 64)],
        source_dataset_ids=[source.dataset_id],
        protocol_id=protocol.protocol_id,
        synthetic=True,
    )

    audit = audit_research_state(
        inquiry=inquiry,
        claims=[],
        hypotheses=[],
        evidence=[],
        datasets=[source, derived],
        protocols=[protocol],
        runs=[],
    )

    assert any(
        item.code == "PROTECTED_DATASET_LINEAGE_PROTOCOL_MISMATCH"
        and item.entity_id == derived.dataset_id
        for item in audit.findings
    )
    assert audit.structurally_valid is False

    synthesis = build_synthesis(
        inquiry,
        questions=[],
        claims=[],
        hypotheses=[],
        evidence=[],
        datasets=[source, derived],
        protocols=[protocol],
        runs=[],
        recommendations=[],
        cross_lane_lessons=[],
        rigor_audit=audit,
        evidence_status_events=[],
    )

    assert "### Protected dataset lineage" in synthesis
    assert "cross-boundary source `source-dataset`" in synthesis
    assert "protocol-closure provenance, not proof" in synthesis


@pytest.mark.parametrize(
    ("datasets", "root_id", "message"),
    [
        (
            [
                DatasetManifest(
                    dataset_id="root",
                    name="Root",
                    role=DatasetRole.CONFIRMATORY,
                    created_at="2026-09-09T00:00:00Z",
                    artifacts=[DatasetArtifact("root.csv", "a" * 64)],
                    source_dataset_ids=["source", "source"],
                    protocol_id="protocol-v1",
                    synthetic=True,
                ),
                DatasetManifest(
                    dataset_id="source",
                    name="Source",
                    role=DatasetRole.CONFIRMATORY,
                    created_at="2026-09-09T00:00:00Z",
                    artifacts=[DatasetArtifact("source.csv", "b" * 64)],
                    protocol_id="protocol-v1",
                    synthetic=True,
                ),
            ],
            "root",
            "repeats lineage source",
        ),
        (
            [
                DatasetManifest(
                    dataset_id="root",
                    name="Root",
                    role=DatasetRole.CONFIRMATORY,
                    created_at="2026-09-09T00:00:00Z",
                    artifacts=[DatasetArtifact("root.csv", "a" * 64)],
                    source_dataset_ids=["source"],
                    protocol_id="protocol-v1",
                    synthetic=True,
                ),
                DatasetManifest(
                    dataset_id="source",
                    name="Source",
                    role=DatasetRole.CONFIRMATORY,
                    created_at="2026-09-09T00:00:00Z",
                    artifacts=[DatasetArtifact("source.csv", "b" * 64)],
                    source_dataset_ids=["root"],
                    protocol_id="protocol-v1",
                    synthetic=True,
                ),
            ],
            "root",
            "contains a cycle",
        ),
    ],
)
def test_protected_lineage_closure_rejects_invalid_graphs(
    datasets: list[DatasetManifest],
    root_id: str,
    message: str,
) -> None:
    datasets_by_id = {dataset.dataset_id: dataset for dataset in datasets}

    with pytest.raises(ValidationError, match=message):
        validate_protected_dataset_lineage_closure(
            datasets_by_id[root_id],
            datasets_by_id,
            validate_payload=False,
        )


def test_show_inquiry_rejects_resealed_cross_protocol_protected_lineage(
    tmp_path: Path,
) -> None:
    service, protocol = _protected_protocol(tmp_path)
    source = service.register_dataset(RegisterDataset(
        dataset_id="source-observations",
        name="Source observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("source.csv", "c" * 64)],
        protocol_id=protocol.protocol_id,
        synthetic=True,
    ))
    service.register_dataset(RegisterDataset(
        dataset_id="derived-observations",
        name="Derived observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("derived.csv", "d" * 64)],
        source_dataset_ids=[source.dataset_id],
        protocol_id=protocol.protocol_id,
        synthetic=True,
    ))
    source_path = (
        tmp_path
        / "inquiries"
        / "formal"
        / "datasets"
        / f"{source.dataset_id}.json"
    )
    _reseal_dataset_record(source_path, protocol_id="other-protocol-v1")

    with pytest.raises(ValidationError, match="lineage crosses role or protocol"):
        service.show_inquiry()


def test_run_intake_rejects_resealed_cross_protocol_protected_lineage(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    draft = service.create_protocol(CreateProtocol(
        experiment_id="lineage-run-test",
        title="Lineage run test",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis_id],
        primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL,
        methodology="Replay a synthetic lineage fixture.",
        quality_requirements=["gate"],
        controls=["control"],
        expected_outputs=["result"],
        success_conditions=["quality gate passes"],
        environment_requirements=["deterministic fixture"],
        sample_size_or_stopping_rule="one synthetic fixture",
        failure_conditions=["quality gate fails"],
        safety_constraints=["synthetic fixture only"],
        analysis_code_hash="a" * 64,
    ))
    protocol = service.freeze_protocol(draft.protocol_id)
    source = service.register_dataset(RegisterDataset(
        dataset_id="run-source-observations",
        name="Run source observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("source.csv", "c" * 64)],
        protocol_id=protocol.protocol_id,
        synthetic=True,
    ))
    derived = service.register_dataset(RegisterDataset(
        dataset_id="run-derived-observations",
        name="Run derived observations",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("derived.csv", "d" * 64)],
        source_dataset_ids=[source.dataset_id],
        protocol_id=protocol.protocol_id,
        synthetic=True,
    ))
    source_path = (
        tmp_path
        / "inquiries"
        / "formal"
        / "datasets"
        / f"{source.dataset_id}.json"
    )
    _reseal_dataset_record(source_path, protocol_id="other-protocol-v1")

    with pytest.raises(ValidationError, match="lineage crosses role or protocol"):
        service.record_run(RecordRun(
            protocol_id=protocol.protocol_id,
            started_at="2026-09-02T12:01:00Z",
            completed_at="2026-09-02T12:02:00Z",
            analysis_code_hash="a" * 64,
            environment_hash="b" * 64,
            dataset_ids=[derived.dataset_id],
            output_artifacts=[
                DatasetArtifact("result.json", "e" * 64, media_type="application/json")
            ],
            quality_gates=[
                QualityGateResult(
                    "gate",
                    QualityGateStatus.PASSED,
                    "Synthetic fixture gate.",
                    details={"evidence_sha256": "e" * 64},
                )
            ],
            summary="Synthetic lineage fixture.",
            synthetic=True,
            metadata={
                "protocol_deviation_disclosure": {
                    "status": "no_deviations_declared",
                    "deviations": [],
                }
            },
        ))


def test_real_protected_dataset_requires_current_registered_bytes(tmp_path: Path) -> None:
    service, protocol = _protected_protocol(tmp_path)
    observations = tmp_path / "observations.csv"
    observations.write_text("unit,group,outcome\nu1,a,1\nu2,b,2\n", encoding="utf-8")
    command = RegisterDataset(
        dataset_id="protected-observations",
        name="Protected observations",
        role=DatasetRole.CONFIRMATORY,
        protocol_id=protocol.protocol_id,
        artifacts=[_artifact(observations)],
    )

    with pytest.raises(ValidationError, match="require artifact_root"):
        service.register_dataset(command)
    assert service.list_datasets() == []

    observations.write_text("tampered before registration\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="HASH_MISMATCH"):
        service.register_dataset(
            RegisterDataset(**{**command.__dict__, "artifact_root": str(tmp_path)})
        )
    assert service.list_datasets() == []

    observations.write_text("unit,group,outcome\nu1,a,1\nu2,b,2\n", encoding="utf-8")
    dataset = service.register_dataset(
        RegisterDataset(**{**command.__dict__, "artifact_root": str(tmp_path)})
    )
    receipt = dataset.metadata["dataset_artifact_verification"]
    assert receipt["artifact_integrity"]["status"] == "passed"
    assert receipt["dataset_artifact_root"] == str(tmp_path.resolve())
    assert receipt["protocol_hash"] == protocol.protocol_hash
    service.show_inquiry()
    service._validate_run_datasets(protocol, [dataset])

    dataset_path = (
        tmp_path
        / "inquiries"
        / "formal"
        / "datasets"
        / f"{dataset.dataset_id}.json"
    )
    dataset_bytes = dataset_path.read_bytes()
    forged = json.loads(dataset_bytes)
    forged["synthetic"] = True
    dataset_path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(ValidationError, match="dataset .* payload"):
        service.list_datasets()
    with pytest.raises(ValidationError, match="dataset .* payload"):
        service.show_inquiry()
    dataset_path.write_bytes(dataset_bytes)

    observations.write_text("tampered after registration\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="HASH_MISMATCH"):
        service.show_inquiry()
    with pytest.raises(ValidationError, match="HASH_MISMATCH"):
        service._validate_run_datasets(protocol, [dataset])


def test_dataset_artifact_verification_cannot_be_self_attested(tmp_path: Path) -> None:
    service, protocol = _protected_protocol(tmp_path)
    with pytest.raises(ValidationError, match="service-generated"):
        service.register_dataset(RegisterDataset(
            name="Forged receipt",
            role=DatasetRole.CONFIRMATORY,
            protocol_id=protocol.protocol_id,
            artifacts=[DatasetArtifact("observations.csv", "a" * 64)],
            metadata={"dataset_artifact_verification": {"status": "passed"}},
            artifact_root=str(tmp_path),
        ))
    with pytest.raises(ValidationError, match="dataset_payload_sha256"):
        service.register_dataset(RegisterDataset(
            name="Forged payload commitment",
            role=DatasetRole.CONFIRMATORY,
            protocol_id=protocol.protocol_id,
            artifacts=[DatasetArtifact("observations.csv", "a" * 64)],
            metadata={"dataset_payload_sha256": "a" * 64},
            artifact_root=str(tmp_path),
        ))


def test_dataset_artifact_receipt_requires_canonical_verifier_metadata(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations.csv"
    observations.write_text("unit,group,outcome\nu1,a,1\n", encoding="utf-8")
    artifacts = [_artifact(observations)]

    with pytest.raises(ValidationError, match="verification actor.*canonical"):
        verify_dataset_artifacts(
            artifacts,
            str(tmp_path),
            actor=" verifier ",
            verified_at="2026-09-07T00:00:00+00:00",
            protocol_hash="a" * 64,
        )

    with pytest.raises(ValidationError, match="verification time must include a UTC offset"):
        verify_dataset_artifacts(
            artifacts,
            str(tmp_path),
            actor="verifier",
            verified_at="2026-09-07T00:00:00",
            protocol_hash="a" * 64,
        )


def test_dataset_artifact_replay_rejects_padded_retained_verifier_metadata(
    tmp_path: Path,
) -> None:
    service, protocol = _protected_protocol(tmp_path)
    observations = tmp_path / "observations.csv"
    observations.write_text("unit,group,outcome\nu1,a,1\nu2,b,2\n", encoding="utf-8")
    dataset = service.register_dataset(RegisterDataset(
        dataset_id="protected-observations",
        name="Protected observations",
        role=DatasetRole.CONFIRMATORY,
        protocol_id=protocol.protocol_id,
        artifacts=[_artifact(observations)],
        artifact_root=str(tmp_path),
    ))

    forged_receipt = dict(dataset.metadata["dataset_artifact_verification"])
    forged_receipt["verified_by"] = f" {forged_receipt['verified_by']} "
    forged = replace(
        dataset,
        metadata={**dataset.metadata, "dataset_artifact_verification": forged_receipt},
    )

    with pytest.raises(ValidationError, match="verification actor.*canonical"):
        reverify_dataset_artifacts(forged, protocol)
