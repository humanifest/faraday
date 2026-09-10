from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    CreateInquiry,
    CreateProtocol,
    ProposeHypothesis,
    RecordEvidence,
    RecordEvidenceStatusEvent,
    RecordRun,
)
from research_machine.application.service import ResearchService
from research_machine.application.rigor import audit_research_state
from research_machine.application.policies import validate_validation_tag_context
from research_machine.reporting.synthesis import build_synthesis
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisMode,
    Claim,
    ClaimLevel,
    ControlDefinition,
    DatasetArtifact,
    DatasetManifest,
    DatasetRole,
    EvidenceDirection,
    Inquiry,
    EvidenceRecord,
    MeasurementDefinition,
    MeasurementRole,
    ProtocolKind,
    ProtocolStatus,
    QualityGateResult,
    QualityGateStatus,
    ResearchRun,
    RigorSeverity,
    ValidationTag,
)


def _service(root: Path, *, actor: str = "author") -> ResearchService:
    counter = iter(f"{actor}{index:02d}" for index in range(100))
    return ResearchService(
        FileSystemRepository(root),
        actor=actor,
        clock=lambda: "2026-09-02T12:00:00Z",
        token=lambda: next(counter),
    )


def _prepared_run(
    root: Path,
    *,
    protocol_overrides: dict | None = None,
    run_summary: str = "",
    gate_summary: str = "Candidate passed and invalid control failed.",
):
    service = _service(root)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry("Rigor gate", "Can the result survive overclaim checks?", "rigor")
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The candidate preserves the registered invariant.",
            observable_prediction="The checker accepts the invariant.",
            null_model="The checker rejects the invariant.",
            falsification_conditions=["A required checker gate fails."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    protocol_values = {
        "experiment_id": "rigor-check",
        "title": "Controlled invariant check",
        "analysis_mode": AnalysisMode.CONFIRMATORY,
        "hypotheses_tested": [hypothesis.hypothesis_id],
        "primary_outcome": "Checker acceptance",
        "protocol_kind": ProtocolKind.FORMAL,
        "methodology": "Replay the candidate and a deliberately invalid control.",
        "quality_requirements": ["checker"],
        "controls": ["The deliberately invalid candidate must fail."],
        "expected_outputs": ["Checker transcript"],
        "success_conditions": ["The candidate passes and the control fails."],
        "environment_requirements": ["Pinned checker"],
        "sample_size_or_stopping_rule": "One candidate and one fixed negative control.",
        "failure_conditions": ["Any required assertion fails."],
        "safety_constraints": ["No physical intervention."],
        "analysis_code_hash": "a" * 64,
    }
    protocol_values.update(protocol_overrides or {})
    draft = service.create_protocol(CreateProtocol(**protocol_values))
    protocol = service.freeze_protocol(draft.protocol_id)
    output = root / "result.json"
    output.write_text('{"checker":"passed"}\n', encoding="utf-8")
    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    run = service.record_run(
        RecordRun(
            protocol_id=protocol.protocol_id,
            started_at="2026-09-02T12:01:00Z",
            completed_at="2026-09-02T12:02:00Z",
            analysis_code_hash="a" * 64,
            environment_hash="b" * 64,
            output_artifacts=[DatasetArtifact(
                "result.json", output_sha256, output.stat().st_size,
                "application/json",
            )],
            artifact_root=str(root),
            quality_gates=[
                QualityGateResult(
                    gate_id="checker",
                    status=QualityGateStatus.PASSED,
                    summary=gate_summary,
                    details={"evidence_sha256": output_sha256},
                )
            ],
            summary=run_summary,
            metadata={"protocol_deviation_disclosure": {
                "status": "no_deviations_declared", "deviations": [],
            }},
        )
    )
    return service, hypothesis, run


def test_rigor_reports_missed_precision_without_marking_run_invalid(tmp_path) -> None:
    service, hypothesis, run = _prepared_run(tmp_path)
    repository = service.repository
    inquiry_id = repository.resolve_inquiry_id(None)
    protocol = service.get_protocol(run.protocol_id)
    precision_protocol = replace(
        protocol, sample_size_plan={"strategy": "precision"},
    )
    observed_run = replace(run, metadata={
        **run.metadata,
        "sample_size_plan_check": {
            "status": "passed",
            "precision_achievement": {
                "status": "not_met", "target_half_width": 1.0,
                "observed_half_width": 1.5,
            },
            "attrition_achievement": {
                "status": "exceeded_assumption",
                "anticipated_attrition_fraction": 0.1,
                "observed_excluded_fraction": 0.15,
                "observed_excluded_fraction_by_group": {"a": 0.1, "b": 0.2},
            },
            "variance_assumption": {
                "status": "exceeded_registered_tolerance",
                "observed_to_assumed_ratio": 1.5,
                "maximum_registered_ratio": 1.25,
                "assumed_standard_deviation": 2.0,
                "observed_pooled_standard_deviation": 3.0,
                "measurement_unit": "fixture units",
                "adequacy_threshold_registered": True,
            },
        },
    })
    inquiry = repository.load_inquiry(inquiry_id)
    claims = repository.load_claims(inquiry_id)
    evidence = repository.list_evidence(inquiry_id)
    datasets = repository.list_datasets(inquiry_id)
    audit = audit_research_state(
        inquiry=inquiry, claims=claims,
        hypotheses=[hypothesis], evidence=evidence, datasets=datasets,
        protocols=[precision_protocol], runs=[observed_run],
    )
    finding = next(
        item for item in audit.findings
        if item.code == "RUN_PRECISION_TARGET_NOT_MET"
    )
    assert finding.entity_id == run.run_id
    assert "observed half-width 1.5 against target 1" in finding.remediation
    attrition_finding = next(
        item for item in audit.findings
        if item.code == "RUN_ATTRITION_EXCEEDED_PLANNING_ASSUMPTION"
    )
    assert "observed excluded fraction 0.15 against anticipated 0.1" in attrition_finding.remediation
    variance_finding = next(
        item for item in audit.findings
        if item.code == "RUN_VARIANCE_EXCEEDED_REGISTERED_TOLERANCE"
    )
    assert "ratio 1.5 against registered maximum 1.25" in variance_finding.remediation
    assert observed_run.status.value == "completed"
    assert observed_run.scientific_evidence_eligible is True
    synthesis = build_synthesis(
        inquiry, [], claims, [hypothesis], evidence, datasets,
        [precision_protocol], [observed_run], [], [], audit, [],
    )
    assert "Precision target: not_met; target half-width 1.0" in synthesis
    assert "evidence eligible: yes" in synthesis
    assert "A missed target does not erase the result or imply invalidity." in synthesis
    assert "Attrition assumption: exceeded_assumption" in synthesis
    assert "Variability assumption: exceeded_registered_tolerance" in synthesis
    assert "Registered maximum ratio 1.25." in synthesis
    assert "a planning miss does not erase the result or imply invalidity." in synthesis


def test_rigor_and_synthesis_expose_protocol_factor_interpretability(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(
        tmp_path / "workspace",
        protocol_overrides={
            "manipulated_factors": ["person", "room"],
            "factorial_or_crossover_design": True,
            "factor_interpretability_plan": (
                "Cross person and room assignments before interpreting either factor."
            ),
        },
    )
    repository = service.repository
    inquiry_id = repository.resolve_inquiry_id(None)
    protocols = repository.list_protocols(inquiry_id)
    audit = audit_research_state(
        inquiry=repository.load_inquiry(inquiry_id),
        claims=repository.load_claims(inquiry_id),
        hypotheses=[hypothesis],
        evidence=repository.list_evidence(inquiry_id),
        datasets=repository.list_datasets(inquiry_id),
        protocols=protocols,
        runs=[run],
    )
    finding = next(
        item for item in audit.findings
        if item.code == "PROTOCOL_FACTOR_INTERPRETABILITY_DECLARED"
    )
    assert finding.entity_id == run.protocol_id
    synthesis = build_synthesis(
        repository.load_inquiry(inquiry_id),
        repository.load_questions(inquiry_id),
        repository.load_claims(inquiry_id),
        [hypothesis],
        repository.list_evidence(inquiry_id),
        repository.list_datasets(inquiry_id),
        protocols,
        [run],
        [],
        [],
        audit,
        [],
    )
    assert "Manipulated-factor interpretability" in synthesis
    assert "person, room (factorial/crossover declared; plan:" in synthesis
    assert "not proof that factor effects are separable" in synthesis


def test_rigor_flags_inverted_claim_dependency_levels(tmp_path: Path) -> None:
    inquiry = CreateInquiry(
        "Claim ladder",
        "Can a lower-level claim depend on a stronger conclusion?",
        "claim-ladder",
    )
    service = _service(tmp_path)
    service.init_workspace()
    service.create_inquiry(inquiry)
    causal = service.add_claim(
        AddClaim(
            statement="The registered condition caused the event in scope.",
            level=ClaimLevel.CAUSAL_DIRECTION,
        )
    )
    measurement = Claim(
        claim_id="clm-inverted",
        statement="The instrument detected the event.",
        level=ClaimLevel.MEASUREMENT_VALIDITY,
        created_at="2026-09-02T12:00:00Z",
        parent_claims=[causal.claim_id],
    )
    audit = audit_research_state(
        inquiry=service.repository.load_inquiry("claim-ladder"),
        claims=[causal, measurement],
        hypotheses=[],
        evidence=[],
        datasets=[],
        protocols=[],
        runs=[],
    )
    finding = next(
        item for item in audit.findings
        if item.code == "CLAIM_DEPENDENCY_LEVEL_INVERTED"
    )
    assert finding.entity_id == measurement.claim_id
    assert causal.claim_id in finding.message


def test_rigor_flags_legacy_support_for_explanatory_claim_levels(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            "Mechanism ceiling",
            "Can weak validation tags support a mechanism claim?",
            "mechanism-ceiling",
        )
    )
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="A mechanism explains the observed pattern.",
            observable_prediction="The registered pattern recurs.",
            null_model="The pattern does not recur beyond measurement error.",
            competing_models=["Measurement error creates the pattern."],
            falsification_conditions=["The registered pattern is absent."],
        )
    )
    hypothesis = service.activate_hypothesis(hypothesis.hypothesis_id)
    claim = service.add_claim(
        AddClaim(
            statement="The proposed mechanism explains the observed pattern.",
            level=ClaimLevel.MECHANISM,
        )
    )
    dataset = DatasetManifest(
        "dataset-mechanism-fixture",
        "Mechanism fixture",
        DatasetRole.EXPLORATORY,
        "2026-09-02T12:00:00Z",
        [DatasetArtifact("mechanism.csv", "a" * 64)],
    )
    evidence = EvidenceRecord(
        "evd-legacy-mechanism",
        hypothesis.hypothesis_id,
        EvidenceDirection.SUPPORTS,
        "A legacy fixture incorrectly supports the mechanism claim.",
        dataset.dataset_id,
        "analysis-mechanism-fixture",
        "2026-09-02T12:00:00Z",
        claim_id=claim.claim_id,
        uncertainty="The fixture does not distinguish mechanism from alternatives.",
        scope="Synthetic fixture only.",
        controls_passed=["negative control fixture"],
        higher_level_conclusions_unsupported=[
            "Adaptation and intent remain unsupported."
        ],
        validation_tags=[ValidationTag.CALIBRATION],
        exploratory=True,
    )
    audit = audit_research_state(
        inquiry=service.repository.load_inquiry("mechanism-ceiling"),
        claims=[claim],
        hypotheses=[hypothesis],
        evidence=[evidence],
        datasets=[dataset],
        protocols=[],
        runs=[],
    )
    finding = next(
        item for item in audit.findings
        if item.code == "VALIDATION_TAG_UNSUPPORTED"
    )
    assert finding.entity_id == evidence.evidence_id
    assert "supporting evidence cannot target mechanism" in finding.message


def test_rigor_replays_execution_method_inference_ceiling_for_legacy_evidence(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path / "workspace")
    claim = service.add_claim(
        AddClaim(
            statement="The registered condition is associated with the measured outcome.",
            level=ClaimLevel.STATISTICAL_ASSOCIATION,
        )
    )
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    legacy_evidence = replace(evidence, claim_id=claim.claim_id)
    legacy_run = replace(
        run,
        metadata={
            **run.metadata,
            "execution_handoff": {
                "result": {"maximum_inference_level": "descriptive"}
            },
        },
    )
    repository = service.repository
    inquiry_id = repository.resolve_inquiry_id(None)

    audit = audit_research_state(
        inquiry=repository.load_inquiry(inquiry_id),
        claims=[claim],
        hypotheses=[hypothesis],
        evidence=[legacy_evidence],
        datasets=repository.list_datasets(inquiry_id),
        protocols=repository.list_protocols(inquiry_id),
        runs=[legacy_run],
    )

    finding = next(
        item for item in audit.findings
        if item.code == "VALIDATION_TAG_UNSUPPORTED"
    )
    assert finding.entity_id == legacy_evidence.evidence_id
    assert "executed method inference ceiling" in finding.message
    assert "descriptive permits measurement_validity" in finding.message


def test_rigor_flags_legacy_unresolved_multi_factor_protocol(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path / "workspace")
    repository = service.repository
    inquiry_id = repository.resolve_inquiry_id(None)
    protocol = replace(
        repository.list_protocols(inquiry_id)[0],
        manipulated_factors=["person", "room"],
    )
    audit = audit_research_state(
        inquiry=repository.load_inquiry(inquiry_id),
        claims=repository.load_claims(inquiry_id),
        hypotheses=[hypothesis],
        evidence=repository.list_evidence(inquiry_id),
        datasets=repository.list_datasets(inquiry_id),
        protocols=[protocol],
        runs=[run],
    )
    finding = next(
        item for item in audit.findings
        if item.code == "PROTOCOL_FACTOR_INTERPRETABILITY_UNRESOLVED"
    )
    assert finding.severity is RigorSeverity.ERROR
    synthesis = build_synthesis(
        repository.load_inquiry(inquiry_id),
        repository.load_questions(inquiry_id),
        repository.load_claims(inquiry_id),
        [hypothesis],
        repository.list_evidence(inquiry_id),
        repository.list_datasets(inquiry_id),
        [protocol],
        [run],
        [],
        [],
        audit,
        [],
    )
    assert "person, room (missing factorial/crossover declaration" in synthesis
    assert "missing factor-interpretability plan" in synthesis


def _classified_evidence(hypothesis_id: str, run_id: str, **overrides):
    values = {
        "hypothesis_id": hypothesis_id,
        "direction": EvidenceDirection.SUPPORTS,
        "summary": "The registered controlled checker accepted the candidate.",
        "analysis_id": "",
        "run_id": run_id,
        "uncertainty": "Bounded to the pinned formal system and checker.",
        "scope": "The registered invariant only.",
        "controls_passed": ["The deliberately invalid candidate was rejected."],
        "higher_level_conclusions_unsupported": [
            "The candidate is empirically correct.",
            "The result is independently replicated.",
        ],
        "validation_tags": [
            ValidationTag.INTERNAL_CONSISTENCY,
            ValidationTag.CONTROLLED_BENCHMARK,
        ],
        "exploratory": False,
    }
    values.update(overrides)
    return RecordEvidence(**values)


def test_rigor_flags_legacy_overclaiming_evidence_summary_without_rewriting(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path / "workspace")
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    legacy_evidence = replace(
        evidence,
        summary="This confirmed and explained the mechanism.",
    )
    repository = service.repository
    inquiry_id = repository.resolve_inquiry_id(None)
    hypotheses = repository.list_hypotheses(inquiry_id)
    audit = audit_research_state(
        inquiry=repository.load_inquiry(inquiry_id),
        claims=repository.load_claims(inquiry_id),
        hypotheses=hypotheses,
        evidence=[legacy_evidence],
        datasets=repository.list_datasets(inquiry_id),
        protocols=repository.list_protocols(inquiry_id),
        runs=repository.list_runs(inquiry_id),
    )
    finding = next(
        item for item in audit.findings
        if item.code == "EVIDENCE_SUMMARY_OVERCLAIM_LANGUAGE"
    )
    assert finding.entity_id == evidence.evidence_id
    assert "confirmed, explained" in finding.message
    assert "Do not rewrite" in finding.remediation
    synthesis = build_synthesis(
        repository.load_inquiry(inquiry_id),
        repository.load_questions(inquiry_id),
        repository.load_claims(inquiry_id),
        hypotheses,
        [legacy_evidence],
        repository.list_datasets(inquiry_id),
        repository.list_protocols(inquiry_id),
        repository.list_runs(inquiry_id),
        [],
        [],
        audit,
        [],
    )
    assert "This confirmed and explained the mechanism." in synthesis
    assert "EVIDENCE_SUMMARY_OVERCLAIM_LANGUAGE (1)" in synthesis


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run", "This confirmed the execution result.", "run summary"),
        ("gate", "This gate explained the mechanism.", "quality gate summary"),
    ],
)
def test_new_run_and_gate_summaries_reject_report_overclaim_language(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    kwargs = {"run_summary": value} if field == "run" else {"gate_summary": value}
    with pytest.raises(ValidationError, match=message):
        _prepared_run(tmp_path / field, **kwargs)


def test_rigor_flags_legacy_overclaiming_run_and_gate_summaries_without_rewriting(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path / "workspace")
    legacy_run = replace(
        run,
        summary="The run confirmed the model.",
        quality_gates=[
            replace(
                run.quality_gates[0],
                summary="The gate explained the effect.",
            )
        ],
    )
    repository = service.repository
    inquiry_id = repository.resolve_inquiry_id(None)
    audit = audit_research_state(
        inquiry=repository.load_inquiry(inquiry_id),
        claims=repository.load_claims(inquiry_id),
        hypotheses=[hypothesis],
        evidence=repository.list_evidence(inquiry_id),
        datasets=repository.list_datasets(inquiry_id),
        protocols=repository.list_protocols(inquiry_id),
        runs=[legacy_run],
    )

    run_finding = next(
        item for item in audit.findings
        if item.code == "RUN_SUMMARY_OVERCLAIM_LANGUAGE"
    )
    gate_finding = next(
        item for item in audit.findings
        if item.code == "QUALITY_GATE_SUMMARY_OVERCLAIM_LANGUAGE"
    )
    assert run_finding.entity_id == run.run_id
    assert "confirmed" in run_finding.message
    assert gate_finding.entity_id == f"{run.run_id}:checker"
    assert "explained" in gate_finding.message
    synthesis = build_synthesis(
        repository.load_inquiry(inquiry_id),
        repository.load_questions(inquiry_id),
        repository.load_claims(inquiry_id),
        [hypothesis],
        repository.list_evidence(inquiry_id),
        repository.list_datasets(inquiry_id),
        repository.list_protocols(inquiry_id),
        [legacy_run],
        [],
        [],
        audit,
        [],
    )
    assert "RUN_SUMMARY_OVERCLAIM_LANGUAGE (1)" in synthesis
    assert "QUALITY_GATE_SUMMARY_OVERCLAIM_LANGUAGE (1)" in synthesis


def _status_command(
    evidence_id: str, root: Path, name: str, status: str, **overrides
) -> RecordEvidenceStatusEvent:
    artifact = root / name
    artifact.write_text(f"{status} review for {evidence_id}", encoding="utf-8")
    values = {
        "evidence_id": evidence_id,
        "status": status,
        "effective_at": "2026-09-02T12:00:00Z",
        "reason": f"Independent review classified this evidence as {status}.",
        "review_artifact_locator": name,
        "review_artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "review_artifact_root": str(root),
    }
    values.update(overrides)
    return RecordEvidenceStatusEvent(**values)


def test_append_only_retraction_removes_evidence_from_current_rigor_not_history(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path / "workspace")
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    assert service.audit_rigor().capabilities["controlled_benchmark"] is True
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    event = service.record_evidence_status_event(
        _status_command(evidence.evidence_id, review_root, "retraction.txt", "retracted")
    )
    assert event.sequence == 1
    assert service.list_evidence()[0].evidence_id == evidence.evidence_id
    synthesis = service.build_synthesis()["content"]
    assert "current status: retracted" in synthesis
    assert "Currently contributing evidence records: 0" in synthesis
    assert "Evidence correction and retraction history" in synthesis
    assert service.audit_rigor().capabilities["controlled_benchmark"] is False
    (review_root / "retraction.txt").write_text("review bytes changed", encoding="utf-8")
    with pytest.raises(ValidationError, match="no longer matches its integrity receipt"):
        service.build_synthesis()


def test_evidence_status_chain_requires_exact_predecessor_and_retraction_is_terminal(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path / "workspace")
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    qualified = service.record_evidence_status_event(
        _status_command(evidence.evidence_id, review_root, "qualified.txt", "qualified")
    )
    with pytest.raises(ValidationError, match="exact latest"):
        service.record_evidence_status_event(
            _status_command(evidence.evidence_id, review_root, "bad.txt", "active")
        )
    retracted = service.record_evidence_status_event(
        _status_command(
            evidence.evidence_id,
            review_root,
            "retracted.txt",
            "retracted",
            supersedes_event_id=qualified.event_id,
        )
    )
    assert retracted.sequence == 2
    with pytest.raises(ValidationError, match="terminal"):
        service.record_evidence_status_event(
            _status_command(
                evidence.evidence_id,
                review_root,
                "reinstate.txt",
                "active",
                supersedes_event_id=retracted.event_id,
            )
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("evidence_id", "{evidence_id} ", "evidence_id must be canonical"),
        ("status", " qualified", "evidence status must be canonical"),
        ("event_id", " evidence-status-manual", "event_id must be canonical"),
        ("reason", " Independent review classified this evidence as qualified. ", "evidence status reason must be canonical"),
        ("review_artifact_locator", " qualified.txt", "review_artifact_locator must be canonical"),
        ("review_artifact_root", "{root} ", "review_artifact_root must be canonical"),
    ],
)
def test_evidence_status_command_handles_must_be_canonical(
    tmp_path: Path, field, value, message
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path / "workspace")
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    if value == "{evidence_id} ":
        value = f"{evidence.evidence_id} "
    elif value == "{root} ":
        value = f"{review_root} "

    command = _status_command(
        evidence.evidence_id, review_root, "qualified.txt", "qualified",
    )
    with pytest.raises(ValidationError, match=message):
        service.record_evidence_status_event(replace(command, **{field: value}))


def test_evidence_status_supersedes_handle_must_be_canonical(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path / "workspace")
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    qualified = service.record_evidence_status_event(
        _status_command(evidence.evidence_id, review_root, "qualified.txt", "qualified")
    )

    with pytest.raises(ValidationError, match="supersedes_event_id must be canonical"):
        service.record_evidence_status_event(
            _status_command(
                evidence.evidence_id,
                review_root,
                "active.txt",
                "active",
                supersedes_event_id=f"{qualified.event_id} ",
            )
        )


def test_evidence_status_reads_fail_closed_on_semantic_chain_tampering(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    service, hypothesis, run = _prepared_run(workspace)
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    event = service.record_evidence_status_event(
        _status_command(evidence.evidence_id, review_root, "qualified.txt", "qualified")
    )
    event_file = next(workspace.rglob(f"{event.event_id}.json"))
    tampered = json.loads(event_file.read_text(encoding="utf-8"))
    tampered["sequence"] = 3
    event_file.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValidationError, match="contiguous from 1"):
        service.list_evidence_status_events()
    with pytest.raises(ValidationError, match="contiguous from 1"):
        service.audit_rigor()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event_id", "{event_id} ", "evidence status event_id must be canonical"),
        ("evidence_id", "{evidence_id} ", "evidence status evidence_id must be canonical"),
        ("status", " qualified", "evidence status must be canonical"),
        ("effective_at", " 2026-09-02T12:00:00Z", "evidence status effective_at must be canonical"),
        ("supersedes_event_id", "{event_id} ", "evidence status supersedes_event_id must be canonical"),
        ("review_artifact_locator", " qualified.txt", "review artifact locator must be canonical"),
        ("review_artifact_root", "{root} ", "review artifact root must be canonical"),
        ("created_by", " test-researcher", "evidence status created_by must be canonical"),
        ("reason", " Independent review classified this evidence as qualified. ", "evidence status reason must be canonical"),
        ("conclusion_ceiling", " Append-only evidence interpretation status.", "evidence status conclusion ceiling must be canonical"),
    ],
)
def test_evidence_status_reads_fail_closed_on_noncanonical_chain_tampering(
    tmp_path: Path, field, value, message
) -> None:
    workspace = tmp_path / "workspace"
    service, hypothesis, run = _prepared_run(workspace)
    evidence = service.record_evidence(
        _classified_evidence(hypothesis.hypothesis_id, run.run_id)
    )
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    event = service.record_evidence_status_event(
        _status_command(evidence.evidence_id, review_root, "qualified.txt", "qualified")
    )
    if value == "{event_id} ":
        value = f"{event.event_id} "
    elif value == "{evidence_id} ":
        value = f"{evidence.evidence_id} "
    elif value == "{root} ":
        value = f"{review_root} "
    event_file = next(workspace.rglob(f"{event.event_id}.json"))
    tampered = json.loads(event_file.read_text(encoding="utf-8"))
    tampered[field] = value
    event_file.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        service.list_evidence_status_events()


def test_new_evidence_requires_scope_ceiling_and_classification(tmp_path: Path) -> None:
    service, hypothesis, run = _prepared_run(tmp_path)
    with pytest.raises(ValidationError, match="scope must not be empty"):
        service.record_evidence(
            RecordEvidence(
                hypothesis_id=hypothesis.hypothesis_id,
                direction=EvidenceDirection.INCONCLUSIVE,
                summary="An unscoped result must fail.",
                analysis_id="",
                run_id=run.run_id,
                exploratory=False,
            )
        )
    with pytest.raises(ValidationError, match="unclassified new evidence"):
        service.record_evidence(
            _classified_evidence(
                hypothesis.hypothesis_id,
                run.run_id,
                validation_tags=[],
            )
        )
    with pytest.raises(
        ValidationError,
        match="higher_level_conclusions_unsupported must not contain duplicates",
    ):
        service.record_evidence(
            _classified_evidence(
                hypothesis.hypothesis_id,
                run.run_id,
                higher_level_conclusions_unsupported=[
                    "Mechanism remains unsupported.",
                    " Mechanism remains unsupported. ",
                ],
            )
        )


def test_protocol_freeze_requires_controls_quality_gates_and_stop_rule(
    tmp_path: Path,
) -> None:
    service, hypothesis, _ = _prepared_run(tmp_path)
    draft = service.create_protocol(
        CreateProtocol(
            experiment_id="under-specified",
            title="Under-specified protocol",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[hypothesis.hypothesis_id],
            primary_outcome="An assertion",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Run one checker.",
            expected_outputs=["Output"],
            success_conditions=["The assertion passes."],
            environment_requirements=["Pinned checker"],
            failure_conditions=["The assertion fails."],
            safety_constraints=["No physical intervention."],
            analysis_code_hash="9" * 64,
        )
    )
    with pytest.raises(ValidationError) as captured:
        service.freeze_protocol(draft.protocol_id)
    message = str(captured.value)
    assert "quality_requirements" in message
    assert "controls" in message
    assert "sample_size_or_stopping_rule" in message


def test_rigor_warns_when_protected_protocol_lacks_discriminating_control_families():
    from test_ethics_gate import _human_protocol

    reference_only = replace(
        _human_protocol(human_subjects=False),
        status=ProtocolStatus.FROZEN,
    )
    inquiry = Inquiry(
        "i1",
        "Control family audit",
        "Synthetic fixture, no scientific claim.",
        "2026-09-02T12:00:00Z",
    )
    audit = audit_research_state(
        inquiry=inquiry,
        claims=[],
        hypotheses=[],
        evidence=[],
        datasets=[],
        protocols=[reference_only],
        runs=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert "PROTECTED_PROTOCOL_WITHOUT_POSITIVE_CONTROL" in codes
    assert "PROTECTED_PROTOCOL_WITHOUT_FALSIFYING_CONTROL" in codes

    balanced = replace(
        reference_only,
        controls=["Known-effect sample", "Blank sample"],
        control_definitions=[
            ControlDefinition(
                "positive-1", "Known-effect sample", "positive",
                "Show the pipeline detects a known effect.",
                "Known effect is detected.", "integrity",
            ),
            ControlDefinition(
                "negative-1", "Blank sample", "negative",
                "Reveal contamination or false detection.",
                "No target signal is detected.", "integrity",
            ),
        ],
    )
    balanced_audit = audit_research_state(
        inquiry=inquiry,
        claims=[],
        hypotheses=[],
        evidence=[],
        datasets=[],
        protocols=[balanced],
        runs=[],
    )
    balanced_codes = {finding.code for finding in balanced_audit.findings}
    assert "PROTECTED_PROTOCOL_WITHOUT_POSITIVE_CONTROL" not in balanced_codes
    assert "PROTECTED_PROTOCOL_WITHOUT_FALSIFYING_CONTROL" not in balanced_codes


def test_rigor_flags_legacy_protected_controls_without_structured_definitions():
    from test_ethics_gate import _human_protocol

    legacy = replace(
        _human_protocol(human_subjects=False),
        control_definitions=[],
        status=ProtocolStatus.FROZEN,
    )
    inquiry = Inquiry(
        "i1",
        "Legacy control audit",
        "Synthetic fixture, no scientific claim.",
        "2026-09-02T12:00:00Z",
    )
    audit = audit_research_state(
        inquiry=inquiry,
        claims=[],
        hypotheses=[],
        evidence=[],
        datasets=[],
        protocols=[legacy],
        runs=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert "PROTECTED_PROTOCOL_CONTROLS_UNSTRUCTURED" in codes
    assert "PROTECTED_PROTOCOL_WITHOUT_POSITIVE_CONTROL" not in codes
    assert "PROTECTED_PROTOCOL_WITHOUT_FALSIFYING_CONTROL" not in codes


def test_typed_measurement_contract_rejects_omitted_control_time(
    tmp_path: Path,
) -> None:
    service, hypothesis, _ = _prepared_run(tmp_path)
    control = "The negative dissipator must violate complete positivity."

    def measurement(
        measurement_id: str,
        role: MeasurementRole,
        target: str,
        point: str,
    ) -> MeasurementDefinition:
        return MeasurementDefinition(
            measurement_id=measurement_id,
            role=role,
            registered_target=target,
            observable="minimum Choi eigenvalue",
            input_condition="fixed finite CQ generator",
            parameter_values={"t": "0.01 dimensionless"},
            evaluation_point=point,
            convention="column-vectorization Choi convention",
            aggregation="minimum over Hermitian eigenspectrum",
            tolerance="absolute error <= 1e-6",
            expected_behavior="negative for the malformed generator",
        )

    common = dict(
        title="Typed CQ control contract",
        analysis_mode=AnalysisMode.REPLICATION,
        hypotheses_tested=[hypothesis.hypothesis_id],
        primary_outcome="Main channel structural verdict",
        protocol_kind=ProtocolKind.COMPUTATIONAL,
        methodology="Evaluate the main channel and fixed malformed control.",
        quality_requirements=["contract-check"],
        controls=[control],
        expected_outputs=["Measurement packet"],
        success_conditions=["The fixed measurement contract is reproduced."],
        environment_requirements=["Pinned numerical environment"],
        sample_size_or_stopping_rule="Exactly one fixed evaluation.",
        failure_conditions=["Any registered measurement is omitted."],
        safety_constraints=["No physical intervention."],
        analysis_code_hash="8" * 64,
    )
    untyped = service.create_protocol(
        CreateProtocol(experiment_id="typed-cq-legacy", **common)
    )
    service.freeze_protocol(untyped.protocol_id)
    audit = service.audit_rigor()
    assert any(
        item.code == "PROTECTED_COMPUTATIONAL_MEASUREMENTS_UNTYPED"
        and item.entity_id == untyped.protocol_id
        for item in audit.findings
    )

    incomplete = service.create_protocol(
        CreateProtocol(
            experiment_id="typed-cq-incomplete",
            measurement_definitions=[
                measurement(
                    "main",
                    MeasurementRole.PRIMARY,
                    common["primary_outcome"],
                    "t=0.05",
                ),
                measurement("negative", MeasurementRole.CONTROL, control, ""),
            ],
            **common,
        )
    )
    with pytest.raises(ValidationError, match="evaluation_point"):
        service.freeze_protocol(incomplete.protocol_id)

    misaligned = service.create_protocol(
        CreateProtocol(
            experiment_id="typed-cq-misaligned",
            measurement_definitions=[
                measurement(
                    "main",
                    MeasurementRole.PRIMARY,
                    common["primary_outcome"],
                    "t=0.05",
                ),
                measurement(
                    "negative",
                    MeasurementRole.CONTROL,
                    "An unregistered control",
                    "t=0.01",
                ),
            ],
            **common,
        )
    )
    with pytest.raises(ValidationError, match="exactly one measurement"):
        service.freeze_protocol(misaligned.protocol_id)

    complete = service.create_protocol(
        CreateProtocol(
            experiment_id="typed-cq-complete",
            measurement_definitions=[
                measurement(
                    "main",
                    MeasurementRole.PRIMARY,
                    common["primary_outcome"],
                    "t=0.05",
                ),
                measurement("negative", MeasurementRole.CONTROL, control, "t=0.01"),
            ],
            **common,
        )
    )
    frozen = service.freeze_protocol(complete.protocol_id)
    assert frozen.measurement_definitions[1].evaluation_point == "t=0.01"
    reloaded = service.get_protocol(frozen.protocol_id)
    assert reloaded.measurement_definitions[0].role is MeasurementRole.PRIMARY


def test_advanced_tags_cannot_overstate_a_formal_self_check(tmp_path: Path) -> None:
    service, hypothesis, run = _prepared_run(tmp_path)
    with pytest.raises(ValidationError, match="replication-mode run"):
        service.record_evidence(
            _classified_evidence(
                hypothesis.hypothesis_id,
                run.run_id,
                validation_tags=[ValidationTag.INDEPENDENT_REPLICATION],
            )
        )
    with pytest.raises(ValidationError, match="observational or experimental"):
        service.record_evidence(
            _classified_evidence(
                hypothesis.hypothesis_id,
                run.run_id,
                validation_tags=[ValidationTag.EMPIRICAL_TEST],
            )
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("dimension", " executor", "independence_dimensions item"),
        ("allowed_input", " contract.md", "allowed_inputs\\[0\\].locator"),
        ("disclosure", " contamination note ", "contamination_disclosures item"),
        ("attestation", " attestation.json", "attestation_artifact"),
        ("duplicate_dimension", None, "independence_dimensions must not contain duplicates"),
        ("duplicate_allowed_input", None, "allowed_inputs must not contain duplicates"),
        ("duplicate_disclosure", None, "contamination_disclosures must not contain duplicates"),
    ],
)
def test_independent_replication_requires_canonical_clean_room_metadata(
    tmp_path: Path, field, value, message
) -> None:
    _, hypothesis, original = _prepared_run(tmp_path)
    independence = {
        "design": "clean_room",
        "independence_dimensions": ["executor", "implementation"],
        "prior_implementation_accessed": False,
        "allowed_inputs": [{"locator": "contract.md", "sha256": "2" * 64}],
        "contamination_disclosures": ["none declared"],
        "attestation_artifact": "attestation.json",
    }
    if field == "dimension":
        independence["independence_dimensions"] = [value, "implementation"]
    elif field == "allowed_input":
        independence["allowed_inputs"] = [{"locator": value, "sha256": "2" * 64}]
    elif field == "disclosure":
        independence["contamination_disclosures"] = [value]
    elif field == "attestation":
        independence["attestation_artifact"] = value
    elif field == "duplicate_dimension":
        independence["independence_dimensions"] = [
            "executor", "implementation", "executor"
        ]
    elif field == "duplicate_allowed_input":
        independence["allowed_inputs"] = [
            {"locator": "contract.md", "sha256": "2" * 64},
            {"locator": "contract.md", "sha256": "2" * 64},
        ]
    elif field == "duplicate_disclosure":
        independence["contamination_disclosures"] = [
            "none declared", "none declared"
        ]
    replication = ResearchRun(
        run_id="replication-run",
        protocol_id="replication-protocol",
        protocol_hash="p" * 64,
        analysis_mode=AnalysisMode.REPLICATION,
        started_at="2026-09-02T12:03:00Z",
        completed_at="2026-09-02T12:04:00Z",
        executed_by="replicator",
        analysis_code_hash="d" * 64,
        environment_hash="e" * 64,
        output_artifacts=[DatasetArtifact(
            "attestation.json",
            "a" * 64,
            metadata={"artifact_role": "independence_attestation"},
        )],
        quality_gates=[
            QualityGateResult(
                "replication-check",
                QualityGateStatus.PASSED,
                "Replication check passed.",
                details={"evidence_sha256": "a" * 64},
            )
        ],
        scientific_evidence_eligible=True,
        metadata={
            "replicates_run_id": original.run_id,
            "replication_independence": independence,
            "artifact_integrity": {
                "status": "passed",
                "all_artifacts_match": True,
                "attestation_schema_matches_commitment": True,
                "attestation_schema_valid": True,
                "attestation_consistent": True,
            },
        },
    )

    with pytest.raises(ValidationError, match=message):
        validate_validation_tag_context(
            tags=[ValidationTag.INDEPENDENT_REPLICATION],
            hypothesis=hypothesis,
            exploratory=False,
            protocol=None,
            run=replication,
            datasets=[],
            controls_passed=[],
            replicated_run=original,
        )


def test_audit_and_synthesis_publish_a_conservative_ceiling(tmp_path: Path) -> None:
    service, hypothesis, run = _prepared_run(tmp_path)
    service.record_evidence(_classified_evidence(hypothesis.hypothesis_id, run.run_id))

    audit = service.audit_rigor(fail_on="error")
    assert audit.structurally_valid is True
    assert audit.conclusion_ceiling == "controlled but internally generated result"
    assert audit.capabilities["internal_consistency"] is True
    assert audit.capabilities["controlled_benchmark"] is True
    assert audit.capabilities["independent_replication"] is False
    assert any(
        finding.code == "CAPABILITY_INDEPENDENT_REPLICATION_ABSENT"
        for finding in audit.findings
    )
    with pytest.raises(ValidationError, match="rigor audit failed"):
        service.audit_rigor(fail_on="warning")

    synthesis = service.build_synthesis()["content"]
    assert "Epistemic rigor audit" in synthesis
    assert "controlled but internally generated result" in synthesis
    assert "independent_replication: absent" in synthesis


def test_audit_warns_when_empirical_preprocessing_conformance_is_unreported(
    tmp_path: Path,
) -> None:
    service, hypothesis, run = _prepared_run(tmp_path)
    repository = service.repository
    inquiry_id = repository.resolve_inquiry_id(None)
    protocol = replace(
        service.get_protocol(run.protocol_id),
        protocol_kind=ProtocolKind.OBSERVATIONAL,
        preprocessing_pipeline="Registered fixture preprocessing pipeline.",
        measurement_definitions=[
            MeasurementDefinition(
                measurement_id="primary-measurement",
                role=MeasurementRole.PRIMARY,
                registered_target="Checker acceptance",
                observable="Synthetic fixture outcome",
                input_condition="All eligible fixture rows",
                parameter_values={"scale": "fixture units"},
                evaluation_point="registered endpoint",
                convention="higher is larger",
                aggregation="mean by group",
                tolerance="exact fixture parsing",
                expected_behavior="Reported regardless of direction",
                data_column="outcome",
                temporal_role="not_applicable",
                scale_type="interval",
                unit="fixture units",
                valid_min=0.0,
                valid_max=100.0,
                missing_value_codes=["<blank>"],
            )
        ],
    )

    audit = audit_research_state(
        inquiry=repository.load_inquiry(inquiry_id),
        claims=repository.load_claims(inquiry_id),
        hypotheses=[hypothesis],
        evidence=repository.list_evidence(inquiry_id),
        datasets=repository.list_datasets(inquiry_id),
        protocols=[protocol],
        runs=[run],
    )

    assert any(
        finding.code == "PROTECTED_EMPIRICAL_PREPROCESSING_CONFORMANCE_UNASSESSED"
        and finding.entity_id == protocol.protocol_id
        for finding in audit.findings
    )


def test_retrospectively_amended_evidence_cannot_raise_prospective_ceiling(tmp_path: Path) -> None:
    service, hypothesis, predecessor_run = _prepared_run(tmp_path)
    predecessor = service.get_protocol(predecessor_run.protocol_id)
    values = {field.name: getattr(predecessor, field.name) for field in fields(CreateProtocol)}
    amendment = service.amend_protocol(
        predecessor.protocol_id, CreateProtocol(**values), "Changed after inspecting output",
        "after_analysis", "full_data_seen",
    )
    frozen = service.freeze_protocol(amendment.protocol_id)
    amended_output = tmp_path / "amended.json"
    amended_output.write_text('{"checker":"passed"}\n', encoding="utf-8")
    amended_sha256 = hashlib.sha256(amended_output.read_bytes()).hexdigest()
    run = service.record_run(RecordRun(
        protocol_id=frozen.protocol_id, started_at="2026-09-02T12:03:00Z",
        completed_at="2026-09-02T12:04:00Z", analysis_code_hash="a" * 64,
        environment_hash="b" * 64, output_artifacts=[DatasetArtifact(
            "amended.json", amended_sha256, amended_output.stat().st_size,
            "application/json",
        )],
        artifact_root=str(tmp_path),
        quality_gates=[QualityGateResult(gate_id="checker", status=QualityGateStatus.PASSED,
                                         summary="Amended checker passed.",
                                         details={"evidence_sha256": amended_sha256})],
        metadata={"protocol_deviation_disclosure": {
            "status": "no_deviations_declared", "deviations": [],
        }},
    ))
    service.record_evidence(_classified_evidence(hypothesis.hypothesis_id, run.run_id))
    audit = service.audit_rigor()
    assert audit.capabilities["controlled_benchmark"] is True
    assert audit.conclusion_ceiling == "retrospectively amended evidence only; prospective confirmation required"
    assert any(item.code == "EVIDENCE_FROM_RETROSPECTIVE_OR_EXPOSED_AMENDMENT"
               for item in audit.findings)


def test_independent_replication_requires_clean_room_attestation(
    tmp_path: Path,
) -> None:
    author, hypothesis, original = _prepared_run(tmp_path)
    draft = author.create_protocol(
        CreateProtocol(
            experiment_id="rigor-check-replication",
            title="Independent invariant replication",
            analysis_mode=AnalysisMode.REPLICATION,
            hypotheses_tested=[hypothesis.hypothesis_id],
            primary_outcome="Independent checker acceptance",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Reimplement the invariant check with a distinct checker.",
            quality_requirements=["replication-check"],
            controls=["The independent invalid candidate must fail."],
            expected_outputs=["Independent checker transcript"],
            success_conditions=["Independent reproduction passes."],
            environment_requirements=["Distinct pinned checker"],
            sample_size_or_stopping_rule="One original result and one replication.",
            failure_conditions=["The reproduction or its control fails."],
            safety_constraints=["No physical intervention."],
            analysis_code_hash="d" * 64,
        )
    )
    protocol = author.freeze_protocol(draft.protocol_id)
    replicator = _service(tmp_path, actor="replicator")
    incomplete_output = tmp_path / "replication.json"
    incomplete_output.write_text('{"reproduced":true}\n', encoding="utf-8")
    incomplete_sha256 = hashlib.sha256(incomplete_output.read_bytes()).hexdigest()
    incomplete_replication = replicator.record_run(
        RecordRun(
            protocol_id=protocol.protocol_id,
            started_at="2026-09-02T12:03:00Z",
            completed_at="2026-09-02T12:04:00Z",
            analysis_code_hash="d" * 64,
            environment_hash="e" * 64,
            output_artifacts=[DatasetArtifact(
                "replication.json", incomplete_sha256,
                incomplete_output.stat().st_size, "application/json",
            )],
            artifact_root=str(tmp_path),
            quality_gates=[
                QualityGateResult(
                    gate_id="replication-check",
                    status=QualityGateStatus.PASSED,
                    summary="Independent implementation reproduced the result.",
                    details={"evidence_sha256": incomplete_sha256},
                )
            ],
            metadata={
                "replicates_run_id": original.run_id,
                "protocol_deviation_disclosure": {
                    "status": "no_deviations_declared", "deviations": [],
                },
            },
        )
    )
    with pytest.raises(
        ValidationError, match="replication_independence"
    ):
        replicator.record_evidence(
            _classified_evidence(
                hypothesis.hypothesis_id,
                incomplete_replication.run_id,
                validation_tags=[ValidationTag.INDEPENDENT_REPLICATION],
            )
        )

    attestation_locator = "independence-attestation.json"
    artifact_root = tmp_path / "replication-artifacts"
    artifact_root.mkdir()
    result_path = artifact_root / "replication-clean-room.json"
    result_path.write_text('{"reproduced":true}\n', encoding="utf-8")
    attestation = {
        "target_run_id": original.run_id,
        "executor_identity": "replicator",
        "design": "clean_room",
        "independence_dimensions": ["executor", "implementation"],
        "prior_implementation_accessed": False,
        "allowed_input_manifest": {
            "locator": "contract.md",
            "sha256": "2" * 64,
        },
        "analysis_code_hash": "d" * 64,
        "contamination_disclosures": [],
    }
    attestation_path = artifact_root / attestation_locator
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
    attestation_schema = tmp_path / "attestation.schema.json"
    attestation_schema.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": list(attestation),
                "properties": {
                    "target_run_id": {"const": original.run_id},
                    "executor_identity": {"const": "replicator"},
                    "design": {"const": "clean_room"},
                    "independence_dimensions": {
                        "type": "array",
                        "minItems": 2,
                        "uniqueItems": True,
                        "items": {"type": "string"},
                    },
                    "prior_implementation_accessed": {"const": False},
                    "allowed_input_manifest": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["locator", "sha256"],
                        "properties": {
                            "locator": {"type": "string", "minLength": 1},
                            "sha256": {
                                "type": "string",
                                "pattern": "^[0-9a-f]{64}$",
                            },
                        },
                    },
                    "analysis_code_hash": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "contamination_disclosures": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    schema_hash = hashlib.sha256(attestation_schema.read_bytes()).hexdigest()
    replication = replicator.record_run(
        RecordRun(
            run_id="run-independent-clean-room",
            protocol_id=protocol.protocol_id,
            started_at="2026-09-02T12:05:00Z",
            completed_at="2026-09-02T12:06:00Z",
            analysis_code_hash="d" * 64,
            environment_hash="e" * 64,
            output_artifacts=[
                DatasetArtifact(
                    "replication-clean-room.json",
                    hashlib.sha256(result_path.read_bytes()).hexdigest(),
                    size_bytes=result_path.stat().st_size,
                ),
                DatasetArtifact(
                    attestation_locator,
                    hashlib.sha256(attestation_path.read_bytes()).hexdigest(),
                    size_bytes=attestation_path.stat().st_size,
                    metadata={"artifact_role": "independence_attestation"},
                ),
            ],
            quality_gates=[
                QualityGateResult(
                    gate_id="replication-check",
                    status=QualityGateStatus.PASSED,
                    summary="Clean-room implementation reproduced the result.",
                    details={"evidence_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()},
                )
            ],
            metadata={
                "replicates_run_id": original.run_id,
                "protocol_deviation_disclosure": {
                    "status": "no_deviations_declared", "deviations": [],
                },
                "replication_independence": {
                    "design": "clean_room",
                    "independence_dimensions": ["executor", "implementation"],
                    "prior_implementation_accessed": False,
                    "allowed_inputs": [
                        {"locator": "contract.md", "sha256": "2" * 64}
                    ],
                    "contamination_disclosures": [],
                    "attestation_artifact": attestation_locator,
                },
            },
            artifact_root=str(artifact_root),
            attestation_schema_path=str(attestation_schema),
            expected_attestation_schema_sha256=schema_hash,
        )
    )
    assert replication.metadata["artifact_integrity"]["status"] == "passed"
    evidence = replicator.record_evidence(
        _classified_evidence(
            hypothesis.hypothesis_id,
            replication.run_id,
            summary="A distinct executor and code artifact reproduced the result.",
            validation_tags=[ValidationTag.INDEPENDENT_REPLICATION],
        )
    )
    assert evidence.validation_tags == [ValidationTag.INDEPENDENT_REPLICATION]
