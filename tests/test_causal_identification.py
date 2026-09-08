import json

import pytest

from research_machine.design.causal import audit_causal_identification
from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main


def _assumptions(assignment="observational"):
    categories = [
        "positivity", "consistency", "interference", "temporal_order",
        "measurement_validity", "selection_bias",
        "exchangeability" if assignment == "observational" else "allocation_integrity",
    ]
    return [{
        "category": category,
        "statement": f"Synthetic {category} assumption.",
        "assessment_kind": "design_record_review",
        "assessment_plan": f"Assess {category} before interpreting the estimate.",
        "failure_response": f"Stop causal interpretation if {category} is not defensible.",
        "assessment_gate_id": "integrity",
    } for category in categories]


def _estimand(outcome="outcome", hypothesis_id="h1"):
    return {
        "target_hypothesis_id": hypothesis_id,
        "description": "Mean outcome difference, group a minus group b.",
        "population": "Eligible study units in the registered setting.",
        "exposure_strategies": ["assign treatment", "assign control"],
        "outcome_variable": outcome,
        "time_zero": "At assignment after eligibility is established.",
        "outcome_time": "Seven days after assignment.",
        "contrast": "Treatment minus control.",
        "summary_measure": "Population mean difference.",
        "intercurrent_events_policy": "Retain all assigned eligible units and report missing outcomes.",
    }


def _confounded(adjustment=None, hypothesis_id="h1"):
    return {
        "nodes": [{"id": "treatment", "observed": True},
                  {"id": "outcome", "observed": True},
                  {"id": "baseline", "observed": True}],
        "edges": [{"cause": "baseline", "effect": "treatment"},
                  {"cause": "baseline", "effect": "outcome"},
                  {"cause": "treatment", "effect": "outcome"}],
        "exposure": "treatment", "outcome": "outcome",
        "proposed_adjustment_set": adjustment or [],
        "assignment_type": "observational",
        "assumptions": _assumptions(),
        "causal_estimand": _estimand(hypothesis_id=hypothesis_id),
    }


def test_observational_backdoor_path_must_be_blocked() -> None:
    blocked = audit_causal_identification(_confounded())
    assert blocked["status"] == "blocked"
    assert blocked["backdoor_criterion_satisfied"] is False
    assert blocked["open_backdoor_connectivity_witness"] == ["treatment", "baseline", "outcome"]
    assert blocked["minimal_observed_adjustment_sets"] == [["baseline"]]
    assert blocked["adjustment_set_enumeration_status"] == "complete"
    passed = audit_causal_identification(_confounded(["baseline"]))
    assert passed["status"] == "review_required"
    assert passed["backdoor_criterion_satisfied"] is True
    assert passed["violations"] == []
    assert passed["minimal_observed_adjustment_sets"] == [["baseline"]]
    assert "does not establish that the DAG or registered assumptions are true" in passed["claim_ceiling"]


def test_unobserved_and_post_treatment_adjustment_fail_closed() -> None:
    unobserved = _confounded(["baseline"])
    unobserved["nodes"][2]["observed"] = False
    assert "UNOBSERVED_ADJUSTMENT" in {
        item["code"] for item in audit_causal_identification(unobserved)["violations"]
    }
    mediator = _confounded(["baseline", "mediator"])
    mediator["nodes"].append({"id": "mediator", "observed": True})
    mediator["edges"].extend([
        {"cause": "treatment", "effect": "mediator"},
        {"cause": "mediator", "effect": "outcome"},
    ])
    assert "POST_TREATMENT_ADJUSTMENT" in {
        item["code"] for item in audit_causal_identification(mediator)["violations"]
    }
    latent_outcome = _confounded(["baseline"])
    latent_outcome["nodes"][1]["observed"] = False
    assert "UNOBSERVED_EXPOSURE_OR_OUTCOME" in {
        item["code"] for item in audit_causal_identification(latent_outcome)["violations"]
    }


def test_randomization_claim_must_not_conflict_with_supplied_graph() -> None:
    spec = _confounded()
    spec["assignment_type"] = "randomized"
    spec["assumptions"] = _assumptions("randomized")
    result = audit_causal_identification(spec)
    assert "RANDOMIZATION_GRAPH_CONFLICT" in {item["code"] for item in result["violations"]}
    assert result["backdoor_criterion_satisfied"] is None


def test_causal_graph_must_be_acyclic() -> None:
    spec = _confounded()
    spec["edges"].append({"cause": "outcome", "effect": "baseline"})
    with pytest.raises(ValidationError, match="acyclic"):
        audit_causal_identification(spec)


def test_minimal_set_enumeration_does_not_recommend_conditioning_on_a_collider() -> None:
    spec = {
        "nodes": [{"id": node, "observed": True} for node in ("x", "y", "u", "collider")],
        "edges": [{"cause": "x", "effect": "collider"},
                  {"cause": "u", "effect": "collider"},
                  {"cause": "u", "effect": "y"}],
        "exposure": "x", "outcome": "y", "proposed_adjustment_set": [],
        "assignment_type": "observational",
        "assumptions": _assumptions(),
        "causal_estimand": _estimand("y"),
    }
    result = audit_causal_identification(spec)
    assert result["backdoor_criterion_satisfied"] is True
    assert result["minimal_observed_adjustment_sets"] == [[]]
    adjusted = audit_causal_identification({**spec, "proposed_adjustment_set": ["collider"]})
    assert "POST_TREATMENT_ADJUSTMENT" in {item["code"] for item in adjusted["violations"]}


def test_adjustment_enumeration_is_bounded_for_large_graphs() -> None:
    nodes = [{"id": "x", "observed": True}, {"id": "y", "observed": True}]
    nodes.extend({"id": f"z{index:02d}", "observed": True} for index in range(17))
    result = audit_causal_identification({
        "nodes": nodes, "edges": [], "exposure": "x", "outcome": "y",
        "proposed_adjustment_set": [], "assignment_type": "observational",
        "assumptions": _assumptions(),
        "causal_estimand": _estimand("y"),
    })
    assert result["adjustment_set_enumeration_status"] == "not_enumerated_more_than_16_observed_candidates"
    assert result["minimal_observed_adjustment_sets"] == []


def test_causal_assumption_register_requires_coverage_and_failure_plans() -> None:
    incomplete = _confounded(["baseline"])
    incomplete["assumptions"] = incomplete["assumptions"][:-1]
    result = audit_causal_identification(incomplete)
    assert result["missing_assumption_categories"] == ["exchangeability"]
    assert "ASSUMPTIONS_INCOMPLETE" in {
        item["code"] for item in result["violations"]
    }
    malformed = _confounded(["baseline"])
    malformed["assumptions"][0]["failure_response"] = " "
    with pytest.raises(ValidationError, match="failure_response"):
        audit_causal_identification(malformed)
    misclassified = _confounded(["baseline"])
    misclassified["assumptions"][0]["assessment_kind"] = "automatically_proven"
    with pytest.raises(ValidationError, match="unsupported causal assessment kind"):
        audit_causal_identification(misclassified)


def test_causal_estimand_is_structured_and_bound_to_graph_outcome() -> None:
    missing = _confounded(["baseline"])
    del missing["causal_estimand"]
    result = audit_causal_identification(missing)
    assert "ESTIMAND_MISSING" in {
        item["code"] for item in result["violations"]
    }
    mismatched = _confounded(["baseline"])
    mismatched["causal_estimand"]["outcome_variable"] = "baseline"
    result = audit_causal_identification(mismatched)
    assert "ESTIMAND_OUTCOME_MISMATCH" in {
        item["code"] for item in result["violations"]
    }
    duplicate_strategies = _confounded(["baseline"])
    duplicate_strategies["causal_estimand"]["exposure_strategies"] = [
        "same strategy", "same strategy"
    ]
    with pytest.raises(ValidationError, match="two distinct"):
        audit_causal_identification(duplicate_strategies)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda spec: spec["nodes"][0].update({"id": " treatment"}),
            "nodes\\[0\\].id",
        ),
        (
            lambda spec: spec.update({"exposure": "treatment "}),
            "exposure",
        ),
        (
            lambda spec: spec["edges"][0].update({"cause": " baseline"}),
            "edges\\[0\\].cause",
        ),
        (
            lambda spec: spec.update({"proposed_adjustment_set": [" baseline"]}),
            "proposed_adjustment_set item",
        ),
        (
            lambda spec: spec["assumptions"][0].update({"assessment_gate_id": " integrity"}),
            "assumptions\\[0\\].assessment_gate_id",
        ),
    ],
)
def test_causal_audit_rejects_noncanonical_graph_commitments(mutate, message) -> None:
    spec = _confounded(["baseline"])
    mutate(spec)
    with pytest.raises(ValidationError, match=message):
        audit_causal_identification(spec)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("target_hypothesis_id", " h1", "causal_estimand.target_hypothesis_id"),
        ("description", "Mean outcome difference, group a minus group b. ", "causal_estimand.description"),
        ("population", " Eligible study units in the registered setting.", "causal_estimand.population"),
        ("outcome_variable", "outcome ", "causal_estimand.outcome_variable"),
    ],
)
def test_causal_estimand_rejects_noncanonical_text(field, value, message) -> None:
    spec = _confounded(["baseline"])
    spec["causal_estimand"][field] = value
    with pytest.raises(ValidationError, match=message):
        audit_causal_identification(spec)


def test_causal_estimand_rejects_noncanonical_exposure_strategies() -> None:
    spec = _confounded(["baseline"])
    spec["causal_estimand"]["exposure_strategies"] = [
        "assign treatment",
        " assign control",
    ]
    with pytest.raises(ValidationError, match="canonical non-blank strategies"):
        audit_causal_identification(spec)


def test_provider_free_causal_audit_cli_hashes_its_input(tmp_path, capsys) -> None:
    path = tmp_path / "causal.json"
    path.write_text(json.dumps(_confounded(["baseline"])), encoding="utf-8")
    assert main(["--json", "design", "identify", "--spec-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["backdoor_criterion_satisfied"] is True
    assert result["provenance"]["specification"] == _confounded(["baseline"])
    assert len(result["provenance"]["specification_sha256"]) == 64
    assert result["provenance"]["scientific_evidence_eligible"] is False


def test_causal_protocol_freeze_binds_passing_graph_and_rejects_open_path(tmp_path) -> None:
    from dataclasses import fields, replace
    from research_machine.application.commands import CreateProtocol
    from research_machine.application.service import _protocol_commitment
    from test_ethics_gate import _human_protocol
    from test_execution import prepared_service

    service, hypothesis_id = prepared_service(tmp_path)
    base = _human_protocol(
        human_subjects=False, hypotheses_tested=[hypothesis_id], causal_claim=True,
        causal_identification=_confounded(["baseline"], hypothesis_id),
    )
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    draft = service.create_protocol(CreateProtocol(**values))
    frozen = service.freeze_protocol(draft.protocol_id)
    assert frozen.causal_identification_audit["backdoor_criterion_satisfied"] is True
    assert frozen.causal_identification_audit["scientific_evidence_eligible"] is False
    assert _protocol_commitment(frozen) == frozen.protocol_hash

    blocked_values = {**values, "experiment_id": "blocked-causal",
                      "causal_identification": _confounded(hypothesis_id=hypothesis_id)}
    blocked = service.create_protocol(CreateProtocol(**blocked_values))
    ledger = next(tmp_path.rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    with pytest.raises(ValidationError, match="OPEN_BACKDOOR_PATH"):
        service.freeze_protocol(blocked.protocol_id)
    assert ledger.read_bytes() == before

    incomplete_graph = _confounded(["baseline"], hypothesis_id)
    incomplete_graph["assumptions"] = incomplete_graph["assumptions"][:-1]
    incomplete = service.create_protocol(CreateProtocol(**{
        **values,
        "experiment_id": "incomplete-causal-assumptions",
        "causal_identification": incomplete_graph,
    }))
    before = ledger.read_bytes()
    with pytest.raises(ValidationError, match="ASSUMPTIONS_INCOMPLETE"):
        service.freeze_protocol(incomplete.protocol_id)
    assert ledger.read_bytes() == before

    wrong_target_graph = _confounded(["baseline"], "hyp-not-tested")
    wrong_target = service.create_protocol(CreateProtocol(**{
        **values,
        "experiment_id": "wrong-causal-target",
        "causal_identification": wrong_target_graph,
    }))
    with pytest.raises(ValidationError, match="target_hypothesis_id"):
        service.freeze_protocol(wrong_target.protocol_id)

    mismatched_estimand_graph = _confounded(["baseline"], hypothesis_id)
    mismatched_estimand_graph["causal_estimand"]["description"] = "A different causal estimand."
    mismatched_estimand = service.create_protocol(CreateProtocol(**{
        **values,
        "experiment_id": "mismatched-causal-estimand",
        "causal_identification": mismatched_estimand_graph,
    }))
    with pytest.raises(ValidationError, match="target hypothesis primary_estimand"):
        service.freeze_protocol(mismatched_estimand.protocol_id)


def test_protocol_freeze_policy_cannot_bypass_or_forge_causal_audit() -> None:
    from dataclasses import replace
    from research_machine.application.policies import validate_protocol_freeze
    from research_machine.domain.models import AnalysisContract
    from test_ethics_gate import _human_protocol

    graph = _confounded(["baseline"])
    protocol = _human_protocol(
        human_subjects=False,
        causal_claim=True,
        causal_identification=graph,
    )
    with pytest.raises(ValidationError, match="must exactly match"):
        validate_protocol_freeze(protocol)
    verified = replace(
        protocol,
        causal_identification_audit=audit_causal_identification(graph),
    )
    validate_protocol_freeze(verified)
    forged = replace(
        verified,
        causal_identification_audit={
            **verified.causal_identification_audit,
            "backdoor_criterion_satisfied": False,
        },
    )
    with pytest.raises(ValidationError, match="must exactly match"):
        validate_protocol_freeze(forged)
    with pytest.raises(ValidationError, match="assessment gates"):
        validate_protocol_freeze(replace(verified, quality_requirements=["other-gate"]))
    mismatched_contract = AnalysisContract(
        primary_hypothesis_id="h1", primary_measurement_id="outcome-measure",
        method="adjusted_linear_effect", outcome_column="outcome",
        group_column="treatment", groups=["treated", "control"],
        estimand=graph["causal_estimand"]["description"],
        missing_data_policy="complete_case", assignment_type="observational",
        effect_estimate_path="/result/effect", uncertainty_path="/result/interval",
        null_value=0.0, support_rule="interval_excludes_null",
        minimum_analyzable_units=10, maximum_excluded_fraction=0.1,
        maximum_group_excluded_fraction_difference=0.1,
        missingness_assumption="Excluded records do not materially distort the registered contrast.",
        missingness_assessment_plan="Inspect total and group-specific exclusions before interpretation.",
        missingness_failure_response="Stop primary interpretation if missingness is not defensible.",
        missingness_assessment_kind="empirical_diagnostic",
        missingness_assessment_gate_id="missingness-assessed",
        adjustment_columns=[],
    )
    with pytest.raises(ValidationError, match="exactly match"):
        validate_protocol_freeze(replace(
            verified, analysis_contract=mismatched_contract,
            quality_requirements=["integrity", "missingness-assessed"],
        ))
    matching_contract = replace(mismatched_contract, adjustment_columns=["baseline"])
    with pytest.raises(ValidationError, match="exposure and outcome nodes"):
        validate_protocol_freeze(replace(
            verified,
            analysis_contract=replace(matching_contract, group_column="assigned_arm"),
            quality_requirements=["integrity", "missingness-assessed"],
        ))
    with pytest.raises(ValidationError, match="must be dedicated"):
        validate_protocol_freeze(replace(
            verified,
            analysis_contract=replace(
                matching_contract, missingness_assessment_gate_id="integrity"
            ),
        ))
    with pytest.raises(ValidationError, match="missingness_assessment_kind"):
        validate_protocol_freeze(replace(
            verified,
            analysis_contract=replace(
                matching_contract, missingness_assessment_kind="automatically_proven"
            ),
            quality_requirements=["integrity", "missingness-assessed"],
        ))


def test_causal_run_requires_artifact_bound_results_for_every_assumption(tmp_path) -> None:
    import hashlib
    from dataclasses import fields, replace
    from research_machine.application.commands import CreateProtocol, RecordRun, RegisterDataset
    from research_machine.domain.models import (
        DatasetArtifact, DatasetRole, QualityGateResult, QualityGateStatus, RunStatus,
    )
    from test_ethics_gate import _human_protocol
    from test_execution import prepared_service

    service, hypothesis_id = prepared_service(tmp_path)
    base = _human_protocol(
        human_subjects=False,
        hypotheses_tested=[hypothesis_id],
        causal_claim=True,
        causal_identification=_confounded(["baseline"], hypothesis_id),
    )
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    protocol = service.freeze_protocol(
        service.create_protocol(CreateProtocol(**values)).protocol_id
    )
    observations = tmp_path / "observations.csv"
    observations.write_text("unit,group,outcome\nu1,a,1\nu2,b,2\n")
    dataset = service.register_dataset(RegisterDataset(
        dataset_id="causal-confirmatory-data",
        name="Causal confirmatory fixture",
        role=DatasetRole.CONFIRMATORY,
        artifacts=[DatasetArtifact(
            "observations.csv",
            hashlib.sha256(observations.read_bytes()).hexdigest(),
            observations.stat().st_size,
            "text/csv",
        )],
        artifact_root=str(tmp_path),
        protocol_id=protocol.protocol_id,
        observation_unit="Participant",
    ))
    evidence_sha = "c" * 64
    assumption_results = {
        item["category"]: {
            "observed_diagnostic": f"Recorded diagnostic for {item['category']}.",
            "interpretation": f"No registered contradiction to {item['category']} was observed.",
            "assessment_status": "consistent_with_assumption",
            "assessment_kind": item["assessment_kind"],
            "evidence_sha256": evidence_sha,
            "evidence_location": f"/diagnostics/{item['category']}",
        }
        for item in protocol.causal_identification_audit["assumption_register"]
    }
    control_results = {
        "reference-1": {
            "observed_behavior": "Registered reference response.",
            "interpretation": "The reference behaved as registered.",
            "matches_expected": True,
            "evidence_sha256": evidence_sha,
            "evidence_location": "/controls/reference-1",
        }
    }
    template_gate = service.run_record_template(protocol.protocol_id)["record"]["quality_gates"][0]
    assert set(template_gate["details"]["causal_assumption_results"]) == set(assumption_results)
    assert set(template_gate["details"]["temporal_order_assessment"]) == {
        "locator",
        "sha256",
        "status",
        "timing_assessment_sha256",
        "specification_sha256",
    }
    assert set(template_gate["details"]["stream_timing_assessment"]) == {
        "locator",
        "sha256",
        "status",
        "inspection_sha256",
        "specification_sha256",
    }
    assert set(template_gate["details"]["instrument_inspection"]) == {
        "locator",
        "sha256",
        "status",
        "source_sha256",
        "config_sha256",
        "implementation_sha256",
    }
    assert template_gate["status"] == "skipped"

    def command(results):
        return RecordRun(
            protocol_id=protocol.protocol_id,
            started_at="2026-09-05T12:01:00Z",
            completed_at="2026-09-05T12:02:00Z",
            analysis_code_hash="a" * 64,
            environment_hash="b" * 64,
            dataset_ids=[dataset.dataset_id],
            output_artifacts=[DatasetArtifact("causal-diagnostics.json", evidence_sha)],
            quality_gates=[QualityGateResult(
                "integrity", QualityGateStatus.PASSED, "Causal diagnostics reviewed.",
                details={
                    "evidence_sha256": evidence_sha,
                    "control_results": control_results,
                    "causal_assumption_results": results,
                },
            )],
        )

    run = service.record_run(command(assumption_results))
    assert run.status is RunStatus.COMPLETED
    synthesis = service.build_synthesis()["content"]
    assert "Causal assumption assessment provenance" in synthesis
    assert "design_record_review=7" in synthesis
    assert "`/diagnostics/positivity`" in synthesis

    failed_results = {key: dict(value) for key, value in assumption_results.items()}
    failed_results["positivity"]["assessment_status"] = "contradicted_assumption"
    failed_results["positivity"]["interpretation"] = (
        "The registered positivity diagnostic contradicted the assumption."
    )
    failed = replace(command(failed_results), quality_gates=[QualityGateResult(
        "integrity", QualityGateStatus.FAILED,
        "At least one causal assumption was contradicted.",
        details={
            "causal_assumption_results": failed_results,
        },
    )])
    failed_run = service.record_run(failed)
    assert failed_run.status is RunStatus.INVALID
    assert failed_run.scientific_evidence_eligible is False
    failed_synthesis = service.build_synthesis()["content"]
    assert "contradicted_assumption" in failed_synthesis

    unstructured_failure = replace(command({}), quality_gates=[QualityGateResult(
        "integrity", QualityGateStatus.FAILED,
        "An assessment failed without structured results.",
    )])
    with pytest.raises(ValidationError, match="requires exact results"):
        service.record_run(unstructured_failure)

    inconclusive_results = {
        key: dict(value) for key, value in assumption_results.items()
    }
    inconclusive_results["positivity"]["assessment_status"] = "inconclusive"
    warning = replace(command(inconclusive_results), quality_gates=[QualityGateResult(
        "integrity", QualityGateStatus.WARNING,
        "The positivity assessment was inconclusive.",
        details={"causal_assumption_results": inconclusive_results},
    )])
    warning_run = service.record_run(warning)
    assert warning_run.status is RunStatus.INVALID

    mislabeled_failure = replace(command(assumption_results), quality_gates=[QualityGateResult(
        "integrity", QualityGateStatus.FAILED,
        "Failure label without a contradicted result.",
        details={"causal_assumption_results": assumption_results},
    )])
    with pytest.raises(ValidationError, match="requires at least one contradicted_assumption"):
        service.record_run(mislabeled_failure)

    missing = dict(assumption_results)
    del missing["positivity"]
    with pytest.raises(ValidationError, match="requires exact results"):
        service.record_run(command(missing))
    unlocated = {key: dict(value) for key, value in assumption_results.items()}
    unlocated["positivity"]["evidence_location"] = ""
    with pytest.raises(ValidationError, match="evidence_location"):
        service.record_run(command(unlocated))
    relabeled = {key: dict(value) for key, value in assumption_results.items()}
    relabeled["positivity"]["assessment_kind"] = "empirical_diagnostic"
    with pytest.raises(ValidationError, match="does not match the frozen"):
        service.record_run(command(relabeled))
    contradicted = {key: dict(value) for key, value in assumption_results.items()}
    contradicted["positivity"]["assessment_status"] = "violated"
    with pytest.raises(ValidationError, match="unsupported assessment_status"):
        service.record_run(command(contradicted))

    passed_contradiction = {
        key: dict(value) for key, value in assumption_results.items()
    }
    passed_contradiction["positivity"]["assessment_status"] = (
        "contradicted_assumption"
    )
    with pytest.raises(ValidationError, match="requires every result"):
        service.record_run(command(passed_contradiction))

    warning_contradiction = replace(
        command(passed_contradiction),
        quality_gates=[QualityGateResult(
            "integrity", QualityGateStatus.WARNING,
            "A contradiction cannot be downgraded to a warning.",
            details={"causal_assumption_results": passed_contradiction},
        )],
    )
    with pytest.raises(ValidationError, match="no contradicted assumptions"):
        service.record_run(warning_contradiction)

    failed_inconclusive = replace(
        command(inconclusive_results),
        quality_gates=[QualityGateResult(
            "integrity", QualityGateStatus.FAILED,
            "An inconclusive result alone cannot be upgraded to contradiction.",
            details={"causal_assumption_results": inconclusive_results},
        )],
    )
    with pytest.raises(ValidationError, match="requires at least one contradicted_assumption"):
        service.record_run(failed_inconclusive)

    extra = {key: dict(value) for key, value in assumption_results.items()}
    extra["unregistered_assumption"] = dict(extra["positivity"])
    with pytest.raises(ValidationError, match="requires exact results"):
        service.record_run(command(extra))


def test_causal_evidence_authority_requires_claim_protocol_handoff_and_method_ceiling() -> None:
    from dataclasses import replace
    from research_machine.application.policies import validate_validation_tag_context
    from research_machine.domain.models import (
        AnalysisContract, AnalysisMode, Claim, ClaimLevel, DatasetArtifact,
        DatasetManifest, DatasetRole, Hypothesis, HypothesisWorkflowState,
        ProtocolStatus, ResearchRun, ValidationTag,
    )
    from test_ethics_gate import _human_protocol

    graph = _confounded(["baseline"])
    contract = AnalysisContract(
        primary_hypothesis_id="h1", primary_measurement_id="outcome-measure",
        method="independent_mean_difference_ci", outcome_column="outcome",
        group_column="treatment", groups=["a", "b"],
        estimand=graph["causal_estimand"]["description"],
        missing_data_policy="complete_case", assignment_type="observational",
        effect_estimate_path="/result/effect", uncertainty_path="/result/interval",
        null_value=0.0, support_rule="interval_excludes_null",
        minimum_analyzable_units=10, maximum_excluded_fraction=0.1,
        maximum_group_excluded_fraction_difference=0.1,
        missingness_assumption="Excluded records do not materially distort the registered contrast.",
        missingness_assessment_plan="Inspect total and group-specific exclusions before interpretation.",
        missingness_failure_response="Stop primary interpretation if missingness is not defensible.",
        missingness_assessment_kind="empirical_diagnostic",
        missingness_assessment_gate_id="missingness-assessed",
        adjustment_columns=["baseline"],
    )
    protocol = _human_protocol(
        human_subjects=False, causal_claim=True, causal_identification=graph,
        causal_identification_audit=audit_causal_identification(graph),
        analysis_contract=contract, status=ProtocolStatus.FROZEN,
        quality_requirements=["integrity", "missingness-assessed"],
    )
    hypothesis = Hypothesis(
        "h1", "Treatment changes outcome.", "2026-09-01T00:00:00Z", "researcher",
        primary_estimand=graph["causal_estimand"]["description"],
        workflow_state=HypothesisWorkflowState.ACTIVE,
    )
    claim = Claim(
        "claim-causal", "Treatment causes the registered outcome contrast.",
        ClaimLevel.CAUSAL_DIRECTION, "2026-09-01T00:00:00Z",
    )
    dataset = DatasetManifest(
        "data", "Observed data", DatasetRole.CONFIRMATORY,
        "2026-09-02T00:00:00Z", [DatasetArtifact("data.csv", "d" * 64)],
    )
    run = ResearchRun(
        "run", protocol.protocol_id, "f" * 64, AnalysisMode.CONFIRMATORY,
        "2026-09-02T01:00:00Z", "2026-09-02T02:00:00Z", "analyst",
        "a" * 64, "b" * 64, dataset_ids=[dataset.dataset_id],
        scientific_evidence_eligible=True,
        metadata={"execution_handoff": {"result": {
            "maximum_inference_level": "design_conditional_effect"
        }}},
    )
    tags = [ValidationTag.EMPIRICAL_TEST, ValidationTag.CAUSAL_ESTIMATE]
    validate_validation_tag_context(
        tags=tags, hypothesis=hypothesis, exploratory=False, protocol=protocol,
        run=run, datasets=[dataset], controls_passed=["Control condition"],
        replicated_run=None, claim=claim,
    )
    with pytest.raises(ValidationError, match="requires the causal_estimate"):
        validate_validation_tag_context(
            tags=[ValidationTag.EMPIRICAL_TEST], hypothesis=hypothesis,
            exploratory=False, protocol=protocol, run=run, datasets=[dataset],
            controls_passed=["Control condition"], replicated_run=None, claim=claim,
        )
    association_run = replace(run, metadata={"execution_handoff": {"result": {
        "maximum_inference_level": "association"
    }}})
    with pytest.raises(ValidationError, match="does not permit"):
        validate_validation_tag_context(
            tags=tags, hypothesis=hypothesis, exploratory=False, protocol=protocol,
            run=association_run, datasets=[dataset], controls_passed=["Control condition"],
            replicated_run=None, claim=claim,
        )
    mismatched_protocol = replace(
        protocol,
        analysis_contract=replace(contract, adjustment_columns=[]),
    )
    with pytest.raises(ValidationError, match="do not match the frozen adjustment set"):
        validate_validation_tag_context(
            tags=tags, hypothesis=hypothesis, exploratory=False,
            protocol=mismatched_protocol, run=run, datasets=[dataset],
            controls_passed=["Control condition"], replicated_run=None, claim=claim,
        )


def test_observational_causal_adjustment_executes_the_exact_frozen_covariates(
    tmp_path, capsys
) -> None:
    import hashlib
    from dataclasses import fields, replace

    from research_machine.addons.execution import _implementation_hash
    from research_machine.addons.general_science import adjusted_linear_effect
    from research_machine.application.commands import (
        CreateProtocol, ProposeHypothesis, RegisterDataset,
    )
    from research_machine.domain.models import (
            AnalysisContract, ConclusionContract, DatasetArtifact, DatasetRole,
            EvidenceDirection, ClaimLevel, MeasurementDefinition,
            MeasurementRole, ProtocolKind,
    )
    from test_ethics_gate import _human_protocol
    from test_execution import prepared_service
    from test_protocol_design_structure import _analysis_measurements

    workspace = tmp_path / "workspace"
    service, shared_hypothesis_id = prepared_service(workspace)
    template_graph = _confounded(["baseline"], shared_hypothesis_id)
    hypothesis = service.propose_hypothesis(ProposeHypothesis(
        statement="Treatment changes the registered outcome.",
        observable_prediction="The adjusted treated-minus-control interval excludes zero.",
        null_model="The adjusted treated-minus-control effect is zero.",
        primary_estimand=template_graph["causal_estimand"]["description"],
        contrast_definition="treated minus control",
        contrast_groups=["treated", "control"],
        expected_effect_direction="two_sided",
        falsification_conditions=["The registered interval remains compatible with the null."],
    ))
    service.activate_hypothesis(hypothesis.hypothesis_id)
    hypothesis_id = hypothesis.hypothesis_id
    graph = _confounded(["baseline"], hypothesis_id)
    _, implementation_sha256 = _implementation_hash(adjusted_linear_effect)
    specification = {
        "method": "adjusted_linear_effect",
        "study_design": "independent_groups",
        "outcome_column": "outcome",
        "group_column": "treatment",
        "groups": ["treated", "control"],
        "covariate_columns": ["baseline"],
        "unit_column": "unit",
        "missing_data_policy": "complete_case",
        "confidence_level": 0.95,
        "estimand": graph["causal_estimand"]["description"],
        "contrast_definition": "treated minus control",
        "claim_ceiling": "Synthetic pipeline fixture only.",
    }
    specification_bytes = json.dumps(specification).encode()
    base = _human_protocol(
        human_subjects=False,
        protocol_kind=ProtocolKind.OBSERVATIONAL,
        hypotheses_tested=[hypothesis_id],
        causal_claim=True,
        causal_identification=graph,
        title="Synthetic adjusted causal pipeline fixture",
        experiment_id="synthetic-adjusted-causal-pipeline",
        sampling_unit="person",
        independent_unit="person",
        methodology="Synthetic fixture for causal adjustment binding; not a study.",
    )
    values = {field.name: getattr(base, field.name) for field in fields(CreateProtocol)}
    measurements = _analysis_measurements(base.primary_outcome, base.controls[0])
    measurements[0] = replace(measurements[0], temporal_role="post_exposure")
    measurements.extend([
        MeasurementDefinition(
            "exposure-measurement", MeasurementRole.EXPOSURE, "treatment",
            "Observed registered treatment-group label", "At registered time zero",
            {"levels": "treated, control"}, "At assignment ascertainment",
            "treated is contrasted against control", "one label per person",
            "exact registered label", "Both registered groups remain reportable",
            "treatment", "at_exposure",
            "nominal", "category", ["treated", "control"], None, None, ["<blank>"],
        ),
        MeasurementDefinition(
            "baseline-measurement", MeasurementRole.COVARIATE, "baseline",
            "Numeric baseline score", "Before treatment ascertainment",
            {"unit": "fixture score units"}, "Registered baseline visit",
            "higher values are larger", "one value per person",
            "exact fixture parsing", "Retain regardless of outcome direction",
            "baseline", "pre_exposure",
            "interval", "fixture score units", [], -10.0, 10.0, ["<blank>"],
        ),
    ])
    contract = AnalysisContract(
        primary_hypothesis_id=hypothesis_id,
        primary_measurement_id="primary-measurement",
        method="adjusted_linear_effect",
        outcome_column="outcome",
        group_column="treatment",
        groups=["treated", "control"],
        adjustment_columns=["baseline"],
        estimand=graph["causal_estimand"]["description"],
        contrast_definition="treated minus control",
        contrast_groups=["treated", "control"],
        missing_data_policy="complete_case",
        assignment_type="observational",
        effect_estimate_path="/result/adjusted_mean_difference_first_minus_second",
        uncertainty_path="/result/robust_confidence_interval",
        null_value=0.0,
        support_rule="interval_excludes_null",
        minimum_analyzable_units=2,
        maximum_excluded_fraction=0.1,
        maximum_group_excluded_fraction_difference=0.1,
        missingness_assumption="Excluded records do not materially distort the registered contrast.",
        missingness_assessment_plan="Inspect total and group-specific exclusions before interpretation.",
        missingness_failure_response="Stop primary interpretation if missingness is not defensible.",
        missingness_assessment_kind="empirical_diagnostic",
        missingness_assessment_gate_id="missingness-assessed",
    )
    common = {
        **values,
        "analysis_design": "independent_groups",
        "unit_id_column": "unit",
        "analysis_code_hash": implementation_sha256,
        "analysis_specification_sha256": hashlib.sha256(specification_bytes).hexdigest(),
            "analysis_contract": contract,
            "conclusion_contract": ConclusionContract(
                primary_hypothesis_id=hypothesis_id,
                decision_rule="interval_and_practical_significance",
                smallest_effect_size_of_interest=1.0,
                effect_scale="adjusted mean difference",
                effect_unit="fixture units",
                population=graph["causal_estimand"]["population"],
                setting="The registered synthetic observational fixture.",
                time_window=graph["causal_estimand"]["outcome_time"],
                non_supporting_direction=EvidenceDirection.INCONCLUSIVE,
                permitted_claim_level=ClaimLevel.CAUSAL_DIRECTION,
                higher_level_conclusions_unsupported=[
                    "No mechanism, adaptation, intent, or out-of-scope generalization."
                ],
            ),
            "quality_requirements": ["integrity", "missingness-assessed"],
    }
    missing_covariate_measurement = service.create_protocol(CreateProtocol(**{
        **common,
        "experiment_id": "synthetic-adjusted-missing-covariate-measurement",
        "measurement_definitions": measurements[:-1],
    }))
    with pytest.raises(ValidationError, match="causal exposure and adjustment"):
        service.freeze_protocol(missing_covariate_measurement.protocol_id)
    wrong_covariate_column = [
        *measurements[:-1],
        MeasurementDefinition(
            **{
                **measurements[-1].to_dict(),
                "role": MeasurementRole.COVARIATE,
                "data_column": "post_treatment_baseline",
            }
        ),
    ]
    mismatched_measurement = service.create_protocol(CreateProtocol(**{
        **common,
        "experiment_id": "synthetic-adjusted-mismatched-covariate-measurement",
        "measurement_definitions": wrong_covariate_column,
    }))
    with pytest.raises(ValidationError, match="exactly map"):
        service.freeze_protocol(mismatched_measurement.protocol_id)
    for suffix, index, temporal_role, message in [
        ("unsupported", 0, "after_treatment_sometime", "supported temporal role"),
        ("outcome", 0, "at_exposure", "primary-outcome measurement temporal_role"),
        ("exposure", 2, "post_exposure", "exposure measurement temporal_role"),
        ("covariate", 3, "post_exposure", "adjustment covariate measurements"),
    ]:
        invalid_timing = list(measurements)
        invalid_timing[index] = replace(
            invalid_timing[index], temporal_role=temporal_role
        )
        timing_draft = service.create_protocol(CreateProtocol(**{
            **common,
            "experiment_id": f"synthetic-adjusted-invalid-{suffix}-timing",
            "measurement_definitions": invalid_timing,
        }))
        with pytest.raises(ValidationError, match=message):
            service.freeze_protocol(timing_draft.protocol_id)
    draft = service.create_protocol(CreateProtocol(**{
        **common,
        "measurement_definitions": measurements,
    }))
    frozen = service.freeze_protocol(draft.protocol_id)
    data = tmp_path / "observations.csv"
    rows = []
    for treatment, label in ((0, "control"), (1, "treated")):
        for index, (baseline, noise) in enumerate(
            [(-2, -1), (-1, 1), (1, 1), (2, -1)]
        ):
            outcome = 10 + 2 * treatment + 3 * baseline + noise
            rows.append(f"{label}-{index},{label},{baseline},{outcome}")
    data.write_text(
        "unit,treatment,baseline,outcome\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    dataset = service.register_dataset(RegisterDataset(
        name="Synthetic adjusted observations",
        role=DatasetRole.CONFIRMATORY,
        protocol_id=frozen.protocol_id,
        synthetic=True,
        artifacts=[DatasetArtifact(
            "observations.csv", hashlib.sha256(data.read_bytes()).hexdigest(),
            size_bytes=len(data.read_bytes()), media_type="text/csv",
        )],
    ))
    spec_path = tmp_path / "analysis.json"
    spec_path.write_bytes(specification_bytes)
    output = tmp_path / "analysis-output"
    assert main([
        "--workspace", str(workspace), "--json", "analysis", "run",
        "--spec-file", str(spec_path), "--data-file", str(data),
        "--output", str(output), "--protocol", frozen.protocol_id,
        "--dataset", dataset.dataset_id,
    ]) == 0
    execution = json.loads(capsys.readouterr().out)["result"]
    assert execution["result"]["result"][
        "adjusted_mean_difference_first_minus_second"
    ] == pytest.approx(2)
    binding = execution["receipt"]["protocol_design_check"]
    assert binding["executed_analysis_semantics"]["covariate_columns"] == ["baseline"]
    assert binding["analysis_contract"]["adjustment_columns"] == ["baseline"]
    receipt_hash = hashlib.sha256(
        (output / "execution-receipt.json").read_bytes()
    ).hexdigest()
    assert main([
        "--workspace", str(workspace), "--json", "analysis", "run-draft",
        "--execution-directory", str(output),
        "--expected-receipt-sha256", receipt_hash,
    ]) == 0
    run_draft = json.loads(capsys.readouterr().out)["result"]
    record = run_draft["record"]
    record["environment_hash"] = "e" * 64
    record["summary"] = "Synthetic adjusted workflow with reviewed fixture diagnostics."
    analysis_output_sha256 = execution["receipt"]["output"]["sha256"]
    gate = record["quality_gates"][0]
    gate["status"] = "passed"
    gate["summary"] = "Synthetic causal diagnostics inspected for workflow validation."
    gate["details"]["evidence_sha256"] = analysis_output_sha256
    gate["details"]["control_results"]["reference-1"] = {
        "observed_behavior": "Synthetic reference remained reportable.",
        "interpretation": "Fixture-only control behavior matched its expectation.",
        "matches_expected": True,
        "evidence_sha256": analysis_output_sha256,
        "evidence_location": "/result/diagnostics",
    }
    missingness_gate = next(
        item for item in record["quality_gates"]
        if item["gate_id"] == "missingness-assessed"
    )
    missingness_gate["status"] = "passed"
    missingness_gate["summary"] = "Synthetic missingness diagnostics inspected."
    missingness_gate["details"]["evidence_sha256"] = analysis_output_sha256
    missingness_gate["details"]["missingness_assessment_result"] = {
        "observed_diagnostic": "Synthetic exclusion report reviewed.",
        "interpretation": "No fixture contradiction to the registered assumption was encoded.",
        "assessment_status": "consistent_with_assumption",
        "assessment_kind": "empirical_diagnostic",
        "evidence_sha256": analysis_output_sha256,
        "evidence_location": "/result/exclusion_report",
    }
    for category in gate["details"]["causal_assumption_results"]:
        gate["details"]["causal_assumption_results"][category] = {
            "observed_diagnostic": f"Synthetic diagnostic reviewed for {category}.",
            "interpretation": "No fixture contradiction was encoded.",
            "assessment_status": "consistent_with_assumption",
            "assessment_kind": "design_record_review",
            "evidence_sha256": analysis_output_sha256,
            "evidence_location": "/result/diagnostics",
        }
    gate["details"].pop("stream_timing_assessment", None)
    gate["details"].pop("temporal_order_assessment", None)
    gate["details"].pop("instrument_inspection", None)
    record_path = tmp_path / "causal-run-record.json"
    preflight = [
        "--workspace", str(workspace), "--json", "run", "preflight",
        "--record-file", str(record_path), "--artifact-root", str(output),
    ]
    missingness_gate["details"]["missingness_assessment_result"][
        "evidence_location"
    ] = "/result/not-a-missingness-diagnostic"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert main(preflight) == 2
    assert "does not resolve" in capsys.readouterr().err
    missingness_gate["details"]["missingness_assessment_result"][
        "evidence_location"
    ] = "/result/exclusion_report"
    saved_missingness_result = dict(
        missingness_gate["details"]["missingness_assessment_result"]
    )
    missingness_gate["details"].pop("missingness_assessment_result")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert main(preflight) == 2
    assert "missingness assessment gate" in capsys.readouterr().err
    missingness_gate["details"]["missingness_assessment_result"] = dict(
        saved_missingness_result
    )
    missingness_gate["details"]["missingness_assessment_result"][
        "assessment_kind"
    ] = "substantive_judgment"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert main(preflight) == 2
    assert "does not match the frozen" in capsys.readouterr().err
    missingness_gate["details"]["missingness_assessment_result"] = dict(
        saved_missingness_result
    )
    missingness_gate["status"] = "warning"
    missingness_gate["details"]["missingness_assessment_result"][
        "assessment_status"
    ] = "inconclusive"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert main(preflight) == 1
    warning_preflight = json.loads(capsys.readouterr().out)["result"]
    assert warning_preflight["status"] == "would_record_invalid"
    missingness_gate["status"] = "passed"
    missingness_gate["details"]["missingness_assessment_result"] = dict(
        saved_missingness_result
    )
    gate["details"]["control_results"]["reference-1"][
        "evidence_location"
    ] = "/result/not-a-control-diagnostic"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert main(preflight) == 2
    assert "does not resolve" in capsys.readouterr().err
    gate["details"]["control_results"]["reference-1"][
        "evidence_location"
    ] = "/result/diagnostics"
    gate["details"]["causal_assumption_results"]["positivity"][
        "evidence_location"
    ] = "/result/not-a-diagnostic"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert main(preflight) == 2
    assert "does not resolve" in capsys.readouterr().err
    gate["details"]["causal_assumption_results"]["positivity"][
        "evidence_location"
    ] = "/result/diagnostics"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert main(preflight) == 0
    preflight_result = json.loads(capsys.readouterr().out)["result"]
    assert preflight_result["status"] == "ready"
    assert preflight_result["scientific_evidence_eligible_if_submitted"] is False
    assert main([
        "--workspace", str(workspace), "--json", "run", "record",
        "--record-file", str(record_path), "--artifact-root", str(output),
    ]) == 0
    recorded = json.loads(capsys.readouterr().out)["result"]
    assert recorded["status"] == "completed"
    synthesis = service.build_synthesis()["content"]
    assert "Missingness assessment provenance" in synthesis
    assert "via dedicated gate `missingness-assessed`" in synthesis
    assert "`/result/exclusion_report`" in synthesis
