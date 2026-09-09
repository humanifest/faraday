from collections.abc import Sequence
from datetime import datetime
import math
import re
from typing import Any

from research_machine.application.claim_integrity import claim_level_rank
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    ActionCandidate,
    ActionLane,
    AnalysisMode,
    AnalysisContract,
    AnalysisFamilyMember,
    AnalysisStepContract,
    CalibrationCriterion,
    CanaryTargetPlan,
    ConclusionContract,
    Claim,
    ClaimLevel,
    DatasetManifest,
    DatasetArtifact,
    ControlDefinition,
    CONTROL_FAMILIES,
    EvidenceDirection,
    ExperimentProtocol,
    Hypothesis,
    HypothesisDiscriminationTarget,
    HypothesisWorkflowState,
    MeasurementDefinition,
    MeasurementValidityCheck,
    MEASUREMENT_TEMPORAL_ROLES,
    MeasurementRole,
    ProtocolKind,
    ProtocolStatus,
    QualityGateResult,
    QualityGateStatus,
    ResearchRun,
    SelectionWeights,
    ValidationTag,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPORT_OVERCLAIM = re.compile(
    r"\b(?:proved|confirmed|explained)\b",
    re.IGNORECASE,
)
_INDEPENDENT_REVIEW_DECISIONS = {"approved", "approved_with_conditions"}
_METHOD_INFERENCE_CLAIM_CEILINGS: dict[str, ClaimLevel | None] = {
    "computation_only": None,
    "descriptive": ClaimLevel.MEASUREMENT_VALIDITY,
    "association": ClaimLevel.STATISTICAL_ASSOCIATION,
    "design_conditional_effect": ClaimLevel.CAUSAL_DIRECTION,
}


def require_sha256(value: str, field_name: str) -> str:
    digest = require_text(value, field_name)
    if digest != value or not _SHA256.fullmatch(digest):
        raise ValidationError(f"{field_name} must be 64 lowercase hex characters")
    return digest


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


def require_bounded_evidence_summary(value: str) -> str:
    summary = require_text(value, "evidence summary")
    if evidence_summary_overclaim_terms(summary):
        raise ValidationError(
            "evidence summary uses report-prohibited overclaiming language; "
            "state bounded support, weakening, refutation, or inconclusiveness instead"
        )
    return summary


def evidence_summary_overclaim_terms(value: str) -> list[str]:
    if not isinstance(value, str):
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for match in _REPORT_OVERCLAIM.finditer(value):
        term = match.group(0).casefold()
        if term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


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
    ceilings = require_text_list(
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
        }
    ):
        raise ValidationError(
            "supporting evidence cannot target mechanism, adaptation, or "
            "attribution-intent claims under the current validation-tag "
            "capability model"
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
        require_canonical_contract_list(
            contract.contrast_groups, "analysis_contract.contrast_groups"
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
        unsupported = require_unique_text_list(
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
            for name, value in control.to_dict().items():
                require_canonical_text(value, f"control definition {name}")
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
        if ordered_targets != registered_controls:
            raise ValidationError(
                "control definitions must cover exactly the registered controls in order"
            )
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


def validate_measurement_contract(protocol: ExperimentProtocol) -> None:
    definitions = protocol.measurement_definitions
    if any(not isinstance(item, MeasurementDefinition) for item in definitions):
        raise ValidationError(
            "measurement_definitions must contain MeasurementDefinition values"
        )
    identifiers: set[str] = set()
    data_columns: dict[str, str] = {}
    observed_targets: list[tuple[MeasurementRole, str]] = []
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
                summary=require_text(gate.summary, "quality gate summary"),
                required=gate.required,
                details=dict(gate.details),
            )
        )
    return normalized


def validate_action_candidates(
    candidates: Sequence[ActionCandidate],
    known_hypotheses: set[str],
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
        unknown = sorted(set(hypotheses) - known_hypotheses)
        if unknown:
            raise ValidationError(
                f"action {action_id} references unknown hypotheses: "
                + ", ".join(unknown)
            )
        discrimination_targets = _validate_hypothesis_discrimination_targets(
            candidate.hypothesis_discrimination_targets, hypotheses, action_id
        )
        for field_name in score_fields:
            value = getattr(candidate, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError(f"{field_name} must be a number from 0 to 1")
            if not 0 <= float(value) <= 1:
                raise ValidationError(f"{field_name} must be a number from 0 to 1")
        if not isinstance(candidate.prerequisites_met, bool):
            raise ValidationError("prerequisites_met must be true or false")
        if not isinstance(candidate.safety_approved, bool):
            raise ValidationError("safety_approved must be true or false")
        if not isinstance(candidate.factorial_or_crossover_design, bool):
            raise ValidationError(
                "factorial_or_crossover_design must be true or false"
            )
        if not isinstance(candidate.metadata, dict):
            raise ValidationError("action metadata must be an object")
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
                burden=float(candidate.burden),
                safety_risk=float(candidate.safety_risk),
                ambiguity_risk=float(candidate.ambiguity_risk),
                rationale=require_text(candidate.rationale, "action rationale"),
                hypothesis_discrimination_targets=discrimination_targets,
                prerequisites_met=candidate.prerequisites_met,
                safety_approved=candidate.safety_approved,
                lane_id=require_canonical_text(candidate.lane_id, "lane_id"),
                information_targets=information_targets,
                depends_on=depends_on,
                manipulated_factors=manipulated_factors,
                factorial_or_crossover_design=(
                    candidate.factorial_or_crossover_design
                ),
                factor_interpretability_plan=factor_interpretability_plan,
                metadata=dict(candidate.metadata),
            )
        )
    return normalized


def _validate_hypothesis_discrimination_targets(
    targets: Sequence[HypothesisDiscriminationTarget],
    hypotheses: list[str],
    action_id: str,
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
            )
        )
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
    known_hypotheses: set[str],
    lanes: Sequence[ActionLane],
    completed_action_ids: Sequence[str],
) -> tuple[list[ActionCandidate], list[str]]:
    normalized = validate_action_candidates(candidates, known_hypotheses)
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
    if integrity_status not in {"declared", "verified_elsewhere"}:
        raise ValidationError(
            "origin_integrity_status must be declared or verified_elsewhere"
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
        "observation": require_text(observation, "observation"),
        "failure_class": failure,
        "strongest_alternative_explanation": require_text(
            strongest_alternative_explanation,
            "strongest_alternative_explanation",
        ),
        "challenged_invariant": require_text(
            challenged_invariant, "challenged_invariant"
        ),
        "first_permitted_future_versions": future_versions,
        "prohibited_retroactive_targets": prohibited_targets,
        "proposed_repair": require_text(proposed_repair, "proposed_repair"),
        "repair_falsifier": require_text(repair_falsifier, "repair_falsifier"),
        "conclusion_ceiling": require_text(
            conclusion_ceiling, "conclusion_ceiling"
        ),
    }
