from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import (
    AddClaim,
    CreateInquiry,
    ReviewClaim,
    SetInquiryDecision,
)
from research_machine.application.rigor import audit_research_state
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    Claim,
    ClaimDisposition,
    ClaimEpistemicLayer,
    ClaimLevel,
    Inquiry,
)
from research_machine.interfaces.cli import main


def make_service(root: Path) -> ResearchService:
    counter = iter(f"recovered{index:02d}" for index in range(100))
    return ResearchService(
        FileSystemRepository(root),
        actor="method-reviewer",
        clock=lambda: "2026-09-03T12:00:00Z",
        token=lambda: next(counter),
    )


def test_legacy_inquiry_and_claim_records_load_with_conservative_defaults() -> None:
    inquiry = Inquiry.from_dict(
        {
            "inquiry_id": "legacy",
            "title": "Legacy inquiry",
            "initial_statement": "A prior question.",
            "created_at": "2026-09-01T00:00:00Z",
        }
    )
    claim = Claim.from_dict(
        {
            "claim_id": "clm-legacy",
            "statement": "A prior claim.",
            "level": "other",
            "created_at": "2026-09-01T00:00:00Z",
        }
    )

    assert inquiry.decision_to_support == ""
    assert inquiry.decision_change_criteria == []
    assert claim.epistemic_layer is ClaimEpistemicLayer.UNRESOLVED
    assert claim.disposition is ClaimDisposition.UNRESOLVED
    assert claim.confidence is None


def test_decision_context_and_claim_layers_remain_explicit(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            title="Archival decision",
            initial_statement="Some historical repositories may be redundant.",
            inquiry_id="archive-decision",
        )
    )
    inquiry = service.set_inquiry_decision(
        SetInquiryDecision(
            decision_to_support="Which repositories can be deleted safely?",
            minimum_evidence=(
                "A clean remote checkpoint and an inventory showing no unique artifacts."
            ),
            decision_change_criteria=[
                "Preserve a repository if it contains a unique executable validator.",
                "Delay deletion if unpushed or untracked work exists.",
            ],
            decision_owner="project-owner",
        )
    )
    first = service.add_claim(
        AddClaim(
            statement="The first repository is fully represented elsewhere.",
            level=ClaimLevel.OTHER,
            epistemic_layer=ClaimEpistemicLayer.DOCUMENTED_FACT,
        )
    )

    with pytest.raises(ValidationError, match="require source_refs"):
        service.review_claim(
            ReviewClaim(
                claim_id=first.claim_id,
                disposition=ClaimDisposition.ACCEPTED,
            )
        )
    with pytest.raises(ValidationError, match="confidence must be"):
        service.review_claim(ReviewClaim(claim_id=first.claim_id, confidence=1.5))

    first = service.review_claim(
        ReviewClaim(
            claim_id=first.claim_id,
            disposition=ClaimDisposition.ACCEPTED,
            confidence=0.8,
            source_refs=["inventory:repo-one@commit-a"],
            falsified_by=["A unique unpushed artifact is found."],
            decision_owner="project-owner",
        )
    )
    second = service.add_claim(
        AddClaim(
            statement="The first repository contains unique material.",
            level=ClaimLevel.OTHER,
            epistemic_layer=ClaimEpistemicLayer.SOURCE_CLAIM,
            disposition=ClaimDisposition.ACCEPTED,
            confidence=0.6,
            source_refs=["recovered-summary:curated-sessions"],
            conflicts_with=[first.claim_id],
            last_reviewed="2026-09-03",
            decision_owner="project-owner",
        )
    )

    audit = service.audit_rigor()
    assert inquiry.decision_to_support.startswith("Which repositories")
    assert second.conflicts_with == [first.claim_id]
    assert any(finding.code == "ACCEPTED_CLAIMS_CONFLICT" for finding in audit.findings)
    assert audit.structurally_valid is False

    synthesis = service.build_synthesis()["content"]
    assert "## Decision context" in synthesis
    assert "documented_fact; accepted" in synthesis
    assert "source_claim; accepted" in synthesis
    assert "inventory:repo-one@commit-a" in synthesis
    assert service.verify_ledger()["events"] == 6


def test_cli_exposes_decision_and_claim_provenance_contracts(
    tmp_path: Path, capsys
) -> None:
    workspace = tmp_path / "workspace"
    global_args = ["--workspace", str(workspace), "--json"]
    assert main([*global_args, "workspace", "init"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                *global_args,
                "inquiry",
                "create",
                "--id",
                "decision-contract",
                "--title",
                "Decision contract",
                "--statement",
                "A repository might be safe to delete.",
                "--decision",
                "Whether to delete it.",
                "--minimum-evidence",
                "A clean remote and unique-content inventory.",
                "--change-criterion",
                "Keep it if unpushed work exists.",
            ]
        )
        == 0
    )
    inquiry = json.loads(capsys.readouterr().out)["result"]
    assert inquiry["decision_to_support"] == "Whether to delete it."

    assert (
        main(
            [
                *global_args,
                "claim",
                "add",
                "--statement",
                "The remote contains the complete repository.",
                "--level",
                "other",
                "--epistemic-layer",
                "documented_fact",
                "--disposition",
                "accepted",
                "--source-ref",
                "git:origin/main@abc123",
                "--confidence",
                "0.95",
                "--last-reviewed",
                "2026-09-03T12:00:00Z",
            ]
        )
        == 0
    )
    claim = json.loads(capsys.readouterr().out)["result"]
    assert claim["epistemic_layer"] == "documented_fact"
    assert claim["source_refs"] == ["git:origin/main@abc123"]


def test_audit_detects_corrupted_claim_spine() -> None:
    inquiry = Inquiry(
        inquiry_id="corrupted",
        title="Corrupted spine",
        initial_statement="Can invalid references be detected?",
        created_at="2026-09-03T12:00:00Z",
        decision_to_support="Whether the claim graph is usable.",
        minimum_evidence="A clean structural audit.",
        decision_change_criteria=["Reject it if dependencies are cyclic."],
        decision_owner="project-owner",
    )
    first = Claim(
        claim_id="clm-first",
        statement="The second claim supports this one.",
        level=ClaimLevel.OTHER,
        created_at="2026-09-03T12:00:00Z",
        parent_claims=["clm-second"],
    )
    second = Claim(
        claim_id="clm-second",
        statement="This is an accepted fact without a traceable source.",
        level=ClaimLevel.OTHER,
        created_at="2026-09-03T12:00:00Z",
        parent_claims=["clm-first"],
        epistemic_layer=ClaimEpistemicLayer.DOCUMENTED_FACT,
        disposition=ClaimDisposition.ACCEPTED,
        last_reviewed="2026-09-03T12:00:00Z",
        decision_owner="project-owner",
    )

    audit = audit_research_state(
        inquiry=inquiry,
        claims=[first, second],
        hypotheses=[],
        evidence=[],
        datasets=[],
        protocols=[],
        runs=[],
    )
    codes = {finding.code for finding in audit.findings}
    assert "CLAIM_DEPENDENCY_CYCLE" in codes
    assert "SOURCE_GROUNDED_CLAIM_WITHOUT_SOURCE" in codes
    assert audit.structurally_valid is False
