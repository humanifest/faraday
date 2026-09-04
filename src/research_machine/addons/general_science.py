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
    ),
    capabilities=("csv-ingestion", "descriptive-statistics", "association", "randomization-inference"),
    protocol_kinds=("observational", "experimental"),
    dataset_media_types=("text/csv",),
    documentation="docs/addons.md",
)
