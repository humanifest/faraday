"""Reproduce supported effect measures from source-reported arm summaries."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from research_machine.domain.errors import ValidationError
from research_machine.literature.effects import create_effect_records, _load
from research_machine.literature.snapshot import _text


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{field} must be a positive integer")
    return value


def _finite(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValidationError(f"{field} must be finite numeric data")
    if positive and value <= 0:
        raise ValidationError(f"{field} must be positive")
    return float(value)


def derive_effect_records(plan_path: Path, expected_plan_sha256: str, extraction_path: Path,
                          evidence_map_path: Path, expected_evidence_map_sha256: str,
                          summaries: dict[str, Any], output: Path) -> dict[str, Any]:
    plan, plan_sha = _load(plan_path, "synthesis plan")
    if plan_sha != expected_plan_sha256:
        raise ValidationError("effect derivation plan does not match the expected SHA-256")
    measure = plan.get("effect_measure")
    if measure not in {"mean_difference", "log_risk_ratio"}:
        raise ValidationError("reproducible derivation currently supports mean_difference and log_risk_ratio")
    contrast = plan.get("contrast_definition")
    if not isinstance(contrast, str) or not contrast.strip() or contrast == "not_applicable":
        raise ValidationError("effect derivation requires a frozen contrast_definition")
    if not isinstance(summaries, dict) or set(summaries) != {"reviewer", "records"}:
        raise ValidationError("effect summaries require exactly reviewer and records")
    reviewer = _text(summaries["reviewer"], "effect derivation reviewer")
    records = summaries["records"]
    if not isinstance(records, list):
        raise ValidationError("effect summary records must be an array")
    derived = []
    required = {"study_id", "status", "reason", "evidence_location", "experimental", "comparator"}
    for item in records:
        if not isinstance(item, dict) or set(item) != required:
            raise ValidationError("effect summary fields do not match the documented contract")
        status = item["status"]
        common = {"study_id": item["study_id"], "status": status, "reason": item["reason"],
                  "effect_measure": measure, "evidence_location": item["evidence_location"]}
        if status == "unavailable":
            if item["experimental"] is not None or item["comparator"] is not None:
                raise ValidationError("unavailable effect summaries require null arms")
            derived.append({**common, "estimate": None, "standard_error": None,
                            "sample_size": None, "derivation": "Unavailable; no imputation performed"})
            continue
        if status != "available" or not isinstance(item["experimental"], dict) or not isinstance(item["comparator"], dict):
            raise ValidationError("available effect summaries require experimental and comparator objects")
        experimental, comparator = item["experimental"], item["comparator"]
        if measure == "mean_difference":
            fields = {"sample_size", "mean", "standard_deviation"}
            if set(experimental) != fields or set(comparator) != fields:
                raise ValidationError("mean-difference arms require sample_size, mean, and standard_deviation")
            n1 = _positive_integer(experimental["sample_size"], "experimental sample_size")
            n0 = _positive_integer(comparator["sample_size"], "comparator sample_size")
            m1, m0 = _finite(experimental["mean"], "experimental mean"), _finite(comparator["mean"], "comparator mean")
            sd1 = _finite(experimental["standard_deviation"], "experimental standard_deviation", positive=True)
            sd0 = _finite(comparator["standard_deviation"], "comparator standard_deviation", positive=True)
            estimate = m1 - m0; standard_error = math.sqrt(sd1 ** 2 / n1 + sd0 ** 2 / n0)
            derivation = "experimental_mean - comparator_mean; SE=sqrt(sd_experimental^2/n_experimental + sd_comparator^2/n_comparator)"
        else:
            fields = {"sample_size", "events"}
            if set(experimental) != fields or set(comparator) != fields:
                raise ValidationError("log-risk-ratio arms require sample_size and events")
            n1 = _positive_integer(experimental["sample_size"], "experimental sample_size")
            n0 = _positive_integer(comparator["sample_size"], "comparator sample_size")
            e1 = _positive_integer(experimental["events"], "experimental events")
            e0 = _positive_integer(comparator["events"], "comparator events")
            if e1 > n1 or e0 > n0:
                raise ValidationError("events cannot exceed arm sample_size")
            estimate = math.log((e1 / n1) / (e0 / n0))
            standard_error = math.sqrt(1 / e1 - 1 / n1 + 1 / e0 - 1 / n0)
            if standard_error <= 0:
                raise ValidationError("log-risk-ratio standard error is not positive")
            derivation = "log((events_experimental/n_experimental)/(events_comparator/n_comparator)); no continuity correction"
        derived.append({**common, "estimate": estimate, "standard_error": standard_error,
                        "sample_size": n1 + n0, "derivation": derivation})
    return create_effect_records(
        plan_path, expected_plan_sha256, extraction_path, evidence_map_path,
        expected_evidence_map_sha256, {"reviewer": reviewer, "records": derived}, output,
        derivation_scope="recomputed_from_source_reported_arm_summaries",
        contrast_definition=contrast,
        source_summaries=records,
    )
