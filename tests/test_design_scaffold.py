from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_machine.interfaces.cli import main
import pytest
from research_machine.design.scaffold import scaffold_design


def _secondary_measurement(outcome: str, column: str, **overrides):
    value = {
        "outcome": outcome, "observable": f"Recorded {outcome}",
        "input_condition": "All eligible units at the endpoint",
        "parameter_values": {"instrument": "registered fixture"},
        "evaluation_point": "Registered endpoint", "convention": "Higher is larger",
        "aggregation": "One value per independent unit", "tolerance": "Exact parsing",
        "expected_behavior": "Report regardless of direction", "data_column": column,
        "temporal_role": "not_applicable", "scale_type": "interval", "unit": "points",
        "admissible_values": [], "valid_min": 0.0, "valid_max": 100.0,
        "missing_value_codes": ["<blank>"],
    }
    return {**value, **overrides}


def _control_measurement(control: str, column: str = "", **overrides):
    value = _secondary_measurement(control, column)
    value["control"] = value.pop("outcome")
    if not column:
        value.update({
            "scale_type": "", "unit": "", "admissible_values": [],
            "valid_min": None, "valid_max": None, "missing_value_codes": [],
        })
    return {**value, **overrides}


def _causal_measurement(variable: str, role: str, column: str, **overrides):
    value = _secondary_measurement(variable, column)
    value["variable"] = value.pop("outcome")
    value["role"] = role
    value["temporal_role"] = "at_exposure" if role == "exposure" else "pre_exposure"
    if role == "exposure":
        value.update({
            "scale_type": "nominal", "unit": "assigned level",
            "admissible_values": ["treated", "control"],
            "valid_min": None, "valid_max": None,
        })
    return {**value, **overrides}


def _validity_check(check_id: str = "primary-validity", gate_id: str = "primary-validity-assessed"):
    return {
        "check_id": check_id,
        "evidence_type": "criterion",
        "validity_claim": "The recorded outcome agrees sufficiently with a traceable reference.",
        "assessment_plan": "Compare a blinded prespecified subset against the reference before analysis unlock.",
        "acceptance_criterion": "Absolute disagreement is at most 2 mm for at least 95% of checked units.",
        "failure_response": "Stop primary interpretation and investigate the measurement process.",
        "assessment_gate_id": gate_id,
    }


def _digest(value):
    if isinstance(value, str):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rendered_digest(value):
    if isinstance(value, str):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    encoded = (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_scaffold_binds_review_artifacts_to_brief_and_findings():
    brief = {
        "title": "Provenance fixture",
        "question": "Does the fixture preserve its design audit?",
        "decision": "Decide whether the scaffold is reviewable.",
        "outcome": "review trace",
        "unit_of_observation": "draft artifact",
        "human_participants": False,
    }

    result = scaffold_design(brief)

    provenance = result["provenance"]
    draft_anchor = {
        key: value
        for key, value in provenance.items()
        if key != "artifact_manifest_sha256"
    }
    assert provenance["brief_content_sha256"] == _digest(brief)
    assert provenance["design_findings_sha256"] == _digest(result["findings"])
    assert provenance["authority"] == "review_only"
    assert provenance["scientific_evidence_eligible"] is False

    protocol = result["artifacts"]["protocol-draft.json"]
    assert protocol["scaffold_provenance"] == draft_anchor

    manifest = result["artifacts"]["design-scaffold-provenance.json"]
    assert manifest["brief_content_sha256"] == provenance["brief_content_sha256"]
    assert manifest["design_findings_sha256"] == provenance["design_findings_sha256"]
    assert manifest["artifact_manifest_sha256"] == provenance["artifact_manifest_sha256"]
    assert manifest["scientific_evidence_eligible"] is False
    manifest_entries = {
        entry["name"]: entry for entry in manifest["artifact_manifest"]
    }
    assert "design-scaffold-provenance.json" not in manifest_entries
    assert manifest_entries["protocol-draft.json"]["content_sha256"] == _rendered_digest(protocol)
    assert manifest_entries["collection-plan.md"]["content_sha256"] == _rendered_digest(
        result["artifacts"]["collection-plan.md"]
    )


def test_measurement_columns_are_explicit_unique_and_not_reserved():
    base = {
        "title": "Column fixture", "question": "Question", "decision": "Decision",
        "outcome": "Primary score", "unit_of_observation": "unit",
        "human_participants": False, "outcome_data_column": "primary_score",
    }
    explicit = scaffold_design(base)
    assert explicit["artifacts"]["measurement-definition-draft.json"]["data_column"] == "primary_score"
    proposed = explicit["artifacts"]["data-dictionary-draft.json"]["proposed_columns"]
    assert "primary_score" in {item["name"] for item in proposed}

    collision = scaffold_design({
        **base,
        "secondary_outcomes": ["Response time"],
        "secondary_measurements": [
            _secondary_measurement("Response time", "PRIMARY_SCORE"),
        ],
    })
    assert "MEASUREMENT_COLUMN_COLLISION" in {
        item["code"] for item in collision["findings"]
    }
    proposed = collision["artifacts"]["data-dictionary-draft.json"]["proposed_columns"]
    assert any(
        item["name"] == "PRIMARY_SCORE" and item["role"] == "secondary_outcome"
        for item in proposed
    )

    reserved = scaffold_design({**base, "outcome_data_column": "unit_id"})
    assert "MEASUREMENT_COLUMN_RESERVED" in {
        item["code"] for item in reserved["findings"]
    }


def test_required_brief_fields_must_be_canonical_before_drafting():
    padded = scaffold_design({
        "title": " Core fixture ",
        "question": " Does the intervention change the score?",
        "decision": "Choose a strategy ",
        "outcome": " Score",
        "unit_of_observation": "unit ",
        "human_participants": False,
    })
    assert "CORE_BRIEF_FIELD_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }
    assert padded["status"] == "blocked"
    assert padded["artifacts"]["protocol-draft.json"]["title"].startswith(" ")
    assert padded["artifacts"]["hypothesis-proposal.json"]["statement"].endswith(
        "score?"
    )
    assert padded["artifacts"]["hypothesis-proposal.json"]["statement"].startswith(
        "[REVIEW REQUIRED]  "
    )


def test_primary_observable_is_not_substituted_by_validity_evidence():
    base = {
        "title": "Construct fixture", "question": "Question", "decision": "Decision",
        "outcome": "Height", "unit_of_observation": "pot",
        "human_participants": False, "study_type": "correlational",
        "measurement_validity": "Compare a blinded subset with a traceable reference ruler.",
        "outcome_data_column": "height_mm",
        "measurement_input_condition": "Eligible pots at day seven",
        "measurement_parameter_values": {"ruler_resolution": "1 mm"},
        "measurement_evaluation_point": "Day seven",
        "measurement_convention": "Millimetres upward from the stem mark",
        "measurement_aggregation": "Mean of two readings per pot",
        "measurement_tolerance": "Readings agree within 2 mm",
        "measurement_expected_behavior": "Retain all valid readings",
        "measurement_temporal_role": "not_applicable",
    }
    unresolved = scaffold_design(base)
    assert "MEASUREMENT_CONTRACT_INCOMPLETE" in {
        item["code"] for item in unresolved["findings"]
    }
    draft = unresolved["artifacts"]["measurement-definition-draft.json"]
    assert draft["observable"].startswith("[REVIEW REQUIRED]")
    assert unresolved["artifacts"]["data-dictionary-draft.json"]["measurement_validity"].startswith("Compare")

    complete = scaffold_design({
        **base, "measurement_observable": "Mean marked-stem height in millimetres",
    })
    assert "MEASUREMENT_CONTRACT_INCOMPLETE" not in {
        item["code"] for item in complete["findings"]
    }
    assert complete["artifacts"]["measurement-definition-draft.json"]["observable"] == (
        "Mean marked-stem height in millimetres"
    )
    padded = scaffold_design({
        **base,
        "measurement_observable": " Mean marked-stem height in millimetres ",
        "measurement_parameter_values": {" ruler_resolution": "1 mm "},
    })
    assert "MEASUREMENT_CONTRACT_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }


def test_prospective_text_commitments_must_be_canonical_before_drafting():
    brief = {
        "title": "Commitment fixture",
        "question": "Question",
        "decision": "Decision",
        "study_type": "causal",
        "assignment_type": "observational",
        "exposure_definition": "Observed treatment",
        "comparison": "No treatment",
        "outcome": "Score",
        "outcome_unit": "points",
        "unit_of_observation": "unit",
        "human_participants": False,
        "sampling_plan": "Fixed eligible cohort",
        "blinding_plan": "Outcome assessor is masked",
        "calibration_plan": "Check instrument before collection",
        "measurement_validity": "Compare a blinded subset with a reference",
        "analysis_commitment": "Estimate the registered contrast",
        "stopping_rule": "Stop after the fixed cohort",
        "observable_prediction": "Scores are higher under treatment",
        "null_model": "Selection explains any apparent difference",
    }
    clean = scaffold_design(brief)
    assert "PROSPECTIVE_COMMITMENT_NONCANONICAL" not in {
        item["code"] for item in clean["findings"]
    }

    padded = scaffold_design({**brief, "analysis_commitment": " Estimate the registered contrast"})
    assert "PROSPECTIVE_COMMITMENT_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }
    assert padded["status"] == "blocked"
    assert padded["artifacts"]["protocol-draft.json"]["statistical_model"].startswith(" ")


def test_guided_preprocessing_pipeline_hash_requires_conformance_gate():
    pipeline_sha256 = "3" * 64
    brief = {
        "title": "Preprocessing fixture",
        "question": "Question",
        "decision": "Decision",
        "outcome": "Score",
        "unit_of_observation": "unit",
        "human_participants": False,
        "preprocessing_pipeline": pipeline_sha256,
        "preprocessing_conformance_gate_id": "preprocessing-conformance-assessed",
    }

    result = scaffold_design(brief)

    codes = {item["code"] for item in result["findings"]}
    assert "PREPROCESSING_PIPELINE_HASH_INVALID" not in codes
    assert "PREPROCESSING_CONFORMANCE_GATE_MISSING" not in codes
    protocol = result["artifacts"]["protocol-draft.json"]
    assert protocol["preprocessing_pipeline"] == pipeline_sha256
    assert "preprocessing-conformance-assessed" in protocol["quality_requirements"]
    dictionary = result["artifacts"]["data-dictionary-draft.json"]
    assert dictionary["preprocessing_pipeline"] == pipeline_sha256
    assert (
        dictionary["preprocessing_conformance_gate_id"]
        == "preprocessing-conformance-assessed"
    )
    plan = result["artifacts"]["preprocessing-conformance-plan-draft.json"]
    assert plan["status"] == "review_required"
    assert plan["registered_pipeline_sha256"] == pipeline_sha256
    assert plan["required_gate_id"] == "preprocessing-conformance-assessed"
    assert (
        plan["required_run_assessment"]["result_shape"]["registered_pipeline_sha256"]
        == pipeline_sha256
    )
    assert pipeline_sha256 in result["artifacts"]["collection-plan.md"]

    missing_gate = scaffold_design({
        **brief,
        "preprocessing_conformance_gate_id": "",
    })
    assert missing_gate["status"] == "blocked"
    assert "PREPROCESSING_CONFORMANCE_GATE_MISSING" in {
        item["code"] for item in missing_gate["findings"]
    }

    padded = scaffold_design({
        **brief,
        "preprocessing_pipeline": f" {pipeline_sha256}",
        "preprocessing_conformance_gate_id": " preprocessing-conformance-assessed ",
    })
    assert padded["status"] == "blocked"
    assert {
        "PREPROCESSING_PIPELINE_HASH_NONCANONICAL",
        "PREPROCESSING_CONFORMANCE_GATE_NONCANONICAL",
    } <= {item["code"] for item in padded["findings"]}


def test_confirmatory_measurement_requires_structured_validity_decision_rules():
    base = {
        "title": "Validity fixture", "question": "Question", "decision": "Decision",
        "outcome": "Height", "unit_of_observation": "pot",
        "human_participants": False, "study_type": "correlational",
        "measurement_validity": "Check against a reference.",
    }
    missing = scaffold_design(base)
    assert "MEASUREMENT_VALIDITY_PLAN_INCOMPLETE" in {
        item["code"] for item in missing["findings"]
    }

    planned = scaffold_design({
        **base, "measurement_validity_checks": [_validity_check()],
    })
    assert "MEASUREMENT_VALIDITY_PLAN_INCOMPLETE" not in {
        item["code"] for item in planned["findings"]
    }
    protocol = planned["artifacts"]["protocol-draft.json"]
    assert protocol["measurement_validity_checks"][0]["evidence_type"] == "criterion"
    assert "primary-validity-assessed" in protocol["quality_requirements"]
    validity = planned["artifacts"]["measurement-validity-plan-draft.json"]
    assert validity["checks"][0]["acceptance_criterion"].startswith("Absolute disagreement")

    collision = scaffold_design({
        **base,
        "measurement_validity_checks": [_validity_check(gate_id="shared-assessment")],
        "missingness_assumption": "Complete cases preserve the contrast.",
        "missingness_assessment_plan": "Inspect missingness patterns.",
        "missingness_failure_response": "Stop interpretation.",
        "missingness_assessment_kind": "empirical_diagnostic",
        "missingness_assessment_gate_id": "shared-assessment",
    })
    assert "QUALITY_GATE_PURPOSE_COLLISION" in {
        item["code"] for item in collision["findings"]
    }
    padded = scaffold_design({
        **base,
        "measurement_validity_checks": [
            _validity_check(
                check_id=" primary-validity ",
                gate_id="primary-validity-assessed ",
            ),
        ],
    })
    assert "MEASUREMENT_VALIDITY_CHECK_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }
    assert padded["status"] == "blocked"


def test_causal_scaffold_retains_measurement_validity_and_assumption_gates():
    assumptions = [
        {
            "category": category,
            "statement": f"Synthetic {category} assumption.",
            "assessment_kind": "design_record_review",
            "assessment_plan": f"Assess {category} before interpretation.",
            "failure_response": f"Stop causal interpretation if {category} fails.",
            "assessment_gate_id": f"causal-{category}-assessed",
        }
        for category in (
            "positivity",
            "consistency",
            "interference",
            "temporal_order",
            "measurement_validity",
            "selection_bias",
            "exchangeability",
        )
    ]
    result = scaffold_design({
        "title": "Combined gate fixture",
        "question": "Does exposure change outcome?",
        "decision": "Choose a strategy",
        "study_type": "causal",
        "assignment_type": "observational",
        "exposure_definition": "Observed exposure before follow-up.",
        "comparison": "control",
        "outcome": "outcome",
        "outcome_unit": "points",
        "unit_of_observation": "unit",
        "human_participants": False,
        "measurement_validity_checks": [_validity_check()],
        "causal_identification": {
            "nodes": [
                {"id": "treatment", "observed": True},
                {"id": "outcome", "observed": True},
            ],
            "edges": [{"cause": "treatment", "effect": "outcome"}],
            "exposure": "treatment",
            "outcome": "outcome",
            "proposed_adjustment_set": [],
            "assignment_type": "observational",
            "assumptions": assumptions,
            "causal_estimand": {
                "target_hypothesis_id": "[REVIEW REQUIRED] bind the reviewed hypothesis",
                "description": "Mean outcome under treatment minus control.",
                "population": "Eligible units.",
                "exposure_strategies": ["observe treatment", "observe control"],
                "outcome_variable": "outcome",
                "time_zero": "Exposure assessment.",
                "outcome_time": "Registered follow-up.",
                "contrast": "Treatment minus control.",
                "summary_measure": "Population mean difference.",
                "intercurrent_events_policy": "Retain eligible units and disclose missing outcomes.",
            },
        },
    })

    requirements = result["artifacts"]["protocol-draft.json"][
        "quality_requirements"
    ]
    assert "primary-validity-assessed" in requirements
    assert {
        item["assessment_gate_id"] for item in assumptions
    } <= set(requirements)
    assert len(requirements) == len(set(requirements))


def test_unit_identity_column_is_explicit_and_shared_by_all_guided_artifacts():
    base = {
        "title": "Unit fixture", "question": "Question", "decision": "Decision",
        "outcome": "Score", "unit_of_observation": "visit",
        "independent_unit": "participant", "human_participants": False,
        "study_type": "correlational", "outcome_data_column": "score",
    }
    missing = scaffold_design(base)
    assert "UNIT_ID_COLUMN_UNRESOLVED" in {
        item["code"] for item in missing["findings"]
    }
    assert missing["status"] == "blocked"

    explicit = scaffold_design({**base, "unit_id_column": "participant_key"})
    assert "UNIT_ID_COLUMN_UNRESOLVED" not in {
        item["code"] for item in explicit["findings"]
    }
    assert explicit["artifacts"]["protocol-draft.json"]["unit_id_column"] == "participant_key"
    columns = explicit["artifacts"]["data-dictionary-draft.json"]["proposed_columns"]
    assert "participant_key" in {item["name"] for item in columns}
    assert "participant_key" in explicit["artifacts"]["collection-plan.md"]

    padded = scaffold_design({**base, "unit_id_column": " participant_key "})
    assert padded["status"] == "blocked"
    assert "UNIT_ID_COLUMN_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }
    padded_dependence = scaffold_design({
        **base,
        "independent_unit": " participant ",
        "unit_id_column": "participant_key",
        "repeated_measures": True,
        "analysis_design": "paired",
        "unit_analysis_plan": " Pair repeated rows within participant ",
    })
    assert "DEPENDENCE_COMMITMENT_NONCANONICAL" in {
        item["code"] for item in padded_dependence["findings"]
    }
    assert padded_dependence["status"] == "blocked"
    assert padded_dependence["artifacts"]["protocol-draft.json"][
        "independent_unit"
    ].startswith(" ")
    assert padded_dependence["artifacts"]["data-dictionary-draft.json"][
        "independent_unit"
    ].startswith(" ")

    collision = scaffold_design({
        **base, "unit_id_column": "participant_key",
        "outcome_data_column": "PARTICIPANT_KEY",
    })
    assert "MEASUREMENT_COLUMN_RESERVED" in {
        item["code"] for item in collision["findings"]
    }


def test_guided_acquisition_timing_commitments_are_shared_by_review_artifacts():
    brief = {
        "title": "Temporal fixture",
        "question": "Question",
        "decision": "Decision",
        "outcome": "Event lag",
        "unit_of_observation": "trial",
        "human_participants": False,
        "sensor_requirements": [
            "audio recorder at 48 kHz",
            "event marker stream",
        ],
        "clock_accuracy_requirement": "Clock drift below 10 ms across the tested lag window.",
        "control_windows": [
            "pre-event baseline",
            "random-time negative window",
        ],
    }

    result = scaffold_design(brief)

    codes = {item["code"] for item in result["findings"]}
    assert "CLOCK_ACCURACY_UNRESOLVED" not in codes
    protocol = result["artifacts"]["protocol-draft.json"]
    assert protocol["sensor_requirements"] == brief["sensor_requirements"]
    assert protocol["clock_accuracy_requirement"] == brief["clock_accuracy_requirement"]
    assert protocol["control_windows"] == brief["control_windows"]
    dictionary = result["artifacts"]["data-dictionary-draft.json"]
    assert dictionary["sensor_requirements"] == brief["sensor_requirements"]
    assert dictionary["clock_accuracy_requirement"] == brief["clock_accuracy_requirement"]
    assert dictionary["control_windows"] == brief["control_windows"]
    collection = result["artifacts"]["collection-plan.md"]
    assert "audio recorder at 48 kHz" in collection
    assert "Clock drift below 10 ms" in collection
    assert "random-time negative window" in collection

    missing_clock = scaffold_design({
        **brief,
        "clock_accuracy_requirement": "",
    })
    assert missing_clock["status"] == "blocked"
    assert "CLOCK_ACCURACY_UNRESOLVED" in {
        item["code"] for item in missing_clock["findings"]
    }

    padded = scaffold_design({
        **brief,
        "sensor_requirements": [" audio recorder at 48 kHz"],
        "clock_accuracy_requirement": " Clock drift below 10 ms",
        "control_windows": [" pre-event baseline"],
    })
    assert padded["status"] == "blocked"
    assert {
        "SENSOR_REQUIREMENT_NONCANONICAL",
        "CONTROL_WINDOW_NONCANONICAL",
        "PROSPECTIVE_COMMITMENT_NONCANONICAL",
    } <= {item["code"] for item in padded["findings"]}


def test_comparison_column_is_bound_to_contrast_and_causal_exposure():
    base = {
        "title": "Contrast fixture", "question": "Question", "decision": "Decision",
        "outcome": "Score", "unit_of_observation": "unit",
        "human_participants": False, "study_type": "correlational",
        "contrast_groups": ["exposed", "unexposed"],
        "outcome_data_column": "score",
    }
    missing = scaffold_design(base)
    assert "GROUP_DATA_COLUMN_UNRESOLVED" in {
        item["code"] for item in missing["findings"]
    }

    explicit = scaffold_design({**base, "group_data_column": "exposure"})
    assert "GROUP_DATA_COLUMN_UNRESOLVED" not in {
        item["code"] for item in explicit["findings"]
    }
    dictionary = explicit["artifacts"]["data-dictionary-draft.json"]
    assert any(
        item["name"] == "exposure" and item["role"] == "comparison_label"
        for item in dictionary["proposed_columns"]
    )
    analysis = explicit["artifacts"]["analysis-commitment-draft.json"]
    assert analysis["group_column"] == "exposure"

    padded = scaffold_design({**base, "group_data_column": " exposure "})
    assert padded["status"] == "blocked"
    assert "GROUP_DATA_COLUMN_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }

    collision = scaffold_design({
        **base, "group_data_column": "score",
    })
    assert "MEASUREMENT_COLUMN_RESERVED" in {
        item["code"] for item in collision["findings"]
    }

    graph = {
        "nodes": [
            {"id": "exposure", "observed": True},
            {"id": "outcome", "observed": True},
        ],
        "edges": [{"cause": "exposure", "effect": "outcome"}],
        "exposure": "exposure", "outcome": "outcome",
        "proposed_adjustment_set": [], "assignment_type": "observational",
        "assumptions": [],
    }
    mismatch = scaffold_design({
        **base, "study_type": "causal", "assignment_type": "observational",
        "exposure_definition": "Recorded baseline exposure",
        "comparison": "Unexposed units", "group_data_column": "assigned_arm",
        "causal_identification": graph,
    })
    assert "CAUSAL_EXPOSURE_COLUMN_MISMATCH" in {
        item["code"] for item in mismatch["findings"]
    }


def test_causal_measurements_exactly_cover_exposure_and_adjustment_set():
    graph = {
        "nodes": [
            {"id": "treatment", "observed": True},
            {"id": "outcome", "observed": True},
            {"id": "baseline", "observed": True},
        ],
        "edges": [
            {"cause": "baseline", "effect": "treatment"},
            {"cause": "baseline", "effect": "outcome"},
            {"cause": "treatment", "effect": "outcome"},
        ],
        "exposure": "treatment", "outcome": "outcome",
        "proposed_adjustment_set": ["baseline"],
        "assignment_type": "observational", "assumptions": [],
    }
    base = {
        "title": "Causal measurement fixture", "question": "Question",
        "decision": "Decision", "outcome": "outcome",
        "unit_of_observation": "unit", "human_participants": False,
        "study_type": "causal", "assignment_type": "observational",
        "exposure_definition": "Observed treatment status", "comparison": "control",
        "contrast_groups": ["treated", "control"],
        "group_data_column": "treatment", "outcome_data_column": "outcome",
        "causal_identification": graph,
    }
    missing = scaffold_design(base)
    assert "CAUSAL_MEASUREMENT_COVERAGE_INVALID" in {
        item["code"] for item in missing["findings"]
    }

    measurements = [
        _causal_measurement("treatment", "exposure", "treatment"),
        _causal_measurement("baseline", "covariate", "baseline"),
    ]
    complete = scaffold_design({**base, "causal_measurements": measurements})
    codes = {item["code"] for item in complete["findings"]}
    assert "CAUSAL_MEASUREMENT_COVERAGE_INVALID" not in codes
    assert "CAUSAL_EXPOSURE_LEVELS_MISMATCH" not in codes
    drafts = complete["artifacts"]["causal-measurement-definitions-draft.json"]["measurements"]
    assert [(item["role"], item["registered_target"]) for item in drafts] == [
        ("exposure", "treatment"), ("covariate", "baseline"),
    ]
    proposed = complete["artifacts"]["data-dictionary-draft.json"]["proposed_columns"]
    assert any(
        item["name"] == "baseline" and item["role"] == "causal_covariate"
        for item in proposed
    )

    post_treatment = [measurements[0], {**measurements[1], "temporal_role": "post_exposure"}]
    invalid = scaffold_design({**base, "causal_measurements": post_treatment})
    assert "CAUSAL_MEASUREMENT_TIMING_INVALID" in {
        item["code"] for item in invalid["findings"]
    }
    degenerate_covariate = scaffold_design({
        **base,
        "causal_measurements": [
            measurements[0],
            _causal_measurement(
                "baseline", "covariate", "baseline", valid_min=5, valid_max=5
            ),
        ],
    })
    assert "CAUSAL_MEASUREMENT_DOMAIN_INVALID" in {
        item["code"] for item in degenerate_covariate["findings"]
    }
    padded = scaffold_design({
        **base,
        "causal_measurements": [
            _causal_measurement(
                "treatment",
                "exposure",
                "treatment",
                admissible_values=["treated", "control "],
            ),
            _causal_measurement(
                "baseline",
                "covariate",
                "baseline",
                observable=" Recorded baseline",
            ),
        ],
    })
    assert "CAUSAL_MEASUREMENT_CONTRACT_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }


def test_secondary_outcomes_require_distinct_roles_and_multiplicity_plan():
    base = {"title": "Fixture", "question": "Question", "decision": "Decision",
            "outcome": "Primary score", "unit_of_observation": "unit",
            "study_type": "correlational", "human_participants": False}
    missing = scaffold_design({**base, "secondary_outcomes": ["Response time", "Errors"]})
    assert "MULTIPLICITY_POLICY_MISSING" in {item["code"] for item in missing["findings"]}
    assert "MULTIPLICITY_PLAN_INCOMPLETE" in {item["code"] for item in missing["findings"]}
    policy = "Primary score is the sole confirmatory outcome; Holm-adjust the two secondary outcomes and interpret them as secondary."
    planned = scaffold_design({**base, "secondary_outcomes": ["Response time", "Errors"],
                               "confirmatory_outcomes": ["Primary score", "Response time", "Errors"],
                               "exploratory_outcomes": [], "multiplicity_method": "holm",
                               "multiplicity_alpha": 0.05,
                               "population": "Registered fixture units",
                               "setting": "Fixture laboratory",
                               "outcome_unit": "points",
                               "effect_scale": "mean difference",
                               "conclusion_time_window": "registered endpoint",
                               "smallest_effect_size_of_interest": 2.0,
                               "non_supporting_direction": "inconclusive",
                               "higher_level_conclusions_unsupported": ["No causal or external-validity conclusion"],
                               "multiple_testing_policy": policy})
    codes = {item["code"] for item in planned["findings"]}
    assert "MULTIPLICITY_POLICY_MISSING" not in codes
    protocol = planned["artifacts"]["protocol-draft.json"]
    assert protocol["secondary_outcomes"] == ["Response time", "Errors"]
    assert protocol["confirmatory_outcomes"] == ["Primary score", "Response time", "Errors"]
    assert protocol["multiplicity_method"] == "holm"
    assert protocol["multiplicity_alpha"] == 0.05
    assert protocol["multiple_testing_policy"] == policy
    assert protocol["conclusion_contract"]["smallest_effect_size_of_interest"] == 2.0
    assert protocol["conclusion_contract"]["permitted_claim_level"] == "statistical_association"
    workflow = planned["artifacts"]["analysis-workflow-draft.json"]
    assert [step["step_id"] for step in workflow["steps"]] == [
        "primary-estimate", "outcome-test-1", "outcome-test-2", "outcome-test-3",
        "confirmatory-holm",
    ]
    assert workflow["steps"][-1]["depends_on"] == [
        "outcome-test-1", "outcome-test-2", "outcome-test-3",
    ]
    assert [item["outcome"] for item in workflow["steps"][-1]["family_members"]] == [
        "Primary score", "Response time", "Errors",
    ]


def test_cli_design_scaffold_accepts_multiplicity_commitments(
    tmp_path: Path, capsys
) -> None:
    brief = {
        "title": "Multiplicity fixture",
        "question": "Question",
        "decision": "Decision",
        "outcome": "Primary score",
        "unit_of_observation": "unit",
        "study_type": "correlational",
        "human_participants": False,
        "secondary_outcomes": ["Response time"],
        "confirmatory_outcomes": ["Primary score", "Response time"],
        "exploratory_outcomes": [],
        "multiplicity_method": "holm",
        "multiplicity_alpha": 0.05,
        "multiple_testing_policy": "Holm-adjust the two confirmatory outcomes.",
        "population": "Registered fixture units",
        "setting": "Fixture laboratory",
        "outcome_unit": "points",
        "effect_scale": "mean difference",
        "conclusion_time_window": "registered endpoint",
        "smallest_effect_size_of_interest": 2.0,
        "non_supporting_direction": "inconclusive",
        "higher_level_conclusions_unsupported": [
            "No causal or external-validity conclusion"
        ],
    }
    brief_file = tmp_path / "brief.json"
    brief_file.write_text(json.dumps(brief), encoding="utf-8")

    assert main(["--json", "design", "scaffold", "--brief-file", str(brief_file)]) == 0

    result = json.loads(capsys.readouterr().out)["result"]
    protocol = result["artifacts"]["protocol-draft.json"]
    assert protocol["confirmatory_outcomes"] == ["Primary score", "Response time"]
    assert protocol["exploratory_outcomes"] == []
    assert protocol["multiplicity_method"] == "holm"
    assert protocol["multiplicity_alpha"] == 0.05


def test_confirmatory_scaffold_emits_structured_analysis_contract():
    brief = {
        "title": "Analysis contract fixture",
        "question": "Does the intervention change the score?",
        "decision": "Choose the next intervention.",
        "study_type": "correlational",
        "population": "Eligible fixture participants.",
        "setting": "Registered fixture setting.",
        "outcome": "Primary score",
        "outcome_unit": "points",
        "outcome_scale": "interval",
        "outcome_valid_min": 0.0,
        "outcome_valid_max": 100.0,
        "outcome_missing_value_codes": ["<blank>"],
        "outcome_data_column": "score",
        "unit_of_observation": "participant",
        "independent_unit": "participant",
        "unit_id_column": "participant_id",
        "analysis_design": "independent_groups",
        "primary_analysis_family": "mean_difference",
        "primary_estimand": "Mean score difference, treated minus control.",
        "contrast_definition": "treated minus control",
        "contrast_groups": ["treated", "control"],
        "group_data_column": "arm",
        "expected_effect_direction": "positive",
        "null_value": 0.0,
        "support_rule": "interval_excludes_null",
        "confidence_level": 0.95,
        "effect_scale": "mean difference",
        "conclusion_time_window": "Registered endpoint.",
        "smallest_effect_size_of_interest": 2.0,
        "non_supporting_direction": "inconclusive",
        "higher_level_conclusions_unsupported": [
            "No causal, mechanism, or out-of-scope conclusion."
        ],
        "minimum_analyzable_units": 12,
        "maximum_excluded_fraction": 0.2,
        "maximum_group_excluded_fraction_difference": 0.1,
        "missingness_assumption": "Complete cases preserve the registered contrast.",
        "missingness_assessment_plan": "Inspect total and group-specific exclusions.",
        "missingness_failure_response": "Stop primary interpretation if exclusions exceed thresholds.",
        "missingness_assessment_kind": "empirical_diagnostic",
        "missingness_assessment_gate_id": "missingness-assessed",
        "measurement_validity": "Compare a blinded subset with a traceable reference.",
        "measurement_validity_checks": [_validity_check()],
        "measurement_observable": "Recorded primary score.",
        "measurement_input_condition": "All eligible participants at endpoint.",
        "measurement_parameter_values": {"instrument": "registered fixture"},
        "measurement_evaluation_point": "Registered endpoint.",
        "measurement_convention": "Higher means more of the target construct.",
        "measurement_aggregation": "One value per independent participant.",
        "measurement_tolerance": "Exact parser agreement.",
        "measurement_expected_behavior": "Retain valid scores regardless of direction.",
        "measurement_temporal_role": "not_applicable",
        "human_participants": False,
    }

    result = scaffold_design(brief)

    codes = {item["code"] for item in result["findings"]}
    assert "INFERENCE_COMMITMENT_INCOMPLETE" not in codes
    assert "MISSINGNESS_ASSESSMENT_INCOMPLETE" not in codes
    protocol = result["artifacts"]["protocol-draft.json"]
    analysis = result["artifacts"]["analysis-commitment-draft.json"]
    contract = protocol["analysis_contract"]
    assert contract == analysis["analysis_contract"]
    assert contract["method"] == "independent_mean_difference_ci"
    assert contract["outcome_column"] == "score"
    assert contract["group_column"] == "arm"
    assert contract["groups"] == ["treated", "control"]
    assert contract["contrast_definition"] == "treated minus control"
    assert contract["effect_estimate_path"] == "/result/mean_difference_first_minus_second"
    assert contract["uncertainty_path"] == "/result/confidence_interval"
    assert contract["missingness_assessment_gate_id"] == "missingness-assessed"
    assert contract["minimum_analyzable_units"] == 12
    assert contract["assignment_type"] == "observational"
    assert "missingness-assessed" in protocol["quality_requirements"]


def test_scaffold_preserves_inquiry_decision_boundary():
    brief = {
        "title": "Decision boundary fixture",
        "question": "Question",
        "decision": "Choose whether to proceed.",
        "minimum_evidence": "Two independent checks support action.",
        "decision_change_criteria": [
            "Stop if the registered falsifier appears.",
            "Proceed only if the validity check is consistent.",
        ],
        "decision_owner": "project-owner",
        "outcome": "Primary score",
        "unit_of_observation": "unit",
        "human_participants": False,
    }

    result = scaffold_design(brief)

    inquiry = result["artifacts"]["inquiry-draft.json"]
    assert inquiry["decision_to_support"] == "Choose whether to proceed."
    assert inquiry["minimum_evidence"] == "Two independent checks support action."
    assert inquiry["decision_change_criteria"] == brief["decision_change_criteria"]
    assert inquiry["decision_owner"] == "project-owner"
    assert "INQUIRY_DECISION_BOUNDARY_INCOMPLETE" not in {
        item["code"] for item in result["findings"]
    }
    assert "Minimum decision-relevant evidence: Two independent checks" in result[
        "artifacts"
    ]["collection-plan.md"]

    padded = scaffold_design(
        {
            **brief,
            "minimum_evidence": " Two independent checks support action.",
        }
    )
    codes = {item["code"] for item in padded["findings"]}
    assert "INQUIRY_DECISION_BOUNDARY_NONCANONICAL" in codes
    assert padded["status"] == "blocked"


def test_scaffold_preserves_data_availability_boundary():
    brief = {
        "title": "Data availability fixture",
        "question": "Question",
        "decision": "Choose whether records can support the test.",
        "outcome": "Primary score",
        "unit_of_observation": "unit",
        "human_participants": False,
        "available_data_sources": [
            "Instrument export retained as CSV.",
            "Operator log retained as PDF.",
        ],
        "unavailable_data": ["No pre-intervention baseline exists."],
        "data_access_owner": "lab-data-steward",
        "data_access_constraints": [
            "Raw identifiers require approved local review."
        ],
        "data_provenance_plan": (
            "Hash source bytes and retain collection context before analysis."
        ),
    }

    result = scaffold_design(brief)

    availability = result["artifacts"]["data-availability-draft.json"]
    assert availability["available_data_sources"] == brief[
        "available_data_sources"
    ]
    assert availability["unavailable_data"] == brief["unavailable_data"]
    assert availability["data_access_owner"] == "lab-data-steward"
    assert availability["data_access_constraints"] == brief[
        "data_access_constraints"
    ]
    assert availability["data_provenance_plan"].startswith("Hash source bytes")
    codes = {item["code"] for item in result["findings"]}
    assert "DATA_AVAILABILITY_UNRESOLVED" not in codes
    assert "DATA_PROVENANCE_PLAN_MISSING" not in codes
    assert "DATA_ACCESS_OWNER_UNRESOLVED" not in codes
    assert "Available data sources: Instrument export retained as CSV." in result[
        "artifacts"
    ]["collection-plan.md"]

    unresolved = scaffold_design(
        {
            **brief,
            "data_access_owner": "",
            "data_provenance_plan": "",
        }
    )
    unresolved_availability = unresolved["artifacts"][
        "data-availability-draft.json"
    ]
    assert unresolved_availability["data_access_owner"] == "[REVIEW REQUIRED]"
    assert unresolved_availability["data_provenance_plan"].startswith(
        "[REVIEW REQUIRED]"
    )
    unresolved_codes = {item["code"] for item in unresolved["findings"]}
    assert "DATA_ACCESS_OWNER_UNRESOLVED" in unresolved_codes
    assert "DATA_PROVENANCE_PLAN_MISSING" in unresolved_codes

    padded = scaffold_design(
        {
            **brief,
            "available_data_sources": [" Instrument export retained as CSV."],
        }
    )
    padded_codes = {item["code"] for item in padded["findings"]}
    assert "DATA_AVAILABILITY_NONCANONICAL" in padded_codes
    assert padded["status"] == "blocked"


def test_scaffold_preserves_ethical_safeguards_boundary():
    brief = {
        "title": "Ethical safeguards fixture",
        "question": "Question",
        "decision": "Choose whether collection can proceed.",
        "outcome": "Primary score",
        "unit_of_observation": "unit",
        "human_participants": False,
        "ethical_constraints": [
            "Avoid unnecessary equipment stress.",
            "Do not collect during facility emergency operations.",
        ],
        "ethical_safeguards_plan": (
            "Review constraints before collection and stop if a constraint is exceeded."
        ),
    }

    result = scaffold_design(brief)

    safeguards = result["artifacts"]["ethical-safeguards-draft.json"]
    assert safeguards["ethical_constraints"] == brief["ethical_constraints"]
    assert safeguards["ethical_safeguards_plan"].startswith(
        "Review constraints"
    )
    protocol = result["artifacts"]["protocol-draft.json"]
    assert protocol["safety_constraints"] == brief["ethical_constraints"]
    assert "Ethical and safety constraints: Avoid unnecessary equipment stress." in result[
        "artifacts"
    ]["collection-plan.md"]
    codes = {item["code"] for item in result["findings"]}
    assert "ETHICAL_CONSTRAINTS_UNRESOLVED" not in codes
    assert "ETHICAL_SAFEGUARDS_PLAN_MISSING" not in codes

    unresolved = scaffold_design(
        {
            **brief,
            "ethical_constraints": [],
            "ethical_safeguards_plan": "",
        }
    )
    unresolved_safeguards = unresolved["artifacts"][
        "ethical-safeguards-draft.json"
    ]
    assert unresolved_safeguards["ethical_constraints"] == []
    assert unresolved_safeguards["ethical_safeguards_plan"].startswith(
        "[REVIEW REQUIRED]"
    )
    unresolved_codes = {item["code"] for item in unresolved["findings"]}
    assert "ETHICAL_CONSTRAINTS_UNRESOLVED" in unresolved_codes
    assert "ETHICAL_SAFEGUARDS_PLAN_MISSING" in unresolved_codes

    padded = scaffold_design(
        {
            **brief,
            "ethical_constraints": [" Avoid unnecessary equipment stress."],
        }
    )
    padded_codes = {item["code"] for item in padded["findings"]}
    assert "ETHICAL_SAFEGUARDS_NONCANONICAL" in padded_codes
    assert padded["status"] == "blocked"


def test_secondary_outcomes_require_exact_typed_measurement_coverage():
    base = {
        "title": "Secondary measurement fixture", "question": "Question",
        "decision": "Decision", "outcome": "Primary score",
        "unit_of_observation": "unit", "human_participants": False,
        "secondary_outcomes": ["Response time", "Errors"],
    }
    missing = scaffold_design(base)
    assert "SECONDARY_MEASUREMENT_COVERAGE_INVALID" in {
        item["code"] for item in missing["findings"]
    }
    covered = scaffold_design({
        **base,
        "secondary_measurements": [
            _secondary_measurement("Response time", "response_time", unit="milliseconds"),
            _secondary_measurement("Errors", "errors", scale_type="count", unit="count", valid_min=0, valid_max=20),
        ],
    })
    assert "SECONDARY_MEASUREMENT_COVERAGE_INVALID" not in {
        item["code"] for item in covered["findings"]
    }
    drafts = covered["artifacts"]["secondary-measurement-definitions-draft.json"]["measurements"]
    assert [item["registered_target"] for item in drafts] == ["Response time", "Errors"]
    substituted = scaffold_design({
        **base,
        "secondary_measurements": [
            _secondary_measurement("Response time", "response_time"),
            _secondary_measurement("Favorable surrogate", "surrogate"),
        ],
    })
    assert "SECONDARY_MEASUREMENT_COVERAGE_INVALID" in {
        item["code"] for item in substituted["findings"]
    }
    degenerate = scaffold_design({
        **base,
        "secondary_measurements": [
            _secondary_measurement(
                "Response time", "response_time", valid_min=10, valid_max=10
            ),
            _secondary_measurement(
                "Errors", "errors", scale_type="count", unit="count", valid_min=0,
                valid_max=20,
            ),
        ],
    })
    assert "SECONDARY_MEASUREMENT_DOMAIN_INVALID" in {
        item["code"] for item in degenerate["findings"]
    }
    padded = scaffold_design({
        **base,
        "secondary_measurements": [
            _secondary_measurement("Response time", " response_time"),
            _secondary_measurement(
                "Errors", "errors", scale_type="count", unit="count",
                valid_min=0, valid_max=20, missing_value_codes=["<blank> "],
            ),
        ],
    })
    assert "SECONDARY_MEASUREMENT_CONTRACT_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }
    conflicted = scaffold_design({**base, "secondary_outcomes": ["primary SCORE"]})
    assert conflicted["status"] == "blocked"
    assert "OUTCOME_ROLE_CONFLICT" in {item["code"] for item in conflicted["findings"]}
    duplicated = scaffold_design({**base, "secondary_outcomes": ["Errors", " errors "]})
    assert "SECONDARY_OUTCOME_DUPLICATE" in {item["code"] for item in duplicated["findings"]}
    assert "SECONDARY_OUTCOME_LABEL_NONCANONICAL" in {
        item["code"] for item in duplicated["findings"]
    }
    policy = "Primary score is the sole confirmatory outcome; classify all other outcomes prospectively."
    omitted = scaffold_design({**base, "secondary_outcomes": ["Response time", "Errors"],
                               "confirmatory_outcomes": ["Primary score"],
                               "exploratory_outcomes": ["Response time"],
                               "multiplicity_method": "single_test", "multiplicity_alpha": 0.05,
                               "multiple_testing_policy": policy})
    assert "MULTIPLICITY_OUTCOME_PARTITION_INVALID" in {item["code"] for item in omitted["findings"]}
    padded_roles = scaffold_design({**base, "secondary_outcomes": ["Response time", "Errors"],
                                    "confirmatory_outcomes": [" Primary score"],
                                    "exploratory_outcomes": [" Response time", "Errors "],
                                    "multiplicity_method": "single_test", "multiplicity_alpha": 0.05,
                                    "multiple_testing_policy": policy})
    assert "CONFIRMATORY_OUTCOME_LABEL_NONCANONICAL" in {
        item["code"] for item in padded_roles["findings"]
    }
    assert "EXPLORATORY_OUTCOME_LABEL_NONCANONICAL" in {
        item["code"] for item in padded_roles["findings"]
    }
    substituted = scaffold_design({**base, "secondary_outcomes": ["Response time", "Errors"],
                                   "confirmatory_outcomes": ["Primary score"],
                                   "exploratory_outcomes": ["Response time", "Favorable surrogate"],
                                   "multiplicity_method": "single_test", "multiplicity_alpha": 0.05,
                                   "multiple_testing_policy": policy})
    assert "MULTIPLICITY_OUTCOME_PARTITION_INVALID" in {item["code"] for item in substituted["findings"]}


def test_controls_require_exact_reproducible_measurement_coverage():
    base = {
        "title": "Control measurement fixture", "question": "Question",
        "decision": "Decision", "outcome": "score", "unit_of_observation": "unit",
        "human_participants": False, "controls": ["Blank sample", "Reference sample"],
    }
    missing = scaffold_design(base)
    assert "CONTROL_MEASUREMENT_COVERAGE_INVALID" in {
        item["code"] for item in missing["findings"]
    }
    covered = scaffold_design({
        **base,
        "control_measurements": [
            _control_measurement("Blank sample"),
            _control_measurement("Reference sample", "reference_value"),
        ],
    })
    assert "CONTROL_MEASUREMENT_COVERAGE_INVALID" not in {
        item["code"] for item in covered["findings"]
    }
    drafts = covered["artifacts"]["control-measurement-definitions-draft.json"]["measurements"]
    assert [item["registered_target"] for item in drafts] == ["Blank sample", "Reference sample"]
    assert drafts[0]["data_column"] == ""
    assert drafts[1]["scale_type"] == "interval"
    degenerate = scaffold_design({
        **base,
        "control_measurements": [
            _control_measurement("Blank sample"),
            _control_measurement(
                "Reference sample", "reference_value", valid_min=1, valid_max=1
            ),
        ],
    })
    assert "CONTROL_MEASUREMENT_DOMAIN_INVALID" in {
        item["code"] for item in degenerate["findings"]
    }
    padded = scaffold_design({
        **base,
        "control_measurements": [
            _control_measurement(
                "Blank sample",
                expected_behavior=" Remains below detection",
            ),
            _control_measurement(
                "Reference sample",
                "reference_value",
                parameter_values={"instrument": " balance "},
            ),
        ],
    })
    assert "CONTROL_MEASUREMENT_CONTRACT_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }
    substituted = scaffold_design({
        **base,
        "control_measurements": [
            _control_measurement("Blank sample"),
            _control_measurement("Favorable surrogate"),
        ],
    })
    assert "CONTROL_MEASUREMENT_COVERAGE_INVALID" in {
        item["code"] for item in substituted["findings"]
    }


def test_controls_and_confounds_must_have_unique_scientific_labels():
    base = {
        "title": "Duplicate fixture", "question": "Question",
        "decision": "Decision", "outcome": "score", "unit_of_observation": "unit",
        "human_participants": False,
    }
    duplicated_controls = scaffold_design({
        **base,
        "controls": ["Blank sample", " blank sample "],
    })
    assert "CONTROL_DUPLICATE" in {
        item["code"] for item in duplicated_controls["findings"]
    }
    assert "CONTROL_LABEL_NONCANONICAL" in {
        item["code"] for item in duplicated_controls["findings"]
    }
    duplicated_confounds = scaffold_design({
        **base,
        "confounds": ["Tray position", " tray POSITION "],
    })
    assert "CONFOUND_DUPLICATE" in {
        item["code"] for item in duplicated_confounds["findings"]
    }
    assert "CONFOUND_LABEL_NONCANONICAL" in {
        item["code"] for item in duplicated_confounds["findings"]
    }
    undefined_control = scaffold_design({
        **base,
        "controls": ["Blank sample"],
    })
    assert "CONTROL_DEFINITION_MISSING" in {
        item["code"] for item in undefined_control["findings"]
    }
    assert undefined_control["status"] == "blocked"
    padded_definition = scaffold_design({
        **base,
        "controls": ["Blank sample"],
        "control_definitions": [{
            "control_id": " blank-control ",
            "registered_control": "Blank sample",
            "family": "negative",
            "purpose": "Detect contamination",
            "expected_behavior": "No signal",
            "evaluation_gate_id": "blank-control-evaluated ",
        }],
    })
    assert "CONTROL_DEFINITION_NONCANONICAL" in {
        item["code"] for item in padded_definition["findings"]
    }
    assert padded_definition["status"] == "blocked"
    reordered_definitions = scaffold_design({
        **base,
        "controls": ["Blank sample", "Reference sample"],
        "control_definitions": [
            {
                "control_id": "reference-1",
                "registered_control": "Reference sample",
                "family": "reference",
                "purpose": "Bound sensitivity",
                "expected_behavior": "Known reference signal appears",
                "evaluation_gate_id": "reference-evaluated",
            },
            {
                "control_id": "negative-1",
                "registered_control": "Blank sample",
                "family": "negative",
                "purpose": "Detect contamination",
                "expected_behavior": "No signal appears",
                "evaluation_gate_id": "blank-evaluated",
            },
        ],
    })
    assert "CONTROL_COVERAGE_INVALID" in {
        item["code"] for item in reordered_definitions["findings"]
    }
    assert reordered_definitions["status"] == "blocked"


def test_structured_controls_warn_without_positive_and_falsifying_families():
    base = {
        "title": "Control family fixture",
        "question": "Can the measurement pipeline distinguish artifacts?",
        "decision": "Whether to freeze the pipeline.",
        "outcome": "score",
        "unit_of_observation": "unit",
        "human_participants": False,
    }
    reference_only = scaffold_design({
        **base,
        "controls": ["Reference sample"],
        "control_definitions": [{
            "control_id": "reference-1",
            "registered_control": "Reference sample",
            "family": "reference",
            "purpose": "Compare against an ordinary reference sample.",
            "expected_behavior": "Reference response remains measurable.",
            "evaluation_gate_id": "reference-evaluated",
        }],
    })
    codes = {item["code"] for item in reference_only["findings"]}
    assert "CONTROL_POSITIVE_FAMILY_MISSING" in codes
    assert "CONTROL_FALSIFYING_FAMILY_MISSING" in codes

    balanced = scaffold_design({
        **base,
        "controls": ["Known-effect sample", "Apparatus-only sample"],
        "control_definitions": [
            {
                "control_id": "positive-1",
                "registered_control": "Known-effect sample",
                "family": "positive",
                "purpose": "Show the pipeline detects a known effect.",
                "expected_behavior": "Known effect is detected.",
                "evaluation_gate_id": "positive-evaluated",
            },
            {
                "control_id": "apparatus-only-1",
                "registered_control": "Apparatus-only sample",
                "family": "apparatus_only",
                "purpose": "Reveal equipment or environment-generated artifacts.",
                "expected_behavior": "No target-dependent signal is detected.",
                "evaluation_gate_id": "apparatus-only-evaluated",
            },
        ],
    })
    balanced_codes = {item["code"] for item in balanced["findings"]}
    assert "CONTROL_POSITIVE_FAMILY_MISSING" not in balanced_codes
    assert "CONTROL_FALSIFYING_FAMILY_MISSING" not in balanced_codes


def test_guided_design_flags_uninterpretable_multi_factor_interventions():
    base = {
        "title": "Factor fixture", "question": "Question",
        "decision": "Decision", "outcome": "score",
        "unit_of_observation": "unit", "human_participants": False,
        "intervention": "Change the room and apparatus together",
        "manipulated_factors": ["room", "apparatus"],
    }
    blocked = scaffold_design(base)
    codes = {item["code"] for item in blocked["findings"]}
    assert "MULTI_FACTOR_INTERVENTION_UNINTERPRETABLE" in codes
    assert blocked["status"] == "blocked"
    protocol = blocked["artifacts"]["protocol-draft.json"]
    assert protocol["manipulated_factors"] == ["room", "apparatus"]
    assert protocol["factorial_or_crossover_design"] is False
    assert "room, apparatus" in blocked["artifacts"]["collection-plan.md"]

    planned = scaffold_design({
        **base,
        "factorial_or_crossover_design": True,
        "factor_interpretability_plan": (
            "Cross room and apparatus assignments so each factor can be "
            "estimated while holding the other factor balanced."
        ),
    })
    planned_codes = {item["code"] for item in planned["findings"]}
    assert "MULTI_FACTOR_INTERVENTION_UNINTERPRETABLE" not in planned_codes
    planned_protocol = planned["artifacts"]["protocol-draft.json"]
    assert planned_protocol["factorial_or_crossover_design"] is True
    assert planned_protocol["factor_interpretability_plan"].startswith("Cross room")
    dictionary = planned["artifacts"]["data-dictionary-draft.json"]
    assert dictionary["manipulated_factors"] == ["room", "apparatus"]

    padded = scaffold_design({
        **base,
        "manipulated_factors": [" room ", "ROOM"],
        "factorial_or_crossover_design": True,
        "factor_interpretability_plan": " Cross the factors by block. ",
    })
    padded_codes = {item["code"] for item in padded["findings"]}
    assert "MANIPULATED_FACTOR_NONCANONICAL" in padded_codes
    assert "MANIPULATED_FACTOR_DUPLICATE" in padded_codes
    assert "FACTOR_INTERPRETABILITY_PLAN_NONCANONICAL" in padded_codes
    assert padded["status"] == "blocked"


def _canary_plan(**overrides):
    value = {
        "plan_id": "masked-target-plan",
        "candidate_target_ids": ["actual-state", "delayed-replay", "silent-marker"],
        "seed_commitment_sha256": "1" * 64,
        "assignment_artifact_sha256": "2" * 64,
        "masking_plan": "Keep target assignment sealed until the registered reveal point.",
        "ethical_disclosure": "Consent describes masked target conditions without deception about risk.",
        "assessment_gate_id": "canary-target-assessed",
    }
    return {**value, **overrides}


def test_guided_design_scaffolds_canary_target_plan():
    brief = {
        "title": "Canary fixture",
        "question": "Does the pattern follow the masked target?",
        "decision": "Choose whether to run the next discrimination test.",
        "outcome": "Detected pattern",
        "unit_of_observation": "session",
        "human_participants": False,
        "canary_target_plan": _canary_plan(),
    }

    result = scaffold_design(brief)

    codes = {item["code"] for item in result["findings"]}
    assert "CANARY_TARGET_PLAN_INCOMPLETE" not in codes
    assert "CANARY_TARGET_PLAN_NONCANONICAL" not in codes
    assert "CANARY_TARGET_PLAN_HASH_INVALID" not in codes
    protocol = result["artifacts"]["protocol-draft.json"]
    assert protocol["canary_target_plan"] == _canary_plan()
    assert "canary-target-assessed" in protocol["quality_requirements"]
    draft = result["artifacts"]["canary-target-plan-draft.json"]
    assert draft["canary_target_plan"]["candidate_target_ids"] == [
        "actual-state", "delayed-replay", "silent-marker"
    ]
    assert draft["required_run_assessment"]["gate_id"] == "canary-target-assessed"
    assert "follows_comparator_or_decoy" in draft["required_run_assessment"]["result_shape"]["assessment_status"]
    assert "Canary target plan: masked-target-plan" in result["artifacts"]["collection-plan.md"]


@pytest.mark.parametrize(("mutation", "code"), [
    (
        {"candidate_target_ids": ["actual-state"]},
        "CANARY_TARGET_PLAN_INCOMPLETE",
    ),
    (
        {"candidate_target_ids": ["actual-state", " Actual-State "]},
        "CANARY_TARGET_PLAN_NONCANONICAL",
    ),
    (
        {"seed_commitment_sha256": "A" * 64},
        "CANARY_TARGET_PLAN_HASH_INVALID",
    ),
    (
        {"masking_plan": " Keep target assignment sealed."},
        "CANARY_TARGET_PLAN_NONCANONICAL",
    ),
])
def test_guided_design_blocks_invalid_canary_target_plans(mutation, code):
    result = scaffold_design({
        "title": "Canary fixture",
        "question": "Question",
        "decision": "Decision",
        "outcome": "Detected pattern",
        "unit_of_observation": "session",
        "human_participants": False,
        "canary_target_plan": _canary_plan(**mutation),
    })
    assert code in {item["code"] for item in result["findings"]}
    assert result["status"] == "blocked"


def test_canary_target_gate_must_be_dedicated():
    result = scaffold_design({
        "title": "Canary gate fixture",
        "question": "Question",
        "decision": "Decision",
        "outcome": "Detected pattern",
        "unit_of_observation": "session",
        "human_participants": False,
        "measurement_validity": "Check with a registered reference.",
        "measurement_validity_checks": [
            _validity_check(gate_id="canary-target-assessed"),
        ],
        "canary_target_plan": _canary_plan(),
    })
    assert "QUALITY_GATE_PURPOSE_COLLISION" in {
        item["code"] for item in result["findings"]
    }
    assert result["status"] == "blocked"


def test_stopping_count_does_not_supply_information_justification(tmp_path, capsys):
    brief = {"title": "Fixture", "question": "Question", "decision": "Decision", "outcome": "Score",
             "unit_of_observation": "unit", "stopping_rule": "Stop after 100 units", "human_participants": False}
    finding = "SAMPLE_SIZE_JUSTIFICATION_MISSING"
    assert finding in {item["code"] for item in scaffold_design(brief)["findings"]}
    brief["sample_size_justification"] = "Feasibility-limited pilot; interval width remains uncertain and no confirmatory power is claimed."
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief))
    assert main(["--json", "design", "scaffold", "--brief-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert finding not in {item["code"] for item in result["findings"]}
    assert result["artifacts"]["data-dictionary-draft.json"]["sample_size_justification"] == brief["sample_size_justification"]
    padded = scaffold_design({
        **brief,
        "sample_size_justification": " " + brief["sample_size_justification"],
    })
    assert "SAMPLE_SIZE_JUSTIFICATION_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }
    assert padded["status"] == "blocked"


def test_guided_design_recomputes_and_audits_sample_size_decision():
    base = {
        "title": "Planning fixture", "question": "Does A improve score?",
        "decision": "Choose A or B", "study_type": "correlational",
        "outcome": "score", "unit_of_observation": "unit", "human_participants": False,
        "expected_effect_direction": "positive",
        "analysis_design": "independent_groups",
        "minimum_analyzable_units": 63, "maximum_excluded_fraction": 0.1,
        "multiplicity_method": "single_test", "multiplicity_alpha": 0.05,
        "confidence_level": 0.95, "smallest_effect_size_of_interest": 0.5,
    }
    practical = {
        "strategy": "practical_power",
        "specification": {
            "study_design": "independent_groups",
            "smallest_effect_size_of_interest": 0.5,
            "assumed_true_effect": 1.0, "assumed_standard_deviation": 1.0,
            "alpha": 0.05, "confidence_level": 0.95,
            "target_power": 0.8, "alternative": "positive",
        },
        "justification": "Power the confidence bound clearing the practical threshold.",
    }
    result = scaffold_design({**base, "sample_size_plan": practical})
    receipt = result["artifacts"]["sample-size-plan-draft.json"]
    assert receipt["calculation"]["analyzable_n_per_group"] == 63
    assert receipt["specification_sha256"]
    assert result["artifacts"]["protocol-draft.json"]["sample_size_plan"]["strategy"] == "practical_power"
    assert "SAMPLE_SIZE_DECISION_MISMATCH" not in {
        item["code"] for item in result["findings"]
    }
    conventional = scaffold_design({
        **base,
        "sample_size_plan": {
            "strategy": "power",
            "specification": {
                "study_design": "independent_groups",
                "smallest_effect_size_of_interest": 0.5,
                "assumed_standard_deviation": 1.0, "alpha": 0.05,
                "target_power": 0.8, "alternative": "greater",
            },
            "justification": "Conventional null-rejection power.",
        },
    })
    assert "SAMPLE_SIZE_DECISION_MISMATCH" in {
        item["code"] for item in conventional["findings"]
    }
    premature = scaffold_design({
        **base,
        "sample_size_plan": {
            **practical,
            "target_hypothesis_id": "invented-hypothesis",
            "target_measurement_id": "invented-measurement",
            "measurement_unit": "points",
        },
    })
    assert "SAMPLE_SIZE_TARGET_PREMATURE" in {
        item["code"] for item in premature["findings"]
    }
    invalid = scaffold_design({
        **base,
        "sample_size_plan": {
            **practical,
            "specification": {**practical["specification"], "target_power": 1.0},
        },
    })
    assert invalid["artifacts"]["sample-size-plan-draft.json"]["status"] == "unresolved"
    assert "SAMPLE_SIZE_PLAN_INVALID" in {item["code"] for item in invalid["findings"]}


@pytest.mark.parametrize(
    ("brief_changes", "plan_changes", "expected_code"),
    [
        ({"analysis_design": "paired"}, {}, "SAMPLE_SIZE_DESIGN_MISMATCH"),
        ({"minimum_analyzable_units": 64}, {}, "SAMPLE_SIZE_INFORMATION_MISMATCH"),
        ({"maximum_excluded_fraction": 0.1}, {"anticipated_attrition_fraction": 0.2}, "SAMPLE_SIZE_ATTRITION_MISMATCH"),
        ({"multiplicity_alpha": 0.01}, {}, "SAMPLE_SIZE_ALPHA_MISMATCH"),
        ({"confidence_level": 0.90}, {}, "SAMPLE_SIZE_CONFIDENCE_MISMATCH"),
        ({"smallest_effect_size_of_interest": 0.25}, {}, "SAMPLE_SIZE_EFFECT_THRESHOLD_MISMATCH"),
        ({"multiplicity_method": "holm"}, {}, "SAMPLE_SIZE_MULTIPLICITY_MISMATCH"),
    ],
)
def test_guided_planning_must_match_the_rest_of_the_design(
    brief_changes, plan_changes, expected_code,
):
    specification = {
        "study_design": "independent_groups",
        "smallest_effect_size_of_interest": 0.5,
        "assumed_true_effect": 1.0, "assumed_standard_deviation": 1.0,
        "alpha": 0.05, "confidence_level": 0.95,
        "target_power": 0.8, "alternative": "positive",
        **plan_changes,
    }
    brief = {
        "title": "Coherence fixture", "question": "Does A improve score?",
        "decision": "Choose A or B", "study_type": "correlational",
        "outcome": "score", "unit_of_observation": "unit", "human_participants": False,
        "expected_effect_direction": "positive", "analysis_design": "independent_groups",
        "minimum_analyzable_units": 63, "maximum_excluded_fraction": 0.1,
        "multiplicity_method": "single_test", "multiplicity_alpha": 0.05,
        "confidence_level": 0.95, "smallest_effect_size_of_interest": 0.5,
        **brief_changes,
        "sample_size_plan": {
            "strategy": "practical_power", "specification": specification,
            "justification": "Power the registered practical-significance decision.",
        },
    }
    assert expected_code in {item["code"] for item in scaffold_design(brief)["findings"]}


def test_scaffold_emits_typed_measurement_draft_and_rejects_incompatible_analysis():
    base = {
        "title": "Scale fixture", "question": "Does condition change response?",
        "decision": "Choose a condition", "outcome": "response category",
        "outcome_unit": "category", "unit_of_observation": "participant",
        "human_participants": False, "analysis_design": "independent_groups",
    }
    invalid = scaffold_design({
        **base, "outcome_scale": "ordinal",
        "outcome_admissible_values": ["worse", "same", "better"],
        "primary_analysis_family": "mean_difference",
    })
    assert "ANALYSIS_SCALE_INCOMPATIBLE" in {
        item["code"] for item in invalid["findings"]
    }
    valid = scaffold_design({
        **base, "outcome_scale": "ordinal",
        "outcome_admissible_values": ["worse", "same", "better"],
        "outcome_missing_value_codes": ["not_recorded"],
        "primary_analysis_family": "custom_reviewed",
    })
    measurement = valid["artifacts"]["measurement-definition-draft.json"]
    assert measurement["scale_type"] == "ordinal"
    assert measurement["admissible_values"] == ["worse", "same", "better"]
    assert measurement["missing_value_codes"] == ["not_recorded"]
    assert measurement["analysis_family"] == "custom_reviewed"
    assert "ANALYSIS_SCALE_INCOMPATIBLE" not in {
        item["code"] for item in valid["findings"]
    }
    padded = scaffold_design({
        **base,
        "outcome_scale": "ordinal",
        "outcome_admissible_values": ["worse", " same", "better"],
        "outcome_missing_value_codes": ["not_recorded "],
        "primary_analysis_family": "custom_reviewed",
    })
    assert "MEASUREMENT_DOMAIN_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }


def test_scaffold_rejects_invalid_binary_and_numeric_domains():
    base = {
        "title": "Domain fixture", "question": "Question", "decision": "Decision",
        "outcome": "response", "outcome_unit": "response units",
        "unit_of_observation": "unit", "human_participants": False,
        "primary_analysis_family": "descriptive",
    }
    binary = scaffold_design({
        **base, "outcome_scale": "binary",
        "outcome_admissible_values": ["yes", "no", "unknown"],
    })
    assert "BINARY_DOMAIN_INVALID" in {item["code"] for item in binary["findings"]}
    count = scaffold_design({
        **base, "outcome_scale": "count", "outcome_valid_min": -1,
        "outcome_valid_max": 10,
    })
    assert "MEASUREMENT_RANGE_INVALID" in {item["code"] for item in count["findings"]}
    fractional_count = scaffold_design({
        **base, "outcome_scale": "count", "outcome_valid_min": 0,
        "outcome_valid_max": 10.5,
    })
    assert "COUNT_RANGE_INVALID" in {
        item["code"] for item in fractional_count["findings"]
    }
    duration = scaffold_design({
        **base, "outcome_scale": "time_to_event", "outcome_valid_min": -0.1,
        "outcome_valid_max": 30,
    })
    assert "MEASUREMENT_RANGE_INVALID" in {
        item["code"] for item in duration["findings"]
    }


def test_confirmatory_scaffold_binds_estimand_contrast_null_and_support_rule():
    base = {
        "title": "Inference fixture", "question": "Is the outcome associated with group?",
        "decision": "Interpret the association", "study_type": "correlational",
        "outcome": "score", "outcome_unit": "points", "unit_of_observation": "unit",
        "human_participants": False, "population": "Eligible units", "setting": "Lab",
        "effect_scale": "mean difference", "conclusion_time_window": "Day 7",
        "smallest_effect_size_of_interest": 1.0,
        "non_supporting_direction": "inconclusive",
        "higher_level_conclusions_unsupported": ["No causal conclusion"],
    }
    incomplete = scaffold_design(base)
    assert "INFERENCE_COMMITMENT_INCOMPLETE" in {
        item["code"] for item in incomplete["findings"]
    }
    complete = scaffold_design({
        **base, "primary_estimand": "Population mean score difference, A minus B.",
        "contrast_definition": "A minus B", "contrast_groups": ["A", "B"],
        "expected_effect_direction": "positive",
        "null_value": 0.0, "support_rule": "interval_excludes_null",
        "confidence_level": 0.95,
    })
    commitment = complete["artifacts"]["analysis-commitment-draft.json"]
    assert commitment["primary_estimand"].startswith("Population mean")
    assert commitment["contrast_definition"] == "A minus B"
    assert commitment["null_value"] == 0.0
    assert "INFERENCE_COMMITMENT_INCOMPLETE" not in {
        item["code"] for item in complete["findings"]
    }
    conflict = scaffold_design({
        **base, "primary_estimand": "Mean difference", "contrast_definition": "A minus B",
        "contrast_groups": ["A", "B"],
        "expected_effect_direction": "equivalence", "null_value": 0.0,
        "support_rule": "interval_excludes_null", "confidence_level": 0.90,
    })
    assert "EQUIVALENCE_RULE_CONFLICT" in {item["code"] for item in conflict["findings"]}
    malformed = scaffold_design({
        **base, "primary_estimand": "Mean difference", "contrast_definition": "A minus A",
        "contrast_groups": ["A", "A"], "expected_effect_direction": "positive",
        "null_value": 0.0, "support_rule": "interval_excludes_null",
        "confidence_level": 0.95,
    })
    assert "CONTRAST_GROUPS_INVALID" in {item["code"] for item in malformed["findings"]}
    padded = scaffold_design({
        **base, "primary_estimand": "Mean difference", "contrast_definition": "A minus B",
        "contrast_groups": [" A", "B "], "expected_effect_direction": "positive",
        "null_value": 0.0, "support_rule": "interval_excludes_null",
        "confidence_level": 0.95,
    })
    assert "CONTRAST_GROUP_LABEL_NONCANONICAL" in {item["code"] for item in padded["findings"]}
    padded_contract = scaffold_design({
        **base,
        "population": " Eligible units",
        "primary_estimand": " Mean difference",
        "contrast_definition": "A minus B ",
        "contrast_groups": ["A", "B"], "expected_effect_direction": "positive",
        "null_value": 0.0, "support_rule": "interval_excludes_null",
        "confidence_level": 0.95,
    })
    codes = {item["code"] for item in padded_contract["findings"]}
    assert "CONCLUSION_CONTRACT_NONCANONICAL" in codes
    assert "INFERENCE_COMMITMENT_NONCANONICAL" in codes
    assert padded_contract["status"] == "blocked"
    assert padded_contract["artifacts"]["protocol-draft.json"]["conclusion_contract"][
        "population"
    ].startswith(" ")
    assert padded_contract["artifacts"]["analysis-commitment-draft.json"][
        "primary_estimand"
    ].startswith(" ")
    padded_ceiling = scaffold_design({
        **base,
        "higher_level_conclusions_unsupported": [" No causal conclusion"],
    })
    assert "UNSUPPORTED_CONCLUSION_NONCANONICAL" in {
        item["code"] for item in padded_ceiling["findings"]
    }


def test_scaffold_carries_reviewable_information_and_attrition_thresholds():
    brief = {"title": "Fixture", "question": "Question", "decision": "Decision",
             "outcome": "Score", "unit_of_observation": "unit", "human_participants": False}
    missing = scaffold_design(brief)
    codes = {item["code"] for item in missing["findings"]}
    assert {
        "MINIMUM_ANALYZABLE_UNITS_MISSING", "MAXIMUM_EXCLUDED_FRACTION_MISSING",
        "MAXIMUM_GROUP_EXCLUSION_DIFFERENCE_MISSING",
    } <= codes
    planned = scaffold_design({**brief, "minimum_analyzable_units": 20,
                               "maximum_excluded_fraction": 0.1,
                               "maximum_group_excluded_fraction_difference": 0.05,
                               "missingness_assumption": "Unavailable outcomes do not materially distort the contrast.",
                               "missingness_assessment_plan": "Inspect total and group-specific patterns.",
                               "missingness_failure_response": "Stop primary interpretation.",
                               "missingness_assessment_kind": "empirical_diagnostic",
                               "missingness_assessment_gate_id": "missingness-assessed"})
    codes = {item["code"] for item in planned["findings"]}
    assert "MINIMUM_ANALYZABLE_UNITS_MISSING" not in codes
    assert "MAXIMUM_EXCLUDED_FRACTION_MISSING" not in codes
    assert "MAXIMUM_GROUP_EXCLUSION_DIFFERENCE_MISSING" not in codes
    assert "MISSINGNESS_ASSESSMENT_INCOMPLETE" not in codes
    dictionary = planned["artifacts"]["data-dictionary-draft.json"]
    assert dictionary["minimum_analyzable_units"] == 20
    assert dictionary["maximum_excluded_fraction"] == 0.1
    assert dictionary["maximum_group_excluded_fraction_difference"] == 0.05
    assert dictionary["missingness_assessment"]["missingness_assessment_gate_id"] == "missingness-assessed"
    assert "missingness-assessed" in planned["artifacts"]["protocol-draft.json"]["quality_requirements"]
    padded = scaffold_design({**brief, "minimum_analyzable_units": 20,
                               "maximum_excluded_fraction": 0.1,
                               "maximum_group_excluded_fraction_difference": 0.05,
                               "missingness_assumption": " Unavailable outcomes do not materially distort the contrast.",
                               "missingness_assessment_plan": "Inspect total and group-specific patterns.",
                               "missingness_failure_response": "Stop primary interpretation.",
                               "missingness_assessment_kind": "empirical_diagnostic",
                               "missingness_assessment_gate_id": "missingness-assessed "})
    assert "MISSINGNESS_ASSESSMENT_NONCANONICAL" in {
        item["code"] for item in padded["findings"]
    }
    assert padded["status"] == "blocked"


def test_review_commitment_lists_must_be_canonical_before_drafting():
    base = {
        "title": "Review commitment fixture", "question": "Question",
        "decision": "Decision", "outcome": "score", "unit_of_observation": "unit",
        "human_participants": False,
    }
    padded = scaffold_design({
        **base,
        "exclusions": [" Exclude broken sensors"],
        "falsification_conditions": ["Null effect in the registered interval "],
    })
    codes = {item["code"] for item in padded["findings"]}
    assert "EXCLUSION_RULE_NONCANONICAL" in codes
    assert "FALSIFICATION_CONDITION_NONCANONICAL" in codes
    assert padded["status"] == "blocked"


@pytest.mark.parametrize("study_type", ["causal", "correlational", "exploratory", "descriptive"])
def test_assignment_plan_does_not_satisfy_masking_review(study_type):
    brief = {"title": "Synthetic masking fixture", "question": "Question", "decision": "Decision",
             "outcome": "Score", "unit_of_observation": "unit", "study_type": study_type,
             "randomization_plan": "Seeded random assignment", "human_participants": False}
    result = scaffold_design(brief)
    assert "BLINDING_UNRESOLVED" in {item["code"] for item in result["findings"]}
    plan = "Collection cannot be masked; condition labels are withheld from the outcome assessor and analyst until the analysis is locked."
    revised = scaffold_design({**brief, "blinding_plan": plan})
    assert "BLINDING_UNRESOLVED" not in {item["code"] for item in revised["findings"]}
    assert revised["artifacts"]["protocol-draft.json"]["blinding_plan"] == plan
    assert revised["status"] != "approved"


def test_omitted_human_scope_is_not_nonhuman_clearance():
    brief = {"title": "Fixture", "question": "Question", "decision": "Decision",
             "outcome": "Outcome", "outcome_unit": "units", "unit_of_observation": "unit"}
    unresolved = scaffold_design(brief)
    assert unresolved["status"] == "blocked"
    assert unresolved["artifacts"]["protocol-draft.json"]["human_subjects"] is None
    assert "HUMAN_SCOPE_UNRESOLVED" in {item["code"] for item in unresolved["findings"]}
    nonhuman = scaffold_design({**brief, "human_participants": False})
    assert nonhuman["status"] == "review_required"
    assert nonhuman["artifacts"]["protocol-draft.json"]["human_subjects"] is False
    human = scaffold_design({**brief, "human_participants": True})
    assert human["status"] == "blocked"
    assert "HUMAN_REVIEW_REQUIRED" in {item["code"] for item in human["findings"]}


def test_human_review_receipt_alone_does_not_clear_design() -> None:
    brief = {
        "title": "Fixture", "question": "Question", "decision": "Decision",
        "outcome": "Outcome", "unit_of_observation": "participant",
        "human_participants": True, "independent_review": True,
        "independent_review_receipt": "IRB-001",
    }
    codes = {item["code"] for item in scaffold_design(brief)["findings"]}
    assert "HUMAN_REVIEW_RECEIPT_MISSING" not in codes
    assert {
        "HUMAN_REVIEW_DECISION_MISSING", "HUMAN_REVIEWER_ROLE_MISSING",
        "HUMAN_REVIEW_TIME_MISSING", "HUMAN_REVIEW_SCOPE_MISSING",
        "HUMAN_REVIEW_DIGEST_MISSING",
    } <= codes


def test_conditional_human_review_requires_recorded_conditions() -> None:
    brief = {
        "title": "Fixture", "question": "Question", "decision": "Decision",
        "outcome": "Outcome", "unit_of_observation": "participant",
        "human_participants": True, "independent_review": True,
        "independent_review_receipt": "IRB-001",
        "independent_review_decision": "approved_with_conditions",
        "independent_reviewer_role": "Institutional review board",
        "independent_reviewed_at": "2026-09-04T01:00:00Z",
        "independent_review_scope": "Protocol and consent materials",
        "independent_review_artifact_locator": "review/decision.pdf",
        "independent_review_artifact_sha256": "b" * 64,
    }
    result = scaffold_design(brief)
    assert "HUMAN_REVIEW_CONDITIONS_MISSING" in {item["code"] for item in result["findings"]}
    padded_safeguard = scaffold_design({
        **brief,
        "consent_plan": " Written consent.",
        "withdrawal_plan": "Withdrawal without penalty.",
        "privacy_plan": "Pseudonymous records.",
        "retention_deletion_plan": "Delete identifiers after retention.",
        "risk_description": "Low risk.",
        "vulnerable_population_plan": "Adults only.",
        "data_security_plan": "Encrypted storage.",
        "incidental_findings_plan": "Escalate safety-relevant findings.",
    })
    assert "HUMAN_SAFEGUARD_NONCANONICAL" in {
        item["code"] for item in padded_safeguard["findings"]
    }
    padded_review = scaffold_design({
        **brief,
        "consent_plan": "Written consent.",
        "withdrawal_plan": "Withdrawal without penalty.",
        "privacy_plan": "Pseudonymous records.",
        "retention_deletion_plan": "Delete identifiers after retention.",
        "risk_description": "Low risk.",
        "vulnerable_population_plan": "Adults only.",
        "data_security_plan": "Encrypted storage.",
        "incidental_findings_plan": "Escalate safety-relevant findings.",
        "independent_review_receipt": " IRB-001",
        "independent_review_conditions": ["Submit annual report "],
    })
    assert "HUMAN_REVIEW_NONCANONICAL" in {
        item["code"] for item in padded_review["findings"]
    }
    assert padded_review["status"] == "blocked"
    malformed_digest = scaffold_design({
        **brief,
        "consent_plan": "Written consent.",
        "withdrawal_plan": "Withdrawal without penalty.",
        "privacy_plan": "Pseudonymous records.",
        "retention_deletion_plan": "Delete identifiers after retention.",
        "risk_description": "Low risk.",
        "vulnerable_population_plan": "Adults only.",
        "data_security_plan": "Encrypted storage.",
        "incidental_findings_plan": "Escalate safety-relevant findings.",
        "independent_review_artifact_sha256": "B" * 64,
    })
    assert "HUMAN_REVIEW_DIGEST_INVALID" in {
        item["code"] for item in malformed_digest["findings"]
    }
    assert malformed_digest["status"] == "blocked"


@pytest.mark.parametrize("field", ["question", "consent_plan", "independent_review_receipt", "study_type", "analysis_commitment"])
@pytest.mark.parametrize("value", [None, True, 42, {}, []])
def test_malformed_answers_do_not_satisfy_design_review(field, value):
    brief = {"title": "Synthetic fixture", "question": "Question", "decision": "Decision",
             "outcome": "Outcome", "unit_of_observation": "pot", field: value}
    with pytest.raises(ValueError, match=f"field {field} must be a string"):
        scaffold_design(brief)


@pytest.mark.parametrize("field", ["controls", "confounds", "exclusions"])
def test_blank_list_entries_do_not_count_as_design_content(field):
    brief = {"title": "Synthetic fixture", "question": "Question", "decision": "Decision",
             "outcome": "Outcome", "unit_of_observation": "pot", field: [" "]}
    with pytest.raises(ValueError, match="non-blank strings"):
        scaffold_design(brief)


def test_design_audit_blocks_declared_pseudoreplication(tmp_path: Path, capsys) -> None:
    brief = {"title": "Synthetic design fixture", "question": "Does condition change height?",
             "decision": "Compare conditions", "outcome": "height", "outcome_unit": "mm",
             "unit_of_observation": "pot-day", "independent_unit": "pot", "unit_id_column": "pot_id",
             "repeated_measures": True, "analysis_design": "independent_groups", "human_participants": False}
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief))
    assert main(["--json", "design", "scaffold", "--brief-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "blocked"
    assert "PSEUDOREPLICATION_RISK" in {item["code"] for item in result["findings"]}
    dictionary = result["artifacts"]["data-dictionary-draft.json"]
    assert dictionary["independent_unit"] == "pot"
    assert dictionary["repeated_measures"] is True
    columns = {item["name"]: item for item in dictionary["proposed_columns"]}
    assert columns["observation_id"]["role"] == "row_identity"
    assert columns["pot_id"]["role"] == "independent_unit_identity"
    assert "not a new identifier" in columns["pot_id"]["constraint"]
    collection = result["artifacts"]["collection-plan.md"]
    assert "Repeated observations retain the same unit ID" in collection
    assert "not an executable collection validator" in collection
    brief["analysis_design"] = "repeated_measures"
    brief["unit_analysis_plan"] = "Model repeated pot-day rows by pot ID with a prespecified time effect."
    path.write_text(json.dumps(brief))
    assert main(["--json", "design", "scaffold", "--brief-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "review_required"
    assert "DEPENDENCE_METHOD_REVIEW" in {item["code"] for item in result["findings"]}


def test_human_causal_scaffold_fails_closed_until_safeguards_exist(tmp_path: Path, capsys) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({
        "title": "Bedtime and concentration", "question": "Does an earlier bedtime improve next-day concentration?",
        "decision": "Whether to recommend a bedtime intervention.", "study_type": "causal",
        "outcome": "Concentration score", "unit_of_observation": "participant-day",
        "human_participants": True, "controls": [], "confounds": [],
    }), encoding="utf-8")
    assert main(["--json", "design", "scaffold", "--brief-file", str(brief)]) == 0
    payload = json.loads(capsys.readouterr().out)["result"]
    assert payload["status"] == "blocked"
    codes = {finding["code"] for finding in payload["findings"]}
    assert {"HUMAN_CONSENT_MISSING", "HUMAN_PRIVACY_MISSING", "HUMAN_REVIEW_REQUIRED", "CAUSAL_COMPARISON_MISSING",
            "HUMAN_VULNERABILITY_PLAN_MISSING", "HUMAN_DATA_SECURITY_MISSING",
            "HUMAN_INCIDENTAL_FINDINGS_MISSING"} <= codes
    assert payload["artifacts"]["hypothesis-proposal.json"]["generated_by"] == "guided_experiment_scaffold"


def test_complete_nonhuman_scaffold_remains_review_only(tmp_path: Path, capsys) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({
        "title": "Seedling light trial", "question": "Does blue light change seedling height?", "decision": "Choose a greenhouse light.", "human_participants": False,
        "study_type": "causal", "assignment_type": "randomized", "intervention": "blue light", "comparison": "white light", "outcome": "height", "outcome_unit": "millimetres",
        "manipulated_factors": ["light spectrum"],
        "primary_estimand": "Mean final height under blue light minus white light.",
        "contrast_definition": "blue light minus white light",
        "contrast_groups": ["blue light", "white light"],
        "group_data_column": "light_condition",
        "expected_effect_direction": "two_sided", "null_value": 0.0,
        "support_rule": "interval_excludes_null", "confidence_level": 0.95,
        "unit_of_observation": "independent pot", "sampling_plan": "Randomly sample pots from one tray.", "randomization_plan": "Randomize pots to light.",
        "controls": ["White-light control"], "confounds": ["Tray position"], "calibration_plan": "Verify light meter against a reference.",
            "control_definitions": [{
                "control_id": "white-light-control",
                "registered_control": "White-light control",
                "family": "reference",
                "purpose": "Bound ordinary growth under the comparison light condition.",
                "expected_behavior": "White-light seedlings remain measurable under the same endpoint procedure.",
                "evaluation_gate_id": "white-light-control-evaluated",
            }],
            "control_measurements": [_control_measurement("White-light control")],
            "measurement_validity": "Measure a marked stem with a calibrated ruler.", "analysis_commitment": "Estimate mean difference with a confidence interval.", "stopping_rule": "20 pots per arm.", "exclusions": [],
            "measurement_validity_checks": [_validity_check()],
            "measurement_observable": "Mean marked-stem height in millimetres per eligible pot.",
            "measurement_input_condition": "All eligible pots at the registered final visit.",
            "measurement_parameter_values": {"ruler_resolution": "1 mm", "readings": "2"},
            "measurement_evaluation_point": "Seven days after assignment.",
            "measurement_convention": "Positive height is upward from the marked stem origin.",
            "measurement_aggregation": "Mean of two blinded readings per pot.",
            "measurement_tolerance": "Paired readings must agree within 2 mm.",
            "measurement_expected_behavior": "Retain every valid reading regardless of treatment direction.",
            "measurement_temporal_role": "post_exposure",
            "outcome_data_column": "height_mm",
            "population": "Eligible seedlings from the registered tray population.",
            "setting": "The registered greenhouse bay.",
            "effect_scale": "Mean height difference",
            "conclusion_time_window": "The registered final measurement day.",
            "smallest_effect_size_of_interest": 5.0,
            "non_supporting_direction": "inconclusive",
            "higher_level_conclusions_unsupported": [
                "No mechanism or generalization beyond the registered greenhouse setting."
            ],
        }), encoding="utf-8")
    assert main(["--json", "design", "scaffold", "--brief-file", str(brief)]) == 0
    payload = json.loads(capsys.readouterr().out)["result"]
    assert payload["status"] == "review_required"
    assert "REVIEW REQUIRED" in payload["artifacts"]["protocol-draft.json"]["hypotheses_tested"][0]
    assert payload["artifacts"]["protocol-draft.json"]["measurement_custody_requirements"]
    assert payload["artifacts"]["protocol-draft.json"]["manipulated_factors"] == ["light spectrum"]
    measurement = payload["artifacts"]["measurement-definition-draft.json"]
    assert measurement["observable"].startswith("Mean marked-stem height")
    assert measurement["parameter_values"]["ruler_resolution"] == "1 mm"
    assert measurement["temporal_role"] == "post_exposure"
    assert "MEASUREMENT_CONTRACT_INCOMPLETE" not in {
        item["code"] for item in payload["findings"]
    }
    assert "CAUSAL_GRAPH_UNRESOLVED" in {item["code"] for item in payload["findings"]}
    assert payload["artifacts"]["causal-identification-audit.json"]["status"] == "unresolved"


def test_causal_scaffold_blocks_open_backdoor_and_carries_passing_audit() -> None:
    base = {
        "title": "Causal fixture", "question": "Does treatment change outcome?",
        "decision": "Choose treatment", "study_type": "causal", "intervention": "treatment",
        "comparison": "control", "outcome": "outcome", "unit_of_observation": "unit",
        "human_participants": False, "confounds": ["baseline"],
    }
    graph = {
        "nodes": [{"id": "treatment", "observed": True}, {"id": "outcome", "observed": True},
                  {"id": "baseline", "observed": True}],
        "edges": [{"cause": "baseline", "effect": "treatment"},
                  {"cause": "baseline", "effect": "outcome"},
                  {"cause": "treatment", "effect": "outcome"}],
        "exposure": "treatment", "outcome": "outcome", "proposed_adjustment_set": [],
        "assignment_type": "observational",
        "assumptions": [{
                "category": category,
                "statement": f"Synthetic {category} assumption.",
                "assessment_kind": "design_record_review",
                "assessment_plan": f"Assess {category} before interpretation.",
            "failure_response": f"Stop causal interpretation if {category} fails.",
            "assessment_gate_id": f"causal-{category}-assessed",
        } for category in (
            "positivity", "consistency", "interference", "temporal_order",
            "measurement_validity", "selection_bias", "exchangeability",
        )],
        "causal_estimand": {
            "target_hypothesis_id": "[REVIEW REQUIRED] bind the reviewed hypothesis",
            "description": "Mean outcome under treatment minus control at day 7.",
            "population": "Eligible study units.",
            "exposure_strategies": ["assign treatment", "assign control"],
            "outcome_variable": "outcome",
            "time_zero": "At assignment.",
            "outcome_time": "Seven days after assignment.",
            "contrast": "Treatment minus control.",
            "summary_measure": "Population mean difference.",
            "intercurrent_events_policy": "Retain assigned units and disclose missing outcomes.",
        },
    }
    blocked = scaffold_design({**base, "causal_identification": graph})
    assert blocked["status"] == "blocked"
    assert "CAUSAL_OPEN_BACKDOOR_PATH" in {item["code"] for item in blocked["findings"]}
    reviewed = scaffold_design({
        **base, "causal_identification": {**graph, "proposed_adjustment_set": ["baseline"]}
    })
    assert "CAUSAL_GRAPH_UNRESOLVED" not in {item["code"] for item in reviewed["findings"]}
    audit = reviewed["artifacts"]["causal-identification-audit.json"]
    assert audit["backdoor_criterion_satisfied"] is True
    assert audit["minimal_observed_adjustment_sets"] == [["baseline"]]
    protocol = reviewed["artifacts"]["protocol-draft.json"]
    assert protocol["protocol_kind"] == "observational"
    assert "assignment: observational; exposure: treatment" in protocol["methodology"]
    adjusted = scaffold_design({
        **base,
        "primary_analysis_family": "adjusted_linear_effect",
        "primary_estimand": "Mean outcome under treatment minus control at day 7.",
        "contrast_definition": "treatment minus control",
        "contrast_groups": ["treatment", "control"],
        "group_data_column": "treatment",
        "outcome_data_column": "outcome",
        "causal_identification": {**graph, "proposed_adjustment_set": ["baseline"]},
    })
    contract = adjusted["artifacts"]["protocol-draft.json"]["analysis_contract"]
    assert contract["method"] == "adjusted_linear_effect"
    assert contract["adjustment_columns"] == ["baseline"]
    assert contract["effect_estimate_path"] == "/result/adjusted_mean_difference_first_minus_second"
    assert contract["uncertainty_path"] == "/result/robust_confidence_interval"
    incomplete_graph = {
        **graph,
        "proposed_adjustment_set": ["baseline"],
        "assumptions": graph["assumptions"][:-1],
    }
    incomplete = scaffold_design({**base, "causal_identification": incomplete_graph})
    assert "CAUSAL_ASSUMPTIONS_INCOMPLETE" in {
        item["code"] for item in incomplete["findings"]
    }
    assert incomplete["status"] == "blocked"
    omitted = scaffold_design({
        **base, "confounds": ["baseline", "site"],
        "causal_identification": {**graph, "proposed_adjustment_set": ["baseline"]},
    })
    assert "CAUSAL_CONFOUND_NOT_IN_GRAPH" in {item["code"] for item in omitted["findings"]}
    assert omitted["status"] == "blocked"


def test_causal_intent_does_not_determine_assignment_mechanism() -> None:
    base = {
        "title": "Assignment fixture", "question": "Does exposure change outcome?",
        "decision": "Choose a strategy", "study_type": "causal",
        "outcome": "outcome", "unit_of_observation": "unit",
        "comparison": "control", "human_participants": False,
    }
    unresolved = scaffold_design(base)
    assert "REVIEW REQUIRED" in unresolved["artifacts"]["protocol-draft.json"]["protocol_kind"]
    assert "CAUSAL_ASSIGNMENT_TYPE_UNRESOLVED" in {
        item["code"] for item in unresolved["findings"]
    }
    randomized = scaffold_design({
        **base, "assignment_type": "randomized", "intervention": "assigned treatment",
        "randomization_plan": "Use the frozen seeded assignment schedule.",
    })
    assert randomized["artifacts"]["protocol-draft.json"]["protocol_kind"] == "experimental"
    observational = scaffold_design({
        **base, "assignment_type": "observational",
        "exposure_definition": "Exposure recorded before outcome follow-up.",
    })
    assert observational["artifacts"]["protocol-draft.json"]["protocol_kind"] == "observational"
    assert "CAUSAL_INTERVENTION_MISSING" not in {
        item["code"] for item in observational["findings"]
    }
    graph = {
        "nodes": [{"id": "exposure", "observed": True}, {"id": "outcome", "observed": True}],
        "edges": [{"cause": "exposure", "effect": "outcome"}],
        "exposure": "exposure", "outcome": "outcome", "proposed_adjustment_set": [],
        "assignment_type": "observational", "assumptions": [],
    }
    conflicted = scaffold_design({
        **base, "assignment_type": "randomized", "intervention": "treatment",
        "causal_identification": graph,
    })
    assert "CAUSAL_ASSIGNMENT_CONFLICT" in {item["code"] for item in conflicted["findings"]}
    assert "REVIEW REQUIRED" in conflicted["artifacts"]["protocol-draft.json"]["protocol_kind"]


def test_human_scaffold_requires_review_receipt_not_only_boolean(tmp_path: Path, capsys) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({
        "title": "Reviewed human study", "question": "Does the intervention change the outcome?", "decision": "Whether to continue.",
        "study_type": "causal", "intervention": "registered intervention", "comparison": "registered control",
        "outcome": "score", "outcome_unit": "points", "unit_of_observation": "participant",
        "sampling_plan": "Fixed eligible sample.", "randomization_plan": "Random assignment.",
        "controls": ["Registered control"], "confounds": ["Baseline score"],
        "calibration_plan": "Check instrument against its reference.", "measurement_validity": "Validated instrument.",
        "analysis_commitment": "Registered mean comparison.", "stopping_rule": "Fixed sample.", "exclusions": [],
        "human_participants": True, "consent_plan": "Written consent.", "withdrawal_plan": "Withdrawal without penalty.",
        "privacy_plan": "Pseudonymous records.", "retention_deletion_plan": "Delete identifiers after retention.",
        "risk_description": "Low risk with escalation plan.", "independent_review": True,
    }), encoding="utf-8")
    assert main(["--json", "design", "scaffold", "--brief-file", str(brief)]) == 0
    payload = json.loads(capsys.readouterr().out)["result"]
    assert payload["status"] == "blocked"
    assert "HUMAN_REVIEW_RECEIPT_MISSING" in {item["code"] for item in payload["findings"]}
