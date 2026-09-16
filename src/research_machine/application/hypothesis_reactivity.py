"""Hypothesis disclosure / reactivity protocol contract.

Freeze who knows what, when, and which competing process models that disclosure
would distinguish. Permit auditable assessment against those frozen predictions.
Refuse silent rewrite of the model set and refuse to treat design
non-distinguishability as support for an unobserved explanation.
"""

from __future__ import annotations

import re
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    CompetingProcessModel,
    DecisionLossAssumptions,
    ExperimentProtocol,
    HypothesisDisclosureEvent,
    HypothesisReactivityPlan,
    QualityGateResult,
    QualityGateStatus,
)

DISCLOSURE_STATEMENT_ROLES = frozenset(
    {
        "true_hypothesis",
        "decoy_hypothesis",
        "cover_story",
        "withheld",
        "other",
    }
)
DISCLOSURE_TIMING_ANCHORS = frozenset(
    {
        "pre_exposure",
        "at_exposure",
        "post_exposure",
        "analysis",
        "other",
    }
)
PROCESS_MODEL_DISTINGUISHABILITY = frozenset(
    {
        "distinguishable",
        "not_distinguishable_by_this_design",
    }
)
REACTIVITY_ASSESSMENT_STATUSES = frozenset(
    {
        "models_discriminated",
        "compatible_with_multiple",
        "not_distinguishable_by_design",
        "inconclusive",
    }
)

_DETECTION_CLAIM_MARKERS = (
    "currently detected",
    "currently surveilled",
    "proves detection",
    "confirms detection",
    "establishes detection",
    "detected and concealing is true",
    "they are on to me",
    "they are on to you",
)


def _reject_detection_as_finding(text: str, field_name: str) -> str:
    from research_machine.application.policies import (
        require_canonical_bounded_report_text,
    )

    bounded = require_canonical_bounded_report_text(text, field_name)
    lowered = bounded.casefold()
    # Allow explicit denials in notices; reject affirmative detection findings.
    if "not evidence" in lowered or "not a finding" in lowered:
        affirmative = (
            "is currently detected" in lowered
            or "are currently detected" in lowered
            or "currently surveilled" in lowered
            or "proves detection" in lowered
            or "confirms detection" in lowered
        )
        if not affirmative:
            return bounded
    for marker in _DETECTION_CLAIM_MARKERS:
        if marker in lowered:
            raise ValidationError(
                f"{field_name} cannot record detection, surveillance, or an "
                "observer as a finding; keep model compatibility, evidence "
                "discrimination, and decisions separate"
            )
    if re.search(r"\bobserver exists\b", lowered) and "not" not in lowered:
        raise ValidationError(
            f"{field_name} cannot record detection, surveillance, or an "
            "observer as a finding; keep model compatibility, evidence "
            "discrimination, and decisions separate"
        )
    return bounded


def validate_hypothesis_reactivity_plan_freeze(
    protocol: ExperimentProtocol,
    *,
    quality_requirement_set: set[str],
    occupied_gate_ids: set[str],
) -> None:
    from research_machine.application.policies import (
        require_canonical_bounded_report_text,
        require_canonical_text,
        require_unique_canonical_text_list,
    )

    plan = protocol.hypothesis_reactivity_plan
    if plan is None:
        return
    if not isinstance(plan, HypothesisReactivityPlan):
        raise ValidationError(
            "hypothesis_reactivity_plan must be a HypothesisReactivityPlan value"
        )
    require_canonical_text(plan.plan_id, "hypothesis_reactivity_plan.plan_id")
    events = plan.disclosure_schedule
    if not events:
        raise ValidationError(
            "hypothesis_reactivity_plan requires a non-empty disclosure_schedule"
        )
    event_ids: list[str] = []
    for index, event in enumerate(events):
        if not isinstance(event, HypothesisDisclosureEvent):
            raise ValidationError(
                "hypothesis_reactivity_plan.disclosure_schedule entries must be "
                "HypothesisDisclosureEvent values"
            )
        prefix = f"hypothesis_reactivity_plan.disclosure_schedule[{index}]"
        event_ids.append(require_canonical_text(event.event_id, f"{prefix}.event_id"))
        require_canonical_text(event.audience, f"{prefix}.audience")
        require_canonical_bounded_report_text(
            event.statement_disclosed, f"{prefix}.statement_disclosed"
        )
        role = require_canonical_text(event.statement_role, f"{prefix}.statement_role")
        if role not in DISCLOSURE_STATEMENT_ROLES:
            raise ValidationError(
                f"{prefix}.statement_role is unsupported"
            )
        anchor = require_canonical_text(
            event.timing_anchor, f"{prefix}.timing_anchor"
        )
        if anchor not in DISCLOSURE_TIMING_ANCHORS:
            raise ValidationError(f"{prefix}.timing_anchor is unsupported")
        require_canonical_bounded_report_text(
            event.timing_description, f"{prefix}.timing_description"
        )
    if len(set(event_ids)) != len(event_ids):
        raise ValidationError(
            "hypothesis_reactivity_plan.disclosure_schedule event_id values must be unique"
        )

    models = plan.process_models
    if len(models) < 2:
        raise ValidationError(
            "hypothesis_reactivity_plan requires at least two process_models"
        )
    model_ids: list[str] = []
    distinguishable_count = 0
    for index, model in enumerate(models):
        if not isinstance(model, CompetingProcessModel):
            raise ValidationError(
                "hypothesis_reactivity_plan.process_models entries must be "
                "CompetingProcessModel values"
            )
        prefix = f"hypothesis_reactivity_plan.process_models[{index}]"
        model_ids.append(require_canonical_text(model.model_id, f"{prefix}.model_id"))
        require_canonical_bounded_report_text(model.statement, f"{prefix}.statement")
        require_canonical_bounded_report_text(
            model.observable_prediction, f"{prefix}.observable_prediction"
        )
        require_canonical_bounded_report_text(
            model.comparison_rule, f"{prefix}.comparison_rule"
        )
        distinguishability = require_canonical_text(
            model.distinguishability, f"{prefix}.distinguishability"
        )
        if distinguishability not in PROCESS_MODEL_DISTINGUISHABILITY:
            raise ValidationError(f"{prefix}.distinguishability is unsupported")
        rationale = model.non_distinguishability_rationale
        if distinguishability == "not_distinguishable_by_this_design":
            require_canonical_bounded_report_text(
                rationale, f"{prefix}.non_distinguishability_rationale"
            )
        elif isinstance(rationale, str) and rationale.strip():
            raise ValidationError(
                f"{prefix}.non_distinguishability_rationale must be empty when "
                "distinguishability is distinguishable"
            )
        else:
            distinguishable_count += 1
        require_unique_canonical_text_list(
            model.linked_hypothesis_ids, f"{prefix}.linked_hypothesis_ids"
        )
    if len(set(model_ids)) != len(model_ids):
        raise ValidationError(
            "hypothesis_reactivity_plan.process_models model_id values must be unique"
        )
    require_canonical_bounded_report_text(
        plan.likelihood_comparison_rule,
        "hypothesis_reactivity_plan.likelihood_comparison_rule",
    )
    assessment_gate_id = require_canonical_text(
        plan.assessment_gate_id, "hypothesis_reactivity_plan.assessment_gate_id"
    )
    if assessment_gate_id not in quality_requirement_set:
        raise ValidationError(
            "hypothesis_reactivity_plan assessment_gate_id must be a required "
            "protocol quality gate"
        )
    if assessment_gate_id in occupied_gate_ids:
        raise ValidationError(
            "hypothesis_reactivity_plan assessment gate must be dedicated and "
            "cannot be reused for controls, causal assumptions, missingness, "
            "validity, or canary checks"
        )
    require_canonical_bounded_report_text(
        plan.ethical_disclosure, "hypothesis_reactivity_plan.ethical_disclosure"
    )
    require_canonical_bounded_report_text(
        plan.limitations, "hypothesis_reactivity_plan.limitations"
    )
    if distinguishable_count == 0 and "not distinguishable" not in plan.limitations.casefold():
        raise ValidationError(
            "hypothesis_reactivity_plan.limitations must state that no process "
            "model is distinguishable by this design when every model is marked "
            "not_distinguishable_by_this_design"
        )
    assumptions = plan.decision_loss_assumptions
    if assumptions is not None:
        if not isinstance(assumptions, DecisionLossAssumptions):
            raise ValidationError(
                "hypothesis_reactivity_plan.decision_loss_assumptions must be a "
                "DecisionLossAssumptions value"
            )
        require_canonical_bounded_report_text(
            assumptions.false_reassurance_cost,
            "hypothesis_reactivity_plan.decision_loss_assumptions.false_reassurance_cost",
        )
        require_canonical_bounded_report_text(
            assumptions.precaution_cost,
            "hypothesis_reactivity_plan.decision_loss_assumptions.precaution_cost",
        )
        require_canonical_bounded_report_text(
            assumptions.decision_rule,
            "hypothesis_reactivity_plan.decision_loss_assumptions.decision_rule",
        )
        notice = require_canonical_bounded_report_text(
            assumptions.notice,
            "hypothesis_reactivity_plan.decision_loss_assumptions.notice",
        )
        lowered = notice.casefold()
        if "not" not in lowered or (
            "finding" not in lowered and "evidence" not in lowered
        ):
            raise ValidationError(
                "hypothesis_reactivity_plan.decision_loss_assumptions.notice must "
                "state that the precaution is not a finding or not evidence"
            )
        _reject_detection_as_finding(
            notice, "hypothesis_reactivity_plan.decision_loss_assumptions.notice"
        )


def validate_hypothesis_reactivity_assessment_gate(
    *,
    protocol: ExperimentProtocol,
    gate: QualityGateResult,
    outputs: list[Any],
    artifact_root: str | None,
    resolve_json_location,
    result_selection_sha256,
) -> None:
    from research_machine.application.policies import (
        require_canonical_bounded_report_text,
        require_canonical_text,
        require_sha256,
        require_unique_canonical_text_list,
    )

    assessment = gate.details.get("hypothesis_reactivity_assessment")
    if assessment is None:
        return
    plan = protocol.hypothesis_reactivity_plan
    if plan is None:
        raise ValidationError(
            f"quality gate {gate.gate_id} has hypothesis_reactivity_assessment "
            "but the protocol has no hypothesis_reactivity_plan"
        )
    if gate.gate_id != plan.assessment_gate_id:
        raise ValidationError(
            "hypothesis_reactivity_assessment must be recorded on the frozen "
            "reactivity assessment gate"
        )
    required_fields = {
        "plan_id",
        "assessment_status",
        "supported_model_ids",
        "not_distinguishable_model_ids",
        "likelihood_comparison",
        "observed_pattern",
        "interpretation",
        "evidence_sha256",
        "evidence_location",
    }
    optional_fields = {"decision_rationale", "selected_value_sha256"}
    if (
        not isinstance(assessment, dict)
        or not required_fields <= set(assessment)
        or set(assessment) - required_fields - optional_fields
    ):
        raise ValidationError(
            f"quality gate {gate.gate_id} hypothesis_reactivity_assessment must "
            "contain exactly the documented fields"
        )
    prefix = f"quality gate {gate.gate_id} hypothesis_reactivity_assessment"
    if require_canonical_text(assessment["plan_id"], f"{prefix}.plan_id") != plan.plan_id:
        raise ValidationError(
            "reactivity assessment plan_id does not match the frozen plan"
        )
    assessment_status = require_canonical_text(
        assessment["assessment_status"], f"{prefix}.assessment_status"
    )
    if assessment_status not in REACTIVITY_ASSESSMENT_STATUSES:
        raise ValidationError("hypothesis_reactivity assessment_status is unsupported")
    frozen_models = {model.model_id: model for model in plan.process_models}
    supported = require_unique_canonical_text_list(
        assessment["supported_model_ids"], f"{prefix}.supported_model_ids"
    )
    not_distinguishable = require_unique_canonical_text_list(
        assessment["not_distinguishable_model_ids"],
        f"{prefix}.not_distinguishable_model_ids",
    )
    unknown_supported = sorted(set(supported) - set(frozen_models))
    if unknown_supported:
        raise ValidationError(
            "reactivity assessment supported_model_ids are not in the frozen "
            "process model set: " + ", ".join(unknown_supported)
        )
    unknown_nd = sorted(set(not_distinguishable) - set(frozen_models))
    if unknown_nd:
        raise ValidationError(
            "reactivity assessment not_distinguishable_model_ids are not in the "
            "frozen process model set: " + ", ".join(unknown_nd)
        )
    expected_nd = {
        model.model_id
        for model in plan.process_models
        if model.distinguishability == "not_distinguishable_by_this_design"
    }
    if set(not_distinguishable) != expected_nd:
        raise ValidationError(
            "reactivity assessment not_distinguishable_model_ids must exactly "
            "equal the frozen non-distinguishable process models"
        )
    overlap = sorted(set(supported) & expected_nd)
    if overlap:
        raise ValidationError(
            "reactivity assessment cannot treat non-distinguishable models as "
            "supported: " + ", ".join(overlap)
        )
    if assessment_status == "models_discriminated":
        if not supported:
            raise ValidationError(
                "models_discriminated requires nonempty supported_model_ids"
            )
        if gate.status is not QualityGateStatus.PASSED:
            raise ValidationError(
                "models_discriminated requires a passed reactivity assessment gate"
            )
    elif assessment_status in {"compatible_with_multiple", "inconclusive"}:
        if gate.status is not QualityGateStatus.WARNING:
            raise ValidationError(
                f"{assessment_status} requires a warning reactivity assessment gate"
            )
        if assessment_status == "compatible_with_multiple" and len(supported) > 1:
            raise ValidationError(
                "compatible_with_multiple must leave supported_model_ids empty; "
                "name remaining competitors in interpretation under the frozen "
                "likelihood_comparison_rule"
            )
    elif assessment_status == "not_distinguishable_by_design":
        if gate.status is not QualityGateStatus.FAILED:
            raise ValidationError(
                "not_distinguishable_by_design requires a failed reactivity "
                "assessment gate"
            )
        if supported:
            raise ValidationError(
                "not_distinguishable_by_design cannot list supported_model_ids"
            )
    likelihood = require_canonical_bounded_report_text(
        assessment["likelihood_comparison"], f"{prefix}.likelihood_comparison"
    )
    lowered_likelihood = likelihood.casefold()
    if (
        plan.plan_id.casefold() not in lowered_likelihood
        and "frozen" not in lowered_likelihood
        and plan.likelihood_comparison_rule.casefold() not in lowered_likelihood
    ):
        raise ValidationError(
            "reactivity assessment likelihood_comparison must cite the frozen "
            "likelihood_comparison_rule or plan_id"
        )
    _reject_detection_as_finding(
        assessment["observed_pattern"], f"{prefix}.observed_pattern"
    )
    _reject_detection_as_finding(
        assessment["interpretation"], f"{prefix}.interpretation"
    )
    decision_rationale = assessment.get("decision_rationale")
    if decision_rationale is not None:
        if plan.decision_loss_assumptions is None:
            raise ValidationError(
                "reactivity assessment decision_rationale requires frozen "
                "decision_loss_assumptions"
            )
        _reject_detection_as_finding(
            decision_rationale, f"{prefix}.decision_rationale"
        )
        lowered = str(decision_rationale).casefold()
        if "assumption" not in lowered and "loss" not in lowered and "cost" not in lowered:
            raise ValidationError(
                "reactivity assessment decision_rationale must bind the frozen "
                "loss or cost assumptions"
            )
    evidence_sha256 = require_sha256(
        assessment["evidence_sha256"], f"{prefix}.evidence_sha256"
    )
    if evidence_sha256 not in {artifact.sha256 for artifact in outputs}:
        raise ValidationError(
            "reactivity assessment evidence must reference a run output artifact"
        )
    location = require_canonical_text(
        assessment["evidence_location"], f"{prefix}.evidence_location"
    )
    location_verified, selected_value = resolve_json_location(
        outputs,
        artifact_root,
        evidence_sha256,
        location,
        f"{prefix}.evidence_location",
    )
    if location_verified:
        selected_value_sha256 = result_selection_sha256(selected_value)
        supplied = assessment.get("selected_value_sha256")
        if supplied is not None and require_sha256(
            supplied, f"{prefix}.selected_value_sha256"
        ) != selected_value_sha256:
            raise ValidationError(
                "reactivity assessment selected_value_sha256 does not match the "
                "selected JSON value"
            )
        assessment["selected_value_sha256"] = selected_value_sha256


def parse_hypothesis_reactivity_plan(value: Any) -> HypothesisReactivityPlan:
    if not isinstance(value, dict):
        raise ValueError("hypothesis_reactivity_plan must be an object")
    fields = {
        "plan_id",
        "disclosure_schedule",
        "process_models",
        "likelihood_comparison_rule",
        "assessment_gate_id",
        "ethical_disclosure",
        "limitations",
        "decision_loss_assumptions",
    }
    unknown = sorted(set(value) - fields)
    if unknown:
        raise ValueError(
            "unknown hypothesis reactivity plan fields: " + ", ".join(unknown)
        )
    schedule_raw = value.get("disclosure_schedule")
    if not isinstance(schedule_raw, list):
        raise ValueError("disclosure_schedule must be an array")
    schedule = []
    event_fields = {
        "event_id",
        "audience",
        "statement_disclosed",
        "statement_role",
        "timing_anchor",
        "timing_description",
    }
    for item in schedule_raw:
        if not isinstance(item, dict):
            raise ValueError("disclosure_schedule entries must be objects")
        unknown_event = sorted(set(item) - event_fields)
        if unknown_event:
            raise ValueError(
                "unknown disclosure schedule fields: " + ", ".join(unknown_event)
            )
        schedule.append(HypothesisDisclosureEvent(**item))
    models_raw = value.get("process_models")
    if not isinstance(models_raw, list):
        raise ValueError("process_models must be an array")
    models = []
    model_fields = {
        "model_id",
        "statement",
        "observable_prediction",
        "comparison_rule",
        "distinguishability",
        "non_distinguishability_rationale",
        "linked_hypothesis_ids",
    }
    for item in models_raw:
        if not isinstance(item, dict):
            raise ValueError("process_models entries must be objects")
        unknown_model = sorted(set(item) - model_fields)
        if unknown_model:
            raise ValueError(
                "unknown process model fields: " + ", ".join(unknown_model)
            )
        payload = {
            "non_distinguishability_rationale": "",
            "linked_hypothesis_ids": [],
            **item,
        }
        models.append(CompetingProcessModel(**payload))
    assumptions_raw = value.get("decision_loss_assumptions")
    assumptions = None
    if assumptions_raw is not None:
        if not isinstance(assumptions_raw, dict):
            raise ValueError("decision_loss_assumptions must be an object")
        assumption_fields = {
            "false_reassurance_cost",
            "precaution_cost",
            "decision_rule",
            "notice",
        }
        unknown_assumptions = sorted(set(assumptions_raw) - assumption_fields)
        if unknown_assumptions:
            raise ValueError(
                "unknown decision_loss_assumptions fields: "
                + ", ".join(unknown_assumptions)
            )
        assumptions = DecisionLossAssumptions(**assumptions_raw)
    try:
        return HypothesisReactivityPlan(
            plan_id=value["plan_id"],
            disclosure_schedule=schedule,
            process_models=models,
            likelihood_comparison_rule=value["likelihood_comparison_rule"],
            assessment_gate_id=value["assessment_gate_id"],
            ethical_disclosure=value["ethical_disclosure"],
            limitations=value["limitations"],
            decision_loss_assumptions=assumptions,
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid hypothesis reactivity plan: {exc}") from exc
