from __future__ import annotations

import hashlib
import json

from research_machine.domain.errors import ValidationError
from research_machine.domain.models import ExperimentProtocol


def _sha256_json(value: object) -> str:
    try:
        content = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValidationError("cannot hash non-finite canonical JSON") from exc
    return hashlib.sha256(content).hexdigest()


def protocol_commitment(protocol: ExperimentProtocol) -> str:
    payload = protocol.to_dict()
    if not protocol.hypothesis_commitments:
        payload.pop("hypothesis_commitments", None)
    if not protocol.sample_size_plan:
        payload.pop("sample_size_plan", None)
    if not protocol.control_definitions:
        payload.pop("control_definitions", None)
    if not protocol.named_component_contracts:
        payload.pop("named_component_contracts", None)
    if not protocol.calibration_acceptance_criteria:
        payload.pop("calibration_acceptance_criteria", None)
    for criterion in payload.get("calibration_acceptance_criteria", []):
        if not criterion.get("component_bounds"):
            criterion.pop("component_bounds", None)
    if not protocol.analysis_specification_sha256:
        payload.pop("analysis_specification_sha256", None)
    if not protocol.causal_claim:
        payload.pop("causal_claim", None)
    if not protocol.causal_identification:
        payload.pop("causal_identification", None)
    if not protocol.causal_identification_audit:
        payload.pop("causal_identification_audit", None)
    if protocol.analysis_contract is None:
        payload.pop("analysis_contract", None)
    else:
        for field_name in (
            "primary_hypothesis_id",
            "primary_measurement_id",
            "assignment_type",
            "effect_estimate_path",
            "uncertainty_path",
            "allocation_sha256",
            "missingness_assumption",
            "missingness_assessment_plan",
            "missingness_failure_response",
            "missingness_assessment_kind",
            "missingness_assessment_gate_id",
        ):
            if not getattr(protocol.analysis_contract, field_name):
                payload["analysis_contract"].pop(field_name, None)
        if not protocol.analysis_contract.support_rule:
            payload["analysis_contract"].pop("support_rule", None)
            payload["analysis_contract"].pop("null_value", None)
        for field_name in (
            "confidence_level",
            "minimum_analyzable_units",
            "maximum_excluded_fraction",
            "maximum_group_excluded_fraction_difference",
        ):
            if getattr(protocol.analysis_contract, field_name) is None:
                payload["analysis_contract"].pop(field_name, None)
        if not protocol.analysis_contract.adjustment_columns:
            payload["analysis_contract"].pop("adjustment_columns", None)
    if not protocol.analysis_steps:
        payload.pop("analysis_steps", None)
    for field_name in (
        "confirmatory_outcomes",
        "exploratory_outcomes",
        "multiplicity_method",
        "multiplicity_alpha",
    ):
        if not getattr(protocol, field_name):
            payload.pop(field_name, None)
    for definition in payload.get("measurement_definitions", []):
        if not definition.get("data_column"):
            definition.pop("data_column", None)
        for field_name in (
            "scale_type",
            "unit",
            "admissible_values",
            "missing_value_codes",
        ):
            if not definition.get(field_name):
                definition.pop(field_name, None)
        for field_name in ("valid_min", "valid_max"):
            if definition.get(field_name) is None:
                definition.pop(field_name, None)
    for field_name in (
        "unit_analysis_plan",
        "unit_id_column",
        "independent_review_decision",
        "independent_reviewer_role",
        "independent_reviewed_at",
        "independent_review_scope",
        "independent_review_artifact_locator",
        "independent_review_artifact_sha256",
        "vulnerable_population_plan",
        "data_security_plan",
        "incidental_findings_plan",
    ):
        if not getattr(protocol, field_name):
            payload.pop(field_name, None)
    if not protocol.independent_review_conditions:
        payload.pop("independent_review_conditions", None)
    payload.pop("independent_review_verification", None)
    if protocol.amendment_timing is None:
        payload.pop("amendment_timing", None)
    if protocol.evidence_exposure is None:
        payload.pop("evidence_exposure", None)
    if (
        protocol.independent_unit == ""
        and protocol.repeated_measures is None
        and protocol.analysis_design == ""
    ):
        for name in ("independent_unit", "repeated_measures", "analysis_design"):
            payload.pop(name, None)
    for field_name in (
        "status",
        "protocol_hash",
        "registration_timestamp",
        "external_anchor",
    ):
        payload.pop(field_name, None)
    return _sha256_json(payload)
