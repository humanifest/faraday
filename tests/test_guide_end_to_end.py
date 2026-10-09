"""G09 public journey and adverse guards on disposable synthetic state."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.check_ai_science_guide_goal import FIXTURES, run_journey
from scripts.check_ai_science_guide_capabilities import run_design_previews
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import AddQuestion, CreateInquiry
from research_machine.application.guide import preview_csv_data
from research_machine.application.service import ResearchService
from research_machine.domain.errors import ConflictError, ValidationError


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


def test_two_client_stale_guide_intent_requires_refresh(tmp_path: Path) -> None:
    workspace = tmp_path / "two-client-workspace"
    first = ResearchService(FileSystemRepository(workspace), actor="fixture-client-a")
    second = ResearchService(FileSystemRepository(workspace), actor="fixture-client-b")
    first.init_workspace()
    inquiry = first.create_inquiry(CreateInquiry(
        "Synthetic concurrency", "Which question comes next?",
        inquiry_id="synthetic-concurrency",
    ))
    stale_head = first.verify_ledger(inquiry.inquiry_id)["head_hash"]
    second.add_question(AddQuestion("The second client changes the inquiry."), inquiry.inquiry_id)

    before = first.repository.load_questions(inquiry.inquiry_id)
    with pytest.raises(ConflictError, match="stale ledger head"):
        first.require_guide_ledger_head(stale_head, inquiry.inquiry_id)
    assert first.repository.load_questions(inquiry.inquiry_id) == before

    refreshed_head = first.verify_ledger(inquiry.inquiry_id)["head_hash"]
    preflight = first.require_guide_ledger_head(refreshed_head, inquiry.inquiry_id)
    assert preflight["status"] == "current_for_preflight"
    assert preflight["atomic_write_guard"] is False
    assert preflight["canonical_write_performed"] is False
    first.add_question(AddQuestion("The first client uses the refreshed context."), inquiry.inquiry_id)
    assert len(first.repository.load_questions(inquiry.inquiry_id)) == 2
    assert first.verify_ledger(inquiry.inquiry_id)["valid"] is True


def test_capability_checker_replays_paired_and_observational_previews(tmp_path: Path) -> None:
    first = run_design_previews(tmp_path / "first")
    second = run_design_previews(tmp_path / "second")
    assert first == second
    assert first["paired"]["pair_count"] == 2
    assert first["paired"]["adverse_status"] == "blocked"
    assert first["observational"]["complete_case_exclusion_count"] == 1
    assert first["observational"]["causal_identification_verified"] is False
    assert first["canonical_write_performed"] is False
