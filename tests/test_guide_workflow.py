"""W04 public workflow replay and fixture-drift rejection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_ai_science_guide_workflow as workflow


def test_public_workflow_replays_without_canonical_state(tmp_path: Path) -> None:
    result = workflow.run_workflow(tmp_path)
    assert result["fixture_id"] == "guide-workflow-independent-v1"
    assert result["replay_stable"] is True
    assert result["canonical_write_performed"] is False
    assert result["scientific_evidence_eligible"] is False
    assert len(result["packet_sha256"]) == 64
    assert len(result["explanation_sha256"]) == 64
    assert len(result["receipt_sha256"]) == 2
    assert not (tmp_path / "workspace").exists()


def test_design_drift_blocks_workflow_before_output(tmp_path: Path, monkeypatch) -> None:
    fixture = json.loads(workflow.WORKFLOW_INPUTS.read_text(encoding="utf-8"))
    fixture["design"]["outcome_scale"] = "ordinal"
    drifted = tmp_path / "drifted-fixture.json"
    drifted.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(workflow, "WORKFLOW_INPUTS", drifted)
    with pytest.raises(RuntimeError, match="guide preparation was incomplete"):
        workflow.run_workflow(tmp_path)
    assert not (tmp_path / "analysis-1").exists()
    assert not (tmp_path / "workspace").exists()
