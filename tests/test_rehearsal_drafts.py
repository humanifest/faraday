import copy
import json
import sqlite3
import stat
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread
import pytest
from research_machine.application.rehearsal_drafts import RehearsalDraftStore, DraftConflict
from research_machine.interfaces.beginner import make_handler

def draft(text="Synthetic draft"):
    return {"statement":text,"prediction":"","reflection":"","rows":[{"id":"pair-1","shade":"1e","sun":""}],
            "history":[],"inquiry_id":None,"saved_statement":None,"save_state":"draft"}

def test_drafts_survive_reopen_and_remain_outside_canonical_state(tmp_path):
    store=RehearsalDraftStore(tmp_path,"a"*64)
    assert store.load()["draft"] is None
    assert not list(tmp_path.iterdir())
    saved=store.save(0,draft())
    reopened=RehearsalDraftStore(tmp_path,"a"*64).load()
    assert reopened==saved and reopened["draft"]["rows"][0]["shade"]=="1e"
    assert reopened["scientific_evidence_eligible"] is False
    assert reopened["review_status"]=="unresolved"
    assert not (tmp_path/"workspace.json").exists()
    assert not (tmp_path/"inquiries").exists()
    assert stat.S_IMODE(store.path.stat().st_mode)==0o600

def test_versions_conflicts_and_lost_response_retry(tmp_path):
    store=RehearsalDraftStore(tmp_path,"a"*64)
    assert store.save(0,draft())["revision"]==1
    assert store.save(0,draft())["revision"]==1
    with pytest.raises(DraftConflict):
        store.save(0,draft("Different stale draft"))
    assert store.save(1,draft("Second draft"))["revision"]==2
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0]==2
    assert store.load()["draft"]["statement"]=="Second draft"
    assert RehearsalDraftStore(tmp_path,"b"*64).load()["draft"] is None

@pytest.mark.parametrize("extra", [
    {"review_status":"approved"}, {"scientific_evidence_eligible":True},
    {"rows":[{"id":"p","shade":True,"sun":""}]}, {"history":[None]}, {"save_state":"approved"},
])
def test_bad_drafts_fail_without_creating_storage(tmp_path,extra):
    value=draft();value.update(extra)
    with pytest.raises(ValueError): RehearsalDraftStore(tmp_path,"a"*64).save(0,value)
    assert not list(tmp_path.iterdir())

def test_symlinked_database_is_rejected(tmp_path):
    other=tmp_path/"unrelated";other.write_text("unchanged")
    (tmp_path/"rehearsal-drafts.sqlite3").symlink_to(other)
    with pytest.raises(ValueError): RehearsalDraftStore(tmp_path,"a"*64).save(0,draft())
    assert other.read_text()=="unchanged"

def test_authenticated_http_draft_restore_after_browser_storage_loss(tmp_path):
    server=HTTPServer(("127.0.0.1",0),make_handler(tmp_path,"test-token"))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    def post(path,value,authorized=True,origin=None):
        conn=HTTPConnection("127.0.0.1",server.server_port,timeout=5)
        headers={"Content-Type":"application/json"}
        if authorized:headers["X-Faraday-Token"]="test-token"
        if origin:headers["Origin"]=origin
        conn.request("POST",path,json.dumps(value),headers)
        response=conn.getresponse();result=response.status,json.loads(response.read())
        conn.close();return result
    try:
        assert post("/api/draft/save",{},False)[0]==403
        assert post("/api/draft/load",{},origin="https://other.example")[0]==403
        assert post("/api/draft/load",{})[1]["draft"] is None
        status,first=post("/api/draft/save",{"expected_revision":0,"draft":draft()})
        assert status==200 and first["revision"]==1
        # A brand-new browser session needs no stored draft ID or cookie to recover
        # this single-writer workspace's latest draft, only its page session token.
        status,restored=post("/api/draft/load",{})
        assert status==200 and restored["draft"]==draft()
        assert post("/api/draft/save",{"expected_revision":0,"draft":draft("stale")})[0]==409
        assert not (tmp_path/"workspace.json").exists()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)

def test_missing_workspace_is_not_silently_recreated(tmp_path):
    missing=tmp_path/"disconnected-volume"
    with pytest.raises(OSError):
        RehearsalDraftStore(missing,"a"*64).save(0,draft())
    assert not missing.exists()


def test_recording_context_is_optional_and_retains_originals_without_authority(tmp_path):
    store=RehearsalDraftStore(tmp_path,"c"*64)
    legacy=draft()
    assert "recording_notes" not in store.save(0,legacy)["draft"]
    value={**legacy,"recording_notes":"pair-1: source timezone unknown; sun unavailable.",
           "history":[{**legacy,"recording_notes":"Earlier: timing not recorded."}]}
    saved=store.save(1,value)
    assert RehearsalDraftStore(tmp_path,"c"*64).load()==saved
    assert saved["draft"]["recording_notes"]==value["recording_notes"]
    assert saved["draft"]["history"][0]["recording_notes"].startswith("Earlier")
    assert saved["scientific_evidence_eligible"] is False
    assert not (tmp_path/"workspace.json").exists()


@pytest.mark.parametrize("bad",[None,False,{},"x"*10001])
def test_bad_recording_context_is_rejected_before_storage(tmp_path,bad):
    for historical in (False,True):
        value=draft()
        if historical:value["history"]=[{**draft(),"recording_notes":bad}]
        else:value["recording_notes"]=bad
        with pytest.raises(ValueError):RehearsalDraftStore(tmp_path,"d"*64).save(0,value)
        assert not list(tmp_path.iterdir())
