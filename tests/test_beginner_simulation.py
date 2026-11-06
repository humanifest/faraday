"""Synthetic executor bridge: no real observations or canonical evidence."""
import pytest
from research_machine.application.beginner_simulation import SimulationWorkbench
from research_machine.domain.errors import ValidationError

@pytest.mark.parametrize("case", ["positive", "null", "negative", "missing", "invalid"])
def test_retained_recipe_inspection_is_read_only_and_does_not_initialize_canonical_state(tmp_path, case):
    work=SimulationWorkbench(tmp_path);plan=work.prepare(case)
    directory=work.root/plan["simulation_id"]
    before={path.name:path.read_bytes() for path in directory.iterdir()}
    assert work.inspect_recipe(plan["simulation_id"],plan["recipe_sha256"])==plan
    assert {path.name:path.read_bytes() for path in directory.iterdir()}==before
    assert list(tmp_path.iterdir())==[work.root]
    path=directory/"input.csv";path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValueError):work.inspect_recipe(plan["simulation_id"],plan["recipe_sha256"])
    assert not (directory/"execution").exists()


def test_http_retained_simulation_design_rechecks_bytes_and_exposes_only_bundled_method_identity(tmp_path):
    import json
    from http.client import HTTPConnection
    from http.server import HTTPServer
    from threading import Thread
    from research_machine.interfaces.beginner import make_handler
    from research_machine.application.beginner_computation import method_identity
    work=SimulationWorkbench(tmp_path);plan=work.prepare("positive")
    server=HTTPServer(("127.0.0.1",0),make_handler(tmp_path,"handoff-fixture"));thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(body,token=True):
        connection=HTTPConnection(*server.server_address);headers={"Content-Type":"application/json","Host":f"127.0.0.1:{server.server_port}"}
        if token:headers["X-Faraday-Token"]="handoff-fixture"
        connection.request("POST","/api/simulation/design",json.dumps(body),headers)
        response=connection.getresponse();value=json.loads(response.read());connection.close();return response.status,value
    body={"simulation_id":plan["simulation_id"],"recipe_sha256":plan["recipe_sha256"]}
    try:
        assert request(body,False)[0]==403
        assert request(body)==(200,{**plan,"method_identity":method_identity()})
        assert request({**body,"input_path":"/unapproved"})[0]==400
        path=work.root/plan["simulation_id"]/"analysis.json";path.write_bytes(path.read_bytes()+b" ")
        assert request(body)[0]==400
        assert not (work.root/plan["simulation_id"]/"execution").exists()
    finally:server.shutdown();server.server_close();thread.join()

@pytest.mark.parametrize(('case','effect'), [('positive',4),('negative',-4),('null',0)])
def test_native_execution_and_receipt_preserve_direction(tmp_path,case,effect):
    lab=SimulationWorkbench(tmp_path); plan=lab.prepare(case)
    assert not (tmp_path/'workspace.json').exists()
    result=lab.run(plan['simulation_id'],plan['recipe_sha256'])
    assert result['result']['result']['mean_difference_first_minus_second']==effect
    assert result['scientific_evidence_eligible'] is False
    import hashlib
    import json
    receipt = json.loads((lab.root/plan['simulation_id']/'execution'/'execution-receipt.json').read_text())
    assert result['method'] == receipt['method']
    assert result['implementation_sha256'] == receipt['implementation']['sha256']
    assert result['addon'] == receipt['addon']
    assert result['environment'] == receipt['environment']
    assert 'locator' not in result['environment']
    assert lab.verify(plan['simulation_id'],plan['recipe_sha256'],result['receipt_sha256'])==result
    output=lab.root/plan['simulation_id']/'execution'/'analysis-result.json'
    output.write_bytes(output.read_bytes()+b' ')
    with pytest.raises(ValidationError):lab.verify(plan['simulation_id'],plan['recipe_sha256'],result['receipt_sha256'])

def test_changed_inputs_and_invalid_reading_never_publish_result(tmp_path):
    lab=SimulationWorkbench(tmp_path);plan=lab.prepare('null')
    data=lab.root/plan['simulation_id']/'input.csv';data.write_bytes(data.read_bytes()+b'bad')
    with pytest.raises(ValueError):lab.run(plan['simulation_id'],plan['recipe_sha256'])
    assert not (data.parent/'execution').exists()
    bad=lab.prepare('invalid')
    with pytest.raises(ValidationError):lab.run(bad['simulation_id'],bad['recipe_sha256'])
    assert not (lab.root/bad['simulation_id']/'execution').exists()

def test_missingness_is_disclosed_and_unsafe_ids_rejected(tmp_path):
    lab=SimulationWorkbench(tmp_path);plan=lab.prepare('missing')
    result=lab.run(plan['simulation_id'],plan['recipe_sha256'])
    assert result['result']['result']['exclusion_report']['excluded_records']
    with pytest.raises(ValueError):lab.prepare('published-data')
    with pytest.raises(ValueError):lab.verify('../escape','x','y')


def test_http_session_scope_and_full_native_journey(tmp_path):
    import json
    from http.client import HTTPConnection
    from http.server import HTTPServer
    from threading import Thread
    from research_machine.interfaces.beginner import make_handler
    server=HTTPServer(("127.0.0.1",0),make_handler(tmp_path,"simulation-test"))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    def post(route,payload,authorized=True):
        conn=HTTPConnection("127.0.0.1",server.server_port,timeout=10)
        headers={"Content-Type":"application/json"}
        if authorized:headers["X-Faraday-Token"]="simulation-test"
        conn.request("POST","/api/simulation/"+route,json.dumps(payload),headers)
        response=conn.getresponse();answer=(response.status,json.loads(response.read()));conn.close();return answer
    try:
        assert post("prepare",{"case":"null"},False)[0]==403
        assert post("prepare",{"case":"null","approved":True})[0]==400
        assert not list(tmp_path.iterdir())
        status,plan=post("prepare",{"case":"null"});assert status==200
        selected={key:plan[key] for key in ("simulation_id","recipe_sha256")}
        status,result=post("run",selected);assert status==200
        assert result["result"]["result"]["mean_difference_first_minus_second"]==0
        assert post("verify",{**selected,"receipt_sha256":result["receipt_sha256"]})==(200,result)
        assert post("run",selected)[0]==400
        status,saved=post("canonical",selected);assert status==200
        assert saved["scientific_evidence_eligible"] is False and saved["evidence_count"]==0
        pins={key:saved[key] for key in ("simulation_id","recipe_sha256","report_sha256","package_manifest_sha256")}
        assert post("inspect",pins)[0]==200
        assert post("export",pins)[0]==200
        assert post("inspect",{**pins,"approved":True})[0]==400
        assert not (tmp_path/"workspace.json").exists()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def test_changed_contrast_and_untrusted_receipt_pin_fail(tmp_path):
    import json
    lab=SimulationWorkbench(tmp_path);plan=lab.prepare("positive")
    path=lab.root/plan["simulation_id"]/"analysis.json"
    changed=json.loads(path.read_text());changed["groups"].reverse();path.write_text(json.dumps(changed))
    with pytest.raises(ValueError):lab.run(plan["simulation_id"],plan["recipe_sha256"])
    assert not (path.parent/"execution").exists()
    other=lab.prepare("negative");lab.run(other["simulation_id"],other["recipe_sha256"])
    with pytest.raises(ValidationError):lab.verify(other["simulation_id"],other["recipe_sha256"],"0"*64)

@pytest.mark.parametrize('case',['positive','null','negative','missing','invalid'])
def test_canonical_synthetic_fixture_is_pending_and_never_evidence(tmp_path,case):
    lab=SimulationWorkbench(tmp_path);plan=lab.prepare(case)
    result=lab.canonical_fixture(plan['simulation_id'],plan['recipe_sha256'])
    assert result['scientific_evidence_eligible'] is False
    assert result['evidence_count']==0 and result['ledger']['valid']
    assert result['hypothesis_status']=='pending_review'
    assert "Pending human review" in result["report"]
    assert result["workspace_scope"]=="isolated_synthetic_fixture"
    assert len(result["package_manifest_sha256"])==64
    with pytest.raises(ValueError):lab.canonical_fixture(plan["simulation_id"],plan["recipe_sha256"])
    assert result['run_status']==('invalid' if case=='invalid' else 'completed')


def test_synthetic_canonical_run_cannot_be_admitted_as_empirical_evidence(tmp_path):
    import hashlib
    from research_machine.adapters.filesystem import FileSystemRepository
    from research_machine.application.commands import RecordEvidence
    from research_machine.application.service import ResearchService
    from research_machine.domain.models import EvidenceDirection, ValidationTag
    lab=SimulationWorkbench(tmp_path);plan=lab.prepare("positive")
    result=lab.canonical_fixture(plan["simulation_id"],plan["recipe_sha256"])
    root=lab.root/plan["simulation_id"]/"canonical-fixture"
    service=ResearchService(FileSystemRepository(root))
    hypothesis=service.list_hypotheses()[0]
    def inventory():return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    before=inventory()
    with pytest.raises(ValidationError):
        service.record_evidence(RecordEvidence(hypothesis_id=hypothesis.hypothesis_id,
            direction=EvidenceDirection.INCONCLUSIVE,summary="Adverse software test; this must not be empirical evidence.",
            analysis_id="synthetic-check",dataset_id=result["dataset_id"],run_id=result["run_id"],
            effect_estimate="4 synthetic degrees",uncertainty="Synthetic bootstrap only",scope="Synthetic software fixture only",
            higher_level_conclusions_unsupported=["Physical validity, causality and population generalization unsupported."],
            validation_tags=[ValidationTag.EMPIRICAL_TEST],exploratory=True))
    assert inventory()==before


def test_resume_and_private_export_reverify_exact_canonical_bytes(tmp_path):
    import base64,io,json,zipfile
    from research_machine.replication.package import verify_replication_package
    lab=SimulationWorkbench(tmp_path);plan=lab.prepare("null")
    saved=lab.canonical_fixture(plan["simulation_id"],plan["recipe_sha256"])
    pins={key:saved[key] for key in ("simulation_id","recipe_sha256","report_sha256","package_manifest_sha256")}
    before={str(p):p.read_bytes() for p in lab.root.rglob("*") if p.is_file()}
    assert SimulationWorkbench(tmp_path).inspect_canonical(**pins)["report"]==saved["report"]
    exported=lab.export_canonical(**pins)
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(exported["archive_base64"]))) as archive:
        assert str(tmp_path).encode() not in archive.read("simulation-report.md")
        assert json.loads(archive.read("recipe.json"))["data_classification"]=="synthetic"
        extracted=tmp_path/"verify-export";extracted.mkdir()
        for name in archive.namelist():
            if name.startswith("metadata/"):
                path=extracted/name.removeprefix("metadata/");path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(name))
        assert verify_replication_package(extracted,pins["package_manifest_sha256"])["status"]=="passed"
    assert {str(p):p.read_bytes() for p in lab.root.rglob("*") if p.is_file()}==before
    root=lab.root/plan["simulation_id"]/"canonical-fixture"
    report=next(root.rglob("current-synthesis.md"));report.write_text("changed")
    with pytest.raises(ValueError):lab.inspect_canonical(**pins)
    with pytest.raises(ValueError):lab.export_canonical(**pins)


def test_changed_canonical_output_blocks_resume_and_export(tmp_path):
    lab=SimulationWorkbench(tmp_path);plan=lab.prepare("positive")
    saved=lab.canonical_fixture(plan["simulation_id"],plan["recipe_sha256"])
    pins={key:saved[key] for key in ("simulation_id","recipe_sha256","report_sha256","package_manifest_sha256")}
    path=lab.root/plan["simulation_id"]/"canonical-execution"/"analysis-result.json"
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValidationError):lab.inspect_canonical(**pins)
    with pytest.raises(ValidationError):lab.export_canonical(**pins)


def test_same_code_replay_retains_match_and_environment_discrepancy(tmp_path,monkeypatch):
    from research_machine.addons import general_science
    lab=SimulationWorkbench(tmp_path);plan=lab.prepare("positive")
    saved=lab.canonical_fixture(plan["simulation_id"],plan["recipe_sha256"])
    pins={key:saved[key] for key in ("simulation_id","recipe_sha256","report_sha256","package_manifest_sha256")}
    matched=lab.replay_canonical(**pins)
    assert matched["matches"] is True and matched["scientific_evidence_eligible"] is False
    class AlteredRuntimeRandom:
        def __init__(self,seed):pass
        def choice(self,values):return values[0]
    monkeypatch.setattr(general_science.random,"Random",AlteredRuntimeRandom)
    changed=lab.replay_canonical(**pins)
    assert changed["status"]=="replay_completed" and changed["matches"] is False
    assert changed["original_result_sha256"]==matched["original_result_sha256"]
    assert len(list((lab.root/plan["simulation_id"]/"replays").glob("*/replay-summary.json")))==2


@pytest.mark.parametrize("case", ["positive", "negative", "null", "missing", "invalid"])
def test_prepared_design_exposes_exact_retained_bytes_before_execution(tmp_path, case):
    import hashlib
    import json
    lab = SimulationWorkbench(tmp_path)
    plan = lab.prepare(case)
    directory = lab.root / plan["simulation_id"]
    for field, filename, commitment in (("specification_json", "analysis.json", "specification_sha256"),
                                        ("input_csv", "input.csv", "input_sha256")):
        raw = plan["design"][field].encode("utf-8")
        assert raw == (directory / filename).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == plan["recipe"][commitment]
    spec = json.loads(plan["design"]["specification_json"])
    assert spec["groups"] == ["sun", "shade"]
    assert spec.get("missing_data_policy") == ("complete_case" if case == "missing" else None)
    assert len(plan["design"]["input_csv"].splitlines()) == 9
    assert not (directory / "execution").exists()
    assert plan["canonical_write_performed"] is False


def test_prepare_is_available_before_the_first_draft_save(tmp_path):
    workspace = tmp_path / "fresh-workspace"
    assert not workspace.exists()
    plan = SimulationWorkbench(workspace).prepare("positive")
    assert plan["status"] == "prepared"
    assert (workspace / "simulation-workbench" / plan["simulation_id"] / "input.csv").is_file()
    assert not (workspace / "workspace.json").exists()
    assert not (workspace / "inquiries").exists()
