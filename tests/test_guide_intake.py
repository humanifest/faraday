"""G02 literal intake and explicit routing into existing service commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.commands import AddQuestion, CreateInquiry
from research_machine.application.guide import preview_question_intake
from research_machine.application.service import ResearchService
from research_machine.interfaces.cli import main


def test_intake_preserves_question_and_requires_explicit_canonical_routing(tmp_path: Path, capsys) -> None:
    original = "Would the treatment change the measured outcome for these four synthetic units?"
    brief = {
        "original_statement": original,
        "title": "Synthetic treatment question",
        "population": "Four fabricated independent units only.",
        "decision": "Whether a later reviewed study is worth designing.",
    }
    brief_file = tmp_path / "brief.json"
    brief_file.write_text(json.dumps(brief), encoding="utf-8")
    workspace = tmp_path / "workspace"

    assert main([
        "--workspace", str(workspace), "--json", "guide", "intake",
        "--brief-file", str(brief_file),
    ]) == 0
    output = json.loads(capsys.readouterr().out)["result"]
    assert output["authority"] == "review_only"
    assert output["canonical_write_performed"] is False
    assert output["original_statement"] == original
    assert output["supplied_fields"]["population"] == brief["population"]
    assert output["supplied_fields"]["outcome"] is None
    assert output["supplied_fields"]["unit_of_observation"] is None
    assert "outcome" in output["unresolved_fields"]
    assert "ethical_constraints" in output["unresolved_fields"]
    assert not workspace.exists()

    commands = output["proposed_commands"]
    assert commands[0]["service_command"] == "CreateInquiry"
    assert commands[0]["arguments"]["initial_statement"] == original
    assert commands[0]["arguments"]["decision_to_support"] == brief["decision"]
    assert all(item["service_command"] == "AddQuestion" for item in commands[1:])

    # A separate, explicit service operation is required to write the preview.
    service = ResearchService(FileSystemRepository(workspace), actor="guide-fixture")
    service.init_workspace()
    service.create_inquiry(CreateInquiry(**commands[0]["arguments"]))
    for item in commands[1:]:
        service.add_question(AddQuestion(**item["arguments"]))
    state = service.show_inquiry()
    assert state["inquiry"]["initial_statement"] == original
    assert state["inquiry"]["decision_to_support"] == brief["decision"]
    assert len(state["questions"]) == len(commands) - 1
    assert all(item["status"] == "open" for item in state["questions"])
    assert service.verify_ledger()["valid"] is True


def test_intake_does_not_fill_missing_answers_or_invent_a_title() -> None:
    preview = preview_question_intake({"original_statement": "Could X matter?"})
    assert preview["supplied_fields"]["title"] is None
    assert preview["supplied_fields"]["outcome"] is None
    assert preview["proposed_commands"] == []
    assert len(preview["clarifying_questions"]) == len(preview["unresolved_fields"])

    with pytest.raises(ValueError, match="unknown guide intake fields"):
        preview_question_intake({
            "original_statement": "Could X matter?",
            "generated_outcome": "AI guessed an outcome",
        })
    with pytest.raises(ValueError, match="outcome must be non-blank"):
        preview_question_intake({"original_statement": "Could X matter?", "outcome": ""})
    with pytest.raises(ValueError, match="original_statement"):
        preview_question_intake({"original_statement": "  Could X matter?  "})
    with pytest.raises(ValueError, match="distinct statements"):
        preview_question_intake({
            "original_statement": "Could X matter?",
            "decision_change_criteria": ["Change", "change"],
        })
