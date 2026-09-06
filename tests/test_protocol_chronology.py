from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    CreateInquiry,
    CreateProtocol,
    ProposeHypothesis,
    RecordRun,
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


CODE_HASH = "a" * 64
ENVIRONMENT_HASH = "b" * 64


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _service(tmp_path: Path, *, external_anchor: str | None):
    counter = iter(f"chronology{index:02d}" for index in range(100))
    service = ResearchService(
        FileSystemRepository(tmp_path / "workspace"),
        actor="external-executor",
        clock=lambda: "2026-09-03T12:00:00Z",
        token=lambda: next(counter),
    )
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            "External protocol chronology",
            "Was the returned protocol frozen before execution?",
            "external-protocol-chronology",
        )
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The external execution follows its frozen protocol.",
            observable_prediction="The declared freeze predates the run.",
            null_model="The protocol was specified after the run began.",
            falsification_conditions=["The freeze manifest postdates execution."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    draft = service.create_protocol(
        CreateProtocol(
            experiment_id="external-accession",
            title="Accession an externally frozen execution",
            analysis_mode=AnalysisMode.REPLICATION,
            hypotheses_tested=[hypothesis.hypothesis_id],
            primary_outcome="External freeze chronology",
            protocol_kind=ProtocolKind.COMPUTATIONAL,
            methodology="Verify returned artifacts without rerunning the analysis.",
            quality_requirements=["intake-integrity"],
            controls=["A mutated freeze manifest must fail."],
            expected_outputs=["Returned source, protocol, manifest, and result"],
            success_conditions=["The external freeze predates execution."],
            environment_requirements=["Local SHA-256 artifact verification"],
            sample_size_or_stopping_rule="One returned execution packet.",
            failure_conditions=["Any external freeze commitment fails."],
            safety_constraints=["No physical intervention."],
            analysis_code_hash=CODE_HASH,
            external_anchor=external_anchor,
        )
    )
    return service, service.freeze_protocol(draft.protocol_id)


def _artifacts(tmp_path: Path, *, wrong_analysis_hash: bool = False):
    root = tmp_path / "returned"
    root.mkdir()
    protocol_path = root / "protocol.md"
    source_path = root / "source.py"
    result_path = root / "result.json"
    manifest_path = root / "freeze-manifest.json"
    protocol_path.write_text("# Externally frozen protocol\n", encoding="utf-8")
    source_path.write_text("raise SystemExit('never execute during intake')\n", encoding="utf-8")
    result_path.write_text('{"outcome":"preserved"}\n', encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "frozen_at": "2026-09-03T10:00:00Z",
                "scientific_execution_count_at_freeze": 0,
                "analysis_code_sha256": (
                    "0" * 64 if wrong_analysis_hash else CODE_HASH
                ),
                "protocol_sha256": _sha256(protocol_path),
                "artifacts": [
                    {
                        "locator": "protocol.md",
                        "sha256": _sha256(protocol_path),
                    },
                    {
                        "locator": "source.py",
                        "sha256": _sha256(source_path),
                    },
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return root, [
        DatasetArtifact(
            "protocol.md",
            _sha256(protocol_path),
            size_bytes=protocol_path.stat().st_size,
            metadata={"artifact_role": "external_frozen_protocol"},
        ),
        DatasetArtifact(
            "source.py",
            _sha256(source_path),
            size_bytes=source_path.stat().st_size,
            metadata={"artifact_role": "analysis_source"},
        ),
        DatasetArtifact(
            "freeze-manifest.json",
            _sha256(manifest_path),
            size_bytes=manifest_path.stat().st_size,
            metadata={"artifact_role": "external_freeze_manifest"},
        ),
        DatasetArtifact(
            "result.json",
            _sha256(result_path),
            size_bytes=result_path.stat().st_size,
        ),
    ]


def _run(protocol_id: str, root: Path, artifacts: list[DatasetArtifact], **overrides):
    values = {
        "protocol_id": protocol_id,
        "started_at": "2026-09-03T11:00:00Z",
        "completed_at": "2026-09-03T11:01:00Z",
        "analysis_code_hash": CODE_HASH,
        "environment_hash": ENVIRONMENT_HASH,
        "output_artifacts": artifacts,
        "quality_gates": [
            QualityGateResult(
                gate_id="intake-integrity",
                status=QualityGateStatus.PASSED,
                summary="The returned bytes and declarations passed intake.",
                details={"evidence_sha256": artifacts[-1].sha256},
            )
        ],
        "metadata": {"protocol_deviation_disclosure": {
            "status": "no_deviations_declared", "deviations": [],
        }},
        "artifact_root": str(root),
    }
    values.update(overrides)
    metadata = {"protocol_deviation_disclosure": {
        "status": "no_deviations_declared", "deviations": [],
    }}
    metadata.update(values.get("metadata", {}))
    values["metadata"] = metadata
    return RecordRun(**values)


def _external_metadata(**overrides):
    value = {
        "declared_frozen_at": "2026-09-03T10:00:00Z",
        "canonicalized_after_execution": True,
        "protocol_artifact": "protocol.md",
        "analysis_source_artifact": "source.py",
        "freeze_manifest_artifact": "freeze-manifest.json",
    }
    value.update(overrides)
    return {"external_protocol_freeze": value}


def test_run_before_canonical_registration_requires_external_freeze(
    tmp_path: Path,
) -> None:
    service, protocol = _service(tmp_path, external_anchor=None)
    root, artifacts = _artifacts(tmp_path)

    with pytest.raises(ValidationError, match="started before canonical"):
        service.preflight_run(_run(protocol.protocol_id, root, artifacts))


def test_external_freeze_is_hash_checked_and_receipted(tmp_path: Path) -> None:
    service, protocol = _service(tmp_path, external_anchor="sha256:external-anchor")
    root, artifacts = _artifacts(tmp_path)
    command = _run(
        protocol.protocol_id,
        root,
        artifacts,
        metadata=_external_metadata(),
    )

    preflight = service.preflight_run(command)
    assert preflight.status == "ready"
    assert preflight.artifact_integrity is not None
    assert preflight.artifact_integrity["status"] == "passed"
    assert preflight.protocol_chronology == {
        "status": "externally_attested_pre_execution_freeze",
        "canonical_registration_timestamp": "2026-09-03T12:00:00Z",
        "external_declared_frozen_at": "2026-09-03T10:00:00Z",
        "run_started_at": "2026-09-03T11:00:00+00:00",
        "canonical_registration_precedes_run": False,
        "canonicalized_after_execution": True,
        "external_anchor": "sha256:external-anchor",
        "protocol_artifact": "protocol.md",
        "analysis_source_artifact": "source.py",
        "freeze_manifest_artifact": "freeze-manifest.json",
        "chronology_cryptographically_verified": False,
    }

    run = service.record_run(command)
    assert run.scientific_evidence_eligible is True
    assert run.metadata["protocol_chronology"] == preflight.protocol_chronology
    audit = service.audit_rigor()
    assert any(
        finding.code == "EXTERNAL_PROTOCOL_FREEZE_ATTESTED"
        and finding.entity_id == run.run_id
        for finding in audit.findings
    )


def test_external_freeze_manifest_mismatch_fails_preflight(tmp_path: Path) -> None:
    service, protocol = _service(tmp_path, external_anchor="sha256:external-anchor")
    root, artifacts = _artifacts(tmp_path, wrong_analysis_hash=True)

    preflight = service.preflight_run(
        _run(
            protocol.protocol_id,
            root,
            artifacts,
            metadata=_external_metadata(),
        )
    )

    assert preflight.status == "would_reject"
    assert preflight.artifact_integrity is not None
    assert "EXTERNAL_FREEZE_ANALYSIS_HASH_MISMATCH" in {
        item["code"] for item in preflight.artifact_integrity["findings"]
    }


def test_external_freeze_time_must_precede_execution(tmp_path: Path) -> None:
    service, protocol = _service(tmp_path, external_anchor="sha256:external-anchor")
    root, artifacts = _artifacts(tmp_path)

    with pytest.raises(ValidationError, match="must not postdate"):
        service.preflight_run(
            _run(
                protocol.protocol_id,
                root,
                artifacts,
                metadata=_external_metadata(
                    declared_frozen_at="2026-09-03T11:30:00Z"
                ),
            )
        )


def test_protocol_chronology_receipt_is_machine_reserved(tmp_path: Path) -> None:
    service, protocol = _service(tmp_path, external_anchor=None)
    root, artifacts = _artifacts(tmp_path)

    with pytest.raises(ValidationError, match="reserved for machine verification"):
        service.preflight_run(
            _run(
                protocol.protocol_id,
                root,
                artifacts,
                started_at="2026-09-03T12:01:00Z",
                completed_at="2026-09-03T12:02:00Z",
                metadata={"protocol_chronology": {"status": "local_preregistered"}},
            )
        )
