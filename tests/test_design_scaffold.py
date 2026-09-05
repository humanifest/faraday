from __future__ import annotations

import json
from pathlib import Path

from research_machine.interfaces.cli import main


def test_human_causal_scaffold_fails_closed_until_safeguards_exist(tmp_path: Path, capsys) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({
        "title": "Bedtime and concentration", "question": "Does an earlier bedtime improve next-day concentration?",
        "decision": "Whether to recommend a bedtime intervention.", "study_type": "causal",
        "outcome": "Concentration score", "unit_of_observation": "participant-day",
        "human_participants": True, "controls": [], "confounds": [],
    }), encoding="utf-8")
    assert main(["--json", "design", "scaffold", "--brief-file", str(brief)]) == 0
    payload = json.loads(capsys.readouterr().out)["result"]
    assert payload["status"] == "blocked"
    codes = {finding["code"] for finding in payload["findings"]}
    assert {"HUMAN_CONSENT_MISSING", "HUMAN_PRIVACY_MISSING", "HUMAN_REVIEW_REQUIRED", "CAUSAL_COMPARISON_MISSING"} <= codes
    assert payload["artifacts"]["hypothesis-proposal.json"]["generated_by"] == "guided_experiment_scaffold"


def test_complete_nonhuman_scaffold_remains_review_only(tmp_path: Path, capsys) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({
        "title": "Seedling light trial", "question": "Does blue light change seedling height?", "decision": "Choose a greenhouse light.",
        "study_type": "causal", "intervention": "blue light", "comparison": "white light", "outcome": "height", "outcome_unit": "millimetres",
        "unit_of_observation": "independent pot", "sampling_plan": "Randomly sample pots from one tray.", "randomization_plan": "Randomize pots to light.",
        "controls": ["White-light control"], "confounds": ["Tray position"], "calibration_plan": "Verify light meter against a reference.",
        "measurement_validity": "Measure a marked stem with a calibrated ruler.", "analysis_commitment": "Estimate mean difference with a confidence interval.", "stopping_rule": "20 pots per arm.", "exclusions": [],
    }), encoding="utf-8")
    assert main(["--json", "design", "scaffold", "--brief-file", str(brief)]) == 0
    payload = json.loads(capsys.readouterr().out)["result"]
    assert payload["status"] == "review_required"
    assert "REVIEW REQUIRED" in payload["artifacts"]["protocol-draft.json"]["hypotheses_tested"][0]
    assert payload["artifacts"]["protocol-draft.json"]["measurement_custody_requirements"]


def test_human_scaffold_requires_review_receipt_not_only_boolean(tmp_path: Path, capsys) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({
        "title": "Reviewed human study", "question": "Does the intervention change the outcome?", "decision": "Whether to continue.",
        "study_type": "causal", "intervention": "registered intervention", "comparison": "registered control",
        "outcome": "score", "outcome_unit": "points", "unit_of_observation": "participant",
        "sampling_plan": "Fixed eligible sample.", "randomization_plan": "Random assignment.",
        "controls": ["Registered control"], "confounds": ["Baseline score"],
        "calibration_plan": "Check instrument against its reference.", "measurement_validity": "Validated instrument.",
        "analysis_commitment": "Registered mean comparison.", "stopping_rule": "Fixed sample.", "exclusions": [],
        "human_participants": True, "consent_plan": "Written consent.", "withdrawal_plan": "Withdrawal without penalty.",
        "privacy_plan": "Pseudonymous records.", "retention_deletion_plan": "Delete identifiers after retention.",
        "risk_description": "Low risk with escalation plan.", "independent_review": True,
    }), encoding="utf-8")
    assert main(["--json", "design", "scaffold", "--brief-file", str(brief)]) == 0
    payload = json.loads(capsys.readouterr().out)["result"]
    assert payload["status"] == "blocked"
    assert "HUMAN_REVIEW_RECEIPT_MISSING" in {item["code"] for item in payload["findings"]}
