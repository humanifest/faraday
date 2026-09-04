"""Independent log-log analysis for the physical pendulum campaign."""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path
from typing import Any


def classify_from_files(
    observations_path: Path,
    clock_calibration_path: Path,
    allowed_exclusion_flags: set[str],
) -> dict[str, Any]:
    with clock_calibration_path.open(encoding="utf-8", newline="") as handle:
        calibration_rows = list(csv.DictReader(handle))
    ratios: dict[str, list[float]] = {}
    for row in calibration_rows:
        reference = float(row["reference_duration_s"])
        observed = float(row["observed_duration_s"])
        ratios.setdefault(row["clock_id"], []).append(observed / reference)
    clock_scale = {
        clock_id: statistics.fmean(values) for clock_id, values in ratios.items()
    }

    values_by_target: dict[float, list[tuple[float, float]]] = {}
    with observations_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            flag = row["quality_flag"].strip()
            if flag != "ok":
                if flag in allowed_exclusion_flags:
                    continue
                raise ValueError(f"unregistered quality flag: {flag}")
            duration = float(row["end_time_s"]) - float(row["start_time_s"])
            period = (
                duration
                / int(row["oscillation_count"])
                / clock_scale[row["clock_id"]]
            )
            target = float(row["length_target_m"])
            measured = float(row["length_measured_m"])
            values_by_target.setdefault(target, []).append((measured, period))

    points = sorted(
        (
            math.log(statistics.median(measured for measured, _ in values)),
            math.log(statistics.median(period for _, period in values)),
        )
        for values in values_by_target.values()
    )
    if len(points) < 3:
        raise ValueError("at least three measured length levels are required")
    mean_x = statistics.fmean(x for x, _ in points)
    mean_y = statistics.fmean(y for _, y in points)
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
    intercept = mean_y - slope * mean_x
    residual_sum = sum((y - intercept - slope * x) ** 2 for x, y in points)
    slope_standard_error = math.sqrt(
        residual_sum / (len(points) - 2) / denominator
    )
    exponents = {"constant": 0.0, "square_root": 0.5, "linear": 1.0}
    selected = min(exponents, key=lambda model: abs(slope - exponents[model]))
    return {
        "selected_model": selected,
        "estimated_log_log_exponent": slope,
        "slope_standard_error": slope_standard_error,
        "length_level_count": len(points),
        "method": "median period by measured length, log-log ordinary least squares",
    }
