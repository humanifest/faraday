"""Provider-neutral guided revisions using the canonical proposal write path."""
from __future__ import annotations

import json
from typing import Any

from research_machine.application.commands import (
    AddClaim,
    AddQuestion,
    ProposeHypothesis,
    SetInquiryDecision,
)
from research_machine.application.service import ResearchService
from research_machine.design.scaffold import (
    inquiry_decision_commitments,
    scaffold_design,
)
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import ClaimLevel


def _complete_canonical_decision_commitments(
    brief: dict[str, Any]
) -> dict[str, Any] | None:
    criteria = brief.get("decision_change_criteria", [])
    minimum_evidence = brief.get("minimum_evidence", "")
    decision_owner = brief.get("decision_owner", "")
    decision = brief.get("decision", "")
    if not (
        isinstance(decision, str)
        and isinstance(minimum_evidence, str)
        and isinstance(decision_owner, str)
        and isinstance(criteria, list)
        and criteria
    ):
        return None
    if not minimum_evidence.strip() or not decision_owner.strip():
        return None
    texts = [decision, minimum_evidence, decision_owner]
    for criterion in criteria:
        if not isinstance(criterion, str) or not criterion.strip():
            return None
        texts.append(criterion)
    if any(text != text.strip() for text in texts):
        return None
    criteria_keys = [criterion.casefold() for criterion in criteria]
    if len(set(criteria_keys)) != len(criteria_keys):
        return None
    return inquiry_decision_commitments(brief)


def revise_design(
    service: ResearchService, brief: dict[str, Any], *, hypothesis_id: str,
    reason: str, inquiry_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("a non-blank revision reason is required")
    if reason != reason.strip():
        raise ValidationError("revision reason must be canonical without surrounding whitespace")
    scaffold = scaffold_design(brief)
    proposal = scaffold["artifacts"]["hypothesis-proposal.json"]
    state = service.show_inquiry(inquiry_id)
    # Inquiry-wide, deliberately not just parent-linked: other outcomes in the
    # same inquiry can inform a revision too. Absence is not proof of blinding.
    prior_records = {
        collection: sorted(item[key] for item in state[collection])
        for collection, key in (
            ("datasets", "dataset_id"), ("runs", "run_id"),
            ("evidence", "evidence_id"), ("protocols", "protocol_id"),
        )
    }
    chronology = {
        "scope": "registered_inquiry_records_before_revision",
        "prior_records": prior_records,
        "observation_exposure": "unknown",
        "notice": "Registration history does not establish what the researcher saw. This revision is not a preregistration or a protocol amendment; existing observations cannot become prospective tests by revising a hypothesis.",
    }
    # Retain the input and audit in the same canonical record/event as the new
    # proposal. No second mutable draft store or inherited review decision.
    provenance = json.dumps({
        "record_type": "guided_design_revision", "version": 2,
        "reason": reason, "brief": brief,
        "scaffold": scaffold,
        "chronology": chronology,
    }, sort_keys=True, ensure_ascii=False, allow_nan=False)
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement=proposal["statement"], generated_by="guided_design_revision",
        lineage=[hypothesis_id], source_context=[provenance],
        scope=proposal["scope"],
        observable_prediction=proposal["observable_prediction"],
        null_model=proposal["null_model"],
        competing_models=proposal["competing_models"],
        primary_estimand=proposal["primary_estimand"],
        contrast_definition=proposal["contrast_definition"],
        contrast_groups=proposal["contrast_groups"],
        expected_effect_direction=proposal["expected_effect_direction"],
        falsification_conditions=proposal["falsification_conditions"],
    ), state["inquiry"]["inquiry_id"])
    decision_commitments = _complete_canonical_decision_commitments(brief)
    if decision_commitments is not None:
        service.set_inquiry_decision(
            SetInquiryDecision(
                decision_to_support=decision_commitments["decision_to_support"],
                minimum_evidence=decision_commitments["minimum_evidence"],
                decision_change_criteria=decision_commitments[
                    "decision_change_criteria"
                ],
                decision_owner=decision_commitments["decision_owner"],
            ),
            state["inquiry"]["inquiry_id"],
        )
    for question in brief.get("ambiguity_questions", []):
        service.add_question(
            AddQuestion("[Guided revision ambiguity] " + question),
            state["inquiry"]["inquiry_id"],
        )
    for claim in brief.get("claim_boundaries", []):
        service.add_claim(
            AddClaim(
                statement=claim["statement"],
                level=ClaimLevel(claim["level"]),
                scope=claim["scope"],
            ),
            state["inquiry"]["inquiry_id"],
        )
    return {
        "hypothesis": hypothesis.to_dict(), "scaffold": scaffold,
        "chronology": chronology,
        "notice": "New unreviewed proposal. Earlier hypotheses, protocols, and evidence are unchanged; no approval or evidence was inherited.",
    }
