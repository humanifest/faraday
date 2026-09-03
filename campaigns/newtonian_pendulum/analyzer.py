"""Primary preregistered candidate-model analyzer."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelFit:
    model: str
    coefficient: float
    rmse_s: float

    def to_dict(self) -> dict[str, float | str]:
        return {
            "model": self.model,
            "coefficient": self.coefficient,
            "rmse_s": self.rmse_s,
        }


def _basis(model: str, length_m: float) -> float:
    if model == "constant":
        return 1.0
    if model == "linear":
        return length_m
    if model == "square_root":
        return math.sqrt(length_m)
    raise ValueError(f"unknown model: {model}")


def fit_candidate_models(samples: list[tuple[float, float]]) -> dict[str, object]:
    if len(samples) < 3:
        raise ValueError("at least three samples are required")
    fits: list[ModelFit] = []
    for model in ("constant", "linear", "square_root"):
        design = [_basis(model, length) for length, _ in samples]
        coefficient = sum(x * period for x, (_, period) in zip(design, samples)) / sum(
            x * x for x in design
        )
        residuals = [
            period - coefficient * x
            for x, (_, period) in zip(design, samples)
        ]
        rmse = math.sqrt(sum(value * value for value in residuals) / len(residuals))
        fits.append(ModelFit(model, coefficient, rmse))
    fits.sort(key=lambda item: item.rmse_s)
    best = fits[0]
    runner_up = fits[1]
    ratio = math.inf if best.rmse_s == 0 else runner_up.rmse_s / best.rmse_s
    return {
        "selected_model": best.model,
        "runner_up_model": runner_up.model,
        "runner_up_to_best_rmse_ratio": ratio,
        "fits": [item.to_dict() for item in fits],
        "sample_count": len(samples),
    }
