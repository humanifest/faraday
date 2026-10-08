"""Read-only, literal intake for a research question.

This module does not infer answers from prose or write canonical records.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from research_machine.addons.execution import (
    _read_csv,
    _unit_structure,
    validate_measurement_values,
)
from research_machine.domain.errors import ValidationError


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

GUIDE_UNAVAILABLE_CAPABILITIES = {
    "live_model": "not_configured",
    "live_connector": "not_configured",
    "live_instrument": "not_configured",
    "arbitrary_statistics": "unsupported",
    "domain_specific_validity": "unsupported",
    "authenticated_reviewer": "not_configured",
    "metamaps_compilation": "not_configured",
    "concurrent_writes": "unsupported",
}


def guide_unavailable_capability(capability: str) -> dict[str, Any]:
    """Expose an unavailable boundary without probing or invoking it."""
    if capability not in GUIDE_UNAVAILABLE_CAPABILITIES:
        raise ValueError("unknown guide capability")
    return {
        "capability": capability,
        "status": GUIDE_UNAVAILABLE_CAPABILITIES[capability],
        "todo": f"docs/ai-science-guide/TODO.md#{capability.replace('_', '-')}",
        "fallback_used": False,
        "external_call_performed": False,
        "canonical_write_performed": False,
        "grants_authority": False,
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


def preview_csv_data(
    path: Path, spec: dict[str, Any], *, expected_sha256: str | None = None
) -> dict[str, Any]:
    """Inventory one CSV byte snapshot without registering it as a dataset."""
    try:
        if not path.is_file():
            raise ValidationError("guide data input is not a file")
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValidationError("guide data preview is limited to 16 MiB")
        content = path.read_bytes()
    except OSError as exc:
        raise ValidationError("guide data input could not be read") from exc
    if len(content) > 16 * 1024 * 1024:
        raise ValidationError("guide data preview is limited to 16 MiB")
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValidationError("guide data input bytes do not match expected SHA-256")
    rows = _read_csv(content)
    if spec.get("study_design") != "independent_groups":
        raise ValidationError("guide data preview currently supports independent_groups only")
    for key in ("unit_column", "group_column", "outcome_column"):
        value = spec.get(key)
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValidationError(f"guide data {key} must be an exact non-blank column")
        if value not in rows[0]:
            raise ValidationError(f"guide data {key} is absent from the CSV")
    if len({spec[key].casefold() for key in ("unit_column", "group_column", "outcome_column")}) != 3:
        raise ValidationError("guide data unit, group, and outcome columns must be distinct")
    definitions = spec.get("measurement_definitions")
    if not isinstance(definitions, list) or not definitions:
        raise ValidationError("guide data requires executable measurement definitions")

    issues: list[str] = []
    try:
        unit_structure = _unit_structure(spec, rows)
        if unit_structure["repeated_unit_count"]:
            issues.append("repeated independent-unit identifiers")
    except ValidationError as exc:
        unit_structure = None
        issues.append(str(exc))
    if any(value is None for row in rows for value in row.values()):
        measurements = None
        issues.append("CSV row has fewer fields than the header")
    else:
        try:
            measurements = validate_measurement_values(rows, definitions)
        except ValidationError as exc:
            measurements = None
            issues.append(str(exc))
    groups = spec.get("groups")
    if not isinstance(groups, list) or len(groups) != 2 or any(
        not isinstance(group, str) or not group or group != group.strip()
        for group in groups
    ) or len(set(groups)) != 2:
        issues.append("guide data requires two distinct ordered group labels")
    else:
        observed_groups = {row[spec["group_column"]] for row in rows}
        if observed_groups - set(groups):
            issues.append("observed group labels are outside the declared comparison")

    measure_by_column = (
        {item["data_column"]: item for item in measurements["measurements"]}
        if measurements is not None else {}
    )
    if spec["outcome_column"] not in measure_by_column:
        issues.append("primary outcome lacks a passing executable measurement check")
    columns = []
    for name in rows[0]:
        role = (
            "independent_unit_identity" if name == spec["unit_column"]
            else "comparison_label" if name == spec["group_column"]
            else "primary_outcome" if name == spec["outcome_column"]
            else "unresolved"
        )
        checked = measure_by_column.get(name)
        columns.append({
            "name": name,
            "role": role,
            "scale_type": checked["scale_type"] if checked else None,
            "observed_count": checked["observed_count"] if checked else None,
            "missing_count": checked["missing_count"] if checked else None,
        })
    return {
        "preview_version": 1,
        "raw_sha256": digest,
        "raw_size_bytes": len(content),
        "row_count": len(rows),
        "unit_count": unit_structure["unit_count"] if unit_structure else None,
        "columns": columns,
        "quality_issues": issues,
        "source_route": "local_file_preview",
        "role": "unregistered_input",
        "lineage": [],
        "readiness_gaps": [
            "canonical_registration_missing",
            "source_authority_unverified",
            "measurement_custody_unverified",
            "measurement_validity_unverified",
            *(["data_quality_issues"] if issues else []),
        ],
        "scientific_evidence_eligible": False,
        "canonical_write_performed": False,
    }
