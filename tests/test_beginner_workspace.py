"""Question-led notebook: preserve legacy saves and keep canvas notes non-authoritative."""
import copy
import pytest
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.service import ResearchService
from research_machine.application.commands import AddQuestion, CreateInquiry
from research_machine.application.beginner import (
    DECISIONS, INQUIRY_TITLE, start_inquiry, inspect_saved_inquiry, question_pathway, pathway,
)
from research_machine.application.beginner_workspace import WORKSPACE_FIELDS
from research_machine.application.rehearsal_drafts import RehearsalDraftStore, validate_draft


def draft():
    return {"statement": "What explains gaps between prime numbers?", "prediction": "Unresolved",
            "reflection": "No calculation has been run.", "rows": [{"id": "pair-1", "shade": "", "sun": ""}],
            "history": [], "inquiry_id": None, "saved_statement": None, "save_state": "draft",
            "workspace_notes": {"version": 1, "open": True, "approach": "model",
                                **{field: "" for field in WORKSPACE_FIELDS}}}


def test_any_question_uses_generic_intake_and_read_only_recovery(tmp_path):
    service = ResearchService(FileSystemRepository(tmp_path))
    service.init_workspace()
    question = "What explains gaps between prime numbers?"
    saved = start_inquiry(service, question)
    state = service.show_inquiry(saved["inquiry_id"])
    assert state["inquiry"]["title"] == INQUIRY_TITLE
    assert state["inquiry"]["initial_statement"] == question
    assert len(state["questions"]) == 7
    assert not any("surface-temperature instrument" in q["text"] for q in state["questions"])
    before = service.verify_ledger(saved["inquiry_id"])
    assert inspect_saved_inquiry(service, question, saved["inquiry_id"])["status"] == "matching_complete"
    assert service.verify_ledger(saved["inquiry_id"]) == before
    assert not state["hypotheses"] and not service.list_evidence(saved["inquiry_id"])
    assert question_pathway()["pathway_id"] == "question-led-investigation"
    assert pathway()["pathway_id"] == "shade-surface-temperature"  # Existing example retained.


def test_historical_shade_inquiry_still_recovers_without_rewriting(tmp_path):
    service = ResearchService(FileSystemRepository(tmp_path))
    service.init_workspace()
    original = "A preserved historical question?"
    inquiry = service.create_inquiry(CreateInquiry(title="Shade-temperature pathway v1 — review unresolved", initial_statement=original))
    for _, text in DECISIONS:
        service.add_question(AddQuestion(text), inquiry.inquiry_id)
    before = service.verify_ledger(inquiry.inquiry_id)
    assert inspect_saved_inquiry(service, original, inquiry.inquiry_id)["status"] == "matching_complete"
    assert service.verify_ledger(inquiry.inquiry_id) == before
    assert service.show_inquiry(inquiry.inquiry_id)["inquiry"]["title"] == "Shade-temperature pathway v1 — review unresolved"


def test_workspace_and_corrections_survive_server_reopen(tmp_path):
    value = draft()
    value["workspace_notes"]["model_relation"] = "An initial proposed relation."
    earlier = {k: copy.deepcopy(v) for k, v in value.items() if k not in {"history", "inquiry_id", "saved_statement", "save_state"}}
    value["history"] = [earlier]
    value["workspace_notes"]["model_relation"] = "A revised proposed relation."
    store = RehearsalDraftStore(tmp_path, "a" * 64)
    saved = store.save(0, value)
    restored = RehearsalDraftStore(tmp_path, "a" * 64).load()
    assert restored == saved
    assert restored["draft"]["history"][0]["workspace_notes"]["model_relation"] == "An initial proposed relation."
    assert restored["draft"]["workspace_notes"]["model_relation"] == "A revised proposed relation."
    assert restored["scientific_evidence_eligible"] is False
    assert {p.name for p in tmp_path.iterdir()} == {"rehearsal-drafts.sqlite3"}


@pytest.mark.parametrize("mutation", [
    {"version": True}, {"open": "yes"}, {"approach": "approved"}, {"approval": True},
    {"model_relation": "x" * 2001}, {"source_supports": ["not text"]},
])
def test_invalid_or_authority_bearing_workspace_never_writes(tmp_path, mutation):
    value = draft();value["workspace_notes"].update(mutation)
    with pytest.raises(ValueError):
        RehearsalDraftStore(tmp_path, "a" * 64).save(0, value)
    assert list(tmp_path.iterdir()) == []


def test_legacy_draft_stays_unchanged_and_new_ui_is_question_led():
    value = draft();del value["workspace_notes"]
    assert validate_draft(value) == value
    from html.parser import HTMLParser
    from research_machine.interfaces.beginner import PAGE
    class Page(HTMLParser):
        def __init__(self): super().__init__();self.ids = [];self.details = [];self.path = [];self.ancestors = {}
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                self.ids.append(attrs["id"]);self.ancestors[attrs["id"]] = list(self.path)
            if tag == "details":self.path.append(attrs.get("id"))
        def handle_endtag(self, tag):
            if tag == "details":self.path.pop()
    page=Page();page.feed(PAGE.read_text())
    assert len(page.ids) == len(set(page.ids))
    assert "optional-examples" in page.ancestors["simulation-prepare"]
    assert "optional-examples" not in page.ancestors["statement"]
    assert "advanced-tools" in page.ancestors["portable-replay"]
    assert {"workspace-start", "workspace-download", "route-model", "route-track", "route-sources"} <= set(page.ids)
