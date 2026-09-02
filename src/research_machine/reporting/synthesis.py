from __future__ import annotations

from collections import Counter, defaultdict

from research_machine.domain.models import (
    Claim,
    EvidenceRecord,
    Hypothesis,
    Inquiry,
    Question,
)


def _text(value: str) -> str:
    return value.strip() or "Not specified."


def build_synthesis(
    inquiry: Inquiry,
    questions: list[Question],
    claims: list[Claim],
    hypotheses: list[Hypothesis],
    evidence: list[EvidenceRecord],
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
            lines.append(
                f"- `{claim.claim_id}` [{claim.level.value}] {claim.statement} "
                f"(parents: {parents})"
            )
    else:
        lines.append("- No claims recorded.")

    active = [item for item in hypotheses if item.workflow_state.value == "active"]
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
                    "",
                ]
            )
    else:
        lines.append("- No active hypotheses.")

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

    lines.extend(
        [
            "",
            "## Unresolved research state",
            "",
            f"- Unreviewed proposals: {len(drafts)}",
            f"- Parked hypotheses: {len(parked)}",
            f"- Active hypotheses: {len(active)}",
            f"- Evidence records: {len(evidence)}",
            "- Next experiments must distinguish surviving models rather than merely "
            "seek additional support for a preferred explanation.",
            "",
        ]
    )
    return "\n".join(lines)
