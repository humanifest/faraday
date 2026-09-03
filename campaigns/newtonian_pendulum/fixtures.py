"""Deterministic fixture generator, intentionally separate from both analyzers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any


OBSERVATION_FIELDS = [
    "trial_id",
    "sequence",
    "length_reported_m",
    "angle_start_deg",
    "oscillation_count",
    "start_time_s",
    "end_time_s",
    "clock_id",
    "quality_flag",
]
CALIBRATION_FIELDS = [
    "trial_id",
    "length_measured_m",
    "clock_drift_ppm",
    "amplitude_loss_fraction",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _seed_for(seed_reveal: str, case_id: str) -> int:
    digest = hashlib.sha256(f"{seed_reveal}:{case_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _period(model: str, length_m: float, angle_deg: float) -> float:
    if model == "constant":
        return 1.25
    if model == "linear":
        return 1.75 * length_m
    if model == "square_root":
        theta = math.radians(angle_deg)
        amplitude_correction = 1 + theta**2 / 16 + 11 * theta**4 / 3072
        return 2 * math.pi * math.sqrt(length_m / 9.80665) * amplitude_correction
    raise ValueError(f"unknown generator model: {model}")


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _generate_case(
    case: dict[str, Any], spec: dict[str, Any], output_root: Path
) -> None:
    case_id = str(case["case_id"])
    mutation = str(case["mutation"])
    rng = random.Random(_seed_for(str(spec["seed_reveal"]), case_id))
    lengths = [float(value) for value in spec["lengths_m"]]
    repetitions = int(spec["repetitions_per_length"])
    oscillations = int(spec["oscillations_per_trial"])
    logical_trials: list[tuple[float, int]] = []
    for repetition in range(1, repetitions + 1):
        block = [(length, repetition) for length in lengths]
        rng.shuffle(block)
        logical_trials.extend(block)

    observations: list[dict[str, object]] = []
    calibrations: list[dict[str, object]] = []
    for sequence, (length, repetition) in enumerate(logical_trials, start=1):
        trial_id = f"{case_id}-{sequence:03d}"
        clock_id = "clock-a" if sequence % 2 else "clock-b"
        clock_drift_ppm = 18.0 if clock_id == "clock-a" else -14.0
        angle_deg = 5.0
        amplitude_loss = 0.04
        reported_length = length
        measured_length = length * (1 + rng.uniform(-0.0008, 0.0008))
        quality_flag = "ok"

        if mutation == "clock_drift" and clock_id == "clock-b":
            clock_drift_ppm = 5000.0
        if mutation == "length_mislabel" and length == 0.75:
            reported_length = 1.15
        if mutation == "large_angle":
            angle_deg = 25.0
        if mutation == "excessive_damping":
            amplitude_loss = 0.28

        true_period = _period(str(case["generator_model"]), length, angle_deg)
        noisy_period = true_period + rng.gauss(0.0, 0.0035)
        observed_duration = (
            noisy_period * oscillations * (1 + clock_drift_ppm / 1_000_000)
        )
        if mutation == "flagged_dropout" and sequence == 7:
            quality_flag = "sensor_dropout"
            observed_duration += oscillations * 0.8
        if mutation == "unflagged_outlier" and sequence == 7:
            observed_duration += oscillations * 0.8

        start_time = sequence * 50.0
        observations.append(
            {
                "trial_id": trial_id,
                "sequence": sequence,
                "length_reported_m": f"{reported_length:.6f}",
                "angle_start_deg": f"{angle_deg:.3f}",
                "oscillation_count": oscillations,
                "start_time_s": f"{start_time:.9f}",
                "end_time_s": f"{start_time + observed_duration:.9f}",
                "clock_id": clock_id,
                "quality_flag": quality_flag,
            }
        )
        calibrations.append(
            {
                "trial_id": trial_id,
                "length_measured_m": f"{measured_length:.6f}",
                "clock_drift_ppm": f"{clock_drift_ppm:.3f}",
                "amplitude_loss_fraction": f"{amplitude_loss:.4f}",
            }
        )

    if mutation == "incomplete_series":
        omitted = {
            row["trial_id"]
            for row in observations
            if row["length_reported_m"] == "1.250000"
        }
        observations = [row for row in observations if row["trial_id"] not in omitted]
        calibrations = [row for row in calibrations if row["trial_id"] not in omitted]

    case_root = output_root / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    observations_path = case_root / "observations.csv"
    calibration_path = case_root / "calibration.csv"
    _write_csv(observations_path, OBSERVATION_FIELDS, observations)
    _write_csv(calibration_path, CALIBRATION_FIELDS, calibrations)

    manifest = {
        "schema_version": 1,
        "case_id": case_id,
        "synthetic": True,
        "generator_model": case["generator_model"],
        "mutation": mutation,
        "expected_model": case.get("expected_model"),
        "expected_valid": case["expected_valid"],
        "expected_failed_gate": case.get("expected_failed_gate"),
        "expected_rows": len(lengths) * repetitions,
        "expected_lengths_m": lengths,
        "repetitions_per_length": repetitions,
        "artifacts": {
            "observations.csv": sha256_file(observations_path),
            "calibration.csv": sha256_file(calibration_path),
        },
    }
    (case_root / "case.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def generate_fixtures(spec_path: Path, output_root: Path) -> None:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    output_root.mkdir(parents=True, exist_ok=True)
    for case in spec["cases"]:
        _generate_case(case, spec, output_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path(__file__).with_name("campaign-spec.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate_fixtures(args.spec.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
