from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import pytest

from research_machine.application.commands import (
    CreateProtocol,
    RecordEvidence,
    RecordRun,
    RegisterDataset,
)
from research_machine.application.dataset_integrity import (
    dataset_payload_sha256,
    reverify_dataset_artifacts,
    validate_protected_dataset_lineage_closure,
    verify_dataset_artifacts,
)
from research_machine.application.dataset_inventory import build_dataset_inventory
from research_machine.application.evidence_admission import (
    validate_evidence_admission_receipts,
)
from research_machine.application.rigor import audit_research_state
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisMode,
    DatasetArtifact,
    DatasetManifest,
    DatasetRole,
    EvidenceDirection,
    ExperimentProtocol,
    Inquiry,
    ProtocolKind,
    ProtocolStatus,
    QualityGateResult,
    QualityGateStatus,
    ValidationTag,
)
from research_machine.interfaces.cli import main
from research_machine.reporting.synthesis import build_synthesis
from test_ethics_gate import _human_protocol
from test_execution import frozen_formal_protocol, prepared_service, run_command


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
    assert "Blocking findings: PROTECTED_DATASET_LINEAGE_PROTOCOL_MISMATCH" in synthesis

    inventory = build_dataset_inventory([source, derived], [protocol], audit.findings)
    derived_row = next(
        row for row in inventory["datasets"]
        if row["dataset_id"] == derived.dataset_id
    )
    assert derived_row["readiness"]["status"] == "protected_use_blocked_by_rigor"
    assert derived_row["readiness"]["blocking_finding_codes"] == [
        "PROTECTED_DATASET_LINEAGE_PROTOCOL_MISMATCH"
    ]
    assert derived_row["rigor_findings"][0]["severity"] == "error"


def test_synthesis_reports_registered_dataset_inventory_without_overclaiming() -> None:
    inquiry = Inquiry(
        inquiry_id="inventory",
        title="Dataset inventory",
        initial_statement="What data have we actually registered?",
        created_at="2026-09-10T00:00:00Z",
        decision_to_support="Whether the workspace has usable data.",
        minimum_evidence=(
            "A deterministic manifest inventory that separates drafts from "
            "registered datasets."
        ),
        decision_change_criteria=["Do not claim access from a design brief."],
        decision_owner="project-owner",
    )
    protocol = ExperimentProtocol(
        protocol_id="protocol-v1",
        protocol_family_id="protocol",
        version=1,
        experiment_id="inventory-test",
        title="Inventory test",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[],
        primary_outcome="Outcome",
        created_at="2026-09-10T00:00:00Z",
        created_by="test",
        protocol_kind=ProtocolKind.OBSERVATIONAL,
        quality_requirements=["gate"],
        controls=["control"],
        sample_size_or_stopping_rule="synthetic fixture",
        status=ProtocolStatus.FROZEN,
        protocol_hash="c" * 64,
    )
    exploratory = DatasetManifest(
        dataset_id="exploratory-register",
        name="Exploratory register",
        role=DatasetRole.EXPLORATORY,
        created_at="2026-09-10T00:00:00Z",
        artifacts=[DatasetArtifact("explore.csv", "a" * 64, 10, "text/csv")],
        synthetic=False,
        metadata={"dataset_payload_sha256": "d" * 64},
    )
    protected = DatasetManifest(
        dataset_id="protected-register",
        name="Protected register",
        role=DatasetRole.CONFIRMATORY,
        created_at="2026-09-10T00:00:00Z",
        artifacts=[DatasetArtifact("observations.csv", "b" * 64, 12, "text/csv")],
        protocol_id=protocol.protocol_id,
        synthetic=False,
        metadata={
            "dataset_payload_sha256": "e" * 64,
            "dataset_artifact_verification": {
                "dataset_artifact_root": "/tmp/private-observations",
                "artifact_integrity": {
                    "status": "passed",
                    "all_artifacts_match": True,
                },
            },
        },
    )

    audit = audit_research_state(
        inquiry=inquiry,
        claims=[],
        hypotheses=[],
        evidence=[],
        datasets=[exploratory, protected],
        protocols=[protocol],
        runs=[],
    )
    synthesis = build_synthesis(
        inquiry,
        questions=[],
        claims=[],
        hypotheses=[],
        evidence=[],
        datasets=[exploratory, protected],
        protocols=[protocol],
        runs=[],
        recommendations=[],
        cross_lane_lessons=[],
        rigor_audit=audit,
        evidence_status_events=[],
    )

    assert "### Registered dataset inventory" in synthesis
    assert (
        "Role counts: confirmatory: 1, exploratory: 1; synthetic: 0; "
        "non-synthetic: 2"
    ) in synthesis
    assert (
        "Dataset `exploratory-register` [exploratory; non-synthetic; "
        "protocol unbound]"
    ) in synthesis
    assert "not a protected evidence dataset or proof of current local access" in synthesis
    assert (
        "Dataset `protected-register` [confirmatory; non-synthetic; "
        "protocol `protocol-v1`]"
    ) in synthesis
    assert "registered observation bytes service-verified under retained local custody" in synthesis
    assert "No dataset-scoped rigor blockers were detected by the current audit" in synthesis
    assert (
        "not proof of source truth, consent truth, measurement validity, "
        "or analysis adequacy"
    ) in synthesis
    assert "/tmp/private-observations" not in synthesis


def test_synthesis_dataset_inventory_explicitly_excludes_unregistered_sources() -> None:
    inquiry = Inquiry(
        inquiry_id="empty-inventory",
        title="Empty inventory",
        initial_statement="Do draft data-source mentions count?",
        created_at="2026-09-10T00:00:00Z",
    )
    audit = audit_research_state(
        inquiry=inquiry,
        claims=[],
        hypotheses=[],
        evidence=[],
        datasets=[],
        protocols=[],
        runs=[],
    )

    synthesis = build_synthesis(
        inquiry,
        questions=[],
        claims=[],
        hypotheses=[],
        evidence=[],
        datasets=[],
        protocols=[],
        runs=[],
        recommendations=[],
        cross_lane_lessons=[],
        rigor_audit=audit,
        evidence_status_events=[],
    )

    assert "### Registered dataset inventory" in synthesis
    assert "No datasets are registered in canonical workspace state" in synthesis
    assert "external plugin access" in synthesis
    assert "design briefs are not counted as datasets" in synthesis


def test_cli_reports_structured_dataset_inventory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    common = ["--workspace", str(workspace), "--json"]
    assert main([*common, "workspace", "init"]) == 0
    capsys.readouterr()
    assert main([
        *common,
        "inquiry",
        "create",
        "--id",
        "inventory",
        "--title",
        "Inventory",
        "--statement",
        "What datasets are registered?",
    ]) == 0
    capsys.readouterr()

    observations = tmp_path / "observations.csv"
    observations.write_text("unit,outcome\nu1,1\n", encoding="utf-8")
    assert main([
        *common,
        "dataset",
        "register",
        "--id",
        "cli-dataset",
        "--name",
        "CLI dataset",
        "--role",
        "exploratory",
        "--file",
        str(observations),
        "--synthetic",
        "--inquiry",
        "inventory",
    ]) == 0
    capsys.readouterr()

    assert main([*common, "dataset", "inventory", "--inquiry", "inventory"]) == 0
    result = json.loads(capsys.readouterr().out)["result"]

    assert result["registered_dataset_count"] == 1
    assert result["role_counts"] == {"exploratory": 1}
    row = result["datasets"][0]
    assert row["dataset_id"] == "cli-dataset"
    assert row["observation_access"]["status"] == "synthetic_fixture"
    assert row["readiness"]["status"] == "not_protected_evidence_dataset"
    assert row["rigor_findings"] == []
    assert row["operational_roots_redacted"] is True
    assert str(tmp_path) not in json.dumps(result)


def test_dataset_source_authority_records_connector_without_upgrading_authority(
    tmp_path: Path,
) -> None:
    service, _ = prepared_service(tmp_path)
    dataset = service.register_dataset(
        RegisterDataset(
            dataset_id="connector-source-fixture",
            name="Connector source fixture",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("connector.json", "a" * 64, 20, "application/json")],
            synthetic=False,
            metadata={
                "source_authority": {
                    "source_type": "scientific_connector",
                    "source_name": "Open scientific registry connector",
                    "source_record_id": "query-2026-09-13",
                    "retrieved_or_collected_at": "2026-09-13T12:00:00Z",
                    "limitations": [
                        "Connector output is retained as a source route only."
                    ],
                }
            },
        )
    )

    authority = dataset.metadata["source_authority"]
    assert authority["source_type"] == "scientific_connector"
    assert authority["classification_service_checked"] is True
    assert authority["source_truth_verified"] is False
    assert authority["custody_verified_by_source_authority"] is False
    assert authority["evidence_eligibility_conferred"] is False
    assert "not proof of source truth" in authority["authority_boundary"]

    inventory = service.dataset_inventory()
    row = inventory["datasets"][0]
    assert row["source_authority"]["status"] == "typed_source_route"
    assert row["source_authority"]["source_type"] == "scientific_connector"
    assert row["source_authority"]["source_truth_verified"] is False
    assert "does not confer evidence eligibility" in row["source_authority"]["summary"]
    synthesis = build_synthesis(
        service.repository.load_inquiry("formal"),
        questions=[],
        claims=[],
        hypotheses=[],
        evidence=[],
        datasets=[dataset],
        protocols=[],
        runs=[],
        recommendations=[],
        cross_lane_lessons=[],
        rigor_audit=audit_research_state(
            inquiry=service.repository.load_inquiry("formal"),
            claims=[],
            hypotheses=[],
            evidence=[],
            datasets=[dataset],
            protocols=[],
            runs=[],
        ),
        evidence_status_events=[],
    )
    assert "source authority: scientific_connector source route" in synthesis
    assert "does not confer evidence eligibility" in synthesis


def test_dataset_source_authority_rejects_overclaim_and_resealed_drift(
    tmp_path: Path,
) -> None:
    service, _ = prepared_service(tmp_path)
    with pytest.raises(ValidationError, match="overclaiming language"):
        service.register_dataset(
            RegisterDataset(
                dataset_id="overclaiming-source",
                name="Overclaiming source",
                role=DatasetRole.EXPLORATORY,
                artifacts=[DatasetArtifact("source.json", "b" * 64)],
                synthetic=False,
                metadata={
                    "source_authority": {
                        "source_type": "scientific_connector",
                        "source_name": "Connector that validated truth",
                    }
                },
            )
        )
    with pytest.raises(ValidationError, match="service-derived fields"):
        service.register_dataset(
            RegisterDataset(
                dataset_id="caller-service-field",
                name="Caller service field",
                role=DatasetRole.EXPLORATORY,
                artifacts=[DatasetArtifact("service-field.json", "d" * 64)],
                synthetic=False,
                metadata={
                    "source_authority": {
                        "source_type": "manual_import",
                        "source_name": "Researcher file import",
                        "source_truth_verified": False,
                    }
                },
            )
        )
    with pytest.raises(ValidationError, match="must include a UTC offset"):
        service.register_dataset(
            RegisterDataset(
                dataset_id="source-time-without-offset",
                name="Source time without offset",
                role=DatasetRole.EXPLORATORY,
                artifacts=[DatasetArtifact("source-time.json", "e" * 64)],
                synthetic=False,
                metadata={
                    "source_authority": {
                        "source_type": "scientific_connector",
                        "source_name": "Registry connector",
                        "retrieved_or_collected_at": "2026-09-13T12:00:00",
                    }
                },
            )
        )
    with pytest.raises(ValidationError, match="valid ISO-8601 timestamp"):
        service.register_dataset(
            RegisterDataset(
                dataset_id="source-time-invalid",
                name="Source time invalid",
                role=DatasetRole.EXPLORATORY,
                artifacts=[DatasetArtifact("source-time-invalid.json", "f" * 64)],
                synthetic=False,
                metadata={
                    "source_authority": {
                        "source_type": "manual_import",
                        "source_name": "Researcher file import",
                        "retrieved_or_collected_at": "after lunch",
                    }
                },
            )
        )

    accepted = service.register_dataset(
        RegisterDataset(
            dataset_id="typed-source",
            name="Typed source",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact("typed.json", "c" * 64)],
            synthetic=False,
            metadata={
                "source_authority": {
                    "source_type": "manual_import",
                    "source_name": "Researcher file import",
                }
            },
        )
    )
    dataset_path = (
        tmp_path
        / "inquiries"
        / "formal"
        / "datasets"
        / f"{accepted.dataset_id}.json"
    )
    record = json.loads(dataset_path.read_text(encoding="utf-8"))
    record["metadata"]["source_authority"]["evidence_eligibility_conferred"] = True
    record["metadata"].pop("dataset_payload_sha256", None)
    record["metadata"]["dataset_payload_sha256"] = dataset_payload_sha256(
        DatasetManifest.from_dict(record)
    )
    dataset_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="evidence_eligibility_conferred must be false",
    ):
        service.list_datasets()


def test_run_intake_replays_dataset_source_authority_lineage(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    draft = service.create_protocol(CreateProtocol(
        experiment_id="source-authority-run-test",
        title="Source authority run test",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=[hypothesis_id],
        primary_outcome="Outcome",
        protocol_kind=ProtocolKind.FORMAL,
        methodology="Replay a synthetic source-authority fixture.",
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
        dataset_id="source-authority-source",
        name="Source authority source",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact("source.csv", "c" * 64)],
        protocol_id=protocol.protocol_id,
        synthetic=True,
        metadata={
            "source_authority": {
                "source_type": "synthetic_fixture",
                "source_name": "Synthetic source-authority fixture",
            }
        },
    ))
    derived = service.register_dataset(RegisterDataset(
        dataset_id="source-authority-derived",
        name="Source authority derived",
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
    record = json.loads(source_path.read_text(encoding="utf-8"))
    record["metadata"]["source_authority"]["source_truth_verified"] = True
    record["metadata"].pop("dataset_payload_sha256", None)
    record["metadata"]["dataset_payload_sha256"] = dataset_payload_sha256(
        DatasetManifest.from_dict(record)
    )
    source_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="source_truth_verified must be false",
    ):
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
            summary="Synthetic source-authority fixture.",
            synthetic=True,
            metadata={
                "protocol_deviation_disclosure": {
                    "status": "no_deviations_declared",
                    "deviations": [],
                }
            },
        ))


def test_evidence_admission_replays_dataset_source_authority(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    dataset = service.register_dataset(RegisterDataset(
        dataset_id="source-authority-evidence-dataset",
        name="Source authority evidence dataset",
        role=DatasetRole.EXPLORATORY,
        artifacts=[DatasetArtifact("evidence.csv", "f" * 64)],
        synthetic=True,
        metadata={
            "source_authority": {
                "source_type": "synthetic_fixture",
                "source_name": "Synthetic source-authority evidence fixture",
            }
        },
    ))
    dataset_path = (
        tmp_path
        / "inquiries"
        / "formal"
        / "datasets"
        / f"{dataset.dataset_id}.json"
    )
    record = json.loads(dataset_path.read_text(encoding="utf-8"))
    record["metadata"]["source_authority"]["source_truth_verified"] = True
    record["metadata"].pop("dataset_payload_sha256", None)
    record["metadata"]["dataset_payload_sha256"] = dataset_payload_sha256(
        DatasetManifest.from_dict(record)
    )
    dataset_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="source_truth_verified must be false",
    ):
        service.record_evidence(RecordEvidence(
            hypothesis_id=hypothesis_id,
            direction=EvidenceDirection.INCONCLUSIVE,
            summary="The synthetic fixture remains inconclusive.",
            dataset_id=dataset.dataset_id,
            analysis_id="source-authority-evidence-analysis",
            uncertainty="Synthetic fixture only.",
            scope="Synthetic fixture only.",
            higher_level_conclusions_unsupported=[
                "Source truth, custody, and evidence eligibility remain unverified."
            ],
            validation_tags=[ValidationTag.CALIBRATION],
            exploratory=True,
        ))


def test_scientific_evidence_replay_checks_dataset_source_authority(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, hypothesis_id)
    observations = tmp_path / "observations.csv"
    observations.write_text("unit,outcome\nu1,1\n", encoding="utf-8")
    dataset = service.register_dataset(RegisterDataset(
        dataset_id="source-authority-scientific-dataset",
        name="Source authority scientific dataset",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[_artifact(observations)],
        protocol_id=protocol.protocol_id,
        artifact_root=str(tmp_path),
        metadata={
            "source_authority": {
                "source_type": "registered_experiment",
                "source_name": "Registered source-authority replay fixture",
            }
        },
    ))
    output = tmp_path / "proof-output.json"
    output.write_text('{"checker":"passed"}\n', encoding="utf-8")
    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    run = service.record_run(run_command(
        protocol.protocol_id,
        QualityGateStatus.PASSED,
        dataset_ids=[dataset.dataset_id],
        artifact_root=str(tmp_path),
        output_artifacts=[
            DatasetArtifact(
                output.name,
                output_sha256,
                output.stat().st_size,
                "application/json",
            )
        ],
        quality_gates=[
            QualityGateResult(
                "proof-check",
                QualityGateStatus.PASSED,
                "Independent proof-checker result.",
                details={"evidence_sha256": output_sha256},
            )
        ],
    ))
    evidence = service.record_evidence(RecordEvidence(
        hypothesis_id=hypothesis_id,
        direction=EvidenceDirection.SUPPORTS,
        summary="The registered checker accepted the proof object.",
        analysis_id="",
        run_id=run.run_id,
        dataset_id=dataset.dataset_id,
        uncertainty="Bounded to the pinned formal system and checker implementation.",
        scope="The registered invariant in the frozen bounded proof system.",
        controls_passed=["Replay a deliberately invalid derivation."],
        higher_level_conclusions_unsupported=[
            "The candidate is empirically correct.",
            "The result has been independently replicated.",
        ],
        validation_tags=[
            ValidationTag.INTERNAL_CONSISTENCY,
            ValidationTag.CONTROLLED_BENCHMARK,
        ],
        exploratory=False,
    ))
    dataset_path = (
        tmp_path
        / "inquiries"
        / "formal"
        / "datasets"
        / f"{dataset.dataset_id}.json"
    )
    record = json.loads(dataset_path.read_text(encoding="utf-8"))
    record["metadata"]["source_authority"]["source_truth_verified"] = True
    record["metadata"].pop("dataset_payload_sha256", None)
    record["metadata"]["dataset_payload_sha256"] = dataset_payload_sha256(
        DatasetManifest.from_dict(record)
    )
    dataset_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="source_truth_verified must be false",
    ):
        validate_evidence_admission_receipts(
            [evidence],
            [],
            [run],
            [protocol],
            service.repository.list_datasets("formal"),
            [],
        )


def test_run_backed_exploratory_evidence_replays_all_dataset_source_authority(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    draft = service.create_protocol(CreateProtocol(
        experiment_id="exploratory-source-authority",
        title="Exploratory source-authority replay",
        analysis_mode=AnalysisMode.EXPLORATORY,
        hypotheses_tested=[hypothesis_id],
        primary_outcome="Exploratory source route verdict",
        protocol_kind=ProtocolKind.FORMAL,
        methodology="Replay exploratory source-route checks.",
        quality_requirements=["proof-check"],
        controls=["A deliberately invalid derivation must fail."],
        expected_outputs=["Exploratory transcript"],
        success_conditions=["The exploratory route is reproducible."],
        environment_requirements=["Pinned checker"],
        sample_size_or_stopping_rule="Two exploratory source fixtures.",
        failure_conditions=["A source route cannot be reconstructed."],
        safety_constraints=["Do not report this as confirmation."],
        analysis_code_hash="a" * 64,
    ))
    protocol = service.freeze_protocol(draft.protocol_id)
    datasets = [
        service.register_dataset(RegisterDataset(
            dataset_id=f"exploratory-source-authority-{index}",
            name=f"Exploratory source authority {index}",
            role=DatasetRole.EXPLORATORY,
            artifacts=[DatasetArtifact(f"source-{index}.csv", str(index) * 64)],
            protocol_id=protocol.protocol_id,
            synthetic=True,
            metadata={
                "source_authority": {
                    "source_type": "synthetic_fixture",
                    "source_name": f"Synthetic exploratory source {index}",
                }
            },
        ))
        for index in (1, 2)
    ]
    run = service.record_run(RecordRun(
        protocol_id=protocol.protocol_id,
        started_at="2026-09-02T12:01:00Z",
        completed_at="2026-09-02T12:02:00Z",
        analysis_code_hash="a" * 64,
        environment_hash="b" * 64,
        dataset_ids=[dataset.dataset_id for dataset in datasets],
        output_artifacts=[
            DatasetArtifact("result.json", "e" * 64, media_type="application/json")
        ],
        quality_gates=[
            QualityGateResult(
                "proof-check",
                QualityGateStatus.PASSED,
                "Synthetic fixture gate.",
                details={"evidence_sha256": "e" * 64},
            )
        ],
        summary="Synthetic exploratory source-authority fixture.",
        synthetic=True,
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
    ))
    dataset_path = (
        tmp_path
        / "inquiries"
        / "formal"
        / "datasets"
        / f"{datasets[1].dataset_id}.json"
    )
    record = json.loads(dataset_path.read_text(encoding="utf-8"))
    record["metadata"]["source_authority"]["evidence_eligibility_conferred"] = True
    record["metadata"].pop("dataset_payload_sha256", None)
    record["metadata"]["dataset_payload_sha256"] = dataset_payload_sha256(
        DatasetManifest.from_dict(record)
    )
    dataset_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="evidence_eligibility_conferred must be false",
    ):
        service.record_evidence(RecordEvidence(
            hypothesis_id=hypothesis_id,
            direction=EvidenceDirection.INCONCLUSIVE,
            summary="The exploratory run remains inconclusive.",
            analysis_id=run.run_id,
            run_id=run.run_id,
            uncertainty="Synthetic exploratory fixture only.",
            scope="Synthetic exploratory fixture only.",
            higher_level_conclusions_unsupported=[
                "Source truth, custody, and evidence eligibility remain unverified."
            ],
            validation_tags=[ValidationTag.CALIBRATION],
            exploratory=True,
        ))


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
    inventory = service.dataset_inventory()
    assert inventory["registered_dataset_count"] == 1
    row = inventory["datasets"][0]
    assert row["dataset_id"] == dataset.dataset_id
    assert row["observation_access"]["status"] == (
        "protected_observation_bytes_service_verified"
    )
    assert row["readiness"]["status"] == "protected_no_dataset_rigor_blockers_detected"
    assert row["readiness"]["blocking_finding_codes"] == []
    assert row["rigor_findings"] == []
    assert row["payload_commitment"]["sealed"] is True
    assert row["operational_roots_redacted"] is True
    assert str(tmp_path.resolve()) not in json.dumps(inventory)

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
