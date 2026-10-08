"""G09 public journey and adverse guards on disposable synthetic state."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.check_ai_science_guide_goal import FIXTURES, run_journey
from research_machine.application.guide import preview_csv_data
from research_machine.domain.errors import ValidationError


def test_public_journey_audit_ledger_and_replay(tmp_path: Path) -> None:
    result = run_journey(tmp_path)
    assert result["fixture_id"] == "guide-independent-v1"
    assert result["method"] == "independent_mean_difference_ci"
    assert result["audit_errors"] == 0
    assert result["replay_stable"] is True
    assert len(result["report_sha256"]) == 64
    assert len(result["ledger_head"]) == 64


def test_no_usable_data_and_failed_quality_gate_block_readiness(tmp_path: Path) -> None:
    spec = {
        "method": "independent_mean_difference_ci", "study_design": "independent_groups",
        "unit_column": "unit", "group_column": "group", "outcome_column": "outcome",
        "groups": ["treatment", "control"],
        "measurement_definitions": [{
            "measurement_id": "synthetic-outcome-v1", "data_column": "outcome",
            "scale_type": "interval", "unit": "synthetic points",
            "admissible_values": [], "missing_value_codes": ["<blank>"],
            "valid_min": 0.0, "valid_max": 100.0,
        }],
    }
    empty = tmp_path / "empty.csv"
    empty.write_text("unit,group,outcome\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        preview_csv_data(empty, spec)

    duplicate = tmp_path / "duplicate.csv"
    original = (FIXTURES / "independent-two-group.csv").read_bytes()
    duplicate.write_bytes(original.replace(b"u04,treatment,6", b"u01,treatment,6"))
    preview = preview_csv_data(duplicate, spec)
    assert "repeated independent-unit identifiers" in preview["quality_issues"]
    assert "data_quality_issues" in preview["readiness_gaps"]
    assert preview["scientific_evidence_eligible"] is False
    with pytest.raises(ValidationError, match="expected SHA-256"):
        preview_csv_data(duplicate, spec, expected_sha256=hashlib.sha256(original).hexdigest())
