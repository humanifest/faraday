"""Independent model check using a log-log slope, not template fitting."""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path


def classify_from_files(
    observations_path: Path,
    calibration_path: Path,
    allowed_exclusion_flags: set[str],
) -> dict[str, object]:
    with calibration_path.open(encoding="utf-8", newline="") as handle:
        calibration = {
            row["trial_id"]: float(row["clock_drift_ppm"])
            for row in csv.DictReader(handle)
        }
    periods_by_length: dict[float, list[float]] = {}
    with observations_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            flag = row["quality_flag"]
            if flag != "ok":
                if flag in allowed_exclusion_flags:
                    continue
                raise ValueError(f"unregistered quality flag: {flag}")
            duration = float(row["end_time_s"]) - float(row["start_time_s"])
            count = int(row["oscillation_count"])
            drift = calibration[row["trial_id"]]
            corrected_period = duration / count / (1 + drift / 1_000_000)
            periods_by_length.setdefault(float(row["length_reported_m"]), []).append(
                corrected_period
            )
    points = sorted(
        (math.log(length), math.log(statistics.median(periods)))
        for length, periods in periods_by_length.items()
    )
    if len(points) < 3:
        raise ValueError("at least three distinct length levels are required")
    mean_x = statistics.fmean(x for x, _ in points)
    mean_y = statistics.fmean(y for _, y in points)
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
    exponents = {"constant": 0.0, "square_root": 0.5, "linear": 1.0}
    selected = min(exponents, key=lambda model: abs(slope - exponents[model]))
    return {
        "selected_model": selected,
        "estimated_log_log_exponent": slope,
        "length_level_count": len(points),
        "method": "median-period log-log ordinary least squares",
    }
