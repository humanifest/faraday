"""Hypothesis-disclosure reactivity plan freeze, run assessment, and ceilings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import CreateProtocol
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ValidationError
from research_machine.domain.models import (
    AnalysisMode,
    CompetingProcessModel,
    DatasetArtifact,
    DecisionLossAssumptions,
    HypothesisDisclosureEvent,
    HypothesisReactivityPlan,
    ProtocolKind,
    QualityGateResult,
    QualityGateStatus,
)
from test_execution import (
    CODE_HASH,
    SEED_COMMITMENT,
    prepared_service,
    run_command,
)


def _write_json_artifact(path: Path, payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()


def _reactivity_plan(**overrides) -> HypothesisReactivityPlan:
    payload = {
        "plan_id": "disclosure-reactivity-01",
        "disclosure_schedule": [
            HypothesisDisclosureEvent(
                event_id="cover-pre",
                audience="participants",
                statement_disclosed="A cover story about routine equipment checks.",
                statement_role="cover_story",
                timing_anchor="pre_exposure",
                timing_description="Told before any outcome window opens.",
            ),
            HypothesisDisclosureEvent(
                event_id="true-h-post",
                audience="participants",
                statement_disclosed="The registered scientific hypothesis after lock.",
                statement_role="true_hypothesis",
                timing_anchor="analysis",
                timing_description="Debrief after outcome collection ends.",
            ),
        ],
        "process_models": [
            CompetingProcessModel(
                model_id="no-reactivity",
                statement="Disclosure does not change the measured process.",
                observable_prediction="Outcome series matches the no-disclosure baseline.",
                comparison_rule="Differs from demand-compliance by lacking post-disclosure movement toward the stated expectation.",
                distinguishability="distinguishable",
            ),
            CompetingProcessModel(
                model_id="demand-compliance",
                statement="After learning the hypothesis, behavior moves toward the expected pattern.",
                observable_prediction="Post-disclosure movement toward the stated expectation exceeds the decoy contrast.",
                comparison_rule="Differs from no-reactivity by a registered directional post-disclosure change.",
                distinguishability="distinguishable",
            ),
            CompetingProcessModel(
                model_id="detected-and-concealing",
                statement="An observer mimics the null whenever concealment is free.",
                observable_prediction="Any quiet series is accommodated without a costly signature.",
                comparison_rule="Unspecified free concealment fits every quiet outcome.",
                distinguishability="not_distinguishable_by_this_design",
                non_distinguishability_rationale=(
                    "This design has no costly signature that free concealment cannot mimic."
                ),
            ),
        ],
        "likelihood_comparison_rule": (
            "Assign evidential weight only when the registered likelihood of the "
            "observation under a distinguishable model exceeds the alternatives; "
            "shared possibility alone is not an update."
        ),
        "assessment_gate_id": "hypothesis-reactivity-assessed",
        "ethical_disclosure": (
            "Independent review must approve any cover story and debrief timing."
        ),
        "limitations": (
            "Catch-all concealment remains not distinguishable by this design; "
            "quiet results do not establish safety or an observer."
        ),
        "decision_loss_assumptions": DecisionLossAssumptions(
            false_reassurance_cost="Acting as if safe while wrong is high cost.",
            precaution_cost="Extra precautions impose time and operational cost.",
            decision_rule="Choose precaution only under stated loss and cost assumptions.",
            notice="A precaution under these assumptions is not a finding and not evidence that an observer exists.",
        ),
    }
    payload.update(overrides)
    return HypothesisReactivityPlan(**payload)


def frozen_reactivity_protocol(service: ResearchService, hypothesis_id: str):
    plan = _reactivity_plan()
    protocol = service.create_protocol(
        CreateProtocol(
            experiment_id="reactivity-check-01",
            title="Disclosure reactivity probe",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[hypothesis_id],
            primary_outcome="Registered behavioral contrast after disclosure",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Freeze disclosure schedule and competing process models before outcomes.",
            quality_requirements=["proof-check", plan.assessment_gate_id],
            controls=["Replay a deliberately invalid derivation."],
            expected_outputs=["Proof object", "Reactivity assessment artifact"],
            success_conditions=["The independent checker accepts the proof object."],
            environment_requirements=["Pinned checker and axiom-set hashes"],
            sample_size_or_stopping_rule="One registered assessment window.",
            failure_conditions=["The checker rejects any proof step."],
            safety_constraints=["No physical or human intervention is involved."],
            hypothesis_reactivity_plan=plan,
            analysis_code_hash=CODE_HASH,
            random_seed_commitment=SEED_COMMITMENT,
        )
    )
    return service.freeze_protocol(protocol.protocol_id), plan


def test_hypothesis_reactivity_plan_freeze_template_assessment_and_synthesis(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol, plan = frozen_reactivity_protocol(service, hypothesis_id)

    template = service.run_record_template(protocol.protocol_id, "formal")
    assert template["hypothesis_reactivity_plan"]["plan_id"] == plan.plan_id
    assessment_template = template["record"]["quality_gates"][1]["details"][
        "hypothesis_reactivity_assessment"
    ]
    assert assessment_template["plan_id"] == plan.plan_id
    assert "detected-and-concealing" in assessment_template["not_distinguishable_model_ids"]

    proof_output = tmp_path / "proof-output.json"
    proof_sha256 = _write_json_artifact(proof_output, {"proof": {"status": "passed"}})
    reactivity_output = tmp_path / "reactivity-output.json"
    reactivity_value = {
        "status": "compatible_with_multiple",
        "remaining_models": ["no-reactivity", "demand-compliance"],
    }
    reactivity_sha256 = _write_json_artifact(
        reactivity_output, {"reactivity": {"comparison": reactivity_value}}
    )
    selected_value_sha256 = hashlib.sha256(
        (
            json.dumps(
                reactivity_value,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode()
    ).hexdigest()

    run = service.record_run(
        run_command(
            protocol.protocol_id,
            QualityGateStatus.PASSED,
            artifact_root=str(tmp_path),
            output_artifacts=[
                DatasetArtifact(
                    proof_output.name,
                    proof_sha256,
                    size_bytes=proof_output.stat().st_size,
                    media_type="application/json",
                ),
                DatasetArtifact(
                    reactivity_output.name,
                    reactivity_sha256,
                    size_bytes=reactivity_output.stat().st_size,
                    media_type="application/json",
                ),
            ],
            quality_gates=[
                QualityGateResult(
                    gate_id="proof-check",
                    status=QualityGateStatus.PASSED,
                    summary="Independent proof-checker result.",
                    details={"evidence_sha256": proof_sha256},
                ),
                QualityGateResult(
                    gate_id="hypothesis-reactivity-assessed",
                    status=QualityGateStatus.WARNING,
                    summary="Reactivity comparison retained.",
                    details={
                        "evidence_sha256": reactivity_sha256,
                        "hypothesis_reactivity_assessment": {
                            "plan_id": plan.plan_id,
                            "assessment_status": "compatible_with_multiple",
                            "supported_model_ids": [],
                            "not_distinguishable_model_ids": ["detected-and-concealing"],
                            "likelihood_comparison": (
                                f"Under frozen plan {plan.plan_id}, the observation is "
                                "compatible with no-reactivity and demand-compliance; "
                                "shared possibility with catch-all concealment is not an update."
                            ),
                            "observed_pattern": "No costly signature appeared in the window.",
                            "interpretation": (
                                "Multiple distinguishable models remain compatible; "
                                "catch-all concealment stays a design limit."
                            ),
                            "decision_rationale": (
                                "Under the frozen loss and cost assumptions, take the "
                                "registered precaution without treating it as a finding."
                            ),
                            "evidence_sha256": reactivity_sha256,
                            "evidence_location": "/reactivity/comparison",
                        },
                    },
                ),
            ],
        ),
        "formal",
    )

    retained = run.quality_gates[1].details["hypothesis_reactivity_assessment"]
    assert retained["selected_value_sha256"] == selected_value_sha256
    synthesis = service.build_synthesis("formal")["content"]
    assert "Hypothesis reactivity provenance" in synthesis
    assert "not distinguishable by this design" in synthesis.casefold() or (
        "Non-distinguishable models are design limits" in synthesis
    )
    assert any(
        finding.code == "RUN_HYPOTHESIS_REACTIVITY_COMPATIBLE_WITH_MULTIPLE"
        for finding in service.audit_rigor("formal").findings
    )
    assert any(
        finding.code == "PROTOCOL_HYPOTHESIS_REACTIVITY_PLAN_DECLARED"
        for finding in service.audit_rigor("formal").findings
    )


def test_reactivity_rejects_support_for_non_distinguishable_model(
    tmp_path: Path,
) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol, plan = frozen_reactivity_protocol(service, hypothesis_id)
    proof_output = tmp_path / "proof-output.json"
    proof_sha256 = _write_json_artifact(proof_output, {"proof": {"status": "passed"}})
    reactivity_output = tmp_path / "reactivity-output.json"
    reactivity_sha256 = _write_json_artifact(
        reactivity_output, {"reactivity": {"comparison": {"status": "claimed"}}}
    )

    with pytest.raises(ValidationError, match="non-distinguishable"):
        service.record_run(
            run_command(
                protocol.protocol_id,
                QualityGateStatus.PASSED,
                artifact_root=str(tmp_path),
                output_artifacts=[
                    DatasetArtifact(
                        proof_output.name,
                        proof_sha256,
                        size_bytes=proof_output.stat().st_size,
                        media_type="application/json",
                    ),
                    DatasetArtifact(
                        reactivity_output.name,
                        reactivity_sha256,
                        size_bytes=reactivity_output.stat().st_size,
                        media_type="application/json",
                    ),
                ],
                quality_gates=[
                    QualityGateResult(
                        gate_id="proof-check",
                        status=QualityGateStatus.PASSED,
                        summary="Independent proof-checker result.",
                        details={"evidence_sha256": proof_sha256},
                    ),
                    QualityGateResult(
                        gate_id="hypothesis-reactivity-assessed",
                        status=QualityGateStatus.PASSED,
                        summary="Invalid support claim.",
                        details={
                            "evidence_sha256": reactivity_sha256,
                            "hypothesis_reactivity_assessment": {
                                "plan_id": plan.plan_id,
                                "assessment_status": "models_discriminated",
                                "supported_model_ids": ["detected-and-concealing"],
                                "not_distinguishable_model_ids": [
                                    "detected-and-concealing"
                                ],
                                "likelihood_comparison": (
                                    f"Cites frozen plan {plan.plan_id} incorrectly."
                                ),
                                "observed_pattern": "A quiet series.",
                                "interpretation": "Treats catch-all concealment as supported.",
                                "evidence_sha256": reactivity_sha256,
                                "evidence_location": "/reactivity/comparison",
                            },
                        },
                    ),
                ],
            ),
            "formal",
        )


def test_reactivity_rejects_detection_finding_language(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    protocol, plan = frozen_reactivity_protocol(service, hypothesis_id)
    proof_output = tmp_path / "proof-output.json"
    proof_sha256 = _write_json_artifact(proof_output, {"proof": {"status": "passed"}})
    reactivity_output = tmp_path / "reactivity-output.json"
    reactivity_sha256 = _write_json_artifact(
        reactivity_output, {"reactivity": {"comparison": {"status": "ok"}}}
    )

    with pytest.raises(ValidationError, match="detection"):
        service.record_run(
            run_command(
                protocol.protocol_id,
                QualityGateStatus.PASSED,
                artifact_root=str(tmp_path),
                output_artifacts=[
                    DatasetArtifact(
                        proof_output.name,
                        proof_sha256,
                        size_bytes=proof_output.stat().st_size,
                        media_type="application/json",
                    ),
                    DatasetArtifact(
                        reactivity_output.name,
                        reactivity_sha256,
                        size_bytes=reactivity_output.stat().st_size,
                        media_type="application/json",
                    ),
                ],
                quality_gates=[
                    QualityGateResult(
                        gate_id="proof-check",
                        status=QualityGateStatus.PASSED,
                        summary="Independent proof-checker result.",
                        details={"evidence_sha256": proof_sha256},
                    ),
                    QualityGateResult(
                        gate_id="hypothesis-reactivity-assessed",
                        status=QualityGateStatus.PASSED,
                        summary="Overclaiming interpretation.",
                        details={
                            "evidence_sha256": reactivity_sha256,
                            "hypothesis_reactivity_assessment": {
                                "plan_id": plan.plan_id,
                                "assessment_status": "models_discriminated",
                                "supported_model_ids": ["demand-compliance"],
                                "not_distinguishable_model_ids": [
                                    "detected-and-concealing"
                                ],
                                "likelihood_comparison": (
                                    f"Under frozen plan {plan.plan_id}, demand-compliance "
                                    "is favored over no-reactivity."
                                ),
                                "observed_pattern": "Post-disclosure movement matched demand.",
                                "interpretation": "They are currently detected.",
                                "evidence_sha256": reactivity_sha256,
                                "evidence_location": "/reactivity/comparison",
                            },
                        },
                    ),
                ],
            ),
            "formal",
        )


def test_reactivity_freeze_requires_two_process_models(tmp_path: Path) -> None:
    service, hypothesis_id = prepared_service(tmp_path)
    plan = _reactivity_plan(
        process_models=[
            CompetingProcessModel(
                model_id="only-one",
                statement="Single model is incomplete.",
                observable_prediction="Anything.",
                comparison_rule="No comparator.",
                distinguishability="distinguishable",
            )
        ]
    )
    protocol = service.create_protocol(
        CreateProtocol(
            experiment_id="reactivity-bad",
            title="Incomplete repertoire",
            analysis_mode=AnalysisMode.CONFIRMATORY,
            hypotheses_tested=[hypothesis_id],
            primary_outcome="Outcome",
            protocol_kind=ProtocolKind.FORMAL,
            methodology="Incomplete.",
            quality_requirements=["proof-check", plan.assessment_gate_id],
            controls=["Invalid control."],
            expected_outputs=["Proof"],
            success_conditions=["Pass."],
            hypothesis_reactivity_plan=plan,
            analysis_code_hash=CODE_HASH,
            random_seed_commitment=SEED_COMMITMENT,
        )
    )
    with pytest.raises(ValidationError, match="at least two process_models"):
        service.freeze_protocol(protocol.protocol_id)
