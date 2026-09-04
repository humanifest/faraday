from __future__ import annotations

import math
import statistics
from typing import Any

from research_machine.addons.models import AddonManifest, AnalysisMethod
from research_machine.domain.errors import ValidationError


def pendulum_gravity_estimate(
    spec: dict[str, Any], rows: list[dict[str, str]]
) -> dict[str, Any]:
    length_name = spec.get("length_column")
    period_name = spec.get("period_column")
    if not isinstance(length_name, str) or not isinstance(period_name, str):
        raise ValidationError(
            "pendulum_gravity_estimate requires length_column and period_column"
        )
    estimates: list[float] = []
    missing = 0
    for index, row in enumerate(rows, start=2):
        length_raw, period_raw = row.get(length_name), row.get(period_name)
        if length_raw is None or period_raw is None:
            raise ValidationError("pendulum column not found")
        if not length_raw.strip() or not period_raw.strip():
            missing += 1
            continue
        try:
            length, period = float(length_raw), float(period_raw)
        except ValueError as exc:
            raise ValidationError(
                f"non-numeric pendulum value at CSV row {index}"
            ) from exc
        if (
            not math.isfinite(length)
            or not math.isfinite(period)
            or length <= 0
            or period <= 0
        ):
            raise ValidationError(
                "pendulum length and period must be finite and positive "
                f"at CSV row {index}"
            )
        estimates.append(4 * math.pi**2 * length / period**2)
    if len(estimates) < 3:
        raise ValidationError(
            "pendulum_gravity_estimate requires three complete trials"
        )
    return {
        "n": len(estimates),
        "gravity_mean_m_s2": statistics.fmean(estimates),
        "gravity_median_m_s2": statistics.median(estimates),
        "gravity_standard_deviation_m_s2": statistics.stdev(estimates),
        "missing_rows": missing,
        "model": "small-angle simple pendulum g=4*pi^2*L/T^2",
    }


MANIFEST = AddonManifest(
    addon_id="physics",
    name="Physics Experiments",
    version="1.0.0",
    discipline="physics",
    description="Bundled physical and synthetic experiment implementations exercising the common scientific contracts.",
    methods=(
        AnalysisMethod(
            "pendulum_gravity_estimate",
            "Pendulum gravity estimate",
            "Estimate gravitational acceleration from positive length and period observations under the small-angle model.",
            ("length_column", "period_column"),
            pendulum_gravity_estimate,
        ),
    ),
    capabilities=("pendulum-simulation", "physical-pendulum", "independent-model-check"),
    protocol_kinds=("computational", "experimental"),
    dataset_media_types=("text/csv", "application/json"),
    documentation="campaigns/newtonian_pendulum/README.md",
)
