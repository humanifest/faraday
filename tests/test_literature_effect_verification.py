"""Synthetic second review protects against transcribed or calculated errors."""
import hashlib
import json

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.effect_verification import create_effect_verification


def effects_file(tmp_path):
    value = {"effect_records_version": 1, "status": "effects_ready",
        "derivation_scope": "recomputed_from_source_reported_arm_summaries", "reviewer": "Effect reviewer",
        "plan_id": "p1", "snapshot_id": "snap", "source_summaries": [
            {"study_id": "s1", "status": "available"}, {"study_id": "s2", "status": "unavailable"}], "records": [
            {"study_id": "s1", "status": "available"}, {"study_id": "s2", "status": "unavailable"}]}
    encoded = (json.dumps(value, sort_keys=True) + "\n").encode(); path = tmp_path / "effects.json"; path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def review(match=True):
    return {"reviewer": "Independent checker", "assessments": [
        {"study_id": "s1", "source_values_match": match, "calculation_matches": True,
         "checked_location": "table 1", "rationale": "Checked source and arithmetic"},
        {"study_id": "s2", "source_values_match": None, "calculation_matches": None,
         "checked_location": "results", "rationale": "Confirmed unavailable"}]}


def test_effect_verification_cli_records_clean_independent_review(tmp_path, capsys):
    effects, digest = effects_file(tmp_path); review_path = tmp_path / "review.json"; review_path.write_text(json.dumps(review()))
    output = tmp_path / "verification"
    assert main(["--json", "literature", "verify-effects", "--effects-file", str(effects),
        "--expected-effects-sha256", digest, "--review-file", str(review_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["status"] == "effect_verification_recorded" and result["independent_review"] is True
    with pytest.raises(ValidationError, match="already exists"):
        create_effect_verification(effects, digest, review(), output)


def test_mismatch_is_preserved_and_requires_review(tmp_path):
    effects, digest = effects_file(tmp_path)
    result = create_effect_verification(effects, digest, review(False), tmp_path / "verification")
    assert result["status"] == "review_required" and result["mismatch_study_ids"] == ["s1"]


def test_effect_verification_normalizes_study_handles(tmp_path):
    effects, digest = effects_file(tmp_path)
    candidate = review()
    candidate["assessments"][0]["study_id"] = " s1 "
    result = create_effect_verification(effects, digest, candidate, tmp_path / "verification")
    assert result["assessments"][0]["study_id"] == "s1"


@pytest.mark.parametrize("failure", ["hash", "same-reviewer", "missing", "duplicate", "padded-duplicate", "summary-duplicate", "available-null", "unavailable-bool", "location"])
def test_invalid_effect_verification_never_publishes(tmp_path, failure):
    effects, digest = effects_file(tmp_path); candidate = review()
    if failure == "hash": digest = "0" * 64
    elif failure == "same-reviewer": candidate["reviewer"] = " effect REVIEWER "
    elif failure == "missing": candidate["assessments"].pop()
    elif failure == "duplicate": candidate["assessments"][1]["study_id"] = "s1"
    elif failure == "padded-duplicate": candidate["assessments"][1]["study_id"] = " s1 "
    elif failure == "summary-duplicate":
        value = json.loads(effects.read_text())
        value["source_summaries"][1]["study_id"] = " s1 "
        encoded = (json.dumps(value, sort_keys=True) + "\n").encode()
        effects.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
    elif failure == "available-null": candidate["assessments"][0]["source_values_match"] = None
    elif failure == "unavailable-bool": candidate["assessments"][1]["calculation_matches"] = True
    elif failure == "location": candidate["assessments"][0]["checked_location"] = ""
    output = tmp_path / "verification"
    with pytest.raises(ValidationError): create_effect_verification(effects, digest, candidate, output)
    assert not output.exists()
