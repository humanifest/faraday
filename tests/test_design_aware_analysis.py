from __future__ import annotations

import pytest

from research_machine.addons.general_science import (
    adjusted_linear_effect,
    independent_mean_difference_ci,
    paired_mean_difference_ci,
    permutation_mean_difference,
)
from research_machine.domain.errors import ValidationError


def _adjusted_fixture():
    """Synthetic full-factorial rows with a known conditional treatment effect."""
    rows = []
    for treatment, group in ((0, "control"), (1, "treatment")):
        for index, (baseline, noise) in enumerate(
            [(-2, -1), (-1, 1), (1, 1), (2, -1)]
        ):
            rows.append({
                "unit": f"{group}-{index}", "group": group,
                "baseline": str(baseline),
                "outcome": str(10 + 2 * treatment + 3 * baseline + noise),
            })
    return rows


def _adjusted_spec():
    return {
        "outcome_column": "outcome", "group_column": "group",
        "groups": ["treatment", "control"],
        "covariate_columns": ["baseline"], "unit_column": "unit",
        "study_design": "independent_groups", "missing_data_policy": "complete_case",
        "confidence_level": 0.95,
    }


def test_adjusted_linear_effect_recovers_registered_conditional_contrast():
    result = adjusted_linear_effect(_adjusted_spec(), _adjusted_fixture())
    assert result["adjusted_mean_difference_first_minus_second"] == pytest.approx(2)
    assert result["adjustment_columns"] == ["baseline"]
    assert result["n_by_group"] == {"treatment": 4, "control": 4}
    assert result["independent_unit_check"]["status"] == "unique_identifiers"
    assert result["robust_confidence_interval"]["lower"] <= 2
    assert result["robust_confidence_interval"]["upper"] >= 2


@pytest.mark.parametrize(("field", "message"), [
    ("outcome_column", "adjusted_linear_effect outcome_column must be canonical"),
    ("group_column", "adjusted_linear_effect group_column must be canonical"),
    ("groups", "group label must be canonical"),
    ("covariate_columns", "adjusted_linear_effect covariate_column must be canonical"),
    ("unit_column", "adjusted_linear_effect unit_column must be canonical"),
])
def test_adjusted_linear_effect_requires_canonical_model_handles(field, message):
    """Synthetic fixture: padded model handles must not be silently rewritten."""
    spec = {
        **_adjusted_spec(),
    }
    if field == "groups":
        spec[field] = [" treatment ", "control"]
    elif field == "covariate_columns":
        spec[field] = [" baseline "]
    else:
        spec[field] = f" {spec[field]} "
    with pytest.raises(ValidationError, match=message):
        adjusted_linear_effect(spec, _adjusted_fixture())


@pytest.mark.parametrize("scale,offset", [(1000, 0), (0.001, 0), (10, -17)])
def test_adjusted_linear_effect_respects_positive_outcome_unit_conversion(scale, offset):
    original = adjusted_linear_effect(_adjusted_spec(), _adjusted_fixture())
    converted_rows = [
        {**row, "outcome": str(scale * float(row["outcome"]) + offset)}
        for row in _adjusted_fixture()
    ]
    converted = adjusted_linear_effect(_adjusted_spec(), converted_rows)
    assert converted["adjusted_mean_difference_first_minus_second"] == pytest.approx(
        scale * original["adjusted_mean_difference_first_minus_second"]
    )
    assert converted["robust_standard_error_hc1"] == pytest.approx(
        scale * original["robust_standard_error_hc1"]
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows[:-5], "each group requires"),
        (lambda rows: [{**row, "baseline": "1"} for row in rows], "constant adjustment"),
        (lambda rows: [*rows, {**rows[-1], "unit": "new", "group": "unknown"}], "unexpected group"),
        (lambda rows: [*rows[:-1], {**rows[-1], "unit": rows[0]["unit"]}], "independent-unit"),
        (lambda rows: [*rows[:-1], {**rows[-1], "baseline": "not-numeric"}], "non-numeric"),
    ],
)
def test_adjusted_linear_effect_fails_closed_on_invalid_design_data(mutation, message):
    with pytest.raises(ValidationError, match=message):
        adjusted_linear_effect(_adjusted_spec(), mutation(_adjusted_fixture()))


def test_adjusted_linear_effect_reports_registered_complete_case_exclusions():
    rows = _adjusted_fixture()
    rows[-1]["baseline"] = ""
    result = adjusted_linear_effect(_adjusted_spec(), rows)
    assert result["exclusion_report"]["excluded_records"] == [
        {"data_record": 8, "missing_columns": ["baseline"]}
    ]
    with pytest.raises(ValidationError, match="explicit complete_case"):
        adjusted_linear_effect(
            {key: value for key, value in _adjusted_spec().items()
             if key != "missing_data_policy"},
            rows,
        )


def test_adjusted_linear_effect_rejects_noncanonical_covariates_before_duplicates():
    spec = {**_adjusted_spec(), "covariate_columns": ["baseline", " baseline "]}
    with pytest.raises(ValidationError, match="covariate_column must be canonical"):
        adjusted_linear_effect(spec, _adjusted_fixture())


@pytest.mark.parametrize("design", ["paired", "independent_groups"])
@pytest.mark.parametrize("scale,offset", [(1000, 0), (0.001, 0), (1, 273.15), (10, -17)])
def test_effect_estimates_respect_positive_unit_conversion(design, scale, offset):
    """Synthetic algebraic invariants, not coverage or empirical validation."""
    rows = [{"pair": str(i), "group": group, "outcome": str(value)}
            for i, pair in enumerate([(1, 3), (4, 7), (2, 8), (6, 5)])
            for group, value in zip(["control", "treatment"], pair)]
    spec = {"outcome_column": "outcome", "group_column": "group", "groups": ["treatment", "control"],
            "pair_column": "pair", "study_design": design, "seed": 42, "bootstrap_resamples": 1000}
    method = paired_mean_difference_ci if design == "paired" else independent_mean_difference_ci
    original = method(spec, rows)
    converted = method(spec, [{**row, "outcome": str(scale * float(row["outcome"]) + offset)} for row in rows])
    assert converted["mean_difference_first_minus_second"] == pytest.approx(scale * original["mean_difference_first_minus_second"])
    for bound in ("lower", "upper"):
        assert converted["confidence_interval"][bound] == pytest.approx(scale * original["confidence_interval"][bound], abs=1e-10)
    standardized = ["standardized_mean_change"] if design == "paired" else ["cohen_d", "hedges_g"]
    for field in standardized:
        assert converted[field] == pytest.approx(original[field])
    assert converted["confidence_interval"]["level"] == original["confidence_interval"]["level"]
    if design == "independent_groups":
        assert converted["pooled_within_group_standard_deviation"] == pytest.approx(
            scale * original["pooled_within_group_standard_deviation"]
        )


@pytest.mark.parametrize(("field", "message"), [
    ("outcome_column", "paired_mean_difference_ci outcome_column must be canonical"),
    ("group_column", "paired_mean_difference_ci group_column must be canonical"),
    ("groups", "group label must be canonical"),
    ("pair_column", "paired_mean_difference_ci pair_column must be canonical"),
])
def test_paired_mean_difference_requires_canonical_pair_and_comparison_handles(field, message):
    rows = [{"pair": str(i), "group": group, "outcome": str(value)}
            for i, pair in enumerate([(1, 3), (4, 7)])
            for group, value in zip(["control", "treatment"], pair)]
    spec = {
        "outcome_column": "outcome",
        "group_column": "group",
        "groups": ["treatment", "control"],
        "pair_column": "pair",
        "study_design": "paired",
        "seed": 42,
        "bootstrap_resamples": 1000,
    }
    if field == "groups":
        spec[field] = [" treatment ", "control"]
    else:
        spec[field] = f" {spec[field]} "
    with pytest.raises(ValidationError, match=message):
        paired_mean_difference_ci(spec, rows)


@pytest.mark.parametrize("method", [independent_mean_difference_ci, permutation_mean_difference])
@pytest.mark.parametrize("outcome", ["", "  ", "99"])
def test_unregistered_group_cannot_be_hidden_by_missing_outcome(method, outcome):
    rows = [{"group": group, "outcome": str(i)}
            for i, group in enumerate(["a", "a", "b", "b"])]
    rows.append({"group": "unregistered", "outcome": outcome})
    spec = {"outcome_column": "outcome", "group_column": "group", "groups": ["a", "b"],
            "study_design": "independent_groups", "seed": 1, "bootstrap_resamples": 1000,
            "permutations": 100, "missing_data_policy": "complete_case"}
    with pytest.raises(ValidationError, match="unexpected group"):
        method(spec, rows)


@pytest.mark.parametrize("method", [independent_mean_difference_ci, permutation_mean_difference])
@pytest.mark.parametrize("column", ["group", "outcome"])
def test_group_comparisons_require_explicit_missingness_policy(method, column):
    rows = [{"group": group, "outcome": str(i)}
            for i, group in enumerate(["a", "a", "b", "b"])]
    rows.append({"group": "a", "outcome": "99", column: ""})
    spec = {"outcome_column": "outcome", "group_column": "group", "groups": ["a", "b"],
            "study_design": "independent_groups", "seed": 1, "bootstrap_resamples": 1000,
            "permutations": 100}
    with pytest.raises(ValidationError, match="explicit complete_case"):
        method(spec, rows)
    result = method({**spec, "missing_data_policy": "complete_case"}, rows)
    assert result["missing_rows"] == 1
    report = result["exclusion_report"]
    assert report["input_records"] == 5
    assert report["included_records"] == 4
    assert report["excluded_records"] == [{"data_record": 5, "missing_columns": [column]}]
    assert report["excluded_by_group"] == {"a": int(column == "outcome"), "b": 0}
    assert report["excluded_without_registered_group"] == int(column == "group")


@pytest.mark.parametrize("labels", [["control", "control"], ["", "control"], ["  ", "control"], [1, "control"]])
@pytest.mark.parametrize("method,design", [
    (paired_mean_difference_ci, "paired"),
    (independent_mean_difference_ci, "independent_groups"),
    (permutation_mean_difference, "independent_groups"),
])
def test_two_group_methods_reject_invalid_comparisons(labels, method, design):
    # A single observation per participant must never become a self-comparison.
    rows = [{"pair": "a", "group": "control", "outcome": "1"},
            {"pair": "b", "group": "control", "outcome": "2"}]
    spec = {"outcome_column": "outcome", "group_column": "group",
            "pair_column": "pair", "groups": labels, "study_design": design,
            "seed": 1, "bootstrap_resamples": 1000, "permutations": 100}
    with pytest.raises(ValidationError, match="distinct non-blank|group label must be non-blank"):
        method(spec, rows)


@pytest.mark.parametrize("difference", [-3, 0, 3])
@pytest.mark.parametrize("design", ["paired", "independent_groups"])
def test_constant_effect_preserved_without_inventing_standardized_effect(design, difference):
    """Synthetic null, negative, and positive fixtures receive identical handling."""
    import json
    rows = [
        {"pair": pair, "group": group, "outcome": str(value)}
        for pair in ("a", "b", "c")
        for group, value in (("control", 10), ("treatment", 10 + difference))
    ]
    spec = {
        "outcome_column": "outcome", "group_column": "group",
        "groups": ["treatment", "control"], "pair_column": "pair",
        "study_design": design, "seed": 1, "bootstrap_resamples": 1000,
    }
    method = paired_mean_difference_ci if design == "paired" else independent_mean_difference_ci
    result = method(spec, rows)
    assert result["mean_difference_first_minus_second"] == difference
    assert result["standardized_effect_status"] == "undefined_zero_variance"
    assert result["warnings"]
    assert result["confidence_interval"]["lower"] == difference
    assert result["confidence_interval"]["upper"] == difference
    if design == "paired":
        assert result["standardized_mean_change"] is None
    else:
        assert result["pooled_within_group_standard_deviation"] == 0.0
        assert result["cohen_d"] is None
        assert result["hedges_g"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("column", ["pair", "group", "outcome"])
@pytest.mark.parametrize("missing", ["", "  ", None])
def test_paired_estimator_never_silently_excludes_rows(column, missing) -> None:
    # Synthetic fixture: two valid pairs plus a malformed observation.
    rows = [
        {"pair": "a", "group": "control", "outcome": "1"},
        {"pair": "a", "group": "treatment", "outcome": "3"},
        {"pair": "b", "group": "control", "outcome": "2"},
        {"pair": "b", "group": "treatment", "outcome": "5"},
    ]
    spec = {
        "outcome_column": "outcome", "group_column": "group",
        "groups": ["treatment", "control"], "pair_column": "pair",
        "study_design": "paired", "seed": 1, "bootstrap_resamples": 1000,
    }
    result = paired_mean_difference_ci(spec, rows)
    assert result["n_pairs"] == 2
    assert result["mean_difference_first_minus_second"] == 2.5
    assert result["missing_rows"] == 0
    malformed = {"pair": "c", "group": "control", "outcome": "100", column: missing}
    with pytest.raises(ValidationError, match="implicit row exclusions"):
        paired_mean_difference_ci(spec, [*rows, malformed])


def test_independent_estimator_requires_declared_independence() -> None:
    rows = [
        {"group": "control", "outcome": "1"},
        {"group": "control", "outcome": "2"},
        {"group": "treatment", "outcome": "4"},
        {"group": "treatment", "outcome": "5"},
    ]
    spec = {
        "outcome_column": "outcome",
        "group_column": "group",
        "groups": ["treatment", "control"],
        "study_design": "independent_groups",
        "seed": 1,
        "bootstrap_resamples": 1000,
    }
    result = independent_mean_difference_ci(spec, rows)
    assert result["mean_difference_first_minus_second"] == 3
    assert result["confidence_interval"]["level"] == 0.95
    assert result["independent_unit_check"]["status"] == "not_checked"
    with pytest.raises(ValidationError, match="study_design"):
        independent_mean_difference_ci({**spec, "study_design": "paired"}, rows)


@pytest.mark.parametrize("identifier", ["u0", " u0 ", "", None])
def test_independent_unit_check_rejects_repeated_or_missing_units(identifier):
    # Synthetic fixture; duplicate IDs are caught across groups too.
    rows = [{"unit": f"u{i}", "group": group, "outcome": str(i)}
            for i, group in enumerate(["a", "a", "b", "b"])]
    spec = {"outcome_column": "outcome", "group_column": "group",
            "groups": ["a", "b"], "study_design": "independent_groups",
            "unit_column": "unit", "seed": 1, "bootstrap_resamples": 1000}
    result = independent_mean_difference_ci(spec, rows)
    assert result["independent_unit_check"]["n_units"] == 4
    rows[-1]["unit"] = identifier
    with pytest.raises(ValidationError, match="independent-unit identifier"):
        independent_mean_difference_ci(spec, rows)


def test_paired_estimator_refuses_incomplete_pairs() -> None:
    rows = [
        {"pair": "a", "group": "control", "outcome": "1"},
        {"pair": "a", "group": "treatment", "outcome": "3"},
        {"pair": "b", "group": "control", "outcome": "2"},
    ]
    spec = {
        "outcome_column": "outcome",
        "group_column": "group",
        "groups": ["treatment", "control"],
        "pair_column": "pair",
        "study_design": "paired",
        "seed": 1,
        "bootstrap_resamples": 1000,
    }
    with pytest.raises(ValidationError, match="incomplete pairs"):
        paired_mean_difference_ci(spec, rows)
