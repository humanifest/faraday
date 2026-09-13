"""Synthetic fixtures for the workflow-only action audit prerequisite."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.audit_prerequisite import (
    AUDIT_PREREQUISITE_CONCLUSION_CEILING,
)
from research_machine.application.commands import (
    CreateInquiry,
    ProposeHypothesis,
    RecommendActionPortfolio,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import IntegrityError, ValidationError
from research_machine.domain.models import (
    ActionAuditClass,
    ActionCandidate,
    ActionLane,
    AuditPrerequisiteArtifact,
    AuditPrerequisiteContract,
    AuditPrerequisiteSubject,
    HypothesisDiscriminationTarget,
)


def _write(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _audit_payload(subject_sha256: str, verdict: str = "favorable") -> dict[str, object]:
    return {
        "audit_id": "audit-candidate-v1",
        "artifact_role": "adversarial_candidate_audit",
        "audited_subject_role": "candidate",
        "audited_subject_id": "candidate-v1",
        "audited_subject_sha256": subject_sha256,
        "verdict": verdict,
        "scope": "Exact candidate bytes and the bounded proposed next action.",
        "auditor_identity": "declared-auditor-17",
        "audited_at": "2026-09-12T14:00:00Z",
        "limitations": [
            "The record does not authenticate identity, independence, or substantive judgment."
        ],
    }


def _contract(
    root: Path,
    *,
    verdict: str = "favorable",
    materialize_subject: bool = True,
    materialize_audit: bool = True,
    audit_payload: dict[str, object] | None = None,
    contract_audit_payload: dict[str, object] | None = None,
) -> AuditPrerequisiteContract:
    subject_bytes = b"candidate v1 exact scientific content\n"
    subject_sha256 = hashlib.sha256(subject_bytes).hexdigest()
    if materialize_subject:
        _write(root / "candidate.md", subject_bytes)
    observed_payload = audit_payload or _audit_payload(subject_sha256, verdict)
    audit_bytes = (
        json.dumps(observed_payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    audit_sha256 = hashlib.sha256(audit_bytes).hexdigest()
    if materialize_audit:
        _write(root / "candidate-audit.json", audit_bytes)
    declared = contract_audit_payload or _audit_payload(subject_sha256, verdict)
    return AuditPrerequisiteContract(
        contract_version=1,
        action_class=ActionAuditClass.CANDIDATE_ADVANCING,
        subjects=[
            AuditPrerequisiteSubject(
                "candidate", "candidate-v1", "candidate.md", subject_sha256
            )
        ],
        required_audits=[
            AuditPrerequisiteArtifact(
                artifact_locator="candidate-audit.json",
                artifact_sha256=audit_sha256,
                **declared,
            )
        ],
        evaluator_exposure_statement="",
        limitations=[
            "This contract governs workflow selection, not scientific acceptance."
        ],
        conclusion_ceiling=AUDIT_PREREQUISITE_CONCLUSION_CEILING,
    )


def _exposed_contract() -> AuditPrerequisiteContract:
    return AuditPrerequisiteContract(
        contract_version=1,
        action_class=ActionAuditClass.EXPOSED_EVALUATOR_DEVELOPMENT,
        subjects=[],
        required_audits=[],
        evaluator_exposure_statement=(
            "The evaluator is developed in the open and cannot advance a candidate."
        ),
        limitations=["Successful evaluator execution is software behavior only."],
        conclusion_ceiling=AUDIT_PREREQUISITE_CONCLUSION_CEILING,
    )


def _candidate(
    action_id: str,
    contract: AuditPrerequisiteContract | None,
    *,
    score: float,
) -> ActionCandidate:
    return ActionCandidate(
        action_id=action_id,
        title=action_id.replace("-", " ").title(),
        distinguishes_hypotheses=[],
        information_targets=[f"workflow:{action_id}"],
        expected_discrimination=0.0,
        uncertainty_reduction=score,
        cost=0.1,
        duration=0.1,
        burden=0.1,
        safety_risk=0.0,
        ambiguity_risk=0.1,
        rationale=f"Reduce bounded workflow uncertainty for {action_id}.",
        prerequisite_evidence_refs=[f"prerequisite:{action_id}"],
        safety_review_refs=[f"safety:{action_id}"],
        lane_id="theory",
        audit_prerequisite_contract=contract,
    )


def _service(workspace: Path, artifact_root: Path | None) -> ResearchService:
    service = ResearchService(
        FileSystemRepository(workspace),
        actor="audit-prerequisite-test",
        clock=lambda: "2026-09-12T15:00:00Z",
        token=lambda: "auditprereq01",
        audit_artifact_root=artifact_root,
    )
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            "Audit prerequisite fixture",
            "Can action selection fail closed at the audit boundary?",
            "audit-prerequisite-fixture",
        )
    )
    return service


def _portfolio(*candidates: ActionCandidate) -> RecommendActionPortfolio:
    return RecommendActionPortfolio(
        lanes=[ActionLane("theory", "Theory")],
        candidates=list(candidates),
    )


def test_favorable_exact_audit_makes_candidate_workflow_selectable(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    candidate = _candidate("advance-v1", _contract(artifacts), score=0.9)

    recommendation = service.recommend_action_portfolio(_portfolio(candidate))

    assert recommendation.selected_action_id == "advance-v1"
    assert recommendation.score_contract_version == 3
    receipt = recommendation.candidates[0].audit_prerequisite_receipt
    assert receipt["status"] == "passed"
    assert receipt["workflow_eligible"] is True
    assert receipt["candidate_advancement_eligible"] is True
    assert receipt["scientific_validity_established"] is False
    assert receipt["auditor_identity_authenticated"] is False
    assert receipt["scientific_evidence_eligible"] is False
    assert receipt["replication_authority_established"] is False
    assert len(receipt["receipt_sha256"]) == 64
    assert service.list_recommendations() == [recommendation]
    synthesis = service.build_synthesis()["content"]
    assert "audit action_class=candidate_advancing" in synthesis
    assert "role=adversarial_candidate_audit" in synthesis
    assert "subject=candidate:candidate-v1@" in synthesis
    assert "verdict=favorable" in synthesis
    assert "auditor=declared-auditor-17" in synthesis
    assert "audited_at=2026-09-12T14:00:00Z" in synthesis
    assert AUDIT_PREREQUISITE_CONCLUSION_CEILING in synthesis
    rigor = service.audit_rigor()
    assert any(
        finding.code == "ACTION_AUDIT_PREREQUISITE_WORKFLOW_ELIGIBLE"
        for finding in rigor.findings
    )

    context = service.collaborator_context(purpose="Review bounded action provenance.")
    context_receipt = context["recommendations"][0]["candidates"][0][
        "audit_prerequisite_receipt"
    ]
    assert context_receipt["artifact_root"] == "[redacted: retained in canonical store]"
    assert any(
        "replication authority" in constraint
        for constraint in context["scientific_constraints"]
    )
    assert candidate.audit_prerequisite_contract is not None
    contract_audit_sha = candidate.audit_prerequisite_contract.required_audits[
        0
    ].artifact_sha256
    assert (
        context_receipt["audit_observations"][0]["artifact_sha256"]
        == contract_audit_sha
    )
    assert len(contract_audit_sha) == 64


@pytest.mark.parametrize("verdict", ["pending", "adverse"])
def test_pending_or_adverse_audit_is_retained_but_not_selected(
    tmp_path: Path, verdict: str
) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    blocked = _candidate(
        "candidate-blocked", _contract(artifacts, verdict=verdict), score=1.0
    )
    fallback = _candidate("evaluator-work", _exposed_contract(), score=0.3)

    recommendation = service.recommend_action_portfolio(
        _portfolio(blocked, fallback)
    )

    assert recommendation.selected_action_id == "evaluator-work"
    retained = next(
        item for item in recommendation.candidates if item.action_id == "candidate-blocked"
    )
    assert retained.audit_prerequisite_receipt["status"] == "not_eligible"
    assert retained.audit_prerequisite_receipt["candidate_advancement_eligible"] is False
    selected = next(
        item for item in recommendation.candidates if item.action_id == "evaluator-work"
    )
    assert selected.audit_prerequisite_receipt["replication_authority_established"] is False
    rigor = service.audit_rigor()
    assert any(
        finding.code == "ACTION_AUDIT_PREREQUISITE_NOT_ELIGIBLE"
        and finding.entity_id == "candidate-blocked"
        for finding in rigor.findings
    )


@pytest.mark.parametrize(
    ("materialize_subject", "materialize_audit", "message"),
    [
        (False, True, "escapes or is missing"),
        (True, False, "escapes or is missing"),
    ],
)
def test_missing_required_bytes_fail_before_recommendation_is_recorded(
    tmp_path: Path,
    materialize_subject: bool,
    materialize_audit: bool,
    message: str,
) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    candidate = _candidate(
        "advance-v1",
        _contract(
            artifacts,
            materialize_subject=materialize_subject,
            materialize_audit=materialize_audit,
        ),
        score=0.9,
    )

    with pytest.raises(IntegrityError, match=message):
        service.recommend_action_portfolio(_portfolio(candidate))
    assert service.repository.list_recommendations("audit-prerequisite-fixture") == []


def test_candidate_advancement_without_artifact_root_fails_closed(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", None)
    candidate = _candidate("advance-v1", _contract(artifacts), score=0.9)

    with pytest.raises(ValidationError, match="require audit_artifact_root"):
        service.recommend_action_portfolio(_portfolio(candidate))


@pytest.mark.parametrize(
    ("target", "content"),
    [
        ("candidate.md", b"changed candidate bytes\n"),
        ("candidate-audit.json", b"{}\n"),
    ],
)
def test_hash_mismatched_subject_or_audit_bytes_fail_closed(
    tmp_path: Path, target: str, content: bytes
) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    contract = _contract(artifacts)
    (artifacts / target).write_bytes(content)

    with pytest.raises(IntegrityError, match="hash mismatch"):
        service.recommend_action_portfolio(
            _portfolio(_candidate("advance-v1", contract, score=0.9))
        )


@pytest.mark.parametrize("target", ["candidate.md", "candidate-audit.json"])
def test_subject_or_audit_symlinks_fail_closed(tmp_path: Path, target: str) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    contract = _contract(artifacts)
    path = artifacts / target
    copied = artifacts / f"copy-{target}"
    copied.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(copied.name)

    with pytest.raises(IntegrityError, match="must not traverse symlinks"):
        service.recommend_action_portfolio(
            _portfolio(_candidate("advance-v1", contract, score=0.9))
        )


@pytest.mark.parametrize(
    ("component", "locator"),
    [("subject", "../outside.md"), ("audit", "/tmp/outside-audit.json")],
)
def test_subject_or_audit_path_escape_is_rejected(
    tmp_path: Path, component: str, locator: str
) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    contract = _contract(artifacts)
    if component == "subject":
        subject = replace(contract.subjects[0], artifact_locator=locator)
        contract = replace(contract, subjects=[subject])
    else:
        audit = replace(contract.required_audits[0], artifact_locator=locator)
        contract = replace(contract, required_audits=[audit])

    with pytest.raises(ValidationError, match="safe relative path"):
        service.recommend_action_portfolio(
            _portfolio(_candidate("advance-v1", contract, score=0.9))
        )


def test_strict_audit_json_rejects_duplicate_keys_even_with_matching_hash(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    contract = _contract(artifacts)
    duplicate_bytes = b'{"audit_id":"first","audit_id":"second"}\n'
    (artifacts / "candidate-audit.json").write_bytes(duplicate_bytes)
    audit = replace(
        contract.required_audits[0],
        artifact_sha256=hashlib.sha256(duplicate_bytes).hexdigest(),
    )
    contract = replace(contract, required_audits=[audit])

    with pytest.raises(IntegrityError, match="not strict JSON"):
        service.recommend_action_portfolio(
            _portfolio(_candidate("advance-v1", contract, score=0.9))
        )


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("audit_id", "different-audit-id"),
        ("artifact_role", "different_audit_role"),
        ("audited_subject_role", "implementation"),
        ("audited_subject_id", "candidate-v2"),
        ("audited_subject_sha256", "f" * 64),
        ("verdict", "pending"),
        ("scope", "A different scope."),
        ("auditor_identity", "different-declared-auditor"),
        ("audited_at", "2026-09-12T14:01:00Z"),
        ("limitations", ["Different limitations."]),
    ],
)
def test_hash_matching_audit_with_contract_metadata_drift_fails_closed(
    tmp_path: Path, field: str, changed: object
) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    subject_sha = hashlib.sha256(b"candidate v1 exact scientific content\n").hexdigest()
    observed = _audit_payload(subject_sha)
    observed[field] = changed
    contract = _contract(
        artifacts,
        audit_payload=observed,
        contract_audit_payload=_audit_payload(subject_sha),
    )

    with pytest.raises(IntegrityError, match="content does not match"):
        service.recommend_action_portfolio(
            _portfolio(_candidate("advance-v1", contract, score=0.9))
        )


def test_audit_scoped_to_different_declared_subject_hash_is_rejected(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    contract = _contract(artifacts)
    audit = replace(contract.required_audits[0], audited_subject_sha256="f" * 64)
    drifted = replace(contract, required_audits=[audit])

    with pytest.raises(ValidationError, match="different candidate or implementation bytes"):
        service.recommend_action_portfolio(
            _portfolio(_candidate("advance-v1", drifted, score=0.9))
        )


def test_exposed_evaluator_development_cannot_claim_hypothesis_discrimination(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path / "workspace", None)
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="The synthetic target differs from its alternative.",
            observable_prediction="The bounded target outcome differs.",
            null_model="No bounded target difference occurs.",
            falsification_conditions=["The bounded target difference is absent."],
        )
    )
    service.activate_hypothesis(hypothesis.hypothesis_id)
    candidate = replace(
        _candidate("evaluator-work", _exposed_contract(), score=0.5),
        distinguishes_hypotheses=[hypothesis.hypothesis_id],
        hypothesis_discrimination_targets=[
            HypothesisDiscriminationTarget(
                hypothesis_id=hypothesis.hypothesis_id,
                discriminating_observation="The target differs from the null.",
                expected_if_hypothesis="The target difference occurs.",
                expected_if_alternative="No target difference occurs.",
                would_weaken_if="The target difference is absent.",
                competing_model_ref="No bounded target difference occurs.",
            )
        ],
    )
    with pytest.raises(ValidationError, match="cannot claim hypothesis discrimination"):
        service.recommend_action_portfolio(_portfolio(candidate))


def test_exposed_evaluator_exemption_cannot_claim_candidate_coverage(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    advancing = _contract(artifacts)
    disguised = replace(_exposed_contract(), subjects=advancing.subjects)

    with pytest.raises(ValidationError, match="must not claim candidate audit coverage"):
        service.recommend_action_portfolio(
            _portfolio(_candidate("disguised-candidate", disguised, score=0.5))
        )


def test_missing_contract_and_caller_supplied_receipt_are_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path / "workspace", None)
    with pytest.raises(ValidationError, match="requires an audit_prerequisite_contract"):
        service.recommend_action_portfolio(
            _portfolio(_candidate("unclassified", None, score=0.5))
        )
    smuggled = replace(
        _candidate("evaluator-work", _exposed_contract(), score=0.5),
        audit_prerequisite_receipt={"workflow_eligible": True},
    )
    with pytest.raises(ValidationError, match="service-generated"):
        service.recommend_action_portfolio(_portfolio(smuggled))


def test_current_recommendation_replay_rehashes_retained_audit_bytes(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    service = _service(tmp_path / "workspace", artifacts)
    candidate = _candidate("advance-v1", _contract(artifacts), score=0.9)
    service.recommend_action_portfolio(_portfolio(candidate))

    (artifacts / "candidate-audit.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(IntegrityError, match="hash mismatch"):
        service.list_recommendations()


def test_current_record_cannot_be_self_recommitted_around_the_ledger(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path / "workspace", None)
    service.recommend_action_portfolio(
        _portfolio(_candidate("evaluator-work", _exposed_contract(), score=0.5))
    )
    path = next((tmp_path / "workspace").rglob("recommendations/*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed_rationale = "Reduce a different bounded uncertainty."
    payload["candidates"][0]["rationale"] = changed_rationale
    payload["rationale"] = f"theory: {changed_rationale}"
    unsigned = dict(payload)
    unsigned.pop("recommendation_payload_sha256")
    payload["recommendation_payload_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    with pytest.raises(IntegrityError, match="differs from its selection event"):
        service.list_recommendations()
