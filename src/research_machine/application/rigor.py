from __future__ import annotations

from collections import Counter
from datetime import datetime

from research_machine.application.policies import (
    declares_legacy_pre_registration_result_exposure,
    evidence_summary_overclaim_terms,
    normalize_confidence,
    report_overclaim_terms,
    validate_validation_tag_context,
)
from research_machine.application.claim_integrity import claim_level_rank
from research_machine.application.audit_prerequisite import (
    verify_action_audit_prerequisite,
)
from research_machine.application.dataset_source_authority import (
    validate_dataset_source_authority,
)
from research_machine.application.dataset_inventory import (
    dataset_workflow_materialization_status,
)
from research_machine.application.alias_proxy_mapping import (
    alias_proxy_commitments,
    protocol_requires_alias_proxy_mapping,
    validate_alias_proxy_mapping_record,
)
from research_machine.domain.errors import ResearchMachineError
from research_machine.domain.models import (
    AnalysisMode,
    ActionRecommendation,
    AliasProxyMappingRecord,
    Claim,
    ClaimDisposition,
    ClaimEpistemicLayer,
    CrossLaneLesson,
    CrossLaneTransferAuthorityStatus,
    DatasetManifest,
    DatasetRole,
    EvidenceDirection,
    EvidenceRecord,
    ExperimentProtocol,
    Hypothesis,
    Inquiry,
    ProtocolKind,
    ProtocolStatus,
    Question,
    QuestionStatus,
    QualityGateStatus,
    ResearchRun,
    RigorAudit,
    RigorFinding,
    RigorSeverity,
    RunStatus,
    ValidationTag,
)

_FALSIFYING_CONTROL_FAMILIES = {
    "negative", "sham", "replay", "random_time", "adversarial",
    "apparatus_only",
}


def _conclusion_ceiling(capabilities: dict[str, bool]) -> str:
    classified = capabilities["classified_evidence"]
    if not classified:
        return "unclassified evidence only"
    if not capabilities[ValidationTag.INTERNAL_CONSISTENCY.value]:
        return "source assessment or calibration only"
    if not capabilities[ValidationTag.CONTROLLED_BENCHMARK.value]:
        return "internal consistency only"
    if not capabilities[ValidationTag.INDEPENDENT_REPLICATION.value]:
        return "controlled but internally generated result"
    if not capabilities[ValidationTag.KNOWN_RESULT_REPRODUCTION.value]:
        return (
            "independently replicated limited result; known-result reproduction absent"
        )
    if not capabilities[ValidationTag.NOVEL_PREDICTION.value]:
        return "replicated and reproduced result; no novel prediction"
    if not capabilities[ValidationTag.EMPIRICAL_TEST.value]:
        return "registered novel prediction; no empirical test"
    if capabilities[ValidationTag.CAUSAL_ESTIMATE.value]:
        return "scoped design-conditional causal estimate; no mechanism or out-of-scope generalization"
    return "scoped empirical result; not proof of a theory"


def _protected_empirical(protocol: ExperimentProtocol) -> bool:
    return (
        protocol.analysis_mode
        in {AnalysisMode.CONFIRMATORY, AnalysisMode.REPLICATION}
        and protocol.protocol_kind
        in {ProtocolKind.OBSERVATIONAL, ProtocolKind.EXPERIMENTAL}
    )


def _dataset_artifact_verification_passed(dataset: DatasetManifest) -> bool:
    verification = dataset.metadata.get("dataset_artifact_verification")
    if not isinstance(verification, dict):
        return False
    integrity = verification.get("artifact_integrity")
    return (
        isinstance(integrity, dict)
        and integrity.get("status") == "passed"
        and integrity.get("all_artifacts_match") is True
    )


def _dataset_measurement_custody_verification_passed(
    dataset: DatasetManifest,
    protocol: ExperimentProtocol,
) -> bool:
    verification = dataset.metadata.get("measurement_custody_verification")
    if not isinstance(verification, dict):
        return False
    integrity = verification.get("artifact_integrity")
    return (
        isinstance(protocol.protocol_hash, str)
        and len(protocol.protocol_hash) == 64
        and verification.get("protocol_hash") == protocol.protocol_hash
        and verification.get("required_gate_ids")
        == list(protocol.measurement_custody_requirements)
        and isinstance(verification.get("custody_artifact_root"), str)
        and bool(verification["custody_artifact_root"].strip())
        and isinstance(verification.get("custody_receipt_sha256"), str)
        and len(verification["custody_receipt_sha256"]) == 64
        and isinstance(integrity, dict)
        and integrity.get("status") == "passed"
        and integrity.get("all_artifacts_match") is True
    )


def _dataset_ethics_review_status_check_passed(
    dataset: DatasetManifest,
    protocol: ExperimentProtocol,
) -> bool:
    check = dataset.metadata.get("ethics_review_status_check")
    return (
        isinstance(protocol.protocol_hash, str)
        and len(protocol.protocol_hash) == 64
        and isinstance(check, dict)
        and check.get("status") == "active"
        and check.get("protocol_id") == protocol.protocol_id
        and check.get("protocol_hash") == protocol.protocol_hash
        and check.get("basis")
        in {"frozen_independent_review_decision", "append_only_ethics_review_event"}
    )


def _dataset_ethics_condition_verification_passed(
    dataset: DatasetManifest,
    protocol: ExperimentProtocol,
) -> bool:
    verification = dataset.metadata.get("ethics_condition_verification")
    if not isinstance(verification, dict):
        return False
    integrity = verification.get("artifact_integrity")
    condition_results = verification.get("condition_results")
    location_checks = verification.get("evidence_location_checks")
    if (
        not isinstance(condition_results, list)
        or not all(isinstance(item, dict) for item in condition_results)
        or not isinstance(location_checks, list)
        or not all(isinstance(item, dict) for item in location_checks)
    ):
        return False
    return (
        isinstance(protocol.protocol_hash, str)
        and len(protocol.protocol_hash) == 64
        and verification.get("protocol_id") == protocol.protocol_id
        and verification.get("protocol_hash") == protocol.protocol_hash
        and verification.get(
            "independent_review_receipt"
        ) == protocol.independent_review_receipt
        and isinstance(verification.get("evidence_artifact_root"), str)
        and bool(verification["evidence_artifact_root"].strip())
        and isinstance(verification.get("discharge_receipt_sha256"), str)
        and len(verification["discharge_receipt_sha256"]) == 64
        and isinstance(integrity, dict)
        and integrity.get("status") == "passed"
        and integrity.get("all_artifacts_match") is True
        and [item.get("condition") for item in condition_results]
        == list(protocol.independent_review_conditions)
        and [item.get("condition") for item in location_checks]
        == list(protocol.independent_review_conditions)
    )


def _has_preprocessing_conformance_gate(run: ResearchRun) -> bool:
    return any(
        isinstance(gate.details.get("preprocessing_conformance"), dict)
        for gate in run.quality_gates
    )


def _has_structured_gate_detail(run: ResearchRun, key: str) -> bool:
    return any(isinstance(gate.details.get(key), dict) for gate in run.quality_gates)


def _has_structured_gate_detail_for_gate_ids(
    run: ResearchRun,
    key: str,
    gate_ids: set[str],
) -> bool:
    return any(
        gate.gate_id in gate_ids and isinstance(gate.details.get(key), dict)
        for gate in run.quality_gates
    )


def _causal_temporal_order_gate_ids(protocol: ExperimentProtocol) -> set[str]:
    if not protocol.causal_claim:
        return set()
    audit = protocol.causal_identification_audit
    register = audit.get("assumption_register") if isinstance(audit, dict) else None
    if not isinstance(register, list):
        return set()
    return {
        gate_id
        for item in register
        if isinstance(item, dict)
        and item.get("category") == "temporal_order"
        and isinstance((gate_id := item.get("assessment_gate_id")), str)
        and gate_id
    }


def _reported_causal_assumption_categories(
    protocol: ExperimentProtocol,
    runs: list[ResearchRun],
) -> set[str]:
    if not protocol.causal_claim:
        return set()
    audit = protocol.causal_identification_audit
    register = audit.get("assumption_register") if isinstance(audit, dict) else None
    if not isinstance(register, list):
        return set()
    gate_ids = {
        gate_id
        for item in register
        if isinstance(item, dict)
        and isinstance((gate_id := item.get("assessment_gate_id")), str)
        and gate_id
    }
    reported: set[str] = set()
    for run in runs:
        if run.protocol_id != protocol.protocol_id:
            continue
        for gate in run.quality_gates:
            if gate.gate_id not in gate_ids:
                continue
            results = gate.details.get("causal_assumption_results")
            if not isinstance(results, dict):
                continue
            reported.update(
                category
                for category, result in results.items()
                if isinstance(category, str) and isinstance(result, dict)
            )
    return reported


def _reported_measurement_validity_check_ids(
    protocol: ExperimentProtocol,
    runs: list[ResearchRun],
) -> set[str]:
    gate_ids = {
        check.assessment_gate_id
        for check in protocol.measurement_validity_checks
    }
    reported: set[str] = set()
    for run in runs:
        if run.protocol_id != protocol.protocol_id:
            continue
        for gate in run.quality_gates:
            if gate.gate_id not in gate_ids:
                continue
            results = gate.details.get("measurement_validity_results")
            if not isinstance(results, dict):
                continue
            reported.update(
                check_id
                for check_id, result in results.items()
                if isinstance(check_id, str) and isinstance(result, dict)
            )
    return reported


def _reported_control_result_ids(
    protocol: ExperimentProtocol,
    runs: list[ResearchRun],
) -> set[str]:
    gate_ids = {
        control.evaluation_gate_id
        for control in protocol.control_definitions
    }
    reported: set[str] = set()
    for run in runs:
        if run.protocol_id != protocol.protocol_id:
            continue
        for gate in run.quality_gates:
            if gate.gate_id not in gate_ids:
                continue
            results = gate.details.get("control_results")
            if not isinstance(results, dict):
                continue
            reported.update(
                control_id
                for control_id, result in results.items()
                if isinstance(control_id, str) and isinstance(result, dict)
            )
    return reported


def _factor_interpretability_state(protocol: ExperimentProtocol) -> str:
    factors = protocol.manipulated_factors
    has_plan = bool(protocol.factor_interpretability_plan.strip())
    if protocol.factorial_or_crossover_design and not factors:
        return "invalid"
    if protocol.factorial_or_crossover_design and not has_plan:
        return "invalid"
    if len(factors) > 1 and (
        not protocol.factorial_or_crossover_design or not has_plan
    ):
        return "invalid"
    if len(factors) > 1:
        return "planned_multi_factor"
    if len(factors) == 1:
        return "single_factor"
    if has_plan:
        return "plan_without_factor"
    return "none"


def audit_research_state(
    *,
    inquiry: Inquiry,
    claims: list[Claim],
    hypotheses: list[Hypothesis],
    evidence: list[EvidenceRecord],
    datasets: list[DatasetManifest],
    protocols: list[ExperimentProtocol],
    runs: list[ResearchRun],
    alias_proxy_mapping_records: list[AliasProxyMappingRecord] | None = None,
    cross_lane_lessons: list[CrossLaneLesson] | None = None,
    questions: list[Question] | None = None,
    recommendations: list[ActionRecommendation] | None = None,
) -> RigorAudit:
    findings: list[RigorFinding] = []

    def add(
        code: str,
        severity: RigorSeverity,
        message: str,
        *,
        entity_type: str = "workspace",
        entity_id: str = "",
        remediation: str = "",
    ) -> None:
        findings.append(
            RigorFinding(
                code=code,
                severity=severity,
                message=message,
                entity_type=entity_type,
                entity_id=entity_id,
                remediation=remediation,
            )
        )

    if not inquiry.decision_to_support.strip():
        add(
            "INQUIRY_DECISION_MISSING",
            RigorSeverity.WARNING,
            "The inquiry does not state the practical decision it should support.",
            entity_type="inquiry",
            entity_id=inquiry.inquiry_id,
            remediation="Record the smallest practical decision this research informs.",
        )
    if not inquiry.minimum_evidence.strip():
        add(
            "INQUIRY_MINIMUM_EVIDENCE_MISSING",
            RigorSeverity.WARNING,
            "The inquiry has no declared minimum evidence threshold.",
            entity_type="inquiry",
            entity_id=inquiry.inquiry_id,
        )
    if not inquiry.decision_change_criteria:
        add(
            "INQUIRY_CHANGE_CRITERIA_MISSING",
            RigorSeverity.WARNING,
            "The inquiry does not state what observations would change the decision.",
            entity_type="inquiry",
            entity_id=inquiry.inquiry_id,
        )
    if inquiry.decision_to_support.strip() and not inquiry.decision_owner.strip():
        add(
            "INQUIRY_DECISION_OWNER_MISSING",
            RigorSeverity.WARNING,
            "The inquiry names a decision but not the person responsible for it.",
            entity_type="inquiry",
            entity_id=inquiry.inquiry_id,
        )
    open_questions = [
        question
        for question in (questions or [])
        if question.status in {QuestionStatus.OPEN, QuestionStatus.DEFERRED}
    ]
    if open_questions:
        question_ids = ", ".join(question.question_id for question in open_questions)
        add(
            "INQUIRY_OPEN_QUESTIONS_UNRESOLVED",
            RigorSeverity.WARNING,
            (
                f"The inquiry still has {len(open_questions)} unresolved "
                "open or deferred clarifying question(s); these remain live ambiguity rather than "
                "evidence, answers, or authorization to prefer an explanation."
            ),
            entity_type="inquiry",
            entity_id=inquiry.inquiry_id,
            remediation=(
                "Resolve, defer with an explicit rationale, or preserve these "
                "questions before relying on a preferred explanation: "
                + question_ids
            ),
        )

    for recommendation in recommendations or []:
        if recommendation.score_contract_version < 3:
            add(
                "ACTION_AUDIT_PREREQUISITE_LEGACY_MISSING",
                RigorSeverity.WARNING,
                (
                    "Historical recommendation predates typed, current-byte "
                    "audit-prerequisite eligibility and has no current authority "
                    "to advance candidate or implementation bytes."
                ),
                entity_type="recommendation",
                entity_id=recommendation.recommendation_id,
                remediation=(
                    "Preserve the historical record. Create a new recommendation "
                    "with a prospective audit-prerequisite contract before advancement."
                ),
            )
            continue
        selected_ids = (
            set(recommendation.selected_action_ids_by_lane.values())
            if recommendation.selection_mode == "portfolio"
            else {recommendation.selected_action_id}
        )
        for candidate in recommendation.candidates:
            try:
                receipt = verify_action_audit_prerequisite(candidate)
            except ResearchMachineError as exc:
                add(
                    "ACTION_AUDIT_PREREQUISITE_REPLAY_FAILED",
                    RigorSeverity.ERROR,
                    f"Action audit-prerequisite receipt did not replay: {exc}",
                    entity_type="action_candidate",
                    entity_id=candidate.action_id,
                    remediation=(
                        "Restore the exact retained subject and audit artifacts; "
                        "do not select or advance the action."
                    ),
                )
                continue
            contract = candidate.audit_prerequisite_contract
            if contract is None:
                continue
            if receipt.get("action_class") == "exposed_evaluator_development":
                add(
                    "ACTION_EXPOSED_EVALUATOR_DEVELOPMENT",
                    RigorSeverity.INFO,
                    (
                        "Action is explicitly exposed evaluator development; it "
                        "may exercise software but cannot advance a candidate, "
                        "claim hypothesis discrimination, or establish evidence."
                    ),
                    entity_type="action_candidate",
                    entity_id=candidate.action_id,
                )
                continue
            if receipt.get("action_class") == "nonadvancing_information":
                add(
                    "ACTION_NONADVANCING_INFORMATION",
                    RigorSeverity.INFO,
                    (
                        "Action is explicitly non-advancing information work; it "
                        "may gather bounded source or workflow information but cannot "
                        "advance candidate or implementation bytes, claim hypothesis "
                        "discrimination, establish evidence, or create replication authority."
                    ),
                    entity_type="action_candidate",
                    entity_id=candidate.action_id,
                )
                continue
            if receipt.get("candidate_advancement_eligible") is not True:
                add(
                    "ACTION_AUDIT_PREREQUISITE_NOT_ELIGIBLE",
                    (
                        RigorSeverity.ERROR
                        if candidate.action_id in selected_ids
                        else RigorSeverity.WARNING
                    ),
                    (
                        "Candidate-advancing action retains a pending or adverse "
                        "audit and is not workflow-eligible for advancement."
                    ),
                    entity_type="action_candidate",
                    entity_id=candidate.action_id,
                    remediation=(
                        "Do not relabel the audit. Preserve it and address the "
                        "finding in a new candidate or implementation version."
                    ),
                )
            elif candidate.action_id in selected_ids:
                add(
                    "ACTION_AUDIT_PREREQUISITE_WORKFLOW_ELIGIBLE",
                    RigorSeverity.INFO,
                    (
                        "Selected candidate-advancing action is workflow-eligible "
                        "from exact retained bytes only; audit truth, auditor "
                        "identity or independence, scientific validity, and "
                        "evidence eligibility and replication authority remain "
                        "unestablished."
                    ),
                    entity_type="action_candidate",
                    entity_id=candidate.action_id,
                )

    for lesson in cross_lane_lessons or []:
        if (
            lesson.current_transfer_authority
            and lesson.transfer_authority_status
            is CrossLaneTransferAuthorityStatus.CURRENT
        ):
            continue
        if (
            lesson.transfer_authority_status
            is CrossLaneTransferAuthorityStatus.UNVERIFIED
        ):
            add(
                "CROSS_LANE_LESSON_TRANSFER_AUTHORITY_UNVERIFIED",
                RigorSeverity.ERROR,
                (
                    "Cross-lane lesson transfer authority was not derived from "
                    "its hash-verified ledger event."
                ),
                entity_type="cross_lane_lesson",
                entity_id=lesson.lesson_id,
                remediation=(
                    "Load the lesson through the canonical service; do not use an "
                    "unverified projection to change another research lane."
                ),
            )
            continue
        if lesson.report_prose_findings:
            add(
                "CROSS_LANE_LESSON_LEGACY_REPORT_PROSE",
                RigorSeverity.WARNING,
                (
                    "Ledger-bound historical cross-lane lesson fails only current "
                    "lexical report-prose semantics and has no current transfer "
                    "authority: "
                    + ", ".join(lesson.report_prose_findings)
                    + "."
                ),
                entity_type="cross_lane_lesson",
                entity_id=lesson.lesson_id,
                remediation=(
                    "Preserve the historical lesson unchanged. Record a new bounded "
                    "lesson for any prospective transfer; do not treat legacy prose "
                    "as current machine or scientific authority."
                ),
            )
            continue
        add(
            "CROSS_LANE_LESSON_LEGACY_UNCOMMITTED",
            RigorSeverity.WARNING,
            (
                "Ledger-bound historical cross-lane lesson lacks a retained payload "
                "commitment and has no current transfer authority."
            ),
            entity_type="cross_lane_lesson",
            entity_id=lesson.lesson_id,
            remediation=(
                "Preserve the historical lesson unchanged. Record a new committed "
                "lesson if the process observation should influence future work."
            ),
        )

    claim_ids = [claim.claim_id for claim in claims]
    claim_id_set = set(claim_ids)
    duplicate_claim_ids = sorted(
        claim_id for claim_id in claim_id_set if claim_ids.count(claim_id) > 1
    )
    for claim_id in duplicate_claim_ids:
        add(
            "DUPLICATE_CLAIM_ID",
            RigorSeverity.ERROR,
            "The authoritative claim spine contains a duplicate stable ID.",
            entity_type="claim",
            entity_id=claim_id,
        )

    dependencies = {claim.claim_id: claim.parent_claims for claim in claims}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(claim_id: str) -> bool:
        if claim_id in visiting:
            return True
        if claim_id in visited:
            return False
        visiting.add(claim_id)
        cyclic = any(
            parent in dependencies and visit(parent)
            for parent in dependencies.get(claim_id, [])
        )
        visiting.remove(claim_id)
        visited.add(claim_id)
        return cyclic

    if any(visit(claim_id) for claim_id in claim_id_set):
        add(
            "CLAIM_DEPENDENCY_CYCLE",
            RigorSeverity.ERROR,
            "The authoritative claim spine contains a dependency cycle.",
        )

    claims_by_id = {claim.claim_id: claim for claim in claims}
    reported_accepted_conflicts: set[frozenset[str]] = set()
    for claim in claims:
        try:
            normalize_confidence(claim.confidence)
        except ResearchMachineError as exc:
            add(
                "CLAIM_CONFIDENCE_INVALID",
                RigorSeverity.ERROR,
                str(exc),
                entity_type="claim",
                entity_id=claim.claim_id,
            )
        missing_parents = sorted(set(claim.parent_claims) - claim_id_set)
        missing_conflicts = sorted(set(claim.conflicts_with) - claim_id_set)
        if missing_parents:
            add(
                "CLAIM_DEPENDENCY_MISSING",
                RigorSeverity.ERROR,
                "Claim references missing dependencies: " + ", ".join(missing_parents),
                entity_type="claim",
                entity_id=claim.claim_id,
            )
        if missing_conflicts:
            add(
                "CLAIM_CONFLICT_REFERENCE_MISSING",
                RigorSeverity.ERROR,
                "Claim references missing conflicts: " + ", ".join(missing_conflicts),
                entity_type="claim",
                entity_id=claim.claim_id,
            )
        claim_rank = claim_level_rank(claim.level)
        if claim_rank is not None:
            for parent_id in claim.parent_claims:
                parent = claims_by_id.get(parent_id)
                if parent is None:
                    continue
                parent_rank = claim_level_rank(parent.level)
                if parent_rank is not None and parent_rank > claim_rank:
                    add(
                        "CLAIM_DEPENDENCY_LEVEL_INVERTED",
                        RigorSeverity.ERROR,
                        (
                            f"Claim depends on higher-inference parent {parent_id} "
                            f"({parent.level.value}) while its own level is "
                            f"{claim.level.value}."
                        ),
                        entity_type="claim",
                        entity_id=claim.claim_id,
                        remediation=(
                            "Restructure the claim graph so known scientific "
                            "dependencies flow from lower or same inference levels "
                            "toward stronger conclusions; do not use a stronger "
                            "claim as hidden support for a lower-level assertion."
                        ),
                    )
        if (
            claim.epistemic_layer
            in {
                ClaimEpistemicLayer.DOCUMENTED_FACT,
                ClaimEpistemicLayer.SOURCE_CLAIM,
            }
            and not claim.source_refs
        ):
            severity = (
                RigorSeverity.ERROR
                if claim.disposition is ClaimDisposition.ACCEPTED
                else RigorSeverity.WARNING
            )
            add(
                "SOURCE_GROUNDED_CLAIM_WITHOUT_SOURCE",
                severity,
                "A documented fact or source claim has no source reference.",
                entity_type="claim",
                entity_id=claim.claim_id,
            )
        if (
            claim.epistemic_layer is ClaimEpistemicLayer.REASONABLE_INFERENCE
            and not claim.parent_claims
        ):
            add(
                "INFERENCE_WITHOUT_DEPENDENCY",
                RigorSeverity.WARNING,
                "A reasonable inference does not identify the claims it depends on.",
                entity_type="claim",
                entity_id=claim.claim_id,
            )
        if claim.disposition is ClaimDisposition.ACCEPTED and not claim.last_reviewed:
            add(
                "ACCEPTED_CLAIM_NOT_REVIEWED",
                RigorSeverity.WARNING,
                "An accepted claim has no recorded review timestamp.",
                entity_type="claim",
                entity_id=claim.claim_id,
            )
        if (
            claim.disposition is ClaimDisposition.ACCEPTED
            and not claim.decision_owner.strip()
        ):
            add(
                "ACCEPTED_CLAIM_OWNER_MISSING",
                RigorSeverity.WARNING,
                "An accepted claim has no recorded decision owner.",
                entity_type="claim",
                entity_id=claim.claim_id,
            )
        if claim.disposition is ClaimDisposition.REJECTED and not claim.falsified_by:
            add(
                "REJECTED_CLAIM_WITHOUT_FALSIFIER",
                RigorSeverity.WARNING,
                "A rejected claim does not identify what rejected it.",
                entity_type="claim",
                entity_id=claim.claim_id,
            )
        for conflict_id in claim.conflicts_with:
            conflict = claims_by_id.get(conflict_id)
            conflict_pair = frozenset({claim.claim_id, conflict_id})
            if (
                conflict is not None
                and claim.disposition is ClaimDisposition.ACCEPTED
                and conflict.disposition is ClaimDisposition.ACCEPTED
                and conflict_pair not in reported_accepted_conflicts
            ):
                reported_accepted_conflicts.add(conflict_pair)
                add(
                    "ACCEPTED_CLAIMS_CONFLICT",
                    RigorSeverity.ERROR,
                    f"Accepted claims {claim.claim_id} and {conflict_id} conflict.",
                    entity_type="claim",
                    entity_id=claim.claim_id,
                    remediation="Resolve the conflict or narrow the claims before relying on both.",
                )

    hypothesis_by_id = {item.hypothesis_id: item for item in hypotheses}
    protocol_by_id = {item.protocol_id: item for item in protocols}
    run_by_id = {item.run_id: item for item in runs}
    dataset_by_id = {item.dataset_id: item for item in datasets}
    alias_records_by_protocol: dict[str, list[AliasProxyMappingRecord]] = {}
    for record in alias_proxy_mapping_records or []:
        alias_records_by_protocol.setdefault(record.protocol_id, []).append(record)
    protected_dataset_roles = {DatasetRole.CONFIRMATORY, DatasetRole.REPLICATION}
    for protocol in protocols:
        if not protocol_requires_alias_proxy_mapping(protocol):
            continue
        records = alias_records_by_protocol.get(protocol.protocol_id, [])
        severity = (
            RigorSeverity.ERROR
            if _protected_empirical(protocol)
            else RigorSeverity.WARNING
        )
        if not records:
            commitments = ", ".join(
                f"{definition.measurement_id}:{commitment.commitment_id}"
                for definition, commitment in alias_proxy_commitments(protocol)
            )
            add(
                "ALIAS_PROXY_MAPPING_CUSTODY_MISSING",
                severity,
                (
                    "Protocol uses blinded aliases or proxy measurements but has "
                    "no verified private mapping custody record; the frozen hash "
                    "commitment remains a design commitment only."
                ),
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "Record the private mapping through the canonical alias/proxy "
                    "custody command before treating runs as strong evidence. "
                    "Missing commitments: "
                    + commitments
                ),
            )
            continue
        for record in records:
            try:
                validate_alias_proxy_mapping_record(protocol, record)
            except ResearchMachineError as exc:
                add(
                    "ALIAS_PROXY_MAPPING_CUSTODY_INVALID",
                    RigorSeverity.ERROR,
                    (
                        "Alias/proxy private mapping custody no longer replays "
                        f"against current local bytes and frozen commitments: {exc}"
                    ),
                    entity_type="alias_proxy_mapping_record",
                    entity_id=record.record_id,
                    remediation=(
                        "Restore the exact private mapping artifact bytes/root or "
                        "treat all runs under this aliased protocol as "
                        "non-evidentiary; never rewrite the frozen mapping hash."
                    ),
                )
            else:
                add(
                    "ALIAS_PROXY_MAPPING_CUSTODY_RECORDED",
                    RigorSeverity.INFO,
                    (
                        "Alias/proxy private mapping bytes replay against the "
                        "frozen protocol commitment. This preserves auditability "
                        "without proving proxy validity or revealing the mapping."
                    ),
                    entity_type="alias_proxy_mapping_record",
                    entity_id=record.record_id,
                )
    for dataset in datasets:
        if (
            "workflow_materialization" in dataset.metadata
            or "workflow_materialization_verification" in dataset.metadata
        ):
            try:
                dataset_workflow_materialization_status(dataset)
            except ResearchMachineError as exc:
                add(
                    "DATASET_WORKFLOW_MATERIALIZATION_INVALID",
                    RigorSeverity.ERROR,
                    (
                        "Dataset workflow-materialization metadata no longer "
                        "satisfies the bounded local byte-chain contract."
                    ),
                    entity_type="dataset",
                    entity_id=dataset.dataset_id,
                    remediation=(
                        "Do not use this materialized workflow dataset for "
                        "scientific interpretation until the canonical service can "
                        "replay its local byte-chain contract without upgrading it "
                        f"to evidence eligibility, chronology authentication, "
                        f"executor independence, or source-data truth: {exc}"
                    ),
                )
        if "source_authority" in dataset.metadata:
            try:
                validate_dataset_source_authority(
                    dataset.metadata["source_authority"],
                    synthetic=dataset.synthetic,
                )
            except ResearchMachineError as exc:
                add(
                    "DATASET_SOURCE_AUTHORITY_INVALID",
                    RigorSeverity.ERROR,
                    "Dataset source-authority metadata no longer satisfies the bounded source-route contract.",
                    entity_type="dataset",
                    entity_id=dataset.dataset_id,
                    remediation=(
                        "Do not use this dataset for scientific interpretation until "
                        "the canonical service can replay its source route without "
                        f"upgrading authority: {exc}"
                    ),
                )
        if dataset.role not in protected_dataset_roles:
            continue
        if (
            not dataset.synthetic
            and "source_authority" not in dataset.metadata
        ):
            add(
                "PROTECTED_DATASET_SOURCE_AUTHORITY_NOT_RECORDED",
                RigorSeverity.WARNING,
                "Protected non-synthetic dataset lacks typed source-route authority metadata.",
                entity_type="dataset",
                entity_id=dataset.dataset_id,
                remediation=(
                    "Record the bounded source route for future protected datasets "
                    "through canonical dataset registration; artifact hashes, plugin "
                    "access, connector access, or dataset role do not establish source "
                    "truth, custody, consent, or evidence eligibility."
                ),
            )
        if not dataset.protocol_id:
            add(
                "PROTECTED_DATASET_PROTOCOL_MISSING",
                RigorSeverity.ERROR,
                "Protected dataset is not bound to a frozen protocol.",
                entity_type="dataset",
                entity_id=dataset.dataset_id,
                remediation=(
                    "Treat this dataset as unusable for protected analysis; register "
                    "future protected observations against the exact frozen protocol."
                ),
            )
            continue
        if dataset.protocol_id not in protocol_by_id:
            add(
                "PROTECTED_DATASET_PROTOCOL_UNKNOWN",
                RigorSeverity.ERROR,
                "Protected dataset references a protocol that is not present in the workspace.",
                entity_type="dataset",
                entity_id=dataset.dataset_id,
                remediation=(
                    "Restore the frozen protocol or register a new protected dataset "
                    "without rewriting this record."
                ),
            )
        protocol = protocol_by_id.get(dataset.protocol_id)
        if (
            protocol is not None
            and protocol.human_subjects
            and not _dataset_ethics_review_status_check_passed(dataset, protocol)
        ):
            add(
                "PROTECTED_DATASET_ETHICS_REVIEW_STATUS_CHECK_MISSING",
                RigorSeverity.ERROR,
                (
                    "Protected human-subject dataset lacks an active "
                    "service-generated ethics review status check bound to the "
                    "exact frozen protocol."
                ),
                entity_type="dataset",
                entity_id=dataset.dataset_id,
                remediation=(
                    "Treat the dataset as unusable for protected analysis until it "
                    "is registered through the canonical service after evaluating "
                    "the latest applicable ethics review status; a frozen approval "
                    "record alone is not current clearance."
                ),
            )
        if (
            protocol is not None
            and protocol.human_subjects
            and protocol.independent_review_decision == "approved_with_conditions"
            and not _dataset_ethics_condition_verification_passed(
                dataset, protocol
            )
        ):
            add(
                "PROTECTED_DATASET_ETHICS_CONDITION_VERIFICATION_MISSING",
                RigorSeverity.ERROR,
                (
                    "Protected conditionally approved human-subject dataset lacks "
                    "a passed service-generated condition-discharge verification "
                    "covering every frozen review condition."
                ),
                entity_type="dataset",
                entity_id=dataset.dataset_id,
                remediation=(
                    "Treat the dataset as unusable for protected analysis until it "
                    "is registered through the canonical service with artifact-"
                    "backed discharge evidence for every frozen condition; "
                    "condition prose cannot discharge human-subject obligations."
                ),
            )
        if (
            protocol is not None
            and protocol.measurement_custody_requirements
            and not _dataset_measurement_custody_verification_passed(
                dataset, protocol
            )
        ):
            add(
                "PROTECTED_DATASET_MEASUREMENT_CUSTODY_VERIFICATION_MISSING",
                RigorSeverity.ERROR,
                (
                    "Protected dataset lacks a passed service-generated "
                    "measurement-custody verification receipt for the exact frozen "
                    "protocol and required custody gates."
                ),
                entity_type="dataset",
                entity_id=dataset.dataset_id,
                remediation=(
                    "Treat the dataset as unusable for protected analysis until it "
                    "is registered through the canonical service with the original "
                    "custody receipt, local custody-artifact root, exact protocol "
                    "hash, exact required custody gates, and current-byte "
                    "verification; do not trust declared artifact hashes or a "
                    "generic custody note."
                ),
            )
        if (
            not dataset.synthetic
            and not _dataset_artifact_verification_passed(dataset)
        ):
            add(
                "PROTECTED_DATASET_ARTIFACT_VERIFICATION_MISSING",
                RigorSeverity.ERROR,
                "Protected non-synthetic dataset lacks a passed service-generated artifact verification receipt for its registered observation bytes.",
                entity_type="dataset",
                entity_id=dataset.dataset_id,
                remediation=(
                    "Treat the dataset as unusable for protected analysis until it is registered through the canonical service with a local artifact root and current-byte verification; do not trust declared artifact hashes alone."
                ),
            )
        seen_sources: set[str] = set()
        for source_id in dataset.source_dataset_ids:
            if source_id in seen_sources:
                add(
                    "PROTECTED_DATASET_LINEAGE_DUPLICATE_SOURCE",
                    RigorSeverity.ERROR,
                    "Protected dataset repeats a lineage source.",
                    entity_type="dataset",
                    entity_id=dataset.dataset_id,
                    remediation=(
                        "Do not collapse duplicate lineage by editing state; create a "
                        "new corrected dataset record if the lineage was recorded incorrectly."
                    ),
                )
                continue
            seen_sources.add(source_id)
            source = dataset_by_id.get(source_id)
            if source is None:
                add(
                    "PROTECTED_DATASET_LINEAGE_SOURCE_MISSING",
                    RigorSeverity.ERROR,
                    "Protected dataset references a missing lineage source.",
                    entity_type="dataset",
                    entity_id=dataset.dataset_id,
                    remediation=(
                        "Restore the source dataset or treat this protected derivative "
                        "as unusable for confirmatory or replication analysis."
                    ),
                )
                continue
            if source.role is not dataset.role or source.protocol_id != dataset.protocol_id:
                add(
                    "PROTECTED_DATASET_LINEAGE_PROTOCOL_MISMATCH",
                    RigorSeverity.ERROR,
                    "Protected dataset lineage crosses role or protocol boundaries.",
                    entity_type="dataset",
                    entity_id=dataset.dataset_id,
                    remediation=(
                        "Do not use role equality or a derivative label to launder "
                        "observations across frozen protocols; collect or register "
                        "lineage under the exact same protected protocol."
                    ),
                )

    for run in runs:
        run_overclaim_terms = report_overclaim_terms(run.summary)
        if run_overclaim_terms:
            add(
                "RUN_SUMMARY_OVERCLAIM_LANGUAGE",
                RigorSeverity.WARNING,
                "Run summary uses report-prohibited overclaiming language: "
                + ", ".join(run_overclaim_terms)
                + ". Treat the stored prose as a legacy execution assertion, not a scientific conclusion.",
                entity_type="run",
                entity_id=run.run_id,
                remediation=(
                    "Do not rewrite the historical run record; retain the run and "
                    "record bounded evidence or status review before drawing conclusions."
                ),
            )
        for gate in run.quality_gates:
            gate_overclaim_terms = report_overclaim_terms(gate.summary)
            if gate_overclaim_terms:
                add(
                    "QUALITY_GATE_SUMMARY_OVERCLAIM_LANGUAGE",
                    RigorSeverity.WARNING,
                    "Quality gate summary uses report-prohibited overclaiming language: "
                    + ", ".join(gate_overclaim_terms)
                    + ". Treat the stored prose as a legacy gate assertion, not evidence of truth.",
                    entity_type="run",
                    entity_id=f"{run.run_id}:{gate.gate_id}",
                    remediation=(
                        "Do not rewrite the historical gate; preserve its status and "
                        "use bounded artifact-backed gate details or evidence records."
                    ),
                )

    tag_counts: Counter[str] = Counter()
    prospective_tag_counts: Counter[str] = Counter()
    for record in evidence:
        overclaim_terms = evidence_summary_overclaim_terms(record.summary)
        if overclaim_terms:
            add(
                "EVIDENCE_SUMMARY_OVERCLAIM_LANGUAGE",
                RigorSeverity.WARNING,
                "Evidence summary uses report-prohibited overclaiming language: "
                + ", ".join(overclaim_terms)
                + ". Treat the stored prose as a legacy assertion rather than a stronger conclusion.",
                entity_type="evidence",
                entity_id=record.evidence_id,
                remediation=(
                    "Do not rewrite the historical evidence record; append a bounded "
                    "status review or record new scoped evidence with calibrated language."
                ),
            )
        if not record.scope.strip():
            add(
                "EVIDENCE_SCOPE_MISSING",
                RigorSeverity.ERROR,
                "Evidence has no explicit scope.",
                entity_type="evidence",
                entity_id=record.evidence_id,
                remediation="Record the population, regime, model class, or theorem scope.",
            )
        if not record.uncertainty.strip():
            add(
                "EVIDENCE_UNCERTAINTY_MISSING",
                RigorSeverity.ERROR,
                "Evidence has no uncertainty or limitation statement.",
                entity_type="evidence",
                entity_id=record.evidence_id,
                remediation="State statistical, numerical, formal, or source uncertainty.",
            )
        if not record.higher_level_conclusions_unsupported:
            add(
                "EVIDENCE_CEILING_MISSING",
                RigorSeverity.ERROR,
                "Evidence has no explicit higher-level claim ceiling.",
                entity_type="evidence",
                entity_id=record.evidence_id,
                remediation="Name at least one conclusion this result cannot support.",
            )
        if record.direction in {
            EvidenceDirection.SUPPORTS,
            EvidenceDirection.WEAKENS,
            EvidenceDirection.REFUTES,
        } and not (record.controls_passed or record.controls_failed):
            add(
                "DIRECTIONAL_EVIDENCE_WITHOUT_CONTROLS",
                RigorSeverity.ERROR,
                "Directional evidence records no passed or failed control.",
                entity_type="evidence",
                entity_id=record.evidence_id,
                remediation="Record the comparator or negative control that makes direction interpretable.",
            )
        if not record.validation_tags:
            add(
                "LEGACY_EVIDENCE_UNCLASSIFIED",
                RigorSeverity.WARNING,
                "Evidence predates validation tags and contributes to no maturity capability.",
                entity_type="evidence",
                entity_id=record.evidence_id,
                remediation="Do not mutate the record; reproduce it under a newly classified protocol if needed.",
            )
        if not record.claim_id:
            add(
                "EVIDENCE_NOT_CLAIM_SCOPED",
                RigorSeverity.WARNING,
                "Evidence is attached to a hypothesis but not an exact claim node.",
                entity_type="evidence",
                entity_id=record.evidence_id,
                remediation="Attach future evidence to the narrowest applicable claim.",
            )

        hypothesis = hypothesis_by_id.get(record.hypothesis_id)
        if hypothesis is None:
            add(
                "EVIDENCE_HYPOTHESIS_MISSING",
                RigorSeverity.ERROR,
                "Evidence references a missing hypothesis.",
                entity_type="evidence",
                entity_id=record.evidence_id,
            )
            continue
        run = run_by_id.get(record.run_id) if record.run_id else None
        protocol = (
            protocol_by_id.get(record.protocol_id) if record.protocol_id else None
        )
        record_datasets: list[DatasetManifest] = []
        if run is not None:
            record_datasets = [
                dataset_by_id[dataset_id]
                for dataset_id in run.dataset_ids
                if dataset_id in dataset_by_id
            ]
        elif record.dataset_id and record.dataset_id in dataset_by_id:
            record_datasets = [dataset_by_id[record.dataset_id]]
        if record.scientific_evidence_eligible and (
            run is None or not run.scientific_evidence_eligible
        ):
            add(
                "EVIDENCE_ELIGIBILITY_INCONSISTENT",
                RigorSeverity.ERROR,
                "Evidence eligibility is not backed by an eligible run.",
                entity_type="evidence",
                entity_id=record.evidence_id,
            )
        if record.validation_tags:
            replicated_run = None
            if run is not None and isinstance(
                run.metadata.get("replicates_run_id"), str
            ):
                replicated_run = run_by_id.get(run.metadata["replicates_run_id"])
            method_maximum_inference_level = None
            if run is not None:
                handoff = run.metadata.get("execution_handoff")
                result = handoff.get("result") if isinstance(handoff, dict) else None
                if isinstance(result, dict) and isinstance(
                    result.get("maximum_inference_level"), str
                ):
                    method_maximum_inference_level = result["maximum_inference_level"]
            try:
                validate_validation_tag_context(
                    tags=record.validation_tags,
                    direction=record.direction,
                    hypothesis=hypothesis,
                    exploratory=record.exploratory,
                    protocol=protocol,
                    run=run,
                    datasets=record_datasets,
                    controls_passed=record.controls_passed,
                    replicated_run=replicated_run,
                    claim=(claims_by_id.get(record.claim_id) if record.claim_id else None),
                    method_maximum_inference_level=method_maximum_inference_level,
                )
            except ResearchMachineError as exc:
                add(
                    "VALIDATION_TAG_UNSUPPORTED",
                    RigorSeverity.ERROR,
                    str(exc),
                    entity_type="evidence",
                    entity_id=record.evidence_id,
                    remediation="Remove the overclaim by creating a new correctly classified result; never rewrite evidence.",
                )
            else:
                tag_counts.update(tag.value for tag in record.validation_tags)
                retrospective_protocol = bool(
                    protocol is not None
                    and protocol.supersedes_protocol_id is not None
                    and (
                        protocol.amendment_timing in {"after_collection", "after_analysis", "unknown"}
                        or protocol.evidence_exposure in {"aggregate_seen", "full_data_seen", "unknown"}
                    )
                )
                if retrospective_protocol:
                    add(
                        "EVIDENCE_FROM_RETROSPECTIVE_OR_EXPOSED_AMENDMENT",
                        RigorSeverity.WARNING,
                        "Evidence uses a retrospective, exposed, or uncertain protocol amendment and cannot raise prospective maturity.",
                        entity_type="evidence", entity_id=record.evidence_id,
                        remediation="Seek a new frozen prospective protocol and independent data; retain this result as amended evidence.",
                    )
                else:
                    prospective_tag_counts.update(tag.value for tag in record.validation_tags)

    runs_by_protocol: Counter[str] = Counter(run.protocol_id for run in runs)
    for protocol in protocols:
        if protocol.supersedes_protocol_id is not None:
            retrospective = (protocol.amendment_timing in {"after_collection", "after_analysis", "unknown"}
                             or protocol.evidence_exposure in {"aggregate_seen", "full_data_seen", "unknown"})
            add(
                "RETROSPECTIVE_OR_EXPOSED_PROTOCOL_AMENDMENT" if retrospective else "PROSPECTIVE_PROTOCOL_AMENDMENT_DISCLOSED",
                RigorSeverity.WARNING if retrospective else RigorSeverity.INFO,
                ("Protocol amendment occurred after collection/results or has uncertain timing/exposure; it cannot be treated as a prospective commitment."
                 if retrospective else "Protocol amendment is declared before collection with no evidence exposure."),
                entity_type="protocol", entity_id=protocol.protocol_id,
                remediation=("Interpret affected analyses as amended or exploratory and retain the superseded protocol."
                             if retrospective else "Freeze the new version before collection and retain the superseded protocol."),
            )
        if protocol.status is not ProtocolStatus.FROZEN:
            continue
        if not protocol.quality_requirements:
            add(
                "FROZEN_PROTOCOL_WITHOUT_QUALITY_GATES",
                RigorSeverity.ERROR,
                "Frozen protocol has no required quality gates.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
            )
        if not protocol.controls:
            add(
                "FROZEN_PROTOCOL_WITHOUT_CONTROLS",
                RigorSeverity.WARNING,
                "Frozen protocol has no comparator or negative control.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
            )
        if _protected_empirical(protocol):
            if protocol.controls and not protocol.control_definitions:
                add(
                    "PROTECTED_PROTOCOL_CONTROLS_UNSTRUCTURED",
                    RigorSeverity.WARNING,
                    "Protected empirical protocol names controls but lacks structured control definitions.",
                    entity_type="protocol",
                    entity_id=protocol.protocol_id,
                    remediation=(
                        "Treat legacy controls as prose commitments only; they do not "
                        "establish family, expected-behavior, or gate-binding coverage."
                    ),
                )
            if protocol.control_definitions:
                control_families = {
                    control.family for control in protocol.control_definitions
                }
                if "positive" not in control_families:
                    add(
                        "PROTECTED_PROTOCOL_WITHOUT_POSITIVE_CONTROL",
                        RigorSeverity.WARNING,
                        "Protected empirical protocol has no structured positive control.",
                        entity_type="protocol",
                        entity_id=protocol.protocol_id,
                        remediation=(
                            "Treat measurement sensitivity as unproven by controls; "
                            "freeze a future protocol with a known-effect positive control "
                            "or an explicit justification."
                        ),
                    )
                if not control_families.intersection(_FALSIFYING_CONTROL_FAMILIES):
                    add(
                        "PROTECTED_PROTOCOL_WITHOUT_FALSIFYING_CONTROL",
                        RigorSeverity.WARNING,
                        "Protected empirical protocol has no negative, sham, replay, random-time, adversarial, or apparatus-only control family.",
                        entity_type="protocol",
                        entity_id=protocol.protocol_id,
                        remediation=(
                            "Treat favorable direction as weak against mundane alternatives; "
                            "freeze a future protocol with a falsifying control family."
                        ),
                    )
                if runs_by_protocol[protocol.protocol_id] > 0:
                    expected_control_ids = {
                        control.control_id for control in protocol.control_definitions
                    }
                    missing_control_ids = sorted(
                        expected_control_ids
                        - _reported_control_result_ids(protocol, runs)
                    )
                    if missing_control_ids:
                        add(
                            "PROTECTED_EMPIRICAL_CONTROL_RESULTS_UNASSESSED",
                            RigorSeverity.WARNING,
                            "Protected empirical protocol has frozen structured controls, but recorded runs do not expose structured results for every control.",
                            entity_type="protocol",
                            entity_id=protocol.protocol_id,
                            remediation=(
                                "Record artifact-bound control_results for "
                                + ", ".join(missing_control_ids)
                                + "; do not infer control passage from expected behavior, gate labels, or favorable analysis output."
                            ),
                        )
        factor_state = _factor_interpretability_state(protocol)
        if factor_state == "invalid":
            add(
                "PROTOCOL_FACTOR_INTERPRETABILITY_UNRESOLVED",
                RigorSeverity.ERROR,
                "Frozen protocol has unresolved manipulated-factor interpretability commitments.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "Do not interpret simultaneous factor changes as separable effects; "
                    "freeze a new prospective factorial or crossover protocol with a "
                    "factor-interpretability plan before drawing factor-specific conclusions."
                ),
            )
        elif factor_state == "planned_multi_factor":
            add(
                "PROTOCOL_FACTOR_INTERPRETABILITY_DECLARED",
                RigorSeverity.INFO,
                "Frozen protocol declares a multi-factor intervention with a prospective factor-interpretability plan.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "Report the plan as provenance only; it does not prove that observed effects are separable by factor."
                ),
            )
        elif factor_state == "single_factor":
            add(
                "PROTOCOL_MANIPULATED_FACTOR_DECLARED",
                RigorSeverity.INFO,
                "Frozen protocol declares one manipulated factor.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "Keep factor-specific interpretation scoped to the frozen protocol and observed controls."
                ),
            )
        if protocol.control_windows and not protocol.clock_accuracy_requirement.strip():
            add(
                "PROTOCOL_CONTROL_WINDOWS_WITHOUT_CLOCK_ACCURACY",
                RigorSeverity.ERROR,
                "Frozen protocol declares temporal control windows without a clock-accuracy or synchronization commitment.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "Do not interpret timing-window comparisons as prospectively bounded; "
                    "freeze a new protocol version with an explicit timing-accuracy "
                    "requirement before protected data collection."
                ),
            )
        elif (
            protocol.sensor_requirements
            or protocol.clock_accuracy_requirement.strip()
            or protocol.control_windows
        ):
            add(
                "PROTOCOL_ACQUISITION_TIMING_DECLARED",
                RigorSeverity.INFO,
                "Frozen protocol declares acquisition or timing commitments.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "Report these as prospective design provenance only; they do not "
                    "prove sensor custody, calibration, synchronization, or clock accuracy."
                ),
            )
        if protocol.canary_target_plan is not None:
            add(
                "PROTOCOL_CANARY_TARGET_PLAN_DECLARED",
                RigorSeverity.INFO,
                "Frozen protocol declares a masked canary-target plan with a hash-bound assignment artifact.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "Treat the canary plan as prospective adversarial-design provenance; "
                    "it does not establish adaptation, mechanism, attribution, or intent."
                ),
            )
        if protocol.hypothesis_reactivity_plan is not None:
            plan = protocol.hypothesis_reactivity_plan
            distinguishable = [
                model.model_id
                for model in plan.process_models
                if model.distinguishability == "distinguishable"
            ]
            add(
                "PROTOCOL_HYPOTHESIS_REACTIVITY_PLAN_DECLARED",
                RigorSeverity.INFO,
                "Frozen protocol declares a hypothesis-disclosure reactivity plan with competing process models.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "Treat disclosure schedule and process models as prospective design "
                    "provenance. Observation, model compatibility, and decision loss remain "
                    "separate; non-distinguishable models are not independently supported."
                ),
            )
            if not distinguishable:
                add(
                    "PROTOCOL_HYPOTHESIS_REACTIVITY_NO_DISTINGUISHABLE_MODEL",
                    RigorSeverity.WARNING,
                    "Hypothesis-reactivity plan marks every process model as not distinguishable by this design.",
                    entity_type="protocol",
                    entity_id=protocol.protocol_id,
                    remediation=(
                        "Report design non-discrimination explicitly. Do not treat quiet "
                        "results or catch-all concealment as support for an unobserved "
                        "explanation."
                    ),
                )
        if (
            protocol.analysis_mode
            in {AnalysisMode.CONFIRMATORY, AnalysisMode.REPLICATION}
            and protocol.protocol_kind is ProtocolKind.COMPUTATIONAL
            and not protocol.measurement_definitions
        ):
            add(
                "PROTECTED_COMPUTATIONAL_MEASUREMENTS_UNTYPED",
                RigorSeverity.WARNING,
                "This protected computational protocol has no typed measurement "
                "contract, so parameter and evaluation-point completeness is not "
                "machine-verifiable.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "Use measurement_definitions in the next protocol version; do "
                    "not retroactively certify or rewrite the frozen protocol."
                ),
            )
        if not protocol.sample_size_or_stopping_rule.strip():
            add(
                "FROZEN_PROTOCOL_WITHOUT_STOP_RULE",
                RigorSeverity.WARNING,
                "Frozen protocol has no explicit sample-size or stopping rule.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation="Require a stopping rule in the next protocol version.",
            )
        if (
            _protected_empirical(protocol)
            and protocol.measurement_definitions
            and not protocol.measurement_validity_checks
        ):
            add(
                "PROTECTED_EMPIRICAL_VALIDITY_PLAN_UNTYPED",
                RigorSeverity.WARNING,
                "Protected empirical protocol has typed measurements but no canonical prospective measurement-validity checks.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "In the next prospective protocol version, bind structured validity claims, acceptance criteria, failure responses, and dedicated gates; do not retroactively rewrite this frozen protocol."
                ),
            )
        if (
            _protected_empirical(protocol)
            and protocol.measurement_validity_checks
            and runs_by_protocol[protocol.protocol_id] > 0
        ):
            expected_validity_check_ids = {
                check.check_id for check in protocol.measurement_validity_checks
            }
            missing_validity_check_ids = sorted(
                expected_validity_check_ids
                - _reported_measurement_validity_check_ids(protocol, runs)
            )
            if missing_validity_check_ids:
                add(
                    "PROTECTED_EMPIRICAL_VALIDITY_RESULTS_UNASSESSED",
                    RigorSeverity.WARNING,
                    "Protected empirical protocol has frozen measurement-validity checks, but recorded runs do not expose structured results for every check.",
                    entity_type="protocol",
                    entity_id=protocol.protocol_id,
                    remediation=(
                        "Record artifact-bound measurement-validity results for "
                        + ", ".join(missing_validity_check_ids)
                        + "; do not infer validity from the prospective plan or favorable analysis output."
                    ),
                )
        missingness_gate_id = (
            protocol.analysis_contract.missingness_assessment_gate_id
            if protocol.analysis_contract is not None else ""
        )
        if (
            _protected_empirical(protocol)
            and missingness_gate_id
            and runs_by_protocol[protocol.protocol_id] > 0
            and not any(
                _has_structured_gate_detail_for_gate_ids(
                    run,
                    "missingness_assessment_result",
                    {missingness_gate_id},
                )
                for run in runs
                if run.protocol_id == protocol.protocol_id
            )
        ):
            add(
                "PROTECTED_EMPIRICAL_MISSINGNESS_ASSESSMENT_UNASSESSED",
                RigorSeverity.WARNING,
                "Protected empirical protocol has a frozen missingness-assessment gate, but recorded runs expose no structured missingness assessment for that gate.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "In the next run, attach an artifact-bound missingness assessment to the frozen gate; do not infer ignorable missingness from the prospective plan, complete-case execution, or favorable results."
                ),
            )
        if _protected_empirical(protocol) and not protocol.sample_size_plan:
            add(
                "PROTECTED_EMPIRICAL_SAMPLE_SIZE_PLAN_UNVERIFIED",
                RigorSeverity.WARNING,
                "Protected empirical protocol has a prose stopping rule but no machine-recomputed precision or power receipt.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "In the next protocol version, bind a reviewed sample_size_plan or document why this design requires a different typed planning method."
                ),
            )
        if (
            _protected_empirical(protocol)
            and protocol.preprocessing_pipeline.strip()
            and runs_by_protocol[protocol.protocol_id] > 0
            and not any(
                _has_preprocessing_conformance_gate(run)
                for run in runs
                if run.protocol_id == protocol.protocol_id
            )
        ):
            add(
                "PROTECTED_EMPIRICAL_PREPROCESSING_CONFORMANCE_UNASSESSED",
                RigorSeverity.WARNING,
                "Protected empirical protocol has a frozen preprocessing commitment, but recorded runs expose no structured preprocessing-conformance gate.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "In the next run, attach a byte-verified preprocessing-conformance record to a quality gate; do not infer adherence from an analysis summary."
                ),
            )
        if (
            _protected_empirical(protocol)
            and protocol.sensor_requirements
            and runs_by_protocol[protocol.protocol_id] > 0
            and not any(
                _has_structured_gate_detail(run, "instrument_inspection")
                for run in runs
                if run.protocol_id == protocol.protocol_id
            )
        ):
            add(
                "PROTECTED_EMPIRICAL_ACQUISITION_INSPECTION_UNASSESSED",
                RigorSeverity.WARNING,
                "Protected empirical protocol declares required sensors or streams, but recorded runs expose no structured instrument-inspection gate.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "In the next run, attach a byte-verified instrument-inspection record to a quality gate; do not infer acquisition coverage from an analysis summary."
                ),
            )
        if (
            _protected_empirical(protocol)
            and (
                protocol.clock_accuracy_requirement.strip()
                or protocol.control_windows
            )
            and runs_by_protocol[protocol.protocol_id] > 0
            and not any(
                _has_structured_gate_detail(run, "stream_timing_assessment")
                for run in runs
                if run.protocol_id == protocol.protocol_id
            )
        ):
            add(
                "PROTECTED_EMPIRICAL_STREAM_TIMING_UNASSESSED",
                RigorSeverity.WARNING,
                "Protected empirical protocol declares clock or temporal-window commitments, but recorded runs expose no structured stream-timing assessment gate.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "In the next run, attach a byte-verified stream-timing assessment to a quality gate; do not infer timing feasibility from declared windows or favorable results."
                ),
            )
        temporal_order_gate_ids = _causal_temporal_order_gate_ids(protocol)
        assumption_register = (
            protocol.causal_identification_audit.get("assumption_register", [])
            if protocol.causal_claim
            and isinstance(protocol.causal_identification_audit, dict)
            else []
        )
        expected_causal_assumption_categories = {
            item["category"]
            for item in assumption_register
            if isinstance(item, dict)
            and isinstance(item.get("category"), str)
            and item["category"]
        }
        if (
            _protected_empirical(protocol)
            and expected_causal_assumption_categories
            and runs_by_protocol[protocol.protocol_id] > 0
        ):
            missing_causal_categories = sorted(
                expected_causal_assumption_categories
                - _reported_causal_assumption_categories(protocol, runs)
            )
            if missing_causal_categories:
                add(
                    "PROTECTED_CAUSAL_ASSUMPTIONS_UNASSESSED",
                    RigorSeverity.WARNING,
                    "Protected causal protocol has frozen causal-assumption assessment gates, but recorded runs do not expose structured results for every assumption category.",
                    entity_type="protocol",
                    entity_id=protocol.protocol_id,
                    remediation=(
                        "Record artifact-bound causal_assumption_results for "
                        + ", ".join(missing_causal_categories)
                        + "; do not infer exchangeability, temporality, positivity, consistency, measurement validity, or selection validity from the DAG, design prose, gate labels, or favorable results."
                    ),
                )
        if (
            _protected_empirical(protocol)
            and temporal_order_gate_ids
            and runs_by_protocol[protocol.protocol_id] > 0
            and not any(
                _has_structured_gate_detail_for_gate_ids(
                    run,
                    "temporal_order_assessment",
                    temporal_order_gate_ids,
                )
                for run in runs
                if run.protocol_id == protocol.protocol_id
            )
        ):
            add(
                "PROTECTED_CAUSAL_TEMPORAL_ORDER_UNASSESSED",
                RigorSeverity.WARNING,
                "Protected causal protocol has a frozen temporal-order assessment gate, but recorded runs expose no structured temporal-order assessment for that gate.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "In the next run, attach a byte-verified temporal-order assessment to the registered causal temporal-order gate; do not infer causal direction from timing prose, assumptions, or favorable results."
                ),
            )
        canary_plan = protocol.canary_target_plan
        if (
            _protected_empirical(protocol)
            and canary_plan is not None
            and runs_by_protocol[protocol.protocol_id] > 0
            and not any(
                _has_structured_gate_detail_for_gate_ids(
                    run,
                    "canary_target_assessment",
                    {canary_plan.assessment_gate_id},
                )
                for run in runs
                if run.protocol_id == protocol.protocol_id
            )
        ):
            add(
                "PROTECTED_EMPIRICAL_CANARY_TARGET_UNASSESSED",
                RigorSeverity.WARNING,
                "Protected empirical protocol has a frozen canary-target assessment gate, but recorded runs expose no structured canary-target assessment for that gate.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "In the next run, attach the canary-target assessment to the frozen canary gate; do not infer target-following, adaptation, mechanism, attribution, or intent from the masked plan alone."
                ),
            )
        reactivity_plan = protocol.hypothesis_reactivity_plan
        if (
            _protected_empirical(protocol)
            and reactivity_plan is not None
            and runs_by_protocol[protocol.protocol_id] > 0
            and not any(
                _has_structured_gate_detail_for_gate_ids(
                    run,
                    "hypothesis_reactivity_assessment",
                    {reactivity_plan.assessment_gate_id},
                )
                for run in runs
                if run.protocol_id == protocol.protocol_id
            )
        ):
            add(
                "PROTECTED_EMPIRICAL_HYPOTHESIS_REACTIVITY_UNASSESSED",
                RigorSeverity.WARNING,
                "Protected empirical protocol has a frozen hypothesis-reactivity assessment gate, but recorded runs expose no structured hypothesis-reactivity assessment for that gate.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation=(
                    "In the next run, attach the reactivity assessment to the frozen gate; "
                    "do not infer detection, adaptation, or intent from the disclosure "
                    "schedule alone, and do not treat non-distinguishable models as supported."
                ),
            )
        if runs_by_protocol[protocol.protocol_id] == 0:
            add(
                "FROZEN_PROTOCOL_NOT_EXECUTED",
                RigorSeverity.INFO,
                "Frozen protocol has no recorded run.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
            )

    invalid_runs = 0
    for run in runs:
        disclosure = run.metadata.get("protocol_deviation_disclosure")
        if not isinstance(disclosure, dict) or disclosure.get("status") == "legacy_not_declared":
            add(
                "RUN_PROTOCOL_DEVIATIONS_UNDECLARED",
                RigorSeverity.WARNING,
                "Run has no explicit protocol-deviation declaration and cannot be treated as evidence-eligible.",
                entity_type="run",
                entity_id=run.run_id,
                remediation="Record a new run with an explicit disclosure; never rewrite this historical run.",
            )
        elif disclosure.get("status") == "deviations_declared":
            deviations = disclosure.get("deviations", [])
            add(
                "RUN_PROTOCOL_DEVIATIONS_DECLARED",
                RigorSeverity.WARNING,
                f"Run declares {len(deviations) if isinstance(deviations, list) else 0} departure(s) from its frozen protocol and requires separate scientific review.",
                entity_type="run",
                entity_id=run.run_id,
                remediation="Inspect every departure and its output-bound evidence; do not automatically promote this run to evidence.",
            )
        exposure_disclosure = run.metadata.get("result_exposure_disclosure")
        if (
            not isinstance(exposure_disclosure, dict)
            or exposure_disclosure.get("status") == "legacy_not_declared"
        ):
            add(
                "RUN_RESULT_EXPOSURE_UNDECLARED",
                RigorSeverity.WARNING,
                "Run predates or omits the typed result-exposure disclosure; absence does not establish that relevant output was unseen before registration.",
                entity_type="run",
                entity_id=run.run_id,
                remediation="For future runs, declare result_exposure_disclosure and preserve exact exposure references; do not rewrite this historical run.",
            )
        elif exposure_disclosure.get("status") in {
            "favorable_output_seen", "full_output_seen", "unknown",
        }:
            add(
                "RUN_RESULT_PREEXPOSED_OR_UNKNOWN",
                RigorSeverity.WARNING,
                "Run declares favorable, full, or unknown pre-registration result exposure and cannot be automatically evidence-eligible.",
                entity_type="run",
                entity_id=run.run_id,
                remediation="Treat the run as exposed development and use only a future independent or prospectively protected lineage for stronger evidence.",
            )
        if (
            run.scientific_evidence_eligible
            and declares_legacy_pre_registration_result_exposure(run.metadata)
        ):
            add(
                "RUN_ELIGIBILITY_CONFLICTS_WITH_DECLARED_PREEXPOSURE",
                RigorSeverity.WARNING,
                "Legacy structured run metadata says favorable development or prototype output was seen before registration while the stored automatic eligibility bit is true; effective evidence eligibility is quarantined.",
                entity_type="run",
                entity_id=run.run_id,
                remediation="Do not admit this immutable run as scientific evidence; use the typed result-exposure disclosure in a future run lineage.",
            )
        protocol = protocol_by_id.get(run.protocol_id)
        for gate in run.quality_gates:
            instrument_inspection = gate.details.get("instrument_inspection")
            if isinstance(instrument_inspection, dict):
                record_status = instrument_inspection.get("status")
                if record_status == "inspection_recorded":
                    add(
                        "RUN_INSTRUMENT_INSPECTION_REPLAYED",
                        RigorSeverity.INFO,
                        "Run exposes an artifact-bound instrument-inspection record "
                        f"({instrument_inspection.get('stream_count', 'unknown')} proposed streams; "
                        "temporal metadata status "
                        f"{instrument_inspection.get('temporal_metadata_status', 'unknown')}). "
                        "The retained inspection is low-authority acquisition metadata, not calibration, custody, or evidence approval.",
                        entity_type="run",
                        entity_id=run.run_id,
                    )
            conformance = gate.details.get("preprocessing_conformance")
            if isinstance(conformance, dict):
                record_status = conformance.get("status")
                if record_status == "preprocessing_conformance_failed":
                    add(
                        "RUN_PREPROCESSING_CONFORMANCE_FAILED",
                        RigorSeverity.ERROR,
                        "Run retains a failed preprocessing-conformance record; the discrepancy must stay visible and cannot support a passed preprocessing gate.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Inspect the conformance artifact, preserve the failed gate outcome, and bound or repeat the analysis before drawing conclusions."
                        ),
                    )
                elif record_status == "preprocessing_conformance_passed":
                    add(
                        "RUN_PREPROCESSING_CONFORMANCE_REPLAYED",
                        RigorSeverity.INFO,
                        "Run exposes an artifact-bound preprocessing-conformance gate; the pass is a bounded adherence check, not proof of implementation correctness.",
                        entity_type="run",
                        entity_id=run.run_id,
                    )
            stream_timing = gate.details.get("stream_timing_assessment")
            if isinstance(stream_timing, dict):
                record_status = stream_timing.get("status")
                if record_status == "timing_feasibility_failed":
                    add(
                        "RUN_STREAM_TIMING_ASSESSMENT_FAILED",
                        RigorSeverity.ERROR,
                        "Run retains a failed stream-timing assessment "
                        f"({stream_timing.get('required_stream_failure_count', 'unknown')} stream failures of "
                        f"{stream_timing.get('required_stream_count', 'unknown')} required streams; "
                        f"{stream_timing.get('event_failure_count', 'unknown')} event failures of "
                        f"{stream_timing.get('event_count', 'unknown')} events). "
                        "Event-timing interpretation must stay bounded.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Inspect the stream-timing artifact, preserve the failed gate outcome, and do not infer event timing from unsupported stream metadata."
                        ),
                    )
                elif record_status == "timing_feasibility_passed":
                    add(
                        "RUN_STREAM_TIMING_ASSESSMENT_REPLAYED",
                        RigorSeverity.INFO,
                        "Run exposes an artifact-bound stream-timing assessment "
                        f"({stream_timing.get('required_stream_count', 'unknown')} required streams; "
                        f"{stream_timing.get('event_count', 'unknown')} events). "
                        "The pass is a feasibility check, not acquisition or calibration proof.",
                        entity_type="run",
                        entity_id=run.run_id,
                    )
            temporal_order = gate.details.get("temporal_order_assessment")
            if isinstance(temporal_order, dict):
                record_status = temporal_order.get("status")
                if record_status == "temporal_order_failed":
                    add(
                        "RUN_TEMPORAL_ORDER_ASSESSMENT_FAILED",
                        RigorSeverity.ERROR,
                        "Run retains a failed temporal-order assessment "
                        f"({temporal_order.get('failed_check_count', 'unknown')} failed of "
                        f"{temporal_order.get('check_count', 'unknown')} registered checks; "
                        f"{temporal_order.get('warning_check_count', 'unknown')} warnings). "
                        "Causal direction or event-order interpretation must stay bounded.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Inspect the temporal-order artifact, preserve the failed gate outcome, and do not infer causal direction from the affected run."
                        ),
                    )
                elif record_status == "temporal_order_passed":
                    add(
                        "RUN_TEMPORAL_ORDER_ASSESSMENT_REPLAYED",
                        RigorSeverity.INFO,
                        "Run exposes an artifact-bound temporal-order assessment "
                        f"({temporal_order.get('check_count', 'unknown')} registered checks; "
                        f"{temporal_order.get('warning_check_count', 'unknown')} warnings). "
                        "The pass classifies order under timing uncertainty and does not prove causality.",
                        entity_type="run",
                        entity_id=run.run_id,
                    )
            reactivity = gate.details.get("hypothesis_reactivity_assessment")
            if isinstance(reactivity, dict):
                reactivity_status = reactivity.get("assessment_status")
                if reactivity_status == "models_discriminated":
                    add(
                        "RUN_HYPOTHESIS_REACTIVITY_MODELS_DISCRIMINATED",
                        RigorSeverity.INFO,
                        "Run reactivity assessment reported discrimination among frozen distinguishable process models under the registered likelihood comparison.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Keep the result bounded to the frozen model set. Do not promote "
                            "it to adaptation, detection, or intent."
                        ),
                    )
                elif reactivity_status == "compatible_with_multiple":
                    add(
                        "RUN_HYPOTHESIS_REACTIVITY_COMPATIBLE_WITH_MULTIPLE",
                        RigorSeverity.WARNING,
                        "Run reactivity assessment left multiple frozen process models compatible under the registered likelihood comparison.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Report non-discrimination for this contrast. Do not treat a quiet "
                            "result as safety or as support for an unobserved explanation."
                        ),
                    )
                elif reactivity_status == "not_distinguishable_by_design":
                    add(
                        "RUN_HYPOTHESIS_REACTIVITY_NOT_DISTINGUISHABLE",
                        RigorSeverity.WARNING,
                        "Run reactivity assessment reported that the design cannot distinguish the relevant process models.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Mark catch-all concealment as not distinguishable by this design; "
                            "do not treat it as an independently supported explanation."
                        ),
                    )
                elif reactivity_status == "inconclusive":
                    add(
                        "RUN_HYPOTHESIS_REACTIVITY_INCONCLUSIVE",
                        RigorSeverity.WARNING,
                        "Run reactivity assessment remained inconclusive under the frozen disclosure and process-model plan.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Disclose the inconclusive result and avoid detection, adaptation, or intent claims."
                        ),
                    )
            canary = gate.details.get("canary_target_assessment")
            if not isinstance(canary, dict):
                continue
            canary_status = canary.get("assessment_status")
            if canary_status == "follows_comparator_or_decoy":
                add(
                    "RUN_CANARY_TARGET_FOLLOWED_COMPARATOR",
                    RigorSeverity.WARNING,
                    "Run canary assessment reported a pattern following a comparator or decoy rather than the revealed target.",
                    entity_type="run",
                    entity_id=run.run_id,
                    remediation=(
                        "Preserve the comparator-following result as disconfirming or ambiguity evidence; do not relabel it as support for adaptation."
                    ),
                )
            elif canary_status == "follows_no_target":
                add(
                    "RUN_CANARY_TARGET_FOLLOWED_NO_TARGET",
                    RigorSeverity.WARNING,
                    "Run canary assessment reported that the pattern followed no registered target.",
                    entity_type="run",
                    entity_id=run.run_id,
                    remediation=(
                        "Preserve the no-target result as disconfirming or ambiguity evidence; do not relabel it as target-specific support."
                    ),
                )
            elif canary_status in {"mixed", "inconclusive"}:
                add(
                    "RUN_CANARY_TARGET_ASSESSMENT_AMBIGUOUS",
                    RigorSeverity.WARNING,
                    "Run canary assessment reported mixed or inconclusive target-following.",
                    entity_type="run",
                    entity_id=run.run_id,
                    remediation=(
                        "Disclose the ambiguous canary result and avoid source, mechanism, or intent claims."
                    ),
                )
            elif canary_status == "consistent_with_revealed_target":
                add(
                    "RUN_CANARY_TARGET_ASSESSMENT_RETAINED",
                    RigorSeverity.INFO,
                    "Run exposes an artifact-bound canary target assessment; the result remains bounded design evidence, not proof of adaptation or intent.",
                    entity_type="run",
                    entity_id=run.run_id,
                )
        if protocol is not None and protocol.measurement_validity_checks:
            gates_by_id = {item.gate_id: item for item in run.quality_gates}
            for check in protocol.measurement_validity_checks:
                gate = gates_by_id.get(check.assessment_gate_id)
                results = (
                    gate.details.get("measurement_validity_results", {})
                    if gate is not None else {}
                )
                result = results.get(check.check_id) if isinstance(results, dict) else None
                if not isinstance(result, dict):
                    continue
                status = result.get("assessment_status")
                if status == "inconclusive":
                    add(
                        "MEASUREMENT_VALIDITY_INCONCLUSIVE",
                        RigorSeverity.WARNING,
                        f"Measurement validity check {check.check_id} was inconclusive; the run cannot support an unqualified measurement-validity claim.",
                        entity_type="run", entity_id=run.run_id,
                        remediation=check.failure_response,
                    )
                elif status == "contradicted_validity_claim":
                    add(
                        "MEASUREMENT_VALIDITY_CONTRADICTED",
                        RigorSeverity.ERROR,
                        f"Measurement validity check {check.check_id} contradicted its frozen validity claim.",
                        entity_type="run", entity_id=run.run_id,
                        remediation=check.failure_response,
                    )
        if protocol is not None and any(
            control.witness_contract is not None
            for control in protocol.control_definitions
        ):
            gates_by_id = {item.gate_id: item for item in run.quality_gates}
            for control in protocol.control_definitions:
                if control.witness_contract is None:
                    continue
                gate = gates_by_id.get(control.evaluation_gate_id)
                results = (
                    gate.details.get("control_results", {})
                    if gate is not None else {}
                )
                result = (
                    results.get(control.control_id)
                    if isinstance(results, dict) else None
                )
                witness = result.get("witness") if isinstance(result, dict) else None
                if not isinstance(witness, dict):
                    add(
                        "CONTROL_WITNESS_UNASSESSED",
                        RigorSeverity.WARNING,
                        f"Control {control.control_id} has a prospective scalar witness contract but this run does not expose its structured witness.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the run as incomplete or invalid; execute a new preregistered run with the exact artifact-selected scalar witness."
                        ),
                    )
                elif witness.get("decision") is False:
                    add(
                        "CONTROL_WITNESS_ADVERSE",
                        RigorSeverity.WARNING,
                        f"Control {control.control_id} has an artifact-bound scalar witness whose frozen comparison was false.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve and disclose the adverse control result; do not treat execution quality as scientific support."
                        ),
                    )
        if protocol is not None and protocol.named_component_contracts:
            gates_by_id = {item.gate_id: item for item in run.quality_gates}
            for contract in protocol.named_component_contracts:
                gate = gates_by_id.get(contract.evaluation_gate_id)
                results = (
                    gate.details.get("named_component_results", {})
                    if gate is not None else {}
                )
                result = (
                    results.get(contract.contract_id)
                    if isinstance(results, dict) else None
                )
                if not isinstance(result, dict):
                    continue
                status = result.get("assessment_status")
                if status == "inconclusive":
                    add(
                        "NAMED_COMPONENT_SELECTION_INCONCLUSIVE",
                        RigorSeverity.WARNING,
                        f"Named-component contract {contract.contract_id} was inconclusive under its frozen relabeling.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Inspect the retained mapping evidence; do not treat positional and name-addressed selections as equivalent."
                        ),
                    )
                elif status == "contradicted_named_selection":
                    add(
                        "NAMED_COMPONENT_SELECTION_CONTRADICTED",
                        RigorSeverity.ERROR,
                        f"Named-component contract {contract.contract_id} selected different names after the frozen relabeling.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the failure, replace positional slicing with explicit name lookup, and preregister a new protocol before retesting."
                        ),
                    )
        if protocol is not None and protocol.mathematical_predicate_contracts:
            gates_by_id = {item.gate_id: item for item in run.quality_gates}
            for contract in protocol.mathematical_predicate_contracts:
                gate = gates_by_id.get(contract.evaluation_gate_id)
                results = (
                    gate.details.get("mathematical_predicate_results", {})
                    if gate is not None else {}
                )
                result = (
                    results.get(contract.contract_id)
                    if isinstance(results, dict) else None
                )
                if not isinstance(result, dict):
                    continue
                status = result.get("assessment_status")
                if status == "inconclusive":
                    add(
                        "MATHEMATICAL_PREDICATE_INCONCLUSIVE",
                        RigorSeverity.WARNING,
                        f"Mathematical predicate contract {contract.contract_id} "
                        f"for object {contract.object_id} was inconclusive.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the typed result and inspect its retained "
                            "witness without transferring the predicate to a "
                            "source, quotient, or comparator object."
                        ),
                    )
                elif status == "contradicted_predicate":
                    add(
                        "MATHEMATICAL_PREDICATE_CONTRADICTED",
                        RigorSeverity.WARNING,
                        f"Mathematical predicate contract {contract.contract_id} "
                        f"for object {contract.object_id} was contradicted.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the adverse result at the frozen object, "
                            "domain, codomain, and quotient; any repair requires "
                            "a new protocol version."
                        ),
                    )
        if protocol is not None and protocol.duality_reconstruction_contracts:
            gates_by_id = {item.gate_id: item for item in run.quality_gates}
            for contract in protocol.duality_reconstruction_contracts:
                gate = gates_by_id.get(contract.evaluation_gate_id)
                results = (
                    gate.details.get("duality_reconstruction_results", {})
                    if gate is not None else {}
                )
                result = (
                    results.get(contract.contract_id)
                    if isinstance(results, dict) else None
                )
                if not isinstance(result, dict):
                    continue
                status = result.get("assessment_status")
                if status == "inconclusive":
                    add(
                        "DUALITY_RECONSTRUCTION_INCONCLUSIVE",
                        RigorSeverity.WARNING,
                        f"Duality reconstruction contract {contract.contract_id} "
                        "was inconclusive.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the typed result and inspect the pairing, "
                            "basis, quadrature, transfer, and dependency closure; "
                            "do not infer a strong representative."
                        ),
                    )
        if (
            protocol is not None
            and protocol.reconstruction_family_stability_contracts
        ):
            gates_by_id = {item.gate_id: item for item in run.quality_gates}
            for contract in protocol.reconstruction_family_stability_contracts:
                gate = gates_by_id.get(contract.evaluation_gate_id)
                results = (
                    gate.details.get(
                        "reconstruction_family_stability_results", {}
                    )
                    if gate is not None
                    else {}
                )
                result = (
                    results.get(contract.contract_id)
                    if isinstance(results, dict)
                    else None
                )
                if not isinstance(result, dict):
                    continue
                status = result.get("assessment_status")
                if status == "inconclusive":
                    add(
                        "RECONSTRUCTION_FAMILY_STABILITY_INCONCLUSIVE",
                        RigorSeverity.WARNING,
                        f"Reconstruction family stability contract "
                        f"{contract.contract_id} was inconclusive.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the typed result and inspect the frozen "
                            "resolution family, norms, stability values, "
                            "cross-projections, and transfer maps."
                        ),
                    )
                elif status == "contradicted_family_stability_contract":
                    add(
                        "RECONSTRUCTION_FAMILY_STABILITY_CONTRADICTED",
                        RigorSeverity.ERROR,
                        f"Reconstruction family stability contract "
                        f"{contract.contract_id} was contradicted.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the adverse family result. Do not make a "
                            "cross-resolution or continuum inference; any new "
                            "norm, family, transfer, statistic, or threshold "
                            "requires a new protocol version."
                        ),
                    )
                elif status == "contradicted_reconstruction_contract":
                    add(
                        "DUALITY_RECONSTRUCTION_CONTRADICTED",
                        RigorSeverity.ERROR,
                        f"Duality reconstruction contract {contract.contract_id} "
                        "was contradicted.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the adverse result. Any replacement of the "
                            "pairing, reconstruction, basis, quadrature, transfer, "
                            "or dependency boundary requires a new protocol version."
                        ),
                    )
        if (
            protocol is not None
            and protocol.analysis_implementation_bundle_contracts
        ):
            gates_by_id = {item.gate_id: item for item in run.quality_gates}
            for contract in protocol.analysis_implementation_bundle_contracts:
                gate = gates_by_id.get(contract.evaluation_gate_id)
                results = (
                    gate.details.get(
                        "analysis_implementation_bundle_results", {}
                    )
                    if gate is not None
                    else {}
                )
                result = (
                    results.get(contract.contract_id)
                    if isinstance(results, dict)
                    else None
                )
                if not isinstance(result, dict):
                    continue
                status = result.get("assessment_status")
                if status == "inconclusive":
                    add(
                        "ANALYSIS_IMPLEMENTATION_BUNDLE_INCONCLUSIVE",
                        RigorSeverity.WARNING,
                        f"Analysis implementation bundle contract "
                        f"{contract.contract_id} was inconclusive.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the member inventory and inspect the "
                            "frozen closure method, observed receipt, external "
                            "dependency boundary, and declared limitations."
                        ),
                    )
                elif status == "contradicted_implementation_bundle_contract":
                    add(
                        "ANALYSIS_IMPLEMENTATION_BUNDLE_CONTRADICTED",
                        RigorSeverity.ERROR,
                        f"Analysis implementation bundle contract "
                        f"{contract.contract_id} was contradicted.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the closure failure. Do not treat the run "
                            "as implementation-reproducible; changed entrypoints, "
                            "members, hashes, or dependency boundaries require a "
                            "new protocol version."
                        ),
                    )
        if (
            protocol is not None
            and protocol.computation_route_separation_contracts
        ):
            gates_by_id = {item.gate_id: item for item in run.quality_gates}
            for contract in protocol.computation_route_separation_contracts:
                gate = gates_by_id.get(contract.evaluation_gate_id)
                results = (
                    gate.details.get("computation_route_separation_results", {})
                    if gate is not None
                    else {}
                )
                result = (
                    results.get(contract.contract_id)
                    if isinstance(results, dict)
                    else None
                )
                if not isinstance(result, dict):
                    continue
                status = result.get("assessment_status")
                if status == "inconclusive":
                    add(
                        "COMPUTATION_ROUTE_SEPARATION_INCONCLUSIVE",
                        RigorSeverity.WARNING,
                        f"Computation route separation contract "
                        f"{contract.contract_id} was inconclusive.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the typed receipt and inspect static and "
                            "runtime coverage, shared members, forbidden edges, "
                            "the adverse helper control, and declared limitations."
                        ),
                    )
                elif status == "contradicted_route_separation_contract":
                    add(
                        "COMPUTATION_ROUTE_SEPARATION_CONTRADICTED",
                        RigorSeverity.ERROR,
                        f"Computation route separation contract "
                        f"{contract.contract_id} was contradicted.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the shared-helper or cross-route dependency "
                            "failure. Do not describe the two calculations as "
                            "code-separated; changed routes, bundles, sharing, or "
                            "tracing methods require a new protocol version."
                        ),
                    )
        if protocol is not None and protocol.bounded_negative_search_contracts:
            gates_by_id = {item.gate_id: item for item in run.quality_gates}
            for contract in protocol.bounded_negative_search_contracts:
                gate = gates_by_id.get(contract.evaluation_gate_id)
                results = (
                    gate.details.get("bounded_negative_search_results", {})
                    if gate is not None
                    else {}
                )
                result = (
                    results.get(contract.contract_id)
                    if isinstance(results, dict)
                    else None
                )
                if not isinstance(result, dict):
                    continue
                status = result.get("assessment_status")
                if status == "inconclusive":
                    add(
                        "BOUNDED_NEGATIVE_SEARCH_INCONCLUSIVE",
                        RigorSeverity.WARNING,
                        f"Bounded negative search contract {contract.contract_id} "
                        "was inconclusive.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the record and inspect the frozen queries, "
                            "interfaces, stop rule, screening decisions, retained "
                            "source hashes, exclusions, and omission control."
                        ),
                    )
                elif status == "contradicted_bounded_search_contract":
                    add(
                        "BOUNDED_NEGATIVE_SEARCH_CONTRADICTED",
                        RigorSeverity.ERROR,
                        f"Bounded negative search contract {contract.contract_id} "
                        "was contradicted.",
                        entity_type="run",
                        entity_id=run.run_id,
                        remediation=(
                            "Preserve the adverse search result. Do not infer "
                            "absence; changed scope, queries, interfaces, dates, "
                            "screening, or stop rules require a new protocol version."
                        ),
                    )
        if (
            protocol is not None
            and protocol.sample_size_plan
            and run.metadata.get("sample_size_plan_check", {}).get("status")
            != "passed"
        ):
            add(
                "RUN_SAMPLE_SIZE_PLAN_NOT_EXECUTION_BOUND",
                RigorSeverity.WARNING,
                "Run did not verify that its analysis satisfied the protocol-bound sample-size plan and cannot be scientific evidence.",
                entity_type="run",
                entity_id=run.run_id,
                remediation=(
                    "Use a verified execution or workflow-adjudication receipt whose registered information check enforces the planned analyzable count per group."
                ),
            )
        if (
            protocol is not None
            and run.metadata.get("sample_size_plan_check", {}).get(
                "variance_assumption", {}
            ).get("status") == "exceeded_registered_tolerance"
        ):
            variance = run.metadata["sample_size_plan_check"][
                "variance_assumption"
            ]
            add(
                "RUN_VARIANCE_EXCEEDED_REGISTERED_TOLERANCE",
                RigorSeverity.WARNING,
                "Run remains potentially admissible, but observed variability exceeded the prospectively registered planning tolerance.",
                entity_type="run",
                entity_id=run.run_id,
                remediation=(
                    f"Report observed-to-assumed SD ratio {variance['observed_to_assumed_ratio']:.12g} "
                    f"against registered maximum {variance['maximum_registered_ratio']:.12g}; do not describe the variance assumption as satisfied."
                ),
            )
        if (
            protocol is not None
            and protocol.sample_size_plan.get("strategy") == "precision"
            and run.metadata.get("sample_size_plan_check", {}).get(
                "precision_achievement", {}
            ).get("status") == "not_met"
        ):
            precision = run.metadata["sample_size_plan_check"][
                "precision_achievement"
            ]
            add(
                "RUN_PRECISION_TARGET_NOT_MET",
                RigorSeverity.WARNING,
                "Run is admissible evidence, but its observed confidence interval did not meet the frozen precision target.",
                entity_type="run",
                entity_id=run.run_id,
                remediation=(
                    f"Report observed half-width {precision['observed_half_width']:.12g} "
                    f"against target {precision['target_half_width']:.12g}; do not describe the planned precision as achieved."
                ),
            )
        if (
            protocol is not None
            and run.metadata.get("sample_size_plan_check", {}).get(
                "attrition_achievement", {}
            ).get("status") == "exceeded_assumption"
        ):
            attrition = run.metadata["sample_size_plan_check"][
                "attrition_achievement"
            ]
            add(
                "RUN_ATTRITION_EXCEEDED_PLANNING_ASSUMPTION",
                RigorSeverity.WARNING,
                "Run remains potentially admissible, but observed exclusions exceeded the prospective attrition assumption.",
                entity_type="run",
                entity_id=run.run_id,
                remediation=(
                    f"Report observed excluded fraction {attrition['observed_excluded_fraction']:.12g} "
                    f"against anticipated {attrition['anticipated_attrition_fraction']:.12g}, including group-specific rates; do not describe attrition as within plan."
                ),
            )
        if protocol is not None and protocol.registration_timestamp:
            try:
                run_started = datetime.fromisoformat(
                    run.started_at.replace("Z", "+00:00")
                )
                registered = datetime.fromisoformat(
                    protocol.registration_timestamp.replace("Z", "+00:00")
                )
            except ValueError:
                add(
                    "PROTOCOL_RUN_CHRONOLOGY_INVALID",
                    RigorSeverity.ERROR,
                    "Protocol registration or run-start timestamp is not valid ISO-8601.",
                    entity_type="run",
                    entity_id=run.run_id,
                )
            else:
                if run_started.utcoffset() is None or registered.utcoffset() is None:
                    add(
                        "PROTOCOL_RUN_CHRONOLOGY_INVALID",
                        RigorSeverity.ERROR,
                        "Protocol registration and run-start timestamps must include a UTC offset.",
                        entity_type="run",
                        entity_id=run.run_id,
                    )
                else:
                    chronology = run.metadata.get("protocol_chronology")
                    external_receipt = (
                        isinstance(chronology, dict)
                        and chronology.get("status")
                        == "externally_attested_pre_execution_freeze"
                        and chronology.get("chronology_cryptographically_verified")
                        is False
                    )
                    integrity = run.metadata.get("artifact_integrity")
                    external_integrity_passed = (
                        isinstance(integrity, dict)
                        and integrity.get("status") == "passed"
                    )
                    if (
                        run_started < registered
                        and chronology is None
                    ):
                        add(
                            "LEGACY_RUN_CHRONOLOGY_UNATTESTED",
                            RigorSeverity.WARNING,
                            "This run predates machine-issued protocol chronology receipts; "
                            "its relationship to canonical registration is not attested.",
                            entity_type="run",
                            entity_id=run.run_id,
                            remediation=(
                                "Do not call this locally preregistered. Reproduce it under a "
                                "current protocol or preserve a verifiable external-freeze accession."
                            ),
                        )
                    elif run_started < registered and not (
                        external_receipt and external_integrity_passed
                    ):
                        add(
                            "RUN_PRECEDES_CANONICAL_PROTOCOL_REGISTRATION",
                            RigorSeverity.ERROR,
                            "Run started before canonical protocol registration without a "
                            "machine-verified external-freeze accession receipt.",
                            entity_type="run",
                            entity_id=run.run_id,
                            remediation=(
                                "Do not call this locally preregistered. Preserve and verify "
                                "the externally frozen protocol, source, and freeze manifest."
                            ),
                        )
                    elif external_receipt:
                        add(
                            "EXTERNAL_PROTOCOL_FREEZE_ATTESTED",
                            RigorSeverity.WARNING,
                            "The run uses a hash-verified external freeze declaration; byte "
                            "identity is checked, but the declared pre-execution time is not "
                            "cryptographically authenticated by Research Machine.",
                            entity_type="run",
                            entity_id=run.run_id,
                        )
        if run.scientific_evidence_eligible and (
            run.synthetic or run.status is not RunStatus.COMPLETED
        ):
            add(
                "RUN_ELIGIBILITY_INCONSISTENT",
                RigorSeverity.ERROR,
                "Run is marked evidence-eligible despite synthetic or incomplete status.",
                entity_type="run",
                entity_id=run.run_id,
            )
        if not run.scientific_evidence_eligible:
            invalid_runs += 1
        passed_gate_ids = {
            gate.gate_id
            for gate in run.quality_gates
            if gate.status is QualityGateStatus.PASSED
        }
        required_gates_passed = all(
            gate.status is QualityGateStatus.PASSED
            for gate in run.quality_gates
            if gate.required
        )
        if (
            run.metadata.get("artifact_integrity_missing_for_evidence") is True
            and not run.synthetic
            and run.status is RunStatus.COMPLETED
            and required_gates_passed
        ):
            add(
                "RUN_ARTIFACT_INTEGRITY_MISSING_FOR_EVIDENCE",
                RigorSeverity.WARNING,
                "Run passed its required gates but lacks machine-replayed local output-byte verification, so it cannot support scientific evidence.",
                entity_type="run",
                entity_id=run.run_id,
                remediation=(
                    "Re-record the run with a local artifact root and exact output bytes; "
                    "do not treat declared output hashes or passed gate labels as evidence eligibility."
                ),
            )
        if (
            run.synthetic
            and run.status is RunStatus.COMPLETED
            and required_gates_passed
            and "known-result-reproduction" in passed_gate_ids
        ):
            add(
                "SYNTHETIC_KNOWN_RESULT_CALIBRATION_PASSED",
                RigorSeverity.INFO,
                "A synthetic run passed its known-result calibration gates but remains "
                "ineligible as scientific evidence.",
                entity_type="run",
                entity_id=run.run_id,
            )
    if invalid_runs:
        add(
            "FAILED_OR_INELIGIBLE_RUNS_RETAINED",
            RigorSeverity.INFO,
            f"{invalid_runs} failed, invalid, synthetic, workflow-component, or deviation-restricted runs remain visible.",
        )

    capabilities = {tag.value: bool(tag_counts[tag.value]) for tag in ValidationTag}
    capabilities["classified_evidence"] = bool(sum(tag_counts.values()))
    prospective_capabilities = {
        tag.value: bool(prospective_tag_counts[tag.value]) for tag in ValidationTag
    }
    prospective_capabilities["classified_evidence"] = bool(sum(prospective_tag_counts.values()))
    for tag in (
        ValidationTag.INDEPENDENT_REPLICATION,
        ValidationTag.KNOWN_RESULT_REPRODUCTION,
        ValidationTag.NOVEL_PREDICTION,
        ValidationTag.EMPIRICAL_TEST,
    ):
        if not capabilities[tag.value]:
            add(
                f"CAPABILITY_{tag.value.upper()}_ABSENT",
                RigorSeverity.WARNING,
                f"No evidence is classified as {tag.value}.",
            )
    if evidence and all(record.exploratory for record in evidence):
        add(
            "ALL_EVIDENCE_EXPLORATORY",
            RigorSeverity.WARNING,
            "All recorded evidence is exploratory.",
            remediation="Do not use confirmatory language until a protected confirmatory or replication result exists.",
        )

    severity_order = {
        RigorSeverity.ERROR: 0,
        RigorSeverity.WARNING: 1,
        RigorSeverity.INFO: 2,
    }
    findings.sort(
        key=lambda item: (
            severity_order[item.severity],
            item.code,
            item.entity_type,
            item.entity_id,
        )
    )
    evidence_counts = {
        "total": len(evidence),
        "classified": sum(bool(record.validation_tags) for record in evidence),
        "legacy_unclassified": sum(not record.validation_tags for record in evidence),
        "exploratory": sum(record.exploratory for record in evidence),
        "confirmatory_or_replication": sum(
            not record.exploratory for record in evidence
        ),
    }
    return RigorAudit(
        structurally_valid=not any(
            item.severity is RigorSeverity.ERROR for item in findings
        ),
        conclusion_ceiling=(
            _conclusion_ceiling(prospective_capabilities)
            if prospective_capabilities["classified_evidence"]
            else "retrospectively amended evidence only; prospective confirmation required"
            if capabilities["classified_evidence"]
            else _conclusion_ceiling(capabilities)
        ),
        capabilities=capabilities,
        evidence_counts=evidence_counts,
        findings=findings,
    )
