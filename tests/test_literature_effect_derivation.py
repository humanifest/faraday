"""Synthetic arm summaries test reproducible arithmetic, not source truth."""
import hashlib
import json
import math

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.effect_derivation import derive_effect_records
from tests.test_literature_effects import artifacts


def update_measure(plan, measure):
    value = json.loads(plan.read_text()); value["effect_measure"] = measure
    value["contrast_definition"] = "experimental versus comparator"
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode(); plan.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def summaries(measure="mean_difference"):
    if measure == "mean_difference":
        arms = ({"sample_size": 25, "mean": 4.0, "standard_deviation": 2.0},
                {"sample_size": 25, "mean": 3.0, "standard_deviation": 1.0})
    else:
        arms = ({"sample_size": 100, "events": 20}, {"sample_size": 100, "events": 10})
    return {"reviewer": "Summary reviewer", "records": [
        {"study_id": "study-1", "status": "available", "reason": "Reported arms",
         "evidence_location": "table 1", "experimental": arms[0], "comparator": arms[1]},
        {"study_id": "study-2", "status": "unavailable", "reason": "No compatible outcome",
         "evidence_location": "results", "experimental": None, "comparator": None}]}


def test_mean_difference_cli_recomputes_estimate_and_variance(tmp_path, capsys):
    plan, _, extraction, evidence_map, map_sha = artifacts(tmp_path)
    plan_sha = update_measure(plan, "mean_difference")
    summary_path = tmp_path / "summaries.json"; summary_path.write_text(json.dumps(summaries()))
    output = tmp_path / "effects"
    assert main(["--json", "literature", "derive-effects", "--plan-file", str(plan),
        "--expected-plan-sha256", plan_sha, "--extraction-file", str(extraction),
        "--evidence-map-file", str(evidence_map), "--expected-evidence-map-sha256", map_sha,
        "--summaries-file", str(summary_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["records"][0]["estimate"] == pytest.approx(1.0)
    assert result["records"][0]["standard_error"] == pytest.approx(math.sqrt(0.2))
    assert result["derivation_scope"].startswith("recomputed")
    persisted = json.loads((output / "effect-records.json").read_text())
    assert persisted["derivation_scope"] == result["derivation_scope"]
    assert persisted["contrast_definition"] == "experimental versus comparator"
    assert persisted["source_summaries"] == summaries()["records"]


def test_log_risk_ratio_is_recomputed_without_continuity_correction(tmp_path):
    plan, _, extraction, evidence_map, map_sha = artifacts(tmp_path)
    plan_sha = update_measure(plan, "log_risk_ratio")
    result = derive_effect_records(plan, plan_sha, extraction, evidence_map, map_sha,
                                   summaries("log_risk_ratio"), tmp_path / "effects")
    assert result["records"][0]["estimate"] == pytest.approx(math.log(2))


@pytest.mark.parametrize("failure", ["unsupported", "zero-events", "events-over-n", "negative-sd", "arm-shape", "unavailable-arm"])
def test_invalid_or_undeclared_derivation_never_publishes(tmp_path, failure):
    plan, _, extraction, evidence_map, map_sha = artifacts(tmp_path)
    measure = "mean_difference" if failure in {"negative-sd", "arm-shape", "unavailable-arm"} else "log_risk_ratio"
    plan_sha = update_measure(plan, "odds_ratio" if failure == "unsupported" else measure)
    candidate = summaries(measure)
    if failure == "zero-events": candidate["records"][0]["experimental"]["events"] = 0
    elif failure == "events-over-n": candidate["records"][0]["experimental"]["events"] = 101
    elif failure == "negative-sd": candidate["records"][0]["experimental"]["standard_deviation"] = -1
    elif failure == "arm-shape": candidate["records"][0]["experimental"]["extra"] = 1
    elif failure == "unavailable-arm": candidate["records"][1]["experimental"] = {}
    output = tmp_path / "effects"
    with pytest.raises(ValidationError):
        derive_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize(("field", "expected"), [
    ("plan", "A" * 64),
    ("map", "g" * 64),
])
def test_effect_derivation_rejects_malformed_expected_hashes(tmp_path, field, expected):
    plan, _, extraction, evidence_map, map_sha = artifacts(tmp_path)
    plan_sha = update_measure(plan, "mean_difference")
    if field == "plan":
        plan_sha = expected
        message = "expected_plan_sha256 must be a lowercase SHA-256 digest"
    else:
        map_sha = expected
        message = "expected_evidence_map_sha256 must be a lowercase SHA-256 digest"
    output = tmp_path / "effects"
    with pytest.raises(ValidationError, match=message):
        derive_effect_records(plan, plan_sha, extraction, evidence_map, map_sha, summaries(), output)
    assert not output.exists()
