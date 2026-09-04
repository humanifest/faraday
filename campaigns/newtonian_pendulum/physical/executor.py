"""Read-only analysis and run-record construction for physical pendulum data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import random
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from campaigns.newtonian_pendulum.physical.independent_checker import (
    classify_from_files,
)


PHYSICAL_ROOT = Path(__file__).resolve().parent
SPEC_PATH = PHYSICAL_ROOT / "physical-spec.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analysis_code_hash(spec_path: Path = SPEC_PATH) -> str:
    digest = hashlib.sha256()
    for path in (
        PHYSICAL_ROOT / "executor.py",
        PHYSICAL_ROOT / "independent_checker.py",
        spec_path,
    ):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def environment_hash() -> str:
    value = {
        "implementation": "python-standard-library",
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _expected_schedule(spec: dict[str, Any]) -> list[dict[str, str]]:
    seed = int.from_bytes(
        hashlib.sha256(str(spec["seed_reveal"]).encode()).digest()[:8], "big"
    )
    rng = random.Random(seed)
    lengths = [float(value) for value in spec["lengths_m"]]
    rows: list[dict[str, str]] = []
    sequence = 0
    for block in range(1, int(spec["blocks"]) + 1):
        block_lengths = list(lengths)
        rng.shuffle(block_lengths)
        for length in block_lengths:
            sequence += 1
            rows.append(
                {
                    "trial_id": f"b{block:02d}-t{sequence:03d}",
                    "block": str(block),
                    "sequence": str(sequence),
                    "length_target_m": f"{length:.3f}",
                    "oscillation_count": str(spec["oscillations_per_trial"]),
                    "source_id": f"block-{block:02d}",
                    "timing_audit": "yes" if (sequence - 1) % len(lengths) == 0 else "no",
                }
            )
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is blank")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp lacks a UTC offset")
    return parsed


def _gate(gate_id: str, passed: bool, summary: str, **details: object) -> dict[str, object]:
    return {
        "gate_id": gate_id,
        "status": "passed" if passed else "failed",
        "summary": summary,
        "required": True,
        "details": details,
    }


def _basis(model: str, length_m: float) -> float:
    if model == "constant":
        return 1.0
    if model == "linear":
        return length_m
    if model == "square_root":
        return math.sqrt(length_m)
    raise ValueError(f"unknown candidate model: {model}")


def _fit_candidate_models(
    samples: list[tuple[float, float, float]],
) -> dict[str, Any]:
    target_lengths = sorted({target for target, _, _ in samples})
    if len(target_lengths) < 3:
        raise ValueError("at least three target length levels are required")
    fits: list[dict[str, Any]] = []
    for model in ("constant", "linear", "square_root"):
        squared_errors: list[float] = []
        for held_out in target_lengths:
            training = [sample for sample in samples if sample[0] != held_out]
            testing = [sample for sample in samples if sample[0] == held_out]
            design = [_basis(model, measured) for _, measured, _ in training]
            coefficient = sum(
                x * period
                for x, (_, _, period) in zip(design, training)
            ) / sum(x * x for x in design)
            squared_errors.extend(
                (period - coefficient * _basis(model, measured)) ** 2
                for _, measured, period in testing
            )
        all_design = [_basis(model, measured) for _, measured, _ in samples]
        all_coefficient = sum(
            x * period for x, (_, _, period) in zip(all_design, samples)
        ) / sum(x * x for x in all_design)
        fits.append(
            {
                "model": model,
                "coefficient": all_coefficient,
                "leave_one_length_out_rmse_s": math.sqrt(
                    sum(squared_errors) / len(squared_errors)
                ),
            }
        )
    fits.sort(key=lambda item: float(item["leave_one_length_out_rmse_s"]))
    best_rmse = float(fits[0]["leave_one_length_out_rmse_s"])
    runner_up_rmse = float(fits[1]["leave_one_length_out_rmse_s"])
    ratio = math.inf if best_rmse == 0 else runner_up_rmse / best_rmse
    square_root_fit = next(item for item in fits if item["model"] == "square_root")
    square_root_coefficient = float(square_root_fit["coefficient"])
    gravity = (2 * math.pi / square_root_coefficient) ** 2
    return {
        "selected_model": fits[0]["model"],
        "runner_up_model": fits[1]["model"],
        "runner_up_to_best_rmse_ratio": ratio,
        "implied_gravity_m_s2": gravity,
        "sample_count": len(samples),
        "length_level_count": len(target_lengths),
        "fits": fits,
        "method": "one-parameter fits scored by leave-one-target-length-out RMSE",
    }


def _clock_scales(rows: list[dict[str, str]]) -> tuple[dict[str, float], bool, dict[str, object]]:
    ratios: dict[str, list[float]] = {}
    phases: dict[str, set[str]] = {}
    parse_errors: list[str] = []
    for row in rows:
        try:
            reference = float(row["reference_duration_s"])
            observed = float(row["observed_duration_s"])
            if reference <= 0 or observed <= 0:
                raise ValueError
            ratios.setdefault(row["clock_id"], []).append(observed / reference)
            phases.setdefault(row["clock_id"], set()).add(row["phase"])
        except (KeyError, ValueError):
            parse_errors.append(row.get("calibration_id", "unknown"))
    scales = {
        clock_id: statistics.fmean(values) for clock_id, values in ratios.items()
    }
    complete = bool(scales) and all(
        phases.get(clock_id) == {"before", "after"} for clock_id in scales
    )
    return scales, complete and not parse_errors, {
        "clock_scales": scales,
        "phases": {key: sorted(value) for key, value in phases.items()},
        "parse_error_calibration_ids": parse_errors,
    }


def _source_integrity(
    kit_root: Path,
    source_rows: list[dict[str, str]],
    observations: list[dict[str, str]],
    expected_blocks: int,
) -> tuple[bool, dict[str, object]]:
    duplicate_ids = [
        source_id
        for source_id, count in Counter(row.get("source_id", "") for row in source_rows).items()
        if not source_id or count != 1
    ]
    source_by_id = {row.get("source_id", ""): row for row in source_rows}
    errors: list[str] = []
    block_reference_mismatches: list[str] = []
    verified_blocks: set[int] = set()
    for source_id, row in source_by_id.items():
        try:
            block = int(row["block"])
            locator = row["locator"].strip()
            expected_hash = row["sha256"].strip().lower()
            expected_size = int(row["size_bytes"])
            path = Path(locator)
            if not path.is_absolute():
                path = kit_root / path
            if not path.is_file():
                raise ValueError("source file is missing")
            if path.stat().st_size != expected_size:
                raise ValueError("source byte count differs")
            if sha256_file(path) != expected_hash:
                raise ValueError("source SHA-256 differs")
            verified_blocks.add(block)
        except (KeyError, OSError, ValueError) as exc:
            errors.append(f"{source_id or 'missing-id'}: {exc}")
    observation_source_ids = {row.get("source_id", "") for row in observations}
    missing_references = sorted(observation_source_ids - set(source_by_id))
    for row in observations:
        source = source_by_id.get(row.get("source_id", ""))
        if source is not None and row.get("block", "") != source.get("block", ""):
            block_reference_mismatches.append(row.get("trial_id", "unknown"))
    expected_block_set = set(range(1, expected_blocks + 1))
    passed = (
        not duplicate_ids
        and not errors
        and not missing_references
        and not block_reference_mismatches
        and verified_blocks == expected_block_set
    )
    return passed, {
        "duplicate_or_blank_source_ids": sorted(duplicate_ids),
        "source_errors": errors,
        "unregistered_observation_source_ids": missing_references,
        "source_block_mismatch_trial_ids": block_reference_mismatches,
        "verified_blocks": sorted(verified_blocks),
        "expected_blocks": sorted(expected_block_set),
    }


def _scientific_outcome(
    primary: dict[str, Any] | None,
    independent: dict[str, Any] | None,
    spec: dict[str, Any],
    quality_valid: bool,
) -> dict[str, Any]:
    if not quality_valid or primary is None or independent is None:
        return {
            "direction": "not_interpretable",
            "summary": "Scientific interpretation is withheld because execution quality failed.",
        }
    primary_model = str(primary["selected_model"])
    independent_model = str(independent["selected_model"])
    ratio = float(primary["runner_up_to_best_rmse_ratio"])
    exponent = float(independent["estimated_log_log_exponent"])
    gravity = float(primary["implied_gravity_m_s2"])
    separated = ratio >= float(spec["minimum_model_rmse_ratio"])
    analyzers_agree = primary_model == independent_model
    exponent_low, exponent_high = map(float, spec["square_root_exponent_interval"])
    gravity_low, gravity_high = map(float, spec["gravity_interval_m_s2"])
    if (
        separated
        and analyzers_agree
        and primary_model == "square_root"
        and exponent_low <= exponent <= exponent_high
        and gravity_low <= gravity <= gravity_high
    ):
        direction = "supports_square_root"
        summary = (
            "The registered apparatus-level data favor T proportional to square root "
            "of L against the constant and linear alternatives."
        )
    elif separated and analyzers_agree and primary_model != "square_root":
        direction = f"supports_{primary_model}"
        summary = (
            f"The registered apparatus-level data favor the {primary_model} model; "
            "the square-root prediction is weakened in this scope."
        )
    else:
        direction = "inconclusive"
        summary = (
            "The registered model-separation or cross-analyzer agreement rule was not met."
        )
    return {
        "direction": direction,
        "summary": summary,
        "primary_selected_model": primary_model,
        "independent_selected_model": independent_model,
        "runner_up_to_best_rmse_ratio": ratio,
        "minimum_required_ratio": float(spec["minimum_model_rmse_ratio"]),
        "estimated_log_log_exponent": exponent,
        "square_root_exponent_interval": [exponent_low, exponent_high],
        "implied_gravity_m_s2": gravity,
        "registered_gravity_interval_m_s2": [gravity_low, gravity_high],
        "claim_ceiling": (
            "This result concerns one apparatus and the registered length and angle "
            "range. It does not validate a universal theory or establish a mechanism."
        ),
    }


def analyze_field_run(kit_root: Path, spec_path: Path = SPEC_PATH) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    protocol_summary = json.loads(
        (kit_root / "protocol-summary.json").read_text(encoding="utf-8")
    )
    session = json.loads((kit_root / "session.json").read_text(encoding="utf-8"))
    schedule = _read_csv(kit_root / "schedule.csv")
    observations_path = kit_root / "observations.csv"
    observations = _read_csv(observations_path)
    clock_path = kit_root / "clock-calibration.csv"
    clock_rows = _read_csv(clock_path)
    source_rows = _read_csv(kit_root / "source-files.csv")
    gates: list[dict[str, object]] = []

    session_errors: list[str] = []
    for field in (
        "session_id",
        "collector_id",
        "location_description",
        "apparatus_id",
        "timer_method",
    ):
        if not isinstance(session.get(field), str) or not session[field].strip():
            session_errors.append(f"{field} is blank")
    if session.get("protocol_id") != protocol_summary.get("protocol_id"):
        session_errors.append("protocol_id does not match the frozen kit")
    if session.get("protocol_hash") != protocol_summary.get("protocol_hash"):
        session_errors.append("protocol_hash does not match the frozen kit")
    try:
        registered = _aware_datetime(protocol_summary["registration_timestamp"])
        started = _aware_datetime(session["collection_started_at_utc"])
        completed = _aware_datetime(session["collection_completed_at_utc"])
        if started < registered:
            session_errors.append("collection began before protocol registration")
        if completed < started:
            session_errors.append("collection completed before it began")
        analysis_timestamp = session.get("analysis_completed_at_utc")
        if isinstance(analysis_timestamp, str) and analysis_timestamp.strip():
            analyzed = _aware_datetime(analysis_timestamp)
            if analyzed < completed:
                session_errors.append("analysis completed before collection")
    except (KeyError, TypeError, ValueError) as exc:
        session_errors.append(f"invalid session chronology: {exc}")
    if not isinstance(session.get("deviations"), list):
        session_errors.append("deviations must be a list")
    session_ok = not session_errors
    gates.append(
        _gate(
            "session-integrity",
            session_ok,
            "Session identity and chronology match the frozen local protocol."
            if session_ok
            else "Session identity, required metadata, or chronology is invalid.",
            errors=session_errors,
        )
    )

    source_ok, source_details = _source_integrity(
        kit_root, source_rows, observations, int(spec["blocks"])
    )
    gates.append(
        _gate(
            "raw-source-integrity",
            source_ok,
            "Every block has a content-verified raw source referenced by its trials."
            if source_ok
            else "Raw source coverage or content verification failed.",
            **source_details,
        )
    )

    scheduled_ids = [row.get("trial_id", "") for row in schedule]
    observed_ids = [row.get("trial_id", "") for row in observations]
    expected_rows = int(spec["blocks"]) * len(spec["lengths_m"])
    complete = (
        len(schedule) == expected_rows
        and len(observations) == expected_rows
        and len(set(observed_ids)) == expected_rows
        and set(observed_ids) == set(scheduled_ids)
    )
    gates.append(
        _gate(
            "dataset-completeness",
            complete,
            "All preregistered trial rows are present exactly once."
            if complete
            else "Trial rows are missing, duplicated, or not preregistered.",
            expected_rows=expected_rows,
            observed_rows=len(observations),
            duplicate_count=len(observed_ids) - len(set(observed_ids)),
            missing_trial_ids=sorted(set(scheduled_ids) - set(observed_ids)),
            unexpected_trial_ids=sorted(set(observed_ids) - set(scheduled_ids)),
        )
    )

    expected_schedule = _expected_schedule(spec)
    fixed_fields = (
        "trial_id",
        "block",
        "sequence",
        "length_target_m",
        "oscillation_count",
        "source_id",
        "timing_audit",
    )
    frozen_schedule_matches_seed = [
        {field: row.get(field, "").strip() for field in fixed_fields}
        for row in schedule
    ] == expected_schedule
    seed_reveal = str(protocol_summary.get("random_seed_reveal", ""))
    seed_commitment = str(protocol_summary.get("random_seed_commitment", ""))
    seed_commitment_matches = (
        seed_reveal == str(spec["seed_reveal"])
        and hashlib.sha256(seed_reveal.encode()).hexdigest() == seed_commitment
    )
    schedule_by_id = {row["trial_id"]: row for row in schedule}
    schedule_mismatches: list[str] = []
    for row in observations:
        expected = schedule_by_id.get(row.get("trial_id", ""))
        if expected is None:
            continue
        for field in fixed_fields[1:]:
            if row.get(field, "").strip() != expected.get(field, "").strip():
                schedule_mismatches.append(f"{row['trial_id']}:{field}")
    schedule_ok = (
        complete
        and seed_commitment_matches
        and frozen_schedule_matches_seed
        and not schedule_mismatches
    )
    gates.append(
        _gate(
            "schedule-compliance",
            schedule_ok,
            "Trial order and fixed conditions match the randomized schedule."
            if schedule_ok
            else "One or more fixed trial fields differ from the frozen schedule.",
            mismatches=schedule_mismatches,
            seed_reveal_matches_commitment=seed_commitment_matches,
            frozen_schedule_matches_committed_seed=frozen_schedule_matches_seed,
        )
    )

    clock_scales, clock_complete, clock_details = _clock_scales(clock_rows)
    used_clocks = {row.get("clock_id", "") for row in observations}
    max_clock_error = max(
        (abs(scale - 1) for scale in clock_scales.values()), default=float("inf")
    )
    clock_ok = (
        clock_complete
        and used_clocks == set(clock_scales)
        and max_clock_error <= float(spec["maximum_clock_relative_error"])
    )
    gates.append(
        _gate(
            "clock-calibration",
            clock_ok,
            "Before/after clock checks satisfy the frozen error bound."
            if clock_ok
            else "Clock calibration is incomplete or outside the frozen error bound.",
            maximum_relative_error=max_clock_error,
            allowed=float(spec["maximum_clock_relative_error"]),
            used_clocks=sorted(used_clocks),
            **clock_details,
        )
    )

    parse_errors: list[str] = []
    length_errors: list[float] = []
    angles: list[float] = []
    amplitude_losses: list[float] = []
    amplitude_growth_ids: list[str] = []
    periods: list[float] = []
    timing_audit_errors: list[float] = []
    missing_timing_audits: list[str] = []
    samples: list[tuple[float, float, float]] = []
    excluded: list[tuple[str, float, str]] = []
    unregistered_flags: list[str] = []
    allowed_flags = set(spec["allowed_exclusion_flags"])
    for row in observations:
        trial_id = row.get("trial_id", "unknown")
        try:
            target = float(row["length_target_m"])
            measured = float(row["length_measured_m"])
            angle = float(row["angle_start_deg"])
            amplitude_end = float(row["amplitude_end_deg"])
            count = int(row["oscillation_count"])
            start = float(row["start_time_s"])
            end = float(row["end_time_s"])
            scale = clock_scales[row["clock_id"]]
            if (
                target <= 0
                or measured <= 0
                or angle <= 0
                or amplitude_end < 0
                or count <= 0
                or end <= start
            ):
                raise ValueError
            period = (end - start) / count / scale
            length_errors.append(abs(measured - target) / target)
            angles.append(angle)
            amplitude_losses.append(max(0.0, 1 - amplitude_end / angle))
            if amplitude_end > angle:
                amplitude_growth_ids.append(trial_id)
            periods.append(period)
            if row["timing_audit"].strip() == "yes":
                try:
                    audit_start = float(row["audit_start_time_s"])
                    audit_end = float(row["audit_end_time_s"])
                    if audit_end <= audit_start:
                        raise ValueError
                    audit_period = (audit_end - audit_start) / count / scale
                    timing_audit_errors.append(abs(audit_period - period))
                except (KeyError, ValueError):
                    missing_timing_audits.append(trial_id)
            flag = row["quality_flag"].strip()
            if flag == "ok":
                samples.append((target, measured, period))
            elif flag in allowed_flags:
                excluded.append((trial_id, target, flag))
            else:
                unregistered_flags.append(f"{trial_id}:{flag}")
        except (KeyError, ValueError, ZeroDivisionError):
            parse_errors.append(trial_id)

    max_length_error = max(length_errors, default=float("inf"))
    length_ok = not parse_errors and max_length_error <= float(
        spec["maximum_relative_length_error"]
    )
    gates.append(
        _gate(
            "length-calibration",
            length_ok,
            "Measured pivot-to-center lengths satisfy the frozen tolerance."
            if length_ok
            else "Length measurements are missing or outside the frozen tolerance.",
            maximum_relative_error=max_length_error,
            allowed=float(spec["maximum_relative_length_error"]),
        )
    )

    max_angle = max(angles, default=float("inf"))
    angle_ok = not parse_errors and max_angle <= float(spec["maximum_starting_angle_deg"])
    gates.append(
        _gate(
            "small-angle-boundary",
            angle_ok,
            "Every trial is inside the registered small-angle range."
            if angle_ok
            else "At least one trial exceeds the registered starting angle.",
            maximum_angle_deg=max_angle,
            allowed_deg=float(spec["maximum_starting_angle_deg"]),
        )
    )

    max_damping = max(amplitude_losses, default=float("inf"))
    damping_ok = (
        not parse_errors
        and not amplitude_growth_ids
        and max_damping <= float(spec["maximum_amplitude_loss_fraction"])
    )
    gates.append(
        _gate(
            "damping-boundary",
            damping_ok,
            "Observed amplitude loss satisfies the frozen damping bound."
            if damping_ok
            else "At least one trial exceeds the frozen damping bound.",
            maximum_amplitude_loss_fraction=max_damping,
            allowed=float(spec["maximum_amplitude_loss_fraction"]),
            amplitude_growth_trial_ids=amplitude_growth_ids,
        )
    )

    exclusions_by_length = Counter(target for _, target, _ in excluded)
    included_by_length = Counter(target for target, _, _ in samples)
    exclusion_ok = (
        not unregistered_flags
        and len(excluded) <= int(spec["maximum_exclusions_total"])
        and max(exclusions_by_length.values(), default=0)
        <= int(spec["maximum_exclusions_per_length"])
        and all(
            included_by_length[float(length)] >= int(spec["minimum_included_per_length"])
            for length in spec["lengths_m"]
        )
    )
    gates.append(
        _gate(
            "exclusion-compliance",
            exclusion_ok,
            "Only contemporaneously flagged exclusions were applied within fixed limits."
            if exclusion_ok
            else "Exclusion flags, counts, or retained observations violate the protocol.",
            excluded_trials=[trial_id for trial_id, _, _ in excluded],
            exclusions_by_length=dict(sorted(exclusions_by_length.items())),
            unregistered_flags=unregistered_flags,
            included_by_length=dict(sorted(included_by_length.items())),
        )
    )

    timing_ok = (
        not parse_errors
        and periods
        and all(0.2 <= period <= 5.0 for period in periods)
    )
    gates.append(
        _gate(
            "timing-sanity",
            bool(timing_ok),
            "All durations are positive and yield periods inside the broad sanity range."
            if timing_ok
            else "Timing values are missing, nonpositive, or outside the broad sanity range.",
            parse_error_trial_ids=parse_errors,
            minimum_period_s=min(periods, default=None),
            maximum_period_s=max(periods, default=None),
        )
    )

    expected_audits = int(spec["blocks"])
    max_audit_error = max(timing_audit_errors, default=float("inf"))
    audit_ok = (
        len(timing_audit_errors) == expected_audits
        and not missing_timing_audits
        and max_audit_error <= float(spec["maximum_timing_repeatability_error_s"])
    )
    gates.append(
        _gate(
            "timing-repeatability",
            audit_ok,
            "All prespecified blind repeat extractions satisfy the timing tolerance."
            if audit_ok
            else "Timing audit coverage or repeatability does not satisfy the protocol.",
            expected_audit_count=expected_audits,
            completed_audit_count=len(timing_audit_errors),
            missing_audit_trial_ids=missing_timing_audits,
            maximum_period_difference_s=max_audit_error,
            allowed_s=float(spec["maximum_timing_repeatability_error_s"]),
        )
    )

    current_code_hash = analysis_code_hash(spec_path)
    expected_code_hash = str(protocol_summary["analysis_code_hash"])
    code_ok = current_code_hash == expected_code_hash
    gates.append(
        _gate(
            "analysis-code-integrity",
            code_ok,
            "Current analysis sources match the hash frozen in the protocol."
            if code_ok
            else "Current analysis sources differ from the frozen protocol hash.",
            expected_sha256=expected_code_hash,
            actual_sha256=current_code_hash,
        )
    )

    primary: dict[str, Any] | None = None
    independent: dict[str, Any] | None = None
    analysis_errors: list[str] = []
    try:
        primary = _fit_candidate_models(samples)
    except (ValueError, ZeroDivisionError) as exc:
        analysis_errors.append(f"primary: {exc}")
    try:
        independent = classify_from_files(
            clock_calibration_path=clock_path,
            observations_path=observations_path,
            allowed_exclusion_flags=allowed_flags,
        )
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        analysis_errors.append(f"independent: {exc}")
    analysis_complete = primary is not None and independent is not None
    gates.append(
        _gate(
            "analysis-complete",
            analysis_complete,
            "Both frozen analysis implementations produced complete results."
            if analysis_complete
            else "At least one frozen analysis implementation did not complete.",
            errors=analysis_errors,
        )
    )

    required_gate_ids = list(spec["required_quality_gates"])
    by_gate = {str(gate["gate_id"]): gate for gate in gates}
    exact_gate_set = set(by_gate) == set(required_gate_ids)
    quality_valid = exact_gate_set and all(
        by_gate[gate_id]["status"] == "passed" for gate_id in required_gate_ids
    )
    return {
        "schema_version": 1,
        "campaign_id": spec["campaign_id"],
        "physical_spec_sha256": sha256_file(spec_path),
        "protocol_id": protocol_summary["protocol_id"],
        "protocol_hash": protocol_summary["protocol_hash"],
        "synthetic": False,
        "execution_quality_valid": quality_valid,
        "quality_gates": gates,
        "primary_analysis": primary,
        "independent_analysis": independent,
        "scientific_outcome": _scientific_outcome(
            primary, independent, spec, quality_valid
        ),
        "claim_ceiling": (
            "A valid result concerns only this apparatus and registered regime; it is "
            "not evidence for or against Universal Theory as a whole."
        ),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_analysis_package(
    kit_root: Path,
    dataset_id: str,
    output_root: Path,
    spec_path: Path = SPEC_PATH,
) -> dict[str, Any]:
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "analysis-report.json"
    report = analyze_field_run(kit_root, spec_path)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    protocol_summary = json.loads(
        (kit_root / "protocol-summary.json").read_text(encoding="utf-8")
    )
    session = json.loads((kit_root / "session.json").read_text(encoding="utf-8"))
    run_record = {
        "run_id": f"run-{session['session_id']}",
        "protocol_id": protocol_summary["protocol_id"],
        "started_at": session["collection_started_at_utc"],
        "completed_at": session.get("analysis_completed_at_utc") or _utc_now(),
        "analysis_code_hash": analysis_code_hash(spec_path),
        "environment_hash": environment_hash(),
        "random_seed_reveal": protocol_summary["random_seed_reveal"],
        "dataset_ids": [dataset_id],
        "output_artifacts": [
            {
                "locator": report_path.name,
                "sha256": sha256_file(report_path),
                "size_bytes": report_path.stat().st_size,
                "media_type": "application/json",
                "metadata": {"artifact_role": "physical_analysis_report"},
            }
        ],
        "quality_gates": report["quality_gates"],
        "summary": report["scientific_outcome"]["summary"],
        "synthetic": False,
        "metadata": {
            "campaign_id": report["campaign_id"],
            "scientific_outcome": report["scientific_outcome"],
            "claim_ceiling": report["claim_ceiling"],
        },
    }
    record_path = output_root / "run-record.json"
    record_path.write_text(
        json.dumps(run_record, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return {
        "analysis_report_path": str(report_path.resolve()),
        "run_record_path": str(record_path.resolve()),
        "run_record_sha256": sha256_file(record_path),
        "execution_quality_valid": report["execution_quality_valid"],
        "scientific_outcome": report["scientific_outcome"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=SPEC_PATH)
    args = parser.parse_args()
    result = write_analysis_package(
        args.kit.resolve(),
        args.dataset_id,
        args.output.resolve(),
        args.spec.resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["execution_quality_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
