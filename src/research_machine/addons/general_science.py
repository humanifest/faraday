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
    if not isinstance(columns, list) or not columns or any(not isinstance(item, str) or not item for item in columns):
        raise ValidationError("descriptive_summary requires a non-empty columns array")
    summaries: dict[str, Any] = {}
    missing: dict[str, int] = {}
    for name in columns:
        values, missing_count = _column(rows, name)
        summaries[name] = _summary(values)
        missing[name] = missing_count
    return {"summaries": summaries, "missing_by_column": missing}


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


def permutation_mean_difference(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    outcome = spec.get("outcome_column")
    group = spec.get("group_column")
    labels = spec.get("groups")
    permutations = spec.get("permutations", 10000)
    seed = spec.get("seed")
    if not isinstance(outcome, str) or not isinstance(group, str):
        raise ValidationError("permutation_mean_difference requires outcome_column and group_column")
    if not isinstance(labels, list) or len(labels) != 2 or any(not isinstance(item, str) for item in labels):
        raise ValidationError("groups must contain exactly two string labels")
    if not isinstance(permutations, int) or isinstance(permutations, bool) or not 100 <= permutations <= 1_000_000:
        raise ValidationError("permutations must be an integer from 100 to 1000000")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValidationError("a committed integer seed is required")
    first: list[float] = []
    second: list[float] = []
    missing = 0
    for index, row in enumerate(rows, start=2):
        raw, label = row.get(outcome), row.get(group)
        if raw is None or label is None:
            raise ValidationError("permutation-test column not found")
        if not raw.strip() or not label.strip():
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
    if not isinstance(labels, list) or len(labels) != 2 or any(not isinstance(item, str) or not item for item in labels):
        raise ValidationError("groups must contain exactly two non-empty string labels")
    first: list[float] = []
    second: list[float] = []
    missing = 0
    for index, row in enumerate(rows, start=2):
        raw, label = row.get(outcome), row.get(group)
        if raw is None or label is None:
            raise ValidationError(f"{method} column not found")
        if not raw.strip() or not label.strip():
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
    resamples, seed, confidence = _bootstrap_settings(spec, "independent_mean_difference_ci")
    mean_first, mean_second = statistics.fmean(first), statistics.fmean(second)
    difference = mean_first - mean_second
    pooled_variance = ((len(first) - 1) * statistics.variance(first) + (len(second) - 1) * statistics.variance(second)) / (len(first) + len(second) - 2)
    if pooled_variance == 0:
        raise ValidationError("standardized effect is undefined when both groups have zero variance")
    cohen_d = difference / math.sqrt(pooled_variance)
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
        "mean_by_group": {labels[0]: mean_first, labels[1]: mean_second},
        "mean_difference_first_minus_second": difference,
        "confidence_interval": {"level": confidence, **_percentile_interval(draws, confidence)},
        "cohen_d": cohen_d,
        "hedges_g": correction * cohen_d,
        "bootstrap_resamples": resamples,
        "seed": seed,
        "missing_rows": missing,
        "assumptions": ["Observations are independent within and between groups.", "The registered outcome is numeric and measured on a comparable scale."],
    }


def paired_mean_difference_ci(spec: dict[str, Any], rows: list[dict[str, str]]) -> dict[str, Any]:
    """Bootstrap estimation that refuses to treat paired observations as independent."""
    if spec.get("study_design") != "paired":
        raise ValidationError("paired_mean_difference_ci requires study_design paired")
    pair_column = spec.get("pair_column")
    if not isinstance(pair_column, str) or not pair_column.strip():
        raise ValidationError("paired_mean_difference_ci requires pair_column")
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
        if not raw.strip() or not label.strip() or not pair_id.strip():
            continue
        if label not in labels:
            continue
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
    if sd == 0:
        raise ValidationError("standardized paired effect is undefined when pair differences have zero variance")
    return {
        "study_design": "paired",
        "groups": labels,
        "n_pairs": len(differences),
        "mean_difference_first_minus_second": statistics.fmean(differences),
        "confidence_interval": {"level": confidence, **_percentile_interval(draws, confidence)},
        "standardized_mean_change": statistics.fmean(differences) / sd,
        "bootstrap_resamples": resamples,
        "seed": seed,
        "missing_rows": missing,
        "assumptions": ["Pair identifiers correctly link repeated observations.", "Pairs are independent of other pairs."],
    }


MANIFEST = AddonManifest(
    addon_id="general_science",
    name="General Science Toolkit",
    version="1.0.0",
    discipline="cross-disciplinary",
    description="Deterministic, dependency-free analyses usable across empirical disciplines.",
    methods=(
        AnalysisMethod("descriptive_summary", "Descriptive summary", "Summarize preregistered numeric columns without inferential promotion.", ("columns",), descriptive_summary),
        AnalysisMethod("pearson_correlation", "Pearson correlation", "Measure linear association for complete numeric pairs.", ("x_column", "y_column"), pearson_correlation),
        AnalysisMethod("permutation_mean_difference", "Permutation mean difference", "Compare two labeled groups with a deterministic two-sided randomization test.", ("outcome_column", "group_column", "groups", "seed"), permutation_mean_difference),
        AnalysisMethod("independent_mean_difference_ci", "Independent-groups mean difference with confidence interval", "Estimate a registered two-group effect only when observations are declared independent.", ("outcome_column", "group_column", "groups", "study_design", "seed"), independent_mean_difference_ci),
        AnalysisMethod("paired_mean_difference_ci", "Paired mean difference with confidence interval", "Estimate a repeated-measure effect only when complete pair structure is explicit.", ("outcome_column", "group_column", "groups", "pair_column", "study_design", "seed"), paired_mean_difference_ci),
    ),
    capabilities=("csv-ingestion", "descriptive-statistics", "association", "randomization-inference", "effect-estimation", "bootstrap-confidence-intervals", "paired-design-safeguards"),
    protocol_kinds=("observational", "experimental"),
    dataset_media_types=("text/csv",),
    documentation="docs/addons.md",
)
