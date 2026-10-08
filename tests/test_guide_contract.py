"""Synthetic guide-client characterization of Faraday's existing proposal boundary."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import AddQuestion, CreateInquiry
from research_machine.application.service import ResearchService
from research_machine.collaboration.proposal import (
    create_context_snapshot,
    validate_collaborator_proposal,
    verify_collaborator_proposal_record,
)
from research_machine.domain.errors import ValidationError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "guide" / "inquiry-plan.json"


def _proposal(context_sha256: str, purpose: str, inquiry_ref: str) -> dict:
    return {
        "proposal_version": 1,
        "proposal_id": "guide-fixture-proposal-1",
        "context_sha256": context_sha256,
        "generated_by": {
            "kind": "llm",
            "provider": "synthetic-fixture",
            "model": "fixed-response",
        },
        "purpose": purpose,
        "summary": "A later study needs a measured outcome and an alternative model.",
        "uncertainty": "The four synthetic rows establish no result about a population.",
        "competing_explanations": [{
            "statement": "Measurement error could create an apparent contrast.",
            "context_refs": [inquiry_ref],
        }],
        "disconfirming_evidence": [{
            "statement": "A matched control measurement could weaken that account.",
            "context_refs": [inquiry_ref],
        }],
        "limitations": [{
            "statement": "Only the frozen synthetic inquiry context was read.",
            "context_refs": [inquiry_ref],
        }],
        "suggestions": [{
            "suggestion_id": "question-1",
            "kind": "question",
            "statement": "What would count as a meaningful outcome change?",
            "rationale": "The decision threshold is unresolved.",
            "uncertainty": "No threshold follows from the synthetic rows.",
            "evidence_refs": [inquiry_ref],
            "falsification_conditions": [
                "A prespecified threshold makes this question unnecessary."
            ],
            "next_test": "Ask the decision owner to define the smallest effect of interest.",
            "authority": "review_only",
        }],
    }


def test_guide_reuses_hash_bound_read_only_collaborator_contract(tmp_path: Path) -> None:
    plan = json.loads(FIXTURE.read_text(encoding="utf-8"))
    workspace = tmp_path / "workspace"
    service = ResearchService(FileSystemRepository(workspace), actor="guide-fixture")
    service.init_workspace()
    service.create_inquiry(CreateInquiry(
        "Synthetic guide proposal boundary",
        plan["original_question"],
        inquiry_id="guide-contract-v1",
        decision_to_support=plan["decision"],
    ))
    service.add_question(AddQuestion("Which measured change matters?"))
    before = service.show_inquiry()
    purpose = "Clarify a synthetic guide inquiry"
    context = service.collaborator_context(purpose=purpose)
    assert context["context_version"] == 2
    assert context["inquiry"]["initial_statement"] == plan["original_question"]
    assert context["write_boundary"]["context_is_read_only"] is True
    assert context["write_boundary"]["provider_required"] is False
    assert context["dataset_inventory"]["registered_dataset_count"] == 0
    jsonschema.validate(
        context,
        json.loads((ROOT / "schemas" / "collaborator-context.schema.json").read_text()),
    )

    snapshot = create_context_snapshot(context, tmp_path / "context")
    inquiry_ref = "inquiry:guide-contract-v1"
    assert inquiry_ref in {item["ref"] for item in context["context_reference_index"]}
    proposal = _proposal(snapshot["context_sha256"], purpose, inquiry_ref)
    jsonschema.validate(
        proposal,
        json.loads((ROOT / "schemas" / "collaborator-proposal.schema.json").read_text()),
    )
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps(proposal), encoding="utf-8")
    result = validate_collaborator_proposal(
        Path(snapshot["context_file"]), snapshot["context_sha256"],
        proposal_file, tmp_path / "validated",
    )
    record = json.loads(Path(result["record_file"]).read_text(encoding="utf-8"))
    assert record["status"] == "pending_human_review"
    assert record["canonical_writes_performed"] is False
    assert record["model_invoked_by_faraday"] is False
    assert record["scientific_evidence_eligible"] is False
    assert record["authorized_actions"] == []
    assert verify_collaborator_proposal_record(
        Path(result["record_file"]), result["record_sha256"]
    )["record_status"] == "pending_human_review"
    assert service.show_inquiry() == before
    assert service.verify_ledger()["valid"] is True

    with pytest.raises(ValidationError, match="trusted SHA-256"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]), "0" * 64,
            proposal_file, tmp_path / "wrong-context",
        )
    unknown = copy.deepcopy(proposal)
    unknown["suggestions"][0]["evidence_refs"] = ["inquiry:invented"]
    proposal_file.write_text(json.dumps(unknown), encoding="utf-8")
    with pytest.raises(ValidationError, match="not present in the frozen context"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]), snapshot["context_sha256"],
            proposal_file, tmp_path / "unknown-ref",
        )
    unauthorized = copy.deepcopy(proposal)
    unauthorized["suggestions"][0]["authority"] = "approved"
    proposal_file.write_text(json.dumps(unauthorized), encoding="utf-8")
    with pytest.raises(ValidationError, match="authority must be review_only"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]), snapshot["context_sha256"],
            proposal_file, tmp_path / "unauthorized",
        )
    assert not (tmp_path / "wrong-context").exists()
    assert not (tmp_path / "unknown-ref").exists()
    assert not (tmp_path / "unauthorized").exists()
