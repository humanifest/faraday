from __future__ import annotations

from collections import Counter
from datetime import datetime

from research_machine.application.policies import (
    normalize_confidence,
    validate_validation_tag_context,
)
from research_machine.domain.errors import ResearchMachineError
from research_machine.domain.models import (
    AnalysisMode,
    Claim,
    ClaimDisposition,
    ClaimEpistemicLayer,
    DatasetManifest,
    EvidenceDirection,
    EvidenceRecord,
    ExperimentProtocol,
    Hypothesis,
    Inquiry,
    ProtocolKind,
    ProtocolStatus,
    QualityGateStatus,
    ResearchRun,
    RigorAudit,
    RigorFinding,
    RigorSeverity,
    RunStatus,
    ValidationTag,
)


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


def audit_research_state(
    *,
    inquiry: Inquiry,
    claims: list[Claim],
    hypotheses: list[Hypothesis],
    evidence: list[EvidenceRecord],
    datasets: list[DatasetManifest],
    protocols: list[ExperimentProtocol],
    runs: list[ResearchRun],
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

    tag_counts: Counter[str] = Counter()
    prospective_tag_counts: Counter[str] = Counter()
    for record in evidence:
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
            try:
                validate_validation_tag_context(
                    tags=record.validation_tags,
                    hypothesis=hypothesis,
                    exploratory=record.exploratory,
                    protocol=protocol,
                    run=run,
                    datasets=record_datasets,
                    controls_passed=record.controls_passed,
                    replicated_run=replicated_run,
                    claim=(claims_by_id.get(record.claim_id) if record.claim_id else None),
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
            protocol.analysis_mode
            in {AnalysisMode.CONFIRMATORY, AnalysisMode.REPLICATION}
            and protocol.protocol_kind
            in {ProtocolKind.OBSERVATIONAL, ProtocolKind.EXPERIMENTAL}
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
            protocol.analysis_mode
            in {AnalysisMode.CONFIRMATORY, AnalysisMode.REPLICATION}
            and protocol.protocol_kind
            in {ProtocolKind.OBSERVATIONAL, ProtocolKind.EXPERIMENTAL}
            and not protocol.sample_size_plan
        ):
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
        protocol = protocol_by_id.get(run.protocol_id)
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
