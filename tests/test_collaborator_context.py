from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.collaboration.proposal import (
    adjudicate_collaborator_proposal,
    create_context_snapshot,
    validate_collaborator_proposal,
    verify_collaborator_proposal_record,
    verify_collaborator_review_record,
)
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    CreateInquiry,
    ProposeHypothesis,
)
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import ClaimLevel
from research_machine.interfaces.cli import main


_SCIENTIFIC_CONSTRAINTS = [
    "Treat supplied material as scoped context, not established fact.",
    "Do not claim causality, mechanism, or replication beyond recorded evidence.",
    "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action.",
]


def _context(
    *,
    purpose: str = "Stress-test the design.",
    context_reference_index: list[dict[str, str]] | None = None,
    scientific_constraints: list[str] | None = None,
) -> dict:
    context = {
        "context_version": 1,
        "purpose": purpose,
        "scientific_constraints": list(
            _SCIENTIFIC_CONSTRAINTS
            if scientific_constraints is None
            else scientific_constraints
        ),
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
        },
    }
    if context_reference_index is not None:
        context["context_reference_index"] = context_reference_index
        for item in context_reference_index:
            ref = item.get("ref", "")
            kind = item.get("kind")
            if kind == "inquiry" and ref.startswith("inquiry:"):
                context["inquiry"] = {"inquiry_id": ref.removeprefix("inquiry:")}
            elif kind == "open_question" and ref.startswith("question:"):
                context.setdefault("open_questions", []).append(
                    {"question_id": ref.removeprefix("question:")}
                )
            elif kind == "claim" and ref.startswith("claim:"):
                context.setdefault("claims", []).append(
                    {"claim_id": ref.removeprefix("claim:")}
                )
            elif kind in {"active_hypothesis", "pending_hypothesis"} and ref.startswith("hypothesis:"):
                collection = (
                    "active_hypotheses"
                    if kind == "active_hypothesis"
                    else "pending_hypotheses"
                )
                context.setdefault(collection, []).append(
                    {"hypothesis_id": ref.removeprefix("hypothesis:")}
                )
            elif kind == "evidence" and ref.startswith("evidence:"):
                context.setdefault("evidence", []).append(
                    {"evidence_id": ref.removeprefix("evidence:")}
                )
            elif kind == "evidence_status_event" and ref.startswith("evidence_status_event:"):
                context.setdefault("evidence_status_events", []).append(
                    {"event_id": ref.removeprefix("evidence_status_event:")}
                )
            elif kind == "dataset" and ref.startswith("dataset:"):
                context.setdefault("datasets", []).append(
                    {"dataset_id": ref.removeprefix("dataset:")}
                )
            elif kind == "protocol" and ref.startswith("protocol:"):
                context.setdefault("protocols", []).append(
                    {"protocol_id": ref.removeprefix("protocol:")}
                )
            elif kind == "run" and ref.startswith("run:"):
                context.setdefault("runs", []).append(
                    {"run_id": ref.removeprefix("run:")}
                )
            elif kind == "ethics_review_event" and ref.startswith("ethics_review_event:"):
                context.setdefault("ethics_review_events", []).append(
                    {"event_id": ref.removeprefix("ethics_review_event:")}
                )
    return context


def test_collaborator_context_is_read_only_and_preserves_scientific_boundaries(
    tmp_path
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Question", "Statement", "question"))
    service.add_question(AddQuestion("What comparison would discriminate causes?"))
    claim = service.add_claim(
        AddClaim(
            "The observed contrast is a source claim, not a causal finding.",
            ClaimLevel.STATISTICAL_ASSOCIATION,
        )
    )
    context = service.collaborator_context(purpose="Help draft a design review.")
    assert context["write_boundary"]["provider_required"] is False
    assert context["ethics_review_events"] == []
    assert context["write_boundary"]["context_is_read_only"] is True
    assert context["open_questions"][0]["text"].startswith("What comparison")
    assert context["claims"][0]["claim_id"] == claim.claim_id
    assert context["evidence"] == []
    assert context["datasets"] == []
    assert context["protocols"] == []
    assert context["runs"] == []
    assert context["context_reference_index"] == [
        {"ref": f"inquiry:{context['inquiry']['inquiry_id']}", "kind": "inquiry"},
        {
            "ref": f"question:{context['open_questions'][0]['question_id']}",
            "kind": "open_question",
        },
        {"ref": f"claim:{claim.claim_id}", "kind": "claim"},
    ]
    assert any("causality" in item for item in context["scientific_constraints"])


def test_proposal_can_cite_body_backed_evidence_status_event(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[
            {
                "ref": "evidence_status_event:evidence-status-1",
                "kind": "evidence_status_event",
            }
        ]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"],
        evidence_refs=["evidence_status_event:evidence-status-1"],
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    record = json.loads(Path(validated["record_file"]).read_text(encoding="utf-8"))
    assert record["proposal"]["suggestions"][0]["evidence_refs"] == [
        "evidence_status_event:evidence-status-1"
    ]


def test_context_snapshot_rejects_index_without_visible_body_record(
    tmp_path: Path,
) -> None:
    context = _context()
    context["context_reference_index"] = [
        {"ref": "claim:claim-1", "kind": "claim"}
    ]

    with pytest.raises(ValidationError, match="absent from the frozen context body"):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_context_snapshot_rejects_visible_body_record_missing_from_index(
    tmp_path: Path,
) -> None:
    context = _context()
    context["claims"] = [{"claim_id": "claim-1"}]
    context["context_reference_index"] = []

    with pytest.raises(ValidationError, match="missing from context_reference_index"):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_context_snapshot_rejects_duplicate_visible_body_reference(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    context["claims"].append({"claim_id": "claim-1"})

    with pytest.raises(
        ValidationError,
        match="duplicate citable record: claim:claim-1",
    ):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_context_snapshot_rejects_duplicate_hypothesis_across_review_lanes(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[
            {"ref": "hypothesis:hypothesis-1", "kind": "active_hypothesis"}
        ]
    )
    context["pending_hypotheses"] = [{"hypothesis_id": "hypothesis-1"}]

    with pytest.raises(
        ValidationError,
        match="duplicate citable record: hypothesis:hypothesis-1",
    ):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_collaborator_context_purpose_must_be_canonical(tmp_path: Path) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Question", "Statement", "question"))

    with pytest.raises(ValidationError, match="purpose must be canonical"):
        service.collaborator_context(purpose=" design review ")
    with pytest.raises(ValidationError, match="purpose must not be empty"):
        service.collaborator_context(purpose="")


def test_collaborator_context_exposes_pending_review_hypotheses(
    tmp_path: Path,
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Question", "Statement", "question"))
    hypothesis = service.propose_hypothesis(
        ProposeHypothesis(
            statement="A pending proposal needs review before confirmation.",
            observable_prediction="A reviewer can inspect a bounded prediction.",
            null_model="The bounded prediction does not hold.",
            falsification_conditions=["The registered observation is absent."],
        )
    )
    staged = service.stage_hypothesis(
        hypothesis.hypothesis_id,
        rationale="The proposal is complete but still needs human review.",
        confidence="high",
    )

    context = service.collaborator_context(purpose="Stress-test the design.")

    assert context["active_hypotheses"] == []
    assert context["pending_hypotheses"][0]["hypothesis_id"] == staged.hypothesis_id
    assert context["pending_hypotheses"][0]["workflow_state"] == "pending_review"
    assert {
        "ref": f"hypothesis:{staged.hypothesis_id}",
        "kind": "pending_hypothesis",
    } in context["context_reference_index"]
    context_result = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                context_result["context_sha256"],
                evidence_refs=[f"hypothesis:{staged.hypothesis_id}"],
            )
        ),
        encoding="utf-8",
    )
    result = validate_collaborator_proposal(
        Path(context_result["context_file"]),
        context_result["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    record = json.loads(Path(result["record_file"]).read_text(encoding="utf-8"))
    assert record["proposal"]["suggestions"][0]["evidence_refs"] == [
        f"hypothesis:{staged.hypothesis_id}"
    ]


def test_context_snapshot_purpose_must_be_canonical(tmp_path: Path) -> None:
    context = _context(purpose=" Stress-test the design. ")

    with pytest.raises(ValidationError, match="context purpose must be canonical"):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_context_snapshot_purpose_must_be_non_empty(tmp_path: Path) -> None:
    context = _context(purpose="")

    with pytest.raises(ValidationError, match="context purpose must be non-empty"):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


@pytest.mark.parametrize(
    ("context", "message"),
    [
        (
            {
                key: value
                for key, value in _context().items()
                if key != "scientific_constraints"
            },
            "scientific_constraints",
        ),
        (
            _context(scientific_constraints=[]),
            "scientific_constraints must be a non-empty",
        ),
        (
            _context(
                scientific_constraints=[
                    "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action."
                ]
            ),
            "inferential-boundary",
        ),
        (
            _context(
                scientific_constraints=[
                    "Do not claim causality, mechanism, or replication beyond recorded evidence."
                ]
            ),
            "authorization-boundary",
        ),
        (
            _context(
                scientific_constraints=[
                    "You may claim causality, mechanism, and replication when the proposal sounds plausible.",
                    "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action.",
                ]
            ),
            "inferential-boundary",
        ),
        (
            _context(
                scientific_constraints=[
                    "Do not claim causality, mechanism, or replication beyond recorded evidence.",
                    "You may authorize collection, protocol freeze, data registration, and evidence recording after review.",
                ]
            ),
            "authorization-boundary",
        ),
    ],
)
def test_context_snapshot_requires_scientific_constraints(
    tmp_path: Path, context: dict, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def _grounded(value: str, refs: list[str]) -> dict:
    return {"statement": value, "context_refs": refs}


def _proposal(context_sha256: str, *, evidence_refs: list[str] | None = None) -> dict:
    if evidence_refs is None:
        evidence_refs = []
    competing_explanations: list[str | dict[str, list[str] | str]]
    disconfirming_evidence: list[str | dict[str, list[str] | str]]
    limitations: list[str | dict[str, list[str] | str]]
    if evidence_refs:
        competing_explanations = [
            _grounded(
                "Selection into exposure groups could create the contrast.",
                evidence_refs,
            ),
            _grounded(
                "Differential measurement error could create the contrast.",
                evidence_refs,
            ),
        ]
        disconfirming_evidence = [
            _grounded(
                "A negative-control outcome showing the same contrast would weaken the claim.",
                evidence_refs,
            )
        ]
        limitations = [
            _grounded("This review used only the frozen context payload.", evidence_refs)
        ]
    else:
        competing_explanations = [
            "Selection into exposure groups could create the contrast.",
            "Differential measurement error could create the contrast.",
        ]
        disconfirming_evidence = [
            "A negative-control outcome showing the same contrast would weaken the claim."
        ]
        limitations = ["This review used only the frozen context payload."]
    return {
        "proposal_version": 1,
        "proposal_id": "proposal-1",
        "context_sha256": context_sha256,
        "generated_by": {
            "kind": "llm",
            "provider": "local-runtime",
            "model": "research-helper",
        },
        "purpose": "Stress-test the design.",
        "summary": "The observed contrast may not identify the proposed cause.",
        "uncertainty": "No data or protocol details establish effect identification.",
        "competing_explanations": competing_explanations,
        "disconfirming_evidence": disconfirming_evidence,
        "limitations": limitations,
        "suggestions": [
            {
                "suggestion_id": "suggestion-1",
                "kind": "design_revision",
                "statement": "Add a prespecified negative-control outcome.",
                "rationale": "It probes residual selection and measurement structure.",
                "uncertainty": "A null control result would not eliminate all confounding.",
                "evidence_refs": evidence_refs,
                "falsification_conditions": [
                    "The negative-control outcome exhibits the predicted primary contrast."
                ],
                "next_test": "Review whether the control is causally insulated from exposure.",
                "authority": "review_only",
            }
        ],
    }


def _review(proposal_record_sha256: str) -> dict:
    return {
        "review_version": 1,
        "review_id": "review-1",
        "proposal_record_sha256": proposal_record_sha256,
        "reviewer": {"reviewer_id": "researcher-1", "role": "principal investigator"},
        "reviewed_at": "2026-09-06T12:00:00Z",
        "overall_assessment": "Advance the control idea for ordinary design review.",
        "decisions": [
            {
                "suggestion_id": "suggestion-1",
                "disposition": "advance_to_domain_review",
                "rationale": "The proposed control could discriminate an alternative explanation.",
                "domain_route": "design.revise",
            }
        ],
    }


def _canonical_json_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _proposal_body_grounding(proposal: dict) -> list[dict]:
    result = []
    for section in ("competing_explanations", "disconfirming_evidence", "limitations"):
        for item in proposal[section]:
            if isinstance(item, dict):
                statement = item["statement"]
                refs = item["context_refs"]
            else:
                statement = item
                refs = []
            result.append(
                {
                    "section": section,
                    "statement_sha256": hashlib.sha256(
                        statement.encode("utf-8")
                    ).hexdigest(),
                    "context_refs": refs,
                }
            )
    return result


def _pad_retained_suggestion_statement(record: dict) -> None:
    suggestion = record["reviewed_suggestions"][0]["suggestion"]
    suggestion["statement"] = " Add a prespecified negative-control outcome. "
    record["reviewed_suggestions"][0]["suggestion_sha256"] = _canonical_json_sha256(
        suggestion
    )


def test_context_snapshot_and_proposal_are_write_once_and_noncanonical(
    tmp_path: Path,
) -> None:
    repository = FileSystemRepository(tmp_path / "workspace")
    service = ResearchService(repository, actor="test")
    service.init_workspace()
    inquiry = service.create_inquiry(
        CreateInquiry("Question", "Can exposure cause outcome?", "question")
    )
    service.add_question(
        AddQuestion("Which design change would best test the alternative explanation?"),
        inquiry.inquiry_id,
    )
    claim = service.add_claim(
        AddClaim(
            "The current comparison is associational until a causal protocol is frozen.",
            ClaimLevel.STATISTICAL_ASSOCIATION,
        ),
        inquiry.inquiry_id,
    )
    before = service.show_inquiry(inquiry.inquiry_id)

    context_result = create_context_snapshot(
        service.collaborator_context(inquiry.inquiry_id, purpose="Stress-test the design."),
        tmp_path / "context",
    )
    context = json.loads(Path(context_result["context_file"]).read_text(encoding="utf-8"))
    cited_refs = [
        item["ref"]
        for item in context["context_reference_index"]
        if item["ref"] in {
            f"question:{context['open_questions'][0]['question_id']}",
            f"claim:{claim.claim_id}",
        }
    ]
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(context_result["context_sha256"], evidence_refs=cited_refs)),
        encoding="utf-8",
    )
    result = validate_collaborator_proposal(
        Path(context_result["context_file"]),
        context_result["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )

    record = json.loads(Path(result["record_file"]).read_text(encoding="utf-8"))
    assert record["status"] == "pending_human_review"
    assert record["context_reference_index"] == context["context_reference_index"]
    assert record["context_scientific_constraints"] == context["scientific_constraints"]
    assert record["proposal_body_grounding"] == _proposal_body_grounding(
        record["proposal"]
    )
    assert record["proposal"]["suggestions"][0]["evidence_refs"] == cited_refs
    assert record["canonical_writes_performed"] is False
    assert record["model_invoked_by_faraday"] is False
    assert record["scientific_evidence_eligible"] is False
    assert record["authorized_actions"] == []
    verified = verify_collaborator_proposal_record(
        Path(result["record_file"]),
        result["record_sha256"],
    )
    assert verified == {
        "record_sha256": result["record_sha256"],
        "record_status": "pending_human_review",
        "context_sha256": context_result["context_sha256"],
        "proposal_sha256": result["proposal_sha256"],
        "proposal_id": "proposal-1",
        "suggestion_count": 1,
        "body_grounding_count": 4,
        "context_reference_replay": "retained_index_verified",
        "canonical_writes_performed": False,
        "model_invoked_by_faraday": False,
        "scientific_evidence_eligible": False,
    }
    assert service.show_inquiry(inquiry.inquiry_id) == before
    with pytest.raises(ValidationError, match="already exists"):
        validate_collaborator_proposal(
            Path(context_result["context_file"]),
            context_result["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"authority": "canonical_write"}
            ),
            "authority must be review_only",
        ),
        (
            lambda proposal: proposal.update({"disconfirming_evidence": []}),
            "disconfirming_evidence must be a non-empty",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"falsification_conditions": []}
            ),
            "falsification_conditions must be a non-empty",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"evidence_refs": ["evidence:not-in-context"]}
            ),
            "evidence_refs are not present in the frozen context",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"evidence_refs": ["claim:claim-1", " claim:claim-1 "]}
            ),
            "evidence_refs must be canonical",
        ),
        (
            lambda proposal: proposal.update(
                {"summary": " The observed contrast may not identify the proposed cause. "}
            ),
            "summary must be canonical",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"statement": " Add a prespecified negative-control outcome. "}
            ),
            "statement must be canonical",
        ),
        (
            lambda proposal: proposal["suggestions"][0].update(
                {"next_test": " Review whether the control is causally insulated from exposure. "}
            ),
            "next_test must be canonical",
        ),
    ],
)
def test_proposal_fails_closed_on_missing_scientific_boundaries(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"],
        evidence_refs=["claim:claim-1"],
    )
    mutation(proposal)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda record: record.update({"canonical_writes_performed": True}),
            "authority boundary",
        ),
        (
            lambda record: record["proposal"].update({"context_sha256": "0" * 64}),
            "not bound to the exact context hash",
        ),
        (
            lambda record: record["proposal"]["suggestions"][0].update(
                {"authority": "canonical_write"}
            ),
            "authority must be review_only",
        ),
        (
            lambda record: record["proposal_body_grounding"][0].update(
                {"context_refs": ["claim:not-in-context"]}
            ),
            "body grounding disagrees",
        ),
        (
            lambda record: record["proposal"]["suggestions"][0].update(
                {"evidence_refs": ["claim:not-in-context"]}
            ),
            "evidence_refs are not present",
        ),
        (
            lambda record: record.update(
                {
                    "context_scientific_constraints": [
                        "Do not authorize collection, protocol freeze, data registration, evidence recording, or other canonical action."
                    ]
                }
            ),
            "inferential-boundary",
        ),
    ],
)
def test_verify_collaborator_proposal_record_replays_retained_boundaries(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    record_path = Path(validated["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    mutation(record)
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match=message):
        verify_collaborator_proposal_record(record_path, trusted_hash)


def test_proposal_requires_a_citation_when_context_has_references(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"],
        evidence_refs=["claim:claim-1"],
    )
    proposal["suggestions"][0]["evidence_refs"] = []
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    with pytest.raises(ValidationError, match="evidence_refs must be a non-empty"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


def test_proposal_requires_grounded_body_claims_when_context_has_references(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"],
        evidence_refs=["claim:claim-1"],
    )
    proposal["competing_explanations"] = [
        "Selection into exposure groups could create the contrast."
    ]
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    with pytest.raises(ValidationError, match="must cite frozen context"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


def test_proposal_rejects_body_grounding_outside_frozen_context(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(
        snapshot["context_sha256"],
        evidence_refs=["claim:claim-1"],
    )
    proposal["limitations"][0]["context_refs"] = ["claim:not-in-context"]
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    with pytest.raises(ValidationError, match="references are not present"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda review: review.update(
                {"overall_assessment": " Advance the control idea for ordinary design review. "}
            ),
            "overall_assessment must be canonical",
        ),
        (
            lambda review: review["decisions"][0].update(
                {"rationale": " The proposed control could discriminate an alternative explanation. "}
            ),
            "decision.rationale must be canonical",
        ),
    ],
)
def test_collaborator_review_prose_must_be_canonical(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    mutation(review)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        adjudicate_collaborator_proposal(
            Path(validated["record_file"]),
            validated["record_sha256"],
            review_path,
            tmp_path / "reviewed",
        )
    assert not (tmp_path / "reviewed").exists()


def test_proposal_adjudication_replays_retained_body_grounding(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    record_path = Path(validated["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["proposal_body_grounding"][0]["context_refs"] = ["claim:not-in-context"]
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(_review(trusted_hash)), encoding="utf-8")

    with pytest.raises(ValidationError, match="body grounding disagrees"):
        adjudicate_collaborator_proposal(
            record_path,
            trusted_hash,
            review_path,
            tmp_path / "reviewed",
        )
    assert not (tmp_path / "reviewed").exists()


def test_proposal_suggestion_ids_must_be_canonical(tmp_path: Path) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    duplicate = dict(proposal["suggestions"][0])
    duplicate["suggestion_id"] = " suggestion-1 "
    proposal["suggestions"].append(duplicate)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    with pytest.raises(ValidationError, match="suggestion_id must be canonical"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda proposal: proposal.update({"proposal_id": " proposal-1 "}),
            "proposal_id must be canonical",
        ),
        (
            lambda proposal: proposal.update(
                {"purpose": " Stress-test the design. "}
            ),
            "purpose does not match its context",
        ),
        (
            lambda proposal: proposal["generated_by"].update(
                {"provider": " local-runtime "}
            ),
            "generated_by.provider must be canonical",
        ),
        (
            lambda proposal: proposal["generated_by"].update(
                {"model": " research-helper "}
            ),
            "generated_by.model must be canonical",
        ),
    ],
)
def test_proposal_identity_and_generator_handles_must_be_canonical(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    mutation(proposal)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


def test_proposal_rejects_stale_context_and_duplicate_json_keys(tmp_path: Path) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        '{"proposal_version":1,"proposal_version":1}', encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="trusted SHA-256"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            "0" * 64,
            proposal_path,
            tmp_path / "stale",
        )
    with pytest.raises(ValidationError, match="duplicate JSON object key"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]),
            snapshot["context_sha256"],
            proposal_path,
            tmp_path / "duplicate",
        )


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        (
            [
                {"ref": "question:q1", "kind": "open_question"},
                {"ref": " question:q1 ", "kind": "open_question"},
            ],
            "ref must be canonical",
        ),
        (
            [{"ref": "source:x", "kind": "external_source"}],
            "kind is unsupported",
        ),
        (
            [{"ref": "evidence:ev1", "kind": "claim"}],
            "ref must match kind claim",
        ),
        (
            [{"ref": "claim:claim-1", "kind": "claim", "title": "Extra label"}],
            "has unknown fields",
        ),
    ],
)
def test_proposal_rejects_malformed_context_reference_index(
    tmp_path: Path, reference: list[dict[str, str]], message: str
) -> None:
    context = _context(context_reference_index=reference)
    with pytest.raises(ValidationError, match=message):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


def test_validate_proposal_replays_context_scientific_constraints(
    tmp_path: Path,
) -> None:
    context = _context()
    del context["scientific_constraints"]
    context_dir = tmp_path / "manual-context"
    context_dir.mkdir()
    context_file = context_dir / "collaborator-context.json"
    context_file.write_text(json.dumps(context), encoding="utf-8")
    context_sha256 = hashlib.sha256(context_file.read_bytes()).hexdigest()
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(_proposal(context_sha256)), encoding="utf-8")

    with pytest.raises(ValidationError, match="scientific_constraints"):
        validate_collaborator_proposal(
            context_file,
            context_sha256,
            proposal_path,
            tmp_path / "validated",
        )
    assert not (tmp_path / "validated").exists()


def test_cli_exports_context_and_validates_proposal_without_a_provider(
    tmp_path: Path, capsys
) -> None:
    workspace = tmp_path / "workspace"
    common = ["--workspace", str(workspace), "--json"]
    assert main([*common, "workspace", "init"]) == 0
    capsys.readouterr()
    assert main(
        [
            *common,
            "inquiry",
            "create",
            "--id",
            "provider-neutral",
            "--title",
            "Provider-neutral review",
            "--statement",
            "Can optional collaboration preserve scientific authority?",
        ]
    ) == 0
    capsys.readouterr()
    context_dir = tmp_path / "context"
    assert main(
        [
            *common,
            "collaborator",
            "context",
            "--purpose",
            "Stress-test the design.",
            "--output",
            str(context_dir),
        ]
    ) == 0
    context_result = json.loads(capsys.readouterr().out)["result"]
    context_payload = json.loads(
        Path(context_result["context_file"]).read_text(encoding="utf-8")
    )
    inquiry_ref = context_payload["context_reference_index"][0]["ref"]
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(context_result["context_sha256"], evidence_refs=[inquiry_ref])
        ),
        encoding="utf-8",
    )
    output = tmp_path / "validated"
    assert main(
        [
            *common,
            "collaborator",
            "validate-proposal",
            "--context-file",
            context_result["context_file"],
            "--expected-context-sha256",
            context_result["context_sha256"],
            "--proposal-file",
            str(proposal_path),
            "--output",
            str(output),
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "pending_human_review"
    assert result["model_invoked_by_faraday"] is False
    assert main(
        [
            *common,
            "collaborator",
            "verify-proposal",
            "--proposal-record-file",
            result["record_file"],
            "--expected-proposal-record-sha256",
            result["record_sha256"],
        ]
    ) == 0
    verified_proposal = json.loads(capsys.readouterr().out)["result"]
    assert verified_proposal["record_status"] == "pending_human_review"
    assert verified_proposal["context_reference_replay"] == "retained_index_verified"
    assert verified_proposal["model_invoked_by_faraday"] is False

    review_file = tmp_path / "review.json"
    review_file.write_text(json.dumps(_review(result["record_sha256"])), encoding="utf-8")
    assert main(
        [
            *common,
            "collaborator",
            "review-proposal",
            "--proposal-record-file",
            result["record_file"],
            "--expected-proposal-record-sha256",
            result["record_sha256"],
            "--review-file",
            str(review_file),
            "--output",
            str(tmp_path / "reviewed"),
        ]
    ) == 0
    reviewed = json.loads(capsys.readouterr().out)["result"]
    assert reviewed["status"] == "reviewed_requires_manual_domain_action"
    assert reviewed["advanced_suggestion_count"] == 1
    assert reviewed["canonical_writes_performed"] is False
    assert main(
        [
            *common,
            "collaborator",
            "verify-review",
            "--review-record-file",
            reviewed["record_file"],
            "--expected-review-record-sha256",
            reviewed["record_sha256"],
        ]
    ) == 0
    verified = json.loads(capsys.readouterr().out)["result"]
    assert verified["reviewed_suggestion_count"] == 1
    assert verified["context_reference_replay"] == "verified"
    assert verified["proposal_record_replay"] == "verified"
    assert verified["proposal_suggestion_replay"] == "verified"
    assert verified["canonical_writes_performed"] is False


def test_collaborator_context_cli_requires_purpose(tmp_path: Path) -> None:
    common = ["--workspace", str(tmp_path / "workspace"), "--json"]
    assert main([*common, "workspace", "init"]) == 0

    with pytest.raises(SystemExit):
        main([*common, "collaborator", "context"])


def test_proposal_adjudication_is_complete_hash_bound_and_noncanonical(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    second_suggestion = {
        **proposal["suggestions"][0],
        "suggestion_id": "suggestion-2",
        "kind": "question",
        "statement": "Ask whether selection into the exposure is measured.",
        "rationale": "The design cannot interpret exposure differences without it.",
        "next_test": "Decide whether this is already represented in the DAG.",
    }
    proposal["suggestions"].append(second_suggestion)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    review["decisions"].append({
        "suggestion_id": "suggestion-2",
        "disposition": "defer",
        "rationale": "The existing design record needs to be checked first.",
        "domain_route": "none",
    })
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    result = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record = json.loads(Path(result["record_file"]).read_text(encoding="utf-8"))
    assert record["advanced_suggestions"] == [
        {"suggestion_id": "suggestion-1", "domain_route": "design.revise"}
    ]
    assert record["proposal_suggestion_ids"] == ["suggestion-1", "suggestion-2"]
    assert record["context_reference_index"] == []
    assert record["proposal_record_replay"] == {
        "context_reference_index_sha256": _canonical_json_sha256([]),
        "context_scientific_constraints_sha256": _canonical_json_sha256(
            _SCIENTIFIC_CONSTRAINTS
        ),
        "proposal_body_grounding_sha256": _canonical_json_sha256(
            _proposal_body_grounding(proposal)
        ),
    }
    assert record["proposal_body_grounding"] == _proposal_body_grounding(proposal)
    expected_suggestions = proposal["suggestions"]
    reviewed = record["reviewed_suggestions"]
    assert reviewed == [
        {
            "suggestion_id": "suggestion-1",
            "suggestion_sha256": _canonical_json_sha256(expected_suggestions[0]),
            "suggestion": expected_suggestions[0],
            "disposition": "advance_to_domain_review",
            "rationale": "The proposed control could discriminate an alternative explanation.",
            "domain_route": "design.revise",
            "manual_domain_review_required": True,
            "canonical_writes_performed": False,
            "scientific_evidence_eligible": False,
        },
        {
            "suggestion_id": "suggestion-2",
            "suggestion_sha256": _canonical_json_sha256(expected_suggestions[1]),
            "suggestion": expected_suggestions[1],
            "disposition": "defer",
            "rationale": "The existing design record needs to be checked first.",
            "domain_route": "none",
            "manual_domain_review_required": False,
            "canonical_writes_performed": False,
            "scientific_evidence_eligible": False,
        },
    ]
    assert record["context_scientific_constraints"] == _SCIENTIFIC_CONSTRAINTS
    assert record["reviewer_identity_authenticated"] is False
    assert record["authorized_actions"] == []
    assert record["scientific_evidence_eligible"] is False
    verified = verify_collaborator_review_record(
        Path(result["record_file"]),
        result["record_sha256"],
    )
    assert verified["reviewed_suggestion_count"] == 2
    assert verified["advanced_suggestion_count"] == 1
    assert verified["context_reference_replay"] == "verified"
    assert verified["proposal_record_replay"] == "verified"
    assert verified["proposal_suggestion_replay"] == "verified"
    assert verified["scientific_evidence_eligible"] is False


def test_verify_collaborator_review_rejects_omitted_proposal_suggestion(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    proposal["suggestions"].append(
        {
            **proposal["suggestions"][0],
            "suggestion_id": "suggestion-2",
            "kind": "question",
            "statement": "Ask whether a simpler artifact explanation fits first.",
            "rationale": "The review should not jump to the favored explanation.",
            "next_test": "Check the existing evidence graph for artifact controls.",
        }
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    review["decisions"].append(
        {
            "suggestion_id": "suggestion-2",
            "disposition": "defer",
            "rationale": "The artifact explanation needs separate domain review.",
            "domain_route": "none",
        }
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["review"]["decisions"] = record["review"]["decisions"][:1]
    record["reviewed_suggestions"] = record["reviewed_suggestions"][:1]
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="exactly cover"):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_collaborator_review_rejects_reordered_proposal_suggestions(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal = _proposal(snapshot["context_sha256"])
    proposal["suggestions"].append(
        {
            **proposal["suggestions"][0],
            "suggestion_id": "suggestion-2",
            "kind": "question",
            "statement": "Ask whether a simpler artifact explanation fits first.",
            "rationale": "The review should not jump to the favored explanation.",
            "next_test": "Check the existing evidence graph for artifact controls.",
        }
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    review["decisions"].append(
        {
            "suggestion_id": "suggestion-2",
            "disposition": "defer",
            "rationale": "The artifact explanation needs separate domain review.",
            "domain_route": "none",
        }
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["reviewed_suggestions"].reverse()
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="order and coverage"):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_legacy_collaborator_review_discloses_missing_suggestion_ids(
    tmp_path: Path,
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(_review(validated["record_sha256"])), encoding="utf-8")
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.pop("proposal_suggestion_ids")
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    verified = verify_collaborator_review_record(record_path, trusted_hash)

    assert verified["context_reference_replay"] == "verified"
    assert verified["proposal_record_replay"] == "verified"
    assert verified["proposal_suggestion_replay"] == "legacy_missing"


def test_verify_legacy_collaborator_review_discloses_missing_proposal_replay(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.pop("proposal_record_replay")
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    verified = verify_collaborator_review_record(record_path, trusted_hash)

    assert verified["context_reference_replay"] == "verified"
    assert verified["proposal_record_replay"] == "legacy_missing"
    assert verified["proposal_suggestion_replay"] == "verified"
    assert verified["reviewed_suggestion_count"] == 1
    assert verified["scientific_evidence_eligible"] is False


def test_verify_legacy_collaborator_review_discloses_missing_context_index(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.pop("context_reference_index")
    record.pop("proposal_record_replay")
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    verified = verify_collaborator_review_record(record_path, trusted_hash)

    assert verified["context_reference_replay"] == "legacy_missing"
    assert verified["proposal_record_replay"] == "legacy_missing"
    assert verified["proposal_suggestion_replay"] == "verified"
    assert verified["reviewed_suggestion_count"] == 1
    assert verified["scientific_evidence_eligible"] is False


def test_verify_collaborator_review_replays_retained_context_references(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["context_reference_index"] == context["context_reference_index"]
    suggestion = record["reviewed_suggestions"][0]["suggestion"]
    suggestion["evidence_refs"] = ["claim:not-in-context"]
    record["reviewed_suggestions"][0]["suggestion_sha256"] = _canonical_json_sha256(
        suggestion
    )
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(
        ValidationError,
        match="evidence_refs are not present in the retained context",
    ):
        verify_collaborator_review_record(record_path, trusted_hash)


def test_verify_collaborator_review_replays_proposal_body_grounding_refs(
    tmp_path: Path,
) -> None:
    context = _context(
        context_reference_index=[{"ref": "claim:claim-1", "kind": "claim"}]
    )
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            _proposal(
                snapshot["context_sha256"],
                evidence_refs=["claim:claim-1"],
            )
        ),
        encoding="utf-8",
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review(validated["record_sha256"])), encoding="utf-8"
    )
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["proposal_body_grounding"][0]["context_refs"] = ["claim:not-in-context"]
    record["proposal_record_replay"]["proposal_body_grounding_sha256"] = (
        _canonical_json_sha256(record["proposal_body_grounding"])
    )
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="references are not present"):
        verify_collaborator_review_record(record_path, trusted_hash)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda record: record["reviewed_suggestions"][0]["suggestion"].update(
                {"statement": "A later rewrite cannot keep the old suggestion digest."}
            ),
            "suggestion_sha256 does not match",
        ),
        (
            lambda record: record["reviewed_suggestions"][0].update(
                {"canonical_writes_performed": True}
            ),
            "canonical write boundary",
        ),
        (
            lambda record: record.update({"advanced_suggestions": []}),
            "advanced_suggestions disagrees",
        ),
        (
            lambda record: record["reviewed_suggestions"][0].update(
                {"manual_domain_review_required": False}
            ),
            "manual review flag",
        ),
        (
            lambda record: record["review"].update({"proposal_record_sha256": "0" * 64}),
            "different proposal record",
        ),
        (
            lambda record: record["review"].update({"review_version": 2}),
            "review_version must be 1",
        ),
        (
            lambda record: record["reviewed_suggestions"][0]["suggestion"].update(
                {"authority": "canonical_write"}
            ),
            "authority must be review_only",
        ),
        (
            lambda record: record["review"].update(
                {"overall_assessment": " Advance the control idea for ordinary design review. "}
            ),
            "overall_assessment must be canonical",
        ),
        (
            lambda record: record["review"]["decisions"][0].update(
                {"rationale": " The proposed control could discriminate an alternative explanation. "}
            ),
            "decision.rationale must be canonical",
        ),
        (
            _pad_retained_suggestion_statement,
            "statement must be canonical",
        ),
        (
            lambda record: record["context_scientific_constraints"].append(
                "Additional causal and authorization boundary reminder."
            ),
            "proposal_record_replay disagrees",
        ),
    ],
)
def test_verify_collaborator_review_record_replays_retained_receipts(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(_review(validated["record_sha256"])), encoding="utf-8")
    reviewed = adjudicate_collaborator_proposal(
        Path(validated["record_file"]),
        validated["record_sha256"],
        review_path,
        tmp_path / "reviewed",
    )
    record_path = Path(reviewed["record_file"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    mutation(record)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    trusted_hash = hashlib.sha256(record_path.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match=message):
        verify_collaborator_review_record(record_path, trusted_hash)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda review: review.update({"decisions": []}),
            "must decide every suggestion",
        ),
        (
            lambda review: review["decisions"][0].update(
                {"domain_route": "hypothesis.propose"}
            ),
            "incompatible with suggestion kind",
        ),
        (
            lambda review: review["decisions"][0].update(
                {"disposition": "reject", "domain_route": "design.revise"}
            ),
            "domain_route must be none",
        ),
        (
            lambda review: review["decisions"].append(
                {
                    "suggestion_id": " suggestion-1 ",
                    "disposition": "defer",
                    "rationale": "A padded duplicate cannot become another review.",
                    "domain_route": "none",
                }
            ),
            "decision.suggestion_id must be canonical",
        ),
        (
            lambda review: review.update({"review_id": " review-1 "}),
            "review_id must be canonical",
        ),
        (
            lambda review: review["reviewer"].update({"reviewer_id": " researcher-1 "}),
            "reviewer.reviewer_id must be canonical",
        ),
    ],
)
def test_proposal_adjudication_fails_closed(
    tmp_path: Path, mutation, message: str
) -> None:
    context = _context()
    snapshot = create_context_snapshot(context, tmp_path / "context")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(snapshot["context_sha256"])), encoding="utf-8"
    )
    validated = validate_collaborator_proposal(
        Path(snapshot["context_file"]),
        snapshot["context_sha256"],
        proposal_path,
        tmp_path / "validated",
    )
    review = _review(validated["record_sha256"])
    mutation(review)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        adjudicate_collaborator_proposal(
            Path(validated["record_file"]),
            validated["record_sha256"],
            review_path,
            tmp_path / "reviewed",
        )
    assert not (tmp_path / "reviewed").exists()
