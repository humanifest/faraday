from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import pytest

from research_machine.application.commands import CreateProtocol, RegisterDataset
from research_machine.application.dataset_integrity import (
    reverify_dataset_artifacts,
    verify_dataset_artifacts,
)
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import DatasetArtifact, DatasetRole
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
