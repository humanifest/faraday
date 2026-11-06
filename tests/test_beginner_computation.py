"""Draft-bound input retention and real registered computation in disposable state."""
import hashlib
import json
from pathlib import Path
import pytest
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.service import ResearchService
from research_machine.application.commands import ProposeHypothesis
from research_machine.application.beginner import start_inquiry
from research_machine.application.beginner_design import DESIGN_FIELDS, preview_notebook_design, notebook_protocol_draft
from research_machine.application.beginner_computation import NotebookComputation, method_identity
from research_machine.application.beginner_simulation import _inputs
from research_machine.domain.errors import ValidationError


def fixture(tmp_path, case="positive", scope="synthetic"):
    service = ResearchService(FileSystemRepository(tmp_path))
    service.init_workspace()
    inquiry = start_inquiry(service, "Can the retained synthetic mean difference be reproduced?")
    h = service.propose_hypothesis(ProposeHypothesis(
        statement="The synthetic signed estimate exceeds zero.", observable_prediction="The retained sun-minus-shade estimate is positive.",
        null_model="The signed estimate is zero.", competing_models=["The contrast is reversed."],
        falsification_conditions=["The valid estimate is nonpositive."], scope="Synthetic software only."), inquiry["inquiry_id"])
    design = {field: "" for field in DESIGN_FIELDS}
    design.update(data_scope=scope, analysis_code_hash=method_identity()["implementation_sha256"])
    request = {"inquiry_id": inquiry["inquiry_id"], "original_statement": inquiry["original_statement"],
               "hypothesis_id": h.hypothesis_id, "hypothesis_sha256": h.scientific_content_sha256,
               "planning": {"title": "Synthetic draft", "outcome": "Mean difference", "unit_of_observation": "Generated unit"}, "design": design}
    checked = {"request": request, "design_input_sha256": preview_notebook_design(service, request)["design_input_sha256"]}
    notebook_protocol_draft(service, checked, write=True)
    spec, data = _inputs(case)
    payload = {"checked_draft": checked, "specification_json": spec.decode(), "input_csv": data.decode(),
               "provenance": "Generated fixed software fixture; no physical observations."}
    return service, NotebookComputation(service), payload


@pytest.mark.parametrize("case,sign", [("positive", 1), ("null", 0), ("negative", -1), ("missing", 0)])
def test_bound_draft_computation_retains_real_native_result_without_canonical_advancement(tmp_path, case, sign):
    service, work, payload = fixture(tmp_path, case)
    inquiry = payload["checked_draft"]["request"]["inquiry_id"]
    before = service.verify_ledger(inquiry)
    prepared = work.prepare(payload)
    assert prepared == work.prepare(payload)  # Idempotent preparation, no output replacement.
    value = work.run(prepared["bundle_sha256"])
    assert value["status"] == "verified_computation"
    assert work.verify(value["bundle_sha256"], value["receipt_sha256"]) == value
    assert value["canonical_write_performed"] is False
    assert value["scientific_evidence_eligible"] is False
    result = value["result"]["result"]
    estimate = result["mean_difference_first_minus_second"]
    if case != "missing":
        assert (estimate > 0) - (estimate < 0) == sign
    assert result["assumptions"]
    assert service.verify_ledger(inquiry) == before
    assert service.list_protocols(inquiry)[0].status.value == "draft"
    assert service.get_hypothesis(payload["checked_draft"]["request"]["hypothesis_id"], inquiry).workflow_state.value == "unreviewed"
    assert service.list_datasets(inquiry) == []
    assert service.list_runs(inquiry) == []
    with pytest.raises((ValueError, FileExistsError)):
        work.run(prepared["bundle_sha256"])


@pytest.mark.parametrize("artifact", ["bundle.json", "analysis.json", "input.csv", "execution/analysis-result.json"])
def test_changed_artifacts_block_verification_without_replacement(tmp_path, artifact):
    _, work, payload = fixture(tmp_path)
    prepared = work.prepare(payload)
    value = work.run(prepared["bundle_sha256"])
    path = work.directory(value["bundle_sha256"]) / artifact
    path.write_bytes(path.read_bytes() + b" ")
    changed = path.read_bytes()
    with pytest.raises((ValueError, ValidationError)):
        work.verify(value["bundle_sha256"], value["receipt_sha256"])
    assert path.read_bytes() == changed


@pytest.mark.parametrize("mutation", ["method", "budget", "draft_hash", "extra_authority", "no_source"])
def test_bad_inputs_do_not_create_a_computation_or_change_canonical_state(tmp_path, mutation):
    service, work, payload = fixture(tmp_path)
    before = service.verify_ledger(payload["checked_draft"]["request"]["inquiry_id"])
    if mutation in {"method", "budget"}:
        spec = json.loads(payload["specification_json"])
        spec["method" if mutation == "method" else "bootstrap_resamples"] = "caller-code" if mutation == "method" else 1000000
        payload["specification_json"] = json.dumps(spec)
    elif mutation == "draft_hash": payload["checked_draft"]["design_input_sha256"] = "0" * 64
    elif mutation == "extra_authority": payload["freeze"] = True
    else: payload["provenance"] = ""
    with pytest.raises(ValueError): work.prepare(payload)
    assert not work.root.exists()
    assert service.verify_ledger(payload["checked_draft"]["request"]["inquiry_id"]) == before


def test_symlinked_input_fails_closed(tmp_path):
    _, work, payload = fixture(tmp_path)
    value = work.prepare(payload)
    path = work.directory(value["bundle_sha256"]) / "input.csv"
    exported = tmp_path / "exported.csv"
    exported.write_bytes(path.read_bytes())
    path.unlink(); path.symlink_to(exported)
    with pytest.raises(ValueError): work.inspect(value["bundle_sha256"])


def test_changed_implementation_fails_closed(tmp_path, monkeypatch):
    _, work, payload = fixture(tmp_path)
    value = work.prepare(payload)
    import research_machine.application.beginner_computation as module
    monkeypatch.setattr(module, "method_identity", lambda: {"method": "independent_mean_difference_ci", "implementation_sha256": "0"*64})
    with pytest.raises(ValueError): work.inspect(value["bundle_sha256"])


def test_invalid_data_retains_hash_bound_refusal_without_numerical_result(tmp_path):
    _, work, payload = fixture(tmp_path, "invalid")
    prepared = work.prepare(payload)
    result = work.run(prepared["bundle_sha256"])
    assert result["status"] == "refused_computation"
    assert "result" not in result and result["attempted"] is True
    assert result == work.verify(result["bundle_sha256"], failure_sha256=result["failure_sha256"])
    with pytest.raises(FileExistsError): work.run(result["bundle_sha256"])
    path = work.directory(result["bundle_sha256"]) / "failure.json"
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValueError): work.verify(result["bundle_sha256"], failure_sha256=result["failure_sha256"])


def test_partial_prepare_is_not_repaired_by_retry(tmp_path, monkeypatch):
    _, work, payload = fixture(tmp_path)
    original = work.write
    def interrupted(path, raw):
        if path.name == "bundle.json": raise OSError("fixture interrupted before final bundle")
        return original(path, raw)
    monkeypatch.setattr(work, "write", interrupted)
    with pytest.raises(OSError): work.prepare(payload)
    with pytest.raises(FileNotFoundError): work.prepare(payload)
    assert len(list(work.root.iterdir())) == 1


def test_http_computation_is_session_scoped_and_never_freezes_draft(tmp_path):
    from http.client import HTTPConnection
    from http.server import HTTPServer
    from threading import Thread
    from research_machine.interfaces.beginner import make_handler
    service, _, payload = fixture(tmp_path)
    server = HTTPServer(("127.0.0.1", 0), make_handler(tmp_path, "computation-session"))
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    def request(path, body, token=True):
        connection = HTTPConnection(*server.server_address)
        headers = {"Content-Type": "application/json", "Host": f"127.0.0.1:{server.server_port}"}
        if token: headers["X-Faraday-Token"] = "computation-session"
        connection.request("POST", path, json.dumps(body), headers)
        response = connection.getresponse(); value = json.loads(response.read()); connection.close()
        return response.status, value
    try:
        assert request("/api/computation/prepare", payload, False)[0] == 403
        status, prepared = request("/api/computation/prepare", payload)
        assert status == 200
        reference = {"bundle_sha256": prepared["bundle_sha256"]}
        status, result = request("/api/computation/run", reference)
        assert status == 200 and result["status"] == "verified_computation"
        assert request("/api/computation/verify", {**reference, "receipt_sha256": result["receipt_sha256"]}) == (200, result)
        assert request("/api/computation/run", reference)[0] == 400  # Write-once attempt, not a retry.
        assert request("/api/computation/prepare", {**payload, "freeze": True})[0] == 400
        assert service.list_protocols(payload["checked_draft"]["request"]["inquiry_id"])[0].status.value == "draft"
    finally:
        server.shutdown(); server.server_close(); thread.join()
