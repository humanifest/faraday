from __future__ import annotations

from collections import Counter

from research_machine.application.policies import validate_validation_tag_context
from research_machine.domain.errors import ResearchMachineError
from research_machine.domain.models import (
    DatasetManifest,
    EvidenceDirection,
    EvidenceRecord,
    ExperimentProtocol,
    Hypothesis,
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
        return "independently replicated limited result; known-result reproduction absent"
    if not capabilities[ValidationTag.NOVEL_PREDICTION.value]:
        return "replicated and reproduced result; no novel prediction"
    if not capabilities[ValidationTag.EMPIRICAL_TEST.value]:
        return "registered novel prediction; no empirical test"
    return "scoped empirical result; not proof of a theory"


def audit_research_state(
    *,
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

    hypothesis_by_id = {item.hypothesis_id: item for item in hypotheses}
    protocol_by_id = {item.protocol_id: item for item in protocols}
    run_by_id = {item.run_id: item for item in runs}
    dataset_by_id = {item.dataset_id: item for item in datasets}

    tag_counts: Counter[str] = Counter()
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
        protocol = protocol_by_id.get(record.protocol_id) if record.protocol_id else None
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
            if run is not None and isinstance(run.metadata.get("replicates_run_id"), str):
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

    runs_by_protocol: Counter[str] = Counter(run.protocol_id for run in runs)
    for protocol in protocols:
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
        if not protocol.sample_size_or_stopping_rule.strip():
            add(
                "FROZEN_PROTOCOL_WITHOUT_STOP_RULE",
                RigorSeverity.WARNING,
                "Frozen protocol has no explicit sample-size or stopping rule.",
                entity_type="protocol",
                entity_id=protocol.protocol_id,
                remediation="Require a stopping rule in the next protocol version.",
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
            f"{invalid_runs} failed, invalid, or synthetic runs remain visible.",
        )

    capabilities = {
        tag.value: bool(tag_counts[tag.value]) for tag in ValidationTag
    }
    capabilities["classified_evidence"] = bool(sum(tag_counts.values()))
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
        "legacy_unclassified": sum(
            not record.validation_tags for record in evidence
        ),
        "exploratory": sum(record.exploratory for record in evidence),
        "confirmatory_or_replication": sum(
            not record.exploratory for record in evidence
        ),
    }
    return RigorAudit(
        structurally_valid=not any(
            item.severity is RigorSeverity.ERROR for item in findings
        ),
        conclusion_ceiling=_conclusion_ceiling(capabilities),
        capabilities=capabilities,
        evidence_counts=evidence_counts,
        findings=findings,
    )
