from __future__ import annotations

from collections import Counter, defaultdict

from research_machine.domain.models import (
    ActionCandidate,
    ActionRecommendation,
    Claim,
    CrossLaneLesson,
    DatasetManifest,
    EvidenceRecord,
    EvidenceStatusEvent,
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


def _evidence_detail_lines(
    records: list[EvidenceRecord], statuses: dict[str, EvidenceStatusEvent]
) -> list[str]:
    if not records:
        return ["- Evidence detail: No evidence recorded."]
    lines: list[str] = []
    for record in records:
        mode = "exploratory" if record.exploratory else "confirmatory"
        current = statuses.get(record.evidence_id)
        status = current.status if current is not None else "active_no_status_event"
        lines.extend(
            [
                f"- `{record.evidence_id}` [{mode}; {record.direction.value}] "
                f"(current status: {status}) {record.summary}",
                f"  - Scope: {_text(record.scope)}",
                f"  - Effect estimate: {_text(record.effect_estimate)}",
                f"  - Uncertainty: {_text(record.uncertainty)}",
                f"  - Analysis claim ceiling: {_text(record.analysis_claim_ceiling)}",
                f"  - Result direction check: {_text(record.result_direction_check)}",
                f"  - Verified analysis output: {_text(record.analysis_output_sha256)}",
                "  - Validation tags: "
                + (
                    ", ".join(tag.value for tag in record.validation_tags)
                    or "Unclassified legacy evidence."
                ),
                "  - Consistent frozen measurement-validity checks: "
                + (
                    ", ".join(record.measurement_validity_check_ids)
                    or "none"
                ),
                "  - Higher conclusions unsupported: "
                + (
                    "; ".join(record.higher_level_conclusions_unsupported)
                    or "None specified."
                ),
            ]
        )
        if current is not None:
            lines.extend([
                f"  - Latest status reason: {_text(current.reason)}",
                f"  - Status review artifact: `{current.review_artifact_sha256}` at `{current.review_artifact_locator}`",
            ])
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
    evidence_status_events: list[EvidenceStatusEvent],
) -> str:
    latest_status: dict[str, EvidenceStatusEvent] = {}
    for event in sorted(evidence_status_events, key=lambda item: (item.evidence_id, item.sequence)):
        latest_status[event.evidence_id] = event
    contributing_ids = {
        record.evidence_id for record in evidence
        if record.evidence_id not in latest_status
        or latest_status[record.evidence_id].status == "active"
    }
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
            directions = Counter(
                record.direction.value for record in records
                if record.evidence_id in contributing_ids
            )
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
            lines.extend(_evidence_detail_lines(records, latest_status))
            lines.append("")
    else:
        lines.append("- No active hypotheses.")

    lines.extend(["", "## Pending human review", ""])
    if pending:
        for hypothesis in pending:
            records = evidence_by_hypothesis[hypothesis.hypothesis_id]
            directions = Counter(
                record.direction.value for record in records
                if record.evidence_id in contributing_ids
            )
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
            lines.extend(_evidence_detail_lines(records, latest_status))
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
            f"- Ineligible runs retained: {len(invalid_runs)}",
            f"- Currently contributing evidence records: {sum(item.scientific_evidence_eligible and item.evidence_id in contributing_ids for item in evidence)}",
            f"- Evidence records under qualification, withdrawal, or retraction: {len(evidence) - len(contributing_ids)}",
        ]
    )
    planned_runs = [
        run for run in runs
        if isinstance(run.metadata.get("sample_size_plan_check"), dict)
        and run.metadata["sample_size_plan_check"].get("status")
        != "not_applicable"
    ]
    if planned_runs:
        lines.extend(["", "### Planning outcome accountability", ""])
        for run in sorted(planned_runs, key=lambda item: item.run_id):
            check = run.metadata["sample_size_plan_check"]
            lines.append(
                f"- Run `{run.run_id}` [{check.get('strategy', 'unknown')} plan; "
                f"sample binding: {check.get('status', 'unknown')}; evidence eligible: "
                f"{'yes' if run.scientific_evidence_eligible else 'no'}]."
            )
            lines.append(
                "  - Analyzable units per group: required "
                f"{check.get('required_analyzable_units_per_group', 'unverified')}; "
                f"observed {check.get('observed_minimum_analyzable_units_per_group', 'unverified')}."
            )
            lines.append(
                "  - Excluded fraction: anticipated "
                f"{check.get('anticipated_attrition_fraction', 'unverified')}; "
                f"maximum {check.get('registered_maximum_excluded_fraction', 'unverified')}; "
                f"observed {check.get('observed_excluded_fraction', 'unverified')}."
            )
            attrition = check.get("attrition_achievement")
            if isinstance(attrition, dict):
                lines.append(
                    "  - Attrition assumption: "
                    f"{attrition.get('status', 'unverified')}; group-specific observed "
                    f"fractions {attrition.get('observed_excluded_fraction_by_group', 'unverified')}; "
                    "a planning miss does not erase the result or imply invalidity."
                )
            variance = check.get("variance_assumption")
            if isinstance(variance, dict):
                unit = variance.get("measurement_unit") or check.get("measurement_unit") or "unit unspecified"
                lines.append(
                    "  - Variability assumption: "
                    f"{variance.get('status', 'unverified')}; assumed SD "
                    f"{variance.get('assumed_standard_deviation', 'unverified')} {unit}; "
                    f"observed pooled SD {variance.get('observed_pooled_standard_deviation', 'unverified')}; "
                    f"ratio {variance.get('observed_to_assumed_ratio', 'unverified')}. "
                    + (
                        f"Registered maximum ratio {variance.get('maximum_registered_ratio')}."
                        if variance.get("adequacy_threshold_registered") is True
                        else "No adequacy threshold was inferred after observing the data."
                    )
                )
            precision = check.get("precision_achievement")
            if isinstance(precision, dict) and precision.get("status") != "not_applicable":
                unit = precision.get("measurement_unit") or check.get("measurement_unit") or "unit unspecified"
                lines.append(
                    "  - Precision target: "
                    f"{precision.get('status', 'unverified')}; target half-width "
                    f"{precision.get('target_half_width', 'unverified')} {unit}; "
                    f"observed {precision.get('observed_half_width', 'unverified')}. "
                    "A missed target does not erase the result or imply invalidity."
                )
    preprocessing_runs = [
        run for run in runs
        if any(
            isinstance(gate.details.get("preprocessing_conformance"), dict)
            for gate in run.quality_gates
        )
    ]
    if preprocessing_runs:
        lines.extend(["", "### Preprocessing conformance provenance", ""])
        for run in sorted(preprocessing_runs, key=lambda item: item.run_id):
            for gate in run.quality_gates:
                conformance = gate.details.get("preprocessing_conformance")
                if not isinstance(conformance, dict):
                    continue
                lines.append(
                    f"- Run `{run.run_id}` gate `{gate.gate_id}` {gate.status.value}; "
                    f"record status: {conformance.get('status', 'unclassified')}; "
                    f"record `{conformance.get('sha256', 'unavailable')}` at "
                    f"`{conformance.get('locator', 'unavailable')}`."
                )
                lines.append(
                    "  - Registered pipeline: "
                    f"`{conformance.get('registered_pipeline_sha256', 'unavailable')}`; "
                    "observed pipeline: "
                    f"`{conformance.get('observed_pipeline_sha256', 'unavailable')}`. "
                    "This is a bounded conformance replay, not evidence of implementation correctness."
                )
    instrument_runs = [
        run for run in runs
        if any(
            isinstance(gate.details.get("instrument_inspection"), dict)
            for gate in run.quality_gates
        )
    ]
    if instrument_runs:
        lines.extend(["", "### Instrument inspection provenance", ""])
        for run in sorted(instrument_runs, key=lambda item: item.run_id):
            for gate in run.quality_gates:
                inspection = gate.details.get("instrument_inspection")
                if not isinstance(inspection, dict):
                    continue
                lines.append(
                    f"- Run `{run.run_id}` gate `{gate.gate_id}` {gate.status.value}; "
                    f"record status: {inspection.get('status', 'unclassified')}; "
                    f"record `{inspection.get('sha256', 'unavailable')}` at "
                    f"`{inspection.get('locator', 'unavailable')}`."
                )
                lines.append(
                    "  - Source: "
                    f"`{inspection.get('source_sha256', 'unavailable')}`; "
                    "config: "
                    f"`{inspection.get('config_sha256', 'unavailable')}`; "
                    "implementation: "
                    f"`{inspection.get('implementation_sha256', 'unavailable')}`. "
                    "This is retained acquisition metadata only, not calibration, custody, or scientific-evidence approval."
                )
    stream_timing_runs = [
        run for run in runs
        if any(
            isinstance(gate.details.get("stream_timing_assessment"), dict)
            for gate in run.quality_gates
        )
    ]
    if stream_timing_runs:
        lines.extend(["", "### Stream timing provenance", ""])
        for run in sorted(stream_timing_runs, key=lambda item: item.run_id):
            for gate in run.quality_gates:
                assessment = gate.details.get("stream_timing_assessment")
                if not isinstance(assessment, dict):
                    continue
                lines.append(
                    f"- Run `{run.run_id}` gate `{gate.gate_id}` {gate.status.value}; "
                    f"record status: {assessment.get('status', 'unclassified')}; "
                    f"record `{assessment.get('sha256', 'unavailable')}` at "
                    f"`{assessment.get('locator', 'unavailable')}`."
                )
                lines.append(
                    "  - Inspection record: "
                    f"`{assessment.get('inspection_sha256', 'unavailable')}`; "
                    "stream-timing specification: "
                    f"`{assessment.get('specification_sha256', 'unavailable')}`. "
                    "This checks timing feasibility from proposed stream metadata; it does not authenticate acquisition or calibration truth."
                )
    temporal_order_runs = [
        run for run in runs
        if any(
            isinstance(gate.details.get("temporal_order_assessment"), dict)
            for gate in run.quality_gates
        )
    ]
    if temporal_order_runs:
        lines.extend(["", "### Temporal order provenance", ""])
        for run in sorted(temporal_order_runs, key=lambda item: item.run_id):
            for gate in run.quality_gates:
                assessment = gate.details.get("temporal_order_assessment")
                if not isinstance(assessment, dict):
                    continue
                lines.append(
                    f"- Run `{run.run_id}` gate `{gate.gate_id}` {gate.status.value}; "
                    f"record status: {assessment.get('status', 'unclassified')}; "
                    f"record `{assessment.get('sha256', 'unavailable')}` at "
                    f"`{assessment.get('locator', 'unavailable')}`."
                )
                lines.append(
                    "  - Timing assessment: "
                    f"`{assessment.get('timing_assessment_sha256', 'unavailable')}`; "
                    "temporal-order specification: "
                    f"`{assessment.get('specification_sha256', 'unavailable')}`. "
                    "This classifies event order under timing uncertainty; it does not prove causality."
                )
    if evidence_status_events:
        lines.extend(["", "### Evidence correction and retraction history", ""])
        for event in sorted(evidence_status_events, key=lambda item: (item.evidence_id, item.sequence)):
            lines.append(
                f"- `{event.evidence_id}` event `{event.event_id}` sequence {event.sequence}: **{event.status}** effective {event.effective_at}. {event.reason} Artifact `{event.review_artifact_sha256}` at `{event.review_artifact_locator}`."
            )
    if invalid_runs:
        lines.extend(["", "### Calibration and ineligible run outcomes", ""])
        for run in invalid_runs:
            required = [gate for gate in run.quality_gates if gate.required]
            passed = sum(gate.status.value == "passed" for gate in required)
            disclosure = run.metadata.get("protocol_deviation_disclosure")
            disclosure_status = (
                disclosure.get("status") if isinstance(disclosure, dict) else "legacy_not_declared"
            )
            if run.synthetic:
                kind = "synthetic calibration"
            elif disclosure_status == "deviations_declared":
                kind = "deviation-restricted run"
            elif disclosure_status == "legacy_not_declared":
                kind = "deviation status undeclared"
            else:
                kind = "ineligible run"
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
            if disclosure_status == "legacy_not_declared":
                lines.append("  - Protocol deviations: not explicitly declared; adherence cannot be inferred from silence.")
            elif disclosure_status == "deviations_declared" and isinstance(disclosure, dict):
                deviations = disclosure.get("deviations", [])
                lines.append(f"  - Protocol deviations declared: {len(deviations) if isinstance(deviations, list) else 0}.")
                if isinstance(deviations, list):
                    for deviation in deviations:
                        if isinstance(deviation, dict):
                            lines.append(
                                f"    - `{deviation.get('deviation_id', 'unknown')}` [{deviation.get('timing', 'unknown')}; potential impact: {deviation.get('potential_impact', 'unknown')}]: frozen `{deviation.get('frozen_commitment', 'unavailable')}`; actual `{deviation.get('actual_method', 'unavailable')}`; evidence `{deviation.get('evidence_sha256', 'unavailable')}` at `{deviation.get('evidence_location', 'unavailable')}`."
                            )
    controlled_protocols = [
        protocol for protocol in protocols if protocol.control_definitions
    ]
    if controlled_protocols:
        lines.extend(["", "### Control evaluation provenance", ""])
        for protocol in controlled_protocols:
            controls_by_id = {
                control.control_id: control
                for control in protocol.control_definitions
            }
            lines.append(
                f"- Protocol `{protocol.protocol_id}` frozen controls: "
                + "; ".join(
                    f"`{control.control_id}` ({control.family})"
                    for control in protocol.control_definitions
                )
                + ". Expected behavior is a scientific outcome, not a gate-pass criterion."
            )
            for run in sorted(
                (item for item in runs if item.protocol_id == protocol.protocol_id),
                key=lambda item: item.run_id,
            ):
                for gate in run.quality_gates:
                    results = gate.details.get("control_results")
                    if not isinstance(results, dict):
                        continue
                    for control_id, result in sorted(results.items()):
                        if not isinstance(result, dict):
                            continue
                        control = controls_by_id.get(control_id)
                        expected = result.get("matches_expected")
                        disposition = (
                            "matched expected behavior" if expected is True
                            else "did not match expected behavior" if expected is False
                            else "unclassified"
                        )
                        lines.append(
                            f"  - Run `{run.run_id}` / `{control_id}`"
                            + (f" ({control.family})" if control is not None else "")
                            + f": gate `{gate.gate_id}` {gate.status.value}; {disposition}; "
                            f"artifact `{result.get('evidence_sha256', 'unavailable')}` at "
                            f"`{result.get('evidence_location', 'unavailable')}`."
                        )
    validity_protocols = [
        protocol for protocol in protocols if protocol.measurement_validity_checks
    ]
    if validity_protocols:
        lines.extend(["", "### Measurement validity provenance", ""])
        for protocol in validity_protocols:
            lines.append(
                f"- Protocol `{protocol.protocol_id}` frozen validity checks: "
                + "; ".join(
                    f"`{check.check_id}` ({check.evidence_type}) for measurement "
                    f"`{check.measurement_id}`; claim: {_text(check.validity_claim)}; "
                    f"failure response: {_text(check.failure_response)}"
                    for check in protocol.measurement_validity_checks
                )
                + ". A consistent diagnostic does not prove construct validity."
            )
            checks_by_id = {
                check.check_id: check
                for check in protocol.measurement_validity_checks
            }
            for run in sorted(
                (item for item in runs if item.protocol_id == protocol.protocol_id),
                key=lambda item: item.run_id,
            ):
                reported: set[str] = set()
                for gate in run.quality_gates:
                    results = gate.details.get("measurement_validity_results")
                    if not isinstance(results, dict):
                        continue
                    for check_id, result in sorted(results.items()):
                        if not isinstance(result, dict):
                            continue
                        reported.add(check_id)
                        check = checks_by_id.get(check_id)
                        lines.append(
                            f"  - Run `{run.run_id}` / `{check_id}`"
                            + (f" ({check.evidence_type})" if check is not None else "")
                            + f": gate `{gate.gate_id}` {gate.status.value}; "
                            f"{result.get('assessment_status', 'unclassified')}; "
                            f"observed: {_text(str(result.get('observed_diagnostic', '')))} "
                            f"Interpretation: {_text(str(result.get('interpretation', '')))} "
                            f"Artifact `{result.get('evidence_sha256', 'unavailable')}` at "
                            f"`{result.get('evidence_location', 'unavailable')}`."
                        )
                missing = sorted(set(checks_by_id) - reported)
                if missing:
                    lines.append(
                        f"  - Run `{run.run_id}`: validity results unavailable for "
                        + ", ".join(f"`{item}`" for item in missing)
                        + "; no validity conclusion may be inferred."
                    )
    missingness_protocols = [
        protocol for protocol in protocols
        if protocol.analysis_contract is not None
        and protocol.analysis_contract.missingness_assessment_gate_id
    ]
    if missingness_protocols:
        lines.extend(["", "### Missingness assessment provenance", ""])
        for protocol in missingness_protocols:
            contract = protocol.analysis_contract
            lines.append(
                f"- Protocol `{protocol.protocol_id}`: "
                f"{contract.missingness_assessment_kind} via dedicated gate "
                f"`{contract.missingness_assessment_gate_id}`; assumption: "
                f"{_text(contract.missingness_assumption)} Failure response: "
                f"{_text(contract.missingness_failure_response)}"
            )
            for run in sorted(
                (item for item in runs if item.protocol_id == protocol.protocol_id),
                key=lambda item: item.run_id,
            ):
                gate = next(
                    (item for item in run.quality_gates
                     if item.gate_id == contract.missingness_assessment_gate_id),
                    None,
                )
                if gate is None:
                    lines.append(
                        f"  - Run `{run.run_id}`: required missingness gate absent; "
                        "scientific evidence ineligible."
                    )
                    continue
                result = gate.details.get("missingness_assessment_result")
                if not isinstance(result, dict):
                    lines.append(
                        f"  - Run `{run.run_id}`: gate {gate.status.value}; "
                        "assessment not performed or unavailable."
                    )
                    continue
                lines.append(
                    f"  - Run `{run.run_id}`: gate {gate.status.value}; "
                    f"{result.get('assessment_kind', 'legacy_unclassified')}; "
                    f"{result.get('assessment_status', 'unclassified')}; artifact "
                    f"`{result.get('evidence_sha256', 'unavailable')}` at "
                    f"`{result.get('evidence_location', 'unavailable')}`."
                )
    causal_protocols = [protocol for protocol in protocols if protocol.causal_claim]
    if causal_protocols:
        lines.extend(["", "### Causal assumption assessment provenance", ""])
        for protocol in causal_protocols:
            assumptions = protocol.causal_identification_audit.get(
                "assumption_register", []
            )
            kind_counts = Counter(
                item.get("assessment_kind", "legacy_unclassified")
                for item in assumptions if isinstance(item, dict)
            )
            lines.append(
                f"- Protocol `{protocol.protocol_id}` frozen assessment kinds: "
                + ("; ".join(
                    f"{kind}={count}" for kind, count in sorted(kind_counts.items())
                ) or "none")
                + ". A passed assessment is not proof that its assumption is true."
            )
            for run in sorted(
                (item for item in runs if item.protocol_id == protocol.protocol_id),
                key=lambda item: item.run_id,
            ):
                for gate in run.quality_gates:
                    results = gate.details.get("causal_assumption_results")
                    if not isinstance(results, dict):
                        continue
                    for category, result in sorted(results.items()):
                        if not isinstance(result, dict):
                            continue
                        lines.append(
                            f"  - Run `{run.run_id}` / `{category}`: "
                            f"gate `{gate.gate_id}` {gate.status.value}; "
                            f"{result.get('assessment_kind', 'legacy_unclassified')}; "
                            f"{result.get('assessment_status', 'unclassified')}; "
                            f"artifact `{result.get('evidence_sha256', 'unavailable')}` at "
                            f"`{result.get('evidence_location', 'unavailable')}`."
                        )
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
    candidates_by_id = {
        candidate.action_id: candidate for candidate in latest.candidates
    }
    if latest.selection_mode == "portfolio":
        selected = "; ".join(
            f"{lane_id}: {action_id}"
            for lane_id, action_id in latest.selected_action_ids_by_lane.items()
        )
        factors = "; ".join(
            f"{lane_id}: {_action_factor_summary(candidates_by_id[action_id])}"
            for lane_id, action_id in latest.selected_action_ids_by_lane.items()
            if action_id in candidates_by_id
        )
        return (
            "- Selected next actions by lane: "
            + selected
            + ". Factor plan: "
            + (factors or "not available")
            + "."
        )
    selected = candidates_by_id.get(latest.selected_action_id)
    factor_summary = (
        _action_factor_summary(selected) if selected is not None else "not available"
    )
    return (
        "- Selected next action: "
        + latest.selected_action_id
        + " — "
        + latest.rationale
        + " Factor plan: "
        + factor_summary
        + "."
    )


def _action_factor_summary(candidate: ActionCandidate) -> str:
    factors = candidate.manipulated_factors
    if not factors:
        return "no manipulated factors declared"
    if candidate.factorial_or_crossover_design:
        design = "factorial/crossover declared"
    elif len(factors) == 1:
        design = "single-factor or legacy-unresolved design"
    else:
        design = "missing factorial/crossover declaration"
    if candidate.factor_interpretability_plan:
        design += f"; plan: {candidate.factor_interpretability_plan}"
    return ", ".join(factors) + f" ({design})"
