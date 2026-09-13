from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.application.commands import (
    CreateProtocol,
    RecordAliasProxyMapping,
    RecordRun,
)
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AliasProxyCommitment,
    AnalysisMode,
    DatasetArtifact,
    MeasurementDefinition,
    MeasurementRole,
    ProtocolKind,
    QualityGateResult,
    QualityGateStatus,
)
from test_execution import (
    CODE_HASH,
    ENVIRONMENT_HASH,
    SEED_COMMITMENT,
    SEED_REVEAL,
    prepared_service,
)


def _write_bytes(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _alias_protocol(tmp_path: Path):
    service, hypothesis_id = prepared_service(tmp_path)
    mapping_root = tmp_path / "private-mapping"
    mapping_sha256 = _write_bytes(
        mapping_root / "aliases" / "mapping.json",
        json.dumps(
            {
                "Condition A": "private target retained outside public review",
                "Outcome proxy 1": "private construct retained outside public review",
            },
            sort_keys=True,
        ).encode("utf-8"),
    )
    measurement = MeasurementDefinition(
        measurement_id="primary-measurement",
        role=MeasurementRole.PRIMARY,
        registered_target="Proof checker acceptance",
        observable="Condition A acceptance",
        input_condition="all registered proof attempts",
        parameter_values={"aliasing": "masked"},
        evaluation_point="registered endpoint",
        convention="accepted means one",
        aggregation="single registered result",
        tolerance="exact checker parsing",
        expected_behavior="Reported regardless of direction",
        alias_proxy_commitment=AliasProxyCommitment(
            commitment_id="map-1",
            concealment_scope="observable_alias",
            public_label="Condition A acceptance",
            private_mapping_sha256=mapping_sha256,
            construct_validity_rationale=(
                "The public alias preserves blinded review while the private "
                "mapping is retained for later audit."
            ),
            limitations=[
                "The mapping hash does not establish that the proxy is adequate."
            ],
            reveal_conditions=(
                "Reveal to authorized auditors after primary analysis lock."
            ),
        ),
    )
    control_measurement = MeasurementDefinition(
        measurement_id="control-measurement",
        role=MeasurementRole.CONTROL,
        registered_target="Replay a deliberately invalid derivation.",
        observable="Invalid derivation rejection",
        input_condition="registered invalid-control proof attempt",
        parameter_values={"aliasing": "not masked"},
        evaluation_point="registered control endpoint",
        convention="rejected means expected control behavior",
        aggregation="single registered result",
        tolerance="exact checker parsing",
        expected_behavior="Invalid derivation is rejected.",
    )
    draft = service.create_protocol(
        CreateProtocol(
            experiment_id="alias-check-01",
            title="Check aliased invariant derivation",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[hypothesis_id],
            primary_outcome="Proof checker acceptance",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Replay an aliased derivation in the proof checker.",
            quality_requirements=["proof-check"],
            controls=["Replay a deliberately invalid derivation."],
            measurement_definitions=[measurement, control_measurement],
            expected_outputs=["Proof object", "Checker transcript"],
            success_conditions=["The independent checker accepts the proof object."],
            environment_requirements=["Pinned checker and axiom-set hashes"],
            sample_size_or_stopping_rule=(
                "One registered proof object and one fixed invalid control."
            ),
            failure_conditions=["The checker rejects any proof step."],
            safety_constraints=["No physical or human intervention is involved."],
            analysis_code_hash=CODE_HASH,
            random_seed_commitment=SEED_COMMITMENT,
        )
    )
    protocol = service.freeze_protocol(draft.protocol_id)
    return service, protocol, mapping_root, mapping_sha256


def _record_run(service, protocol, output_root: Path):
    output_sha256 = _write_bytes(
        output_root / "proof-output.json",
        b'{"accepted": true}\n',
    )
    return service.record_run(
        RecordRun(
            protocol_id=protocol.protocol_id,
            started_at="2026-09-02T12:01:00Z",
            completed_at="2026-09-02T12:02:00Z",
            analysis_code_hash=CODE_HASH,
            environment_hash=ENVIRONMENT_HASH,
            random_seed_reveal=SEED_REVEAL,
            dataset_ids=[],
            output_artifacts=[
                DatasetArtifact(
                    "proof-output.json",
                    output_sha256,
                    (output_root / "proof-output.json").stat().st_size,
                    "application/json",
                )
            ],
            quality_gates=[
                QualityGateResult(
                    gate_id="proof-check",
                    status=QualityGateStatus.PASSED,
                    summary="Independent proof-checker result.",
                    details={"evidence_sha256": output_sha256},
                )
            ],
            summary="Aliased fixture run.",
            artifact_root=str(output_root),
            metadata={
                "protocol_deviation_disclosure": {
                    "status": "no_deviations_declared",
                    "deviations": [],
                },
                "result_exposure_disclosure": {
                    "status": "no_relevant_output_seen",
                    "exposures": [],
                },
            },
        )
    )


def test_alias_proxy_mapping_custody_controls_evidence_eligibility(tmp_path: Path) -> None:
    service, protocol, mapping_root, mapping_sha256 = _alias_protocol(tmp_path)

    missing_run = _record_run(service, protocol, tmp_path / "run-missing")

    assert missing_run.scientific_evidence_eligible is False
    assert (
        missing_run.metadata["alias_proxy_mapping_verification"]["status"]
        == "missing"
    )
    audit = service.audit_rigor()
    assert any(
        finding.code == "ALIAS_PROXY_MAPPING_CUSTODY_MISSING"
        for finding in audit.findings
    )

    record = service.record_alias_proxy_mapping(
        RecordAliasProxyMapping(
            protocol_id=protocol.protocol_id,
            mapping_artifact_root=str(mapping_root),
            mappings=[
                {
                    "measurement_id": "primary-measurement",
                    "commitment_id": "map-1",
                    "mapping_locator": "aliases/mapping.json",
                    "mapping_sha256": mapping_sha256,
                }
            ],
            access_control_statement=(
                "The private mapping is available only to authorized auditors."
            ),
            reveal_policy_statement=(
                "Disclosure follows the frozen reveal condition after analysis lock."
            ),
            limitations=[
                "Custody verifies bytes only, not whether the proxy is adequate."
            ],
            record_id="alias-map-1",
        )
    )
    verified_run = _record_run(service, protocol, tmp_path / "run-verified")

    assert record.mappings[0].mapping_sha256 == mapping_sha256
    assert verified_run.scientific_evidence_eligible is True
    assert (
        verified_run.metadata["alias_proxy_mapping_verification"]["status"]
        == "verified"
    )
    synthesis = service.build_synthesis()["content"]
    assert "Alias/proxy custody" in synthesis
    assert "alias-map-1" in synthesis
    collaborator = service.collaborator_context(purpose="alias custody review")
    assert (
        collaborator["alias_proxy_mapping_records"][0]["mapping_artifact_root"]
        == "[redacted: retained in canonical store]"
    )
    exported = service.export_replication_package(
        protocol.protocol_id,
        str(tmp_path / "package"),
    )
    package_alias_records = json.loads(
        (tmp_path / "package" / "alias-proxy-mapping-records.json").read_text()
    )
    assert exported["package_version"] == 2
    assert package_alias_records[0]["mapping_artifact_root"] == (
        "[redacted: obtain from authorized source]"
    )
    assert package_alias_records[0]["mappings"][0]["mapping_locator"] == (
        "[redacted: obtain from authorized source]"
    )


def test_alias_proxy_mapping_record_replays_current_private_bytes(tmp_path: Path) -> None:
    service, protocol, mapping_root, mapping_sha256 = _alias_protocol(tmp_path)
    service.record_alias_proxy_mapping(
        RecordAliasProxyMapping(
            protocol_id=protocol.protocol_id,
            mapping_artifact_root=str(mapping_root),
            mappings=[
                {
                    "measurement_id": "primary-measurement",
                    "commitment_id": "map-1",
                    "mapping_locator": "aliases/mapping.json",
                    "mapping_sha256": mapping_sha256,
                }
            ],
            access_control_statement=(
                "The private mapping is available only to authorized auditors."
            ),
            reveal_policy_statement=(
                "Disclosure follows the frozen reveal condition after analysis lock."
            ),
            limitations=[
                "Custody verifies bytes only, not whether the proxy is adequate."
            ],
            record_id="alias-map-1",
        )
    )
    (mapping_root / "aliases" / "mapping.json").write_bytes(b'{"changed": true}\n')

    with pytest.raises(ValidationError, match="current bytes"):
        service.show_inquiry()
