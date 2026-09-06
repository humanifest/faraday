"""Synthetic workflow fixtures, not scientific evidence."""
import json

import pytest

from research_machine.application.commands import CreateInquiry, ProposeHypothesis
from research_machine.design.revision import revise_design
from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from test_service import make_service


def test_revision_cli_preserves_original_and_retains_audited_brief(tmp_path, capsys):
    service = make_service(tmp_path / "workspace")
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Fixture question"))
    original = service.propose_hypothesis(ProposeHypothesis(
        statement="Fixture prediction", observable_prediction="Higher score",
        null_model="No difference", falsification_conditions=["Lower score"],
    ))
    service.activate_hypothesis(original.hypothesis_id)
    before = {p: p.read_bytes() for p in (tmp_path / "workspace").rglob("*.json")}
    brief = {"title": "Revised fixture", "question": "Different question",
             "decision": "Choose design", "outcome": "score", "unit_of_observation": "unit",
             "primary_estimand": "Mean score difference, A minus B.",
             "contrast_definition": "A minus B",
             "contrast_groups": ["A", "B"],
             "expected_effect_direction": "negative"}
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief))
    assert main(["--workspace", str(tmp_path / "workspace"), "--json", "design", "revise",
                 "--brief-file", str(path), "--hypothesis", original.hypothesis_id,
                 "--reason", "Narrow the outcome before collection"]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    revised = result["hypothesis"]
    assert revised["workflow_state"] == "unreviewed"
    assert revised["lineage"] == [original.hypothesis_id]
    assert revised["hypothesis_id"] != original.hypothesis_id
    assert revised["primary_estimand"] == brief["primary_estimand"]
    assert revised["contrast_definition"] == brief["contrast_definition"]
    assert revised["contrast_groups"] == ["A", "B"]
    assert revised["expected_effect_direction"] == "negative"
    assert not revised["activated_at"]
    provenance = json.loads(revised["source_context"][0])
    assert provenance["brief"] == brief
    assert provenance["scaffold"] == result["scaffold"]
    assert provenance["reason"] == "Narrow the outcome before collection"
    assert provenance["chronology"] == result["chronology"]
    assert result["chronology"]["observation_exposure"] == "unknown"
    assert all(p.read_bytes() == content for p, content in before.items())
    assert service.verify_ledger()["valid"]


def test_revision_retains_prior_run_chronology(tmp_path):
    from test_execution import prepared_service, frozen_formal_protocol, run_command
    from research_machine.domain.models import QualityGateStatus
    service, parent = prepared_service(tmp_path)
    protocol = frozen_formal_protocol(service, parent)
    run = service.record_run(run_command(protocol.protocol_id, QualityGateStatus.PASSED, synthetic=True))
    result = revise_design(service, {
        "title": "Fixture", "question": "Revised question", "decision": "Decision",
        "outcome": "Score", "unit_of_observation": "unit",
    }, hypothesis_id=parent, reason="Outcome-informed exploratory revision")
    chronology = result["chronology"]
    assert chronology["prior_records"]["runs"] == [run.run_id]
    assert chronology["prior_records"]["protocols"] == [protocol.protocol_id]
    assert chronology["observation_exposure"] == "unknown"
    assert result["hypothesis"]["workflow_state"] == "unreviewed"
    assert service.verify_ledger()["valid"]


@pytest.mark.parametrize("cancel", [False, True])
def test_interactive_revision_and_cancellation(tmp_path, monkeypatch, capsys, cancel):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    answers = iter(["Changed measurement", "Fixture", "Question", "Decision", "Score", "unit", "exploratory", "no"] + [""] * 50)
    def answer():
        if cancel:
            raise EOFError
        return next(answers)
    monkeypatch.setattr("builtins.input", answer)
    code = main(["--workspace", str(tmp_path), "--json", "design", "interview",
                 "--revise-hypothesis", parent.hypothesis_id])
    captured = capsys.readouterr()
    if cancel:
        assert code == 2
        assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    else:
        assert code == 0
        revised = json.loads(captured.out)["result"]["revision"]["hypothesis"]
        assert revised["workflow_state"] == "unreviewed"
        assert revised["lineage"] == [parent.hypothesis_id]
        assert json.loads(revised["source_context"][0])["reason"] == "Changed measurement"
    assert service.verify_ledger()["valid"]


@pytest.mark.parametrize("parent,reason", [("unknown", "Revision"), ("unknown", " ")])
def test_invalid_revision_does_not_write(tmp_path, parent, reason):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValidationError):
        revise_design(service, {"title": "Fixture", "question": "Question", "decision": "Decision",
                      "outcome": "Score", "unit_of_observation": "unit"},
                      hypothesis_id=parent, reason=reason)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert service.verify_ledger()["valid"]
