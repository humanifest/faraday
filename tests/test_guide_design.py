"""G04 guide design preview stays behind existing scaffold and registry rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_machine.addons.registry import default_registry
from research_machine.design.scaffold import scaffold_design
from research_machine.domain.errors import NotFoundError
from research_machine.interfaces.cli import main


def _brief() -> dict:
    return {
        "title": "Synthetic independent-group preview",
        "question": "Could assignment change a synthetic score?",
        "decision": "Whether to design a later reviewed study.",
        "outcome": "score",
        "unit_of_observation": "independent unit",
        "independent_unit": "One fabricated unit contributes one outcome.",
        "human_participants": False,
        "study_type": "exploratory",
        "assignment_type": "randomized",
        "comparison": "control",
        "outcome_unit": "points",
        "outcome_scale": "interval",
        "primary_analysis_family": "mean_difference",
        "analysis_design": "independent_groups",
        "unit_id_column": "unit",
        "group_data_column": "group",
        "outcome_data_column": "score",
        "measurement_temporal_role": "post_exposure",
        "primary_estimand": "Mean assigned-group score difference.",
        "contrast_definition": "treatment minus control",
        "contrast_groups": ["treatment", "control"],
        "expected_effect_direction": "two_sided",
        "null_value": 0.0,
        "support_rule": "interval_excludes_null",
        "confidence_level": 0.95,
        "stopping_rule": "Stop at the prospective enrollment cap.",
        "minimum_analyzable_units": 31,
        "maximum_excluded_fraction": 0.1,
        "maximum_group_excluded_fraction_difference": 0.1,
        "missingness_assumption": "Unavailable outcomes do not materially distort the contrast.",
        "missingness_assessment_plan": "Inspect total and group-specific patterns.",
        "missingness_failure_response": "Stop primary interpretation.",
        "missingness_assessment_kind": "empirical_diagnostic",
        "missingness_assessment_gate_id": "missingness-assessed",
        "multiplicity_method": "exploratory_only",
        "multiple_testing_policy": "All reported analyses are exploratory and labeled accordingly.",
        "sample_size_plan": {
            "strategy": "precision",
            "specification": {
                "study_design": "independent_groups",
                "target_half_width": 1.0,
                "assumed_standard_deviation": 2.0,
                "confidence_level": 0.95,
                "anticipated_attrition_fraction": 0.1,
            },
            "justification": "Prospective interval-width target for the synthetic outcome.",
        },
    }


def _error_codes(result: dict) -> set[str]:
    return {item["code"] for item in result["findings"] if item["severity"] == "error"}


def test_review_only_design_preview_and_registered_method_metadata(tmp_path: Path, capsys) -> None:
    brief = _brief()
    brief_file = tmp_path / "brief.json"
    brief_file.write_text(json.dumps(brief), encoding="utf-8")
    workspace = tmp_path / "workspace"
    assert main([
        "--workspace", str(workspace), "--json", "design", "scaffold",
        "--brief-file", str(brief_file),
    ]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "review_required"
    assert _error_codes(result) == set()
    assert not workspace.exists()

    artifacts = result["artifacts"]
    protocol = artifacts["protocol-draft.json"]
    measurement = artifacts["measurement-definition-draft.json"]
    analysis = artifacts["analysis-commitment-draft.json"]
    size = artifacts["sample-size-plan-draft.json"]
    assert protocol["sampling_unit"] == brief["unit_of_observation"]
    assert protocol["unit_id_column"] == brief["unit_id_column"]
    assert protocol["sample_size_or_stopping_rule"] == brief["stopping_rule"]
    assert protocol["multiplicity_method"] == "exploratory_only"
    assert protocol["missingness_assessment"]["missingness_assessment_gate_id"] == "missingness-assessed"
    assert measurement["data_column"] == "score"
    assert measurement["scale_type"] == "interval"
    assert measurement["temporal_role"] == "post_exposure"
    assert analysis["primary_estimand"] == brief["primary_estimand"]
    assert analysis["contrast_definition"] == brief["contrast_definition"]
    assert analysis["contrast_groups"] == brief["contrast_groups"]
    assert analysis["confidence_level"] == 0.95
    assert size["calculation"]["target_half_width"] == 1.0
    assert size["calculation"]["analyzable_n_per_group"] == 31
    assert size["scientific_interpretation_verified"] is False
    assert protocol["scaffold_provenance"]["authority"] == "review_only"

    assert main(["--workspace", str(workspace), "--json", "addon", "list"]) == 0
    catalog = json.loads(capsys.readouterr().out)["result"]
    assert any(
        method["method_id"] == "independent_mean_difference_ci"
        for addon_item in catalog for method in addon_item["methods"]
    )
    assert not workspace.exists()

    registry = default_registry(include_installed=False)
    addon, method = registry.resolve_method("independent_mean_difference_ci")
    assert addon.addon_id == "general_science"
    assert method.method_id == "independent_mean_difference_ci"
    assert {"groups", "study_design", "outcome_column"} <= set(method.required_spec_fields)
    assert "Causal interpretation additionally requires" in method.maximum_claim_ceiling
    with pytest.raises(NotFoundError, match="analysis method not found"):
        registry.resolve_method("unregistered_favorable_method")


def test_incompatible_scales_units_designs_and_causal_timing_block() -> None:
    brief = _brief()
    assert "ANALYSIS_SCALE_INCOMPATIBLE" in _error_codes(scaffold_design({
        **brief, "outcome_scale": "nominal",
    }))
    assert "MEASUREMENT_COLUMN_RESERVED" in _error_codes(scaffold_design({
        **brief, "unit_id_column": "score",
    }))
    assert "ANALYSIS_DESIGN_FAMILY_CONFLICT" in _error_codes(scaffold_design({
        **brief, "primary_analysis_family": "paired_mean_difference",
    }))
    causal = {**brief, "study_type": "causal", "intervention": "treatment"}
    assert "CAUSAL_OUTCOME_TIMING_INVALID" in _error_codes(scaffold_design({
        **causal, "measurement_temporal_role": "pre_exposure",
    }))
    assert "CONTRAST_GROUPS_INVALID" in _error_codes(scaffold_design({
        **causal, "contrast_groups": ["treatment", "treatment"],
    }))
    assert "INFERENCE_COMMITMENT_INCOMPLETE" in _error_codes(scaffold_design({
        **causal, "primary_estimand": "",
    }))
    assert "SAMPLE_SIZE_INFORMATION_MISMATCH" in _error_codes(scaffold_design({
        **brief, "minimum_analyzable_units": 62,
    }))
    assert "SAMPLE_SIZE_CONFIDENCE_MISMATCH" in _error_codes(scaffold_design({
        **brief, "confidence_level": 0.90,
    }))
