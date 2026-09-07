from __future__ import annotations

import math
import random
import statistics
from typing import Any

from research_machine.addons.models import AddonManifest, AnalysisMethod
from research_machine.domain.errors import ValidationError


def _column(rows: list[dict[str, str]], name: str) -> tuple[list[float], int]:
    values: list[float] = []
    missing = 0
    for index, row in enumerate(rows, start=2):
        raw = row.get(name)
        if raw is None:
            raise ValidationError(f"column not found: {name}")
        if raw.strip() == "":
            missing += 1
            continue
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValidationError(f"non-numeric value in {name} at CSV row {index}") from exc
        if not math.isfinite(value):
            raise ValidationError(f"non-finite value in {name} at CSV row {index}")
        values.append(value)
    return values, missing


def _summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "standard_deviation": None, "minimum": None, "maximum": None}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "standard_deviation": statistics.stdev(values) if len(values) > 1 else None,
        "minimum": min(values),
        "maximum": max(values),
    }


def descriptive_summary(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    columns = spec.get("columns")
    if not isinstance(columns, list) or not columns or any(not isinstance(item, str) or not item.strip() for item in columns):
        raise ValidationError("descriptive_summary requires a non-empty columns array")
    columns = [item.strip() for item in columns]
    if len(set(columns)) != len(columns):
        raise ValidationError("descriptive_summary columns must not contain duplicates")
    summaries: dict[str, Any] = {}
    missing: dict[str, int] = {}
    for name in columns:
        values, missing_count = _column(rows, name)
        summaries[name] = _summary(values)
        missing[name] = missing_count
    return {"summaries": summaries, "missing_by_column": missing}


def missingness_report(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    columns = spec.get("columns")
    if not isinstance(columns, list) or not columns or any(
        not isinstance(item, str) or not item.strip() for item in columns
    ):
        raise ValidationError("missingness_report requires a non-empty columns array")
    columns = [item.strip() for item in columns]
    if len(set(columns)) != len(columns):
        raise ValidationError("missingness_report columns must not contain duplicates")
    if not rows:
        raise ValidationError("missingness_report requires at least one observation")
    counts = {column: 0 for column in columns}
    patterns: dict[tuple[str, ...], int] = {}
    complete_rows = 0
    for index, row in enumerate(rows, start=2):
        missing = []
        for column in columns:
            value = row.get(column)
            if value is None:
                raise ValidationError(f"column not found: {column}")
            if not value.strip():
                counts[column] += 1
                missing.append(column)
        if not missing:
            complete_rows += 1
        else:
            key = tuple(missing)
            patterns[key] = patterns.get(key, 0) + 1
    return {
        "row_count": len(rows),
        "complete_case_row_count": complete_rows,
        "complete_case_fraction": complete_rows / len(rows),
        "missing_by_column": counts,
        "missingness_patterns": [{"missing_columns": list(key), "row_count": count}
                                 for key, count in sorted(patterns.items())],
        "limitation": "This describes observed missingness; it does not establish a missing-data mechanism or justify complete-case analysis.",
    }


def pearson_correlation(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    x_name = spec.get("x_column")
    y_name = spec.get("y_column")
    if not isinstance(x_name, str) or not isinstance(y_name, str):
        raise ValidationError("pearson_correlation requires x_column and y_column")
    pairs: list[tuple[float, float]] = []
    missing = 0
    for index, row in enumerate(rows, start=2):
        x_raw, y_raw = row.get(x_name), row.get(y_name)
        if x_raw is None or y_raw is None:
            raise ValidationError("correlation column not found")
        if not x_raw.strip() or not y_raw.strip():
            missing += 1
            continue
        try:
            x, y = float(x_raw), float(y_raw)
        except ValueError as exc:
            raise ValidationError(f"non-numeric correlation value at CSV row {index}") from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValidationError(f"non-finite correlation value at CSV row {index}")
        pairs.append((x, y))
    if len(pairs) < 3:
        raise ValidationError("pearson_correlation requires at least three complete pairs")
    xs, ys = zip(*pairs)
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    if denominator == 0:
        raise ValidationError("pearson_correlation is undefined for a constant column")
    return {"n": len(pairs), "pearson_r": numerator / denominator, "missing_pairs": missing}


def _validate_group_labels(labels: Any) -> None:
    if (
        not isinstance(labels, list) or len(labels) != 2
        or any(not isinstance(item, str) or not item.strip() for item in labels)
        or labels[0] == labels[1]
    ):
        raise ValidationError("groups must contain exactly two distinct non-blank string labels")


def _comparison_exclusions(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    """Describe validated complete-case omissions without exposing unit IDs."""
    excluded = []
    by_group = {label: 0 for label in spec["groups"]}
    unassigned = 0
    for record, row in enumerate(rows, start=1):
        missing_fields = [field for field in (spec["outcome_column"], spec["group_column"])
                          if not row[field].strip()]
        if not missing_fields:
            continue
        group = row[spec["group_column"]]
        if group in by_group:
            by_group[group] += 1
        else:
            unassigned += 1
        excluded.append({"data_record": record, "missing_columns": missing_fields})
    return {"policy": spec.get("missing_data_policy", "no_missing_observations"),
            "input_records": len(rows), "included_records": len(rows) - len(excluded),
            "excluded_records": excluded, "excluded_by_group": by_group,
            "excluded_without_registered_group": unassigned,
            "record_numbering": "One-based parsed data records, excluding the header; not physical file lines.",
            "limitation": "These counts do not establish a missing-data mechanism or absence of selection bias."}


def permutation_mean_difference(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    outcome = spec.get("outcome_column")
    group = spec.get("group_column")
    labels = spec.get("groups")
    permutations = spec.get("permutations", 10000)
    seed = spec.get("seed")
    if not isinstance(outcome, str) or not isinstance(group, str):
        raise ValidationError("permutation_mean_difference requires outcome_column and group_column")
    _validate_group_labels(labels)
    if not isinstance(permutations, int) or isinstance(permutations, bool) or not 100 <= permutations <= 1_000_000:
        raise ValidationError("permutations must be an integer from 100 to 1000000")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValidationError("a committed integer seed is required")
    unit_check = {"status": "not_checked", "notice": "No independent-unit column supplied; exchangeability is a declaration only."}
    if "unit_column" in spec:
        unit_column = spec.get("unit_column")
        if not isinstance(unit_column, str) or not unit_column.strip():
            raise ValidationError("permutation_mean_difference unit_column must be non-blank")
        units: set[str] = set()
        for index, row in enumerate(rows, start=2):
            unit = row.get(unit_column)
            if not isinstance(unit, str) or not unit.strip():
                raise ValidationError(f"missing independent-unit identifier at CSV row {index}")
            unit = unit.strip()
            if unit in units:
                raise ValidationError(
                    f"repeated independent-unit identifier at CSV row {index}; use a dependence-aware randomization procedure"
                )
            units.add(unit)
        unit_check = {
            "status": "unique_identifiers", "column": unit_column,
            "n_units": len(units),
            "notice": "Unique identifiers do not prove exchangeability or sampling independence.",
        }
    first: list[float] = []
    second: list[float] = []
    missing = 0
    for index, row in enumerate(rows, start=2):
        raw, label = row.get(outcome), row.get(group)
        if raw is None or label is None:
            raise ValidationError("permutation-test column not found")
        if label.strip() and label not in labels:
            raise ValidationError(f"unexpected group {label!r} at CSV row {index}")
        if not raw.strip() or not label.strip():
            if spec.get("missing_data_policy") != "complete_case":
                raise ValidationError("missing observations require an explicit complete_case missing_data_policy")
            missing += 1
            continue
        if label not in labels:
            raise ValidationError(f"unexpected group {label!r} at CSV row {index}")
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValidationError(f"non-numeric outcome at CSV row {index}") from exc
        if not math.isfinite(value):
            raise ValidationError(f"non-finite outcome at CSV row {index}")
        (first if label == labels[0] else second).append(value)
    if len(first) < 2 or len(second) < 2:
        raise ValidationError("each group requires at least two complete observations")
    observed = statistics.fmean(first) - statistics.fmean(second)
    pooled = first + second
    size = len(first)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(permutations):
        shuffled = pooled.copy()
        rng.shuffle(shuffled)
        difference = statistics.fmean(shuffled[:size]) - statistics.fmean(shuffled[size:])
        if abs(difference) >= abs(observed):
            extreme += 1
    return {
        "groups": labels,
        "n_by_group": {labels[0]: len(first), labels[1]: len(second)},
        "mean_by_group": {labels[0]: statistics.fmean(first), labels[1]: statistics.fmean(second)},
        "mean_difference_first_minus_second": observed,
        "two_sided_permutation_p": (extreme + 1) / (permutations + 1),
        "independent_unit_check": unit_check,
        "exclusion_report": _comparison_exclusions(spec, rows),
        "permutations": permutations,
        "seed": seed,
        "missing_rows": missing,
    }


def _bootstrap_settings(spec: dict[str, Any], method: str) -> tuple[int, int, float]:
    resamples = spec.get("bootstrap_resamples", 10_000)
    seed = spec.get("seed")
    confidence = spec.get("confidence_level", 0.95)
    if not isinstance(resamples, int) or isinstance(resamples, bool) or not 1_000 <= resamples <= 1_000_000:
        raise ValidationError(f"{method} bootstrap_resamples must be an integer from 1000 to 1000000")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValidationError(f"{method} requires a committed integer seed")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0.8 <= confidence < 1:
        raise ValidationError(f"{method} confidence_level must be in [0.8, 1)")
    return resamples, seed, float(confidence)


def _percentile_interval(values: list[float], confidence: float) -> dict[str, float]:
    ordered = sorted(values)
    alpha = (1 - confidence) / 2
    lower_index = max(0, math.floor(alpha * (len(ordered) - 1)))
    upper_index = min(len(ordered) - 1, math.ceil((1 - alpha) * (len(ordered) - 1)))
    return {"lower": ordered[lower_index], "upper": ordered[upper_index]}


def _two_groups(
    spec: dict[str, Any],
    rows: list[dict[str, str]],
    method: str,
    *,
    require_two_per_group: bool = True,
) -> tuple[list[float], list[float], list[str], int]:
    outcome, group, labels = spec.get("outcome_column"), spec.get("group_column"), spec.get("groups")
    if not isinstance(outcome, str) or not isinstance(group, str):
        raise ValidationError(f"{method} requires outcome_column and group_column")
    _validate_group_labels(labels)
    first: list[float] = []
    second: list[float] = []
    missing = 0
    for index, row in enumerate(rows, start=2):
        raw, label = row.get(outcome), row.get(group)
        if raw is None or label is None:
            raise ValidationError(f"{method} column not found")
        if label.strip() and label not in labels:
            raise ValidationError(f"unexpected group {label!r} at CSV row {index}")
        if not raw.strip() or not label.strip():
            if spec.get("missing_data_policy") != "complete_case":
                raise ValidationError("missing observations require an explicit complete_case missing_data_policy")
            missing += 1
            continue
        if label not in labels:
            raise ValidationError(f"unexpected group {label!r} at CSV row {index}")
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValidationError(f"non-numeric outcome at CSV row {index}") from exc
        if not math.isfinite(value):
            raise ValidationError(f"non-finite outcome at CSV row {index}")
        (first if label == labels[0] else second).append(value)
    if require_two_per_group and (len(first) < 2 or len(second) < 2):
        raise ValidationError("each group requires at least two complete observations")
    return first, second, labels, missing


def independent_mean_difference_ci(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    """Bootstrap estimation for a declared independent-groups comparison."""
    if spec.get("study_design") != "independent_groups":
        raise ValidationError("independent_mean_difference_ci requires study_design independent_groups")
    first, second, labels, missing = _two_groups(spec, rows, "independent_mean_difference_ci")
    unit_column = spec.get("unit_column")
    unit_check = {"status": "not_checked", "notice": "No independent-unit column supplied; independence is a declaration only."}
    if "unit_column" in spec:
        if not isinstance(unit_column, str) or not unit_column.strip():
            raise ValidationError("unit_column must be a non-blank column name")
        units: set[str] = set()
        for index, row in enumerate(rows, start=2):
            unit = row.get(unit_column)
            if not isinstance(unit, str) or not unit.strip():
                raise ValidationError(f"missing independent-unit identifier at CSV row {index}")
            unit = unit.strip()
            if unit in units:
                raise ValidationError(f"repeated independent-unit identifier at CSV row {index}; use a dependence-aware design")
            units.add(unit)
        unit_check = {"status": "unique_identifiers", "column": unit_column,
                      "n_units": len(units), "notice": "Unique identifiers do not prove sampling independence or rule out shared clusters."}
    resamples, seed, confidence = _bootstrap_settings(spec, "independent_mean_difference_ci")
    mean_first, mean_second = statistics.fmean(first), statistics.fmean(second)
    difference = mean_first - mean_second
    pooled_variance = ((len(first) - 1) * statistics.variance(first) + (len(second) - 1) * statistics.variance(second)) / (len(first) + len(second) - 2)
    pooled_standard_deviation = math.sqrt(pooled_variance)
    cohen_d = difference / pooled_standard_deviation if pooled_standard_deviation else None
    correction = 1 - 3 / (4 * (len(first) + len(second)) - 9)
    rng = random.Random(seed)
    draws = [
        statistics.fmean(rng.choice(first) for _ in first) - statistics.fmean(rng.choice(second) for _ in second)
        for _ in range(resamples)
    ]
    return {
        "study_design": "independent_groups",
        "groups": labels,
        "n_by_group": {labels[0]: len(first), labels[1]: len(second)},
        "independent_unit_check": unit_check,
        "exclusion_report": _comparison_exclusions(spec, rows),
        "mean_by_group": {labels[0]: mean_first, labels[1]: mean_second},
        "mean_difference_first_minus_second": difference,
        "pooled_within_group_standard_deviation": pooled_standard_deviation,
        "confidence_interval": {"level": confidence, **_percentile_interval(draws, confidence)},
        "cohen_d": cohen_d,
        "hedges_g": correction * cohen_d if cohen_d is not None else None,
        "standardized_effect_status": "defined" if cohen_d is not None else "undefined_zero_variance",
        "warnings": (["Observed within-group variance is zero. The bootstrap interval is degenerate and does not establish zero population uncertainty."] if pooled_variance == 0 else []),
        "bootstrap_resamples": resamples,
        "seed": seed,
        "missing_rows": missing,
        "assumptions": ["Observations are independent within and between groups.", "The registered outcome is numeric and measured on a comparable scale."],
    }


def _invert_matrix(matrix: list[list[float]]) -> list[list[float]]:
    """Invert a small symmetric design matrix with scaled pivot checks."""
    size = len(matrix)
    augmented = [
        [*row, *(1.0 if column == index else 0.0 for column in range(size))]
        for index, row in enumerate(matrix)
    ]
    scale = max((abs(value) for row in matrix for value in row), default=0.0)
    tolerance = max(1.0, scale) * 1e-12
    for column in range(size):
        pivot_row = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot_row][column]) <= tolerance:
            raise ValidationError(
                "adjusted_linear_effect design matrix is singular or numerically rank deficient"
            )
        augmented[column], augmented[pivot_row] = augmented[pivot_row], augmented[column]
        pivot = augmented[column][column]
        augmented[column] = [value / pivot for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            multiplier = augmented[row][column]
            augmented[row] = [
                value - multiplier * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [row[size:] for row in augmented]


def _matrix_vector(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(value * item for value, item in zip(row, vector)) for row in matrix]


def adjusted_linear_effect(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    """Estimate a prespecified adjusted two-group contrast using OLS with HC1 uncertainty."""
    method = "adjusted_linear_effect"
    if spec.get("study_design") != "independent_groups":
        raise ValidationError(f"{method} requires study_design independent_groups")
    outcome, group, labels = (
        spec.get("outcome_column"), spec.get("group_column"), spec.get("groups")
    )
    if not isinstance(outcome, str) or not outcome.strip() or not isinstance(group, str) or not group.strip():
        raise ValidationError(f"{method} requires outcome_column and group_column")
    _validate_group_labels(labels)
    covariates = spec.get("covariate_columns")
    if (
        not isinstance(covariates, list)
        or not covariates
        or any(not isinstance(item, str) or not item.strip() for item in covariates)
        or len(set(covariates)) != len(covariates)
    ):
        raise ValidationError(f"{method} requires distinct non-blank covariate_columns")
    if outcome in covariates or group in covariates:
        raise ValidationError("covariate_columns cannot include the outcome or group column")
    confidence = spec.get("confidence_level", 0.95)
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0.8 <= float(confidence) < 1
    ):
        raise ValidationError(f"{method} confidence_level must be in [0.8, 1)")
    unit_column = spec.get("unit_column")
    if not isinstance(unit_column, str) or not unit_column.strip():
        raise ValidationError(f"{method} requires a non-blank unit_column")
    if unit_column in {outcome, group, *covariates}:
        raise ValidationError("unit_column must be distinct from modeled columns")

    required = [outcome, group, *covariates]
    parsed: list[tuple[float, int, list[float]]] = []
    excluded: list[dict[str, Any]] = []
    excluded_by_group = {label: 0 for label in labels}
    excluded_without_group = 0
    units: set[str] = set()
    for record, row in enumerate(rows, start=1):
        csv_row = record + 1
        unit = row.get(unit_column)
        if not isinstance(unit, str) or not unit.strip():
            raise ValidationError(f"missing independent-unit identifier at CSV row {csv_row}")
        unit = unit.strip()
        if unit in units:
            raise ValidationError(
                f"repeated independent-unit identifier at CSV row {csv_row}; use a dependence-aware design"
            )
        units.add(unit)
        label = row.get(group)
        if label is None:
            raise ValidationError(f"column not found: {group}")
        if label.strip() and label not in labels:
            raise ValidationError(f"unexpected group {label!r} at CSV row {csv_row}")
        missing_fields: list[str] = []
        for column in required:
            raw = row.get(column)
            if raw is None:
                raise ValidationError(f"column not found: {column}")
            if not raw.strip():
                missing_fields.append(column)
        if missing_fields:
            if spec.get("missing_data_policy") != "complete_case":
                raise ValidationError(
                    "missing observations require an explicit complete_case missing_data_policy"
                )
            excluded.append({"data_record": record, "missing_columns": missing_fields})
            if label in excluded_by_group:
                excluded_by_group[label] += 1
            else:
                excluded_without_group += 1
            continue
        numeric: list[float] = []
        for column in [outcome, *covariates]:
            try:
                value = float(row[column])
            except ValueError as exc:
                raise ValidationError(f"non-numeric value in {column} at CSV row {csv_row}") from exc
            if not math.isfinite(value):
                raise ValidationError(f"non-finite value in {column} at CSV row {csv_row}")
            numeric.append(value)
        parsed.append((numeric[0], int(label == labels[0]), numeric[1:]))

    group_counts = {
        labels[0]: sum(treatment for _, treatment, _ in parsed),
        labels[1]: sum(1 - treatment for _, treatment, _ in parsed),
    }
    if min(group_counts.values()) < 2:
        raise ValidationError("each group requires at least two complete observations")
    parameter_count = 2 + len(covariates)
    if len(parsed) <= parameter_count:
        raise ValidationError(
            "adjusted_linear_effect requires more complete independent units than fitted parameters"
        )
    means = [statistics.fmean(values[index] for _, _, values in parsed)
             for index in range(len(covariates))]
    scales = [math.sqrt(statistics.fmean(
        (values[index] - means[index]) ** 2 for _, _, values in parsed
    )) for index in range(len(covariates))]
    constant = [name for name, scale in zip(covariates, scales) if scale <= 1e-15]
    if constant:
        raise ValidationError("constant adjustment covariates: " + ", ".join(constant))
    design = [
        [1.0, float(treatment), *[
            (value - mean) / scale
            for value, mean, scale in zip(values, means, scales)
        ]]
        for _, treatment, values in parsed
    ]
    outcomes = [value for value, _, _ in parsed]
    xtx = [[sum(row[i] * row[j] for row in design) for j in range(parameter_count)]
           for i in range(parameter_count)]
    bread = _invert_matrix(xtx)
    xty = [sum(row[index] * value for row, value in zip(design, outcomes))
           for index in range(parameter_count)]
    coefficients = _matrix_vector(bread, xty)
    residuals = [
        observed - sum(coefficient * value for coefficient, value in zip(coefficients, row))
        for row, observed in zip(design, outcomes)
    ]
    meat = [[sum(
        residual ** 2 * row[i] * row[j]
        for row, residual in zip(design, residuals)
    ) for j in range(parameter_count)] for i in range(parameter_count)]
    bread_meat = [[sum(bread[i][k] * meat[k][j] for k in range(parameter_count))
                   for j in range(parameter_count)] for i in range(parameter_count)]
    covariance = [[
        len(parsed) / (len(parsed) - parameter_count)
        * sum(bread_meat[i][k] * bread[j][k] for k in range(parameter_count))
        for j in range(parameter_count)
    ] for i in range(parameter_count)]
    variance = covariance[1][1]
    if variance < -1e-12 or not math.isfinite(variance):
        raise ValidationError("adjusted_linear_effect produced invalid robust uncertainty")
    standard_error = math.sqrt(max(0.0, variance))
    z_value = statistics.NormalDist().inv_cdf(0.5 + float(confidence) / 2)
    effect = coefficients[1]
    fitted_mean = statistics.fmean(outcomes)
    total_sum_squares = sum((value - fitted_mean) ** 2 for value in outcomes)
    residual_sum_squares = sum(value ** 2 for value in residuals)
    leverage = [sum(row[i] * bread[i][j] * row[j]
                    for i in range(parameter_count) for j in range(parameter_count))
                for row in design]
    names = ["intercept", f"{group}:{labels[0]}_vs_{labels[1]}", *covariates]
    return {
        "study_design": "independent_groups",
        "groups": labels,
        "n_by_group": group_counts,
        "n_complete": len(parsed),
        "parameter_count": parameter_count,
        "residual_degrees_of_freedom": len(parsed) - parameter_count,
        "adjustment_columns": covariates,
        "adjusted_mean_difference_first_minus_second": effect,
        "robust_standard_error_hc1": standard_error,
        "robust_confidence_interval": {
            "level": float(confidence),
            "lower": effect - z_value * standard_error,
            "upper": effect + z_value * standard_error,
            "reference_distribution": "normal",
            "variance_estimator": "HC1 heteroskedasticity-consistent sandwich",
        },
        "coefficients": [
            {"term": name, "estimate": estimate}
            for name, estimate in zip(names, coefficients)
        ],
        "diagnostics": {
            "r_squared": (1 - residual_sum_squares / total_sum_squares)
            if total_sum_squares else None,
            "residual_sum_squares": residual_sum_squares,
            "maximum_leverage": max(leverage),
        },
        "independent_unit_check": {
            "status": "unique_identifiers", "column": unit_column,
            "n_units": len(units),
            "notice": "Unique identifiers do not prove sampling independence or rule out shared clusters.",
        },
        "exclusion_report": {
            "policy": spec.get("missing_data_policy", "no_missing_observations"),
            "input_records": len(rows), "included_records": len(parsed),
            "excluded_records": excluded, "excluded_by_group": excluded_by_group,
            "excluded_without_registered_group": excluded_without_group,
            "record_numbering": "One-based parsed data records, excluding the header; not physical file lines.",
            "limitation": "These counts do not establish a missing-data mechanism or absence of selection bias.",
        },
        "assumptions": [
            "The frozen DAG and adjustment set are substantively correct; this calculation does not verify them.",
            "The conditional outcome model is linear and correctly specified for the registered estimand.",
            "Independent units, positivity, consistency, temporality, and measurement validity remain protocol assumptions.",
            "HC1 uncertainty is an asymptotic approximation and may be unreliable in small samples or under high leverage.",
        ],
    }


def paired_mean_difference_ci(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    """Bootstrap estimation that refuses to treat paired observations as independent."""
    if spec.get("study_design") != "paired":
        raise ValidationError("paired_mean_difference_ci requires study_design paired")
    pair_column = spec.get("pair_column")
    if not isinstance(pair_column, str) or not pair_column.strip():
        raise ValidationError("paired_mean_difference_ci requires pair_column")
    for field in ("outcome_column", "group_column"):
        if not isinstance(spec.get(field), str) or not spec[field].strip():
            raise ValidationError(f"paired_mean_difference_ci requires {field}")
    # Validate every submitted row before numeric parsing can discard missing
    # observations. This method has no registered exclusion policy.
    for index, row in enumerate(rows, start=2):
        for column in (pair_column, spec.get("outcome_column"), spec.get("group_column")):
            value = row.get(column)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(
                    f"paired analysis requires non-missing {column!r} at CSV row {index}; "
                    "implicit row exclusions are not supported"
                )
    first, second, labels, missing = _two_groups(
        spec,
        rows,
        "paired_mean_difference_ci",
        require_two_per_group=False,
    )
    del first, second
    outcome, group = spec["outcome_column"], spec["group_column"]
    pairs: dict[str, dict[str, float]] = {}
    for index, row in enumerate(rows, start=2):
        raw, label, pair_id = row.get(outcome), row.get(group), row.get(pair_column)
        if raw is None or label is None or pair_id is None:
            raise ValidationError("paired_mean_difference_ci column not found")
        value = float(raw)
        if pair_id in pairs and label in pairs[pair_id]:
            raise ValidationError(f"duplicate observation for pair {pair_id!r} and group {label!r} at CSV row {index}")
        pairs.setdefault(pair_id, {})[label] = value
    incomplete = [pair_id for pair_id, values in pairs.items() if set(values) != set(labels)]
    if incomplete:
        raise ValidationError("paired analysis requires exactly one complete observation per group for every pair; incomplete pairs: " + ", ".join(sorted(incomplete)))
    differences = [values[labels[0]] - values[labels[1]] for values in pairs.values()]
    if len(differences) < 2:
        raise ValidationError("paired analysis requires at least two complete pairs")
    resamples, seed, confidence = _bootstrap_settings(spec, "paired_mean_difference_ci")
    rng = random.Random(seed)
    draws = [statistics.fmean(rng.choice(differences) for _ in differences) for _ in range(resamples)]
    sd = statistics.stdev(differences)
    return {
        "study_design": "paired",
        "groups": labels,
        "n_pairs": len(differences),
        "mean_difference_first_minus_second": statistics.fmean(differences),
        "confidence_interval": {"level": confidence, **_percentile_interval(draws, confidence)},
        "standardized_mean_change": statistics.fmean(differences) / sd if sd else None,
        "standardized_effect_status": "defined" if sd else "undefined_zero_variance",
        "warnings": (["Observed pair differences have zero variance. The bootstrap interval is degenerate and does not establish zero population uncertainty."] if sd == 0 else []),
        "bootstrap_resamples": resamples,
        "seed": seed,
        "missing_rows": missing,
        "assumptions": ["Pair identifiers correctly link repeated observations.", "Pairs are independent of other pairs."],
    }


def holm_adjustment(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    """Adjust one explicitly declared family without choosing that family."""
    hypothesis_column = spec.get("hypothesis_column")
    p_value_column = spec.get("p_value_column")
    family_name = spec.get("family_name")
    if any(not isinstance(value, str) or not value.strip()
           for value in (hypothesis_column, p_value_column, family_name)):
        raise ValidationError("holm_adjustment requires non-blank hypothesis_column, p_value_column, and family_name")
    family_hypothesis_ids = spec.get("family_hypothesis_ids")
    if (
        not isinstance(family_hypothesis_ids, list)
        or not family_hypothesis_ids
        or any(
            not isinstance(identifier, str)
            or not identifier.strip()
            or identifier != identifier.strip()
            for identifier in family_hypothesis_ids
        )
        or len(set(family_hypothesis_ids)) != len(family_hypothesis_ids)
    ):
        raise ValidationError(
            "holm_adjustment family_hypothesis_ids must be a non-empty list of "
            "unique, canonical non-blank identifiers"
        )
    alpha = spec.get("alpha")
    if (not isinstance(alpha, (int, float)) or isinstance(alpha, bool)
            or not math.isfinite(float(alpha)) or not 0 < float(alpha) < 1):
        raise ValidationError("holm_adjustment alpha must be a finite number strictly between zero and one")
    observed: list[tuple[int, str, float]] = []
    identifiers: set[str] = set()
    for index, row in enumerate(rows, start=2):
        raw_id, raw_p = row.get(hypothesis_column), row.get(p_value_column)
        if raw_id is None or raw_p is None:
            raise ValidationError("holm_adjustment column not found")
        if not raw_id.strip() or not raw_p.strip():
            raise ValidationError(f"holm_adjustment does not allow missing identifiers or p-values at CSV row {index}")
        identifier = raw_id.strip()
        if identifier in identifiers:
            raise ValidationError(f"duplicate hypothesis identifier {identifier!r} at CSV row {index}")
        identifiers.add(identifier)
        try:
            p_value = float(raw_p)
        except ValueError as exc:
            raise ValidationError(f"non-numeric p-value at CSV row {index}") from exc
        if not math.isfinite(p_value) or not 0 <= p_value <= 1:
            raise ValidationError(f"p-value must be finite and within [0, 1] at CSV row {index}")
        observed.append((len(observed), identifier, p_value))
    if identifiers != set(family_hypothesis_ids):
        missing = sorted(set(family_hypothesis_ids) - identifiers)
        extra = sorted(identifiers - set(family_hypothesis_ids))
        raise ValidationError(
            "holm_adjustment input must exactly match the prespecified family; "
            f"missing={missing}; extra={extra}"
        )
    ordered = sorted(observed, key=lambda item: (item[2], item[1]))
    adjusted_by_index: dict[int, float] = {}
    running = 0.0
    family_size = len(ordered)
    for rank, (original_index, _, p_value) in enumerate(ordered, start=1):
        running = max(running, min(1.0, (family_size - rank + 1) * p_value))
        adjusted_by_index[original_index] = running
    results = [{"hypothesis_id": identifier, "raw_p_value": p_value,
                "holm_adjusted_p_value": adjusted_by_index[index],
                "reject_at_alpha": adjusted_by_index[index] <= float(alpha)}
               for index, identifier, p_value in observed]
    return {
        "method": "holm_step_down", "family_name": family_name.strip(),
        "family_hypothesis_ids": list(family_hypothesis_ids),
        "family_size": family_size, "alpha": float(alpha), "results": results,
        "rejected_hypothesis_ids": [item["hypothesis_id"] for item in results if item["reject_at_alpha"]],
        "assumptions": [
            "All hypotheses in the intended confirmatory family are present exactly once.",
            "Raw p-values are valid for their underlying tests; this adjustment does not repair invalid models, dependence assumptions, outcome switching, or selective reporting.",
            "The family definition and alpha were fixed before inspecting results; this calculation does not establish that chronology.",
        ],
    }


MANIFEST = AddonManifest(
    addon_id="general_science",
    name="General Science Toolkit",
    version="8.0.0",
    discipline="cross-disciplinary",
    description="Deterministic, dependency-free analyses usable across empirical disciplines.",
    methods=(
        AnalysisMethod("descriptive_summary", "Descriptive summary", "Summarize preregistered numeric columns without inferential promotion.", ("columns",), descriptive_summary, "Descriptive summaries of specified columns in the hashed dataset only.", "descriptive"),
        AnalysisMethod("missingness_report", "Missingness report", "Describe complete-case loss and observed missingness patterns without assuming a missing-data mechanism.", ("columns",), missingness_report, "Observed missingness counts and patterns in specified columns of the hashed dataset only.", "descriptive"),
        AnalysisMethod("pearson_correlation", "Pearson correlation", "Measure linear association for complete numeric pairs.", ("x_column", "y_column"), pearson_correlation, "Linear association between the two specified variables in complete pairs of the hashed dataset; no causal direction.", "association"),
        AnalysisMethod("permutation_mean_difference", "Permutation mean difference", "Compare two labeled groups with a deterministic two-sided randomization test.", ("outcome_column", "group_column", "groups", "seed"), permutation_mean_difference, "Observed group mean difference and randomization-test compatibility under the stated exchangeability procedure. Causal interpretation additionally requires a validated causal protocol and does not follow from this calculation alone.", "design_conditional_effect"),
        AnalysisMethod("independent_mean_difference_ci", "Independent-groups mean difference with confidence interval", "Estimate a registered two-group effect only when observations are declared independent.", ("outcome_column", "group_column", "groups", "study_design", "seed"), independent_mean_difference_ci, "Estimated mean difference for the specified independent groups in the hashed dataset under stated bootstrap assumptions. Causal interpretation additionally requires a validated causal protocol and does not follow from this calculation alone.", "design_conditional_effect"),
        AnalysisMethod("adjusted_linear_effect", "Covariate-adjusted linear effect with robust confidence interval", "Estimate a prespecified two-group contrast conditional on the exact frozen adjustment columns.", ("outcome_column", "group_column", "groups", "covariate_columns", "unit_column", "study_design"), adjusted_linear_effect, "Adjusted mean contrast for the specified independent groups in the hashed dataset, conditional on the frozen DAG, adjustment set, linear outcome model, positivity, independent units, and HC1 asymptotics. The calculation does not verify causal assumptions or establish causal truth.", "design_conditional_effect"),
        AnalysisMethod("paired_mean_difference_ci", "Paired mean difference with confidence interval", "Estimate a repeated-measure effect only when complete pair structure is explicit.", ("outcome_column", "group_column", "groups", "pair_column", "study_design", "seed"), paired_mean_difference_ci, "Estimated mean within-pair difference in the hashed dataset under stated pairing and bootstrap assumptions. Causal interpretation additionally requires a validated causal protocol and does not follow from this calculation alone.", "design_conditional_effect"),
        AnalysisMethod("holm_adjustment", "Holm family-wise error adjustment", "Adjust an exact prespecified hypothesis family without selecting or validating its members.", ("hypothesis_column", "p_value_column", "family_name", "family_hypothesis_ids", "alpha"), holm_adjustment, "Holm-adjusted values for the exact supplied named family, conditional on valid raw p-values and a prespecified complete family; no validation of underlying tests or family selection.", "descriptive"),
    ),
    capabilities=("csv-ingestion", "descriptive-statistics", "association", "randomization-inference", "effect-estimation", "covariate-adjusted-linear-models", "robust-confidence-intervals", "bootstrap-confidence-intervals", "paired-design-safeguards", "multiple-testing-adjustment"),
    protocol_kinds=("observational", "experimental"),
    dataset_media_types=("text/csv",),
    documentation="docs/addons.md",
)
