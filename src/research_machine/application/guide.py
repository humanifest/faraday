"""Read-only, literal intake for a research question.

This module does not infer answers from prose or write canonical records.
"""

from __future__ import annotations

from typing import Any


INTAKE_FIELDS = {
    "original_statement", "title", "population", "unit_of_observation",
    "outcome", "comparison", "time_window", "decision", "minimum_evidence",
    "decision_owner", "decision_change_criteria", "available_data_sources",
    "ethical_constraints",
}

_PROMPTS = {
    "title": "What title should identify this inquiry?",
    "population": "Which population does this question concern?",
    "unit_of_observation": "What is the independent unit of observation?",
    "outcome": "What observable outcome would answer the question?",
    "comparison": "What comparison, if any, is intended?",
    "time_window": "Over what time window should the outcome be measured?",
    "decision": "What practical decision should the evidence support?",
    "minimum_evidence": "What minimum evidence would inform that decision?",
    "decision_owner": "Who owns the decision?",
    "decision_change_criteria": "What observation would change the decision?",
    "available_data_sources": "What data are available, and where did they come from?",
    "ethical_constraints": "What ethical, consent, privacy, or data-rights constraints apply?",
}

_LIST_FIELDS = {
    "decision_change_criteria", "available_data_sources", "ethical_constraints",
}


def preview_question_intake(brief: dict[str, Any]) -> dict[str, Any]:
    """Return only user-supplied values, unresolved fields, and proposed commands."""
    if not isinstance(brief, dict):
        raise ValueError("guide intake brief must be an object")
    unknown = sorted(set(brief) - INTAKE_FIELDS)
    if unknown:
        raise ValueError("unknown guide intake fields: " + ", ".join(unknown))
    statement = brief.get("original_statement")
    if not isinstance(statement, str) or not statement or statement != statement.strip():
        raise ValueError("original_statement must be non-blank, unpadded text")

    supplied: dict[str, str | list[str] | None] = {}
    unresolved: list[str] = []
    for field in _PROMPTS:
        value = brief.get(field)
        if field in _LIST_FIELDS:
            if value is not None and (
                not isinstance(value, list)
                or any(not isinstance(item, str) or not item or item != item.strip() for item in value)
            ):
                raise ValueError(f"{field} must be an array of non-blank, unpadded strings")
            if field == "decision_change_criteria" and value is not None:
                folded = [item.casefold() for item in value]
                if len(folded) != len(set(folded)):
                    raise ValueError("decision_change_criteria must contain distinct statements")
            supplied[field] = list(value) if value else None
        else:
            if value is not None and (
                not isinstance(value, str) or not value or value != value.strip()
            ):
                raise ValueError(f"{field} must be non-blank, unpadded text")
            supplied[field] = value
        if supplied[field] is None:
            unresolved.append(field)

    proposed_commands: list[dict[str, Any]] = []
    if supplied["title"] is not None:
        proposed_commands.append({
            "service_command": "CreateInquiry",
            "arguments": {
                "title": supplied["title"],
                "initial_statement": statement,
                "decision_to_support": supplied["decision"] or "",
                "minimum_evidence": supplied["minimum_evidence"] or "",
                "decision_change_criteria": supplied["decision_change_criteria"] or [],
                "decision_owner": supplied["decision_owner"] or "",
            },
        })
        proposed_commands.extend({
            "service_command": "AddQuestion",
            "arguments": {"text": _PROMPTS[field]},
        } for field in unresolved if field != "title")

    return {
        "preview_version": 1,
        "authority": "review_only",
        "original_statement": statement,
        "supplied_fields": supplied,
        "unresolved_fields": unresolved,
        "clarifying_questions": [
            {"field": field, "text": _PROMPTS[field]} for field in unresolved
        ],
        "proposed_commands": proposed_commands,
        "canonical_write_performed": False,
    }
