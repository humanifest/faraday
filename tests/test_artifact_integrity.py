from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.artifact_integrity import verify_run_artifacts
from research_machine.application.commands import (
    CreateInquiry,
    CreateProtocol,
    ProposeHypothesis,
    RecordRun,
)
from research_machine.application.run_integrity import reverify_run_artifacts
from research_machine.application.policies import validate_dataset_artifacts
from research_machine.application.json_schema_profile import (
    AttestationSchemaProfileError,
    validate_attestation_schema,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisMode,
    DatasetArtifact,
    ProtocolKind,
    QualityGateResult,
    QualityGateStatus,
)
from research_machine.interfaces.cli import main


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema(target_run_id: str) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "target_run_id",
            "executor_identity",
            "design",
            "independence_dimensions",
            "prior_implementation_accessed",
            "allowed_input_manifest",
            "analysis_code_hash",
            "contamination_disclosures",
            "attested_at",
        ],
        "properties": {
            "target_run_id": {"const": target_run_id},
            "executor_identity": {"type": "string", "minLength": 1},
            "design": {"const": "clean_room"},
            "independence_dimensions": {
                "type": "array",
                "minItems": 2,
                "uniqueItems": True,
                "allOf": [
                    {"contains": {"const": "executor"}},
                    {"contains": {"const": "implementation"}},
                ],
                "items": {"type": "string", "minLength": 1},
            },
            "prior_implementation_accessed": {"const": False},
            "allowed_input_manifest": {
                "type": "object",
                "additionalProperties": False,
                "required": ["locator", "sha256"],
                "properties": {
                    "locator": {"type": "string", "minLength": 1},
                    "sha256": {"$ref": "#/$defs/hash"},
                },
            },
            "analysis_code_hash": {
                "allOf": [
                    {"$ref": "#/$defs/hash"},
                    {"not": {"const": "a" * 64}},
                ]
            },
            "contamination_disclosures": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "attested_at": {"type": "string", "format": "date-time"},
        },
        "$defs": {"hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
    }


def _attestation(target_run_id: str, *, actor: str = "independent-lab") -> dict:
    return {
        "target_run_id": target_run_id,
        "executor_identity": actor,
        "design": "clean_room",
        "independence_dimensions": ["executor", "implementation"],
        "prior_implementation_accessed": False,
        "allowed_input_manifest": {
            "locator": "handoff.json",
            "sha256": "2" * 64,
        },
        "analysis_code_hash": "d" * 64,
        "contamination_disclosures": [],
        "attested_at": "2026-09-03T08:15:00Z",
    }


def _metadata(target_run_id: str) -> dict:
    return {
        "replicates_run_id": target_run_id,
        "replication_independence": {
            "design": "clean_room",
            "independence_dimensions": ["executor", "implementation"],
            "prior_implementation_accessed": False,
            "allowed_inputs": [
                {"locator": "handoff.json", "sha256": "2" * 64}
            ],
            "contamination_disclosures": [],
            "attestation_artifact": "attestation.json",
        },
    }


def _artifact_fixture(tmp_path: Path):
    target_run_id = "run-original"
    root = tmp_path / "returned"
    root.mkdir()
    result_path = root / "result.json"
    result_path.write_text('{"outcome":"reproduced"}\n', encoding="utf-8")
    attestation_path = root / "attestation.json"
    attestation_path.write_text(
        json.dumps(_attestation(target_run_id)), encoding="utf-8"
    )
    schema_path = tmp_path / "attestation.schema.json"
    schema_path.write_text(json.dumps(_schema(target_run_id)), encoding="utf-8")
    artifacts = [
        DatasetArtifact(
            "result.json",
            _sha256(result_path),
            size_bytes=result_path.stat().st_size,
        ),
        DatasetArtifact(
            "attestation.json",
            _sha256(attestation_path),
            size_bytes=attestation_path.stat().st_size,
            metadata={"artifact_role": "independence_attestation"},
        ),
    ]
    return target_run_id, root, schema_path, artifacts


def test_supported_schema_profile_enforces_refs_contains_not_and_format() -> None:
    schema = _schema("run-original")
    assert validate_attestation_schema(
        _attestation("run-original"), schema
    ) == []

    invalid = _attestation("run-original")
    invalid["analysis_code_hash"] = "a" * 64
    invalid["independence_dimensions"] = ["executor", "executor"]
    invalid["attested_at"] = "yesterday"
    errors = validate_attestation_schema(invalid, schema)
    assert any("items must be unique" in error for error in errors)
    assert any("no item matching contains" in error for error in errors)
    assert any("matches prohibited schema" in error for error in errors)
    assert any("RFC 3339" in error for error in errors)


def test_schema_profile_rejects_unsupported_keywords() -> None:
    with pytest.raises(AttestationSchemaProfileError, match="unsupported keywords"):
        validate_attestation_schema(
            "value",
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "string",
                "maxLength": 4,
            },
        )


def test_schema_profile_does_not_equate_json_booleans_and_numbers() -> None:
    assert validate_attestation_schema(True, {"const": 1}) == [
        "$ does not match const"
    ]
    assert validate_attestation_schema(True, {"enum": [1]}) == [
        "$ is not in enum"
    ]


def test_schema_profile_rejects_reference_to_non_schema_value() -> None:
    with pytest.raises(AttestationSchemaProfileError, match="does not resolve"):
        validate_attestation_schema(
            "value",
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$ref": "#/title",
                "title": "not a schema",
            },
        )


def test_artifact_integrity_passes_hash_schema_and_record_cross_checks(
    tmp_path: Path,
) -> None:
    target_run_id, root, schema_path, artifacts = _artifact_fixture(tmp_path)

    report = verify_run_artifacts(
        artifacts,
        artifact_root=str(root),
        actor="independent-lab",
        analysis_code_hash="d" * 64,
        run_metadata=_metadata(target_run_id),
        attestation_schema_path=str(schema_path),
        expected_attestation_schema_sha256=_sha256(schema_path),
    )

    assert report.status == "passed"
    assert report.all_artifacts_match is True
    assert report.attestation_schema_matches_commitment is True
    assert report.attestation_schema_valid is True
    assert report.attestation_consistent is True
    assert report.findings == []


@pytest.mark.parametrize("expected_schema_hash", ["A" * 64, "0" * 63, " " + "0" * 64])
def test_artifact_integrity_rejects_malformed_attestation_schema_commitment(
    tmp_path: Path, expected_schema_hash: str
) -> None:
    target_run_id, root, schema_path, artifacts = _artifact_fixture(tmp_path)

    report = verify_run_artifacts(
        artifacts,
        artifact_root=str(root),
        actor="independent-lab",
        analysis_code_hash="d" * 64,
        run_metadata=_metadata(target_run_id),
        attestation_schema_path=str(schema_path),
        expected_attestation_schema_sha256=expected_schema_hash,
    )

    assert report.status == "failed"
    assert report.attestation_schema_sha256 is None
    assert report.attestation_schema_matches_commitment is None
    assert {
        finding["code"]
        for finding in report.findings
    } >= {"ATTESTATION_SCHEMA_COMMITMENT_MALFORMED"}
    assert "ATTESTATION_SCHEMA_HASH_MISMATCH" not in {
        finding["code"]
        for finding in report.findings
    }


def test_artifact_integrity_rejects_unpinned_schema_path_without_attestation(
    tmp_path: Path,
) -> None:
    _, root, schema_path, artifacts = _artifact_fixture(tmp_path)

    report = verify_run_artifacts(
        artifacts[:1],
        artifact_root=str(root),
        actor="independent-lab",
        analysis_code_hash="d" * 64,
        run_metadata={},
        attestation_schema_path=str(schema_path),
        expected_attestation_schema_sha256=None,
    )

    assert report.status == "failed"
    assert {
        finding["code"]
        for finding in report.findings
    } == {"ATTESTATION_SCHEMA_COMMITMENT_REQUIRED"}


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("artifact_hash", "ARTIFACT_HASH_MISMATCH"),
        ("schema_hash", "ATTESTATION_SCHEMA_HASH_MISMATCH"),
        ("executor", "ATTESTATION_RUN_METADATA_MISMATCH"),
    ],
)
def test_artifact_integrity_fails_closed_on_mutations(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    target_run_id, root, schema_path, artifacts = _artifact_fixture(tmp_path)
    expected_schema_hash = _sha256(schema_path)
    actor = "independent-lab"
    if mutation == "artifact_hash":
        artifacts[0] = DatasetArtifact("result.json", "0" * 64)
    elif mutation == "schema_hash":
        expected_schema_hash = "0" * 64
    else:
        actor = "different-actor"

    report = verify_run_artifacts(
        artifacts,
        artifact_root=str(root),
        actor=actor,
        analysis_code_hash="d" * 64,
        run_metadata=_metadata(target_run_id),
        attestation_schema_path=str(schema_path),
        expected_attestation_schema_sha256=expected_schema_hash,
    )

    assert report.status == "failed"
    assert expected_code in {finding["code"] for finding in report.findings}


def test_artifact_integrity_rejects_parent_traversal(tmp_path: Path) -> None:
    target_run_id, root, schema_path, artifacts = _artifact_fixture(tmp_path)
    artifacts[0] = DatasetArtifact("../result.json", artifacts[0].sha256)

    report = verify_run_artifacts(
        artifacts,
        artifact_root=str(root),
        actor="independent-lab",
        analysis_code_hash="d" * 64,
        run_metadata=_metadata(target_run_id),
        attestation_schema_path=str(schema_path),
        expected_attestation_schema_sha256=_sha256(schema_path),
    )

    assert report.status == "failed"
    assert "ARTIFACT_LOCATOR_UNSAFE" in {
        finding["code"] for finding in report.findings
    }


def test_dataset_artifact_locator_must_be_canonical() -> None:
    with pytest.raises(ValidationError, match="artifact locator must be canonical"):
        validate_dataset_artifacts([DatasetArtifact(" result.json ", "a" * 64)])


def test_dataset_artifact_media_type_must_be_canonical() -> None:
    with pytest.raises(ValidationError, match="artifact media_type must be canonical"):
        validate_dataset_artifacts([
            DatasetArtifact("result.json", "a" * 64, media_type=" application/json ")
        ])


def test_artifact_integrity_rejects_duplicate_attestation_keys(
    tmp_path: Path,
) -> None:
    target_run_id, root, schema_path, artifacts = _artifact_fixture(tmp_path)
    attestation_path = root / "attestation.json"
    content = attestation_path.read_text(encoding="utf-8")
    attestation_path.write_text(
        content[:-1] + ',"executor_identity":"ambiguous"}',
        encoding="utf-8",
    )
    artifacts[1] = DatasetArtifact(
        "attestation.json",
        _sha256(attestation_path),
        size_bytes=attestation_path.stat().st_size,
        metadata={"artifact_role": "independence_attestation"},
    )

    report = verify_run_artifacts(
        artifacts,
        artifact_root=str(root),
        actor="independent-lab",
        analysis_code_hash="d" * 64,
        run_metadata=_metadata(target_run_id),
        attestation_schema_path=str(schema_path),
        expected_attestation_schema_sha256=_sha256(schema_path),
    )

    assert report.status == "failed"
    assert "ATTESTATION_JSON_INVALID" in {
        finding["code"] for finding in report.findings
    }


def test_artifact_integrity_rejects_duplicate_attested_dimensions_without_schema_rule(
    tmp_path: Path,
) -> None:
    target_run_id, root, schema_path, artifacts = _artifact_fixture(tmp_path)
    schema = _schema(target_run_id)
    schema["properties"]["independence_dimensions"].pop("uniqueItems")
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    attestation_path = root / "attestation.json"
    attestation = _attestation(target_run_id)
    attestation["independence_dimensions"] = [
        "executor", "implementation", "executor"
    ]
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
    artifacts[1] = DatasetArtifact(
        "attestation.json",
        _sha256(attestation_path),
        size_bytes=attestation_path.stat().st_size,
        metadata={"artifact_role": "independence_attestation"},
    )

    report = verify_run_artifacts(
        artifacts,
        artifact_root=str(root),
        actor="independent-lab",
        analysis_code_hash="d" * 64,
        run_metadata=_metadata(target_run_id),
        attestation_schema_path=str(schema_path),
        expected_attestation_schema_sha256=_sha256(schema_path),
    )

    assert report.status == "failed"
    assert "ATTESTATION_INDEPENDENCE_DIMENSIONS_DUPLICATE" in {
        finding["code"] for finding in report.findings
    }


def test_machine_reserved_integrity_receipt_cannot_be_self_supplied(
    tmp_path: Path,
) -> None:
    service, protocol_id = _replication_service(tmp_path)
    command = RecordRun(
        protocol_id=protocol_id,
        started_at="2026-09-03T08:15:00Z",
        completed_at="2026-09-03T08:16:00Z",
        analysis_code_hash="d" * 64,
        environment_hash="e" * 64,
        output_artifacts=[DatasetArtifact("result.json", "f" * 64)],
        quality_gates=[
            QualityGateResult(
                gate_id="replication-check",
                status=QualityGateStatus.PASSED,
                summary="Self-declared integrity must not be accepted.",
            )
        ],
        metadata={"artifact_integrity": {"status": "passed"}},
    )

    with pytest.raises(ValidationError, match="reserved for machine verification"):
        service.preflight_run(command, "replication")


def _replication_service(tmp_path: Path) -> tuple[ResearchService, str]:
    service = ResearchService(
        FileSystemRepository(tmp_path / "workspace"),
        actor="independent-lab",
        clock=lambda: "2026-09-03T08:15:00Z",
        token=lambda: "fixed-token",
    )
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry("Replication", "Does the result reproduce?", "replication")
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The registered result reproduces.",
            observable_prediction="The independent checks pass.",
            null_model="At least one independent check fails.",
            falsification_conditions=["Any frozen replication gate fails."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    draft = service.create_protocol(
        CreateProtocol(
            experiment_id="replication-intake",
            title="Replication intake",
            analysis_mode=AnalysisMode.REPLICATION,
            hypotheses_tested=[hypothesis.hypothesis_id],
            primary_outcome="Frozen gate result",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Execute the independent checker once.",
            quality_requirements=["replication-check"],
            controls=["The registered invalid control must fail."],
            expected_outputs=["Result and attestation"],
            success_conditions=["All frozen gates pass."],
            environment_requirements=["Pinned independent environment"],
            sample_size_or_stopping_rule="One protected execution.",
            failure_conditions=["Any required gate fails."],
            safety_constraints=["No physical intervention."],
            analysis_code_hash="d" * 64,
        )
    )
    protocol = service.freeze_protocol(draft.protocol_id)
    return service, protocol.protocol_id


def test_run_preflight_rejects_unverified_replication_without_writing(
    tmp_path: Path,
) -> None:
    service, protocol_id = _replication_service(tmp_path)
    _, _, _, artifacts = _artifact_fixture(tmp_path)
    before = service.verify_ledger("replication")
    command = RecordRun(
        protocol_id=protocol_id,
        started_at="2026-09-03T08:15:00Z",
        completed_at="2026-09-03T08:16:00Z",
        analysis_code_hash="d" * 64,
        environment_hash="e" * 64,
        output_artifacts=artifacts,
        quality_gates=[
            QualityGateResult(
                gate_id="replication-check",
                status=QualityGateStatus.PASSED,
                summary="The independent checks passed.",
                details={"evidence_sha256": artifacts[0].sha256},
            )
        ],
        metadata=_metadata("run-original"),
    )

    preflight = service.preflight_run(command, "replication")

    assert preflight.status == "would_reject"
    assert preflight.artifact_integrity is not None
    codes = {
        finding["code"]
        for finding in preflight.artifact_integrity["findings"]
    }
    assert codes == {
        "ARTIFACT_ROOT_REQUIRED",
        "ATTESTATION_SCHEMA_REQUIRED",
        "ATTESTATION_SCHEMA_COMMITMENT_REQUIRED",
    }
    assert service.verify_ledger("replication") == before
    with pytest.raises(ValidationError, match="artifact integrity preflight failed"):
        service.record_run(command, "replication")
    assert service.verify_ledger("replication") == before


def test_run_preflight_rejects_noncanonical_attestation_schema_hash(
    tmp_path: Path,
) -> None:
    service, protocol_id = _replication_service(tmp_path)
    target_run_id, root, schema_path, artifacts = _artifact_fixture(tmp_path)
    command = RecordRun(
        protocol_id=protocol_id,
        started_at="2026-09-03T08:15:00Z",
        completed_at="2026-09-03T08:16:00Z",
        analysis_code_hash="d" * 64,
        environment_hash="e" * 64,
        output_artifacts=artifacts,
        quality_gates=[
            QualityGateResult(
                gate_id="replication-check",
                status=QualityGateStatus.PASSED,
                summary="The independent checks passed.",
                details={"evidence_sha256": artifacts[0].sha256},
            )
        ],
        metadata=_metadata(target_run_id),
        artifact_root=str(root),
        attestation_schema_path=str(schema_path),
        expected_attestation_schema_sha256=_sha256(schema_path).upper(),
    )

    with pytest.raises(
        ValidationError,
        match="expected_attestation_schema_sha256 must be 64 lowercase hex characters",
    ):
        service.preflight_run(command, "replication")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("artifact_root", "{root} ", "artifact_root must be canonical"),
        (
            "attestation_schema_path",
            "{schema} ",
            "attestation_schema_path must be canonical",
        ),
        ("output_artifacts", "{padded_locator}", "artifact locator must be canonical"),
        ("output_artifacts", "{padded_media_type}", "artifact media_type must be canonical"),
    ],
)
def test_run_artifact_receipt_paths_must_be_canonical_at_intake(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    service, protocol_id = _replication_service(tmp_path)
    target_run_id, root, schema_path, artifacts = _artifact_fixture(tmp_path)
    if value == "{root} ":
        value = f"{root} "
    elif value == "{schema} ":
        value = f"{schema_path} "
    command = RecordRun(
        protocol_id=protocol_id,
        started_at="2026-09-03T08:15:00Z",
        completed_at="2026-09-03T08:16:00Z",
        analysis_code_hash="d" * 64,
        environment_hash="e" * 64,
        output_artifacts=artifacts,
        quality_gates=[
            QualityGateResult(
                gate_id="replication-check",
                status=QualityGateStatus.PASSED,
                summary="The independent checks passed.",
                details={"evidence_sha256": artifacts[0].sha256},
            )
        ],
        metadata=_metadata(target_run_id),
        artifact_root=str(root),
        attestation_schema_path=str(schema_path),
        expected_attestation_schema_sha256=_sha256(schema_path),
    )
    if value == "{padded_locator}":
        value = [
            DatasetArtifact(
                f" {artifacts[0].locator} ",
                artifacts[0].sha256,
                artifacts[0].size_bytes,
                artifacts[0].media_type,
                artifacts[0].metadata,
            ),
            artifacts[1],
        ]
    elif value == "{padded_media_type}":
        value = [
            DatasetArtifact(
                artifacts[0].locator,
                artifacts[0].sha256,
                artifacts[0].size_bytes,
                " application/json ",
                artifacts[0].metadata,
            ),
            artifacts[1],
        ]

    with pytest.raises(ValidationError, match=message):
        service.preflight_run(replace(command, **{field: value}), "replication")


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("run_artifact_root", "run artifact root must be canonical"),
        ("run_attestation_schema_path", "run attestation schema path must be canonical"),
    ],
)
def test_run_artifact_replay_rejects_padded_retained_paths(
    tmp_path: Path, field: str, message: str
) -> None:
    service, protocol_id = _replication_service(tmp_path)
    target_run_id, root, schema_path, artifacts = _artifact_fixture(tmp_path)
    run = service.record_run(
        RecordRun(
            protocol_id=protocol_id,
            started_at="2026-09-03T08:15:00Z",
            completed_at="2026-09-03T08:16:00Z",
            analysis_code_hash="d" * 64,
            environment_hash="e" * 64,
            output_artifacts=artifacts,
            quality_gates=[
                QualityGateResult(
                    gate_id="replication-check",
                    status=QualityGateStatus.PASSED,
                    summary="The independent checks passed.",
                    details={"evidence_sha256": artifacts[0].sha256},
                )
            ],
            metadata=_metadata(target_run_id),
            artifact_root=str(root),
            attestation_schema_path=str(schema_path),
            expected_attestation_schema_sha256=_sha256(schema_path),
        ),
        "replication",
    )
    tampered = replace(
        run,
        metadata={**run.metadata, field: f" {run.metadata[field]} "},
    )

    with pytest.raises(ValidationError, match=message):
        reverify_run_artifacts(tampered)


def test_cli_rechecks_artifact_bytes_when_recording(
    tmp_path: Path, capsys
) -> None:
    _, protocol_id = _replication_service(tmp_path)
    target_run_id, root, schema_path, artifacts = _artifact_fixture(tmp_path)
    record_path = tmp_path / "returned-run.json"
    record_path.write_text(
        json.dumps(
            {
                "run_id": "run-independent-return",
                "protocol_id": protocol_id,
                "started_at": "2026-09-03T08:15:00Z",
                "completed_at": "2026-09-03T08:16:00Z",
                "analysis_code_hash": "d" * 64,
                "environment_hash": "e" * 64,
                "output_artifacts": [artifact.to_dict() for artifact in artifacts],
                "quality_gates": [
                    {
                        "gate_id": "replication-check",
                        "status": "passed",
                        "summary": "The independent checks passed.",
                        "details": {"evidence_sha256": artifacts[0].sha256},
                    }
                ],
                "metadata": _metadata(target_run_id),
            }
        ),
        encoding="utf-8",
    )
    global_args = [
        "--workspace",
        str(tmp_path / "workspace"),
        "--actor",
        "independent-lab",
        "--json",
    ]
    integrity_args = [
        "--artifact-root",
        str(root),
        "--attestation-schema",
        str(schema_path),
        "--expect-attestation-schema-sha256",
        _sha256(schema_path),
    ]
    assert (
        main(
            [
                *global_args,
                "run",
                "preflight",
                "--record-file",
                str(record_path),
                *integrity_args,
            ]
        )
        == 0
    )
    preflight = json.loads(capsys.readouterr().out)["result"]
    assert preflight["artifact_integrity"]["status"] == "passed"

    result_path = root / "result.json"
    original_result = result_path.read_bytes()
    result_path.write_text('{"outcome":"changed-after-preflight"}\n', encoding="utf-8")
    assert (
        main(
            [
                *global_args,
                "run",
                "record",
                "--record-file",
                str(record_path),
                "--expect-record-sha256",
                preflight["record_file_sha256"],
                *integrity_args,
            ]
        )
        == 2
    )
    error = json.loads(capsys.readouterr().err)
    assert "ARTIFACT_HASH_MISMATCH" in error["error"]["message"]

    result_path.write_bytes(original_result)
    assert (
        main(
            [
                *global_args,
                "run",
                "record",
                "--record-file",
                str(record_path),
                "--expect-record-sha256",
                preflight["record_file_sha256"],
                *integrity_args,
            ]
        )
        == 0
    )
    recorded = json.loads(capsys.readouterr().out)["result"]
    assert recorded["metadata"]["artifact_integrity"]["status"] == "passed"
