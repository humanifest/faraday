"""G03 competing-model proposals use existing review and hypothesis boundaries."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import CreateInquiry, ProposeHypothesis
from research_machine.application.service import ResearchService
from research_machine.collaboration.proposal import (
    create_context_snapshot,
    validate_collaborator_proposal,
    verify_collaborator_proposal_record,
)
from research_machine.domain.errors import ValidationError


_MODELS = (
    (
        "null",
        "No decision-relevant change exists in the target comparison.",
        "A prespecified held-out comparison would fall within the decision-neutral range.",
        "A precise held-out estimate lies outside the prespecified neutral range.",
    ),
    (
        "measurement-error",
        "A measurement artifact could create the apparent contrast.",
        "A blinded reference measure would shrink the apparent contrast.",
        "The contrast persists on a calibrated independent measure.",
    ),
    (
        "selection-confounding",
        "Selection into the groups could account for the apparent contrast.",
        "A prospectively balanced comparison would shrink the apparent contrast.",
        "The contrast persists under a prespecified balance check.",
    ),
    (
        "user-favored",
        "The treatment could change the measured outcome.",
        "A prospectively assigned comparison would show a directional outcome change.",
        "A precise prospectively assigned comparison is incompatible with a meaningful change.",
    ),
)


def _proposal(context_hash: str, purpose: str, inquiry_ref: str) -> dict:
    suggestions = [
        {
            "suggestion_id": label,
            "kind": "hypothesis",
            "statement": statement,
            "rationale": "Candidate explanation for a future, separately reviewed test.",
            "uncertainty": "The synthetic inquiry has no evidentiary result.",
            "evidence_refs": [inquiry_ref],
            "falsification_conditions": [falsifier],
            "next_test": prediction,
            "authority": "review_only",
        }
        for label, statement, prediction, falsifier in _MODELS
    ]
    return {
        "proposal_version": 1,
        "proposal_id": "guide-models-synthetic-v1",
        "context_sha256": context_hash,
        "generated_by": {
            "kind": "llm", "provider": "synthetic-fixture", "model": "fixed-response",
        },
        "purpose": purpose,
        "summary": "Four candidate models need prospective discrimination.",
        "uncertainty": "The inquiry and fabricated rows do not select a model.",
        "competing_explanations": [
            {"statement": item[1], "context_refs": [inquiry_ref]}
            for item in _MODELS if item[0] != "user-favored"
        ],
        "disconfirming_evidence": [{
            "statement": "A preregistered result could weaken more than one candidate.",
            "context_refs": [inquiry_ref],
        }],
        "limitations": [{
            "statement": "The proposed models are untested in a real population.",
            "context_refs": [inquiry_ref],
        }],
        "suggestions": suggestions,
    }


def test_competing_models_remain_review_only_until_explicit_service_route(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    service = ResearchService(FileSystemRepository(workspace), actor="guide-fixture")
    service.init_workspace()
    service.create_inquiry(CreateInquiry(
        "Synthetic model comparison",
        "Could a treatment change an outcome in fabricated units?",
        inquiry_id="guide-models-v1",
    ))
    before = service.show_inquiry()
    purpose = "Compare synthetic candidate explanations"
    snapshot = create_context_snapshot(
        service.collaborator_context(purpose=purpose), tmp_path / "context"
    )
    inquiry_ref = "inquiry:guide-models-v1"
    proposal = _proposal(snapshot["context_sha256"], purpose, inquiry_ref)
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(json.dumps(proposal), encoding="utf-8")

    result = validate_collaborator_proposal(
        Path(snapshot["context_file"]), snapshot["context_sha256"],
        proposal_file, tmp_path / "validated",
    )
    record = json.loads(Path(result["record_file"]).read_text(encoding="utf-8"))
    assert result["status"] == "pending_human_review"
    assert record["canonical_writes_performed"] is False
    assert record["authorized_actions"] == []
    assert verify_collaborator_proposal_record(
        Path(result["record_file"]), result["record_sha256"]
    )["record_status"] == "pending_human_review"
    assert {item["suggestion_id"] for item in record["proposal"]["suggestions"]} == {
        item[0] for item in _MODELS
    }
    assert service.show_inquiry() == before

    # Only this explicit canonical service call creates a hypothesis. The
    # proposal record does not supply approval or activation authority.
    suggestions = {item["suggestion_id"]: item for item in record["proposal"]["suggestions"]}
    favored = suggestions["user-favored"]
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement=favored["statement"],
        generated_by="synthetic-guide-fixture",
        source_context=favored["evidence_refs"],
        observable_prediction=favored["next_test"],
        null_model=suggestions["null"]["statement"],
        competing_models=[
            suggestions["measurement-error"]["statement"],
            suggestions["selection-confounding"]["statement"],
        ],
        falsification_conditions=favored["falsification_conditions"],
    ))
    assert hypothesis.workflow_state.value == "unreviewed"
    assert hypothesis.observable_prediction == favored["next_test"]
    assert hypothesis.falsification_conditions == favored["falsification_conditions"]
    assert hypothesis.null_model == suggestions["null"]["statement"]
    assert len(hypothesis.competing_models) == 2
    assert all(
        item["workflow_state"] != "active"
        for item in service.show_inquiry()["hypotheses"]
    )
    assert service.verify_ledger()["valid"] is True


def test_empty_alternatives_and_claimed_approval_fail_closed(tmp_path: Path) -> None:
    service = ResearchService(FileSystemRepository(tmp_path / "workspace"), actor="guide-fixture")
    service.init_workspace()
    service.create_inquiry(CreateInquiry("Synthetic", "Could a treatment matter?"))
    purpose = "Compare candidate explanations"
    snapshot = create_context_snapshot(
        service.collaborator_context(purpose=purpose), tmp_path / "context"
    )
    inquiry_ref = "inquiry:" + service.show_inquiry()["inquiry"]["inquiry_id"]
    proposal = _proposal(snapshot["context_sha256"], purpose, inquiry_ref)
    proposal_file = tmp_path / "proposal.json"
    before = service.show_inquiry()

    no_alternatives = copy.deepcopy(proposal)
    no_alternatives["competing_explanations"] = []
    proposal_file.write_text(json.dumps(no_alternatives), encoding="utf-8")
    with pytest.raises(ValidationError, match="competing_explanations must be a non-empty array"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]), snapshot["context_sha256"],
            proposal_file, tmp_path / "no-alternatives",
        )
    assert not (tmp_path / "no-alternatives").exists()

    claimed_approval = copy.deepcopy(proposal)
    claimed_approval["suggestions"][0]["authority"] = "approved"
    proposal_file.write_text(json.dumps(claimed_approval), encoding="utf-8")
    with pytest.raises(ValidationError, match="authority must be review_only"):
        validate_collaborator_proposal(
            Path(snapshot["context_file"]), snapshot["context_sha256"],
            proposal_file, tmp_path / "claimed-approval",
        )
    assert not (tmp_path / "claimed-approval").exists()
    assert service.show_inquiry() == before
