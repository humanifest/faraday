"""Quality-gated executor for the synthetic pendulum benchmark suite."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from campaigns.newtonian_pendulum.analyzer import fit_candidate_models
from campaigns.newtonian_pendulum.independent_checker import classify_from_files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gate(gate_id: str, passed: bool, summary: str, **details: object) -> dict[str, object]:
    return {
        "gate_id": gate_id,
        "status": "passed" if passed else "failed",
        "summary": summary,
        "required": True,
        "details": details,
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _case_analysis(case_root: Path, spec: dict[str, Any]) -> dict[str, object]:
    manifest_path = case_root / "case.json"
    observations_path = case_root / "observations.csv"
    calibration_path = case_root / "calibration.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    observations = _read_rows(observations_path)
    calibrations = _read_rows(calibration_path)
    gates: list[dict[str, object]] = []

    integrity_actual = {
        "observations.csv": _sha256(observations_path),
        "calibration.csv": _sha256(calibration_path),
    }
    integrity_passed = integrity_actual == manifest["artifacts"]
    gates.append(
        _gate(
            "artifact-integrity",
            integrity_passed,
            "Fixture artifact hashes match the sealed case manifest."
            if integrity_passed
            else "At least one fixture artifact differs from its sealed manifest.",
            expected=manifest["artifacts"],
            actual=integrity_actual,
        )
    )

    expected_rows = int(manifest["expected_rows"])
    expected_lengths = [float(value) for value in manifest["expected_lengths_m"]]
    reported_counts = Counter(float(row["length_reported_m"]) for row in observations)
    complete = (
        len(observations) == expected_rows
        and len(calibrations) == expected_rows
        and set(reported_counts) == set(expected_lengths)
        and all(
            reported_counts[length] == int(manifest["repetitions_per_length"])
            for length in expected_lengths
        )
    )
    gates.append(
        _gate(
            "dataset-completeness",
            complete,
            "All preregistered trials and length strata are present."
            if complete
            else "The observed rows or length strata do not match the stopping rule.",
            expected_rows=expected_rows,
            observed_rows=len(observations),
            counts_by_reported_length=dict(sorted(reported_counts.items())),
        )
    )

    sequence_lengths = [float(row["length_reported_m"]) for row in observations]
    monotonic = sequence_lengths == sorted(sequence_lengths) or sequence_lengths == sorted(
        sequence_lengths, reverse=True
    )
    maximum_run = 0
    current_run = 0
    previous: float | None = None
    for length in sequence_lengths:
        current_run = current_run + 1 if length == previous else 1
        maximum_run = max(maximum_run, current_run)
        previous = length
    randomized = bool(sequence_lengths) and not monotonic and maximum_run <= 3
    gates.append(
        _gate(
            "randomization-check",
            randomized,
            "Acquisition order is interleaved across length conditions."
            if randomized
            else "Acquisition order is sorted or excessively blocked.",
            maximum_adjacent_same_length=maximum_run,
            monotonic=monotonic,
        )
    )

    calibration_by_id = {row["trial_id"]: row for row in calibrations}
    paired_ids = {row["trial_id"] for row in observations} == set(calibration_by_id)
    relative_errors: list[float] = []
    clock_drifts: list[float] = []
    amplitude_losses: list[float] = []
    samples: list[tuple[float, float]] = []
    excluded_ids: list[str] = []
    unregistered_flags: list[str] = []
    allowed_flags = set(spec["allowed_exclusion_flags"])
    periods_by_length: dict[float, list[tuple[str, float]]] = {}
    if paired_ids:
        for row in observations:
            calibration = calibration_by_id[row["trial_id"]]
            reported = float(row["length_reported_m"])
            measured = float(calibration["length_measured_m"])
            relative_errors.append(abs(measured - reported) / measured)
            drift = float(calibration["clock_drift_ppm"])
            clock_drifts.append(abs(drift))
            amplitude_losses.append(float(calibration["amplitude_loss_fraction"]))
            flag = row["quality_flag"]
            if flag != "ok":
                if flag in allowed_flags:
                    excluded_ids.append(row["trial_id"])
                    continue
                unregistered_flags.append(flag)
            duration = float(row["end_time_s"]) - float(row["start_time_s"])
            period = duration / int(row["oscillation_count"]) / (1 + drift / 1_000_000)
            samples.append((reported, period))
            periods_by_length.setdefault(reported, []).append((row["trial_id"], period))

    max_length_error = max(relative_errors, default=float("inf"))
    length_ok = paired_ids and max_length_error <= float(
        spec["maximum_relative_length_error"]
    )
    gates.append(
        _gate(
            "length-calibration",
            length_ok,
            "Reported lengths agree with independent calibration."
            if length_ok
            else "Reported and independently measured lengths disagree.",
            maximum_relative_error=max_length_error,
            allowed=float(spec["maximum_relative_length_error"]),
            calibration_pairs_complete=paired_ids,
        )
    )

    max_clock_drift = max(clock_drifts, default=float("inf"))
    clock_ok = paired_ids and max_clock_drift <= float(spec["maximum_clock_drift_ppm"])
    gates.append(
        _gate(
            "clock-calibration",
            clock_ok,
            "All clocks satisfy the preregistered drift bound."
            if clock_ok
            else "At least one clock exceeds the preregistered drift bound.",
            maximum_absolute_drift_ppm=max_clock_drift,
            allowed_ppm=float(spec["maximum_clock_drift_ppm"]),
        )
    )

    max_angle = max(
        (float(row["angle_start_deg"]) for row in observations), default=float("inf")
    )
    angle_ok = max_angle <= float(spec["small_angle_max_deg"])
    gates.append(
        _gate(
            "small-angle-boundary",
            angle_ok,
            "All trials remain inside the preregistered small-angle regime."
            if angle_ok
            else "At least one trial is outside the small-angle regime.",
            maximum_angle_deg=max_angle,
            allowed_deg=float(spec["small_angle_max_deg"]),
        )
    )

    max_amplitude_loss = max(amplitude_losses, default=float("inf"))
    damping_ok = paired_ids and max_amplitude_loss <= float(
        spec["maximum_amplitude_loss_fraction"]
    )
    gates.append(
        _gate(
            "damping-boundary",
            damping_ok,
            "Amplitude loss remains inside the registered damping bound."
            if damping_ok
            else "Amplitude loss exceeds the registered damping bound.",
            maximum_amplitude_loss_fraction=max_amplitude_loss,
            allowed=float(spec["maximum_amplitude_loss_fraction"]),
        )
    )

    exclusions_ok = (
        not unregistered_flags
        and len(excluded_ids) <= int(spec["maximum_registered_exclusions"])
    )
    gates.append(
        _gate(
            "exclusion-compliance",
            exclusions_ok,
            "Only preregistered sensor flags were excluded within the fixed limit."
            if exclusions_ok
            else "Exclusions violate the preregistered flag or count policy.",
            excluded_trial_ids=excluded_ids,
            unregistered_flags=unregistered_flags,
            maximum_exclusions=int(spec["maximum_registered_exclusions"]),
        )
    )

    outlier_ids: list[str] = []
    for group in periods_by_length.values():
        values = [period for _, period in group]
        if len(values) < 3:
            continue
        median = statistics.median(values)
        mad = statistics.median(abs(value - median) for value in values)
        threshold = max(6 * 1.4826 * mad, 0.03)
        outlier_ids.extend(
            trial_id
            for trial_id, period in group
            if abs(period - median) > threshold
        )
    stability_ok = not outlier_ids
    gates.append(
        _gate(
            "measurement-stability",
            stability_ok,
            "No unflagged within-condition timing outlier was detected."
            if stability_ok
            else "An unflagged timing outlier exceeded the frozen robust threshold.",
            outlier_trial_ids=sorted(outlier_ids),
            rule="absolute residual > max(6 * 1.4826 * MAD, 0.03 seconds)",
        )
    )

    primary = fit_candidate_models(samples)
    independent = classify_from_files(
        observations_path, calibration_path, allowed_flags
    )
    discrimination_ok = float(primary["runner_up_to_best_rmse_ratio"]) >= float(
        spec["minimum_model_rmse_ratio"]
    )
    gates.append(
        _gate(
            "model-discrimination",
            discrimination_ok,
            "The winning model clears the preregistered separation threshold."
            if discrimination_ok
            else "The candidate models are not cleanly separated.",
            selected_model=primary["selected_model"],
            runner_up_to_best_rmse_ratio=primary["runner_up_to_best_rmse_ratio"],
            required_ratio=float(spec["minimum_model_rmse_ratio"]),
        )
    )

    required_validity_gates = {
        "artifact-integrity",
        "dataset-completeness",
        "randomization-check",
        "length-calibration",
        "clock-calibration",
        "small-angle-boundary",
        "damping-boundary",
        "exclusion-compliance",
        "measurement-stability",
        "model-discrimination",
    }
    gate_status = {str(gate["gate_id"]): gate["status"] == "passed" for gate in gates}
    valid = all(gate_status[gate_id] for gate_id in required_validity_gates)
    expected_valid = bool(manifest["expected_valid"])
    expected_model = manifest.get("expected_model")
    expected_failed_gate = manifest.get("expected_failed_gate")
    expectation_met = (
        valid
        and expected_valid
        and primary["selected_model"] == expected_model
        and independent["selected_model"] == expected_model
    ) or (
        not expected_valid
        and not valid
        and isinstance(expected_failed_gate, str)
        and not gate_status.get(expected_failed_gate, True)
    )
    return {
        "case_id": manifest["case_id"],
        "synthetic": True,
        "expected_valid": expected_valid,
        "expected_model": expected_model,
        "expected_failed_gate": expected_failed_gate,
        "valid": valid,
        "expectation_met": expectation_met,
        "primary_analysis": primary,
        "independent_analysis": independent,
        "quality_gates": gates,
    }


def _suite_gate(
    gate_id: str, passed: bool, summary: str, case_ids: list[str]
) -> dict[str, object]:
    return _gate(gate_id, passed, summary, case_ids=case_ids)


def _case_gate_passed(result: dict[str, object], gate_id: str) -> bool:
    gates = result["quality_gates"]
    if not isinstance(gates, list):
        return False
    matching = [
        gate
        for gate in gates
        if isinstance(gate, dict) and gate.get("gate_id") == gate_id
    ]
    return len(matching) == 1 and matching[0].get("status") == "passed"


def execute_suite(
    fixture_root: Path, spec_path: Path, output_path: Path | None = None
) -> dict[str, object]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    results = [
        _case_analysis(fixture_root / str(case["case_id"]), spec)
        for case in spec["cases"]
    ]
    by_id = {str(result["case_id"]): result for result in results}
    clean_ids = ["clean_square_root"]
    control_ids = ["constant_control", "linear_control"]
    exclusion_ids = ["registered_dropout"]
    adversarial_ids = [
        str(case["case_id"])
        for case in spec["cases"]
        if not bool(case["expected_valid"])
    ]
    valid_ids = clean_ids + control_ids + exclusion_ids

    fixture_integrity = all(
        _case_gate_passed(result, "artifact-integrity") for result in results
    )
    randomization_ok = all(
        _case_gate_passed(result, "randomization-check")
        for result in results
        if bool(result["expected_valid"])
    )
    clean_ok = all(bool(by_id[case_id]["expectation_met"]) for case_id in clean_ids)
    controls_ok = all(bool(by_id[case_id]["expectation_met"]) for case_id in control_ids)
    exclusion_ok = all(
        bool(by_id[case_id]["expectation_met"]) for case_id in exclusion_ids
    )
    adversarial_ok = all(
        bool(by_id[case_id]["expectation_met"]) for case_id in adversarial_ids
    )
    analyzers_agree = all(
        by_id[case_id]["primary_analysis"]["selected_model"]
        == by_id[case_id]["independent_analysis"]["selected_model"]
        for case_id in valid_ids
    )
    suite_gates = [
        _suite_gate(
            "fixture-integrity",
            fixture_integrity,
            "Every generated input matches its sealed case manifest.",
            [str(result["case_id"]) for result in results],
        ),
        _suite_gate(
            "randomization-check",
            randomization_ok,
            "All valid calibration and control cases retain an interleaved acquisition order.",
            valid_ids,
        ),
        _suite_gate(
            "clean-known-result",
            clean_ok,
            "The clean fixture recovers T proportional to square root of L.",
            clean_ids,
        ),
        _suite_gate(
            "alternative-model-controls",
            controls_ok,
            "The analyzers recover constant and linear controls instead of hard-coding the expected law.",
            control_ids,
        ),
        _suite_gate(
            "registered-exclusion-control",
            exclusion_ok,
            "A preregistered sensor dropout is excluded without changing the model verdict.",
            exclusion_ids,
        ),
        _suite_gate(
            "adversarial-fail-closed",
            adversarial_ok,
            "Every planted defect invalidates its case through the preregistered gate.",
            adversarial_ids,
        ),
        _suite_gate(
            "analyzer-agreement",
            analyzers_agree,
            "Template fitting and the independent log-log implementation agree on all valid cases.",
            valid_ids,
        ),
    ]
    known_result_ok = all(gate["status"] == "passed" for gate in suite_gates)
    suite_gates.append(
        _suite_gate(
            "known-result-reproduction",
            known_result_ok,
            "The complete synthetic calibration suite reproduces the registered known result and all controls."
            if known_result_ok
            else "The known-result reproduction is withheld because at least one required suite gate failed.",
            [str(result["case_id"]) for result in results],
        )
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "campaign_id": spec["campaign_id"],
        "synthetic": True,
        "scientific_evidence_eligible": False,
        "conclusion": (
            "Executor calibration passed; this is not empirical evidence for Newtonian physics."
            if known_result_ok
            else "Executor calibration failed; inspect the required suite gates."
        ),
        "quality_gates": suite_gates,
        "cases": results,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return report
