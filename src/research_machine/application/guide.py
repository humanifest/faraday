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
from research_machine.domain.models import ProtocolStatus, QualityGateStatus


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
    "model_specific_next_experiment": "review_only",
    "paired_observational_packet": "review_only",
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


def preview_construct_validity(service: Any, protocol_id: str, *, run_id: str | None = None) -> dict[str, Any]:
    """Project frozen validity checks and recorded results without judging the construct."""
    protocol = service.get_protocol(protocol_id)
    if protocol.status is not ProtocolStatus.FROZEN:
        raise ValidationError("construct-validity preview requires a frozen protocol")
    run = service.get_run(run_id) if run_id is not None else None
    if run is not None and (run.protocol_id != protocol_id or run.protocol_hash != protocol.protocol_hash):
        raise ValidationError("construct-validity run does not match the frozen protocol")

    gates = {gate.gate_id: gate for gate in run.quality_gates} if run is not None else {}
    artifact_hashes = {item.sha256 for item in run.output_artifacts} if run is not None else set()
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    if not protocol.measurement_validity_checks:
        blockers.append("no_frozen_measurement_validity_checks")
    for check in protocol.measurement_validity_checks:
        gate = gates.get(check.assessment_gate_id)
        results = gate.details.get("measurement_validity_results") if gate is not None else None
        result = results.get(check.check_id) if isinstance(results, dict) else None
        evidence_sha256 = result.get("evidence_sha256") if isinstance(result, dict) else None
        source_bound = bool(
            isinstance(result, dict)
            and isinstance(evidence_sha256, str)
            and evidence_sha256 in artifact_hashes
            and result.get("selected_value_sha256")
        )
        consistent = bool(
            gate is not None and gate.status is QualityGateStatus.PASSED
            and isinstance(result, dict)
            and result.get("assessment_status") == "consistent_with_validity_claim"
            and source_bound
        )
        if not consistent:
            blockers.append(f"validity_check_not_source_bound_and_consistent:{check.check_id}")
        checks.append({
            "check_id": check.check_id,
            "measurement_id": check.measurement_id,
            "evidence_type": check.evidence_type,
            "validity_claim": check.validity_claim,
            "acceptance_criterion": check.acceptance_criterion,
            "failure_response": check.failure_response,
            "assessment_gate_id": check.assessment_gate_id,
            "gate_status": gate.status.value if gate is not None else "absent",
            "assessment_status": result.get("assessment_status", "absent") if isinstance(result, dict) else "absent",
            "evidence_sha256": evidence_sha256 if source_bound else None,
            "selected_value_sha256": result.get("selected_value_sha256") if source_bound else None,
            "source_bound": source_bound,
            "consistent_with_frozen_claim": consistent,
        })
    if run is None:
        blockers.append("no_recorded_run")
    if run is not None and not run.scientific_evidence_eligible:
        blockers.append("run_not_scientific_evidence_eligible")
    return {
        "protocol_id": protocol.protocol_id,
        "protocol_hash": protocol.protocol_hash,
        "run_id": run.run_id if run is not None else None,
        "checks": checks,
        "blocking_reasons": blockers,
        "validity_evidence_complete": not blockers,
        "status": "blocked" if blockers else "review_only",
        "supportive_interpretation_authorized": False,
        "construct_validity_proven": False,
        "canonical_write_performed": False,
        "notice": "A consistent diagnostic does not prove construct validity; independent scientific review is still required.",
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
    design = spec.get("study_design")
    method_id = spec.get("method")
    if design not in {"independent_groups", "paired"}:
        raise ValidationError("guide data preview supports independent_groups or paired only")
    if (design == "paired") != (method_id == "paired_mean_difference_ci"):
        raise ValidationError("guide data design conflicts with the selected paired method")
    identity_key = "pair_column" if design == "paired" else "unit_column"
    for key in (identity_key, "group_column", "outcome_column"):
        value = spec.get(key)
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValidationError(f"guide data {key} must be an exact non-blank column")
        if value not in rows[0]:
            raise ValidationError(f"guide data {key} is absent from the CSV")
    if len({spec[key].casefold() for key in (identity_key, "group_column", "outcome_column")}) != 3:
        raise ValidationError("guide data unit, group, and outcome columns must be distinct")
    definitions = spec.get("measurement_definitions")
    if not isinstance(definitions, list) or not definitions:
        raise ValidationError("guide data requires executable measurement definitions")

    issues: list[str] = []
    try:
        unit_structure = _unit_structure(spec, rows)
        if design == "independent_groups" and unit_structure["repeated_unit_count"]:
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
    groups_valid = isinstance(groups, list) and len(groups) == 2 and not any(
        not isinstance(group, str) or not group or group != group.strip()
        for group in groups
    ) and len({group.casefold() for group in groups}) == 2
    if not groups_valid:
        issues.append("guide data requires two distinct ordered group labels")
    else:
        observed_groups = {row[spec["group_column"]] for row in rows}
        if observed_groups - set(groups):
            issues.append("observed group labels are outside the declared comparison")

    design_inventory: dict[str, Any] = {"study_design": design}
    if design == "paired" and groups_valid and unit_structure is not None:
        pairs: dict[str, list[str]] = {}
        for row in rows:
            pairs.setdefault(row[spec[identity_key]], []).append(row[spec["group_column"]])
        duplicates = sum(any(labels.count(group) > 1 for group in groups)
                         for labels in pairs.values())
        incomplete = sum(sorted(labels) != sorted(groups) for labels in pairs.values())
        missing_outcomes = sum(not isinstance(row.get(spec["outcome_column"]), str)
                               or not row[spec["outcome_column"]].strip() for row in rows)
        design_inventory.update({
            "pair_column": spec[identity_key], "pair_count": len(pairs),
            "duplicate_pair_count": duplicates, "incomplete_pair_count": incomplete,
            "missing_outcome_count": missing_outcomes,
            "missing_data_policy": spec.get("missing_data_policy"),
            "claim_ceiling": "Within-pair descriptive preview; pairing and causal validity are unverified.",
        })
        if duplicates:
            issues.append("duplicate pair-group observations")
        if incomplete:
            issues.append("incomplete paired observations")
        if missing_outcomes:
            issues.append("paired outcome has missing values; implicit exclusions are unsupported")
    elif method_id == "adjusted_linear_effect":
        covariates = spec.get("covariate_columns")
        if (not isinstance(covariates, list) or not covariates
            or any(not isinstance(name, str) or not name or name != name.strip()
                   for name in covariates)
            or len({name.casefold() for name in covariates}) != len(covariates)
            or any(name not in rows[0] for name in covariates)
            or any(name.casefold() in {spec[key].casefold() for key in
                    (identity_key, "group_column", "outcome_column")} for name in covariates)):
            raise ValidationError("guide adjusted analysis requires distinct present covariate columns")
        missing = {name: sum(not isinstance(row.get(name), str) or not row[name].strip()
                             for row in rows) for name in covariates}
        missing_rows = sum(any(not isinstance(row.get(name), str) or not row[name].strip() for name in
                               [spec["outcome_column"], spec["group_column"], *covariates])
                           for row in rows)
        design_inventory.update({
            "covariate_columns": covariates, "covariate_missing_count": missing,
            "complete_case_exclusion_count": missing_rows,
            "missing_data_policy": spec.get("missing_data_policy"),
            "causal_identification_verified": False,
            "claim_ceiling": "Adjusted association preview; confounding and causal identification are unverified.",
        })
        if missing_rows and spec.get("missing_data_policy") != "complete_case":
            issues.append("missing adjusted-analysis values require an explicit complete_case policy")

    measure_by_column = (
        {item["data_column"]: item for item in measurements["measurements"]}
        if measurements is not None else {}
    )
    if spec["outcome_column"] not in measure_by_column:
        issues.append("primary outcome lacks a passing executable measurement check")
    columns = []
    for name in rows[0]:
        role = (
            ("pair_identity" if design == "paired" else "independent_unit_identity")
            if name == spec[identity_key]
            else "comparison_label" if name == spec["group_column"]
            else "primary_outcome" if name == spec["outcome_column"]
            else "adjustment_covariate" if name in design_inventory.get("covariate_columns", [])
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
        "design_inventory": design_inventory,
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


_MODEL_QUESTIONS = (
    ("null", "What would no decision-relevant change predict?"),
    ("measurement_error", "Could measurement or coding error create this pattern?"),
    ("selection_or_confounding", "Could selection or another variable explain it?"),
    ("user_explanation", "What would the user's explanation predict differently?"),
)


def preview_guide_packet(
    brief: dict[str, Any], *, design: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    analysis_spec: dict[str, Any] | None = None,
    measurement_spec: dict[str, Any] | None = None,
    method: dict[str, Any] | None = None,
    input_sha256: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compose existing read-only previews without inferring scientific answers."""
    intake = preview_question_intake(brief)
    issues: list[str] = []
    if design is not None:
        if design.get("brief_question") != intake["original_statement"]:
            issues.append("design question differs from the literal original statement")
        declared = design.get("declared", {})
        for field in ("outcome", "unit_of_observation", "decision", "comparison"):
            supplied = intake["supplied_fields"].get(field)
            if supplied is not None and declared.get(field) is not None and supplied != declared[field]:
                issues.append(f"design {field} conflicts with the literal brief")
        if design.get("error_findings"):
            issues.append("design scaffold has blocking findings")
    if data is not None and data["quality_issues"]:
        issues.append("CSV inventory has data-quality issues")
    if analysis_spec is not None:
        if method is None or method.get("method_id") != analysis_spec.get("method"):
            issues.append("analysis method is not an exact registered method")
        elif method.get("missing_spec_fields"):
            issues.append("analysis specification omits required method fields")
        if design is not None:
            declared = design.get("declared", {})
            for design_key, spec_key in (
                ("analysis_design", "study_design"),
                ("unit_id_column", "unit_column"),
                ("group_data_column", "group_column"),
                ("outcome_data_column", "outcome_column"),
                ("contrast_groups", "groups"),
            ):
                if declared.get(design_key) is not None and declared[design_key] != analysis_spec.get(spec_key):
                    issues.append(f"design {design_key} conflicts with analysis {spec_key}")
            definitions = (measurement_spec or {}).get("measurement_definitions", [])
            outcome_definition = next((item for item in definitions
                                       if item.get("data_column") == analysis_spec.get("outcome_column")), None)
            if outcome_definition is not None:
                for design_key, measurement_key in (("outcome_scale", "scale_type"), ("outcome_unit", "unit")):
                    if declared.get(design_key) is not None and declared[design_key] != outcome_definition.get(measurement_key):
                        issues.append(f"design {design_key} conflicts with measurement {measurement_key}")

    unresolved = list(intake["unresolved_fields"])
    if design is None:
        unresolved.append("prospective_design")
    if analysis_spec is None:
        unresolved.append("analysis_specification")
    if data is None:
        unresolved.append("observation_data")
    status = "blocked" if issues else "needs_clarification" if unresolved else "ready_for_review"
    next_steps = [
        {"route": "research design scaffold", "reason": "Review design assumptions before outcome use"}
        if design is None else
        {"route": "research design scaffold", "reason": "Resolve blocking design findings"}
        if design.get("error_findings") else None,
        {"route": "research guide data", "reason": "Inventory exact CSV bytes and custody gaps"}
        if data is None else None,
        {"route": "research collaborator context", "reason": "Bind competing-model proposals to a redacted inquiry context"},
        {"route": "research analysis run", "reason": "Exploratory only; requires separately trusted specification and input hashes"}
        if status == "ready_for_review" else None,
    ]
    return {
        "packet_version": 1,
        "authority": "review_only",
        "status": status,
        "original_statement": intake["original_statement"],
        "intake": intake,
        "design_preview": design,
        "data_preview": data,
        "method_preview": method,
        "competing_model_questions": [
            {"role": role, "question": question, "prediction_required": True,
             "falsifier_required": True, "asserts_explanation": False}
            for role, question in _MODEL_QUESTIONS
        ],
        "blocking_issues": issues,
        "unresolved_fields": unresolved,
        "next_steps": [step for step in next_steps if step is not None],
        "input_sha256": input_sha256 or {},
        "scientific_evidence_eligible": False,
        "canonical_write_performed": False,
        "analysis_performed": False,
    }


def validate_guide_run_packet(
    packet: dict[str, Any], *, specification_sha256: str,
    input_sha256: str, method_id: str,
) -> None:
    """Require an exact W01 review packet before exploratory computation."""
    for label, value in (("specification", specification_sha256), ("input", input_sha256)):
        if not isinstance(value, str) or len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValidationError(f"guide run {label} SHA-256 must be lowercase hex")
    if not isinstance(packet, dict) or packet.get("packet_version") != 1:
        raise ValidationError("guide run requires a version-1 guide packet")
    if (packet.get("authority") != "review_only"
        or packet.get("status") != "ready_for_review"
        or packet.get("blocking_issues") != []
        or packet.get("unresolved_fields") != []
        or packet.get("canonical_write_performed") is not False
        or packet.get("analysis_performed") is not False
        or packet.get("scientific_evidence_eligible") is not False):
        raise ValidationError("guide packet has unresolved checks or claims authority")
    hashes = packet.get("input_sha256")
    if not isinstance(hashes, dict) or (
        hashes.get("analysis_specification") != specification_sha256
        or hashes.get("data") != input_sha256
        or not hashes.get("brief")
        or not hashes.get("data_specification")
    ):
        raise ValidationError("guide packet does not bind the trusted specification and input bytes")
    inventory = packet.get("data_preview")
    if (not isinstance(inventory, dict)
        or inventory.get("raw_sha256") != input_sha256
        or inventory.get("quality_issues") != []
        or inventory.get("scientific_evidence_eligible") is not False):
        raise ValidationError("guide packet lacks a clean, non-evidentiary data inventory")
    method = packet.get("method_preview")
    if (not isinstance(method, dict)
        or method.get("method_id") != method_id
        or method.get("missing_spec_fields") != []):
        raise ValidationError("guide packet method differs from the executable specification")


_EXPLAINABLE_METHODS = {
    "independent_mean_difference_ci": ("mean_difference_first_minus_second", "confidence_interval"),
    "paired_mean_difference_ci": ("mean_difference_first_minus_second", "confidence_interval"),
    "adjusted_linear_effect": ("adjusted_mean_difference_first_minus_second", "robust_confidence_interval"),
}


def explain_guide_execution(
    packet: dict[str, Any], verified: dict[str, Any], *, packet_sha256: str,
    specification_sha256: str, input_sha256: str,
    implementation_sha256: str,
) -> dict[str, Any]:
    """Explain a byte-verified computation without promoting it to evidence."""
    receipt, result = verified["receipt"], verified["result"]
    method_id = result.get("method")
    validate_guide_run_packet(
        packet, specification_sha256=specification_sha256,
        input_sha256=input_sha256, method_id=method_id,
    )
    if (receipt.get("specification", {}).get("sha256") != specification_sha256
        or receipt.get("input", {}).get("sha256") != input_sha256
        or receipt.get("implementation", {}).get("sha256") != implementation_sha256
        or receipt.get("method") != method_id):
        raise ValidationError("guide execution receipt does not match packet, source, or current method bytes")
    if method_id not in _EXPLAINABLE_METHODS:
        raise ValidationError("guide explanation does not support this analysis method")
    body = result.get("result")
    if not isinstance(body, dict):
        raise ValidationError("guide analysis result body is missing")
    effect_key, interval_key = _EXPLAINABLE_METHODS[method_id]
    effect, interval = body.get(effect_key), body.get(interval_key)
    if (isinstance(effect, bool) or not isinstance(effect, (int, float))
        or not isinstance(interval, dict)
        or any(isinstance(interval.get(key), bool) or not isinstance(interval.get(key), (int, float))
               for key in ("lower", "upper"))):
        raise ValidationError("guide analysis lacks a numeric estimate and interval")
    lower, upper = interval["lower"], interval["upper"]
    if lower > effect or effect > upper:
        raise ValidationError("guide estimate lies outside its reported interval")
    interval_relation = "spans_zero" if lower <= 0 <= upper else "above_zero" if lower > 0 else "below_zero"
    return {
        "explanation_version": 1,
        "status": "exploratory_computation_only",
        "original_statement": packet["original_statement"],
        "packet_sha256": packet_sha256,
        "receipt_sha256": verified["receipt_sha256"],
        "method": method_id,
        "effect_estimate": {"value": effect, "field": effect_key,
                            "signed_contrast": result.get("contrast_groups", [])},
        "uncertainty": {"interval": interval, "relation_to_zero": interval_relation},
        "unit_counts": body.get("n_by_group", {"pairs": body.get("n_pairs")}),
        "exclusions": body.get("exclusion_report"),
        "assumptions": body.get("assumptions", []),
        "method_claim_ceiling": result["claim_ceiling"],
        "unresolved_fields": packet["unresolved_fields"],
        "unresolved_alternatives": packet["competing_model_questions"],
        "next_experiment": {
            "status": "needs_model_specific_predictions_and_review",
            "candidate": None,
            "questions": [
                "Which competing models make different predictions on a future independent sample?",
                "What measurement or selection check would weaken each model?",
                "What effect size, stopping rule, and safety constraints must be set before collection?",
            ],
            "discrimination_established": False,
        },
        "scientific_evidence_eligible": False,
        "canonical_write_performed": False,
        "confirmatory_plan_verified": False,
        "notice": "An interval's position relative to zero is a calculation, not scientific confirmation or a causal conclusion.",
    }


_NEXT_MODEL_ROLES = (
    "null", "measurement_error", "selection_or_confounding", "user_explanation",
)


def preview_next_experiment_candidate(
    packet: dict[str, Any], explanation: dict[str, Any],
    collaborator_record: dict[str, Any], candidate_spec: dict[str, Any], *,
    inquiry_ref: str, context_sha256: str, proposal_record_sha256: str,
    packet_sha256: str, receipt_sha256: str,
) -> dict[str, Any]:
    """Project a verified collaborator proposal into review-only next-test guidance."""
    expected_fields = {
        "candidate_version", "inquiry_ref", "proposal_id", "model_roles",
        "test_suggestion_id", "discrimination_criterion",
    }
    if not isinstance(candidate_spec, dict) or set(candidate_spec) != expected_fields:
        raise ValidationError("guide next candidate fields are incomplete or unknown")
    if candidate_spec["candidate_version"] != 1:
        raise ValidationError("guide next candidate_version must be 1")
    if (candidate_spec["inquiry_ref"] != inquiry_ref
        or not inquiry_ref.startswith("inquiry:")
        or candidate_spec["proposal_id"] != collaborator_record.get("proposal", {}).get("proposal_id")):
        raise ValidationError("guide next candidate differs from the current inquiry or proposal")
    if (packet.get("original_statement") != explanation.get("original_statement")
        or explanation.get("packet_sha256") != packet_sha256
        or explanation.get("receipt_sha256") != receipt_sha256
        or explanation.get("status") != "exploratory_computation_only"
        or explanation.get("next_experiment", {}).get("candidate") is not None
        or explanation.get("scientific_evidence_eligible") is not False
        or explanation.get("canonical_write_performed") is not False):
        raise ValidationError("guide next explanation is not bound to the reviewed packet and receipt")
    if (collaborator_record.get("status") != "pending_human_review"
        or collaborator_record.get("context_input", {}).get("sha256") != context_sha256
        or collaborator_record.get("authorized_actions") != []
        or collaborator_record.get("canonical_writes_performed") is not False
        or collaborator_record.get("scientific_evidence_eligible") is not False):
        raise ValidationError("guide next proposal record has no review-only context binding")
    roles = candidate_spec["model_roles"]
    if (not isinstance(roles, dict) or set(roles) != set(_NEXT_MODEL_ROLES)
        or any(not isinstance(value, str) or not value or value != value.strip()
               for value in roles.values())
        or len(set(roles.values())) != len(_NEXT_MODEL_ROLES)):
        raise ValidationError("guide next requires four distinct model suggestion IDs")
    test_id = candidate_spec["test_suggestion_id"]
    criterion = candidate_spec["discrimination_criterion"]
    if (not isinstance(test_id, str) or not test_id or test_id != test_id.strip()
        or test_id in roles.values()
        or not isinstance(criterion, str) or not criterion or criterion != criterion.strip()):
        raise ValidationError("guide next requires a separate test suggestion and criterion")
    suggestions = {item["suggestion_id"]: item
                   for item in collaborator_record["proposal"]["suggestions"]}
    test = suggestions.get(test_id)
    if (test is None or test["kind"] not in {"next_action", "design_revision"}
        or inquiry_ref not in test["evidence_refs"]):
        raise ValidationError("guide next test is not a grounded review-only action")
    models = []
    for role in _NEXT_MODEL_ROLES:
        suggestion = suggestions.get(roles[role])
        if (suggestion is None or suggestion["kind"] != "hypothesis"
            or suggestion["authority"] != "review_only"
            or inquiry_ref not in suggestion["evidence_refs"]
            or not suggestion["falsification_conditions"]):
            raise ValidationError(f"guide next {role} lacks a grounded prediction or falsifier")
        models.append({
            "role": role, "suggestion_id": suggestion["suggestion_id"],
            "model": suggestion["statement"], "prediction": suggestion["next_test"],
            "falsifiers": suggestion["falsification_conditions"],
        })
    distinct_predictions = len({item["prediction"].casefold() for item in models}) == len(models)
    return {
        "next_candidate_version": 1,
        "status": "review_only_candidate" if distinct_predictions else "inconclusive_predictions",
        "inquiry_ref": inquiry_ref,
        "context_sha256": context_sha256,
        "proposal_record_sha256": proposal_record_sha256,
        "packet_sha256": packet_sha256,
        "receipt_sha256": receipt_sha256,
        "candidate": ({
            "test_suggestion_id": test_id, "proposed_test": test["next_test"],
            "model_predictions": models,
            "proposed_discrimination_criterion": criterion,
        } if distinct_predictions else None),
        "discrimination_established": False,
        "prospective_plan_frozen": False,
        "independent_design_review_required": True,
        "ethics_review_required": True,
        "experiment_authorized": False,
        "scientific_evidence_eligible": False,
        "canonical_write_performed": False,
    }
