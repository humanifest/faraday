from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_REQUIRED = {"title", "question", "decision", "outcome", "unit_of_observation"}
_STUDY_TYPES = {"causal", "correlational", "exploratory", "descriptive"}


@dataclass(frozen=True)
class DesignFinding:
    code: str
    severity: str
    message: str
    remediation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "remediation": self.remediation,
        }


def _text_list(brief: dict[str, Any], key: str) -> list[str]:
    value = brief.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"design brief field {key} must be an array of strings")
    return value


def validate_brief(brief: dict[str, Any]) -> None:
    unknown = set(brief) - {
        "title", "question", "decision", "study_type", "population", "setting",
        "intervention", "outcome", "outcome_unit", "unit_of_observation",
        "comparison", "sampling_plan", "randomization_plan", "blinding_plan",
        "controls", "confounds", "calibration_plan", "measurement_validity",
        "analysis_commitment", "stopping_rule", "human_participants", "consent_plan",
        "privacy_plan", "withdrawal_plan", "retention_deletion_plan",
        "independent_review", "independent_review_receipt", "risk_description",
        "exclusions",
    }
    if unknown:
        raise ValueError("unknown design brief fields: " + ", ".join(sorted(unknown)))
    missing = sorted(key for key in _REQUIRED if not str(brief.get(key, "")).strip())
    if missing:
        raise ValueError("design brief is missing required fields: " + ", ".join(missing))
    study_type = brief.get("study_type", "exploratory")
    if study_type not in _STUDY_TYPES:
        raise ValueError("study_type must be one of: " + ", ".join(sorted(_STUDY_TYPES)))
    for key in {"controls", "confounds", "exclusions"}:
        _text_list(brief, key)
    for key in {"human_participants", "independent_review"}:
        if key in brief and not isinstance(brief[key], bool):
            raise ValueError(f"design brief field {key} must be a boolean")


def audit_design(brief: dict[str, Any]) -> list[DesignFinding]:
    validate_brief(brief)
    findings: list[DesignFinding] = []

    def add(code: str, severity: str, message: str, remediation: str) -> None:
        findings.append(DesignFinding(code, severity, message, remediation))

    study_type = brief.get("study_type", "exploratory")
    if study_type == "causal":
        if not str(brief.get("intervention", "")).strip():
            add("CAUSAL_INTERVENTION_MISSING", "error", "A causal study does not specify an intervention.", "Define what is changed, by whom, and when.")
        if not str(brief.get("comparison", "")).strip():
            add("CAUSAL_COMPARISON_MISSING", "error", "A causal study has no comparison condition.", "Add a control, crossover, or justified comparison group.")
        if not str(brief.get("randomization_plan", "")).strip():
            add("CAUSAL_ASSIGNMENT_UNRESOLVED", "warning", "Assignment is not randomized or otherwise justified.", "Specify randomization, matching, or the identification assumptions and likely confounders.")
    if not str(brief.get("outcome_unit", "")).strip():
        add("MEASUREMENT_UNIT_MISSING", "error", "The outcome has no stated unit or scale.", "Name the instrument, scale, units, and direction of better/worse values.")
    if not str(brief.get("measurement_validity", "")).strip():
        add("MEASUREMENT_VALIDITY_UNRESOLVED", "warning", "No validity evidence is named for the outcome measurement.", "State how the measurement can be checked against a reference, blind sample, or known result.")
    if not str(brief.get("calibration_plan", "")).strip():
        add("CALIBRATION_UNRESOLVED", "warning", "No calibration or measurement-quality plan is recorded.", "Specify calibration, synchronization, missing-channel, or data-quality checks before collection.")
    if not _text_list(brief, "controls"):
        add("CONTROL_FAMILY_MISSING", "warning", "No positive, negative, sham, replay, or other control is planned.", "Choose the control family that could reveal a misleading measurement or procedure.")
    if not _text_list(brief, "confounds"):
        add("CONFOUNDS_UNASSESSED", "warning", "No plausible confounders are recorded.", "List competing explanations and how each will be measured, blocked, or bounded.")
    if not str(brief.get("analysis_commitment", "")).strip():
        add("ANALYSIS_COMMITMENT_MISSING", "warning", "The analysis and estimand are not committed before collection.", "Specify the primary comparison, uncertainty method, exclusions, and multiplicity handling.")
    if not str(brief.get("stopping_rule", "")).strip():
        add("STOPPING_RULE_MISSING", "warning", "No sample-size, precision, or stopping rule is declared.", "Set a sample-size, precision target, or fixed stopping condition before inspecting results.")
    if brief.get("human_participants"):
        for field, code, label in (
            ("consent_plan", "HUMAN_CONSENT_MISSING", "consent and withdrawal"),
            ("privacy_plan", "HUMAN_PRIVACY_MISSING", "privacy and access"),
            ("withdrawal_plan", "HUMAN_WITHDRAWAL_MISSING", "withdrawal handling"),
            ("retention_deletion_plan", "HUMAN_RETENTION_MISSING", "retention and deletion"),
            ("risk_description", "HUMAN_RISK_UNASSESSED", "physical and psychological risks"),
        ):
            if not str(brief.get(field, "")).strip():
                add(code, "error", f"Human-participant work lacks a {label} plan.", f"Document {label} before the study can proceed.")
        if not brief.get("independent_review", False):
            add("HUMAN_REVIEW_REQUIRED", "error", "Human-participant work is blocked pending qualified independent review.", "Obtain and record the applicable ethics, institutional, or qualified professional review.")
        elif not str(brief.get("independent_review_receipt", "")).strip():
            add("HUMAN_REVIEW_RECEIPT_MISSING", "error", "Qualified independent review is asserted without a review receipt.", "Record the review body's stable receipt or approval identifier before the study can proceed.")
    return findings


def scaffold_design(brief: dict[str, Any]) -> dict[str, Any]:
    findings = audit_design(brief)
    blockers = [item for item in findings if item.severity == "error"]
    study_type = brief.get("study_type", "exploratory")
    controls = _text_list(brief, "controls")
    confounds = _text_list(brief, "confounds")
    hypothesis = {
        "statement": f"[REVIEW REQUIRED] {brief['question']}",
        "generated_by": "guided_experiment_scaffold",
        "scope": f"Population: {brief.get('population', 'unresolved')}; setting: {brief.get('setting', 'unresolved')}",
        "observable_prediction": "[REVIEW REQUIRED] State the observation that would discriminate this hypothesis from alternatives.",
        "null_model": "[REVIEW REQUIRED] State the no-effect or competing explanation.",
        "competing_models": confounds or ["[REVIEW REQUIRED] Add measurement, selection, and confounding alternatives."],
        "falsification_conditions": ["[REVIEW REQUIRED] Define a result that would weaken this hypothesis."],
    }
    protocol = {
        "experiment_id": "[REVIEW REQUIRED] stable experiment ID",
        "title": brief["title"],
        "analysis_mode": "confirmatory" if study_type in {"causal", "correlational"} else "exploratory",
        "hypotheses_tested": ["[REVIEW REQUIRED] create and review hypothesis first"],
        "primary_outcome": brief["outcome"],
        "protocol_kind": "experimental" if study_type == "causal" else "observational",
        "methodology": f"{study_type} study; intervention: {brief.get('intervention', 'not applicable')}; comparison: {brief.get('comparison', 'unresolved')}",
        "controls": controls or ["[REVIEW REQUIRED] add a control family"],
        "sampling_unit": brief["unit_of_observation"],
        "sample_size_or_stopping_rule": brief.get("stopping_rule", "[REVIEW REQUIRED]"),
        "randomization_plan": brief.get("randomization_plan", "[REVIEW REQUIRED]"),
        "blinding_plan": brief.get("blinding_plan", "[REVIEW REQUIRED]"),
        "calibration_requirements": [brief.get("calibration_plan", "[REVIEW REQUIRED]")],
        "measurement_custody_requirements": ["[REVIEW REQUIRED] name the custody gate that demonstrates the calibration requirement was met"],
        "statistical_model": brief.get("analysis_commitment", "[REVIEW REQUIRED]"),
        "inclusion_rules": [brief.get("sampling_plan", "[REVIEW REQUIRED]")],
        "exclusion_rules": _text_list(brief, "exclusions"),
        "safety_constraints": ["Human-participant review required before collection."] if brief.get("human_participants") else ["[REVIEW REQUIRED] assess applicable safety constraints."],
        "human_subjects": bool(brief.get("human_participants", False)),
        "consent_plan": brief.get("consent_plan", ""),
        "withdrawal_plan": brief.get("withdrawal_plan", ""),
        "privacy_plan": brief.get("privacy_plan", ""),
        "retention_deletion_plan": brief.get("retention_deletion_plan", ""),
        "risk_assessment": brief.get("risk_description", ""),
        "independent_review_receipt": brief.get("independent_review_receipt", ""),
    }
    return {
        "status": "blocked" if blockers else "review_required",
        "plain_language_summary": "This scaffold is a draft. It does not register, approve, or freeze a study.",
        "findings": [item.to_dict() for item in findings],
        "artifacts": {
            "hypothesis-proposal.json": hypothesis,
            "protocol-draft.json": protocol,
            "data-dictionary-draft.json": {
                "outcome": brief["outcome"], "unit_or_scale": brief.get("outcome_unit", "[REVIEW REQUIRED]"), "unit_of_observation": brief["unit_of_observation"], "measurement_validity": brief.get("measurement_validity", "[REVIEW REQUIRED]"),
            },
            "collection-plan.md": f"# {brief['title']}\n\nQuestion: {brief['question']}\n\nDecision: {brief['decision']}\n\nCollect only after all blocking findings are resolved and the protocol is reviewed.\n",
        },
    }
