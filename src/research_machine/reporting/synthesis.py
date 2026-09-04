from __future__ import annotations

from collections import Counter, defaultdict

from research_machine.domain.models import (
    ActionRecommendation,
    Claim,
    CrossLaneLesson,
    DatasetManifest,
    EvidenceRecord,
    ExperimentProtocol,
    Hypothesis,
    Inquiry,
    Question,
    ResearchRun,
    RigorAudit,
    RigorSeverity,
)


def _text(value: str) -> str:
    return value.strip() or "Not specified."


def _evidence_detail_lines(records: list[EvidenceRecord]) -> list[str]:
    if not records:
        return ["- Evidence detail: No evidence recorded."]
    lines: list[str] = []
    for record in records:
        mode = "exploratory" if record.exploratory else "confirmatory"
        lines.extend(
            [
                f"- `{record.evidence_id}` [{mode}; {record.direction.value}] "
                f"{record.summary}",
                f"  - Scope: {_text(record.scope)}",
                f"  - Uncertainty: {_text(record.uncertainty)}",
                "  - Validation tags: "
                + (
                    ", ".join(tag.value for tag in record.validation_tags)
                    or "Unclassified legacy evidence."
                ),
                "  - Higher conclusions unsupported: "
                + (
                    "; ".join(record.higher_level_conclusions_unsupported)
                    or "None specified."
                ),
            ]
        )
    return lines


def build_synthesis(
    inquiry: Inquiry,
    questions: list[Question],
    claims: list[Claim],
    hypotheses: list[Hypothesis],
    evidence: list[EvidenceRecord],
    datasets: list[DatasetManifest],
    protocols: list[ExperimentProtocol],
    runs: list[ResearchRun],
    recommendations: list[ActionRecommendation],
    cross_lane_lessons: list[CrossLaneLesson],
    rigor_audit: RigorAudit,
) -> str:
    evidence_by_hypothesis: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in evidence:
        evidence_by_hypothesis[record.hypothesis_id].append(record)

    lines = [
        f"# Evidence synthesis: {inquiry.title}",
        "",
        f"**Inquiry:** {inquiry.initial_statement}",
        "",
        "This report is derived from structured state. It does not promote evidence "
        "between claim levels or infer mechanism, adaptation, attribution, or intent.",
        "",
        "## Decision context",
        "",
        f"- Decision to support: {_text(inquiry.decision_to_support)}",
        f"- Minimum evidence: {_text(inquiry.minimum_evidence)}",
        "- Decision owner: " + _text(inquiry.decision_owner),
        "- Evidence that would change the decision: "
        + (
            "; ".join(inquiry.decision_change_criteria)
            or "No change criteria recorded."
        ),
        "",
        "## Clarifying questions",
        "",
    ]
    if questions:
        for question in questions:
            answer = f" — {question.answer}" if question.answer else ""
            lines.append(f"- [{question.status.value}] {question.text}{answer}")
    else:
        lines.append("- No clarifying questions recorded.")

    lines.extend(["", "## Claim map", ""])
    if claims:
        for claim in claims:
            parents = ", ".join(claim.parent_claims) or "none"
            confidence = (
                f"{claim.confidence:.2f}"
                if claim.confidence is not None
                else "not assessed"
            )
            lines.extend(
                [
                    f"- `{claim.claim_id}` [{claim.level.value}; "
                    f"{claim.epistemic_layer.value}; {claim.disposition.value}] "
                    f"{claim.statement}",
                    f"  - Depends on: {parents}",
                    "  - Conflicts with: "
                    + (", ".join(claim.conflicts_with) or "none"),
                    "  - Sources: " + ("; ".join(claim.source_refs) or "none"),
                    "  - Falsified by: "
                    + ("; ".join(claim.falsified_by) or "not specified"),
                    f"  - Confidence: {confidence}; last reviewed: "
                    + (claim.last_reviewed or "not recorded"),
                ]
            )
    else:
        lines.append("- No claims recorded.")

    active = [item for item in hypotheses if item.workflow_state.value == "active"]
    pending = [
        item for item in hypotheses if item.workflow_state.value == "pending_review"
    ]
    drafts = [item for item in hypotheses if item.workflow_state.value == "unreviewed"]
    parked = [item for item in hypotheses if item.workflow_state.value == "parked"]
    retired = [item for item in hypotheses if item.workflow_state.value == "retired"]

    lines.extend(["", "## Active competing hypotheses", ""])
    if active:
        for hypothesis in active:
            records = evidence_by_hypothesis[hypothesis.hypothesis_id]
            directions = Counter(record.direction.value for record in records)
            evidence_summary = (
                ", ".join(
                    f"{name}: {count}" for name, count in sorted(directions.items())
                )
                or "no evidence recorded"
            )
            lines.extend(
                [
                    f"### {hypothesis.hypothesis_id}",
                    "",
                    hypothesis.statement,
                    "",
                    f"- Prediction: {_text(hypothesis.observable_prediction)}",
                    f"- Null model: {_text(hypothesis.null_model)}",
                    "- Competing models: "
                    + ("; ".join(hypothesis.competing_models) or "Not specified."),
                    "- Falsification conditions: "
                    + (
                        "; ".join(hypothesis.falsification_conditions)
                        or "Not specified."
                    ),
                    f"- Evidence records: {evidence_summary}",
                ]
            )
            lines.extend(_evidence_detail_lines(records))
            lines.append("")
    else:
        lines.append("- No active hypotheses.")

    lines.extend(["", "## Pending human review", ""])
    if pending:
        for hypothesis in pending:
            records = evidence_by_hypothesis[hypothesis.hypothesis_id]
            directions = Counter(record.direction.value for record in records)
            evidence_summary = (
                ", ".join(
                    f"{name}: {count}" for name, count in sorted(directions.items())
                )
                or "no exploratory evidence recorded"
            )
            lines.extend(
                [
                    f"### {hypothesis.hypothesis_id}",
                    "",
                    hypothesis.statement,
                    "",
                    "- Status: provisionally staged for exploratory work; human "
                    "ratification remains pending.",
                    f"- Staged by: {_text(hypothesis.pending_review_by or '')}",
                    f"- Confidence: {_text(hypothesis.pending_review_confidence)}",
                    f"- Rationale: {_text(hypothesis.pending_review_rationale)}",
                    f"- Exploratory evidence records: {evidence_summary}",
                ]
            )
            lines.extend(_evidence_detail_lines(records))
            lines.append("")
    else:
        lines.append("- No hypotheses pending human review.")

    lines.extend(["", "## Rejected and retired hypothesis memory", ""])
    if retired:
        for hypothesis in retired:
            retirement = hypothesis.retirement or {}
            resurrection = retirement.get("resurrection_conditions", [])
            lines.extend(
                [
                    f"### {hypothesis.hypothesis_id}",
                    "",
                    hypothesis.statement,
                    "",
                    f"- Decision: {retirement.get('rejection_type', 'not specified')}",
                    f"- Reason: {retirement.get('reason', 'not specified')}",
                    f"- Limitations: {retirement.get('limitations') or 'Not specified.'}",
                    "- Resurrection conditions: "
                    + ("; ".join(resurrection) or "None recorded."),
                    "",
                ]
            )
    else:
        lines.append("- No retired hypotheses.")

    valid_runs = [run for run in runs if run.scientific_evidence_eligible]
    invalid_runs = [run for run in runs if not run.scientific_evidence_eligible]
    lines.extend(
        [
            "",
            "## Execution and provenance",
            "",
            f"- Registered datasets: {len(datasets)}",
            f"- Frozen protocols: {sum(item.status.value == 'frozen' for item in protocols)}",
            f"- Evidence-eligible runs: {len(valid_runs)}",
            f"- Invalid or synthetic runs: {len(invalid_runs)}",
            f"- Evidence-eligible records: {sum(item.scientific_evidence_eligible for item in evidence)}",
        ]
    )
    if invalid_runs:
        lines.extend(["", "### Calibration and ineligible run outcomes", ""])
        for run in invalid_runs:
            required = [gate for gate in run.quality_gates if gate.required]
            passed = sum(gate.status.value == "passed" for gate in required)
            kind = "synthetic calibration" if run.synthetic else "ineligible run"
            lines.append(
                f"- `{run.run_id}` [{kind}; {run.status.value}; scientific evidence "
                f"ineligible]: required gates passed {passed}/{len(required)}. "
                f"{_text(run.summary)}"
            )
            failed = [
                gate.gate_id for gate in required if gate.status.value != "passed"
            ]
            if failed:
                lines.append("  - Required gates not passed: " + "; ".join(failed))
    lines.extend(
        [
            "",
            "## Epistemic rigor audit",
            "",
            f"- Conclusion ceiling: **{rigor_audit.conclusion_ceiling}**",
            f"- Classified evidence: {rigor_audit.evidence_counts['classified']} of {rigor_audit.evidence_counts['total']}",
            "- Capability tags are machine-checked provenance claims, not proof that "
            "the underlying scientific conclusion is true.",
        ]
    )
    for name, present in rigor_audit.capabilities.items():
        if name == "classified_evidence":
            continue
        lines.append(f"- {name}: {'present' if present else 'absent'}")
    severity_counts = Counter(item.severity.value for item in rigor_audit.findings)
    lines.extend(
        [
            "- Audit findings: "
            + ", ".join(
                f"{severity.value}={severity_counts[severity.value]}"
                for severity in RigorSeverity
            ),
        ]
    )
    finding_codes = Counter(
        item.code
        for item in rigor_audit.findings
        if item.severity is not RigorSeverity.INFO
    )
    if finding_codes:
        lines.append(
            "- Open rigor warnings/errors: "
            + "; ".join(
                f"{code} ({count})" for code, count in sorted(finding_codes.items())
            )
        )
    lines.extend(
        [
            "",
            "## Unresolved research state",
            "",
            f"- Unreviewed proposals: {len(drafts)}",
            f"- Pending human review: {len(pending)}",
            f"- Parked hypotheses: {len(parked)}",
            f"- Active hypotheses: {len(active)}",
            f"- Evidence records: {len(evidence)}",
            f"- Cross-lane process lessons: {len(cross_lane_lessons)}",
            _recommendation_summary(recommendations),
            "",
        ]
    )
    return "\n".join(lines)


def _recommendation_summary(
    recommendations: list[ActionRecommendation],
) -> str:
    if not recommendations:
        return (
            "- No next action has been selected. Candidate actions should "
            "distinguish surviving models rather than merely seek support for a "
            "preferred explanation."
        )
    latest = recommendations[-1]
    if latest.selection_mode == "portfolio":
        selected = "; ".join(
            f"{lane_id}: {action_id}"
            for lane_id, action_id in latest.selected_action_ids_by_lane.items()
        )
        return "- Selected next actions by lane: " + selected
    return (
        "- Selected next action: "
        + latest.selected_action_id
        + " — "
        + latest.rationale
    )
