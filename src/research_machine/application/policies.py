from collections.abc import Mapping, Sequence
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from research_machine.application.claim_integrity import claim_level_rank
from research_machine.application.audit_prerequisite import (
    validate_audit_prerequisite_contract,
)
from research_machine.domain.errors import ValidationError
from research_machine.application.report_language import report_overclaim_terms
from research_machine.domain.models import (
    ActionCandidate,
    ActionLane,
    AnalysisMode,
    AnalysisContract,
    AnalysisImplementationBundleContract,
    AnalysisImplementationMember,
    BoundedNegativeSearchContract,
    BoundedSearchInterface,
    BoundedSearchQuery,
    AnalysisFamilyMember,
    AnalysisStepContract,
    CalibrationCriterion,
    CanaryTargetPlan,
    ConclusionContract,
    ComputationRouteSeparationContract,
    Claim,
    ClaimLevel,
    DatasetManifest,
    DatasetArtifact,
    DualityReconstructionContract,
    ControlDefinition,
    ControlWitnessContract,
    CrossRouteDependencyEdge,
    CONTROL_FAMILIES,
    EvidenceDirection,
    ExperimentProtocol,
    Hypothesis,
    HypothesisDiscriminationTarget,
    HypothesisWorkflowState,
    MathematicalPredicateContract,
    AliasProxyCommitment,
    MeasurementDefinition,
    NamedComponentContract,
    MeasurementValidityCheck,
    MEASUREMENT_TEMPORAL_ROLES,
    MeasurementRole,
    ProtocolKind,
    ProtocolStatus,
    QualityGateResult,
    QualityGateStatus,
    ReconstructionFamilyStabilityContract,
    ResearchRun,
    RejectionType,
    ScreenedSearchCandidate,
    RuntimePreflightRequirement,
    SelectionWeights,
    ValidationTag,
)


_LEGACY_PRE_REGISTRATION_RESULT_EXPOSURE_FLAGS = (
    "favorable_development_output_seen_before_registration",
    "favorable_prototype_output_seen_before_registration",
)


def declares_legacy_pre_registration_result_exposure(
    metadata: Mapping[str, Any],
) -> bool:
    """Recognize only historical structured booleans, never narrative prose."""

    return any(
        metadata.get(field_name) is True
        for field_name in _LEGACY_PRE_REGISTRATION_RESULT_EXPOSURE_FLAGS
    )


def typed_result_exposure_allows_evidence(metadata: Mapping[str, Any]) -> bool:
    """Return whether sealed metadata carries the normalized prospective form."""

    if declares_legacy_pre_registration_result_exposure(metadata):
        return False
    disclosure = metadata.get("result_exposure_disclosure")
    return (
        isinstance(disclosure, dict)
        and set(disclosure) == {
            "status",
            "exposures",
            "automatic_evidence_eligible",
            "interpretation_boundary",
        }
        and disclosure.get("status") == "no_relevant_output_seen"
        and disclosure.get("exposures") == []
        and disclosure.get("automatic_evidence_eligible") is True
        and isinstance(disclosure.get("interpretation_boundary"), str)
    )

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PENDING_REVIEW_AUTHORITY_CLAIM = re.compile(
    r"\b(?:accepts?|accepted|approves?|approved|approval|authorizes?|"
    r"authorized|authorization|confirms?|confirmed|confirmation|proves?|"
    r"proved|proof|validates?|validated|validation)\b|"
    r"human[- ]reviewed|reviewed by human|human review complete|"
    r"canonical write|canonical action|evidence creation|creates evidence|"
    r"created evidence|"
    r"\b(?:establish(?:es|ed)?|finds?|found|determines?|determined|"
    r"shows?|showed|demonstrates?|demonstrated)\b(?:\s+\w+){0,6}\s+"
    r"\b(?:legal characterization|legal responsibility|legal liability|"
    r"culpability|liability|guilt|negligence|fraudulent intent|criminal intent|"
    r"intentional wrongdoing)\b|"
    r"\b(?:is|are|was|were)\s+(?:legally responsible|liable|guilty|negligent)\b|"
    r"\bcommitted\s+fraud\b",
    re.IGNORECASE,
)
_PENDING_REVIEW_NEGATION_PREFIX = re.compile(
    r"\b(?:does|do|did|is|are|was|were|has|have|had|can|could|will|would|"
    r"shall|should|must)\s+not(?!\s+only\b)(?:\s+\w+){0,6}\s*$|"
    r"\bcannot(?:\s+\w+){0,6}\s*$|\bno(?:\s+\w+){0,3}\s*$",
    re.IGNORECASE,
)
_INDEPENDENT_REVIEW_DECISIONS = {"approved", "approved_with_conditions"}
_METHOD_INFERENCE_CLAIM_CEILINGS: dict[str, ClaimLevel | None] = {
    "computation_only": None,
    "descriptive": ClaimLevel.MEASUREMENT_VALIDITY,
    "association": ClaimLevel.STATISTICAL_ASSOCIATION,
    "design_conditional_effect": ClaimLevel.CAUSAL_DIRECTION,
}
_RETIREMENT_FIELDS = {
    "rejection_type",
    "reason",
    "limitations",
    "resurrection_conditions",
    "superseded_by",
    "decided_at",
    "decided_by",
}


def require_sha256(value: str, field_name: str) -> str:
    digest = require_text(value, field_name)
    if digest != value or not _SHA256.fullmatch(digest):
        raise ValidationError(f"{field_name} must be 64 lowercase hex characters")
    return digest


def validate_runtime_preflight_requirement(
    requirement: RuntimePreflightRequirement | None,
) -> RuntimePreflightRequirement | None:
    if requirement is None:
        return None
    if not isinstance(requirement, RuntimePreflightRequirement):
        raise ValidationError(
            "runtime_preflight_requirement must be a RuntimePreflightRequirement"
        )
    require_sha256(
        requirement.receipt_sha256,
        "runtime_preflight_requirement.receipt_sha256",
    )
    if requirement.probe_id != "research-machine-runtime-preflight-v1":
        raise ValidationError(
            "runtime_preflight_requirement.probe_id is unsupported"
        )
    for field_name in (
        "probe_id",
        "interpreter_path",
        "kernel_name",
        "working_directory",
    ):
        value = getattr(requirement, field_name)
        if require_text(
            value, f"runtime_preflight_requirement.{field_name}"
        ) != value:
            raise ValidationError(
                f"runtime_preflight_requirement.{field_name} must be canonical"
            )
    if not Path(requirement.interpreter_path).is_absolute():
        raise ValidationError(
            "runtime_preflight_requirement.interpreter_path must be absolute"
        )
    if not Path(requirement.working_directory).is_absolute():
        raise ValidationError(
            "runtime_preflight_requirement.working_directory must be absolute"
        )
    return requirement


def validate_notebook_freeze_input_bundle_requirement(
    bundle_sha256: str | None,
    runtime_requirement: RuntimePreflightRequirement | None,
) -> str | None:
    if bundle_sha256 is None:
        return None
    require_sha256(
        bundle_sha256,
        "notebook_freeze_input_bundle_sha256",
    )
    if runtime_requirement is None:
        raise ValidationError(
            "notebook freeze-input bundle requires runtime_preflight_requirement"
        )
    return bundle_sha256


def is_canonical_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))


def normalize_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    return value.strip()


def require_text(value: str, field_name: str) -> str:
    normalized = normalize_text(value, field_name)
    if not normalized:
        raise ValidationError(f"{field_name} must not be empty")
    return normalized


def require_bounded_report_text(
    value: str,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> str:
    summary = normalize_text(value, field_name)
    if not summary:
        if allow_empty:
            return summary
        raise ValidationError(f"{field_name} must not be empty")
    if report_overclaim_terms(summary):
        raise ValidationError(
            f"{field_name} uses report-prohibited overclaiming language; "
            "state bounded support, weakening, refutation, or inconclusiveness instead"
    )
    return summary


def require_canonical_bounded_report_text(value: str, field_name: str) -> str:
    summary = require_canonical_text(value, field_name)
    if report_overclaim_terms(summary):
        raise ValidationError(
            f"{field_name} uses report-prohibited overclaiming language; "
            "state bounded support, weakening, refutation, or inconclusiveness instead"
        )
    return summary


def require_pending_review_rationale(value: str) -> str:
    rationale = require_canonical_text(value, "pending-review rationale")
    authority_claims = list(_PENDING_REVIEW_AUTHORITY_CLAIM.finditer(rationale))
    unnegated_claims = []
    for match in authority_claims:
        boundary = max(
            rationale.rfind(separator, 0, match.start())
            for separator in (".", ";", "!", "?", "\n")
        )
        clause_prefix = rationale[boundary + 1 : match.start()]
        if not _PENDING_REVIEW_NEGATION_PREFIX.search(clause_prefix):
            unnegated_claims.append(match)
    if unnegated_claims:
        raise ValidationError(
            "pending-review rationale must not describe provisional staging as "
            "approval, validation, confirmation, human-reviewed acceptance, "
            "evidence creation, canonical action, authorization, or "
            "legal/intent characterization"
        )
    return rationale


def _bounded_json_metadata(value: Any, field_name: str) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError(f"{field_name} must contain only finite numbers")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if value != value.strip():
            raise ValidationError(
                f"{field_name} text must be canonical without surrounding whitespace"
            )
        if value and _metadata_overclaim_terms(value):
            raise ValidationError(
                f"{field_name} uses report-prohibited overclaiming language; "
                "metadata is caller-authored context, not scientific authority"
            )
        return value
    if isinstance(value, list):
        return [
            _bounded_json_metadata(item, field_name)
            for item in value
        ]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not key.strip() or key != key.strip():
                raise ValidationError(
                    f"{field_name} keys must be canonical non-empty text"
                )
            if _metadata_overclaim_terms(key):
                raise ValidationError(
                    f"{field_name} keys use report-prohibited overclaiming language; "
                    "metadata is caller-authored context, not scientific authority"
                )
            normalized[key] = _bounded_json_metadata(item, field_name)
        return normalized
    raise ValidationError(f"{field_name} must be JSON-compatible")


def validate_action_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("action metadata must be an object")
    return _bounded_json_metadata(value, "action metadata")


def validate_hypothesis_pending_review_boundary(hypothesis: Hypothesis) -> None:
    if hypothesis.workflow_state is not HypothesisWorkflowState.PENDING_REVIEW:
        return
    require_pending_review_rationale(hypothesis.pending_review_rationale)


def validate_hypothesis_retirement_boundary(hypothesis: Hypothesis) -> None:
    if hypothesis.workflow_state is not HypothesisWorkflowState.RETIRED:
        return
    retirement = hypothesis.retirement
    if not isinstance(retirement, dict):
        raise ValidationError("retired hypothesis must retain retirement metadata")
    missing = sorted(_RETIREMENT_FIELDS - set(retirement))
    unknown = sorted(set(retirement) - _RETIREMENT_FIELDS)
    if missing:
        raise ValidationError("retirement metadata missing fields: " + ", ".join(missing))
    if unknown:
        raise ValidationError("retirement metadata has unknown fields: " + ", ".join(unknown))
    try:
        RejectionType(
            require_canonical_text(
                retirement["rejection_type"], "retirement rejection_type"
            )
        )
    except ValueError as exc:
        raise ValidationError("retirement rejection_type is unsupported") from exc
    require_canonical_bounded_report_text(retirement["reason"], "retirement reason")
    require_canonical_bounded_report_text(
        retirement["limitations"], "retirement limitations"
    )
    require_nonempty_unique_bounded_report_text_list(
        retirement["resurrection_conditions"], "resurrection_conditions"
    )
    superseded_by = retirement["superseded_by"]
    if superseded_by is not None:
        require_canonical_text(superseded_by, "retirement superseded_by")
    require_canonical_text(retirement["decided_at"], "retirement decided_at")
    require_canonical_text(retirement["decided_by"], "retirement decided_by")


def require_bounded_evidence_summary(value: str) -> str:
    return require_bounded_report_text(value, "evidence summary")


def _metadata_overclaim_terms(value: str) -> list[str]:
    return report_overclaim_terms(value) or report_overclaim_terms(
        value.replace("_", " ").replace("-", " ")
    )


def evidence_summary_overclaim_terms(value: str) -> list[str]:
    return report_overclaim_terms(value)


def require_canonical_text(value: str, field_name: str) -> str:
    text = require_text(value, field_name)
    if text != value:
        raise ValidationError(
            f"{field_name} must be canonical without surrounding whitespace"
        )
    return text


def require_text_list(values: Sequence[str], field_name: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValidationError(f"{field_name} must be a list of text values")
    return [require_text(value, f"{field_name} item") for value in values]


def require_unique_text_list(values: Sequence[str], field_name: str) -> list[str]:
    normalized = require_text_list(values, field_name)
    if len(set(normalized)) != len(normalized):
        raise ValidationError(f"{field_name} must not contain duplicates")
    return normalized


def require_unique_bounded_report_text_list(
    values: Sequence[str], field_name: str
) -> list[str]:
    normalized = [
        require_bounded_report_text(value, f"{field_name} item")
        for value in require_text_list(values, field_name)
    ]
    if len(set(normalized)) != len(normalized):
        raise ValidationError(f"{field_name} must not contain duplicates")
    return normalized


def require_nonempty_unique_bounded_report_text_list(
    values: Sequence[str], field_name: str
) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValidationError(f"{field_name} must be a list of text values")
    normalized = [
        require_canonical_bounded_report_text(value, f"{field_name} item")
        for value in values
    ]
    if not normalized:
        raise ValidationError(f"{field_name} must contain at least one item")
    if len(set(normalized)) != len(normalized):
        raise ValidationError(f"{field_name} must not contain duplicates")
    return normalized


def require_canonical_text_list(
    values: Sequence[str], field_name: str
) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValidationError(f"{field_name} must be a list of text values")
    return [
        require_canonical_text(value, f"{field_name} item")
        for value in values
    ]


def require_unique_canonical_text_list(
    values: Sequence[str], field_name: str
) -> list[str]:
    normalized = require_canonical_text_list(values, field_name)
    if len(set(normalized)) != len(normalized):
        raise ValidationError(f"{field_name} must not contain duplicates")
    return normalized


def normalize_confidence(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("confidence must be a number from 0 through 1 or null")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0 <= normalized <= 1:
        raise ValidationError("confidence must be a number from 0 through 1 or null")
    return normalized


def _reject_review_placeholders(value: object, path: str) -> None:
    if isinstance(value, str) and "[review required]" in value.casefold():
        raise ValidationError(f"unresolved scaffold placeholder in {path}; replace it with reviewed scientific content")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_review_placeholders(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_review_placeholders(child, f"{path}[{index}]")


def validate_hypothesis_activation(hypothesis: Hypothesis) -> None:
    _reject_review_placeholders(hypothesis.to_dict(), "hypothesis")
    if hypothesis.workflow_state not in {
        HypothesisWorkflowState.UNREVIEWED,
        HypothesisWorkflowState.PENDING_REVIEW,
        HypothesisWorkflowState.PARKED,
    }:
        raise ValidationError(
            f"hypothesis {hypothesis.hypothesis_id} cannot be activated from "
            f"{hypothesis.workflow_state.value}"
        )
    missing: list[str] = []
    if not hypothesis.observable_prediction.strip():
        missing.append("observable_prediction")
    if not hypothesis.falsification_conditions:
        missing.append("falsification_conditions")
    if not hypothesis.null_model.strip() and not hypothesis.competing_models:
        missing.append("null_model or competing_models")
    if missing:
        raise ValidationError(
            "hypothesis cannot be activated until it defines: " + ", ".join(missing)
        )


def validate_hypothesis_staging(hypothesis: Hypothesis) -> None:
    _reject_review_placeholders(hypothesis.to_dict(), "hypothesis")
    if hypothesis.workflow_state not in {
        HypothesisWorkflowState.UNREVIEWED,
        HypothesisWorkflowState.PARKED,
    }:
        raise ValidationError(
            f"hypothesis {hypothesis.hypothesis_id} cannot be staged from "
            f"{hypothesis.workflow_state.value}"
        )
    missing: list[str] = []
    if not hypothesis.observable_prediction.strip():
        missing.append("observable_prediction")
    if not hypothesis.falsification_conditions:
        missing.append("falsification_conditions")
    if not hypothesis.null_model.strip() and not hypothesis.competing_models:
        missing.append("null_model or competing_models")
    if missing:
        raise ValidationError(
            "hypothesis cannot enter pending review until it defines: "
            + ", ".join(missing)
        )


def validate_evidence_target(hypothesis: Hypothesis, *, exploratory: bool) -> None:
    if hypothesis.workflow_state is HypothesisWorkflowState.UNREVIEWED:
        raise ValidationError(
            "evidence cannot be attached to an unreviewed proposal; stage or activate "
            "it first"
        )
    if (
        hypothesis.workflow_state is HypothesisWorkflowState.PENDING_REVIEW
        and not exploratory
    ):
        raise ValidationError(
            "confirmatory evidence cannot be attached while human review is pending"
        )


def validate_evidence_annotations(
    *,
    direction: EvidenceDirection,
    scope: str,
    uncertainty: str,
    controls_passed: Sequence[str],
    controls_failed: Sequence[str],
    higher_level_conclusions_unsupported: Sequence[str],
    validation_tags: Sequence[ValidationTag],
) -> tuple[str, str, list[str], list[str], list[str], list[ValidationTag]]:
    normalized_scope = require_text(scope, "scope")
    normalized_uncertainty = require_text(uncertainty, "uncertainty")
    passed = require_text_list(controls_passed, "controls_passed")
    failed = require_text_list(controls_failed, "controls_failed")
    if len(set(passed)) != len(passed) or len(set(failed)) != len(failed):
        raise ValidationError("control disclosures must not contain duplicates")
    if set(passed) & set(failed):
        raise ValidationError("control disclosures cannot list the same control as passed and failed")
    ceilings = require_unique_bounded_report_text_list(
        higher_level_conclusions_unsupported,
        "higher_level_conclusions_unsupported",
    )
    if not ceilings:
        raise ValidationError(
            "higher_level_conclusions_unsupported must name at least one claim ceiling"
        )
    if direction in {
        EvidenceDirection.SUPPORTS,
        EvidenceDirection.WEAKENS,
        EvidenceDirection.REFUTES,
    } and not (passed or failed):
        raise ValidationError(
            "directional evidence must record at least one passed or failed control"
        )
    if isinstance(validation_tags, (str, bytes)) or not isinstance(
        validation_tags, Sequence
    ):
        raise ValidationError("validation_tags must be a list")
    tags: list[ValidationTag] = []
    for value in validation_tags:
        if not isinstance(value, ValidationTag):
            raise ValidationError("validation_tags must contain ValidationTag values")
        tags.append(value)
    if not tags:
        raise ValidationError(
            "validation_tags must classify the evidence; unclassified new evidence "
            "is not permitted"
        )
    if len(set(tags)) != len(tags):
        raise ValidationError("validation_tags must not contain duplicates")
    return (
        normalized_scope,
        normalized_uncertainty,
        passed,
        failed,
        ceilings,
        tags,
    )


def validate_result_direction(
    *, expected_direction: str, evidence_direction: EvidenceDirection, effect: Any,
    uncertainty: Any, null_value: float, support_rule: str,
    equivalence_margin: float | None = None,
) -> str:
    if expected_direction not in {"positive", "negative", "two_sided", "equivalence"}:
        raise ValidationError(
            "execution-backed primary hypothesis expected_effect_direction must be positive, negative, two_sided, or equivalence"
        )
    if isinstance(effect, bool) or not isinstance(effect, (int, float)) or not math.isfinite(float(effect)):
        raise ValidationError("registered primary effect estimate must be a finite number")
    if not isinstance(uncertainty, dict):
        raise ValidationError("registered uncertainty must be a confidence-interval object")
    try:
        lower, upper, level = uncertainty["lower"], uncertainty["upper"], uncertainty["level"]
    except KeyError as exc:
        raise ValidationError("registered confidence interval requires lower, upper, and level") from exc
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in (lower, upper, level)):
        raise ValidationError("registered confidence interval values must be finite numbers")
    if lower > effect or effect > upper or not 0 < level < 1:
        raise ValidationError("registered confidence interval must contain the effect and use a level between zero and one")
    if evidence_direction is not EvidenceDirection.SUPPORTS:
        return "not_directionally_assertive"
    if expected_direction == "equivalence":
        if (
            isinstance(equivalence_margin, bool)
            or not isinstance(equivalence_margin, (int, float))
            or not math.isfinite(float(equivalence_margin))
            or float(equivalence_margin) <= 0
        ):
            raise ValidationError("equivalence support requires a frozen positive finite margin")
        if support_rule != "interval_within_equivalence_margin":
            raise ValidationError("equivalence support requires the frozen interval-within-margin rule")
        margin = float(equivalence_margin)
        if not (lower > null_value - margin and upper < null_value + margin):
            raise ValidationError(
                "supporting equivalence evidence interval is not wholly within the frozen margin"
            )
        return "confidence_interval_wholly_within_registered_equivalence_margin"
    if expected_direction == "positive" and effect <= null_value:
        raise ValidationError("supporting evidence contradicts the frozen positive effect direction")
    if expected_direction == "negative" and effect >= null_value:
        raise ValidationError("supporting evidence contradicts the frozen negative effect direction")
    if expected_direction == "two_sided" and effect == null_value:
        raise ValidationError("supporting evidence equals the frozen null value")
    if support_rule == "interval_excludes_null":
        supports = (
            lower > null_value if expected_direction == "positive" else
            upper < null_value if expected_direction == "negative" else
            upper < null_value or lower > null_value
        )
        if not supports:
            raise ValidationError("supporting evidence does not satisfy the frozen interval-excludes-null rule")
        return "confidence_interval_excludes_registered_null_in_expected_direction"
    return "point_estimate_direction_consistent; uncertainty still governs inference"


def adjudicate_conclusion_contract(
    *, conclusion: ConclusionContract, analysis: AnalysisContract,
    hypothesis: Hypothesis, effect: Any, uncertainty: Any,
    adjusted_primary_rejects: bool | None = None,
) -> dict[str, Any]:
    """Apply one frozen study-level decision policy without authoring prose."""
    if isinstance(effect, bool) or not isinstance(effect, (int, float)) or not math.isfinite(float(effect)):
        raise ValidationError("conclusion adjudication requires a finite numeric estimate")
    if not isinstance(uncertainty, dict):
        raise ValidationError("conclusion adjudication requires a confidence interval")
    try:
        lower = float(uncertainty["lower"])
        upper = float(uncertainty["upper"])
        level = float(uncertainty["level"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("conclusion adjudication requires finite confidence bounds and level") from exc
    if (
        not all(math.isfinite(value) for value in (lower, upper, level))
        or lower > float(effect) or float(effect) > upper or not 0 < level < 1
    ):
        raise ValidationError("conclusion adjudication requires a coherent confidence interval")
    null = float(analysis.null_value)
    expected = hypothesis.expected_effect_direction
    if expected not in {"positive", "negative", "two_sided", "equivalence"}:
        raise ValidationError("conclusion adjudication requires a frozen expected effect direction")
    threshold = float(conclusion.smallest_effect_size_of_interest)
    equivalence = conclusion.decision_rule == "equivalence_interval_within_margin"
    if equivalence:
        if expected != "equivalence":
            raise ValidationError("equivalence conclusion requires an equivalence hypothesis")
        if adjusted_primary_rejects is not None:
            raise ValidationError("direct equivalence rule cannot receive a multiplicity decision")
        within_margin = lower > null - threshold and upper < null + threshold
        return {
            "decision_rule": conclusion.decision_rule,
            "adjudicated_evidence_direction": (
                EvidenceDirection.SUPPORTS.value
                if within_margin else conclusion.non_supporting_direction.value
            ),
            "criteria": {
                "equivalence_margin": threshold,
                "lower_equivalence_bound": null - threshold,
                "upper_equivalence_bound": null + threshold,
                "registered_interval_within_equivalence_margin": within_margin,
                "absence_not_inferred_from_nonsignificance": True,
            },
            "scope": {
                "population": conclusion.population, "setting": conclusion.setting,
                "time_window": conclusion.time_window,
                "effect_scale": conclusion.effect_scale,
                "effect_unit": conclusion.effect_unit,
            },
            "permitted_claim_level": conclusion.permitted_claim_level.value,
            "higher_level_conclusions_unsupported": list(
                conclusion.higher_level_conclusions_unsupported
            ),
        }
    interval_supports = (
        lower > null if expected == "positive" else
        upper < null if expected == "negative" else
        upper < null or lower > null
    )
    practically_significant = (
        lower >= null + threshold if expected == "positive" else
        upper <= null - threshold if expected == "negative" else
        lower >= null + threshold or upper <= null - threshold
    )
    requires_adjustment = (
        conclusion.decision_rule
        == "adjusted_primary_rejection_and_interval_and_practical_significance"
    )
    if requires_adjustment and type(adjusted_primary_rejects) is not bool:
        raise ValidationError("adjusted conclusion rule requires the frozen primary family decision")
    if not requires_adjustment and adjusted_primary_rejects is not None:
        raise ValidationError("direct conclusion rule cannot receive a multiplicity decision")
    supports = interval_supports and practically_significant and (
        adjusted_primary_rejects is True if requires_adjustment else True
    )
    return {
        "decision_rule": conclusion.decision_rule,
        "adjudicated_evidence_direction": (
            EvidenceDirection.SUPPORTS.value
            if supports else conclusion.non_supporting_direction.value
        ),
        "criteria": {
            **(
                {"adjusted_primary_rejects": adjusted_primary_rejects}
                if requires_adjustment else {}
            ),
            "registered_interval_supports_expected_direction": interval_supports,
            "smallest_effect_size_of_interest": threshold,
            "practical_significance_satisfied": practically_significant,
            "practical_significance_requires_confidence_bound": True,
        },
        "scope": {
            "population": conclusion.population,
            "setting": conclusion.setting,
            "time_window": conclusion.time_window,
            "effect_scale": conclusion.effect_scale,
            "effect_unit": conclusion.effect_unit,
        },
        "permitted_claim_level": conclusion.permitted_claim_level.value,
        "higher_level_conclusions_unsupported": list(
            conclusion.higher_level_conclusions_unsupported
        ),
    }


def validate_validation_tag_context(
    *,
    tags: Sequence[ValidationTag],
    hypothesis: Hypothesis,
    exploratory: bool,
    protocol: ExperimentProtocol | None,
    run: ResearchRun | None,
    datasets: Sequence[DatasetManifest],
    controls_passed: Sequence[str],
    replicated_run: ResearchRun | None,
    claim: Claim | None = None,
    direction: EvidenceDirection = EvidenceDirection.INCONCLUSIVE,
    method_maximum_inference_level: str | None = None,
) -> None:
    tag_set = set(tags)

    if (
        method_maximum_inference_level is not None
        and direction is EvidenceDirection.SUPPORTS
    ):
        ceiling = _METHOD_INFERENCE_CLAIM_CEILINGS.get(method_maximum_inference_level)
        if method_maximum_inference_level not in _METHOD_INFERENCE_CLAIM_CEILINGS:
            raise ValidationError(
                "execution-backed evidence has an unsupported maximum_inference_level"
            )
        if claim is None:
            raise ValidationError(
                "execution-backed supporting evidence requires an exact claim so "
                "the method inference ceiling can be enforced"
            )
        claim_rank = claim_level_rank(claim.level)
        ceiling_rank = claim_level_rank(ceiling) if ceiling is not None else None
        if claim_rank is not None and (
            ceiling_rank is None or claim_rank > ceiling_rank
        ):
            ceiling_label = (
                "no scientific claim"
                if ceiling is None else ceiling.value
            )
            raise ValidationError(
                "supporting evidence claim level exceeds the executed method "
                f"inference ceiling: {method_maximum_inference_level} permits "
                f"{ceiling_label}, not {claim.level.value}"
            )

    if (
        claim is not None
        and direction is EvidenceDirection.SUPPORTS
        and claim.level
        in {
            ClaimLevel.MECHANISM,
            ClaimLevel.ADAPTATION,
            ClaimLevel.ATTRIBUTION_INTENT,
            ClaimLevel.LEGAL_CHARACTERIZATION,
        }
    ):
        raise ValidationError(
            "supporting evidence cannot target mechanism, adaptation, "
            "attribution-intent, or legal-characterization claims under the "
            "current validation-tag capability model"
        )

    if (
        claim is not None
        and claim.level is ClaimLevel.CAUSAL_DIRECTION
        and ValidationTag.CAUSAL_ESTIMATE not in tag_set
    ):
        raise ValidationError(
            "evidence attached to a causal-direction claim requires the causal_estimate validation tag"
        )

    def require_eligible_run(tag: ValidationTag) -> ResearchRun:
        if run is None or not run.scientific_evidence_eligible:
            raise ValidationError(
                f"validation tag {tag.value} requires an eligible recorded run"
            )
        return run

    if ValidationTag.SOURCE_ASSESSMENT in tag_set:
        if run is not None and (
            protocol is None or protocol.protocol_kind is not ProtocolKind.LITERATURE
        ):
            raise ValidationError(
                "source_assessment requires a literature run or dataset-only evidence"
            )
        if run is None and not datasets:
            raise ValidationError(
                "source_assessment requires a dataset or literature run"
            )

    if ValidationTag.CALIBRATION in tag_set and run is None and not datasets:
        raise ValidationError("calibration requires a dataset or recorded run")

    if ValidationTag.INTERNAL_CONSISTENCY in tag_set:
        require_eligible_run(ValidationTag.INTERNAL_CONSISTENCY)

    if ValidationTag.CONTROLLED_BENCHMARK in tag_set:
        require_eligible_run(ValidationTag.CONTROLLED_BENCHMARK)
        if protocol is None or not protocol.controls:
            raise ValidationError(
                "controlled_benchmark requires a protocol with registered controls"
            )
        if not controls_passed:
            raise ValidationError(
                "controlled_benchmark requires at least one recorded passed control"
            )

    if ValidationTag.INDEPENDENT_REPLICATION in tag_set:
        current = require_eligible_run(ValidationTag.INDEPENDENT_REPLICATION)
        if current.analysis_mode is not AnalysisMode.REPLICATION:
            raise ValidationError(
                "independent_replication requires a replication-mode run"
            )
        if replicated_run is None:
            raise ValidationError(
                "independent_replication requires run metadata.replicates_run_id"
            )
        if not replicated_run.scientific_evidence_eligible:
            raise ValidationError(
                "independent_replication target must be an eligible recorded run"
            )
        if current.executed_by == replicated_run.executed_by:
            raise ValidationError(
                "independent_replication requires a different executor identity"
            )
        if current.analysis_code_hash == replicated_run.analysis_code_hash:
            raise ValidationError(
                "independent_replication requires a distinct analysis-code hash"
            )
        independence = current.metadata.get("replication_independence")
        if not isinstance(independence, dict):
            raise ValidationError(
                "independent_replication requires run metadata.replication_independence"
            )
        if independence.get("design") != "clean_room":
            raise ValidationError(
                "independent_replication requires a clean_room replication design"
            )
        dimensions_input = independence.get("independence_dimensions", [])
        if isinstance(dimensions_input, (str, bytes)) or not isinstance(
            dimensions_input, Sequence
        ):
            raise ValidationError(
                "replication_independence.independence_dimensions must be a list of text values"
            )
        dimensions = [
            require_canonical_text(
                value, "replication_independence.independence_dimensions item"
            )
            for value in dimensions_input
        ]
        if len(set(dimensions)) != len(dimensions):
            raise ValidationError(
                "replication_independence.independence_dimensions must not contain duplicates"
            )
        missing_dimensions = {"executor", "implementation"} - set(dimensions)
        if missing_dimensions:
            raise ValidationError(
                "independent_replication requires executor and implementation "
                "independence dimensions"
            )
        if independence.get("prior_implementation_accessed") is not False:
            raise ValidationError(
                "independent_replication requires an explicit false "
                "prior_implementation_accessed declaration"
            )
        allowed_inputs = independence.get("allowed_inputs")
        if not isinstance(allowed_inputs, list) or not allowed_inputs:
            raise ValidationError(
                "independent_replication requires a non-empty allowed_inputs manifest"
            )
        allowed_input_keys: set[tuple[str, str]] = set()
        for index, item in enumerate(allowed_inputs):
            if not isinstance(item, dict):
                raise ValidationError(
                    "replication_independence.allowed_inputs items must be objects"
                )
            locator = require_canonical_text(
                item.get("locator", ""),
                f"replication_independence.allowed_inputs[{index}].locator",
            )
            digest = require_sha256(
                item.get("sha256", ""),
                f"replication_independence.allowed_inputs[{index}].sha256",
            )
            allowed_input_keys.add((locator, digest))
        if len(allowed_input_keys) != len(allowed_inputs):
            raise ValidationError(
                "replication_independence.allowed_inputs must not contain duplicates"
            )
        disclosures = independence.get("contamination_disclosures")
        if not isinstance(disclosures, list):
            raise ValidationError(
                "independent_replication requires a contamination_disclosures list"
            )
        if isinstance(disclosures, (str, bytes)) or not isinstance(
            disclosures, Sequence
        ):
            raise ValidationError(
                "independent_replication requires a contamination_disclosures list"
            )
        normalized_disclosures = [
            require_canonical_text(
                value, "replication_independence.contamination_disclosures item"
            )
            for value in disclosures
        ]
        if len(set(normalized_disclosures)) != len(normalized_disclosures):
            raise ValidationError(
                "replication_independence.contamination_disclosures must not contain duplicates"
            )
        attestation_locator = require_canonical_text(
            independence.get("attestation_artifact", ""),
            "replication_independence.attestation_artifact",
        )
        matching_attestations = [
            artifact
            for artifact in current.output_artifacts
            if artifact.locator == attestation_locator
            and artifact.metadata.get("artifact_role") == "independence_attestation"
        ]
        if not matching_attestations:
            raise ValidationError(
                "independent_replication requires a hashed output artifact matching "
                "attestation_artifact with artifact_role=independence_attestation"
            )
        artifact_integrity = current.metadata.get("artifact_integrity")
        if not isinstance(artifact_integrity, dict):
            raise ValidationError(
                "independent_replication requires machine-verified artifact_integrity"
            )
        if (
            artifact_integrity.get("status") != "passed"
            or artifact_integrity.get("all_artifacts_match") is not True
            or artifact_integrity.get("attestation_schema_matches_commitment")
            is not True
            or artifact_integrity.get("attestation_schema_valid") is not True
            or artifact_integrity.get("attestation_consistent") is not True
        ):
            raise ValidationError(
                "independent_replication requires passed artifact bytes, pinned "
                "attestation schema validation, and run-attestation consistency"
            )

    if ValidationTag.KNOWN_RESULT_REPRODUCTION in tag_set:
        current = require_eligible_run(ValidationTag.KNOWN_RESULT_REPRODUCTION)
        passed_gate_ids = {
            gate.gate_id
            for gate in current.quality_gates
            if gate.status is QualityGateStatus.PASSED
        }
        if "known-result-reproduction" not in passed_gate_ids:
            raise ValidationError(
                "known_result_reproduction requires a passed "
                "known-result-reproduction quality gate"
            )

    if ValidationTag.NOVEL_PREDICTION in tag_set:
        current = require_eligible_run(ValidationTag.NOVEL_PREDICTION)
        if (
            exploratory
            or hypothesis.workflow_state is not HypothesisWorkflowState.ACTIVE
        ):
            raise ValidationError(
                "novel_prediction requires confirmatory evidence for an active hypothesis"
            )
        if current.analysis_mode is not AnalysisMode.CONFIRMATORY:
            raise ValidationError("novel_prediction requires a confirmatory-mode run")
        if protocol is None or not protocol.registration_timestamp:
            raise ValidationError(
                "novel_prediction requires a frozen protocol timestamp"
            )

    if ValidationTag.EMPIRICAL_TEST in tag_set:
        require_eligible_run(ValidationTag.EMPIRICAL_TEST)
        if (
            exploratory
            or hypothesis.workflow_state is not HypothesisWorkflowState.ACTIVE
        ):
            raise ValidationError(
                "empirical_test requires confirmatory evidence for an active hypothesis"
            )
        if protocol is None or protocol.protocol_kind not in {
            ProtocolKind.OBSERVATIONAL,
            ProtocolKind.EXPERIMENTAL,
        }:
            raise ValidationError(
                "empirical_test requires an observational or experimental protocol"
            )
        if not datasets:
            raise ValidationError(
                "empirical_test requires at least one recorded dataset"
            )
        if any(dataset.synthetic for dataset in datasets):
            raise ValidationError("empirical_test cannot use synthetic data")

    if ValidationTag.CAUSAL_ESTIMATE in tag_set:
        current = require_eligible_run(ValidationTag.CAUSAL_ESTIMATE)
        if claim is None or claim.level is not ClaimLevel.CAUSAL_DIRECTION:
            raise ValidationError(
                "causal_estimate requires evidence attached to an exact causal-direction claim"
            )
        if ValidationTag.EMPIRICAL_TEST not in tag_set:
            raise ValidationError("causal_estimate also requires the empirical_test tag")
        if exploratory or current.analysis_mode is AnalysisMode.EXPLORATORY:
            raise ValidationError("causal_estimate requires confirmatory or replication evidence")
        if protocol is None or not protocol.causal_claim:
            raise ValidationError("causal_estimate requires a frozen causal protocol")
        causal_estimand = protocol.causal_identification_audit.get("causal_estimand")
        if (
            not isinstance(causal_estimand, dict)
            or causal_estimand.get("target_hypothesis_id") != hypothesis.hypothesis_id
        ):
            raise ValidationError(
                "causal_estimate hypothesis must match the frozen causal estimand target"
            )
        if protocol.analysis_contract is None:
            raise ValidationError("causal_estimate requires a frozen analysis contract")
        if (
            protocol.causal_identification_audit.get("assignment_type")
            == "observational"
            and protocol.analysis_contract.adjustment_columns
            != protocol.causal_identification_audit.get("proposed_adjustment_set")
        ):
            raise ValidationError(
                "causal_estimate analysis covariates do not match the frozen adjustment set"
            )
        handoff = current.metadata.get("execution_handoff")
        if not isinstance(handoff, dict) or not isinstance(handoff.get("result"), dict):
            raise ValidationError("causal_estimate requires a verified execution handoff")
        if handoff["result"].get("maximum_inference_level") != "design_conditional_effect":
            raise ValidationError(
                "executed method does not permit a design-conditional effect estimate"
            )


def validate_dataset_artifacts(
    artifacts: Sequence[DatasetArtifact],
) -> list[DatasetArtifact]:
    if isinstance(artifacts, (str, bytes)) or not isinstance(artifacts, Sequence):
        raise ValidationError("artifacts must be a list")
    if not artifacts:
        raise ValidationError("a dataset must contain at least one hashed artifact")
    normalized: list[DatasetArtifact] = []
    locators: set[str] = set()
    digests: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, DatasetArtifact):
            raise ValidationError("artifacts must be DatasetArtifact values")
        locator = require_canonical_text(artifact.locator, "artifact locator")
        digest = require_sha256(artifact.sha256, "artifact sha256")
        if artifact.size_bytes is not None and (
            isinstance(artifact.size_bytes, bool)
            or not isinstance(artifact.size_bytes, int)
            or artifact.size_bytes < 0
        ):
            raise ValidationError("artifact size_bytes must be non-negative or null")
        if not isinstance(artifact.metadata, dict):
            raise ValidationError("artifact metadata must be an object")
        if locator in locators:
            raise ValidationError(f"duplicate artifact locator: {locator}")
        if digest in digests:
            raise ValidationError(f"duplicate artifact digest: {digest}")
        locators.add(locator)
        digests.add(digest)
        media_type = normalize_text(artifact.media_type, "artifact media_type")
        if media_type != artifact.media_type:
            raise ValidationError(
                "artifact media_type must be canonical without surrounding whitespace"
            )
        normalized.append(
            DatasetArtifact(
                locator=locator,
                sha256=digest,
                size_bytes=artifact.size_bytes,
                media_type=media_type,
                metadata=dict(artifact.metadata),
            )
        )
    return normalized


def validate_planning_inference_coherence(
    *, sample_size_plan: dict[str, Any], analysis_contract: AnalysisContract,
    expected_direction: str, multiplicity_alpha: float | None,
    measurement_unit: str,
    smallest_effect_size_of_interest: float | None,
    maximum_excluded_fraction: float,
    multiplicity_method: str = "single_test",
) -> None:
    """Require prospective planning assumptions to match registered inference."""
    if sample_size_plan.get("target_hypothesis_id") != analysis_contract.primary_hypothesis_id:
        raise ValidationError(
            "sample_size_plan target_hypothesis_id must match the analysis contract"
        )
    if sample_size_plan.get("target_measurement_id") != analysis_contract.primary_measurement_id:
        raise ValidationError(
            "sample_size_plan target_measurement_id must match the analysis contract"
        )
    if sample_size_plan.get("measurement_unit") != measurement_unit:
        raise ValidationError(
            "sample_size_plan measurement_unit must match the primary measurement"
        )
    if analysis_contract.method != "independent_mean_difference_ci":
        raise ValidationError(
            "two-group sample_size_plan requires analysis_contract.method independent_mean_difference_ci"
        )
    calculation = sample_size_plan["calculation"]
    anticipated_attrition = calculation["anticipated_attrition_fraction"]
    if anticipated_attrition > float(maximum_excluded_fraction):
        raise ValidationError(
            "sample_size_plan anticipated attrition exceeds the analysis contract maximum excluded fraction"
        )
    strategy = sample_size_plan["strategy"]
    if strategy == "precision":
        if analysis_contract.confidence_level is None:
            raise ValidationError(
                "a precision sample_size_plan requires analysis_contract.confidence_level"
            )
        if float(analysis_contract.confidence_level) != calculation["confidence_level"]:
            raise ValidationError(
                "precision sample_size_plan confidence level must match the analysis contract"
            )
        return
    if strategy == "equivalence_power":
        if expected_direction != "equivalence":
            raise ValidationError(
                "equivalence_power sample_size_plan requires an equivalence hypothesis"
            )
        if multiplicity_method != "single_test":
            raise ValidationError(
                "equivalence_power supports only a direct single-test decision"
            )
        if multiplicity_alpha is None or float(multiplicity_alpha) != calculation["alpha"]:
            raise ValidationError(
                "equivalence_power sample_size_plan alpha must match the protocol multiplicity_alpha"
            )
        if smallest_effect_size_of_interest is None or (
            float(smallest_effect_size_of_interest)
            != calculation["equivalence_margin"]
        ):
            raise ValidationError(
                "equivalence_power margin must match the conclusion contract"
            )
        if (
            analysis_contract.confidence_level is None
            or float(analysis_contract.confidence_level)
            != calculation["confidence_level"]
        ):
            raise ValidationError(
                "equivalence_power confidence level must match the analysis contract"
            )
        return
    if strategy == "power":
        raise ValidationError(
            "ordinary difference-test power cannot govern practical-significance conclusions; use practical_power"
        )
    if expected_direction not in {"positive", "negative", "two_sided"}:
        raise ValidationError(
            "practical_power requires a directional primary hypothesis"
        )
    if calculation["alternative"] != expected_direction:
        raise ValidationError(
            "practical_power alternative must match the primary hypothesis expected direction"
        )
    if multiplicity_method != "single_test":
        raise ValidationError(
            "practical_power supports only a direct single-test decision"
        )
    if multiplicity_alpha is None or float(multiplicity_alpha) != calculation["alpha"]:
        raise ValidationError(
            "practical_power alpha must match the protocol multiplicity_alpha"
        )
    if smallest_effect_size_of_interest is None or float(
        smallest_effect_size_of_interest
    ) != calculation["smallest_effect_size_of_interest"]:
        raise ValidationError(
            "practical_power smallest effect must match the conclusion contract"
        )
    if analysis_contract.confidence_level is None or float(
        analysis_contract.confidence_level
    ) != calculation["confidence_level"]:
        raise ValidationError(
            "practical_power confidence level must match the analysis contract"
        )


def validate_equivalence_design_coherence(
    *, analysis_contract: AnalysisContract,
    conclusion_contract: ConclusionContract | None,
    expected_direction: str, multiplicity_method: str,
    multiplicity_alpha: float | None,
) -> None:
    """Bind equivalence intent, margin rule, and TOST-compatible interval level."""
    equivalence = expected_direction == "equivalence"
    if equivalence != (
        analysis_contract.support_rule == "interval_within_equivalence_margin"
    ):
        raise ValidationError(
            "equivalence hypothesis and analysis support rule must be declared together"
        )
    if equivalence != (
        conclusion_contract is not None
        and conclusion_contract.decision_rule == "equivalence_interval_within_margin"
    ):
        raise ValidationError(
            "equivalence hypothesis and conclusion decision rule must be declared together"
        )
    if not equivalence:
        return
    if multiplicity_method != "single_test":
        raise ValidationError(
            "equivalence currently requires multiplicity_method single_test"
        )
    if (
        multiplicity_alpha is None
        or analysis_contract.confidence_level is None
        or not math.isclose(
            float(analysis_contract.confidence_level),
            1 - 2 * float(multiplicity_alpha), rel_tol=0.0, abs_tol=1e-12,
        )
    ):
        raise ValidationError(
            "equivalence confidence level must equal one minus twice the frozen alpha"
        )


def assess_precision_achievement(
    sample_size_plan: dict[str, Any], uncertainty: Any,
) -> dict[str, Any]:
    """Compare an executed interval with a frozen precision target."""
    if sample_size_plan.get("strategy") != "precision":
        return {"status": "not_applicable", "reason": "not a precision plan"}
    target = sample_size_plan["calculation"]["target_half_width"]
    if not isinstance(uncertainty, dict):
        return {
            "status": "unverified", "target_half_width": target,
            "reason": "no verified primary confidence interval was available",
        }
    lower = uncertainty.get("lower")
    upper = uncertainty.get("upper")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(float(value)) for value in (lower, upper)
    ) or float(lower) > float(upper):
        return {
            "status": "unverified", "target_half_width": target,
            "reason": "verified primary uncertainty was not a finite ordered interval",
        }
    observed = (float(upper) - float(lower)) / 2
    return {
        "status": "met" if observed <= target else "not_met",
        "target_half_width": target,
        "observed_half_width": observed,
        "measurement_unit": sample_size_plan.get("measurement_unit"),
        "scientific_interpretation_verified": False,
    }


def assess_attrition_achievement(
    sample_size_plan: dict[str, Any], information_check: Any,
) -> dict[str, Any]:
    """Compare observed exclusions with the prospective attrition assumption."""
    anticipated = sample_size_plan["calculation"]["anticipated_attrition_fraction"]
    if not isinstance(information_check, dict) or information_check.get("status") != "passed":
        return {
            "status": "unverified",
            "anticipated_attrition_fraction": anticipated,
            "reason": "no passed registered information check was available",
        }
    observed = information_check["observed_excluded_fraction"]
    return {
        "status": (
            "within_assumption" if observed <= anticipated
            else "exceeded_assumption"
        ),
        "anticipated_attrition_fraction": anticipated,
        "observed_excluded_fraction": observed,
        "registered_maximum_excluded_fraction": information_check[
            "registered_maximum_excluded_fraction"
        ],
        "observed_excluded_fraction_by_group": information_check[
            "observed_excluded_fraction_by_group"
        ],
        "observed_group_excluded_fraction_difference": information_check[
            "observed_group_excluded_fraction_difference"
        ],
        "registered_maximum_group_excluded_fraction_difference": information_check[
            "registered_maximum_group_excluded_fraction_difference"
        ],
        "scientific_interpretation_verified": False,
    }


def assess_variance_assumption(
    sample_size_plan: dict[str, Any], observed_standard_deviation: Any,
) -> dict[str, Any]:
    """Expose observed variability without inventing an adequacy threshold."""
    assumed = sample_size_plan["calculation"]["assumed_standard_deviation"]
    if (
        isinstance(observed_standard_deviation, bool)
        or not isinstance(observed_standard_deviation, (int, float))
        or not math.isfinite(float(observed_standard_deviation))
        or float(observed_standard_deviation) < 0
    ):
        return {
            "status": "unverified", "assumed_standard_deviation": assumed,
            "reason": "verified primary analysis did not expose a finite observed standard deviation",
        }
    observed = float(observed_standard_deviation)
    ratio = observed / assumed
    maximum_ratio = sample_size_plan["calculation"].get(
        "maximum_observed_to_assumed_sd_ratio"
    )
    return {
        "status": (
            "observed_no_preregistered_tolerance" if maximum_ratio is None
            else "within_registered_tolerance" if ratio <= maximum_ratio
            else "exceeded_registered_tolerance"
        ),
        "assumed_standard_deviation": assumed,
        "observed_pooled_standard_deviation": observed,
        "observed_to_assumed_ratio": ratio,
        "maximum_registered_ratio": maximum_ratio,
        "measurement_unit": sample_size_plan.get("measurement_unit"),
        "adequacy_threshold_registered": maximum_ratio is not None,
        "scientific_interpretation_verified": False,
    }


def validate_protocol_freeze(protocol: ExperimentProtocol) -> None:
    _reject_review_placeholders(protocol.to_dict(), "protocol")
    validate_runtime_preflight_requirement(protocol.runtime_preflight_requirement)
    validate_notebook_freeze_input_bundle_requirement(
        protocol.notebook_freeze_input_bundle_sha256,
        protocol.runtime_preflight_requirement,
    )
    lowered_inputs = [value.casefold() for value in protocol.inputs_required]
    if (
        protocol.runtime_preflight_requirement is None
        and any("runtime preflight" in value for value in lowered_inputs)
    ):
        raise ValidationError(
            "runtime preflight inputs require runtime_preflight_requirement; "
            "prose digests have no binding authority"
        )
    if (
        protocol.notebook_freeze_input_bundle_sha256 is None
        and any("freeze-input bundle" in value for value in lowered_inputs)
    ):
        raise ValidationError(
            "freeze-input bundle inputs require "
            "notebook_freeze_input_bundle_sha256; prose digests have no binding authority"
        )
    if protocol.status is not ProtocolStatus.DRAFT:
        raise ValidationError("only draft protocols can be frozen")
    if not isinstance(protocol.causal_claim, bool):
        raise ValidationError("causal_claim must be true or false")
    if not isinstance(protocol.factorial_or_crossover_design, bool):
        raise ValidationError("factorial_or_crossover_design must be true or false")
    manipulated_factors = require_unique_canonical_text_list(
        protocol.manipulated_factors,
        "manipulated_factors",
    )
    factor_plan = normalize_text(
        protocol.factor_interpretability_plan,
        "factor_interpretability_plan",
    )
    if factor_plan != protocol.factor_interpretability_plan:
        raise ValidationError(
            "factor_interpretability_plan must be canonical without surrounding whitespace"
        )
    if protocol.factorial_or_crossover_design and not manipulated_factors:
        raise ValidationError(
            "factorial_or_crossover_design cannot be declared without manipulated_factors"
        )
    if protocol.factorial_or_crossover_design and not factor_plan:
        raise ValidationError(
            "factorial_or_crossover_design requires a factor_interpretability_plan"
        )
    if len(manipulated_factors) > 1 and (
        not protocol.factorial_or_crossover_design or not factor_plan
    ):
        raise ValidationError(
            "multi-factor interventions require a factorial or crossover design "
            "and factor_interpretability_plan"
        )
    quality_requirement_ids = []
    for gate_id in protocol.quality_requirements:
        canonical_gate_id = require_text(gate_id, "quality_requirements item")
        if canonical_gate_id != gate_id:
            raise ValidationError(
                "quality_requirements items must be canonical without surrounding whitespace"
            )
        quality_requirement_ids.append(canonical_gate_id)
    quality_requirement_set = set(quality_requirement_ids)
    if protocol.causal_claim:
        from research_machine.design.causal import audit_causal_identification

        if not protocol.causal_identification:
            raise ValidationError(
                "causal protocols require a causal identification specification"
            )
        causal_audit = audit_causal_identification(protocol.causal_identification)
        violation_codes = [item["code"] for item in causal_audit["violations"]]
        if violation_codes:
            raise ValidationError(
                "causal identification is blocked by: " + ", ".join(violation_codes)
            )
        if (
            protocol.protocol_kind is ProtocolKind.OBSERVATIONAL
            and causal_audit["assignment_type"] != "observational"
        ):
            raise ValidationError(
                "observational causal protocols require observational graph assignment"
            )
        if (
            causal_audit["assignment_type"] == "observational"
            and causal_audit["backdoor_criterion_satisfied"] is not True
        ):
            raise ValidationError(
                "observational causal protocols must satisfy the backdoor criterion"
            )
        if protocol.causal_identification_audit != causal_audit:
            raise ValidationError(
                "causal_identification_audit must exactly match the deterministic audit of the supplied graph"
            )
        causal_estimand = causal_audit["causal_estimand"]
        if causal_estimand["target_hypothesis_id"] not in protocol.hypotheses_tested:
            raise ValidationError(
                "causal estimand target_hypothesis_id must name a tested hypothesis"
            )
        if (
            protocol.analysis_contract is not None
            and protocol.analysis_contract.primary_hypothesis_id
            != causal_estimand["target_hypothesis_id"]
        ):
            raise ValidationError(
                "causal estimand and analysis contract must select the same primary hypothesis"
            )
        if (
            protocol.analysis_contract is not None
            and protocol.analysis_contract.estimand != causal_estimand["description"]
        ):
            raise ValidationError(
                "causal estimand description must match the frozen analysis contract estimand"
            )
        if (
            causal_audit["assignment_type"] == "observational"
            and protocol.analysis_contract is not None
            and protocol.analysis_contract.adjustment_columns
            != causal_audit["proposed_adjustment_set"]
        ):
            raise ValidationError(
                "observational causal analysis adjustment_columns must exactly match "
                "the audited proposed_adjustment_set"
            )
        if protocol.analysis_contract is not None and (
            protocol.analysis_contract.group_column != causal_audit["exposure"]
            or protocol.analysis_contract.outcome_column != causal_audit["outcome"]
        ):
            raise ValidationError(
                "causal analysis group and outcome columns must exactly match the audited "
                "exposure and outcome nodes"
            )
        missing_assessment_gates = sorted({
            item["assessment_gate_id"]
            for item in causal_audit["assumption_register"]
        } - quality_requirement_set)
        if missing_assessment_gates:
            raise ValidationError(
                "causal assumption assessment gates must be protocol quality requirements: "
                + ", ".join(missing_assessment_gates)
            )
    elif protocol.causal_identification or protocol.causal_identification_audit:
        raise ValidationError("causal identification requires causal_claim true")
    empirical = protocol.protocol_kind in {ProtocolKind.OBSERVATIONAL, ProtocolKind.EXPERIMENTAL}
    if empirical or protocol.independent_unit or protocol.repeated_measures is not None or protocol.analysis_design:
        if not protocol.independent_unit.strip() or type(protocol.repeated_measures) is not bool or protocol.analysis_design not in {"independent_groups", "paired", "clustered", "repeated_measures", "descriptive"}:
            raise ValidationError("structured design requires independent_unit, boolean repeated_measures, and a supported analysis_design")
        if protocol.repeated_measures and protocol.analysis_design == "independent_groups":
            raise ValidationError("repeated observations cannot use an independent-groups analysis; review dependence or preregister unit-level aggregation")
        if (protocol.repeated_measures or protocol.analysis_design in {"paired", "clustered", "repeated_measures"}) and not protocol.unit_analysis_plan.strip():
            raise ValidationError("paired, clustered, or repeated observations require a unit_analysis_plan defining how rows map to the independent-unit estimand")
        if protocol.analysis_specification_sha256 and not protocol.unit_id_column.strip():
            raise ValidationError("protocols with a pinned analysis specification require a unit_id_column")
        if empirical and protocol.analysis_specification_sha256 and protocol.analysis_contract is None:
            raise ValidationError("empirical protocols with a pinned analysis specification require an analysis_contract")
    if protocol.analysis_contract is not None:
        contract = protocol.analysis_contract
        if not isinstance(contract, AnalysisContract):
            raise ValidationError("analysis_contract must be an AnalysisContract")

        def require_canonical_contract_text(value: object, field: str) -> str:
            text = require_text(value, field)
            if text != value:
                raise ValidationError(
                    f"{field} must be canonical without surrounding whitespace"
                )
            return text

        def require_canonical_contract_list(
            values: Sequence[object], field: str
        ) -> list[str]:
            canonical_values = require_unique_text_list(values, field)
            if list(values) != canonical_values:
                raise ValidationError(
                    f"{field} items must be canonical without surrounding whitespace"
                )
            return canonical_values

        for name in (
            "primary_hypothesis_id",
            "primary_measurement_id",
            "method",
            "outcome_column",
            "group_column",
            "estimand",
            "missing_data_policy",
            "assignment_type",
            "effect_estimate_path",
            "uncertainty_path",
            "missingness_assumption",
            "missingness_assessment_plan",
            "missingness_failure_response",
            "missingness_assessment_kind",
            "missingness_assessment_gate_id",
        ):
            require_canonical_contract_text(
                getattr(contract, name), f"analysis_contract.{name}"
            )
        if contract.contrast_definition:
            require_canonical_contract_text(
                contract.contrast_definition,
                "analysis_contract.contrast_definition",
            )
        if contract.missingness_assessment_kind not in {
            "empirical_diagnostic", "design_record_review", "external_validation",
            "substantive_judgment",
        }:
            raise ValidationError(
                "analysis_contract.missingness_assessment_kind is unsupported"
            )
        if contract.missingness_assessment_gate_id not in quality_requirement_set:
            raise ValidationError(
                "analysis_contract.missingness_assessment_gate_id must name a required quality gate"
            )
        occupied_gate_ids = {
            control.evaluation_gate_id for control in protocol.control_definitions
        }
        if protocol.causal_claim:
            occupied_gate_ids.update(
                item["assessment_gate_id"]
                for item in protocol.causal_identification_audit.get(
                    "assumption_register", []
                )
            )
        if contract.missingness_assessment_gate_id in occupied_gate_ids:
            raise ValidationError(
                "analysis_contract.missingness_assessment_gate_id must be dedicated "
                "and cannot also evaluate a control or causal assumption"
            )
        for name in ("effect_estimate_path", "uncertainty_path"):
            if not getattr(contract, name).startswith("/"):
                raise ValidationError(f"analysis_contract.{name} must be an absolute JSON Pointer")
        if contract.effect_estimate_path == contract.uncertainty_path:
            raise ValidationError("analysis contract effect and uncertainty selectors must be distinct")
        if isinstance(contract.null_value, bool) or not isinstance(contract.null_value, (int, float)) or not math.isfinite(float(contract.null_value)):
            raise ValidationError("analysis_contract.null_value must be a finite number")
        if contract.support_rule not in {
            "point_direction", "interval_excludes_null",
            "interval_within_equivalence_margin",
        }:
            raise ValidationError("analysis_contract.support_rule is unsupported")
        if contract.confidence_level is not None and (
            isinstance(contract.confidence_level, bool)
            or not isinstance(contract.confidence_level, (int, float))
            or not math.isfinite(float(contract.confidence_level))
            or not 0 < float(contract.confidence_level) < 1
        ):
            raise ValidationError(
                "analysis_contract.confidence_level must be finite and strictly between zero and one"
            )
        if type(contract.minimum_analyzable_units) is not int or contract.minimum_analyzable_units < 2:
            raise ValidationError("analysis_contract.minimum_analyzable_units must be an integer of at least two")
        if (isinstance(contract.maximum_excluded_fraction, bool)
                or not isinstance(contract.maximum_excluded_fraction, (int, float))
                or not math.isfinite(float(contract.maximum_excluded_fraction))
                or not 0 <= float(contract.maximum_excluded_fraction) < 1):
            raise ValidationError("analysis_contract.maximum_excluded_fraction must be in [0, 1)")
        if (
            isinstance(contract.maximum_group_excluded_fraction_difference, bool)
            or not isinstance(
                contract.maximum_group_excluded_fraction_difference, (int, float)
            )
            or not math.isfinite(
                float(contract.maximum_group_excluded_fraction_difference)
            )
            or not 0 <= float(
                contract.maximum_group_excluded_fraction_difference
            ) <= 1
        ):
            raise ValidationError(
                "analysis_contract.maximum_group_excluded_fraction_difference "
                "must be in [0, 1]"
            )
        if contract.primary_hypothesis_id not in protocol.hypotheses_tested:
            raise ValidationError("analysis_contract.primary_hypothesis_id must name a tested hypothesis")
        groups = require_canonical_contract_list(
            contract.groups, "analysis_contract.groups"
        )
        if len(groups) != 2:
            raise ValidationError("analysis_contract.groups must contain exactly two distinct levels")
        if not contract.contrast_definition:
            raise ValidationError(
                "analysis_contract.contrast_definition must declare the signed contrast"
            )
        contrast_groups = require_canonical_contract_list(
            contract.contrast_groups, "analysis_contract.contrast_groups"
        )
        if contrast_groups != groups:
            raise ValidationError(
                "analysis_contract.contrast_groups must exactly match the executable group order"
            )
        require_canonical_contract_list(
            contract.adjustment_columns, "analysis_contract.adjustment_columns"
        )
        if contract.missing_data_policy != "complete_case":
            raise ValidationError("analysis_contract currently supports only complete_case missing-data handling")
        allowed_assignment_types = {"observational", "randomized_between_units", "nonrandomized", "not_applicable"}
        if contract.assignment_type not in allowed_assignment_types:
            raise ValidationError("analysis_contract.assignment_type is unsupported")
        if protocol.protocol_kind is ProtocolKind.OBSERVATIONAL and contract.assignment_type != "observational":
            raise ValidationError("observational protocols require assignment_type observational")
        if protocol.protocol_kind is ProtocolKind.EXPERIMENTAL and contract.assignment_type == "observational":
            raise ValidationError("experimental protocols cannot use assignment_type observational")
        if contract.assignment_type == "randomized_between_units":
            require_sha256(contract.allocation_sha256, "analysis_contract.allocation_sha256")
            if protocol.repeated_measures:
                raise ValidationError("randomized_between_units currently requires one observed row per independent unit")
        elif contract.allocation_sha256:
            raise ValidationError("allocation_sha256 is only valid for randomized_between_units assignment")
        if not protocol.measurement_definitions:
            raise ValidationError("analysis_contract requires typed measurement_definitions")
        if protocol.unit_id_column:
            structural_columns = [
                "observation_id",
                protocol.unit_id_column,
                contract.group_column,
                "captured_at",
            ]
            normalized_structural_columns = [
                require_text(column, "structural column").casefold()
                for column in structural_columns
            ]
            if len(set(normalized_structural_columns)) != len(
                normalized_structural_columns
            ):
                raise ValidationError(
                    "protocol structural columns for identity, unit, assignment, "
                    "and capture time must be distinct"
                )
    missing: list[str] = []
    required_text = {
        "experiment_id": protocol.experiment_id,
        "title": protocol.title,
        "primary_outcome": protocol.primary_outcome,
        "methodology": protocol.methodology,
        "analysis_code_hash": protocol.analysis_code_hash,
    }
    if protocol.protocol_kind in {
        ProtocolKind.OBSERVATIONAL,
        ProtocolKind.EXPERIMENTAL,
    }:
        required_text.update(
            {
                "sampling_unit": protocol.sampling_unit,
                "sample_size_or_stopping_rule": (protocol.sample_size_or_stopping_rule),
                "preprocessing_pipeline": protocol.preprocessing_pipeline,
                "statistical_model": protocol.statistical_model,
                "multiple_testing_policy": protocol.multiple_testing_policy,
                "missing_data_policy": protocol.missing_data_policy,
            }
        )
    if protocol.protocol_kind is ProtocolKind.EXPERIMENTAL:
        required_text.update(
            {
                "randomization_plan": protocol.randomization_plan,
                "blinding_plan": protocol.blinding_plan,
            }
        )
    secondary_outcomes = require_unique_text_list(
        protocol.secondary_outcomes, "secondary_outcomes"
    )
    outcome_names = [require_text(protocol.primary_outcome, "primary_outcome"), *secondary_outcomes]
    if len({item.casefold() for item in outcome_names}) != len(outcome_names):
        raise ValidationError(
            "primary_outcome and secondary_outcomes must be distinct ignoring case"
        )
    multiplicity_plan_supplied = bool(
        protocol.confirmatory_outcomes
        or protocol.exploratory_outcomes
        or protocol.multiplicity_method
        or protocol.multiplicity_alpha is not None
    )
    if secondary_outcomes or multiplicity_plan_supplied:
        confirmatory = require_unique_text_list(
            protocol.confirmatory_outcomes, "confirmatory_outcomes"
        )
        exploratory = require_unique_text_list(
            protocol.exploratory_outcomes, "exploratory_outcomes"
        )
        if set(confirmatory) & set(exploratory):
            raise ValidationError(
                "confirmatory_outcomes and exploratory_outcomes must be disjoint"
            )
        if set(confirmatory) | set(exploratory) != set(outcome_names):
            raise ValidationError(
                "typed multiplicity outcomes must exactly partition the primary and secondary outcomes"
            )
        if protocol.analysis_mode is AnalysisMode.EXPLORATORY:
            if confirmatory or exploratory != outcome_names:
                raise ValidationError(
                    "exploratory protocols must classify every outcome as exploratory in registered order"
                )
            if protocol.multiplicity_method != "exploratory_only" or protocol.multiplicity_alpha is not None:
                raise ValidationError(
                    "exploratory outcome plans require multiplicity_method exploratory_only and no alpha"
                )
        else:
            if protocol.primary_outcome not in confirmatory:
                raise ValidationError(
                    "confirmatory and replication protocols must classify the primary outcome as confirmatory"
                )
            expected_method = "single_test" if len(confirmatory) == 1 else "holm"
            if protocol.multiplicity_method != expected_method:
                raise ValidationError(
                    f"typed multiplicity plan for {len(confirmatory)} confirmatory outcome(s) requires {expected_method}"
                )
            if (
                isinstance(protocol.multiplicity_alpha, bool)
                or not isinstance(protocol.multiplicity_alpha, (int, float))
                or not math.isfinite(float(protocol.multiplicity_alpha))
                or not 0 < float(protocol.multiplicity_alpha) < 1
            ):
                raise ValidationError(
                    "typed confirmatory multiplicity plan requires a finite alpha strictly between zero and one"
                )
    if any(not isinstance(item, AnalysisStepContract) for item in protocol.analysis_steps):
        raise ValidationError("analysis_steps must contain AnalysisStepContract values")
    if protocol.analysis_steps:
        def require_canonical_analysis_text(value: object, field: str) -> str:
            text = require_text(value, field)
            if text != value:
                raise ValidationError(
                    f"{field} must be canonical without surrounding whitespace"
                )
            return text

        def require_canonical_analysis_list(
            values: Sequence[object], field: str
        ) -> list[str]:
            texts = require_unique_text_list(values, field)
            if list(values) != texts:
                raise ValidationError(
                    f"{field} items must be canonical without surrounding whitespace"
                )
            return texts

        step_ids: list[str] = []
        steps_by_id: dict[str, AnalysisStepContract] = {}
        for index, step in enumerate(protocol.analysis_steps):
            prefix = f"analysis_steps[{index}]"
            step_id = require_canonical_analysis_text(step.step_id, f"{prefix}.step_id")
            if step_id in steps_by_id:
                raise ValidationError(f"duplicate analysis step_id: {step_id}")
            if step.role not in {"primary_estimate", "confirmatory_test", "exploratory_analysis", "diagnostic", "sensitivity", "multiplicity"}:
                raise ValidationError(f"{prefix}.role is unsupported")
            require_text(step.method, f"{prefix}.method")
            require_sha256(step.specification_sha256, f"{prefix}.specification_sha256")
            require_sha256(step.implementation_sha256, f"{prefix}.implementation_sha256")
            dependencies = require_canonical_analysis_list(
                step.depends_on, f"{prefix}.depends_on"
            )
            if step_id in dependencies:
                raise ValidationError(f"{prefix} cannot depend on itself")
            step_ids.append(step_id)
            steps_by_id[step_id] = step
        unknown_dependencies = sorted({
            dependency for step in protocol.analysis_steps for dependency in step.depends_on
            if dependency not in steps_by_id
        })
        if unknown_dependencies:
            raise ValidationError(
                "analysis steps reference unknown dependencies: " + ", ".join(unknown_dependencies)
            )
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValidationError("analysis_steps dependency graph must be acyclic")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in steps_by_id[step_id].depends_on:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)
        for step_id in step_ids:
            visit(step_id)

        measurement_by_id = {
            item.measurement_id: item for item in protocol.measurement_definitions
        }
        source_steps = [
            step for step in protocol.analysis_steps
            if step.role in {"primary_estimate", "confirmatory_test", "exploratory_analysis"}
        ]
        for step in source_steps:
            require_text(step.hypothesis_id, f"analysis step {step.step_id} hypothesis_id")
            require_text(step.outcome, f"analysis step {step.step_id} outcome")
            require_text(step.measurement_id, f"analysis step {step.step_id} measurement_id")
            if step.hypothesis_id not in protocol.hypotheses_tested:
                raise ValidationError(
                    f"analysis step {step.step_id} hypothesis_id is not tested by the protocol"
                )
            measurement = measurement_by_id.get(step.measurement_id)
            if measurement is None or measurement.registered_target != step.outcome:
                raise ValidationError(
                    f"analysis step {step.step_id} measurement must exactly bind its outcome"
                )
            if step.role == "primary_estimate" and step.outcome != protocol.primary_outcome:
                raise ValidationError(
                    f"analysis step {step.step_id} primary_estimate must bind the primary outcome"
                )
            if step.role == "confirmatory_test":
                if step.outcome not in protocol.confirmatory_outcomes:
                    raise ValidationError(
                        f"analysis step {step.step_id} confirmatory_test must bind a confirmatory outcome"
                    )
                if not step.p_value_path.startswith("/"):
                    raise ValidationError(
                        f"analysis step {step.step_id} confirmatory_test requires an absolute p_value_path"
                    )
            elif step.p_value_path:
                raise ValidationError(
                    f"analysis step {step.step_id} p_value_path is reserved for confirmatory_test"
                )
        if protocol.analysis_contract is not None:
            primary_steps = [step for step in source_steps if step.role == "primary_estimate"]
            if len(primary_steps) != 1:
                raise ValidationError("analysis_steps require exactly one primary_estimate step")
            primary_step = primary_steps[0]
            if (
                primary_step.method != protocol.analysis_contract.method
                or primary_step.specification_sha256 != protocol.analysis_specification_sha256
                or primary_step.implementation_sha256 != protocol.analysis_code_hash
                or primary_step.hypothesis_id != protocol.analysis_contract.primary_hypothesis_id
                or primary_step.measurement_id != protocol.analysis_contract.primary_measurement_id
                or primary_step.outcome != protocol.primary_outcome
            ):
                raise ValidationError(
                    "primary analysis step must exactly match the frozen primary analysis contract"
                )
        multiplicity_steps = [
            step for step in protocol.analysis_steps if step.role == "multiplicity"
        ]
        if protocol.multiplicity_method == "holm":
            if len(multiplicity_steps) != 1:
                raise ValidationError("Holm protocols require exactly one multiplicity analysis step")
            step = multiplicity_steps[0]
            family_id = require_canonical_analysis_text(
                step.family_id, "Holm multiplicity step family_id"
            )
            if step.method != "holm_adjustment" or not family_id:
                raise ValidationError(
                    "Holm multiplicity step requires method holm_adjustment and a family_id"
                )
            if step.alpha != protocol.multiplicity_alpha:
                raise ValidationError("Holm multiplicity step alpha must match the protocol alpha")
            if any(not isinstance(item, AnalysisFamilyMember) for item in step.family_members):
                raise ValidationError("multiplicity family_members must be typed values")
            member_ids = [
                require_canonical_analysis_text(item.member_id, "family member_id")
                for item in step.family_members
            ]
            if len(set(member_ids)) != len(member_ids):
                raise ValidationError("multiplicity family member_id values must be unique")
            source_member_pairs = [
                (
                    require_canonical_analysis_text(
                        item.source_step_id, "family source_step_id"
                    ),
                    item,
                )
                for item in step.family_members
            ]
            members_by_source = dict(source_member_pairs)
            if len(members_by_source) != len(step.family_members):
                raise ValidationError("multiplicity family must use each source step exactly once")
            confirmatory_sources = [
                source for source in source_steps if source.role == "confirmatory_test"
            ]
            expected_source_ids = {source.step_id for source in confirmatory_sources}
            if set(step.depends_on) != expected_source_ids or set(members_by_source) != expected_source_ids:
                raise ValidationError(
                    "Holm multiplicity dependencies and family members must exactly cover confirmatory source steps"
                )
            if {source.outcome for source in confirmatory_sources} != set(protocol.confirmatory_outcomes):
                raise ValidationError(
                    "analysis source steps must exactly cover every confirmatory outcome"
                )
            for source in confirmatory_sources:
                member = members_by_source[source.step_id]
                if (
                    member.hypothesis_id != source.hypothesis_id
                    or member.outcome != source.outcome
                    or member.measurement_id != source.measurement_id
                ):
                    raise ValidationError(
                        "multiplicity family member must exactly match its source analysis step"
                    )
        elif multiplicity_steps:
            raise ValidationError("multiplicity analysis steps require a Holm protocol plan")
    elif protocol.multiplicity_method == "holm":
        raise ValidationError("Holm protocols require a frozen multi-step analysis workflow")
    conclusion = protocol.conclusion_contract
    conclusion_required = bool(
        empirical and protocol.analysis_contract is not None
        and protocol.analysis_mode in {AnalysisMode.CONFIRMATORY, AnalysisMode.REPLICATION}
    )
    if conclusion_required and conclusion is not None:
        if not isinstance(conclusion, ConclusionContract):
            raise ValidationError("conclusion_contract must be a typed ConclusionContract")
        if protocol.analysis_contract is None:
            raise ValidationError("conclusion_contract requires an analysis_contract")
        if conclusion.primary_hypothesis_id != protocol.analysis_contract.primary_hypothesis_id:
            raise ValidationError("conclusion_contract must bind the primary analysis hypothesis")
        allowed_decision_rules = (
            {"adjusted_primary_rejection_and_interval_and_practical_significance"}
            if protocol.multiplicity_method == "holm"
            else {"interval_and_practical_significance", "equivalence_interval_within_margin"}
        )
        if conclusion.decision_rule not in allowed_decision_rules:
            raise ValidationError("conclusion_contract decision_rule disagrees with the multiplicity plan")
        threshold = conclusion.smallest_effect_size_of_interest
        if (
            isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(float(threshold)) or float(threshold) < 0
        ):
            raise ValidationError("smallest_effect_size_of_interest must be a finite non-negative number")
        if conclusion.decision_rule == "equivalence_interval_within_margin" and float(threshold) <= 0:
            raise ValidationError("equivalence conclusion requires a positive finite margin")
        for field_name in ("effect_scale", "effect_unit", "population", "setting", "time_window"):
            require_text(getattr(conclusion, field_name), f"conclusion_contract.{field_name}")
        primary_measurements = [
            item for item in protocol.measurement_definitions
            if item.measurement_id == protocol.analysis_contract.primary_measurement_id
        ]
        if len(primary_measurements) != 1 or conclusion.effect_unit != primary_measurements[0].unit:
            raise ValidationError("conclusion_contract effect_unit must match the primary measurement unit")
        if conclusion.non_supporting_direction not in {
            EvidenceDirection.INCONCLUSIVE, EvidenceDirection.WEAKENS,
        }:
            raise ValidationError("conclusion_contract non_supporting_direction must be inconclusive or weakens")
        required_level = (
            ClaimLevel.CAUSAL_DIRECTION if protocol.causal_claim
            else ClaimLevel.STATISTICAL_ASSOCIATION
        )
        if conclusion.permitted_claim_level is not required_level:
            raise ValidationError(
                "conclusion_contract permitted_claim_level disagrees with the protocol causal scope"
            )
        unsupported = require_unique_bounded_report_text_list(
            conclusion.higher_level_conclusions_unsupported,
            "conclusion_contract.higher_level_conclusions_unsupported",
        )
        if not unsupported:
            raise ValidationError("conclusion_contract must name unsupported higher-level conclusions")
    elif conclusion is not None:
        raise ValidationError("conclusion_contract currently requires a confirmatory empirical analysis contract")
    for name, value in required_text.items():
        if not isinstance(value, str) or not value.strip():
            missing.append(name)
    if not protocol.hypotheses_tested:
        missing.append("hypotheses_tested")
    if not protocol.quality_requirements:
        missing.append("quality_requirements")
    if not protocol.controls:
        missing.append("controls")
    if empirical and not protocol.control_definitions:
        missing.append("control_definitions")
    if (
        not protocol.sample_size_or_stopping_rule.strip()
        and "sample_size_or_stopping_rule" not in missing
    ):
        missing.append("sample_size_or_stopping_rule")
    if protocol.sample_size_plan:
        from research_machine.design.precision import (
            build_sample_size_planning_receipt,
        )
        recomputed_plan = build_sample_size_planning_receipt(
            protocol.sample_size_plan
        )
        if recomputed_plan != protocol.sample_size_plan:
            raise ValidationError(
                "sample_size_plan does not reproduce its deterministic calculation"
            )
        if protocol.analysis_design and protocol.analysis_design != "independent_groups":
            raise ValidationError(
                "two-group sample_size_plan conflicts with protocol analysis_design"
            )
        if (
            protocol.analysis_contract is not None
            and protocol.analysis_contract.minimum_analyzable_units is not None
            and protocol.analysis_contract.minimum_analyzable_units
            != recomputed_plan["calculation"]["analyzable_n_per_group"]
        ):
            raise ValidationError(
                "analysis_contract minimum_analyzable_units must equal the sample_size_plan analyzable_n_per_group"
            )
    if not protocol.failure_conditions:
        missing.append("failure_conditions")
    if not protocol.safety_constraints:
        missing.append("safety_constraints")
    if not isinstance(protocol.human_subjects, bool):
        raise ValidationError("human_subjects must be true or false")
    if protocol.human_subjects:
        for field in (
            "consent_plan",
            "withdrawal_plan",
            "privacy_plan",
            "retention_deletion_plan",
            "risk_assessment",
            "vulnerable_population_plan",
            "data_security_plan",
            "incidental_findings_plan",
            "independent_review_receipt",
            "independent_review_decision",
            "independent_reviewer_role",
            "independent_reviewed_at",
            "independent_review_scope",
            "independent_review_artifact_locator",
            "independent_review_artifact_sha256",
        ):
            value = getattr(protocol, field)
            if not isinstance(value, str) or not value.strip():
                missing.append(field)
        if protocol.independent_review_decision and protocol.independent_review_decision not in _INDEPENDENT_REVIEW_DECISIONS:
            raise ValidationError(
                "independent_review_decision must be approved or approved_with_conditions"
            )
        if protocol.independent_reviewed_at:
            try:
                reviewed_at = datetime.fromisoformat(
                    protocol.independent_reviewed_at.replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise ValidationError(
                    "independent_reviewed_at must be an RFC 3339 timestamp"
                ) from exc
            if reviewed_at.tzinfo is None:
                raise ValidationError(
                    "independent_reviewed_at must include a timezone offset"
                )
        if protocol.independent_review_artifact_sha256:
            require_sha256(
                protocol.independent_review_artifact_sha256,
                "independent_review_artifact_sha256",
            )
        conditions = require_unique_text_list(
            protocol.independent_review_conditions, "independent_review_conditions"
        )
        if protocol.independent_review_decision == "approved_with_conditions" and not conditions:
            raise ValidationError(
                "independent_review_conditions must record every condition of conditional approval"
            )
    if not protocol.expected_outputs:
        missing.append("expected_outputs")
    if not protocol.success_conditions:
        missing.append("success_conditions")
    if len(quality_requirement_set) != len(quality_requirement_ids):
        raise ValidationError("quality_requirements must not contain duplicates")
    canary_plan = protocol.canary_target_plan
    if canary_plan is not None:
        if not isinstance(canary_plan, CanaryTargetPlan):
            raise ValidationError(
                "canary_target_plan must be a CanaryTargetPlan value"
            )
        require_canonical_text(canary_plan.plan_id, "canary_target_plan.plan_id")
        candidate_targets = require_unique_canonical_text_list(
            canary_plan.candidate_target_ids,
            "canary_target_plan.candidate_target_ids",
        )
        if len(candidate_targets) < 2:
            raise ValidationError(
                "canary_target_plan requires at least two candidate targets"
            )
        require_sha256(
            canary_plan.seed_commitment_sha256,
            "canary_target_plan.seed_commitment_sha256",
        )
        require_sha256(
            canary_plan.assignment_artifact_sha256,
            "canary_target_plan.assignment_artifact_sha256",
        )
        require_canonical_text(
            canary_plan.masking_plan, "canary_target_plan.masking_plan"
        )
        require_canonical_text(
            canary_plan.ethical_disclosure,
            "canary_target_plan.ethical_disclosure",
        )
        assessment_gate_id = require_canonical_text(
            canary_plan.assessment_gate_id,
            "canary_target_plan.assessment_gate_id",
        )
        if assessment_gate_id not in quality_requirement_set:
            raise ValidationError(
                "canary_target_plan assessment_gate_id must be a required protocol quality gate"
            )
        occupied_gate_ids = {
            require_text(item.evaluation_gate_id, "control evaluation_gate_id")
            for item in protocol.control_definitions
        }
        if protocol.analysis_contract is not None:
            occupied_gate_ids.add(
                require_text(
                    protocol.analysis_contract.missingness_assessment_gate_id,
                    "analysis_contract.missingness_assessment_gate_id",
                )
            )
        if protocol.causal_identification:
            occupied_gate_ids.update(
                require_text(
                    item["assessment_gate_id"],
                    "causal assumption assessment_gate_id",
                )
                for item in protocol.causal_identification.get("assumptions", [])
            )
        occupied_gate_ids.update(
            require_text(item.assessment_gate_id, "measurement validity assessment_gate_id")
            for item in protocol.measurement_validity_checks
        )
        occupied_gate_ids.discard("")
        if assessment_gate_id in occupied_gate_ids:
            raise ValidationError(
                "canary_target_plan assessment gate must be dedicated and cannot be reused for controls, causal assumptions, missingness, or validity checks"
            )
    if protocol.measurement_definitions:
        validate_measurement_contract(protocol)
    if protocol.measurement_validity_checks:
        check_ids: set[str] = set()
        gate_ids: set[str] = set()
        measurement_ids = {
            require_text(item.measurement_id, "measurement definition measurement_id")
            for item in protocol.measurement_definitions
        }
        occupied_gate_ids = {
            require_text(item.evaluation_gate_id, "control evaluation_gate_id")
            for item in protocol.control_definitions
        }
        if protocol.analysis_contract is not None:
            occupied_gate_ids.add(
                require_text(
                    protocol.analysis_contract.missingness_assessment_gate_id,
                    "analysis_contract.missingness_assessment_gate_id",
                )
            )
        if protocol.canary_target_plan is not None:
            occupied_gate_ids.add(
                require_text(
                    protocol.canary_target_plan.assessment_gate_id,
                    "canary_target_plan.assessment_gate_id",
                )
            )
        if protocol.causal_identification:
            occupied_gate_ids.update(
                require_text(
                    item["assessment_gate_id"],
                    "causal assumption assessment_gate_id",
                )
                for item in protocol.causal_identification.get("assumptions", [])
            )
        occupied_gate_ids.discard("")
        for check in protocol.measurement_validity_checks:
            if not isinstance(check, MeasurementValidityCheck):
                raise ValidationError(
                    "measurement_validity_checks must contain MeasurementValidityCheck values"
                )
            for name, value in check.to_dict().items():
                require_canonical_text(value, f"measurement validity check {name}")
            for name, value in (
                ("check_id", check.check_id),
                ("measurement_id", check.measurement_id),
                ("assessment_gate_id", check.assessment_gate_id),
            ):
                require_canonical_text(value, f"measurement validity check {name}")
            if check.evidence_type not in {
                "criterion", "convergent", "discriminant", "known_groups",
                "test_retest", "inter_rater", "content", "calibration", "other",
            }:
                raise ValidationError("unsupported measurement validity evidence_type")
            check_id = check.check_id
            assessment_gate_id = check.assessment_gate_id
            if check_id in check_ids:
                raise ValidationError("measurement validity check IDs must be unique")
            if assessment_gate_id in gate_ids:
                raise ValidationError("measurement validity assessment gates must be unique")
            if check.measurement_id not in measurement_ids:
                raise ValidationError(
                    "measurement validity check must bind an exact protocol measurement_id"
                )
            if assessment_gate_id not in quality_requirement_set:
                raise ValidationError(
                    "measurement validity assessment gate must be a required protocol quality gate"
                )
            if assessment_gate_id in occupied_gate_ids:
                raise ValidationError(
                    "measurement validity assessment gate must be dedicated and cannot be reused for controls, causal assumptions, missingness, or canary target assessment"
                )
            check_ids.add(check_id)
            gate_ids.add(assessment_gate_id)
    if conclusion_required and conclusion is None:
        raise ValidationError(
            "confirmatory empirical analyses require a typed conclusion_contract"
        )
    if protocol.control_definitions:
        control_ids: set[str] = set()
        targets: set[str] = set()
        ordered_targets: list[str] = []
        registered_controls = []
        for control_name in protocol.controls:
            registered_control = require_text(control_name, "protocol controls item")
            if registered_control != control_name:
                raise ValidationError(
                    "protocol controls must be canonical without surrounding whitespace"
                )
            if registered_control in registered_controls:
                raise ValidationError(
                    "protocol controls must be unique when control_definitions are supplied"
                )
            registered_controls.append(registered_control)
        for control in protocol.control_definitions:
            if not isinstance(control, ControlDefinition):
                raise ValidationError("control_definitions must contain ControlDefinition objects")
            for name in (
                "control_id",
                "registered_control",
                "family",
                "purpose",
                "expected_behavior",
                "evaluation_gate_id",
            ):
                require_canonical_text(
                    getattr(control, name), f"control definition {name}"
                )
            if control.family not in CONTROL_FAMILIES:
                raise ValidationError("unsupported control family")
            control_id = control.control_id
            registered_control = control.registered_control
            if control_id in control_ids or registered_control in targets:
                raise ValidationError("duplicate control definition ID or registered control")
            control_ids.add(control_id)
            targets.add(registered_control)
            ordered_targets.append(registered_control)
            if control.evaluation_gate_id not in quality_requirement_set:
                raise ValidationError(
                    "control evaluation gate must be a required protocol quality gate"
                )
            if control.witness_contract is not None:
                _validate_control_witness_contract(protocol, control)
        if ordered_targets != registered_controls:
            raise ValidationError(
                "control definitions must cover exactly the registered controls in order"
            )
    if protocol.named_component_contracts:
        validate_named_component_contracts(protocol)
    if protocol.mathematical_predicate_contracts:
        validate_mathematical_predicate_contracts(protocol)
    if protocol.duality_reconstruction_contracts:
        validate_duality_reconstruction_contracts(protocol)
    if protocol.reconstruction_family_stability_contracts:
        validate_reconstruction_family_stability_contracts(protocol)
    if protocol.analysis_implementation_bundle_contracts:
        validate_analysis_implementation_bundle_contracts(protocol)
    if protocol.computation_route_separation_contracts:
        validate_computation_route_separation_contracts(protocol)
    if protocol.bounded_negative_search_contracts:
        validate_bounded_negative_search_contracts(protocol)
    custody_requirement_ids = []
    for gate_id in protocol.measurement_custody_requirements:
        canonical_gate_id = require_text(
            gate_id, "measurement_custody_requirements item"
        )
        if canonical_gate_id != gate_id:
            raise ValidationError(
                "measurement_custody_requirements items must be canonical without surrounding whitespace"
            )
        custody_requirement_ids.append(canonical_gate_id)
    if len(set(custody_requirement_ids)) != len(custody_requirement_ids):
        raise ValidationError("measurement_custody_requirements must not contain duplicates")
    criteria_ids: set[str] = set()
    calibration_ids: set[str] = set()
    for criterion in protocol.calibration_acceptance_criteria:
        if not isinstance(criterion, CalibrationCriterion):
            raise ValidationError("calibration_acceptance_criteria must contain CalibrationCriterion values")
        for name in ("criterion_id", "calibration_id", "quantity", "unit", "rationale"):
            require_canonical_text(getattr(criterion, name), f"calibration criterion {name}")
        criterion_id = criterion.criterion_id
        calibration_id = criterion.calibration_id
        if criterion_id in criteria_ids or calibration_id in calibration_ids:
            raise ValidationError("calibration criterion and calibration IDs must be unique")
        criteria_ids.add(criterion_id)
        calibration_ids.add(calibration_id)
        bounds = (criterion.lower_bound, criterion.upper_bound)
        component_bounds = criterion.component_bounds
        if component_bounds:
            if not isinstance(component_bounds, list):
                raise ValidationError("calibration criterion component_bounds must be an array")
            if any(value is not None for value in bounds):
                raise ValidationError(
                    "calibration criterion cannot mix scalar bounds and component_bounds"
                )
            component_ids: set[str] = set()
            for index, component in enumerate(component_bounds):
                if not isinstance(component, dict):
                    raise ValidationError("calibration criterion component_bounds entries must be objects")
                required_fields = {
                    "component_id",
                    "quantity",
                    "unit",
                    "lower_bound",
                    "upper_bound",
                }
                if set(component) != required_fields:
                    raise ValidationError(
                        "calibration criterion component_bounds fields are invalid"
                    )
                component_id = require_canonical_text(
                    component["component_id"],
                    f"calibration criterion component_bounds[{index}].component_id",
                )
                if component_id in component_ids:
                    raise ValidationError(
                        "calibration criterion component_bounds component_id values must be unique"
                    )
                component_ids.add(component_id)
                for name in ("quantity", "unit"):
                    require_canonical_text(
                        component[name],
                        f"calibration criterion component_bounds[{index}].{name}",
                    )
                component_limits = (
                    component["lower_bound"],
                    component["upper_bound"],
                )
                if all(value is None for value in component_limits):
                    raise ValidationError(
                        "calibration criterion component_bounds require a lower_bound or upper_bound"
                    )
                for value in component_limits:
                    if value is not None and (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                    ):
                        raise ValidationError(
                            "calibration criterion component_bounds bounds must be finite numbers or null"
                        )
                if (
                    component["lower_bound"] is not None
                    and component["upper_bound"] is not None
                    and component["lower_bound"] > component["upper_bound"]
                ):
                    raise ValidationError(
                        "calibration criterion component_bounds lower_bound must not exceed upper_bound"
                    )
            multivariate_policy = criterion.multivariate_policy
            if multivariate_policy:
                if not isinstance(multivariate_policy, dict):
                    raise ValidationError(
                        "calibration criterion multivariate_policy must be an object"
                    )
                required_policy_fields = {
                    "policy_id",
                    "norm",
                    "component_ids",
                    "unit",
                    "upper_bound",
                    "rationale",
                }
                if set(multivariate_policy) != required_policy_fields:
                    raise ValidationError(
                        "calibration criterion multivariate_policy fields are invalid"
                    )
                for name in ("policy_id", "norm", "unit", "rationale"):
                    require_canonical_text(
                        multivariate_policy[name],
                        f"calibration criterion multivariate_policy.{name}",
                    )
                if multivariate_policy["norm"] not in {"l1", "l2", "linf"}:
                    raise ValidationError(
                        "calibration criterion multivariate_policy norm is unsupported"
                    )
                if (
                    isinstance(multivariate_policy["upper_bound"], bool)
                    or not isinstance(multivariate_policy["upper_bound"], (int, float))
                    or not math.isfinite(float(multivariate_policy["upper_bound"]))
                    or float(multivariate_policy["upper_bound"]) < 0
                ):
                    raise ValidationError(
                        "calibration criterion multivariate_policy upper_bound must be a finite non-negative number"
                    )
                if (
                    not isinstance(multivariate_policy["component_ids"], list)
                    or not multivariate_policy["component_ids"]
                    or any(
                        not isinstance(value, str)
                        for value in multivariate_policy["component_ids"]
                    )
                ):
                    raise ValidationError(
                        "calibration criterion multivariate_policy component_ids must be an array of text"
                    )
                policy_component_ids = [
                    require_canonical_text(
                        value,
                        "calibration criterion multivariate_policy.component_ids item",
                    )
                    for value in multivariate_policy["component_ids"]
                ]
                expected_component_ids = [
                    component["component_id"] for component in component_bounds
                ]
                if policy_component_ids != expected_component_ids:
                    raise ValidationError(
                        "calibration criterion multivariate_policy component_ids must match component_bounds order exactly"
                    )
                policy_unit = multivariate_policy["unit"]
                if any(component["unit"] != policy_unit for component in component_bounds):
                    raise ValidationError(
                        "calibration criterion multivariate_policy unit must match every component unit"
                    )
        elif criterion.multivariate_policy:
            raise ValidationError(
                "calibration criterion multivariate_policy requires component_bounds"
            )
        elif all(value is None for value in bounds):
            raise ValidationError("calibration criterion requires a lower_bound or upper_bound")
        for value in bounds:
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))):
                raise ValidationError("calibration criterion bounds must be finite numbers or null")
        if criterion.lower_bound is not None and criterion.upper_bound is not None and criterion.lower_bound > criterion.upper_bound:
            raise ValidationError("calibration criterion lower_bound must not exceed upper_bound")
    if protocol.calibration_requirements and not protocol.measurement_custody_requirements:
        missing.append("measurement_custody_requirements")
    if protocol.measurement_custody_requirements and not protocol.calibration_acceptance_criteria:
        missing.append("calibration_acceptance_criteria")
    if (
        protocol.protocol_kind
        in {
            ProtocolKind.COMPUTATIONAL,
            ProtocolKind.FORMAL,
        }
        and not protocol.environment_requirements
    ):
        missing.append("environment_requirements")
    if missing:
        raise ValidationError(
            "protocol cannot be frozen until it defines: " + ", ".join(missing)
        )
    require_sha256(protocol.analysis_code_hash, "analysis_code_hash")
    if protocol.analysis_specification_sha256:
        require_sha256(protocol.analysis_specification_sha256, "analysis_specification_sha256")
    if protocol.random_seed_commitment:
        require_sha256(protocol.random_seed_commitment, "random_seed_commitment")


def _named_component_indices(
    component_ids: Sequence[str], selected_component_ids: Sequence[str]
) -> list[int]:
    return [component_ids.index(component_id) for component_id in selected_component_ids]


_CONTROL_WITNESS_COMPARATORS = {
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
}

_ALIAS_PROXY_SCOPES = {
    "registered_target_alias",
    "observable_alias",
    "input_condition_alias",
    "data_column_alias",
    "value_domain_alias",
    "proxy_measurement",
}


def _validate_alias_proxy_commitment(
    *,
    definition: MeasurementDefinition,
    prefix: str,
) -> None:
    commitment = definition.alias_proxy_commitment
    if commitment is None:
        return
    if not isinstance(commitment, AliasProxyCommitment):
        raise ValidationError(
            f"{prefix}.alias_proxy_commitment must be an AliasProxyCommitment"
        )
    commitment_prefix = f"{prefix}.alias_proxy_commitment"
    commitment_id = require_canonical_text(
        commitment.commitment_id, f"{commitment_prefix}.commitment_id"
    )
    if not commitment_id:
        raise ValidationError(f"{commitment_prefix}.commitment_id must be non-empty")
    scope = require_canonical_text(
        commitment.concealment_scope, f"{commitment_prefix}.concealment_scope"
    )
    if scope not in _ALIAS_PROXY_SCOPES:
        raise ValidationError(
            f"{commitment_prefix}.concealment_scope is unsupported"
        )
    public_label = require_canonical_text(
        commitment.public_label, f"{commitment_prefix}.public_label"
    )
    require_sha256(
        commitment.private_mapping_sha256,
        f"{commitment_prefix}.private_mapping_sha256",
    )
    rationale = require_canonical_bounded_report_text(
        commitment.construct_validity_rationale,
        f"{commitment_prefix}.construct_validity_rationale",
    )
    if not rationale:
        raise ValidationError(
            f"{commitment_prefix}.construct_validity_rationale must be non-empty"
        )
    require_nonempty_unique_bounded_report_text_list(
        commitment.limitations,
        f"{commitment_prefix}.limitations",
    )
    reveal_conditions = require_canonical_bounded_report_text(
        commitment.reveal_conditions, f"{commitment_prefix}.reveal_conditions"
    )
    if not reveal_conditions:
        raise ValidationError(
            f"{commitment_prefix}.reveal_conditions must be non-empty"
        )
    proxy_construct = commitment.proxy_construct
    if not isinstance(proxy_construct, str):
        raise ValidationError(f"{commitment_prefix}.proxy_construct must be text")
    if proxy_construct:
        proxy_construct = require_canonical_bounded_report_text(
            proxy_construct,
            f"{commitment_prefix}.proxy_construct",
        )
    expected_labels = {
        "registered_target_alias": {definition.registered_target},
        "observable_alias": {definition.observable},
        "input_condition_alias": {definition.input_condition},
        "data_column_alias": {definition.data_column},
        "value_domain_alias": set(definition.admissible_values),
        "proxy_measurement": {definition.observable},
    }[scope]
    if not public_label or public_label not in expected_labels:
        raise ValidationError(
            f"{commitment_prefix}.public_label must match the frozen measurement field for its concealment_scope"
        )
    if scope == "data_column_alias" and not definition.data_column:
        raise ValidationError(
            f"{commitment_prefix}.data_column_alias requires an executable data_column"
        )
    if scope == "value_domain_alias" and not definition.admissible_values:
        raise ValidationError(
            f"{commitment_prefix}.value_domain_alias requires an admissible value domain"
        )
    if scope == "proxy_measurement" and not proxy_construct:
        raise ValidationError(
            f"{commitment_prefix}.proxy_construct must identify the hidden construct for proxy_measurement"
        )
    if scope != "proxy_measurement" and proxy_construct:
        raise ValidationError(
            f"{commitment_prefix}.proxy_construct is reserved for proxy_measurement"
        )


def _validate_control_witness_value(value: Any, field_name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field_name} must be a non-boolean finite number")
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValidationError(
            f"{field_name} must be representable as a finite number"
        ) from exc
    if not finite:
        raise ValidationError(f"{field_name} must be finite")
    return value


def _control_witness_measurement(
    protocol: ExperimentProtocol,
    control: ControlDefinition,
) -> MeasurementDefinition:
    contract = control.witness_contract
    if not isinstance(contract, ControlWitnessContract):
        raise ValidationError(
            f"control {control.control_id} witness_contract must be a ControlWitnessContract"
        )
    matches = [
        measurement
        for measurement in protocol.measurement_definitions
        if measurement.measurement_id == contract.measurement_id
    ]
    if len(matches) != 1:
        raise ValidationError(
            f"control {control.control_id} witness_contract must bind one exact protocol measurement_id"
        )
    measurement = matches[0]
    if measurement.role is not MeasurementRole.CONTROL:
        raise ValidationError(
            f"control {control.control_id} witness measurement must have role control"
        )
    if measurement.registered_target != control.registered_control:
        raise ValidationError(
            f"control {control.control_id} witness measurement must target its registered control"
        )
    require_canonical_text(
        measurement.observable,
        f"control {control.control_id} witness measurement observable",
    )
    require_canonical_text(
        measurement.unit,
        f"control {control.control_id} witness measurement unit",
    )
    return measurement


def _validate_control_witness_contract(
    protocol: ExperimentProtocol,
    control: ControlDefinition,
) -> MeasurementDefinition:
    contract = control.witness_contract
    if not isinstance(contract, ControlWitnessContract):
        raise ValidationError(
            f"control {control.control_id} witness_contract must be a ControlWitnessContract"
        )
    require_canonical_text(
        contract.intervention_id,
        f"control {control.control_id} witness intervention_id",
    )
    require_canonical_text(
        contract.measurement_id,
        f"control {control.control_id} witness measurement_id",
    )
    comparator = require_canonical_text(
        contract.comparator,
        f"control {control.control_id} witness comparator",
    )
    if comparator not in _CONTROL_WITNESS_COMPARATORS:
        raise ValidationError(
            f"control {control.control_id} witness comparator is unsupported"
        )
    _validate_control_witness_value(
        contract.reference_value,
        f"control {control.control_id} witness reference_value",
    )
    return _control_witness_measurement(protocol, control)


def validate_control_witness_evidence(
    *,
    protocol: ExperimentProtocol,
    control: ControlDefinition,
    witness: Any,
    matches_expected: Any,
    context: str = "",
) -> bool:
    """Replay one artifact-selected control comparison without trusting its decision."""

    measurement = _validate_control_witness_contract(protocol, control)
    contract = control.witness_contract
    assert contract is not None
    label = f"{context} " if context else ""
    required_fields = {
        "control_id",
        "intervention_id",
        "measurement_id",
        "quantity",
        "unit",
        "comparator",
        "reference_value",
        "observed_value",
        "decision",
    }
    if not isinstance(witness, dict) or set(witness) != required_fields:
        raise ValidationError(
            f"{label}control {control.control_id} witness must be an exact structured JSON object"
        )
    frozen_text = {
        "control_id": control.control_id,
        "intervention_id": contract.intervention_id,
        "measurement_id": contract.measurement_id,
        "quantity": measurement.observable,
        "unit": measurement.unit,
        "comparator": contract.comparator,
    }
    for field_name, expected in frozen_text.items():
        actual = require_canonical_text(
            witness[field_name],
            f"{label}control {control.control_id} witness {field_name}",
        )
        if actual != expected:
            raise ValidationError(
                f"{label}control {control.control_id} witness {field_name} does not match the frozen protocol"
            )
    reference = _validate_control_witness_value(
        witness["reference_value"],
        f"{label}control {control.control_id} witness reference_value",
    )
    if type(reference) is not type(contract.reference_value) or (
        reference != contract.reference_value
    ):
        raise ValidationError(
            f"{label}control {control.control_id} witness reference_value does not match the frozen protocol"
        )
    observed = _validate_control_witness_value(
        witness["observed_value"],
        f"{label}control {control.control_id} witness observed_value",
    )
    comparator = contract.comparator
    derived_decision = {
        "eq": observed == reference,
        "ne": observed != reference,
        "lt": observed < reference,
        "lte": observed <= reference,
        "gt": observed > reference,
        "gte": observed >= reference,
    }[comparator]
    if type(witness["decision"]) is not bool:
        raise ValidationError(
            f"{label}control {control.control_id} witness decision must be a boolean"
        )
    if witness["decision"] is not derived_decision:
        raise ValidationError(
            f"{label}control {control.control_id} witness decision does not match the frozen comparison"
        )
    if type(matches_expected) is not bool or matches_expected is not derived_decision:
        raise ValidationError(
            f"{label}control {control.control_id} matches_expected does not match its structured witness decision"
        )
    return derived_decision


def validate_named_component_contracts(protocol: ExperimentProtocol) -> None:
    """Validate optional name-addressed subset contracts and their adverse control."""

    contracts = protocol.named_component_contracts
    if any(not isinstance(item, NamedComponentContract) for item in contracts):
        raise ValidationError(
            "named_component_contracts must contain NamedComponentContract values"
        )
    measurement_ids = {
        item.measurement_id for item in protocol.measurement_definitions
    }
    controls = {item.control_id: item for item in protocol.control_definitions}
    contract_ids: set[str] = set()
    for index, contract in enumerate(contracts):
        prefix = f"named_component_contracts[{index}]"
        for field_name in (
            "contract_id",
            "measurement_id",
            "relabeling_control_id",
            "evaluation_gate_id",
        ):
            value = getattr(contract, field_name)
            require_canonical_text(value, f"{prefix}.{field_name}")
        if contract.contract_id in contract_ids:
            raise ValidationError("named component contract IDs must be unique")
        contract_ids.add(contract.contract_id)
        if contract.measurement_id not in measurement_ids:
            raise ValidationError(
                "named component contract must bind an exact protocol measurement_id"
            )
        component_ids = require_unique_canonical_text_list(
            contract.component_ids, f"{prefix}.component_ids"
        )
        selected_ids = require_unique_canonical_text_list(
            contract.selected_component_ids, f"{prefix}.selected_component_ids"
        )
        relabeled_ids = require_unique_canonical_text_list(
            contract.relabeled_component_ids,
            f"{prefix}.relabeled_component_ids",
        )
        if len(component_ids) < 2:
            raise ValidationError(
                "named component contract requires at least two component_ids"
            )
        if not selected_ids or len(selected_ids) >= len(component_ids):
            raise ValidationError(
                "named component contract selected_component_ids must be a nonempty proper subset"
            )
        if not set(selected_ids).issubset(component_ids):
            raise ValidationError(
                "named component contract selected_component_ids must name frozen components"
            )
        if set(relabeled_ids) != set(component_ids):
            raise ValidationError(
                "named component contract relabeled_component_ids must be an exact permutation"
            )
        if relabeled_ids == component_ids:
            raise ValidationError(
                "named component contract relabeling must change component order"
            )
        if _named_component_indices(component_ids, selected_ids) == (
            _named_component_indices(relabeled_ids, selected_ids)
        ):
            raise ValidationError(
                "named component contract relabeling must change a selected component index"
            )
        control = controls.get(contract.relabeling_control_id)
        if control is None:
            raise ValidationError(
                "named component contract must bind an exact relabeling control_id"
            )
        if control.family != "adversarial":
            raise ValidationError(
                "named component contract relabeling control must be adversarial"
            )
        if control.evaluation_gate_id != contract.evaluation_gate_id:
            raise ValidationError(
                "named component contract and relabeling control must share an evaluation gate"
            )
        if contract.evaluation_gate_id not in set(protocol.quality_requirements):
            raise ValidationError(
                "named component contract evaluation gate must be a required protocol quality gate"
            )


def validate_named_component_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    gate: QualityGateResult,
    output_hashes: set[str],
    context: str = "",
) -> None:
    """Replay a component-selection invariant without judging domain semantics."""

    contracts = [
        item
        for item in protocol.named_component_contracts
        if item.evaluation_gate_id == gate.gate_id
    ]
    if not contracts or gate.status is QualityGateStatus.SKIPPED:
        return
    label = f"{context} " if context else ""
    results = gate.details.get("named_component_results")
    expected_ids = {item.contract_id for item in contracts}
    if not isinstance(results, dict) or set(results) != expected_ids:
        raise ValidationError(
            f"{label}performed named component gate {gate.gate_id} requires exact results for: "
            + ", ".join(sorted(expected_ids))
        )
    expected_status = {
        QualityGateStatus.PASSED: "consistent_with_named_selection",
        QualityGateStatus.WARNING: "inconclusive",
        QualityGateStatus.FAILED: "contradicted_named_selection",
    }.get(gate.status)
    if expected_status is None:
        raise ValidationError(
            f"{label}named component gate {gate.gate_id} has an unsupported status"
        )
    control_results = gate.details.get("control_results")
    for contract in contracts:
        result = results[contract.contract_id]
        required_fields = {
            "source_component_ids",
            "source_selection_indices",
            "relabeled_component_ids",
            "relabeled_selection_indices",
            "source_selected_component_ids",
            "relabeled_selected_component_ids",
            "assessment_status",
            "observed_behavior",
            "interpretation",
            "evidence_sha256",
            "evidence_location",
        }
        derived_fields = {"selected_value_sha256"}
        if (
            not isinstance(result, dict)
            or not required_fields <= set(result)
            or set(result) - required_fields - derived_fields
        ):
            raise ValidationError(
                f"{label}named component result for {contract.contract_id} must contain exactly the documented fields"
            )
        prefix = (
            f"{label}gate {gate.gate_id} named_component_results "
            f"{contract.contract_id}"
        )
        for field_name in ("observed_behavior", "interpretation", "evidence_location"):
            require_canonical_text(result[field_name], f"{prefix}.{field_name}")
        for field_name in (
            "source_component_ids",
            "relabeled_component_ids",
            "source_selected_component_ids",
            "relabeled_selected_component_ids",
        ):
            require_unique_canonical_text_list(
                result[field_name], f"{prefix}.{field_name}"
            )
        source_ids = result["source_component_ids"]
        relabeled_ids = result["relabeled_component_ids"]
        if source_ids != contract.component_ids:
            raise ValidationError(
                f"{label}named component source order does not match the frozen contract"
            )
        if relabeled_ids != contract.relabeled_component_ids:
            raise ValidationError(
                f"{label}named component relabeled order does not match the frozen contract"
            )
        observed_selected: list[list[str]] = []
        for order_name, indices_name, selected_name in (
            (
                "source_component_ids",
                "source_selection_indices",
                "source_selected_component_ids",
            ),
            (
                "relabeled_component_ids",
                "relabeled_selection_indices",
                "relabeled_selected_component_ids",
            ),
        ):
            indices = result[indices_name]
            if (
                not isinstance(indices, list)
                or len(indices) != len(contract.selected_component_ids)
                or any(type(item) is not int for item in indices)
                or len(set(indices)) != len(indices)
                or any(item < 0 or item >= len(result[order_name]) for item in indices)
            ):
                raise ValidationError(
                    f"{prefix}.{indices_name} must be unique in-range integer indices with frozen subset cardinality"
                )
            derived = [result[order_name][item] for item in indices]
            if result[selected_name] != derived:
                raise ValidationError(
                    f"{prefix}.{selected_name} does not match its recorded order and indices"
                )
            observed_selected.append(derived)
        selections_match = all(
            item == contract.selected_component_ids for item in observed_selected
        )
        status = require_canonical_text(
            result["assessment_status"], f"{prefix}.assessment_status"
        )
        if status != expected_status:
            raise ValidationError(
                f"{label}{gate.status.value} named component gate requires {expected_status}"
            )
        if gate.status is QualityGateStatus.PASSED and not selections_match:
            raise ValidationError(
                f"{label}passed named component gate selected components by position instead of frozen names"
            )
        if gate.status is QualityGateStatus.FAILED and selections_match:
            raise ValidationError(
                f"{label}failed named component gate must retain a contradictory observed selection"
            )
        digest = require_sha256(
            result["evidence_sha256"], f"{prefix}.evidence_sha256"
        )
        if result.get("selected_value_sha256") is not None:
            require_sha256(
                result["selected_value_sha256"],
                f"{prefix}.selected_value_sha256",
            )
        if digest not in output_hashes:
            raise ValidationError(
                f"{label}named component evidence must reference a run output artifact"
            )
        linked_control = (
            control_results.get(contract.relabeling_control_id)
            if isinstance(control_results, dict)
            else None
        )
        control_fields = {
            "observed_behavior",
            "interpretation",
            "matches_expected",
            "evidence_sha256",
            "evidence_location",
        }
        control_derived_fields = {"selected_value_sha256"}
        if (
            not isinstance(linked_control, dict)
            or not control_fields <= set(linked_control)
            or set(linked_control) - control_fields - control_derived_fields
        ):
            raise ValidationError(
                f"{label}named component result requires its exact linked relabeling control evaluation"
            )
        for field_name in ("observed_behavior", "interpretation", "evidence_location"):
            require_canonical_text(
                linked_control[field_name],
                f"{prefix}.linked_control.{field_name}",
            )
        if type(linked_control["matches_expected"]) is not bool:
            raise ValidationError(
                f"{label}named component linked control matches_expected must be a boolean"
            )
        control_digest = require_sha256(
            linked_control["evidence_sha256"],
            f"{prefix}.linked_control.evidence_sha256",
        )
        if control_digest not in output_hashes:
            raise ValidationError(
                f"{label}named component linked control evidence must reference a run output artifact"
            )
        if gate.status is QualityGateStatus.PASSED and not linked_control[
            "matches_expected"
        ]:
            raise ValidationError(
                f"{label}passed named component gate requires its relabeling control to match expectation"
            )
        if gate.status is QualityGateStatus.FAILED and linked_control[
            "matches_expected"
        ]:
            raise ValidationError(
                f"{label}failed named component gate requires its relabeling control to record the mismatch"
            )


_MATHEMATICAL_OBJECT_KINDS = {
    "bilinear_form",
    "custom",
    "linear_map",
    "linear_operator",
    "nonlinear_map",
    "nonlinear_operator",
    "quadratic_form",
    "quotient_map",
    "residual",
    "state_space",
    "tensor",
}
_MATHEMATICAL_PREDICATES = {
    "bijective",
    "closed",
    "conserved",
    "custom",
    "equivalent",
    "injective",
    "invertible",
    "nonnegative",
    "nullity",
    "positive_definite",
    "positive_semidefinite",
    "rank",
    "surjective",
    "tangent",
}
_MAP_PREDICATES = {"bijective", "injective", "invertible", "surjective"}
_MAP_OBJECT_KINDS = {
    "linear_map",
    "linear_operator",
    "nonlinear_map",
    "nonlinear_operator",
    "quotient_map",
}
_POSITIVITY_PREDICATES = {
    "nonnegative",
    "positive_definite",
    "positive_semidefinite",
}
_POSITIVITY_OBJECT_KINDS = {
    "bilinear_form",
    "linear_operator",
    "quadratic_form",
    "tensor",
}
_LINEAR_ALGEBRA_PREDICATES = {"nullity", "rank"}
_LINEAR_ALGEBRA_OBJECT_KINDS = {
    "bilinear_form",
    "linear_map",
    "linear_operator",
    "quadratic_form",
    "tensor",
}


def validate_mathematical_predicate_contracts(
    protocol: ExperimentProtocol,
) -> None:
    """Bind predicates to exact typed objects and prospective equivalence rules."""

    contracts = protocol.mathematical_predicate_contracts
    if any(
        not isinstance(item, MathematicalPredicateContract)
        for item in contracts
    ):
        raise ValidationError(
            "mathematical_predicate_contracts must contain "
            "MathematicalPredicateContract values"
        )
    controls = {item.control_id: item for item in protocol.control_definitions}
    contract_ids: set[str] = set()
    for index, contract in enumerate(contracts):
        prefix = f"mathematical_predicate_contracts[{index}]"
        for field_name in (
            "contract_id",
            "object_id",
            "object_kind",
            "domain",
            "codomain",
            "quotient",
            "construction",
            "predicate",
            "predicate_definition",
            "adversarial_control_id",
            "evaluation_gate_id",
        ):
            require_canonical_text(
                getattr(contract, field_name), f"{prefix}.{field_name}"
            )
        if contract.contract_id in contract_ids:
            raise ValidationError(
                "mathematical predicate contract IDs must be unique"
            )
        contract_ids.add(contract.contract_id)
        if contract.object_kind not in _MATHEMATICAL_OBJECT_KINDS:
            raise ValidationError(
                f"{prefix}.object_kind is unsupported"
            )
        if contract.predicate not in _MATHEMATICAL_PREDICATES:
            raise ValidationError(f"{prefix}.predicate is unsupported")
        derived_from = require_unique_canonical_text_list(
            contract.derived_from_object_ids,
            f"{prefix}.derived_from_object_ids",
        )
        comparison_objects = require_unique_canonical_text_list(
            contract.comparison_object_ids,
            f"{prefix}.comparison_object_ids",
        )
        equivalence_conditions = require_unique_canonical_text_list(
            contract.equivalence_conditions,
            f"{prefix}.equivalence_conditions",
        )
        if contract.object_id in derived_from:
            raise ValidationError(
                "mathematical predicate object cannot derive from itself"
            )
        if contract.object_id in comparison_objects:
            raise ValidationError(
                "mathematical predicate object cannot compare with itself"
            )
        if contract.predicate == "equivalent":
            if len(comparison_objects) != 1 or not equivalence_conditions:
                raise ValidationError(
                    "equivalent predicate requires exactly one comparison object "
                    "and at least one frozen equivalence condition"
                )
        elif comparison_objects or equivalence_conditions:
            raise ValidationError(
                "comparison objects and equivalence conditions are reserved for "
                "the equivalent predicate"
            )
        if (
            contract.predicate in _MAP_PREDICATES
            and contract.object_kind not in _MAP_OBJECT_KINDS
        ):
            raise ValidationError(
                f"{contract.predicate} requires a map or operator object"
            )
        if (
            contract.predicate in _POSITIVITY_PREDICATES
            and contract.object_kind not in _POSITIVITY_OBJECT_KINDS
        ):
            raise ValidationError(
                f"{contract.predicate} requires a form, linear operator, or tensor"
            )
        if (
            contract.predicate in _LINEAR_ALGEBRA_PREDICATES
            and contract.object_kind not in _LINEAR_ALGEBRA_OBJECT_KINDS
        ):
            raise ValidationError(
                f"{contract.predicate} requires a linear-algebra object"
            )
        control = controls.get(contract.adversarial_control_id)
        if control is None:
            raise ValidationError(
                "mathematical predicate contract must bind an exact "
                "adversarial control_id"
            )
        if control.family != "adversarial":
            raise ValidationError(
                "mathematical predicate contract control must be adversarial"
            )
        if control.evaluation_gate_id != contract.evaluation_gate_id:
            raise ValidationError(
                "mathematical predicate contract and adversarial control must "
                "share an evaluation gate"
            )
        if contract.evaluation_gate_id not in set(protocol.quality_requirements):
            raise ValidationError(
                "mathematical predicate contract evaluation gate must be a "
                "required protocol quality gate"
            )


def validate_mathematical_predicate_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    gate: QualityGateResult,
    output_hashes: set[str],
    context: str = "",
) -> None:
    """Replay exact predicate attribution without deciding mathematical truth."""

    contracts = [
        item
        for item in protocol.mathematical_predicate_contracts
        if item.evaluation_gate_id == gate.gate_id
    ]
    if not contracts or gate.status is QualityGateStatus.SKIPPED:
        return
    label = f"{context} " if context else ""
    results = gate.details.get("mathematical_predicate_results")
    expected_ids = {item.contract_id for item in contracts}
    if not isinstance(results, dict) or set(results) != expected_ids:
        raise ValidationError(
            f"{label}performed mathematical predicate gate {gate.gate_id} "
            "requires exact results for: " + ", ".join(sorted(expected_ids))
        )
    expected_status = {
        QualityGateStatus.PASSED: "consistent_with_predicate",
        QualityGateStatus.WARNING: "inconclusive",
        QualityGateStatus.FAILED: "contradicted_predicate",
    }.get(gate.status)
    if expected_status is None:
        raise ValidationError(
            f"{label}mathematical predicate gate {gate.gate_id} has an "
            "unsupported status"
        )
    frozen_fields = (
        "object_id",
        "object_kind",
        "domain",
        "codomain",
        "quotient",
        "construction",
        "predicate",
        "predicate_definition",
        "derived_from_object_ids",
        "comparison_object_ids",
        "equivalence_conditions",
    )
    required_fields = {
        *frozen_fields,
        "assessment_status",
        "observed_witness",
        "interpretation",
        "evidence_sha256",
        "evidence_location",
    }
    derived_fields = {"selected_value_sha256"}
    for contract in contracts:
        result = results[contract.contract_id]
        prefix = (
            f"{label}gate {gate.gate_id} mathematical_predicate_results "
            f"{contract.contract_id}"
        )
        if (
            not isinstance(result, dict)
            or not required_fields <= set(result)
            or set(result) - required_fields - derived_fields
        ):
            raise ValidationError(
                f"{label}mathematical predicate result for "
                f"{contract.contract_id} must contain exactly the documented fields"
            )
        for field_name in frozen_fields:
            actual = result[field_name]
            expected = getattr(contract, field_name)
            if isinstance(expected, list):
                require_unique_canonical_text_list(
                    actual, f"{prefix}.{field_name}"
                )
            else:
                require_canonical_text(actual, f"{prefix}.{field_name}")
            if actual != expected:
                raise ValidationError(
                    f"{label}mathematical predicate {field_name} does not match "
                    "the frozen contract"
                )
        for field_name in (
            "assessment_status",
            "observed_witness",
            "interpretation",
            "evidence_location",
        ):
            require_canonical_text(result[field_name], f"{prefix}.{field_name}")
        if result["assessment_status"] != expected_status:
            raise ValidationError(
                f"{label}{gate.status.value} mathematical predicate gate "
                f"requires {expected_status}"
            )
        digest = require_sha256(
            result["evidence_sha256"], f"{prefix}.evidence_sha256"
        )
        if digest not in output_hashes:
            raise ValidationError(
                f"{label}mathematical predicate evidence must reference a run "
                "output artifact"
            )
        if result.get("selected_value_sha256") is not None:
            require_sha256(
                result["selected_value_sha256"],
                f"{prefix}.selected_value_sha256",
            )


_DUALITY_RECONSTRUCTION_SOURCE_STATUSES = {
    "engineering_assumption",
    "mixed",
    "source_derived",
}


def validate_duality_reconstruction_contracts(
    protocol: ExperimentProtocol,
) -> None:
    """Bind a duality pairing and reconstruction without blessing the choice."""

    contracts = protocol.duality_reconstruction_contracts
    if any(
        not isinstance(item, DualityReconstructionContract)
        for item in contracts
    ):
        raise ValidationError(
            "duality_reconstruction_contracts must contain "
            "DualityReconstructionContract values"
        )
    predicate_contracts = {
        item.contract_id: item
        for item in protocol.mathematical_predicate_contracts
    }
    controls = {item.control_id: item for item in protocol.control_definitions}
    contract_ids: set[str] = set()
    for index, contract in enumerate(contracts):
        prefix = f"duality_reconstruction_contracts[{index}]"
        for field_name in (
            "contract_id",
            "predicate_contract_id",
            "primal_space_id",
            "dual_space_id",
            "pairing_id",
            "pairing_definition",
            "reconstruction_map_id",
            "reconstruction_definition",
            "source_status",
            "circularity_control_id",
            "evaluation_gate_id",
        ):
            require_canonical_text(
                getattr(contract, field_name), f"{prefix}.{field_name}"
            )
        if contract.contract_id in contract_ids:
            raise ValidationError(
                "duality reconstruction contract IDs must be unique"
            )
        contract_ids.add(contract.contract_id)
        if contract.primal_space_id == contract.dual_space_id:
            raise ValidationError(
                "duality reconstruction contract must distinguish primal and "
                "dual space IDs"
            )
        predicate_contract = predicate_contracts.get(
            contract.predicate_contract_id
        )
        if predicate_contract is None:
            raise ValidationError(
                "duality reconstruction contract must bind an exact "
                "mathematical predicate contract ID"
            )
        if predicate_contract.evaluation_gate_id != contract.evaluation_gate_id:
            raise ValidationError(
                "duality reconstruction and mathematical predicate contracts "
                "must share an evaluation gate"
            )
        for field_name in (
            "reconstruction_specification_sha256",
            "basis_specification_sha256",
            "quadrature_specification_sha256",
        ):
            require_sha256(getattr(contract, field_name), f"{prefix}.{field_name}")
        if bool(contract.transfer_map_id) != bool(
            contract.transfer_specification_sha256
        ):
            raise ValidationError(
                "duality reconstruction transfer map ID and specification "
                "SHA-256 must be supplied together"
            )
        if contract.transfer_map_id:
            require_canonical_text(
                contract.transfer_map_id, f"{prefix}.transfer_map_id"
            )
            require_sha256(
                contract.transfer_specification_sha256,
                f"{prefix}.transfer_specification_sha256",
            )
        if contract.source_status not in _DUALITY_RECONSTRUCTION_SOURCE_STATUSES:
            raise ValidationError(
                f"{prefix}.source_status is unsupported"
            )
        source_refs = require_unique_canonical_text_list(
            contract.source_refs, f"{prefix}.source_refs"
        )
        forbidden = require_unique_canonical_text_list(
            contract.forbidden_dependency_object_ids,
            f"{prefix}.forbidden_dependency_object_ids",
        )
        if not source_refs:
            raise ValidationError(
                "duality reconstruction contract requires at least one source "
                "or engineering reference"
            )
        if not forbidden:
            raise ValidationError(
                "duality reconstruction contract requires at least one "
                "forbidden dependency object"
            )
        if predicate_contract.object_id not in forbidden:
            raise ValidationError(
                "duality reconstruction forbidden dependencies must include "
                "the linked predicate object"
            )
        required_dependencies = {
            contract.primal_space_id,
            contract.dual_space_id,
            contract.pairing_id,
            contract.reconstruction_map_id,
        }
        if contract.transfer_map_id:
            required_dependencies.add(contract.transfer_map_id)
        impossible = sorted(required_dependencies & set(forbidden))
        if impossible:
            raise ValidationError(
                "duality reconstruction required dependencies cannot also be "
                "forbidden dependency objects: " + ", ".join(impossible)
            )
        control = controls.get(contract.circularity_control_id)
        if control is None:
            raise ValidationError(
                "duality reconstruction contract must bind an exact "
                "circularity control_id"
            )
        if control.family != "adversarial":
            raise ValidationError(
                "duality reconstruction circularity control must be adversarial"
            )
        if control.evaluation_gate_id != contract.evaluation_gate_id:
            raise ValidationError(
                "duality reconstruction contract and circularity control must "
                "share an evaluation gate"
            )
        if contract.evaluation_gate_id not in set(protocol.quality_requirements):
            raise ValidationError(
                "duality reconstruction evaluation gate must be a required "
                "protocol quality gate"
            )


def validate_duality_reconstruction_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    gate: QualityGateResult,
    output_hashes: set[str],
    context: str = "",
) -> None:
    """Replay a reconstruction dependency boundary from retained metadata."""

    contracts = [
        item
        for item in protocol.duality_reconstruction_contracts
        if item.evaluation_gate_id == gate.gate_id
    ]
    if not contracts or gate.status is QualityGateStatus.SKIPPED:
        return
    label = f"{context} " if context else ""
    results = gate.details.get("duality_reconstruction_results")
    expected_ids = {item.contract_id for item in contracts}
    if not isinstance(results, dict) or set(results) != expected_ids:
        raise ValidationError(
            f"{label}performed duality reconstruction gate {gate.gate_id} "
            "requires exact results for: " + ", ".join(sorted(expected_ids))
        )
    expected_status = {
        QualityGateStatus.PASSED: "consistent_with_reconstruction_contract",
        QualityGateStatus.WARNING: "inconclusive",
        QualityGateStatus.FAILED: "contradicted_reconstruction_contract",
    }.get(gate.status)
    if expected_status is None:
        raise ValidationError(
            f"{label}duality reconstruction gate {gate.gate_id} has an "
            "unsupported status"
        )
    frozen_fields = (
        "predicate_contract_id",
        "primal_space_id",
        "dual_space_id",
        "pairing_id",
        "pairing_definition",
        "reconstruction_map_id",
        "reconstruction_definition",
        "reconstruction_specification_sha256",
        "basis_specification_sha256",
        "quadrature_specification_sha256",
        "source_status",
        "source_refs",
        "forbidden_dependency_object_ids",
        "transfer_map_id",
        "transfer_specification_sha256",
    )
    required_fields = {
        *frozen_fields,
        "observed_reconstruction_dependency_object_ids",
        "assessment_status",
        "observed_witness",
        "interpretation",
        "evidence_sha256",
        "evidence_location",
    }
    derived_fields = {"selected_value_sha256"}
    control_results = gate.details.get("control_results")
    for contract in contracts:
        result = results[contract.contract_id]
        prefix = (
            f"{label}gate {gate.gate_id} duality_reconstruction_results "
            f"{contract.contract_id}"
        )
        if (
            not isinstance(result, dict)
            or not required_fields <= set(result)
            or set(result) - required_fields - derived_fields
        ):
            raise ValidationError(
                f"{label}duality reconstruction result for "
                f"{contract.contract_id} must contain exactly the documented fields"
            )
        for field_name in frozen_fields:
            actual = result[field_name]
            expected = getattr(contract, field_name)
            if isinstance(expected, list):
                require_unique_canonical_text_list(
                    actual, f"{prefix}.{field_name}"
                )
            elif expected:
                require_canonical_text(actual, f"{prefix}.{field_name}")
            elif actual != "":
                raise ValidationError(
                    f"{label}duality reconstruction {field_name} does not match "
                    "the frozen contract"
                )
            if actual != expected:
                raise ValidationError(
                    f"{label}duality reconstruction {field_name} does not match "
                    "the frozen contract"
                )
        dependencies = require_unique_canonical_text_list(
            result["observed_reconstruction_dependency_object_ids"],
            f"{prefix}.observed_reconstruction_dependency_object_ids",
        )
        required_dependencies = {
            contract.primal_space_id,
            contract.dual_space_id,
            contract.pairing_id,
            contract.reconstruction_map_id,
        }
        if contract.transfer_map_id:
            required_dependencies.add(contract.transfer_map_id)
        missing_dependencies = sorted(required_dependencies - set(dependencies))
        if missing_dependencies:
            raise ValidationError(
                f"{label}duality reconstruction result omits required "
                "dependency objects: " + ", ".join(missing_dependencies)
            )
        forbidden = sorted(
            set(dependencies) & set(contract.forbidden_dependency_object_ids)
        )
        if gate.status is QualityGateStatus.PASSED and forbidden:
            raise ValidationError(
                f"{label}passed duality reconstruction gate depends on forbidden "
                "objects: " + ", ".join(forbidden)
            )
        for field_name in (
            "assessment_status",
            "observed_witness",
            "interpretation",
            "evidence_location",
        ):
            require_canonical_text(result[field_name], f"{prefix}.{field_name}")
        if result["assessment_status"] != expected_status:
            raise ValidationError(
                f"{label}{gate.status.value} duality reconstruction gate "
                f"requires {expected_status}"
            )
        digest = require_sha256(
            result["evidence_sha256"], f"{prefix}.evidence_sha256"
        )
        if digest not in output_hashes:
            raise ValidationError(
                f"{label}duality reconstruction evidence must reference a run "
                "output artifact"
            )
        linked_control = (
            control_results.get(contract.circularity_control_id)
            if isinstance(control_results, dict)
            else None
        )
        control_fields = {
            "observed_behavior",
            "interpretation",
            "matches_expected",
            "evidence_sha256",
            "evidence_location",
        }
        control_derived_fields = {"selected_value_sha256"}
        if (
            not isinstance(linked_control, dict)
            or not control_fields <= set(linked_control)
            or set(linked_control) - control_fields - control_derived_fields
        ):
            raise ValidationError(
                f"{label}duality reconstruction result requires its exact "
                "linked circularity control evaluation"
            )
        for field_name in (
            "observed_behavior",
            "interpretation",
            "evidence_location",
        ):
            require_canonical_text(
                linked_control[field_name],
                f"{prefix}.linked_control.{field_name}",
            )
        if type(linked_control["matches_expected"]) is not bool:
            raise ValidationError(
                f"{label}duality reconstruction linked control "
                "matches_expected must be a boolean"
            )
        control_digest = require_sha256(
            linked_control["evidence_sha256"],
            f"{prefix}.linked_control.evidence_sha256",
        )
        if control_digest not in output_hashes:
            raise ValidationError(
                f"{label}duality reconstruction linked control evidence must "
                "reference a run output artifact"
            )
        if gate.status is QualityGateStatus.PASSED and not linked_control[
            "matches_expected"
        ]:
            raise ValidationError(
                f"{label}passed duality reconstruction gate requires its "
                "circularity control to match expectation"
            )
        if result.get("selected_value_sha256") is not None:
            require_sha256(
                result["selected_value_sha256"],
                f"{prefix}.selected_value_sha256",
            )


_FAMILY_STABILITY_STATISTICS = {
    "inf_sup_constant",
    "inverse_operator_norm",
    "smallest_singular_value",
}
_FAMILY_STABILITY_COMPARATORS = {
    "greater_than_or_equal",
    "less_than_or_equal",
}


def validate_reconstruction_family_stability_contracts(
    protocol: ExperimentProtocol,
) -> None:
    """Bind continuum-facing reconstruction claims to a tested map family."""

    contracts = protocol.reconstruction_family_stability_contracts
    if any(
        not isinstance(item, ReconstructionFamilyStabilityContract)
        for item in contracts
    ):
        raise ValidationError(
            "reconstruction_family_stability_contracts must contain "
            "ReconstructionFamilyStabilityContract values"
        )
    reconstructions = {
        item.contract_id: item
        for item in protocol.duality_reconstruction_contracts
    }
    controls = {item.control_id: item for item in protocol.control_definitions}
    contract_ids: set[str] = set()
    for index, contract in enumerate(contracts):
        prefix = f"reconstruction_family_stability_contracts[{index}]"
        for field_name in (
            "contract_id",
            "duality_reconstruction_contract_id",
            "resolution_family_id",
            "primal_norm_id",
            "dual_norm_id",
            "stability_statistic",
            "stability_comparator",
            "test_family_span_id",
            "forward_cross_projection_id",
            "reverse_cross_projection_id",
            "adverse_family_control_id",
            "evaluation_gate_id",
        ):
            require_canonical_text(
                getattr(contract, field_name), f"{prefix}.{field_name}"
            )
        if contract.contract_id in contract_ids:
            raise ValidationError(
                "reconstruction family stability contract IDs must be unique"
            )
        contract_ids.add(contract.contract_id)
        reconstruction = reconstructions.get(
            contract.duality_reconstruction_contract_id
        )
        if reconstruction is None:
            raise ValidationError(
                "reconstruction family stability contract must bind an exact "
                "duality reconstruction contract ID"
            )
        if reconstruction.evaluation_gate_id != contract.evaluation_gate_id:
            raise ValidationError(
                "reconstruction family stability and duality reconstruction "
                "contracts must share an evaluation gate"
            )
        resolutions = require_unique_canonical_text_list(
            contract.resolution_ids, f"{prefix}.resolution_ids"
        )
        if len(resolutions) < 2:
            raise ValidationError(
                "reconstruction family stability contract requires at least "
                "two resolution IDs"
            )
        if contract.primal_norm_id == contract.dual_norm_id:
            raise ValidationError(
                "reconstruction family stability contract must distinguish "
                "primal and dual norm IDs"
            )
        if contract.stability_statistic not in _FAMILY_STABILITY_STATISTICS:
            raise ValidationError(f"{prefix}.stability_statistic is unsupported")
        if contract.stability_comparator not in _FAMILY_STABILITY_COMPARATORS:
            raise ValidationError(f"{prefix}.stability_comparator is unsupported")
        expected_comparator = (
            "less_than_or_equal"
            if contract.stability_statistic == "inverse_operator_norm"
            else "greater_than_or_equal"
        )
        if contract.stability_comparator != expected_comparator:
            raise ValidationError(
                f"{prefix}.stability_comparator must be {expected_comparator} "
                f"for {contract.stability_statistic}"
            )
        threshold = contract.stability_threshold
        if type(threshold) is bool or not isinstance(threshold, (int, float)):
            raise ValidationError(f"{prefix}.stability_threshold must be numeric")
        if not math.isfinite(float(threshold)) or float(threshold) < 0:
            raise ValidationError(
                f"{prefix}.stability_threshold must be finite and nonnegative"
            )
        cross_threshold = contract.cross_projection_error_threshold
        if type(cross_threshold) is bool or not isinstance(
            cross_threshold, (int, float)
        ):
            raise ValidationError(
                f"{prefix}.cross_projection_error_threshold must be numeric"
            )
        if not math.isfinite(float(cross_threshold)) or float(cross_threshold) < 0:
            raise ValidationError(
                f"{prefix}.cross_projection_error_threshold must be finite "
                "and nonnegative"
            )
        if (
            contract.forward_cross_projection_id
            == contract.reverse_cross_projection_id
        ):
            raise ValidationError(
                "reconstruction family stability contract requires distinct "
                "forward and reverse cross-projection IDs"
            )
        transfers = require_unique_canonical_text_list(
            contract.transfer_map_ids, f"{prefix}.transfer_map_ids"
        )
        if not transfers:
            raise ValidationError(
                "reconstruction family stability contract requires at least "
                "one transfer map ID"
            )
        if len(transfers) < len(resolutions) - 1:
            raise ValidationError(
                "reconstruction family stability contract requires at least "
                "one transfer map per adjacent resolution pair"
            )
        if (
            reconstruction.transfer_map_id
            and reconstruction.transfer_map_id not in transfers
        ):
            raise ValidationError(
                "reconstruction family stability transfer maps must include "
                "the linked duality reconstruction transfer map"
            )
        for field_name in (
            "norm_specification_sha256",
            "stability_specification_sha256",
            "family_specification_sha256",
            "test_family_specification_sha256",
            "cross_projection_specification_sha256",
            "transfer_specification_sha256",
            "adverse_family_specification_sha256",
        ):
            require_sha256(getattr(contract, field_name), f"{prefix}.{field_name}")
        control = controls.get(contract.adverse_family_control_id)
        if control is None:
            raise ValidationError(
                "reconstruction family stability contract must bind an exact "
                "adverse family control_id"
            )
        if control.family != "adversarial":
            raise ValidationError(
                "reconstruction family stability control must be adversarial"
            )
        if control.evaluation_gate_id != contract.evaluation_gate_id:
            raise ValidationError(
                "reconstruction family stability contract and adverse control "
                "must share an evaluation gate"
            )
        if contract.evaluation_gate_id not in set(protocol.quality_requirements):
            raise ValidationError(
                "reconstruction family stability evaluation gate must be a "
                "required protocol quality gate"
            )


def validate_reconstruction_family_stability_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    gate: QualityGateResult,
    output_hashes: set[str],
    context: str = "",
) -> None:
    """Replay family stability and two-way cross-projection observations."""

    contracts = [
        item
        for item in protocol.reconstruction_family_stability_contracts
        if item.evaluation_gate_id == gate.gate_id
    ]
    if not contracts or gate.status is QualityGateStatus.SKIPPED:
        return
    label = f"{context} " if context else ""
    results = gate.details.get("reconstruction_family_stability_results")
    expected_ids = {item.contract_id for item in contracts}
    if not isinstance(results, dict) or set(results) != expected_ids:
        raise ValidationError(
            f"{label}performed reconstruction family stability gate "
            f"{gate.gate_id} requires exact results for: "
            + ", ".join(sorted(expected_ids))
        )
    expected_status = {
        QualityGateStatus.PASSED: "consistent_with_family_stability_contract",
        QualityGateStatus.WARNING: "inconclusive",
        QualityGateStatus.FAILED: "contradicted_family_stability_contract",
    }.get(gate.status)
    if expected_status is None:
        raise ValidationError(
            f"{label}reconstruction family stability gate {gate.gate_id} has "
            "an unsupported status"
        )
    frozen_fields = (
        "duality_reconstruction_contract_id",
        "resolution_family_id",
        "resolution_ids",
        "primal_norm_id",
        "dual_norm_id",
        "norm_specification_sha256",
        "stability_statistic",
        "stability_comparator",
        "stability_threshold",
        "stability_specification_sha256",
        "family_specification_sha256",
        "test_family_span_id",
        "test_family_specification_sha256",
        "forward_cross_projection_id",
        "reverse_cross_projection_id",
        "cross_projection_specification_sha256",
        "cross_projection_error_threshold",
        "transfer_map_ids",
        "transfer_specification_sha256",
        "adverse_family_specification_sha256",
    )
    required_fields = {
        *frozen_fields,
        "observed_resolution_ids",
        "observed_stability_values",
        "observed_forward_cross_projection_error",
        "observed_reverse_cross_projection_error",
        "assessment_status",
        "observed_witness",
        "interpretation",
        "evidence_sha256",
        "evidence_location",
    }
    derived_fields = {"selected_value_sha256"}
    control_results = gate.details.get("control_results")
    for contract in contracts:
        result = results[contract.contract_id]
        prefix = (
            f"{label}gate {gate.gate_id} "
            "reconstruction_family_stability_results "
            f"{contract.contract_id}"
        )
        if (
            not isinstance(result, dict)
            or not required_fields <= set(result)
            or set(result) - required_fields - derived_fields
        ):
            raise ValidationError(
                f"{label}reconstruction family stability result for "
                f"{contract.contract_id} must contain exactly the documented fields"
            )
        for field_name in frozen_fields:
            actual = result[field_name]
            expected = getattr(contract, field_name)
            if isinstance(expected, list):
                require_unique_canonical_text_list(actual, f"{prefix}.{field_name}")
            elif isinstance(expected, str):
                require_canonical_text(actual, f"{prefix}.{field_name}")
            elif field_name in {
                "stability_threshold",
                "cross_projection_error_threshold",
            } and (
                type(actual) is bool
                or not isinstance(actual, (int, float))
                or not math.isfinite(float(actual))
            ):
                raise ValidationError(f"{prefix}.{field_name} must be finite numeric")
            if actual != expected:
                raise ValidationError(
                    f"{label}reconstruction family stability {field_name} "
                    "does not match the frozen contract"
                )
        observed_resolutions = require_unique_canonical_text_list(
            result["observed_resolution_ids"],
            f"{prefix}.observed_resolution_ids",
        )
        if observed_resolutions != contract.resolution_ids:
            raise ValidationError(
                f"{label}reconstruction family stability observed resolutions "
                "do not match the frozen family"
            )
        values = result["observed_stability_values"]
        if not isinstance(values, dict) or set(values) != set(
            contract.resolution_ids
        ):
            raise ValidationError(
                f"{label}reconstruction family stability requires one exact "
                "stability value per frozen resolution"
            )
        numeric_values: list[float] = []
        for resolution_id in contract.resolution_ids:
            value = values[resolution_id]
            if type(value) is bool or not isinstance(value, (int, float)):
                raise ValidationError(
                    f"{prefix}.observed_stability_values[{resolution_id}] must "
                    "be numeric"
                )
            numeric = float(value)
            if not math.isfinite(numeric) or numeric < 0:
                raise ValidationError(
                    f"{prefix}.observed_stability_values[{resolution_id}] must "
                    "be finite and nonnegative"
                )
            numeric_values.append(numeric)
        cross_errors: list[float] = []
        for field_name in (
            "observed_forward_cross_projection_error",
            "observed_reverse_cross_projection_error",
        ):
            value = result[field_name]
            if type(value) is bool or not isinstance(value, (int, float)):
                raise ValidationError(f"{prefix}.{field_name} must be numeric")
            numeric = float(value)
            if not math.isfinite(numeric) or numeric < 0:
                raise ValidationError(
                    f"{prefix}.{field_name} must be finite and nonnegative"
                )
            cross_errors.append(numeric)
        if gate.status is QualityGateStatus.PASSED:
            if contract.stability_comparator == "greater_than_or_equal":
                stable = all(
                    value >= contract.stability_threshold
                    for value in numeric_values
                )
            else:
                stable = all(
                    value <= contract.stability_threshold
                    for value in numeric_values
                )
            if not stable:
                raise ValidationError(
                    f"{label}passed reconstruction family stability gate "
                    "violates its frozen stability threshold"
                )
            if any(
                value > contract.cross_projection_error_threshold
                for value in cross_errors
            ):
                raise ValidationError(
                    f"{label}passed reconstruction family stability gate "
                    "violates its frozen cross-projection error threshold"
                )
        for field_name in (
            "assessment_status",
            "observed_witness",
            "interpretation",
            "evidence_location",
        ):
            require_canonical_text(result[field_name], f"{prefix}.{field_name}")
        if result["assessment_status"] != expected_status:
            raise ValidationError(
                f"{label}{gate.status.value} reconstruction family stability "
                f"gate requires {expected_status}"
            )
        digest = require_sha256(
            result["evidence_sha256"], f"{prefix}.evidence_sha256"
        )
        if digest not in output_hashes:
            raise ValidationError(
                f"{label}reconstruction family stability evidence must "
                "reference a run output artifact"
            )
        linked_control = (
            control_results.get(contract.adverse_family_control_id)
            if isinstance(control_results, dict)
            else None
        )
        control_fields = {
            "observed_behavior",
            "interpretation",
            "matches_expected",
            "evidence_sha256",
            "evidence_location",
        }
        control_derived_fields = {"selected_value_sha256"}
        if (
            not isinstance(linked_control, dict)
            or not control_fields <= set(linked_control)
            or set(linked_control) - control_fields - control_derived_fields
        ):
            raise ValidationError(
                f"{label}reconstruction family stability result requires its "
                "exact linked adverse-family control evaluation"
            )
        if type(linked_control["matches_expected"]) is not bool:
            raise ValidationError(
                f"{label}reconstruction family stability linked control "
                "matches_expected must be a boolean"
            )
        control_digest = require_sha256(
            linked_control["evidence_sha256"],
            f"{prefix}.linked_control.evidence_sha256",
        )
        if control_digest not in output_hashes:
            raise ValidationError(
                f"{label}reconstruction family stability linked control "
                "evidence must reference a run output artifact"
            )
        if gate.status is QualityGateStatus.PASSED and not linked_control[
            "matches_expected"
        ]:
            raise ValidationError(
                f"{label}passed reconstruction family stability gate requires "
                "its adverse-family control to match expectation"
            )
        if result.get("selected_value_sha256") is not None:
            require_sha256(
                result["selected_value_sha256"],
                f"{prefix}.selected_value_sha256",
            )


_ANALYSIS_IMPLEMENTATION_CLOSURE_METHODS = {
    "runtime_trace",
    "static_import_graph",
    "static_plus_runtime_trace",
}


def analysis_implementation_bundle_sha256(
    members: Sequence[AnalysisImplementationMember],
) -> str:
    """Hash the complete ordered member records, not a submitter scalar."""

    payload = [member.to_dict() for member in members]
    try:
        content = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "analysis implementation members are not canonical JSON"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def validate_analysis_implementation_bundle_contracts(
    protocol: ExperimentProtocol,
) -> None:
    """Bind an analysis to an exact declared implementation member surface."""

    contracts = protocol.analysis_implementation_bundle_contracts
    if any(
        not isinstance(item, AnalysisImplementationBundleContract)
        for item in contracts
    ):
        raise ValidationError(
            "analysis_implementation_bundle_contracts must contain "
            "AnalysisImplementationBundleContract values"
        )
    controls = {item.control_id: item for item in protocol.control_definitions}
    contract_ids: set[str] = set()
    for index, contract in enumerate(contracts):
        prefix = f"analysis_implementation_bundle_contracts[{index}]"
        for field_name in (
            "contract_id",
            "closure_method",
            "adverse_omission_control_id",
            "evaluation_gate_id",
        ):
            require_canonical_text(
                getattr(contract, field_name), f"{prefix}.{field_name}"
            )
        if contract.contract_id in contract_ids:
            raise ValidationError(
                "analysis implementation bundle contract IDs must be unique"
            )
        contract_ids.add(contract.contract_id)
        require_sha256(
            contract.analysis_code_hash, f"{prefix}.analysis_code_hash"
        )
        if contract.analysis_code_hash != protocol.analysis_code_hash:
            raise ValidationError(
                "analysis implementation bundle must bind the protocol "
                "analysis_code_hash"
            )
        if contract.closure_method not in _ANALYSIS_IMPLEMENTATION_CLOSURE_METHODS:
            raise ValidationError(f"{prefix}.closure_method is unsupported")
        entrypoints = require_unique_canonical_text_list(
            contract.entrypoint_locators, f"{prefix}.entrypoint_locators"
        )
        if not entrypoints:
            raise ValidationError(
                "analysis implementation bundle requires at least one entrypoint"
            )
        if any(
            not isinstance(member, AnalysisImplementationMember)
            for member in contract.members
        ):
            raise ValidationError(
                "analysis implementation bundle members must be "
                "AnalysisImplementationMember values"
            )
        if not contract.members:
            raise ValidationError(
                "analysis implementation bundle requires at least one member"
            )
        locators: list[str] = []
        for member_index, member in enumerate(contract.members):
            member_prefix = f"{prefix}.members[{member_index}]"
            locator = require_canonical_text(
                member.locator, f"{member_prefix}.locator"
            )
            locator_path = Path(locator)
            if locator_path.is_absolute() or ".." in locator_path.parts:
                raise ValidationError(
                    f"{member_prefix}.locator must be a safe relative code locator"
                )
            require_canonical_text(member.role, f"{member_prefix}.role")
            require_sha256(member.sha256, f"{member_prefix}.sha256")
            if type(member.size_bytes) is bool or not isinstance(
                member.size_bytes, int
            ) or member.size_bytes < 0:
                raise ValidationError(
                    f"{member_prefix}.size_bytes must be a nonnegative integer"
                )
            locators.append(locator)
        if len(set(locators)) != len(locators):
            raise ValidationError(
                "analysis implementation bundle member locators must be unique"
            )
        if locators != sorted(locators):
            raise ValidationError(
                "analysis implementation bundle members must be sorted by locator"
            )
        if not set(entrypoints) <= set(locators):
            raise ValidationError(
                "analysis implementation bundle entrypoints must be exact members"
            )
        limitations = require_unique_canonical_text_list(
            contract.closure_limitations, f"{prefix}.closure_limitations"
        )
        if not limitations:
            raise ValidationError(
                "analysis implementation bundle must declare closure limitations"
            )
        require_unique_canonical_text_list(
            contract.allowed_external_dependency_ids,
            f"{prefix}.allowed_external_dependency_ids",
        )
        for field_name in (
            "bundle_sha256",
            "closure_specification_sha256",
            "external_dependency_specification_sha256",
            "observed_member_receipt_specification_sha256",
        ):
            require_sha256(getattr(contract, field_name), f"{prefix}.{field_name}")
        expected_bundle_sha256 = analysis_implementation_bundle_sha256(
            contract.members
        )
        if contract.bundle_sha256 != expected_bundle_sha256:
            raise ValidationError(
                "analysis implementation bundle_sha256 does not match its "
                "complete frozen member records"
            )
        control = controls.get(contract.adverse_omission_control_id)
        if control is None:
            raise ValidationError(
                "analysis implementation bundle must bind an exact adverse "
                "omission control_id"
            )
        if control.family != "adversarial":
            raise ValidationError(
                "analysis implementation bundle omission control must be adversarial"
            )
        if control.evaluation_gate_id != contract.evaluation_gate_id:
            raise ValidationError(
                "analysis implementation bundle and omission control must share "
                "an evaluation gate"
            )
        if contract.evaluation_gate_id not in set(protocol.quality_requirements):
            raise ValidationError(
                "analysis implementation bundle evaluation gate must be a "
                "required protocol quality gate"
            )


def validate_analysis_implementation_bundle_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    gate: QualityGateResult,
    output_hashes: set[str],
    context: str = "",
) -> None:
    """Replay declared-versus-observed analysis implementation closure."""

    contracts = [
        item
        for item in protocol.analysis_implementation_bundle_contracts
        if item.evaluation_gate_id == gate.gate_id
    ]
    if not contracts or gate.status is QualityGateStatus.SKIPPED:
        return
    label = f"{context} " if context else ""
    results = gate.details.get("analysis_implementation_bundle_results")
    expected_ids = {item.contract_id for item in contracts}
    if not isinstance(results, dict) or set(results) != expected_ids:
        raise ValidationError(
            f"{label}performed analysis implementation bundle gate "
            f"{gate.gate_id} requires exact results for: "
            + ", ".join(sorted(expected_ids))
        )
    expected_status = {
        QualityGateStatus.PASSED: "consistent_with_implementation_bundle_contract",
        QualityGateStatus.WARNING: "inconclusive",
        QualityGateStatus.FAILED: "contradicted_implementation_bundle_contract",
    }.get(gate.status)
    if expected_status is None:
        raise ValidationError(
            f"{label}analysis implementation bundle gate {gate.gate_id} has "
            "an unsupported status"
        )
    frozen_fields = (
        "analysis_code_hash",
        "entrypoint_locators",
        "members",
        "bundle_sha256",
        "closure_method",
        "closure_specification_sha256",
        "closure_limitations",
        "allowed_external_dependency_ids",
        "external_dependency_specification_sha256",
        "observed_member_receipt_specification_sha256",
    )
    required_fields = {
        *frozen_fields,
        "observed_entrypoint_locators",
        "observed_member_locators",
        "observed_member_sha256s",
        "observed_bundle_sha256",
        "observed_closure_method",
        "observed_external_dependency_ids",
        "observed_closure_complete",
        "assessment_status",
        "observed_witness",
        "interpretation",
        "evidence_sha256",
        "evidence_location",
    }
    derived_fields = {"selected_value_sha256"}
    control_results = gate.details.get("control_results")
    for contract in contracts:
        result = results[contract.contract_id]
        prefix = (
            f"{label}gate {gate.gate_id} "
            "analysis_implementation_bundle_results "
            f"{contract.contract_id}"
        )
        if (
            not isinstance(result, dict)
            or not required_fields <= set(result)
            or set(result) - required_fields - derived_fields
        ):
            raise ValidationError(
                f"{label}analysis implementation bundle result for "
                f"{contract.contract_id} must contain exactly the documented fields"
            )
        frozen_expected = {
            **contract.to_dict(),
        }
        frozen_expected.pop("contract_id")
        frozen_expected.pop("adverse_omission_control_id")
        frozen_expected.pop("evaluation_gate_id")
        for field_name in frozen_fields:
            if result[field_name] != frozen_expected[field_name]:
                raise ValidationError(
                    f"{label}analysis implementation bundle {field_name} "
                    "does not match the frozen contract"
                )
        observed_entrypoints = require_unique_canonical_text_list(
            result["observed_entrypoint_locators"],
            f"{prefix}.observed_entrypoint_locators",
        )
        observed_locators = require_unique_canonical_text_list(
            result["observed_member_locators"],
            f"{prefix}.observed_member_locators",
        )
        expected_locators = [member.locator for member in contract.members]
        if observed_entrypoints != contract.entrypoint_locators:
            raise ValidationError(
                f"{label}analysis implementation observed entrypoints do not "
                "match the frozen contract"
            )
        if observed_locators != expected_locators:
            raise ValidationError(
                f"{label}analysis implementation observed member set does not "
                "match the frozen complete member set: "
                f"observed={observed_locators!r}, expected={expected_locators!r}"
            )
        observed_hashes = result["observed_member_sha256s"]
        expected_hashes = {
            member.locator: member.sha256 for member in contract.members
        }
        if not isinstance(observed_hashes, dict) or observed_hashes != expected_hashes:
            raise ValidationError(
                f"{label}analysis implementation observed member hashes do not "
                "match the frozen complete member records"
            )
        observed_bundle = require_sha256(
            result["observed_bundle_sha256"],
            f"{prefix}.observed_bundle_sha256",
        )
        if observed_bundle != contract.bundle_sha256:
            raise ValidationError(
                f"{label}analysis implementation observed bundle hash does not "
                "match the frozen contract"
            )
        require_canonical_text(
            result["observed_closure_method"],
            f"{prefix}.observed_closure_method",
        )
        if result["observed_closure_method"] != contract.closure_method:
            raise ValidationError(
                f"{label}analysis implementation observed closure method does "
                "not match the frozen contract"
            )
        observed_external = require_unique_canonical_text_list(
            result["observed_external_dependency_ids"],
            f"{prefix}.observed_external_dependency_ids",
        )
        if observed_external != contract.allowed_external_dependency_ids:
            raise ValidationError(
                f"{label}analysis implementation observed external dependencies "
                "do not match the frozen boundary"
            )
        if type(result["observed_closure_complete"]) is not bool:
            raise ValidationError(
                f"{prefix}.observed_closure_complete must be a boolean"
            )
        if gate.status is QualityGateStatus.PASSED and not result[
            "observed_closure_complete"
        ]:
            raise ValidationError(
                f"{label}passed analysis implementation bundle gate requires "
                "complete declared-versus-observed closure"
            )
        for field_name in (
            "assessment_status",
            "observed_witness",
            "interpretation",
            "evidence_location",
        ):
            require_canonical_text(result[field_name], f"{prefix}.{field_name}")
        if result["assessment_status"] != expected_status:
            raise ValidationError(
                f"{label}{gate.status.value} analysis implementation bundle "
                f"gate requires {expected_status}"
            )
        digest = require_sha256(
            result["evidence_sha256"], f"{prefix}.evidence_sha256"
        )
        if digest not in output_hashes:
            raise ValidationError(
                f"{label}analysis implementation bundle evidence must reference "
                "a run output artifact"
            )
        linked_control = (
            control_results.get(contract.adverse_omission_control_id)
            if isinstance(control_results, dict)
            else None
        )
        control_fields = {
            "observed_behavior",
            "interpretation",
            "matches_expected",
            "evidence_sha256",
            "evidence_location",
        }
        control_derived_fields = {"selected_value_sha256"}
        if (
            not isinstance(linked_control, dict)
            or not control_fields <= set(linked_control)
            or set(linked_control) - control_fields - control_derived_fields
        ):
            raise ValidationError(
                f"{label}analysis implementation bundle result requires its "
                "exact linked adverse-omission control evaluation"
            )
        if type(linked_control["matches_expected"]) is not bool:
            raise ValidationError(
                f"{label}analysis implementation bundle linked control "
                "matches_expected must be a boolean"
            )
        control_digest = require_sha256(
            linked_control["evidence_sha256"],
            f"{prefix}.linked_control.evidence_sha256",
        )
        if control_digest not in output_hashes:
            raise ValidationError(
                f"{label}analysis implementation bundle linked control evidence "
                "must reference a run output artifact"
            )
        if gate.status is QualityGateStatus.PASSED and not linked_control[
            "matches_expected"
        ]:
            raise ValidationError(
                f"{label}passed analysis implementation bundle gate requires "
                "its adverse-omission control to match expectation"
            )
        if result.get("selected_value_sha256") is not None:
            require_sha256(
                result["selected_value_sha256"],
                f"{prefix}.selected_value_sha256",
            )


_ROUTE_STATIC_SEPARATION_METHODS = {
    "static_import_graph",
    "static_dependency_graph",
}
_ROUTE_RUNTIME_SEPARATION_METHODS = {
    "runtime_import_trace",
    "runtime_call_trace",
}
_ROUTE_COMPARATORS = {
    "less_than",
    "less_than_or_equal",
    "equal",
    "greater_than_or_equal",
    "greater_than",
}


def _route_edge_key(edge: CrossRouteDependencyEdge) -> tuple[str, str, str]:
    return (
        edge.source_route_id,
        edge.target_route_id,
        edge.dependency_member_locator,
    )


def _complete_forbidden_cross_route_edges(
    *,
    route_ids: Sequence[str],
    bundles: Sequence[AnalysisImplementationBundleContract],
    approved_shared_member_locators: Sequence[str],
) -> list[CrossRouteDependencyEdge]:
    shared = set(approved_shared_member_locators)
    edges: list[CrossRouteDependencyEdge] = []
    for source_index, source_route_id in enumerate(route_ids):
        target_index = 1 - source_index
        target_route_id = route_ids[target_index]
        target_locators = {
            member.locator for member in bundles[target_index].members
        }
        for locator in sorted(target_locators - shared):
            edges.append(CrossRouteDependencyEdge(
                source_route_id=source_route_id,
                target_route_id=target_route_id,
                dependency_member_locator=locator,
            ))
    return sorted(edges, key=_route_edge_key)


def validate_computation_route_separation_contracts(
    protocol: ExperimentProtocol,
) -> None:
    """Bind exactly two declared code routes without claiming independence."""

    contracts = protocol.computation_route_separation_contracts
    if any(
        not isinstance(item, ComputationRouteSeparationContract)
        for item in contracts
    ):
        raise ValidationError(
            "computation_route_separation_contracts must contain "
            "ComputationRouteSeparationContract values"
        )
    controls = {item.control_id: item for item in protocol.control_definitions}
    predicates = {
        item.contract_id: item for item in protocol.mathematical_predicate_contracts
    }
    bundles_by_id = {
        item.contract_id: item
        for item in protocol.analysis_implementation_bundle_contracts
    }
    contract_ids: set[str] = set()
    for index, contract in enumerate(contracts):
        prefix = f"computation_route_separation_contracts[{index}]"
        for field_name in (
            "contract_id",
            "comparison_predicate_contract_id",
            "comparison_domain",
            "norm_id",
            "comparison_unit",
            "comparison_comparator",
            "static_separation_method",
            "runtime_separation_method",
            "adverse_shared_helper_control_id",
            "evaluation_gate_id",
        ):
            require_canonical_text(
                getattr(contract, field_name), f"{prefix}.{field_name}"
            )
        if contract.contract_id in contract_ids:
            raise ValidationError(
                "computation route separation contract IDs must be unique"
            )
        contract_ids.add(contract.contract_id)
        route_ids = require_unique_canonical_text_list(
            contract.route_ids, f"{prefix}.route_ids"
        )
        if len(route_ids) != 2:
            raise ValidationError(
                "computation route separation contract requires exactly two "
                "distinct route IDs"
            )
        bundle_ids = require_unique_canonical_text_list(
            contract.implementation_bundle_contract_ids,
            f"{prefix}.implementation_bundle_contract_ids",
        )
        if len(bundle_ids) != 2:
            raise ValidationError(
                "computation route separation contract requires exactly two "
                "distinct implementation bundle contract IDs"
            )
        try:
            bundles = [bundles_by_id[bundle_id] for bundle_id in bundle_ids]
        except KeyError as exc:
            raise ValidationError(
                "computation route separation contract references an unknown "
                "analysis implementation bundle contract"
            ) from exc
        shared_inputs = require_unique_canonical_text_list(
            contract.approved_shared_input_object_ids,
            f"{prefix}.approved_shared_input_object_ids",
        )
        if not shared_inputs:
            raise ValidationError(
                "computation route separation contract requires at least one "
                "approved shared input object ID"
            )
        if shared_inputs != sorted(shared_inputs):
            raise ValidationError(
                "approved shared input object IDs must be sorted"
            )
        shared_members = require_unique_canonical_text_list(
            contract.approved_shared_member_locators,
            f"{prefix}.approved_shared_member_locators",
        )
        if shared_members != sorted(shared_members):
            raise ValidationError(
                "approved shared member locators must be sorted"
            )
        for member_index, locator in enumerate(shared_members):
            path = Path(locator)
            if path.is_absolute() or ".." in path.parts:
                raise ValidationError(
                    f"{prefix}.approved_shared_member_locators[{member_index}] "
                    "must be a safe relative code locator"
                )
        bundle_member_sets = [
            {member.locator for member in bundle.members} for bundle in bundles
        ]
        actual_shared_members = sorted(
            bundle_member_sets[0] & bundle_member_sets[1]
        )
        if shared_members != actual_shared_members:
            raise ValidationError(
                "approved shared member locators must exactly equal the two "
                "implementation bundles' shared member surface"
            )
        bundle_members_by_locator = [
            {member.locator: member for member in bundle.members}
            for bundle in bundles
        ]
        for locator in shared_members:
            first = bundle_members_by_locator[0][locator]
            second = bundle_members_by_locator[1][locator]
            if (
                first.sha256 != second.sha256
                or first.size_bytes != second.size_bytes
            ):
                raise ValidationError(
                    "approved shared member locators must have identical byte "
                    "hashes and sizes in both implementation bundles"
                )
        if any(
            not (member_set - set(shared_members))
            for member_set in bundle_member_sets
        ):
            raise ValidationError(
                "each computation route requires at least one route-exclusive "
                "implementation member"
            )
        edges = contract.forbidden_cross_route_dependency_edges
        if any(not isinstance(item, CrossRouteDependencyEdge) for item in edges):
            raise ValidationError(
                "forbidden cross-route dependencies must be "
                "CrossRouteDependencyEdge values"
            )
        for edge_index, edge in enumerate(edges):
            edge_prefix = (
                f"{prefix}.forbidden_cross_route_dependency_edges[{edge_index}]"
            )
            for field_name in (
                "source_route_id",
                "target_route_id",
                "dependency_member_locator",
            ):
                require_canonical_text(
                    getattr(edge, field_name), f"{edge_prefix}.{field_name}"
                )
            path = Path(edge.dependency_member_locator)
            if path.is_absolute() or ".." in path.parts:
                raise ValidationError(
                    f"{edge_prefix}.dependency_member_locator must be a safe "
                    "relative code locator"
                )
        expected_edges = _complete_forbidden_cross_route_edges(
            route_ids=route_ids,
            bundles=bundles,
            approved_shared_member_locators=shared_members,
        )
        if edges != expected_edges:
            raise ValidationError(
                "forbidden cross-route dependency edges must exactly cover both "
                "directed route-to-exclusive-member boundaries in sorted order"
            )
        predicate = predicates.get(contract.comparison_predicate_contract_id)
        if predicate is None:
            raise ValidationError(
                "computation route separation contract must bind an exact "
                "mathematical predicate contract ID"
            )
        if predicate.domain != contract.comparison_domain:
            raise ValidationError(
                "computation route comparison domain must match its mathematical "
                "predicate contract"
            )
        if predicate.evaluation_gate_id != contract.evaluation_gate_id:
            raise ValidationError(
                "computation route separation and comparison predicate must "
                "share an evaluation gate"
            )
        for field_name in (
            "comparison_domain_specification_sha256",
            "alignment_specification_sha256",
            "norm_specification_sha256",
            "static_separation_specification_sha256",
            "runtime_separation_specification_sha256",
        ):
            require_sha256(getattr(contract, field_name), f"{prefix}.{field_name}")
        if contract.comparison_comparator not in _ROUTE_COMPARATORS:
            raise ValidationError(
                f"{prefix}.comparison_comparator is unsupported"
            )
        tolerance = contract.comparison_tolerance
        if type(tolerance) is bool or not isinstance(tolerance, (int, float)):
            raise ValidationError(
                f"{prefix}.comparison_tolerance must be numeric"
            )
        if not math.isfinite(float(tolerance)) or float(tolerance) < 0:
            raise ValidationError(
                f"{prefix}.comparison_tolerance must be finite and nonnegative"
            )
        if contract.static_separation_method not in _ROUTE_STATIC_SEPARATION_METHODS:
            raise ValidationError(
                f"{prefix}.static_separation_method is unsupported"
            )
        if contract.runtime_separation_method not in _ROUTE_RUNTIME_SEPARATION_METHODS:
            raise ValidationError(
                f"{prefix}.runtime_separation_method is unsupported"
            )
        limitations = require_unique_canonical_text_list(
            contract.separation_limitations,
            f"{prefix}.separation_limitations",
        )
        if not limitations:
            raise ValidationError(
                "computation route separation contract must declare limitations"
            )
        control = controls.get(contract.adverse_shared_helper_control_id)
        if control is None:
            raise ValidationError(
                "computation route separation contract must bind an exact "
                "adverse shared-helper control ID"
            )
        if control.family != "adversarial":
            raise ValidationError(
                "computation route shared-helper control must be adversarial"
            )
        if control.evaluation_gate_id != contract.evaluation_gate_id:
            raise ValidationError(
                "computation route separation contract and shared-helper control "
                "must share an evaluation gate"
            )
        if contract.evaluation_gate_id not in set(protocol.quality_requirements):
            raise ValidationError(
                "computation route separation evaluation gate must be a required "
                "protocol quality gate"
            )


def _parse_observed_route_edges(
    value: Any,
    *,
    route_ids: Sequence[str],
    label: str,
) -> list[CrossRouteDependencyEdge]:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be an array")
    fields = {
        "source_route_id",
        "target_route_id",
        "dependency_member_locator",
    }
    edges: list[CrossRouteDependencyEdge] = []
    for index, item in enumerate(value):
        prefix = f"{label}[{index}]"
        if not isinstance(item, dict) or set(item) != fields:
            raise ValidationError(
                f"{prefix} must contain exactly the documented fields"
            )
        edge = CrossRouteDependencyEdge(**item)
        if (
            edge.source_route_id not in route_ids
            or edge.target_route_id not in route_ids
            or edge.source_route_id == edge.target_route_id
        ):
            raise ValidationError(
                f"{prefix} must connect the two distinct frozen route IDs"
            )
        path = Path(require_canonical_text(
            edge.dependency_member_locator,
            f"{prefix}.dependency_member_locator",
        ))
        if path.is_absolute() or ".." in path.parts:
            raise ValidationError(
                f"{prefix}.dependency_member_locator must be a safe relative "
                "code locator"
            )
        edges.append(edge)
    if len({_route_edge_key(edge) for edge in edges}) != len(edges):
        raise ValidationError(f"{label} must not contain duplicates")
    if edges != sorted(edges, key=_route_edge_key):
        raise ValidationError(f"{label} must be sorted")
    return edges


def _route_comparison_satisfied(
    value: float,
    comparator: str,
    tolerance: float,
) -> bool:
    return {
        "less_than": value < tolerance,
        "less_than_or_equal": value <= tolerance,
        "equal": value == tolerance,
        "greater_than_or_equal": value >= tolerance,
        "greater_than": value > tolerance,
    }[comparator]


def validate_computation_route_separation_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    gate: QualityGateResult,
    output_hashes: set[str],
    context: str = "",
) -> None:
    """Replay a two-route separation and comparison receipt."""

    contracts = [
        item
        for item in protocol.computation_route_separation_contracts
        if item.evaluation_gate_id == gate.gate_id
    ]
    if not contracts or gate.status is QualityGateStatus.SKIPPED:
        return
    label = f"{context} " if context else ""
    results = gate.details.get("computation_route_separation_results")
    expected_ids = {item.contract_id for item in contracts}
    if not isinstance(results, dict) or set(results) != expected_ids:
        raise ValidationError(
            f"{label}performed computation route separation gate "
            f"{gate.gate_id} requires exact results for: "
            + ", ".join(sorted(expected_ids))
        )
    expected_status = {
        QualityGateStatus.PASSED: "consistent_with_route_separation_contract",
        QualityGateStatus.WARNING: "inconclusive",
        QualityGateStatus.FAILED: "contradicted_route_separation_contract",
    }.get(gate.status)
    if expected_status is None:
        raise ValidationError(
            f"{label}computation route separation gate {gate.gate_id} has an "
            "unsupported status"
        )
    frozen_fields = (
        "comparison_predicate_contract_id",
        "route_ids",
        "implementation_bundle_contract_ids",
        "approved_shared_input_object_ids",
        "approved_shared_member_locators",
        "forbidden_cross_route_dependency_edges",
        "comparison_domain",
        "comparison_domain_specification_sha256",
        "alignment_specification_sha256",
        "norm_id",
        "norm_specification_sha256",
        "comparison_unit",
        "comparison_comparator",
        "comparison_tolerance",
        "static_separation_method",
        "static_separation_specification_sha256",
        "runtime_separation_method",
        "runtime_separation_specification_sha256",
        "separation_limitations",
    )
    required_fields = {
        *frozen_fields,
        "observed_route_ids",
        "observed_implementation_bundle_contract_ids",
        "observed_shared_input_object_ids",
        "observed_static_shared_member_locators",
        "observed_runtime_shared_member_locators",
        "observed_static_dependency_edges",
        "observed_runtime_dependency_edges",
        "observed_static_receipt_complete",
        "observed_runtime_receipt_complete",
        "static_separation_satisfied",
        "runtime_separation_satisfied",
        "observed_comparison_value",
        "comparison_satisfied",
        "assessment_status",
        "observed_witness",
        "interpretation",
        "evidence_sha256",
        "evidence_location",
    }
    derived_fields = {"selected_value_sha256"}
    control_results = gate.details.get("control_results")
    for contract in contracts:
        result = results[contract.contract_id]
        prefix = (
            f"{label}gate {gate.gate_id} computation_route_separation_results "
            f"{contract.contract_id}"
        )
        if (
            not isinstance(result, dict)
            or not required_fields <= set(result)
            or set(result) - required_fields - derived_fields
        ):
            raise ValidationError(
                f"{label}computation route separation result for "
                f"{contract.contract_id} must contain exactly the documented fields"
            )
        frozen_expected = contract.to_dict()
        for field_name in (
            "contract_id",
            "adverse_shared_helper_control_id",
            "evaluation_gate_id",
        ):
            frozen_expected.pop(field_name)
        for field_name in frozen_fields:
            if result[field_name] != frozen_expected[field_name]:
                raise ValidationError(
                    f"{label}computation route separation {field_name} does not "
                    "match the frozen contract"
                )
        if result["observed_route_ids"] != contract.route_ids:
            raise ValidationError(
                f"{label}observed route IDs do not match the frozen contract"
            )
        if (
            result["observed_implementation_bundle_contract_ids"]
            != contract.implementation_bundle_contract_ids
        ):
            raise ValidationError(
                f"{label}observed implementation bundle IDs do not match the "
                "frozen contract"
            )
        observed_inputs = require_unique_canonical_text_list(
            result["observed_shared_input_object_ids"],
            f"{prefix}.observed_shared_input_object_ids",
        )
        if observed_inputs != contract.approved_shared_input_object_ids:
            raise ValidationError(
                f"{label}observed shared input objects do not match the frozen "
                "approved inputs"
            )
        observed_shared: dict[str, list[str]] = {}
        for route_kind in ("static", "runtime"):
            field_name = f"observed_{route_kind}_shared_member_locators"
            locators = require_unique_canonical_text_list(
                result[field_name], f"{prefix}.{field_name}"
            )
            if locators != sorted(locators):
                raise ValidationError(f"{prefix}.{field_name} must be sorted")
            for locator_index, locator in enumerate(locators):
                path = Path(locator)
                if path.is_absolute() or ".." in path.parts:
                    raise ValidationError(
                        f"{prefix}.{field_name}[{locator_index}] must be a safe "
                        "relative code locator"
                    )
            observed_shared[route_kind] = locators
        observed_edges = {
            route_kind: _parse_observed_route_edges(
                result[f"observed_{route_kind}_dependency_edges"],
                route_ids=contract.route_ids,
                label=f"{prefix}.observed_{route_kind}_dependency_edges",
            )
            for route_kind in ("static", "runtime")
        }
        separation_satisfied: dict[str, bool] = {}
        for route_kind in ("static", "runtime"):
            complete_field = f"observed_{route_kind}_receipt_complete"
            if type(result[complete_field]) is not bool:
                raise ValidationError(f"{prefix}.{complete_field} must be boolean")
            # Every reported edge connects the two frozen routes. The frozen
            # edge inventory proves that the prospective boundary covered all
            # route-exclusive target members; an unanticipated edge is a
            # separation failure too, not a loophole.
            violation_found = bool(observed_edges[route_kind])
            computed = (
                result[complete_field]
                and observed_shared[route_kind]
                == contract.approved_shared_member_locators
                and not violation_found
            )
            declared_field = f"{route_kind}_separation_satisfied"
            if type(result[declared_field]) is not bool:
                raise ValidationError(f"{prefix}.{declared_field} must be boolean")
            if result[declared_field] is not computed:
                raise ValidationError(
                    f"{label}{declared_field} does not match the observed receipt"
                )
            separation_satisfied[route_kind] = computed
        comparison_value = result["observed_comparison_value"]
        if type(comparison_value) is bool or not isinstance(
            comparison_value, (int, float)
        ):
            raise ValidationError(
                f"{prefix}.observed_comparison_value must be numeric"
            )
        comparison_value = float(comparison_value)
        if not math.isfinite(comparison_value) or comparison_value < 0:
            raise ValidationError(
                f"{prefix}.observed_comparison_value must be finite and nonnegative"
            )
        if type(result["comparison_satisfied"]) is not bool:
            raise ValidationError(f"{prefix}.comparison_satisfied must be boolean")
        computed_comparison = _route_comparison_satisfied(
            comparison_value,
            contract.comparison_comparator,
            float(contract.comparison_tolerance),
        )
        if result["comparison_satisfied"] is not computed_comparison:
            raise ValidationError(
                f"{label}comparison_satisfied does not match the frozen comparator "
                "and tolerance"
            )
        for field_name in (
            "assessment_status",
            "observed_witness",
            "interpretation",
            "evidence_location",
        ):
            require_canonical_text(result[field_name], f"{prefix}.{field_name}")
        if result["assessment_status"] != expected_status:
            raise ValidationError(
                f"{label}{gate.status.value} computation route separation gate "
                f"requires {expected_status}"
            )
        if gate.status is QualityGateStatus.PASSED and not all(
            separation_satisfied.values()
        ):
            raise ValidationError(
                f"{label}passed computation route separation gate requires both "
                "static and runtime separation receipts to satisfy the contract"
            )
        if gate.status is QualityGateStatus.FAILED and all(
            separation_satisfied.values()
        ):
            raise ValidationError(
                f"{label}failed computation route separation gate requires an "
                "observed code-separation contradiction"
            )
        digest = require_sha256(
            result["evidence_sha256"], f"{prefix}.evidence_sha256"
        )
        if digest not in output_hashes:
            raise ValidationError(
                f"{label}computation route separation evidence must reference a "
                "run output artifact"
            )
        linked_control = (
            control_results.get(contract.adverse_shared_helper_control_id)
            if isinstance(control_results, dict)
            else None
        )
        control_fields = {
            "observed_behavior",
            "interpretation",
            "matches_expected",
            "evidence_sha256",
            "evidence_location",
        }
        control_derived_fields = {"selected_value_sha256"}
        if (
            not isinstance(linked_control, dict)
            or not control_fields <= set(linked_control)
            or set(linked_control) - control_fields - control_derived_fields
        ):
            raise ValidationError(
                f"{label}computation route separation result requires its exact "
                "linked adverse shared-helper control evaluation"
            )
        if type(linked_control["matches_expected"]) is not bool:
            raise ValidationError(
                f"{label}computation route separation linked control "
                "matches_expected must be a boolean"
            )
        control_digest = require_sha256(
            linked_control["evidence_sha256"],
            f"{prefix}.linked_control.evidence_sha256",
        )
        if control_digest not in output_hashes:
            raise ValidationError(
                f"{label}computation route separation linked control evidence "
                "must reference a run output artifact"
            )
        if gate.status is QualityGateStatus.PASSED and not linked_control[
            "matches_expected"
        ]:
            raise ValidationError(
                f"{label}passed computation route separation gate requires its "
                "shared-helper adverse control to match expectation"
            )
        if result.get("selected_value_sha256") is not None:
            require_sha256(
                result["selected_value_sha256"],
                f"{prefix}.selected_value_sha256",
            )


_BOUNDED_SEARCH_SCREENING_DECISIONS = {
    "in_scope_target",
    "retained_context",
    "excluded",
}
_BOUNDED_SEARCH_CONCLUSION_CEILING = "bounded_retrieval_record_only"
_BOUNDED_SEARCH_REQUIRED_UNSUPPORTED = {
    "universal_absence",
    "mathematical_impossibility",
    "theorem_or_proof",
    "absence_outside_frozen_interfaces_queries_date_and_stop_rule",
}


def validate_bounded_negative_search_contracts(
    protocol: ExperimentProtocol,
) -> None:
    """Validate an exact search record without promoting absence to proof."""

    contracts = protocol.bounded_negative_search_contracts
    if any(not isinstance(item, BoundedNegativeSearchContract) for item in contracts):
        raise ValidationError(
            "bounded_negative_search_contracts must contain "
            "BoundedNegativeSearchContract values"
        )
    controls = {item.control_id: item for item in protocol.control_definitions}
    contract_ids: set[str] = set()
    for index, contract in enumerate(contracts):
        prefix = f"bounded_negative_search_contracts[{index}]"
        for field_name in (
            "contract_id",
            "search_question",
            "stop_rule",
            "conclusion_ceiling",
            "adverse_omission_control_id",
            "evaluation_gate_id",
        ):
            require_canonical_text(
                getattr(contract, field_name), f"{prefix}.{field_name}"
            )
        if contract.contract_id in contract_ids:
            raise ValidationError("bounded negative search contract IDs must be unique")
        contract_ids.add(contract.contract_id)
        inclusions = require_unique_canonical_text_list(
            contract.scope_inclusions, f"{prefix}.scope_inclusions"
        )
        if not inclusions:
            raise ValidationError(
                "bounded negative search requires at least one scope inclusion"
            )
        require_unique_canonical_text_list(
            contract.scope_exclusions, f"{prefix}.scope_exclusions"
        )
        try:
            parsed_date = datetime.strptime(contract.search_date, "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"{prefix}.search_date must be an exact YYYY-MM-DD date"
            ) from exc
        if parsed_date.isoformat() != contract.search_date:
            raise ValidationError(
                f"{prefix}.search_date must be an exact YYYY-MM-DD date"
            )
        if not contract.interfaces or any(
            not isinstance(item, BoundedSearchInterface)
            for item in contract.interfaces
        ):
            raise ValidationError(
                "bounded negative search requires typed database/interface records"
            )
        interface_ids: set[str] = set()
        for interface_index, interface in enumerate(contract.interfaces):
            interface_prefix = f"{prefix}.interfaces[{interface_index}]"
            for field_name in (
                "interface_id", "database_name", "interface_name", "interface_version"
            ):
                require_canonical_text(
                    getattr(interface, field_name), f"{interface_prefix}.{field_name}"
                )
            if interface.interface_id in interface_ids:
                raise ValidationError(
                    "bounded negative search interface IDs must be unique"
                )
            interface_ids.add(interface.interface_id)
        if not contract.queries or any(
            not isinstance(item, BoundedSearchQuery) for item in contract.queries
        ):
            raise ValidationError("bounded negative search requires exact query records")
        query_ids: set[str] = set()
        queried_interfaces: set[str] = set()
        for query_index, query in enumerate(contract.queries):
            query_prefix = f"{prefix}.queries[{query_index}]"
            for field_name in ("query_id", "interface_id", "exact_query"):
                require_canonical_text(
                    getattr(query, field_name), f"{query_prefix}.{field_name}"
                )
            if query.query_id in query_ids:
                raise ValidationError("bounded negative search query IDs must be unique")
            if query.interface_id not in interface_ids:
                raise ValidationError(
                    "bounded negative search query references an unknown interface"
                )
            query_ids.add(query.query_id)
            queried_interfaces.add(query.interface_id)
        if queried_interfaces != interface_ids:
            raise ValidationError(
                "bounded negative search must execute at least one exact query "
                "against every declared interface"
            )
        for field_name, value in (
            ("maximum_queries_to_execute", contract.maximum_queries_to_execute),
            ("maximum_candidates_to_screen", contract.maximum_candidates_to_screen),
        ):
            if type(value) is bool or not isinstance(value, int) or value < 1:
                raise ValidationError(f"{prefix}.{field_name} must be a positive integer")
        if len(contract.queries) > contract.maximum_queries_to_execute:
            raise ValidationError(
                "bounded negative search exact queries exceed the frozen stop bound"
            )
        if len(contract.screened_candidates) > contract.maximum_candidates_to_screen:
            raise ValidationError(
                "bounded negative search candidate records exceed the frozen stop bound"
            )
        if any(
            not isinstance(item, ScreenedSearchCandidate)
            for item in contract.screened_candidates
        ):
            raise ValidationError(
                "bounded negative search candidates must be ScreenedSearchCandidate values"
            )
        candidate_ids: set[str] = set()
        source_ids: set[str] = set()
        for candidate_index, candidate in enumerate(contract.screened_candidates):
            candidate_prefix = f"{prefix}.screened_candidates[{candidate_index}]"
            for field_name in ("candidate_id", "source_id", "screening_decision"):
                require_canonical_text(
                    getattr(candidate, field_name), f"{candidate_prefix}.{field_name}"
                )
            if candidate.candidate_id in candidate_ids:
                raise ValidationError(
                    "bounded negative search candidate IDs must be unique"
                )
            if candidate.source_id in source_ids:
                raise ValidationError(
                    "bounded negative search source IDs must be unique; combine query lineage"
                )
            candidate_ids.add(candidate.candidate_id)
            source_ids.add(candidate.source_id)
            candidate_query_ids = require_unique_canonical_text_list(
                candidate.query_ids, f"{candidate_prefix}.query_ids"
            )
            if not candidate_query_ids or not set(candidate_query_ids) <= query_ids:
                raise ValidationError(
                    "bounded negative search candidate query_ids must be nonempty "
                    "and reference frozen queries"
                )
            if candidate.screening_decision not in _BOUNDED_SEARCH_SCREENING_DECISIONS:
                raise ValidationError(
                    f"{candidate_prefix}.screening_decision is unsupported"
                )
            if candidate.screening_decision == "excluded":
                require_canonical_text(
                    candidate.exclusion_reason, f"{candidate_prefix}.exclusion_reason"
                )
                if candidate.retained_source_sha256:
                    raise ValidationError(
                        "excluded bounded-search candidates cannot declare a retained-source hash"
                    )
            else:
                require_sha256(
                    candidate.retained_source_sha256,
                    f"{candidate_prefix}.retained_source_sha256",
                )
                if candidate.exclusion_reason:
                    raise ValidationError(
                        "retained bounded-search candidates cannot declare an exclusion reason"
                    )
        if contract.conclusion_ceiling != _BOUNDED_SEARCH_CONCLUSION_CEILING:
            raise ValidationError(
                "bounded negative search conclusion_ceiling must remain "
                "bounded_retrieval_record_only"
            )
        unsupported = require_unique_canonical_text_list(
            contract.higher_level_conclusions_unsupported,
            f"{prefix}.higher_level_conclusions_unsupported",
        )
        missing_ceilings = sorted(
            _BOUNDED_SEARCH_REQUIRED_UNSUPPORTED - set(unsupported)
        )
        if missing_ceilings:
            raise ValidationError(
                "bounded negative search must explicitly reject higher conclusions: "
                + ", ".join(missing_ceilings)
            )
        control = controls.get(contract.adverse_omission_control_id)
        if control is None:
            raise ValidationError(
                "bounded negative search must bind an exact adverse omission control_id"
            )
        if control.family != "adversarial":
            raise ValidationError(
                "bounded negative search omission control must be adversarial"
            )
        if control.evaluation_gate_id != contract.evaluation_gate_id:
            raise ValidationError(
                "bounded negative search and omission control must share an evaluation gate"
            )
        if contract.evaluation_gate_id not in set(protocol.quality_requirements):
            raise ValidationError(
                "bounded negative search evaluation gate must be a required protocol quality gate"
            )


def validate_bounded_negative_search_gate_metadata(
    *,
    protocol: ExperimentProtocol,
    gate: QualityGateResult,
    output_hashes: set[str],
    context: str = "",
) -> None:
    """Replay a bounded search record and its omission/truncation control."""

    contracts = [
        item
        for item in protocol.bounded_negative_search_contracts
        if item.evaluation_gate_id == gate.gate_id
    ]
    if not contracts or gate.status is QualityGateStatus.SKIPPED:
        return
    label = f"{context} " if context else ""
    results = gate.details.get("bounded_negative_search_results")
    expected_ids = {item.contract_id for item in contracts}
    if not isinstance(results, dict) or set(results) != expected_ids:
        raise ValidationError(
            f"{label}performed bounded negative search gate {gate.gate_id} "
            "requires exact results for: " + ", ".join(sorted(expected_ids))
        )
    expected_status = {
        QualityGateStatus.PASSED: "consistent_with_bounded_search_contract",
        QualityGateStatus.WARNING: "inconclusive",
        QualityGateStatus.FAILED: "contradicted_bounded_search_contract",
    }.get(gate.status)
    if expected_status is None:
        raise ValidationError(
            f"{label}bounded negative search gate {gate.gate_id} has an unsupported status"
        )
    frozen_fields = (
        "search_question",
        "scope_inclusions",
        "scope_exclusions",
        "search_date",
        "interfaces",
        "queries",
        "stop_rule",
        "maximum_queries_to_execute",
        "maximum_candidates_to_screen",
        "screened_candidates",
        "conclusion_ceiling",
        "higher_level_conclusions_unsupported",
    )
    required_fields = {
        *frozen_fields,
        "observed_query_ids",
        "observed_interface_ids",
        "observed_screened_candidate_ids",
        "observed_retained_source_sha256s",
        "observed_exclusion_reasons",
        "observed_stop_rule_satisfied",
        "observed_search_record_complete",
        "assessment_status",
        "observed_witness",
        "interpretation",
        "evidence_sha256",
        "evidence_location",
    }
    derived_fields = {"selected_value_sha256"}
    control_results = gate.details.get("control_results")
    for contract in contracts:
        result = results[contract.contract_id]
        prefix = (
            f"{label}gate {gate.gate_id} bounded_negative_search_results "
            f"{contract.contract_id}"
        )
        if (
            not isinstance(result, dict)
            or not required_fields <= set(result)
            or set(result) - required_fields - derived_fields
        ):
            raise ValidationError(
                f"{label}bounded negative search result for {contract.contract_id} "
                "must contain exactly the documented fields"
            )
        frozen_expected = contract.to_dict()
        for omitted in (
            "contract_id", "adverse_omission_control_id", "evaluation_gate_id"
        ):
            frozen_expected.pop(omitted)
        for field_name in frozen_fields:
            if result[field_name] != frozen_expected[field_name]:
                raise ValidationError(
                    f"{label}bounded negative search {field_name} does not match "
                    "the frozen contract"
                )
        expected_query_ids = [item.query_id for item in contract.queries]
        expected_interface_ids = [item.interface_id for item in contract.interfaces]
        expected_candidate_ids = [
            item.candidate_id for item in contract.screened_candidates
        ]
        if require_unique_canonical_text_list(
            result["observed_query_ids"], f"{prefix}.observed_query_ids"
        ) != expected_query_ids:
            raise ValidationError(
                f"{label}bounded negative search observed queries do not match the frozen record"
            )
        if require_unique_canonical_text_list(
            result["observed_interface_ids"], f"{prefix}.observed_interface_ids"
        ) != expected_interface_ids:
            raise ValidationError(
                f"{label}bounded negative search observed interfaces do not match the frozen record"
            )
        if require_unique_canonical_text_list(
            result["observed_screened_candidate_ids"],
            f"{prefix}.observed_screened_candidate_ids",
        ) != expected_candidate_ids:
            raise ValidationError(
                f"{label}bounded negative search observed candidate set does not match the frozen record"
            )
        expected_hashes = {
            item.candidate_id: item.retained_source_sha256
            for item in contract.screened_candidates
            if item.screening_decision != "excluded"
        }
        if result["observed_retained_source_sha256s"] != expected_hashes:
            raise ValidationError(
                f"{label}bounded negative search retained-source hashes do not match the frozen record"
            )
        expected_reasons = {
            item.candidate_id: item.exclusion_reason
            for item in contract.screened_candidates
            if item.screening_decision == "excluded"
        }
        if result["observed_exclusion_reasons"] != expected_reasons:
            raise ValidationError(
                f"{label}bounded negative search exclusion reasons do not match the frozen record"
            )
        for field_name in (
            "observed_stop_rule_satisfied", "observed_search_record_complete"
        ):
            if type(result[field_name]) is not bool:
                raise ValidationError(f"{prefix}.{field_name} must be a boolean")
            if gate.status is QualityGateStatus.PASSED and not result[field_name]:
                raise ValidationError(
                    f"{label}passed bounded negative search gate requires {field_name}"
                )
        for field_name in (
            "assessment_status", "observed_witness", "interpretation", "evidence_location"
        ):
            require_canonical_text(result[field_name], f"{prefix}.{field_name}")
        if result["assessment_status"] != expected_status:
            raise ValidationError(
                f"{label}{gate.status.value} bounded negative search gate "
                f"requires {expected_status}"
            )
        digest = require_sha256(result["evidence_sha256"], f"{prefix}.evidence_sha256")
        if digest not in output_hashes:
            raise ValidationError(
                f"{label}bounded negative search evidence must reference a run output artifact"
            )
        linked_control = (
            control_results.get(contract.adverse_omission_control_id)
            if isinstance(control_results, dict)
            else None
        )
        control_fields = {
            "observed_behavior", "interpretation", "matches_expected",
            "evidence_sha256", "evidence_location",
        }
        if (
            not isinstance(linked_control, dict)
            or not control_fields <= set(linked_control)
            or set(linked_control) - control_fields - {"selected_value_sha256"}
        ):
            raise ValidationError(
                f"{label}bounded negative search result requires its exact linked "
                "adverse omission/truncation control evaluation"
            )
        if type(linked_control["matches_expected"]) is not bool:
            raise ValidationError(
                f"{label}bounded negative search linked control matches_expected "
                "must be a boolean"
            )
        control_digest = require_sha256(
            linked_control["evidence_sha256"],
            f"{prefix}.linked_control.evidence_sha256",
        )
        if control_digest not in output_hashes:
            raise ValidationError(
                f"{label}bounded negative search linked control evidence must "
                "reference a run output artifact"
            )
        if gate.status is QualityGateStatus.PASSED and not linked_control[
            "matches_expected"
        ]:
            raise ValidationError(
                f"{label}passed bounded negative search gate requires its adverse "
                "omission/truncation control to match expectation"
            )
        if result.get("selected_value_sha256") is not None:
            require_sha256(
                result["selected_value_sha256"], f"{prefix}.selected_value_sha256"
            )


def validate_measurement_contract(protocol: ExperimentProtocol) -> None:
    definitions = protocol.measurement_definitions
    if any(not isinstance(item, MeasurementDefinition) for item in definitions):
        raise ValidationError(
            "measurement_definitions must contain MeasurementDefinition values"
        )
    identifiers: set[str] = set()
    data_columns: dict[str, str] = {}
    observed_targets: list[tuple[MeasurementRole, str]] = []
    alias_proxy_commitment_keys: set[tuple[str, str]] = set()
    for index, definition in enumerate(definitions):
        prefix = f"measurement_definitions[{index}]"
        measurement_id = require_canonical_text(
            definition.measurement_id, f"{prefix}.measurement_id"
        )
        if measurement_id in identifiers:
            raise ValidationError(f"duplicate measurement_id: {measurement_id}")
        identifiers.add(measurement_id)
        if not isinstance(definition.role, MeasurementRole):
            raise ValidationError(f"{prefix}.role must be a MeasurementRole")
        target = require_canonical_text(
            definition.registered_target, f"{prefix}.registered_target"
        )
        for field_name in (
            "observable",
            "input_condition",
            "evaluation_point",
            "convention",
            "aggregation",
            "tolerance",
            "expected_behavior",
        ):
            require_canonical_text(
                getattr(definition, field_name), f"{prefix}.{field_name}"
            )
        if (
            not isinstance(definition.parameter_values, dict)
            or not definition.parameter_values
        ):
            raise ValidationError(
                f"{prefix}.parameter_values must be a non-empty object"
            )
        for name, value in definition.parameter_values.items():
            require_canonical_text(name, f"{prefix}.parameter_values key")
            require_canonical_text(value, f"{prefix}.parameter_values[{name!r}]")
        _validate_alias_proxy_commitment(definition=definition, prefix=prefix)
        if definition.alias_proxy_commitment is not None:
            commitment_key = (
                measurement_id,
                definition.alias_proxy_commitment.commitment_id,
            )
            if commitment_key in alias_proxy_commitment_keys:
                raise ValidationError(
                    "alias_proxy_commitment commitment_id must be unique per measurement"
                )
            alias_proxy_commitment_keys.add(commitment_key)
        if (
            definition.temporal_role
            and definition.temporal_role not in MEASUREMENT_TEMPORAL_ROLES
        ):
            raise ValidationError(
                f"{prefix}.temporal_role must be a supported temporal role"
            )
        if definition.data_column:
            data_column = require_text(definition.data_column, f"{prefix}.data_column")
            if data_column != definition.data_column:
                raise ValidationError(
                    f"{prefix}.data_column must be canonical without surrounding whitespace"
                )
            normalized_column = data_column.casefold()
            if normalized_column in data_columns:
                raise ValidationError(
                    "measurement_definitions data_column values must be case-insensitively unique"
                )
            data_columns[normalized_column] = data_column
            if definition.scale_type not in {
                "binary", "nominal", "ordinal", "interval", "ratio", "count",
                "time_to_event",
            }:
                raise ValidationError(
                    f"{prefix}.scale_type must classify every executable data column"
                )
            require_canonical_text(definition.unit, f"{prefix}.unit")
            normalized_domains: dict[str, list[str]] = {}
            for field_name in ("admissible_values", "missing_value_codes"):
                values = getattr(definition, field_name)
                if not isinstance(values, list):
                    raise ValidationError(f"{prefix}.{field_name} must be a list")
                normalized = [
                    require_canonical_text(item, f"{prefix}.{field_name} item")
                    for item in values
                ]
                if len(set(normalized)) != len(normalized):
                    raise ValidationError(f"{prefix}.{field_name} must contain unique values")
                normalized_domains[field_name] = normalized
            if (
                set(normalized_domains["admissible_values"])
                & set(normalized_domains["missing_value_codes"])
            ):
                raise ValidationError(
                    f"{prefix} missing-value codes cannot also be admissible observations"
                )
            bounds = (definition.valid_min, definition.valid_max)
            for field_name, bound in zip(("valid_min", "valid_max"), bounds):
                if bound is not None and (
                    isinstance(bound, bool)
                    or not isinstance(bound, (int, float))
                    or not math.isfinite(float(bound))
                ):
                    raise ValidationError(f"{prefix}.{field_name} must be finite or null")
            if (
                all(bound is not None for bound in bounds)
                and definition.valid_min >= definition.valid_max
            ):
                raise ValidationError(
                    f"{prefix}.valid_min must be strictly below valid_max"
                )
            categorical = definition.scale_type in {"binary", "nominal", "ordinal"}
            if categorical:
                if not definition.admissible_values:
                    raise ValidationError(
                        f"{prefix}.admissible_values must enumerate the registered categorical domain"
                    )
                if definition.scale_type == "binary" and len(definition.admissible_values) != 2:
                    raise ValidationError(
                        f"{prefix}.binary measurements require exactly two admissible_values"
                    )
                if any(bound is not None for bound in bounds):
                    raise ValidationError(
                        f"{prefix} categorical measurements cannot use numeric validity bounds"
                    )
            elif definition.admissible_values:
                raise ValidationError(
                    f"{prefix} numeric measurements must use validity bounds, not categorical admissible_values"
                )
            if definition.scale_type in {"ratio", "count", "time_to_event"}:
                if definition.valid_min is not None and definition.valid_min < 0:
                    raise ValidationError(
                        f"{prefix}.{definition.scale_type} valid_min cannot be negative"
                    )
            if definition.scale_type == "count":
                for bound in bounds:
                    if bound is not None and not float(bound).is_integer():
                        raise ValidationError(f"{prefix}.count validity bounds must be integers")
        observed_targets.append((definition.role, target))

    reserved_columns = {"observation_id", "unit_id", "condition", "captured_at"}
    if protocol.unit_id_column:
        reserved_columns.add(require_text(protocol.unit_id_column, "unit_id_column").casefold())
    if protocol.analysis_contract is not None and protocol.analysis_contract.group_column:
        reserved_columns.add(
            require_text(
                protocol.analysis_contract.group_column,
                "analysis_contract.group_column",
            ).casefold()
        )
    reserved_collisions = sorted(
        definition.data_column
        for definition in definitions
        if definition.data_column
        and definition.role is not MeasurementRole.EXPOSURE
        and definition.data_column.casefold() in reserved_columns
    )
    if reserved_collisions:
        raise ValidationError(
            "measurement_definitions data_column values must be distinct from "
            "identity, assignment, and capture-time columns: "
            + ", ".join(reserved_collisions)
        )

    expected_targets = (
        [(MeasurementRole.PRIMARY, protocol.primary_outcome)]
        + [(MeasurementRole.SECONDARY, item) for item in protocol.secondary_outcomes]
        + [(MeasurementRole.CONTROL, item) for item in protocol.controls]
    )
    if protocol.causal_claim and protocol.analysis_contract is not None:
        causal_audit = protocol.causal_identification_audit
        expected_targets += [
            (MeasurementRole.EXPOSURE, causal_audit["exposure"]),
            *[
                (MeasurementRole.COVARIATE, item)
                for item in causal_audit["proposed_adjustment_set"]
            ],
        ]
    if sorted((role.value, target) for role, target in observed_targets) != sorted(
        (role.value, target) for role, target in expected_targets
    ):
        raise ValidationError(
            "measurement_definitions must define exactly one measurement for the "
            "primary outcome, every secondary outcome, every registered control, "
            "and every required causal exposure and adjustment covariate"
        )
    if protocol.analysis_contract is not None:
        matches = [
            item for item in definitions
            if item.measurement_id == protocol.analysis_contract.primary_measurement_id
        ]
        if len(matches) != 1:
            raise ValidationError("analysis_contract.primary_measurement_id must name exactly one measurement definition")
        primary = matches[0]
        if primary.role is not MeasurementRole.PRIMARY or primary.registered_target != protocol.primary_outcome:
            raise ValidationError("analysis contract must select the registered primary-outcome measurement")
        if require_text(primary.data_column, "primary measurement data_column") != protocol.analysis_contract.outcome_column:
            raise ValidationError("primary measurement data_column does not match analysis_contract.outcome_column")
        numeric_outcome_scales = {"binary", "interval", "ratio", "count"}
        if protocol.analysis_contract.method in {
            "independent_mean_difference_ci", "paired_mean_difference_ci",
            "adjusted_linear_effect",
        } and primary.scale_type not in numeric_outcome_scales:
            raise ValidationError(
                "registered mean or linear-effect analysis requires a binary, interval, ratio, or count primary measurement scale"
            )
        if protocol.causal_claim:
            exposure = [
                item for item in definitions if item.role is MeasurementRole.EXPOSURE
            ]
            covariates = [
                item for item in definitions if item.role is MeasurementRole.COVARIATE
            ]
            if require_text(
                exposure[0].data_column, "exposure measurement data_column"
            ) != protocol.analysis_contract.group_column:
                raise ValidationError(
                    "exposure measurement data_column does not match analysis_contract.group_column"
                )
            if exposure[0].scale_type not in {"binary", "nominal"}:
                raise ValidationError(
                    "grouped causal analysis requires a binary or nominal exposure scale"
                )
            if exposure[0].admissible_values != protocol.analysis_contract.groups:
                raise ValidationError(
                    "exposure admissible_values must exactly match analysis_contract.groups in contrast order"
                )
            if primary.temporal_role != "post_exposure":
                raise ValidationError(
                    "causal primary-outcome measurement temporal_role must be post_exposure"
                )
            if exposure[0].temporal_role != "at_exposure":
                raise ValidationError(
                    "causal exposure measurement temporal_role must be at_exposure"
                )
            invalid_covariate_timing = [
                item.registered_target for item in covariates
                if item.temporal_role != "pre_exposure"
            ]
            if invalid_covariate_timing:
                raise ValidationError(
                    "causal adjustment covariate measurements must have temporal_role "
                    "pre_exposure: " + ", ".join(invalid_covariate_timing)
                )
            invalid_covariate_scales = [
                item.registered_target for item in covariates
                if item.scale_type not in numeric_outcome_scales
            ]
            if invalid_covariate_scales:
                raise ValidationError(
                    "adjusted linear covariates require binary, interval, ratio, or count scales: "
                    + ", ".join(invalid_covariate_scales)
                )
            covariate_columns = {
                item.registered_target: require_text(
                    item.data_column,
                    f"covariate measurement {item.measurement_id} data_column",
                )
                for item in covariates
            }
            expected_columns = {
                item: item for item in protocol.analysis_contract.adjustment_columns
            }
            if covariate_columns != expected_columns:
                raise ValidationError(
                    "causal covariate measurement data_columns must exactly map each "
                    "adjustment target to its frozen analysis column"
                )
            modeled_columns = [
                primary.data_column,
                exposure[0].data_column,
                *[item.data_column for item in covariates],
            ]
            if len(modeled_columns) != len(set(modeled_columns)):
                raise ValidationError(
                    "causal outcome, exposure, and covariate measurements must use distinct data columns"
                )


def validate_quality_gates(
    gates: Sequence[QualityGateResult],
) -> list[QualityGateResult]:
    if isinstance(gates, (str, bytes)) or not isinstance(gates, Sequence):
        raise ValidationError("quality_gates must be a list")
    normalized: list[QualityGateResult] = []
    seen: set[str] = set()
    for gate in gates:
        if not isinstance(gate, QualityGateResult):
            raise ValidationError("quality_gates must contain QualityGateResult values")
        gate_id = require_canonical_text(gate.gate_id, "quality gate id")
        if gate_id in seen:
            raise ValidationError(f"duplicate quality gate id: {gate_id}")
        if not isinstance(gate.status, QualityGateStatus):
            raise ValidationError("quality gate status must be a QualityGateStatus")
        if not isinstance(gate.required, bool):
            raise ValidationError("quality gate required must be true or false")
        if not isinstance(gate.details, dict):
            raise ValidationError("quality gate details must be an object")
        seen.add(gate_id)
        normalized.append(
            QualityGateResult(
                gate_id=gate_id,
                status=gate.status,
                summary=require_bounded_report_text(
                    gate.summary, "quality gate summary"
                ),
                required=gate.required,
                details=dict(gate.details),
            )
        )
    return normalized


def validate_action_candidates(
    candidates: Sequence[ActionCandidate],
    known_hypotheses: Mapping[str, str],
    hypothesis_alternatives: Mapping[str, Sequence[str]] | None = None,
) -> list[ActionCandidate]:
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise ValidationError("candidates must be a list")
    if not candidates:
        raise ValidationError("at least one action candidate is required")
    normalized: list[ActionCandidate] = []
    seen: set[str] = set()
    score_fields = (
        "expected_discrimination",
        "uncertainty_reduction",
        "cost",
        "duration",
        "burden",
        "safety_risk",
        "ambiguity_risk",
    )
    for candidate in candidates:
        if not isinstance(candidate, ActionCandidate):
            raise ValidationError("candidates must contain ActionCandidate values")
        action_id = require_canonical_text(candidate.action_id, "action_id")
        if action_id in seen:
            raise ValidationError(f"duplicate action_id: {action_id}")
        hypotheses = require_canonical_text_list(
            candidate.distinguishes_hypotheses, "distinguishes_hypotheses"
        )
        information_targets = require_unique_canonical_text_list(
            candidate.information_targets, "information_targets"
        )
        if not hypotheses and not information_targets:
            raise ValidationError(
                f"action {action_id} must distinguish at least one hypothesis or "
                "name at least one information target"
            )
        if len(set(hypotheses)) != len(hypotheses):
            raise ValidationError(
                f"action {action_id} repeats a hypothesis distinction"
            )
        unknown = sorted(set(hypotheses) - set(known_hypotheses))
        if unknown:
            raise ValidationError(
                f"action {action_id} references unknown hypotheses: "
                + ", ".join(unknown)
            )
        hypothesis_workflow_states = {
            hypothesis_id: known_hypotheses[hypothesis_id]
            for hypothesis_id in hypotheses
        }
        discrimination_targets = _validate_hypothesis_discrimination_targets(
            candidate.hypothesis_discrimination_targets,
            hypotheses,
            action_id,
            hypothesis_alternatives=hypothesis_alternatives,
        )
        for field_name in score_fields:
            value = getattr(candidate, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError(f"{field_name} must be a number from 0 to 1")
            if not 0 <= float(value) <= 1:
                raise ValidationError(f"{field_name} must be a number from 0 to 1")
        if not hypotheses and float(candidate.expected_discrimination) != 0.0:
            raise ValidationError(
                f"action {action_id} names no hypothesis distinction, so "
                "expected_discrimination must be 0; use uncertainty_reduction "
                "for infrastructure or information-gathering actions"
            )
        if not isinstance(candidate.prerequisites_met, bool):
            raise ValidationError("prerequisites_met must be true or false")
        if not isinstance(candidate.safety_approved, bool):
            raise ValidationError("safety_approved must be true or false")
        prerequisite_evidence_refs = require_unique_canonical_text_list(
            candidate.prerequisite_evidence_refs, "prerequisite_evidence_refs"
        )
        safety_review_refs = require_unique_canonical_text_list(
            candidate.safety_review_refs, "safety_review_refs"
        )
        if not prerequisite_evidence_refs:
            raise ValidationError(
                f"action {action_id} must retain prerequisite_evidence_refs "
                "for its prerequisite status"
            )
        if not safety_review_refs:
            raise ValidationError(
                f"action {action_id} must retain safety_review_refs for its "
                "safety approval status"
            )
        if not isinstance(candidate.factorial_or_crossover_design, bool):
            raise ValidationError(
                "factorial_or_crossover_design must be true or false"
            )
        metadata = validate_action_metadata(candidate.metadata)
        if candidate.audit_prerequisite_receipt:
            raise ValidationError(
                "audit_prerequisite_receipt is service-generated and must not be supplied"
            )
        audit_prerequisite_contract = (
            validate_audit_prerequisite_contract(
                candidate.audit_prerequisite_contract
            )
            if candidate.audit_prerequisite_contract is not None
            else None
        )
        depends_on = require_unique_canonical_text_list(
            candidate.depends_on, "depends_on"
        )
        manipulated_factors = require_unique_canonical_text_list(
            candidate.manipulated_factors, "manipulated_factors"
        )
        if not isinstance(candidate.factor_interpretability_plan, str):
            raise ValidationError("factor_interpretability_plan must be text")
        factor_interpretability_plan = ""
        if candidate.factor_interpretability_plan:
            factor_interpretability_plan = require_canonical_text(
                candidate.factor_interpretability_plan,
                "factor_interpretability_plan",
            )
        if candidate.factorial_or_crossover_design and not manipulated_factors:
            raise ValidationError(
                f"action {action_id} declares a factorial or crossover design "
                "without manipulated_factors"
            )
        if candidate.factorial_or_crossover_design and not factor_interpretability_plan:
            raise ValidationError(
                f"action {action_id} declares a factorial or crossover design "
                "without a factor_interpretability_plan"
            )
        if (
            len(manipulated_factors) > 1
            and (
                not candidate.factorial_or_crossover_design
                or not factor_interpretability_plan
            )
        ):
            raise ValidationError(
                f"action {action_id} changes multiple factors without a "
                "factorial or crossover interpretability design"
            )
        seen.add(action_id)
        normalized.append(
            ActionCandidate(
                action_id=action_id,
                title=require_text(candidate.title, "action title"),
                distinguishes_hypotheses=hypotheses,
                expected_discrimination=float(candidate.expected_discrimination),
                uncertainty_reduction=float(candidate.uncertainty_reduction),
                cost=float(candidate.cost),
                duration=float(candidate.duration),
                burden=float(candidate.burden),
                safety_risk=float(candidate.safety_risk),
                ambiguity_risk=float(candidate.ambiguity_risk),
                rationale=require_text(candidate.rationale, "action rationale"),
                hypothesis_discrimination_targets=discrimination_targets,
                hypothesis_workflow_states=hypothesis_workflow_states,
                prerequisites_met=candidate.prerequisites_met,
                safety_approved=candidate.safety_approved,
                prerequisite_evidence_refs=prerequisite_evidence_refs,
                safety_review_refs=safety_review_refs,
                lane_id=require_canonical_text(candidate.lane_id, "lane_id"),
                information_targets=information_targets,
                depends_on=depends_on,
                manipulated_factors=manipulated_factors,
                factorial_or_crossover_design=(
                    candidate.factorial_or_crossover_design
                ),
                factor_interpretability_plan=factor_interpretability_plan,
                metadata=metadata,
                audit_prerequisite_contract=audit_prerequisite_contract,
            )
        )
    return normalized


def _validate_hypothesis_discrimination_targets(
    targets: Sequence[HypothesisDiscriminationTarget],
    hypotheses: list[str],
    action_id: str,
    *,
    hypothesis_alternatives: Mapping[str, Sequence[str]] | None = None,
) -> list[HypothesisDiscriminationTarget]:
    if isinstance(targets, (str, bytes)) or not isinstance(targets, Sequence):
        raise ValidationError("hypothesis_discrimination_targets must be a list")
    if not hypotheses:
        if targets:
            raise ValidationError(
                f"action {action_id} declares hypothesis_discrimination_targets "
                "without distinguishes_hypotheses"
            )
        return []
    if not targets:
        raise ValidationError(
            f"action {action_id} must explain how it distinguishes each named "
            "hypothesis"
        )
    normalized: list[HypothesisDiscriminationTarget] = []
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, HypothesisDiscriminationTarget):
            raise ValidationError(
                "hypothesis_discrimination_targets must contain "
                "HypothesisDiscriminationTarget values"
            )
        hypothesis_id = require_canonical_text(
            target.hypothesis_id, "hypothesis_discrimination_target hypothesis_id"
        )
        if hypothesis_id in seen:
            raise ValidationError(
                "hypothesis_discrimination_targets repeat a hypothesis_id"
            )
        seen.add(hypothesis_id)
        competing_model_ref = require_canonical_text(
            target.competing_model_ref,
            "hypothesis_discrimination_target competing_model_ref",
        )
        if hypothesis_alternatives is not None:
            alternatives = {
                require_canonical_text(
                    alternative,
                    "hypothesis registered alternative",
                )
                for alternative in hypothesis_alternatives.get(hypothesis_id, [])
            }
            if competing_model_ref not in alternatives:
                raise ValidationError(
                    f"action {action_id} discrimination target {hypothesis_id} "
                    "competing_model_ref must match the hypothesis null_model or "
                    "one registered competing_model"
                )
        normalized.append(
            HypothesisDiscriminationTarget(
                hypothesis_id=hypothesis_id,
                discriminating_observation=require_canonical_text(
                    target.discriminating_observation,
                    "hypothesis_discrimination_target discriminating_observation",
                ),
                expected_if_hypothesis=require_canonical_text(
                    target.expected_if_hypothesis,
                    "hypothesis_discrimination_target expected_if_hypothesis",
                ),
                expected_if_alternative=require_canonical_text(
                    target.expected_if_alternative,
                    "hypothesis_discrimination_target expected_if_alternative",
                ),
                would_weaken_if=require_canonical_text(
                    target.would_weaken_if,
                    "hypothesis_discrimination_target would_weaken_if",
                ),
                competing_model_ref=competing_model_ref,
            )
        )
        _validate_discriminating_observation_shape(normalized[-1], action_id)
    if set(hypotheses) != seen:
        missing = sorted(set(hypotheses) - seen)
        extra = sorted(seen - set(hypotheses))
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("extra " + ", ".join(extra))
        raise ValidationError(
            f"action {action_id} hypothesis_discrimination_targets must exactly "
            "cover distinguishes_hypotheses: " + "; ".join(details)
        )
    return sorted(normalized, key=lambda target: target.hypothesis_id)


def _validate_discriminating_observation_shape(
    target: HypothesisDiscriminationTarget,
    action_id: str,
) -> None:
    expected = target.expected_if_hypothesis.casefold()
    alternative = target.expected_if_alternative.casefold()
    weakening = target.would_weaken_if.casefold()
    if expected == alternative:
        raise ValidationError(
            f"action {action_id} discrimination target {target.hypothesis_id} "
            "must state different expected observations for the hypothesis and alternative"
        )
    if expected == weakening:
        raise ValidationError(
            f"action {action_id} discrimination target {target.hypothesis_id} "
            "cannot use the hypothesis-favorable expectation as its weakening condition"
        )


def validate_action_lanes(lanes: Sequence[ActionLane]) -> list[ActionLane]:
    if isinstance(lanes, (str, bytes)) or not isinstance(lanes, Sequence):
        raise ValidationError("lanes must be a list")
    if not lanes:
        raise ValidationError("at least one action lane is required")
    normalized: list[ActionLane] = []
    seen: set[str] = set()
    for lane in lanes:
        if not isinstance(lane, ActionLane):
            raise ValidationError("lanes must contain ActionLane values")
        lane_id = require_canonical_text(lane.lane_id, "lane_id")
        if lane_id in seen:
            raise ValidationError(f"duplicate lane_id: {lane_id}")
        status = require_canonical_text(lane.status, "lane status")
        if status not in {"active", "blocked"}:
            raise ValidationError("lane status must be active or blocked")
        blocked_on = require_unique_canonical_text_list(
            lane.blocked_on, "blocked_on"
        )
        if status == "active" and blocked_on:
            raise ValidationError(f"active lane {lane_id} cannot declare blocked_on")
        if status == "blocked" and not blocked_on:
            raise ValidationError(f"blocked lane {lane_id} must declare blocked_on")
        seen.add(lane_id)
        normalized.append(
            ActionLane(
                lane_id=lane_id,
                title=require_text(lane.title, "lane title"),
                status=status,
                blocked_on=blocked_on,
            )
        )
    if not any(lane.status == "active" for lane in normalized):
        raise ValidationError("at least one action lane must be active")
    return normalized


def validate_portfolio_action_candidates(
    candidates: Sequence[ActionCandidate],
    known_hypotheses: Mapping[str, str],
    hypothesis_alternatives: Mapping[str, Sequence[str]] | None,
    lanes: Sequence[ActionLane],
    completed_action_ids: Sequence[str],
) -> tuple[list[ActionCandidate], list[str]]:
    normalized = validate_action_candidates(
        candidates,
        known_hypotheses,
        hypothesis_alternatives=hypothesis_alternatives,
    )
    lane_ids = {lane.lane_id for lane in lanes}
    for candidate in normalized:
        if candidate.lane_id not in lane_ids:
            raise ValidationError(
                f"action {candidate.action_id} references unknown lane: "
                f"{candidate.lane_id}"
            )

    action_ids = {candidate.action_id for candidate in normalized}
    completed = require_unique_canonical_text_list(
        completed_action_ids, "completed_action_ids"
    )
    unknown_completed = sorted(set(completed) - action_ids)
    if unknown_completed:
        raise ValidationError(
            "completed_action_ids reference unknown actions: "
            + ", ".join(unknown_completed)
        )
    for candidate in normalized:
        unknown_dependencies = sorted(set(candidate.depends_on) - action_ids)
        if unknown_dependencies:
            raise ValidationError(
                f"action {candidate.action_id} has unknown dependencies: "
                + ", ".join(unknown_dependencies)
            )
        if candidate.action_id in candidate.depends_on:
            raise ValidationError(
                f"action {candidate.action_id} cannot depend on itself"
            )

    dependencies = {
        candidate.action_id: set(candidate.depends_on) for candidate in normalized
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(action_id: str) -> None:
        if action_id in visiting:
            raise ValidationError("action dependency graph contains a cycle")
        if action_id in visited:
            return
        visiting.add(action_id)
        for dependency in dependencies[action_id]:
            visit(dependency)
        visiting.remove(action_id)
        visited.add(action_id)

    for action_id in sorted(dependencies):
        visit(action_id)
    return normalized, completed


def validate_selection_weights(weights: SelectionWeights) -> SelectionWeights:
    if not isinstance(weights, SelectionWeights):
        raise ValidationError("weights must be SelectionWeights")
    values: dict[str, float] = {}
    for field_name in (
        "expected_discrimination",
        "uncertainty_reduction",
        "cost",
        "duration",
        "burden",
        "safety_risk",
        "ambiguity_risk",
    ):
        value = getattr(weights, field_name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
        ):
            raise ValidationError(
                f"selection weight {field_name} must be a finite non-negative number"
            )
        values[field_name] = float(value)
    if not any(value > 0 for value in values.values()):
        raise ValidationError(
            "selection weights must include at least one positive utility term"
        )
    return SelectionWeights(**values)


def _normalize_cross_lane_lesson(
    *,
    origin_lane_id: str,
    target_lane_ids: Sequence[str],
    origin_artifact_locator: str,
    origin_artifact_sha256: str,
    origin_integrity_status: str,
    observation: str,
    failure_class: str,
    strongest_alternative_explanation: str,
    challenged_invariant: str,
    first_permitted_future_versions: Sequence[str],
    prohibited_retroactive_targets: Sequence[str],
    proposed_repair: str,
    repair_falsifier: str,
    conclusion_ceiling: str,
    enforce_report_prose: bool,
) -> dict[str, object]:
    report_text = (
        require_canonical_bounded_report_text
        if enforce_report_prose
        else require_canonical_text
    )
    origin_lane = require_canonical_text(origin_lane_id, "origin_lane_id")
    target_lanes = require_unique_canonical_text_list(
        target_lane_ids, "target_lane_ids"
    )
    if not target_lanes:
        raise ValidationError("target_lane_ids must name at least one target lane")
    if origin_lane in target_lanes:
        raise ValidationError("a cross-lane lesson must target a different lane")
    integrity_status = require_canonical_text(
        origin_integrity_status, "origin_integrity_status"
    )
    if integrity_status not in {"declared", "verified_elsewhere", "verified_local"}:
        raise ValidationError(
            "origin_integrity_status must be declared, verified_elsewhere, or verified_local"
        )
    failure = require_canonical_text(failure_class, "failure_class")
    if failure not in {
        "theory_failure",
        "machine_failure",
        "interface_ambiguity",
        "infrastructure_failure",
        "inconclusive",
    }:
        raise ValidationError("failure_class is not recognized")
    future_versions = require_unique_canonical_text_list(
        first_permitted_future_versions, "first_permitted_future_versions"
    )
    prohibited_targets = require_unique_canonical_text_list(
        prohibited_retroactive_targets, "prohibited_retroactive_targets"
    )
    if not future_versions:
        raise ValidationError(
            "first_permitted_future_versions must name at least one future version"
        )
    if not prohibited_targets:
        raise ValidationError(
            "prohibited_retroactive_targets must name at least one frozen or "
            "exposed target"
        )
    overlap = sorted(set(future_versions) & set(prohibited_targets))
    if overlap:
        raise ValidationError(
            "future versions cannot also be prohibited retroactive targets: "
            + ", ".join(overlap)
        )
    return {
        "origin_lane_id": origin_lane,
        "target_lane_ids": target_lanes,
        "origin_artifact_locator": require_canonical_text(
            origin_artifact_locator, "origin_artifact_locator"
        ),
        "origin_artifact_sha256": require_sha256(
            origin_artifact_sha256, "origin_artifact_sha256"
        ),
        "origin_integrity_status": integrity_status,
        "observation": report_text(observation, "observation"),
        "failure_class": failure,
        "strongest_alternative_explanation": report_text(
            strongest_alternative_explanation,
            "strongest_alternative_explanation",
        ),
        "challenged_invariant": report_text(
            challenged_invariant, "challenged_invariant"
        ),
        "first_permitted_future_versions": future_versions,
        "prohibited_retroactive_targets": prohibited_targets,
        "proposed_repair": report_text(proposed_repair, "proposed_repair"),
        "repair_falsifier": report_text(repair_falsifier, "repair_falsifier"),
        "conclusion_ceiling": report_text(conclusion_ceiling, "conclusion_ceiling"),
    }


def validate_cross_lane_lesson(
    *,
    origin_lane_id: str,
    target_lane_ids: Sequence[str],
    origin_artifact_locator: str,
    origin_artifact_sha256: str,
    origin_integrity_status: str,
    observation: str,
    failure_class: str,
    strongest_alternative_explanation: str,
    challenged_invariant: str,
    first_permitted_future_versions: Sequence[str],
    prohibited_retroactive_targets: Sequence[str],
    proposed_repair: str,
    repair_falsifier: str,
    conclusion_ceiling: str,
) -> dict[str, object]:
    """Validate current cross-lane lesson writes and authoritative reads."""

    return _normalize_cross_lane_lesson(
        origin_lane_id=origin_lane_id,
        target_lane_ids=target_lane_ids,
        origin_artifact_locator=origin_artifact_locator,
        origin_artifact_sha256=origin_artifact_sha256,
        origin_integrity_status=origin_integrity_status,
        observation=observation,
        failure_class=failure_class,
        strongest_alternative_explanation=strongest_alternative_explanation,
        challenged_invariant=challenged_invariant,
        first_permitted_future_versions=first_permitted_future_versions,
        prohibited_retroactive_targets=prohibited_retroactive_targets,
        proposed_repair=proposed_repair,
        repair_falsifier=repair_falsifier,
        conclusion_ceiling=conclusion_ceiling,
        enforce_report_prose=True,
    )


def validate_historical_cross_lane_lesson_structure(
    *,
    origin_lane_id: str,
    target_lane_ids: Sequence[str],
    origin_artifact_locator: str,
    origin_artifact_sha256: str,
    origin_integrity_status: str,
    observation: str,
    failure_class: str,
    strongest_alternative_explanation: str,
    challenged_invariant: str,
    first_permitted_future_versions: Sequence[str],
    prohibited_retroactive_targets: Sequence[str],
    proposed_repair: str,
    repair_falsifier: str,
    conclusion_ceiling: str,
) -> list[str]:
    """Validate all current structure while reporting lexical prose drift.

    This compatibility validator is only for a projection already bound to its
    unique hash-verified record event.  It does not authorize writes.
    """

    normalized = _normalize_cross_lane_lesson(
        origin_lane_id=origin_lane_id,
        target_lane_ids=target_lane_ids,
        origin_artifact_locator=origin_artifact_locator,
        origin_artifact_sha256=origin_artifact_sha256,
        origin_integrity_status=origin_integrity_status,
        observation=observation,
        failure_class=failure_class,
        strongest_alternative_explanation=strongest_alternative_explanation,
        challenged_invariant=challenged_invariant,
        first_permitted_future_versions=first_permitted_future_versions,
        prohibited_retroactive_targets=prohibited_retroactive_targets,
        proposed_repair=proposed_repair,
        repair_falsifier=repair_falsifier,
        conclusion_ceiling=conclusion_ceiling,
        enforce_report_prose=False,
    )
    findings: list[str] = []
    for field_name in (
        "observation",
        "strongest_alternative_explanation",
        "challenged_invariant",
        "proposed_repair",
        "repair_falsifier",
        "conclusion_ceiling",
    ):
        terms = report_overclaim_terms(str(normalized[field_name]))
        if terms:
            findings.append(f"{field_name}:" + ",".join(terms))
    return findings
