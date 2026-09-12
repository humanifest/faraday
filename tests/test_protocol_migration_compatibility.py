"""Backward-compatible loading for protocols sealed by historical Faraday runtimes."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.protocol_integrity import protocol_commitment
from research_machine.application.policies import require_pending_review_rationale
from research_machine.application.service import ResearchService
from research_machine.domain.errors import IntegrityError, ValidationError
from research_machine.domain.models import (
    ActionCandidate,
    ActionRecommendation,
    ActionScore,
    AnalysisMode,
    EvidenceDirection,
    EvidenceRecord,
    ExperimentProtocol,
    ProtocolStatus,
    RuntimePreflightRequirement,
    SelectionWeights,
)


def _protocol() -> ExperimentProtocol:
    return ExperimentProtocol(
        protocol_id="prt-legacy-v1",
        protocol_family_id="prt-legacy",
        version=1,
        experiment_id="legacy-load",
        title="Historical protocol compatibility fixture",
        analysis_mode=AnalysisMode.CONFIRMATORY,
        hypotheses_tested=["hyp-legacy"],
        primary_outcome="Registered outcome",
        created_at="2026-09-09T00:00:00Z",
        created_by="historical-runtime",
    )


def test_absent_compatibility_fields_do_not_change_current_serialization() -> None:
    payload = _protocol().to_dict()

    for field_name in (
        "runtime_preflight_requirement",
        "notebook_freeze_input_bundle_sha256",
        "abandoned_at",
        "abandoned_by",
        "abandonment_reason",
    ):
        assert field_name not in payload


def test_historical_runtime_bindings_round_trip_and_remain_committed() -> None:
    requirement = RuntimePreflightRequirement(
        receipt_sha256="a" * 64,
        probe_id="research-machine-runtime-preflight-v1",
        interpreter_path="/pinned/python",
        kernel_name="python3",
        working_directory="/pinned/workspace",
    )
    historical = replace(
        _protocol(),
        status=ProtocolStatus.FROZEN,
        runtime_preflight_requirement=requirement,
        notebook_freeze_input_bundle_sha256="b" * 64,
    )
    sealed = replace(historical, protocol_hash=protocol_commitment(historical))

    restored = ExperimentProtocol.from_dict(sealed.to_dict())

    assert restored == sealed
    assert protocol_commitment(restored) == sealed.protocol_hash
    assert protocol_commitment(
        replace(
            restored,
            runtime_preflight_requirement=replace(
                requirement, working_directory="/different/workspace"
            ),
        )
    ) != sealed.protocol_hash
    assert protocol_commitment(
        replace(restored, notebook_freeze_input_bundle_sha256="c" * 64)
    ) != sealed.protocol_hash


def test_abandonment_metadata_is_audit_visible_but_not_scientific_content() -> None:
    baseline = _protocol()
    abandoned = replace(
        baseline,
        status=ProtocolStatus.ABANDONED,
        abandoned_at="2026-09-09T01:00:00Z",
        abandoned_by="historical-runtime",
        abandonment_reason="The preflight falsified a design assumption.",
    )

    restored = ExperimentProtocol.from_dict(abandoned.to_dict())

    assert restored == abandoned
    assert protocol_commitment(restored) == protocol_commitment(baseline)


def test_repository_finds_and_lists_historical_abandoned_protocol(tmp_path) -> None:
    repository = FileSystemRepository(tmp_path)
    protocol = replace(
        _protocol(),
        status=ProtocolStatus.ABANDONED,
        abandoned_at="2026-09-09T01:00:00Z",
        abandoned_by="historical-runtime",
        abandonment_reason="Superseded before execution.",
    )
    destination = (
        tmp_path
        / "inquiries"
        / "legacy"
        / "protocols"
        / "abandoned"
        / f"{protocol.protocol_id}.json"
    )
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(protocol.to_dict()), encoding="utf-8")

    assert repository.find_protocol("legacy", protocol.protocol_id) == protocol
    assert repository.list_protocols("legacy") == [protocol]


def test_legacy_frozen_protocol_is_verified_from_hash_chained_freeze_event(
    tmp_path,
) -> None:
    repository = FileSystemRepository(tmp_path)
    protocol = replace(_protocol(), status=ProtocolStatus.FROZEN)
    historical_payload = protocol.to_dict()
    # This field was introduced after the historical commitment.  Parsing adds
    # its modern default, so reconstructing the old hash from today's model
    # would be wrong even though the original bytes remain intact.
    historical_payload.pop("human_subjects")
    committed_payload = dict(historical_payload)
    for field_name in (
        "status",
        "protocol_hash",
        "registration_timestamp",
        "external_anchor",
    ):
        committed_payload.pop(field_name, None)
    historical_payload["protocol_hash"] = hashlib.sha256(
        json.dumps(
            committed_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    frozen = ExperimentProtocol.from_dict(historical_payload)
    assert protocol_commitment(frozen) != frozen.protocol_hash
    destination = (
        tmp_path
        / "inquiries"
        / "legacy"
        / "protocols"
        / "frozen"
        / f"{frozen.protocol_id}.json"
    )
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(historical_payload), encoding="utf-8")
    ledger = destination.parents[2] / "ledger.jsonl"
    body = {
        "sequence": 1,
        "event_id": "evt-legacy-freeze",
        "timestamp": "2026-09-09T00:00:01Z",
        "actor": "historical-runtime",
        "command": "protocol.freeze",
        "aggregate_type": "protocol",
        "aggregate_id": frozen.protocol_id,
        "payload": historical_payload,
        "previous_hash": None,
    }
    event = {
        **body,
        "event_hash": hashlib.sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    ledger.write_text(json.dumps(event) + "\n", encoding="utf-8")

    result = repository.verify_legacy_protocol_integrity("legacy", frozen)

    assert result["new_runs_or_evidence_permitted"] is False
    assert repository.verify_ledger("legacy")["valid"] is True


def test_legacy_evidence_requires_exact_hash_chained_projection(tmp_path) -> None:
    repository = FileSystemRepository(tmp_path)
    evidence = EvidenceRecord(
        evidence_id="evd-legacy",
        hypothesis_id="hyp-legacy",
        direction=EvidenceDirection.INCONCLUSIVE,
        summary="Historical result retained without a modern admission receipt.",
        dataset_id=None,
        analysis_id="run-legacy",
        created_at="2026-09-09T02:00:00Z",
        scientific_evidence_eligible=True,
        exploratory=True,
    )
    payload = evidence.to_dict()
    destination = (
        tmp_path
        / "inquiries"
        / "legacy"
        / "evidence"
        / f"{evidence.evidence_id}.json"
    )
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(payload), encoding="utf-8")
    body = {
        "sequence": 1,
        "event_id": "evt-legacy-evidence",
        "timestamp": evidence.created_at,
        "actor": "historical-runtime",
        "command": "evidence.record",
        "aggregate_type": "evidence",
        "aggregate_id": evidence.evidence_id,
        "payload": payload,
        "previous_hash": None,
    }
    event = {
        **body,
        "event_hash": hashlib.sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    ledger = destination.parents[1] / "ledger.jsonl"
    ledger.write_text(json.dumps(event) + "\n", encoding="utf-8")

    result = repository.verify_legacy_evidence_integrity("legacy", evidence)

    assert result["current_scientific_admission"] is False
    (tmp_path / "workspace.json").write_text(
        json.dumps({
            "schema_version": 1,
            "created_at": "2026-09-09T01:00:00Z",
            "active_inquiry_id": "legacy",
            "inquiry_ids": ["legacy"],
        }),
        encoding="utf-8",
    )
    (destination.parents[1] / "claims.json").write_text("[]", encoding="utf-8")
    assert ResearchService(repository).list_evidence_status_events("legacy") == []
    destination.write_text(
        json.dumps({**payload, "summary": "retrospectively changed"}),
        encoding="utf-8",
    )
    try:
        repository.verify_legacy_evidence_integrity("legacy", evidence)
    except IntegrityError as exc:
        assert "differs from its record event" in str(exc)
    else:
        raise AssertionError("tampered legacy evidence projection was accepted")


def test_legacy_recommendation_is_retained_without_current_selection_authority(
    tmp_path,
) -> None:
    repository = FileSystemRepository(tmp_path)
    candidate = ActionCandidate(
        action_id="legacy-action",
        title="Historical candidate",
        distinguishes_hypotheses=["hyp-legacy"],
        expected_discrimination=0.8,
        uncertainty_reduction=0.6,
        cost=0.2,
        burden=0.1,
        safety_risk=0.0,
        ambiguity_risk=0.3,
        rationale="Historical score retained before typed discrimination targets.",
    )
    recommendation = ActionRecommendation(
        recommendation_id="rec-legacy",
        selected_action_id=candidate.action_id,
        created_at="2026-09-09T03:00:00Z",
        created_by="historical-runtime",
        rationale="Historical selection; not current authority.",
        candidates=[candidate],
        ranked_scores=[ActionScore(candidate.action_id, 1.0)],
        weights=SelectionWeights(),
    )
    payload = recommendation.to_dict()
    destination = (
        tmp_path
        / "inquiries"
        / "legacy"
        / "recommendations"
        / f"{recommendation.recommendation_id}.json"
    )
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(payload), encoding="utf-8")
    body = {
        "sequence": 1,
        "event_id": "evt-legacy-recommendation",
        "timestamp": recommendation.created_at,
        "actor": "historical-runtime",
        "command": "next-action.recommend",
        "aggregate_type": "recommendation",
        "aggregate_id": recommendation.recommendation_id,
        "payload": payload,
        "previous_hash": None,
    }
    event = {
        **body,
        "event_hash": hashlib.sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    ledger = destination.parents[1] / "ledger.jsonl"
    ledger.write_text(json.dumps(event) + "\n", encoding="utf-8")

    result = repository.verify_legacy_recommendation_integrity(
        "legacy", recommendation
    )

    assert result["current_selection_authority"] is False


def test_committed_v1_information_score_replays_without_retroactive_rewrite(
    tmp_path,
) -> None:
    repository = FileSystemRepository(tmp_path)
    candidate = ActionCandidate(
        action_id="historical-information-action",
        title="Historical information action",
        distinguishes_hypotheses=[],
        information_targets=["machine:historical-uncertainty"],
        expected_discrimination=0.8,
        uncertainty_reduction=0.6,
        cost=0.2,
        burden=0.1,
        safety_risk=0.0,
        ambiguity_risk=0.3,
        prerequisite_evidence_refs=["historical-review:complete"],
        safety_review_refs=["scope:software-only"],
        rationale=(
            "This committed record predates the separation of information "
            "gain from hypothesis discrimination."
        ),
    )
    weights = SelectionWeights(duration=0.0)
    recommendation = ActionRecommendation(
        recommendation_id="rec-committed-v1",
        selected_action_id=candidate.action_id,
        created_at="2026-09-11T18:11:56Z",
        created_by="historical-runtime",
        rationale=candidate.rationale,
        candidates=[candidate],
        ranked_scores=[
            ActionScore(
                candidate.action_id,
                0.79,
                {
                    "expected_discrimination": 0.8,
                    "uncertainty_reduction": 0.3,
                    "cost_penalty": -0.05,
                    "duration_penalty": -0.0,
                    "burden_penalty": -0.035,
                    "safety_risk_penalty": -0.0,
                    "ambiguity_risk_penalty": -0.225,
                },
            )
        ],
        weights=weights,
    )
    uncommitted_payload = recommendation.to_dict()
    uncommitted_payload.pop("score_contract_version")
    uncommitted_payload.pop("recommendation_payload_sha256")
    commitment = hashlib.sha256(
        json.dumps(
            uncommitted_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    payload = {**uncommitted_payload, "recommendation_payload_sha256": commitment}
    destination = (
        tmp_path
        / "inquiries"
        / "legacy"
        / "recommendations"
        / "rec-committed-v1.json"
    )
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "workspace.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-09-11T18:00:00Z",
                "active_inquiry_id": "legacy",
                "inquiry_ids": ["legacy"],
            }
        ),
        encoding="utf-8",
    )
    body = {
        "sequence": 1,
        "event_id": "evt-committed-v1",
        "timestamp": recommendation.created_at,
        "actor": "historical-runtime",
        "command": "next-action.recommend",
        "aggregate_type": "recommendation",
        "aggregate_id": recommendation.recommendation_id,
        "payload": payload,
        "previous_hash": None,
    }
    event = {
        **body,
        "event_hash": hashlib.sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    ledger = destination.parents[1] / "ledger.jsonl"
    ledger.write_text(json.dumps(event) + "\n", encoding="utf-8")

    restored = ResearchService(repository).list_recommendations("legacy")

    assert restored[0].score_contract_version == 1
    assert restored[0].candidates[0].expected_discrimination == 0.8

    tampered = dict(payload)
    tampered["rationale"] = "A retrospectively rewritten rationale."
    tampered_without_commitment = dict(tampered)
    tampered_without_commitment.pop("recommendation_payload_sha256")
    tampered["recommendation_payload_sha256"] = hashlib.sha256(
        json.dumps(
            tampered_without_commitment,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    destination.write_text(json.dumps(tampered), encoding="utf-8")
    try:
        ResearchService(repository).list_recommendations("legacy")
    except IntegrityError as exc:
        assert "differs from its selection event" in str(exc)
    else:
        raise AssertionError("rewritten historical recommendation was accepted")


def test_pending_review_authority_guard_distinguishes_negation_from_claim() -> None:
    negated = (
        "The structure is ready for review, but staging does not imply human "
        "approval and does not create evidence."
    )

    assert require_pending_review_rationale(negated) == negated
    try:
        require_pending_review_rationale(
            "Codex approved and validated this proposal for human review."
        )
    except ValidationError as exc:
        assert "provisional staging" in str(exc)
    else:
        raise AssertionError("unnegated authority claim was accepted")
