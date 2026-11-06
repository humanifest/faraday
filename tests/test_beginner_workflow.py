"""Connected app client over real loopback service; simulated DOM, no browser claim."""
import json
from pathlib import Path
import shutil
import subprocess
from http.server import HTTPServer
from threading import Thread
import pytest
from research_machine.interfaces.beginner import make_handler, prepare_preview_workspace
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.service import ResearchService


@pytest.mark.parametrize("fresh", [False,True])
def test_actual_client_question_to_followup_without_hand_editing_json(tmp_path,fresh):
    node=shutil.which("node")
    if node is None:pytest.skip("Node.js is required for the actual-client integration fixture")
    workspace=tmp_path/"new-working-folder" if fresh else tmp_path
    if fresh:prepare_preview_workspace(workspace)
    server=HTTPServer(("127.0.0.1",0),make_handler(workspace,"workflow-fixture"))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=subprocess.run([node,"scripts/check_beginner_workflow.cjs",f"http://127.0.0.1:{server.server_port}/"],
                              capture_output=True,text=True,timeout=60,cwd=Path(__file__).resolve().parents[1])
        assert result.returncode==0,result.stderr
        proof=json.loads(result.stdout);assert proof["status"]=="passed" and proof["rendered_browser"] is False
        assert proof["portable_replay_recovered_after_reload"] is True and proof["portable_replay_requests"]==1
        assert proof["question_first_workspace_verified"] is True and proof["canvas_switch_preserved_computation"] is True
        service=ResearchService(FileSystemRepository(workspace));inquiry=proof["inquiry_id"]
        assert service.show_inquiry(inquiry)["inquiry"]["initial_statement"]==proof["original_question_preserved"]
        assert service.list_hypotheses(inquiry)[0].workflow_state.value=="unreviewed"
        assert service.list_protocols(inquiry)[0].status.value=="draft"
        assert service.verify_ledger(inquiry)["valid"] is True
        assert not service.list_datasets(inquiry) and not service.list_runs(inquiry) and not service.list_evidence(inquiry)
    finally:server.shutdown();server.server_close();thread.join()


def test_preview_preparation_is_private_nonrecursive_and_does_not_initialize_research_state(tmp_path):
    workspace=tmp_path/"chosen"
    prepare_preview_workspace(workspace)
    assert workspace.is_dir() and list(workspace.iterdir())==[]
    assert workspace.stat().st_mode & 0o777 == 0o700
    before=workspace.stat().st_mode;prepare_preview_workspace(workspace)
    assert workspace.stat().st_mode==before
    with pytest.raises(FileNotFoundError):prepare_preview_workspace(tmp_path/"absent-parent"/"chosen")
    assert not (tmp_path/"absent-parent").exists()


def test_primary_activity_uses_real_engine_without_advanced_routes(tmp_path):
    node=shutil.which("node")
    if node is None:pytest.skip("Node.js is required for the primary activity integration fixture")
    server=HTTPServer(("127.0.0.1",0),make_handler(tmp_path,"activity-fixture"));thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=subprocess.run([node,"scripts/check_beginner_workflow.cjs",f"http://127.0.0.1:{server.server_port}/","--activity"],capture_output=True,text=True,timeout=60,cwd=Path(__file__).resolve().parents[1])
        assert result.returncode==0,result.stderr
        proof=json.loads(result.stdout);assert proof["status"]=="passed" and proof["advanced_routes_used"]==[]
        service=ResearchService(FileSystemRepository(tmp_path));inquiry=proof["inquiry_id"]
        assert service.show_inquiry(inquiry)["inquiry"]["initial_statement"]==proof["original_question"]
        assert not service.list_hypotheses(inquiry) and not service.list_protocols(inquiry) and not service.list_evidence(inquiry)
    finally:server.shutdown();server.server_close();thread.join()
