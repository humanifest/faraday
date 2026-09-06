from __future__ import annotations

import json
from pathlib import Path

from research_machine.interfaces.cli import main
import pytest
from research_machine.application.service import ResearchService
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.domain.errors import ValidationError


def test_initializer_creates_isolated_workspace_with_unreviewed_hypothesis(
    tmp_path: Path, capsys
) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({
        "title": "Light trial", "question": "Does blue light alter height?",
        "decision": "Choose a light.", "outcome": "height",
        "unit_of_observation": "pot", "controls": [], "confounds": [],
        "primary_estimand": "Mean height difference, blue minus white.",
        "contrast_definition": "blue minus white",
        "contrast_groups": ["blue", "white"],
        "expected_effect_direction": "positive",
    }), encoding="utf-8")
    destination = tmp_path / "light-trial"
    assert main(["--json", "design", "initialize", "--brief-file", str(brief), "--output", str(destination)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["hypothesis_state"] == "unreviewed"
    assert result["git_initialized"] is True
    assert (destination / ".git").is_dir()
    assert (destination / ".research" / "workspace.json").is_file()
    state = json.loads((destination / "experiment-machine.json").read_text())
    assert state["hypothesis_state"] == "unreviewed"
    assert (destination / "drafts" / "protocol-draft.json").is_file()
    service = ResearchService(FileSystemRepository(destination / ".research"), actor="test")
    hypothesis = service.get_hypothesis(result["hypothesis_id"])
    assert hypothesis.primary_estimand == "Mean height difference, blue minus white."
    assert hypothesis.contrast_definition == "blue minus white"
    assert hypothesis.contrast_groups == ["blue", "white"]
    assert hypothesis.expected_effect_direction == "positive"
    ledger = next((destination / ".research").rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    with pytest.raises(ValidationError, match="unresolved scaffold placeholder"):
        service.activate_hypothesis(result["hypothesis_id"])
    with pytest.raises(ValidationError, match="unresolved scaffold placeholder"):
        service.stage_hypothesis(result["hypothesis_id"], "Fixture review", "high")
    assert ledger.read_bytes() == before
    assert service.verify_ledger()["valid"]
