"""Synthetic workflow fixtures, not scientific evidence."""
import json

import pytest

from research_machine.application.commands import CreateInquiry, ProposeHypothesis
from research_machine.design import revision as revision_module
from research_machine.design.revision import revise_design
from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from test_service import make_service


def _controlled_scenario(**overrides):
    scenario = {
        "scenario_id": "planted-signal-recovery",
        "purpose": (
            "Check whether the controlled harness recovers a planted "
            "association without upgrading the claim."
        ),
        "expected_observation": (
            "The planted association is reported as scoped support against "
            "the null fixture."
        ),
        "distinguishes_from": [
            "independent null fixture",
            "movement-confounded fixture",
        ],
        "failure_response": (
            "Keep the campaign below readiness and inspect measurement, "
            "timing, and analysis commitments."
        ),
        "claim_ceiling": (
            "Association readiness only; mechanism, adaptation, attribution, "
            "and intent remain unsupported."
        ),
    }
    scenario.update(overrides)
    return scenario


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


def test_revision_replays_controlled_acceptance_scenarios(tmp_path):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))
    brief = {
        "title": "Revised fixture",
        "question": "Question",
        "decision": "Decision",
        "outcome": "Score",
        "unit_of_observation": "unit",
        "controlled_acceptance_scenarios": [_controlled_scenario()],
    }

    result = revise_design(
        service,
        brief,
        hypothesis_id=parent.hypothesis_id,
        reason="Retain controlled readiness scenarios",
    )

    summary = result["controlled_acceptance_scenarios"]
    assert summary == {
        "status": "review_required",
        "scenario_count": 1,
        "artifact": (
            "scaffold.artifacts.controlled-acceptance-scenarios-draft.json"
        ),
        "scientific_evidence_eligible": False,
    }
    provenance = json.loads(result["hypothesis"]["source_context"][0])
    assert provenance["controlled_acceptance_scenarios"] == summary
    draft = result["scaffold"]["artifacts"][
        "controlled-acceptance-scenarios-draft.json"
    ]
    assert draft["status"] == "review_required"
    assert draft["scenarios"] == brief["controlled_acceptance_scenarios"]
    assert draft["scenario_count"] == 1
    assert draft["scientific_evidence_eligible"] is False
    assert service.verify_ledger()["valid"]


def test_revision_rejects_divergent_controlled_acceptance_draft_before_writing(
    tmp_path, monkeypatch
):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))
    brief = {
        "title": "Revised fixture",
        "question": "Question",
        "decision": "Decision",
        "outcome": "Score",
        "unit_of_observation": "unit",
        "controlled_acceptance_scenarios": [_controlled_scenario()],
    }
    original_scaffold = revision_module.scaffold_design

    def divergent_scaffold(revised_brief):
        scaffold = original_scaffold(revised_brief)
        draft = dict(
            scaffold["artifacts"]["controlled-acceptance-scenarios-draft.json"]
        )
        draft["scenarios"] = [
            _controlled_scenario(scenario_id="different-scenario")
        ]
        scaffold["artifacts"]["controlled-acceptance-scenarios-draft.json"] = draft
        return scaffold

    monkeypatch.setattr(
        revision_module, "scaffold_design", divergent_scaffold
    )
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    with pytest.raises(
        ValidationError, match="controlled acceptance scenarios draft"
    ):
        revision_module.revise_design(
            service,
            brief,
            hypothesis_id=parent.hypothesis_id,
            reason="Reject divergent controlled readiness scenarios",
        )

    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
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


def test_revision_records_guided_ambiguity_and_claim_boundaries(tmp_path):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))

    brief = {
        "title": "Revised fixture",
        "question": "Question",
        "decision": "Decision",
        "outcome": "Score",
        "unit_of_observation": "unit",
        "ambiguity_questions": [
            "Could an unmeasured setup difference explain the result?"
        ],
        "claim_boundaries": [
            {
                "statement": "The registered score measurement is usable.",
                "level": "measurement_validity",
                "scope": "This revised fixture measurement only.",
            },
            {
                "statement": "Condition is associated with score.",
                "level": "statistical_association",
                "scope": "This revised fixture contrast only.",
            },
        ],
    }

    result = revise_design(
        service,
        brief,
        hypothesis_id=parent.hypothesis_id,
        reason="Separate claim levels before review",
    )

    state = service.show_inquiry()
    assert any(
        question["text"] == (
            "[Guided revision ambiguity] "
            "Could an unmeasured setup difference explain the result?"
        )
        and question["status"] == "open"
        for question in state["questions"]
    )
    claim_by_statement = {
        claim["statement"]: claim for claim in state["claims"]
    }
    assert claim_by_statement[
        "The registered score measurement is usable."
    ]["level"] == "measurement_validity"
    assert claim_by_statement[
        "The registered score measurement is usable."
    ]["epistemic_layer"] == "unresolved"
    assert claim_by_statement[
        "Condition is associated with score."
    ]["disposition"] == "unresolved"
    provenance = json.loads(result["hypothesis"]["source_context"][0])
    assert provenance["brief"] == brief
    assert service.verify_ledger()["valid"]


def test_revision_updates_complete_canonical_inquiry_decision_boundary(tmp_path):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            title="Fixture",
            initial_statement="Question",
            decision_to_support="Original decision.",
            minimum_evidence="Original evidence threshold.",
            decision_change_criteria=["Original stopping observation."],
            decision_owner="original-owner",
        )
    )
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))

    brief = {
        "title": "Revised fixture",
        "question": "Question",
        "decision": "Choose the revised design.",
        "minimum_evidence": "A reviewed revision clears the support rule.",
        "decision_change_criteria": [
            "Stop if the registered falsifier appears.",
            "Defer if measurement validity is inconclusive.",
        ],
        "decision_owner": "revision-owner",
        "outcome": "Score",
        "unit_of_observation": "unit",
    }

    revise_design(
        service,
        brief,
        hypothesis_id=parent.hypothesis_id,
        reason="Revise the practical decision boundary",
    )

    inquiry = service.show_inquiry()["inquiry"]
    assert inquiry["decision_to_support"] == "Choose the revised design."
    assert (
        inquiry["minimum_evidence"]
        == "A reviewed revision clears the support rule."
    )
    assert inquiry["decision_change_criteria"] == [
        "Stop if the registered falsifier appears.",
        "Defer if measurement validity is inconclusive.",
    ]
    assert inquiry["decision_owner"] == "revision-owner"
    assert service.verify_ledger()["valid"]


def test_revision_leaves_incomplete_decision_boundary_as_review_material(tmp_path):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            title="Fixture",
            initial_statement="Question",
            decision_to_support="Original decision.",
            minimum_evidence="Original evidence threshold.",
            decision_change_criteria=["Original stopping observation."],
            decision_owner="original-owner",
        )
    )
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))

    result = revise_design(
        service,
        {
            "title": "Revised fixture",
            "question": "Question",
            "decision": "Choose the revised design.",
            "minimum_evidence": " Revised evidence threshold.",
            "decision_change_criteria": [
                "Stop if the registered falsifier appears."
            ],
            "decision_owner": "revision-owner",
            "outcome": "Score",
            "unit_of_observation": "unit",
        },
        hypothesis_id=parent.hypothesis_id,
        reason="Keep padded revision boundary review-only",
    )

    inquiry = service.show_inquiry()["inquiry"]
    assert inquiry["decision_to_support"] == "Original decision."
    assert inquiry["minimum_evidence"] == "Original evidence threshold."
    assert inquiry["decision_change_criteria"] == ["Original stopping observation."]
    assert inquiry["decision_owner"] == "original-owner"
    assert "INQUIRY_DECISION_BOUNDARY_NONCANONICAL" in {
        item["code"] for item in result["scaffold"]["findings"]
    }
    assert service.verify_ledger()["valid"]


def test_revision_rejects_duplicate_decision_boundary_before_writing(tmp_path):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(
        CreateInquiry(
            title="Fixture",
            initial_statement="Question",
            decision_to_support="Original decision.",
            minimum_evidence="Original evidence threshold.",
            decision_change_criteria=["Original stopping observation."],
            decision_owner="original-owner",
        )
    )
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    with pytest.raises(ValueError, match="duplicates an earlier criterion"):
        revise_design(
            service,
            {
                "title": "Revised fixture",
                "question": "Question",
                "decision": "Choose the revised design.",
                "minimum_evidence": "A reviewed revision clears the support rule.",
                "decision_change_criteria": [
                    "Stop if the registered falsifier appears.",
                    "stop if the registered falsifier appears.",
                ],
                "decision_owner": "revision-owner",
                "outcome": "Score",
                "unit_of_observation": "unit",
            },
            hypothesis_id=parent.hypothesis_id,
            reason="Reject duplicate decision boundary",
        )
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    inquiry = service.show_inquiry()["inquiry"]
    assert inquiry["decision_to_support"] == "Original decision."
    assert inquiry["decision_change_criteria"] == ["Original stopping observation."]
    assert service.verify_ledger()["valid"]


def test_revision_rejects_duplicate_claim_boundaries_before_writing(tmp_path):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    with pytest.raises(ValueError, match="duplicates an earlier claim boundary"):
        revise_design(
            service,
            {
                "title": "Revised fixture",
                "question": "Question",
                "decision": "Decision",
                "outcome": "Score",
                "unit_of_observation": "unit",
                "claim_boundaries": [
                    {
                        "statement": "The registered score measurement is usable.",
                        "level": "measurement_validity",
                        "scope": "This revised fixture measurement only.",
                    },
                    {
                        "statement": "the registered score measurement is usable.",
                        "level": "statistical_association",
                        "scope": "This revised fixture contrast only.",
                    },
                ],
            },
            hypothesis_id=parent.hypothesis_id,
            reason="Reject duplicate claim boundary",
        )
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert service.verify_ledger()["valid"]


def test_revision_rejects_duplicate_ambiguity_questions_before_writing(tmp_path):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    with pytest.raises(ValueError, match="duplicates an earlier ambiguity question"):
        revise_design(
            service,
            {
                "title": "Revised fixture",
                "question": "Question",
                "decision": "Decision",
                "outcome": "Score",
                "unit_of_observation": "unit",
                "ambiguity_questions": [
                    "Could an unmeasured setup difference explain the result?",
                    "could an unmeasured setup difference explain the result?",
                ],
            },
            hypothesis_id=parent.hypothesis_id,
            reason="Reject duplicate ambiguity question",
        )
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert service.verify_ledger()["valid"]


def test_revision_rejects_conflicting_data_availability_before_writing(tmp_path):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    with pytest.raises(ValueError, match="conflicts with an available data source"):
        revise_design(
            service,
            {
                "title": "Revised fixture",
                "question": "Question",
                "decision": "Decision",
                "outcome": "Score",
                "unit_of_observation": "unit",
                "available_data_sources": ["Instrument export retained as CSV."],
                "unavailable_data": ["instrument export retained as csv."],
            },
            hypothesis_id=parent.hypothesis_id,
            reason="Reject contradictory availability boundary",
        )
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert service.verify_ledger()["valid"]


def test_revision_rejects_duplicate_review_conditions_before_writing(tmp_path):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    with pytest.raises(ValueError, match="duplicates an earlier review condition"):
        revise_design(
            service,
            {
                "title": "Revised fixture",
                "question": "Question",
                "decision": "Decision",
                "outcome": "Score",
                "unit_of_observation": "participant",
                "human_participants": True,
                "independent_review": True,
                "independent_review_receipt": "IRB-001",
                "independent_review_decision": "approved_with_conditions",
                "independent_review_conditions": [
                    "Submit annual report.",
                    "submit annual report.",
                ],
            },
            hypothesis_id=parent.hypothesis_id,
            reason="Reject duplicated review conditions",
        )
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert service.verify_ledger()["valid"]


@pytest.mark.parametrize("cancel", [False, True])
def test_interactive_revision_and_cancellation(tmp_path, monkeypatch, capsys, cancel):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    parent = service.propose_hypothesis(ProposeHypothesis(statement="Fixture"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    answers = iter(["Changed measurement", "Fixture", "Question", "Decision", "Score", "unit", "exploratory", "no"] + [""] * 70)
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


@pytest.mark.parametrize(
    "parent,reason,match",
    [
        ("unknown", "Revision", None),
        ("unknown", " ", None),
        (None, " Padded revision reason ", "canonical"),
    ],
)
def test_invalid_revision_does_not_write(tmp_path, parent, reason, match):
    service = make_service(tmp_path)
    service.init_workspace()
    service.create_inquiry(CreateInquiry(title="Fixture", initial_statement="Question"))
    parent_id = service.propose_hypothesis(ProposeHypothesis(statement="Fixture")).hypothesis_id
    if parent is None:
        parent = parent_id
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    expectation = pytest.raises(ValidationError, match=match) if match else pytest.raises(ValidationError)
    with expectation:
        revise_design(service, {"title": "Fixture", "question": "Question", "decision": "Decision",
                      "outcome": "Score", "unit_of_observation": "unit"},
                      hypothesis_id=parent, reason=reason)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert service.verify_ledger()["valid"]
