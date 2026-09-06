from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_machine.collaboration.proposal import (
    adjudicate_collaborator_proposal,
    create_context_snapshot,
    validate_collaborator_proposal,
)
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import AddQuestion, CreateInquiry
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main


def test_collaborator_context_is_read_only_and_preserves_scientific_boundaries(
    tmp_path
) -> None:
    service = ResearchService(FileSystemRepository(tmp_path), actor="test")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Question", "Statement", "question"))
    service.add_question(AddQuestion("What comparison would discriminate causes?"))
    context = service.collaborator_context(purpose="Help draft a design review.")
    assert context["write_boundary"]["provider_required"] is False
    assert context["ethics_review_events"] == []
    assert context["write_boundary"]["context_is_read_only"] is True
    assert context["open_questions"][0]["text"].startswith("What comparison")
    assert context["context_reference_index"] == [
        {"ref": f"inquiry:{context['inquiry']['inquiry_id']}", "kind": "inquiry"},
        {
            "ref": f"question:{context['open_questions'][0]['question_id']}",
            "kind": "open_question",
        },
    ]
    assert any("causality" in item for item in context["scientific_constraints"])


def _proposal(context_sha256: str, *, evidence_refs: list[str] | None = None) -> dict:
    if evidence_refs is None:
        evidence_refs = []
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
        "competing_explanations": [
            "Selection into exposure groups could create the contrast.",
            "Differential measurement error could create the contrast.",
        ],
        "disconfirming_evidence": [
            "A negative-control outcome showing the same contrast would weaken the claim."
        ],
        "limitations": ["This review used only the frozen context payload."],
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
    before = service.show_inquiry(inquiry.inquiry_id)

    context_result = create_context_snapshot(
        service.collaborator_context(inquiry.inquiry_id, purpose="Stress-test the design."),
        tmp_path / "context",
    )
    context = json.loads(Path(context_result["context_file"]).read_text(encoding="utf-8"))
    question_ref = next(
        item["ref"]
        for item in context["context_reference_index"]
        if item["kind"] == "open_question"
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(context_result["context_sha256"], evidence_refs=[question_ref])),
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
    assert record["proposal"]["suggestions"][0]["evidence_refs"] == [question_ref]
    assert record["canonical_writes_performed"] is False
    assert record["model_invoked_by_faraday"] is False
    assert record["scientific_evidence_eligible"] is False
    assert record["authorized_actions"] == []
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
    ],
)
def test_proposal_fails_closed_on_missing_scientific_boundaries(
    tmp_path: Path, mutation, message: str
) -> None:
    context = {
        "context_version": 1,
        "purpose": "Stress-test the design.",
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
        },
    }
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
    context = {
        "context_version": 1,
        "purpose": "Stress-test the design.",
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
        },
    }
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


def test_proposal_rejects_malformed_or_duplicate_context_reference_index(
    tmp_path: Path,
) -> None:
    context = {
        "context_version": 1,
        "purpose": "Stress-test the design.",
        "context_reference_index": [
            {"ref": "question:q1", "kind": "open_question"},
            {"ref": "question:q1", "kind": "open_question"},
        ],
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
        },
    }
    with pytest.raises(ValidationError, match="duplicate collaborator context reference"):
        create_context_snapshot(context, tmp_path / "context")
    assert not (tmp_path / "context").exists()


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
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal(context_result["context_sha256"])), encoding="utf-8"
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


def test_proposal_adjudication_is_complete_hash_bound_and_noncanonical(
    tmp_path: Path,
) -> None:
    context = {
        "context_version": 1,
        "purpose": "Stress-test the design.",
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
        },
    }
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
    assert record["reviewer_identity_authenticated"] is False
    assert record["authorized_actions"] == []
    assert record["scientific_evidence_eligible"] is False


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
    ],
)
def test_proposal_adjudication_fails_closed(
    tmp_path: Path, mutation, message: str
) -> None:
    context = {
        "context_version": 1,
        "purpose": "Stress-test the design.",
        "write_boundary": {
            "context_is_read_only": True,
            "provider_required": False,
        },
    }
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
