"""Synthetic meta-analysis validates deterministic mechanics, not conclusions."""
import copy
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.meta_analysis import (
    execute_meta_analysis,
    validate_meta_analysis_boundary,
)


def write_json(path, value):
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode(); path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def mapped_claim(study_id):
    if study_id == "missing":
        return {"extraction_id": "claim-missing",
                "extraction_claim_sha256": "a" * 64,
                "source_id": "source-missing",
                "source_retained_file_sha256": "legacy_missing",
                "result_direction": "mixed",
                "interpretive_ceiling": "reviewed_source_claim",
                "citation_verdict": "supported",
                "citation_checked_location": "not reported"}
    suffix = study_id.removeprefix("s")
    return {"extraction_id": f"claim-{suffix}",
            "extraction_claim_sha256": "a" * 64,
            "source_id": f"source-{suffix}",
            "source_retained_file_sha256": "b" * 64,
            "result_direction": "mixed",
            "interpretive_ceiling": "reviewed_source_claim",
            "citation_verdict": "supported",
            "citation_checked_location": f"page {suffix}"}


def claim_source_provenance(record):
    return [{key: claim[key] for key in ("extraction_id", "extraction_claim_sha256",
                                         "source_id", "source_retained_file_sha256",
                                         "citation_checked_location")}
            for claim in record["mapped_claims"]]


def source_summary_digest(summary):
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_summary(study_id, status="available"):
    if status == "unavailable":
        return {"study_id": study_id, "status": status, "reason": "Not reported",
                "evidence_location": "results", "experimental": None,
                "comparator": None}
    suffix = int(study_id.removeprefix("s")) if study_id.startswith("s") else 1
    return {"study_id": study_id, "status": status, "reason": "Reported arms",
            "evidence_location": f"table {suffix}",
            "experimental": {"sample_size": 25, "mean": 2.0 + suffix,
                             "standard_deviation": 1.0},
            "comparator": {"sample_size": 25, "mean": 1.0 + suffix,
                           "standard_deviation": 1.0}}


def artifacts(tmp_path, model="fixed_effect", minimum=2, count=3,
              sensitivities=None):
    if sensitivities is None:
        sensitivities = ["leave_one_study_out", "exclude_high_or_unclear_bias",
                         "alternate_random_effects" if model == "fixed_effect" else "alternate_fixed_effect"]
    plan = tmp_path / "plan.json"
    plan_sha = write_json(plan, {"synthesis_plan_version": 1, "status": "synthesis_plan_frozen",
        "synthesis_type": "quantitative", "statistical_model": model, "effect_measure": "mean_difference",
        "contrast_definition": "experimental versus comparator",
        "minimum_independent_studies": minimum, "plan_id": "p1", "snapshot_id": "snap",
        "sensitivity_analyses": sensitivities,
        "scientific_evidence_eligible": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "A frozen synthesis plan is a prospective commitment, not evidence.",
        ]})
    records = [{"study_id": f"s{i}", "status": "available", "reason": "Reported arms",
                "effect_measure": "mean_difference", "estimate": value,
                "standard_error": 1.0, "variance": 1.0, "sample_size": 50,
                "evidence_location": f"table {i}", "derivation": "Recomputed from retained arm summaries",
                "risk_of_bias": "high" if i == 3 else "low",
                "mapped_claims": [mapped_claim(f"s{i}")]}
               for i, value in enumerate([1.0, 2.0, 6.0][:count], start=1)]
    records.append({"study_id": "missing", "status": "unavailable", "reason": "Not reported",
                    "effect_measure": "mean_difference", "estimate": None,
                    "standard_error": None, "variance": None, "sample_size": None,
                    "evidence_location": "results", "derivation": "Not reported",
                    "risk_of_bias": "unclear", "mapped_claims": [mapped_claim("missing")]})
    source_summaries = [source_summary(f"s{i}") for i in range(1, count + 1)]
    source_summaries.append(source_summary("missing", "unavailable"))
    effects = tmp_path / "effects.json"
    effects_sha = write_json(effects, {"effect_records_version": 1, "status": "effects_ready",
        "inputs": {"synthesis_plan_sha256": plan_sha}, "effect_measure": "mean_difference",
        "plan_id": "p1", "snapshot_id": "snap",
        "derivation_scope": "recomputed_from_source_reported_arm_summaries",
        "contrast_definition": "experimental versus comparator",
        "source_summaries": source_summaries, "records": records,
        "study_count": len(records), "available_effect_count": count,
        "unavailable_effect_count": 1, "minimum_independent_studies": minimum,
        "scientific_evidence_eligible": False, "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Effect values are reviewer assertions.",
            "Unavailable statistics remain explicit.",
        ]})
    verification = tmp_path / "effect-verification.json"
    verification_sha = write_json(verification, {"effect_verification_version": 1,
        "status": "effect_verification_recorded", "effect_records_sha256": effects_sha,
        "plan_id": "p1", "snapshot_id": "snap",
        "contrast_definition": "experimental versus comparator",
        "effect_reviewer": "Effect reviewer", "verification_reviewer": "Independent checker",
        "independent_review": True, "mismatch_study_ids": [],
        "scientific_evidence_eligible": False, "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "The machine records an independent check but does not read the cited source.",
            "Matching calculations verify arithmetic from retained summaries only.",
        ],
        "assessments": [
            {"study_id": f"s{i}", "effect_status": "available",
             "source_values_match": True, "calculation_matches": True,
             "retained_source_summary_sha256": source_summary_digest(source_summary(f"s{i}")),
             "claim_source_provenance": claim_source_provenance(records[i - 1]),
             "checked_location": f"table {i}",
             "rationale": "Checked retained source summary and arithmetic"}
            for i in range(1, count + 1)
        ] + [{"study_id": "missing", "effect_status": "unavailable",
              "source_values_match": None, "calculation_matches": None,
              "retained_source_summary_sha256": source_summary_digest(source_summary("missing", "unavailable")),
              "claim_source_provenance": claim_source_provenance(records[-1]),
              "checked_location": "results",
              "rationale": "Confirmed no compatible statistics"}]})
    deviations = tmp_path / "deviations.json"
    deviations_sha = write_json(deviations, {"synthesis_deviations_version": 1,
        "synthesis_plan_sha256": plan_sha, "plan_id": "p1", "snapshot_id": "snap",
        "reviewer": "Deviation reviewer", "status": "no_deviations_declared", "deviations": [],
        "timing_counts": {
            "after_results_seen": 0,
            "before_extraction": 0,
            "before_synthesis": 0,
            "unknown": 0,
        },
        "claim_ceiling_effect": "cannot_raise",
        "scientific_evidence_eligible": False,
        "plan_amended": False,
        "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "Deviation declarations disclose departures but do not amend the frozen plan.",
        ],
        "frozen_plan_commitments": {
            "synthesis_type": "quantitative",
            "research_question": None,
            "primary_outcome": None,
            "effect_measure": "mean_difference",
            "contrast_definition": "experimental versus comparator",
            "statistical_model": model,
            "minimum_independent_studies": minimum,
            "included_source_ids_at_freeze": None,
            "conclusion_rule": None,
            "deviation_policy": None,
        }})
    return plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha


def test_fixed_effect_cli_pools_and_preserves_unavailable(tmp_path, capsys):
    plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha = artifacts(tmp_path, count=2)
    output = tmp_path / "meta"
    assert main(["--json", "literature", "pool-effects", "--plan-file", str(plan),
        "--expected-plan-sha256", plan_sha, "--effects-file", str(effects),
        "--expected-effects-sha256", effects_sha, "--deviations-file", str(deviations),
        "--effect-verification-file", str(verification),
        "--expected-effect-verification-sha256", verification_sha,
        "--expected-deviations-sha256", deviations_sha, "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["pooled_estimate"] == pytest.approx(1.5)
    assert result["standard_error"] == pytest.approx(2 ** -0.5)
    assert result["prediction_interval_95"] is None
    assert result["contrast_definition"] == "experimental versus comparator"
    assert result["unavailable_studies"] == [{"reason": "Not reported", "study_id": "missing"}]
    assert result["deviation_plan_commitments"]["statistical_model"] == "fixed_effect"
    assert result["retained_source_summaries"] == [
        source_summary("missing", "unavailable"),
        source_summary("s1"),
        source_summary("s2"),
    ]
    assert result["study_provenance"] == [
        {"study_id": "s1", "effect_status": "available", "risk_of_bias": "low", "mapped_claim_ids": ["claim-1"],
         "retained_source_summary_sha256": source_summary_digest(source_summary("s1")),
         "mapped_claim_source_provenance": claim_source_provenance({"mapped_claims": [mapped_claim("s1")]}),
         "effect_verification": {"study_id": "s1", "effect_status": "available", "source_values_match": True,
                                 "calculation_matches": True,
                                 "retained_source_summary_sha256": source_summary_digest(source_summary("s1")),
                                 "claim_source_provenance": claim_source_provenance({"mapped_claims": [mapped_claim("s1")]}),
                                 "checked_location": "table 1"}},
        {"study_id": "s2", "effect_status": "available", "risk_of_bias": "low", "mapped_claim_ids": ["claim-2"],
         "retained_source_summary_sha256": source_summary_digest(source_summary("s2")),
         "mapped_claim_source_provenance": claim_source_provenance({"mapped_claims": [mapped_claim("s2")]}),
         "effect_verification": {"study_id": "s2", "effect_status": "available", "source_values_match": True,
                                 "calculation_matches": True,
                                 "retained_source_summary_sha256": source_summary_digest(source_summary("s2")),
                                 "claim_source_provenance": claim_source_provenance({"mapped_claims": [mapped_claim("s2")]}),
                                 "checked_location": "table 2"}},
        {"study_id": "missing", "effect_status": "unavailable", "risk_of_bias": "unclear",
         "mapped_claim_ids": ["claim-missing"],
         "retained_source_summary_sha256": source_summary_digest(source_summary("missing", "unavailable")),
         "mapped_claim_source_provenance": claim_source_provenance({"mapped_claims": [mapped_claim("missing")]}),
         "effect_verification": {"study_id": "missing", "effect_status": "unavailable", "source_values_match": None,
                                 "calculation_matches": None,
                                 "retained_source_summary_sha256": source_summary_digest(source_summary("missing", "unavailable")),
                                 "claim_source_provenance": claim_source_provenance({"mapped_claims": [mapped_claim("missing")]}),
                                 "checked_location": "results"}},
    ]
    assert result["conclusion_authorized"] is False
    assert result["scientific_evidence_eligible"] is False
    assert result["publication_authorized"] is False
    assert result["small_study_effects"]["status"] == "not_estimable"
    assert result["small_study_effects"]["publication_bias_conclusion"] is False
    assert [item["analysis"] for item in result["planned_sensitivity_results"]] == [
        "leave_one_study_out", "exclude_high_or_unclear_bias", "alternate_random_effects"]
    with pytest.raises(ValidationError, match="already exists"):
        execute_meta_analysis(plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha, output)


def test_random_effects_reports_heterogeneity_prediction_and_influence(tmp_path):
    plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha = artifacts(tmp_path, model="random_effects")
    result = execute_meta_analysis(plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha, tmp_path / "meta")
    assert result["heterogeneity"]["q"] > result["heterogeneity"]["degrees_of_freedom"]
    assert result["heterogeneity"]["tau_squared_der_simonian_laird"] > 0
    assert len(result["prediction_interval_95"]) == 2
    assert len(result["leave_one_study_out"]) == 3
    assert result["inference_method"] == "modified_hartung_knapp_student_t_95"
    assert result["standard_error"] >= result["conventional_standard_error"]
    assert result["critical_value_95"] == pytest.approx(4.303)
    assert result["hartung_knapp_standard_error"] is not None
    assert "confidence_interval_95_normal_approximation" in result["leave_one_study_out"][0]
    excluded = next(item for item in result["planned_sensitivity_results"]
                    if item["analysis"] == "exclude_high_or_unclear_bias")
    assert excluded["status"] == "completed" and excluded["remaining_study_count"] == 2


def test_egger_diagnostic_requires_ten_varying_precisions_and_never_declares_bias(tmp_path):
    plan, plan_sha, effects, _, verification, _, deviations, deviations_sha = artifacts(tmp_path, sensitivities=["leave_one_study_out"])
    value = json.loads(effects.read_text())
    value["records"] = [
        {"study_id": f"s{i}", "status": "available", "reason": "Reported arms",
         "effect_measure": "mean_difference", "estimate": 0.1 + i * 0.02,
         "standard_error": (0.05 + i * 0.01) ** 0.5, "variance": 0.05 + i * 0.01,
         "sample_size": 50, "evidence_location": f"table {i}",
         "derivation": "Recomputed from retained arm summaries", "risk_of_bias": "low",
         "mapped_claims": [mapped_claim(f"s{i}")]}
        for i in range(10)
    ]
    value["source_summaries"] = [source_summary(f"s{i}") for i in range(10)]
    value["study_count"] = 10
    value["available_effect_count"] = 10
    value["unavailable_effect_count"] = 0
    effects_sha = write_json(effects, value)
    verification_sha = write_json(verification, {"effect_verification_version": 1,
        "status": "effect_verification_recorded", "effect_records_sha256": effects_sha,
        "plan_id": "p1", "snapshot_id": "snap",
        "contrast_definition": "experimental versus comparator",
        "effect_reviewer": "Effect reviewer", "verification_reviewer": "Independent checker",
        "independent_review": True, "mismatch_study_ids": [],
        "scientific_evidence_eligible": False, "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "The machine records an independent check but does not read the cited source.",
            "Matching calculations verify arithmetic from retained summaries only.",
        ],
        "assessments": [
            {"study_id": f"s{i}", "effect_status": "available",
             "source_values_match": True, "calculation_matches": True,
             "retained_source_summary_sha256": source_summary_digest(source_summary(f"s{i}")),
             "claim_source_provenance": claim_source_provenance({"mapped_claims": [mapped_claim(f"s{i}")]}),
             "checked_location": f"table {i}",
             "rationale": "Checked retained source summary and arithmetic"} for i in range(10)
        ]})
    result = execute_meta_analysis(plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha, tmp_path / "meta")
    diagnostic = result["small_study_effects"]
    assert diagnostic["status"] == "estimated"
    assert diagnostic["study_count"] == 10
    assert len(diagnostic["intercept_confidence_interval_95"]) == 2
    assert diagnostic["publication_bias_conclusion"] is False


def test_egger_diagnostic_with_constant_precision_is_not_estimable(tmp_path):
    plan, plan_sha, effects, _, verification, _, deviations, deviations_sha = artifacts(tmp_path, sensitivities=["leave_one_study_out"])
    value = json.loads(effects.read_text())
    value["records"] = [
        {"study_id": f"s{i}", "status": "available", "reason": "Reported arms",
         "effect_measure": "mean_difference", "estimate": float(i),
         "standard_error": 1.0, "variance": 1.0, "sample_size": 50,
         "evidence_location": f"table {i}",
         "derivation": "Recomputed from retained arm summaries", "risk_of_bias": "low",
         "mapped_claims": [mapped_claim(f"s{i}")]} for i in range(10)
    ]
    value["source_summaries"] = [source_summary(f"s{i}") for i in range(10)]
    value["study_count"] = 10
    value["available_effect_count"] = 10
    value["unavailable_effect_count"] = 0
    effects_sha = write_json(effects, value)
    verification_sha = write_json(verification, {"effect_verification_version": 1,
        "status": "effect_verification_recorded", "effect_records_sha256": effects_sha,
        "plan_id": "p1", "snapshot_id": "snap",
        "contrast_definition": "experimental versus comparator",
        "effect_reviewer": "Effect reviewer", "verification_reviewer": "Independent checker",
        "independent_review": True, "mismatch_study_ids": [],
        "scientific_evidence_eligible": False, "conclusion_authorized": False,
        "publication_authorized": False,
        "limitations": [
            "The machine records an independent check but does not read the cited source.",
            "Matching calculations verify arithmetic from retained summaries only.",
        ],
        "assessments": [
            {"study_id": f"s{i}", "effect_status": "available",
             "source_values_match": True, "calculation_matches": True,
             "retained_source_summary_sha256": source_summary_digest(source_summary(f"s{i}")),
             "claim_source_provenance": claim_source_provenance({"mapped_claims": [mapped_claim(f"s{i}")]}),
             "checked_location": f"table {i}",
             "rationale": "Checked retained source summary and arithmetic"} for i in range(10)
        ]})
    result = execute_meta_analysis(plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha, tmp_path / "meta")
    assert result["small_study_effects"]["status"] == "not_estimable"
    assert "precisions do not vary" in result["small_study_effects"]["reason"]


def test_retrospective_deviation_forces_meta_analysis_review_status(tmp_path):
    plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, _ = artifacts(tmp_path)
    value = json.loads(deviations.read_text())
    value["status"] = "retrospective_or_uncertain_deviation_review_required"
    value["deviations"] = [{"deviation_id": "d1", "stage": "synthesis",
                            "frozen_commitment": "Use the frozen pooling rule",
                            "actual_method": "Added an exploratory influence note",
                            "reason": "Reviewer requested disclosure",
                            "timing": "unknown",
                            "impact_assessment": "May affect interpretation",
                            "corrective_action": "Force deviation review",
                            "evidence_location": "review log section 4"}]
    value["timing_counts"] = {
        "after_results_seen": 0,
        "before_extraction": 0,
        "before_synthesis": 0,
        "unknown": 1,
    }
    deviations_sha = write_json(deviations, value)
    result = execute_meta_analysis(
        plan, plan_sha, effects, effects_sha, verification, verification_sha,
        deviations, deviations_sha, tmp_path / "meta"
    )
    assert result["status"] == "meta_analysis_deviation_review_required"
    assert result["deviations"] == value["deviations"]


@pytest.mark.parametrize("tamper", [
    "version",
    "input-hash",
    "plan-id",
    "contrast-definition",
    "scientific-authority",
    "conclusion-authority",
    "publication-authority",
    "limitations-missing",
    "deviation-status",
    "status-drift",
    "deviation-plan-effect-measure",
    "deviation-plan-contrast",
    "deviation-plan-model",
    "model-drift",
    "available-count",
    "unavailable-studies",
    "pooled-ci-drift",
    "heterogeneity-df",
    "fixed-hk-se",
    "prediction-for-fixed",
    "loo-missing",
    "loo-ci-drift",
    "retained-summary-digest",
    "sensitivity-missing",
    "sensitivity-result-drift",
    "small-study-conclusion",
    "small-study-count",
])
def test_meta_analysis_boundary_replays_output_summaries(tmp_path, tamper):
    plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha = artifacts(tmp_path)
    result = execute_meta_analysis(
        plan, plan_sha, effects, effects_sha, verification, verification_sha,
        deviations, deviations_sha, tmp_path / "meta"
    )
    candidate = copy.deepcopy(result)
    planned = json.loads(plan.read_text())["sensitivity_analyses"]
    if tamper == "version":
        candidate["meta_analysis_version"] = 2
    elif tamper == "input-hash":
        candidate["inputs"]["effect_records_sha256"] = "A" * 64
    elif tamper == "plan-id":
        candidate["plan_id"] = " p1 "
    elif tamper == "contrast-definition":
        candidate["contrast_definition"] = "not_applicable"
    elif tamper == "scientific-authority":
        candidate["scientific_evidence_eligible"] = True
    elif tamper == "conclusion-authority":
        candidate["conclusion_authorized"] = True
    elif tamper == "publication-authority":
        candidate["publication_authorized"] = True
    elif tamper == "limitations-missing":
        candidate["limitations"] = []
    elif tamper == "deviation-status":
        candidate["deviation_status"] = "review_complete"
    elif tamper == "status-drift":
        candidate["status"] = "meta_analysis_recorded"
        candidate["deviation_status"] = "retrospective_or_uncertain_deviation_review_required"
    elif tamper == "deviation-plan-effect-measure":
        candidate["deviation_plan_commitments"]["effect_measure"] = "log_risk_ratio"
    elif tamper == "deviation-plan-contrast":
        candidate["deviation_plan_commitments"]["contrast_definition"] = "other contrast"
    elif tamper == "deviation-plan-model":
        candidate["deviation_plan_commitments"]["statistical_model"] = "random_effects"
    elif tamper == "model-drift":
        candidate["statistical_model"] = "vote_count"
    elif tamper == "available-count":
        candidate["available_study_count"] = 99
    elif tamper == "unavailable-studies":
        candidate["unavailable_studies"] = []
    elif tamper == "pooled-ci-drift":
        candidate["confidence_interval_95"][0] = candidate["confidence_interval_95"][0] - 1.0
    elif tamper == "heterogeneity-df":
        candidate["heterogeneity"]["degrees_of_freedom"] = 99
    elif tamper == "fixed-hk-se":
        candidate["hartung_knapp_standard_error"] = candidate["standard_error"]
    elif tamper == "prediction-for-fixed":
        candidate["prediction_interval_95"] = candidate["confidence_interval_95"]
    elif tamper == "loo-missing":
        candidate["leave_one_study_out"].pop()
    elif tamper == "loo-ci-drift":
        candidate["leave_one_study_out"][0]["confidence_interval_95_normal_approximation"][1] += 1.0
    elif tamper == "retained-summary-digest":
        candidate["study_provenance"][0]["retained_source_summary_sha256"] = "c" * 64
    elif tamper == "sensitivity-missing":
        candidate["planned_sensitivity_results"].pop()
    elif tamper == "sensitivity-result-drift":
        candidate["planned_sensitivity_results"][0]["results"] = []
    elif tamper == "small-study-conclusion":
        candidate["small_study_effects"]["publication_bias_conclusion"] = True
    elif tamper == "small-study-count":
        candidate["small_study_effects"]["study_count"] = 99
    with pytest.raises(ValidationError):
        validate_meta_analysis_boundary(
            candidate,
            planned_sensitivity_analyses=planned,
        )


@pytest.mark.parametrize(("artifact", "field"), [
    ("effects-study", "effect record study_id"),
    ("mapped-claim", "mapped claim extraction_id"),
    ("verification-study", "effect-verification assessment study_id"),
    ("verification-location", "effect-verification assessment checked_location"),
])
def test_meta_analysis_requires_canonical_effect_and_verification_handles(tmp_path, artifact, field):
    plan, plan_sha, effects, _, verification, _, deviations, deviations_sha = artifacts(tmp_path, count=2)
    effect_value = json.loads(effects.read_text())
    verification_value = json.loads(verification.read_text())
    if artifact == "effects-study":
        effect_value["records"][0]["study_id"] = " s1 "
    elif artifact == "mapped-claim":
        effect_value["records"][0]["mapped_claims"][0]["extraction_id"] = " claim-1 "
    elif artifact == "verification-study":
        verification_value["assessments"][0]["study_id"] = "s1 "
    else:
        verification_value["assessments"][0]["checked_location"] = " table 1 "
    effects_sha = write_json(effects, effect_value)
    verification_value["effect_records_sha256"] = effects_sha
    verification_sha = write_json(verification, verification_value)
    with pytest.raises(ValidationError, match=field):
        execute_meta_analysis(
            plan, plan_sha, effects, effects_sha, verification, verification_sha,
            deviations, deviations_sha, tmp_path / "meta"
        )


@pytest.mark.parametrize("failure", ["plan-hash", "plan-authority", "plan-conclusion-authority", "plan-publication-authority", "plan-limitations-missing", "effects-hash", "model", "link", "measure", "contrast", "derivation-scope", "effects-authority", "effects-conclusion-authority", "effects-publication-authority", "effects-limitations-missing", "effects-count-drift", "effects-availability-count-drift", "effects-readiness-drift", "source-summary-missing", "source-summary-status", "source-summary-arm", "one-study", "variance", "duplicate", "bias", "claim-provenance", "duplicate-claim", "verification-authority", "verification-conclusion-authority", "verification-publication-authority", "verification-limitations-missing", "verification-contrast", "verification-independent-drift", "verification-reviewer-drift", "verification-mismatch-drift", "verification-status-rewrite", "verification-provenance", "verification-duplicate", "verification-missing-status", "verification-missing-source-summary-digest", "verification-source-summary-digest-drift", "verification-missing-claim-source", "verification-source-anchor-drift", "verification-status-drift", "verification-unclean-available", "verification-applicable-unavailable", "deviation-plan", "deviation-contrast", "deviation-authority", "deviation-conclusion-authority", "deviation-publication-authority", "deviation-plan-amended", "deviation-ceiling", "deviation-limitations-missing", "deviation-timing-counts", "deviation-status-rewrite", "deviation-padded-row", "unknown-sensitivity"])
def test_invalid_meta_analysis_never_publishes(tmp_path, failure):
    plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha = artifacts(tmp_path)
    if failure == "plan-hash": plan_sha = "0" * 64
    elif failure in {"plan-authority", "plan-conclusion-authority",
                     "plan-publication-authority", "plan-limitations-missing"}:
        value = json.loads(plan.read_text())
        if failure == "plan-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "plan-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "plan-publication-authority":
            value["publication_authorized"] = True
        else:
            value["limitations"] = []
        plan_sha = write_json(plan, value)
        value = json.loads(effects.read_text())
        value["inputs"]["synthesis_plan_sha256"] = plan_sha
        effects_sha = write_json(effects, value)
        value = json.loads(deviations.read_text())
        value["synthesis_plan_sha256"] = plan_sha
        deviations_sha = write_json(deviations, value)
    elif failure == "effects-hash": effects_sha = "0" * 64
    elif failure == "model":
        value = json.loads(plan.read_text()); value["statistical_model"] = "not_applicable"; plan_sha = write_json(plan, value)
    elif failure == "link":
        value = json.loads(effects.read_text()); value["inputs"]["synthesis_plan_sha256"] = "0" * 64; effects_sha = write_json(effects, value)
    elif failure == "measure":
        value = json.loads(effects.read_text()); value["effect_measure"] = "other"; effects_sha = write_json(effects, value)
    elif failure == "contrast":
        value = json.loads(effects.read_text()); value["contrast_definition"] = "other contrast"; effects_sha = write_json(effects, value)
    elif failure == "derivation-scope":
        value = json.loads(effects.read_text()); value["derivation_scope"] = "reviewer_reported_effect_and_standard_error"; effects_sha = write_json(effects, value)
    elif failure == "effects-authority":
        value = json.loads(effects.read_text()); value["scientific_evidence_eligible"] = True; effects_sha = write_json(effects, value)
    elif failure == "effects-conclusion-authority":
        value = json.loads(effects.read_text()); value["conclusion_authorized"] = True; effects_sha = write_json(effects, value)
    elif failure == "effects-publication-authority":
        value = json.loads(effects.read_text()); value["publication_authorized"] = True; effects_sha = write_json(effects, value)
    elif failure == "effects-limitations-missing":
        value = json.loads(effects.read_text()); value["limitations"] = []; effects_sha = write_json(effects, value)
    elif failure == "effects-count-drift":
        value = json.loads(effects.read_text()); value["study_count"] = 99; effects_sha = write_json(effects, value)
    elif failure == "effects-availability-count-drift":
        value = json.loads(effects.read_text()); value["available_effect_count"] = 99; effects_sha = write_json(effects, value)
    elif failure == "effects-readiness-drift":
        value = json.loads(effects.read_text()); value["status"] = "insufficient_effects"; effects_sha = write_json(effects, value)
    elif failure == "source-summary-missing":
        value = json.loads(effects.read_text()); del value["source_summaries"]; effects_sha = write_json(effects, value)
    elif failure == "source-summary-status":
        value = json.loads(effects.read_text()); value["source_summaries"][0]["status"] = "unavailable"; effects_sha = write_json(effects, value)
    elif failure == "source-summary-arm":
        value = json.loads(effects.read_text()); value["source_summaries"][0]["experimental"]["standard_deviation"] = 0; effects_sha = write_json(effects, value)
    elif failure == "one-study":
        value = json.loads(effects.read_text()); value["records"] = value["records"][:1]; effects_sha = write_json(effects, value)
    elif failure == "variance":
        value = json.loads(effects.read_text()); value["records"][0]["variance"] = 0; effects_sha = write_json(effects, value)
    elif failure == "duplicate":
        value = json.loads(effects.read_text()); value["records"][1]["study_id"] = "s1"; effects_sha = write_json(effects, value)
    elif failure == "bias":
        value = json.loads(effects.read_text()); value["records"][0]["risk_of_bias"] = "safe"; effects_sha = write_json(effects, value)
    elif failure == "claim-provenance":
        value = json.loads(effects.read_text()); value["records"][0]["mapped_claims"] = []; effects_sha = write_json(effects, value)
    elif failure == "duplicate-claim":
        value = json.loads(effects.read_text())
        value["records"][0]["mapped_claims"].append({"extraction_id": "claim-1"})
        effects_sha = write_json(effects, value)
    elif failure == "verification-authority":
        value = json.loads(verification.read_text()); value["scientific_evidence_eligible"] = True; verification_sha = write_json(verification, value)
    elif failure == "verification-conclusion-authority":
        value = json.loads(verification.read_text()); value["conclusion_authorized"] = True; verification_sha = write_json(verification, value)
    elif failure == "verification-publication-authority":
        value = json.loads(verification.read_text()); value["publication_authorized"] = True; verification_sha = write_json(verification, value)
    elif failure == "verification-limitations-missing":
        value = json.loads(verification.read_text()); value["limitations"] = []; verification_sha = write_json(verification, value)
    elif failure == "verification-contrast":
        value = json.loads(verification.read_text()); value["contrast_definition"] = "other contrast"; verification_sha = write_json(verification, value)
    elif failure == "verification-independent-drift":
        value = json.loads(verification.read_text()); value["independent_review"] = False; verification_sha = write_json(verification, value)
    elif failure == "verification-reviewer-drift":
        value = json.loads(verification.read_text()); value["verification_reviewer"] = "Effect reviewer"; verification_sha = write_json(verification, value)
    elif failure == "verification-mismatch-drift":
        value = json.loads(verification.read_text()); value["mismatch_study_ids"] = ["s1"]; verification_sha = write_json(verification, value)
    elif failure == "verification-status-rewrite":
        value = json.loads(verification.read_text())
        value["assessments"][0]["calculation_matches"] = False
        value["mismatch_study_ids"] = ["s1"]
        verification_sha = write_json(verification, value)
    elif failure == "verification-provenance":
        value = json.loads(verification.read_text()); value["assessments"][0]["checked_location"] = ""; verification_sha = write_json(verification, value)
    elif failure == "verification-duplicate":
        value = json.loads(verification.read_text()); value["assessments"][1]["study_id"] = " s1 "; verification_sha = write_json(verification, value)
    elif failure == "verification-missing-status":
        value = json.loads(verification.read_text()); del value["assessments"][0]["effect_status"]; verification_sha = write_json(verification, value)
    elif failure == "verification-missing-source-summary-digest":
        value = json.loads(verification.read_text()); del value["assessments"][0]["retained_source_summary_sha256"]; verification_sha = write_json(verification, value)
    elif failure == "verification-source-summary-digest-drift":
        value = json.loads(verification.read_text())
        value["assessments"][0]["retained_source_summary_sha256"] = "c" * 64
        verification_sha = write_json(verification, value)
    elif failure == "verification-missing-claim-source":
        value = json.loads(verification.read_text()); del value["assessments"][0]["claim_source_provenance"]; verification_sha = write_json(verification, value)
    elif failure == "verification-source-anchor-drift":
        value = json.loads(verification.read_text())
        value["assessments"][0]["claim_source_provenance"][0]["source_retained_file_sha256"] = "c" * 64
        verification_sha = write_json(verification, value)
    elif failure == "verification-status-drift":
        value = json.loads(verification.read_text()); value["assessments"][0]["effect_status"] = "unavailable"; verification_sha = write_json(verification, value)
    elif failure == "verification-unclean-available":
        value = json.loads(verification.read_text()); value["assessments"][0]["calculation_matches"] = False; verification_sha = write_json(verification, value)
    elif failure == "verification-applicable-unavailable":
        value = json.loads(verification.read_text()); value["assessments"][-1]["source_values_match"] = True; verification_sha = write_json(verification, value)
    elif failure == "deviation-plan":
        value = json.loads(deviations.read_text()); value["frozen_plan_commitments"]["statistical_model"] = "random_effects"; deviations_sha = write_json(deviations, value)
    elif failure == "deviation-contrast":
        value = json.loads(deviations.read_text()); value["frozen_plan_commitments"]["contrast_definition"] = "other contrast"; deviations_sha = write_json(deviations, value)
    elif failure in {"deviation-authority", "deviation-conclusion-authority",
                     "deviation-publication-authority", "deviation-plan-amended",
                     "deviation-ceiling", "deviation-limitations-missing",
                     "deviation-timing-counts", "deviation-status-rewrite",
                     "deviation-padded-row"}:
        value = json.loads(deviations.read_text())
        if failure == "deviation-authority":
            value["scientific_evidence_eligible"] = True
        elif failure == "deviation-conclusion-authority":
            value["conclusion_authorized"] = True
        elif failure == "deviation-publication-authority":
            value["publication_authorized"] = True
        elif failure == "deviation-plan-amended":
            value["plan_amended"] = True
        elif failure == "deviation-ceiling":
            value["claim_ceiling_effect"] = "can_raise"
        elif failure == "deviation-limitations-missing":
            value["limitations"] = []
        elif failure == "deviation-timing-counts":
            value["timing_counts"]["unknown"] = 1
        elif failure == "deviation-status-rewrite":
            value["status"] = "prospective_deviations_recorded"
        else:
            value["deviations"] = [{
                "deviation_id": " d1",
                "stage": "synthesis",
                "frozen_commitment": "Use the frozen pooling rule",
                "actual_method": "Added an exploratory influence note",
                "reason": "Reviewer requested disclosure",
                "timing": "before_synthesis",
                "impact_assessment": "May affect interpretation",
                "corrective_action": "Force review",
                "evidence_location": "review log section 4",
            }]
            value["timing_counts"]["before_synthesis"] = 1
            value["status"] = "prospective_deviations_recorded"
        deviations_sha = write_json(deviations, value)
    elif failure == "unknown-sensitivity":
        value = json.loads(plan.read_text()); value["sensitivity_analyses"] = ["unknown"]; plan_sha = write_json(plan, value)
        value = json.loads(effects.read_text()); value["inputs"]["synthesis_plan_sha256"] = plan_sha; effects_sha = write_json(effects, value)
    output = tmp_path / "meta"
    with pytest.raises(ValidationError):
        execute_meta_analysis(plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha, output)
    assert not output.exists()


@pytest.mark.parametrize(("field", "expected"), [
    ("plan", "A" * 64),
    ("effects", "g" * 64),
    ("verification", "0" * 63),
    ("deviations", "0" * 65),
])
def test_meta_analysis_rejects_malformed_expected_hashes(tmp_path, field, expected):
    plan, plan_sha, effects, effects_sha, verification, verification_sha, deviations, deviations_sha = artifacts(tmp_path)
    if field == "plan":
        plan_sha = expected
        message = "expected_plan_sha256 must be a lowercase SHA-256 digest"
    elif field == "effects":
        effects_sha = expected
        message = "expected_effects_sha256 must be a lowercase SHA-256 digest"
    elif field == "verification":
        verification_sha = expected
        message = "expected_effect_verification_sha256 must be a lowercase SHA-256 digest"
    else:
        deviations_sha = expected
        message = "expected_deviations_sha256 must be a lowercase SHA-256 digest"
    output = tmp_path / "meta"
    with pytest.raises(ValidationError, match=message):
        execute_meta_analysis(
            plan, plan_sha, effects, effects_sha, verification, verification_sha,
            deviations, deviations_sha, output,
        )
    assert not output.exists()
