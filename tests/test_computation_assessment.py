"""Working interpretation stays bound to actual results without scientific promotion."""
import copy
import json
import pytest
from test_beginner_computation import fixture
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.service import ResearchService
from research_machine.application.computation_assessment import ComputationAssessment, FIELDS
from research_machine.application.portable_computation import PortableComputation, export_computation
from research_machine.domain.errors import ValidationError


def setup(tmp_path, case="positive"):
    service, work, payload = fixture(tmp_path, case)
    result = work.run(work.prepare(payload)["bundle_sha256"])
    reference = {"bundle_sha256": result["bundle_sha256"], **{key:result[key] for key in ("receipt_sha256", "failure_sha256") if key in result}}
    notes = {"interpretation":"The registered software returned the retained outcome; no physical inference.",
             "uncertainty":"The interval is conditional on independent generated units and the declared estimator.",
             "alternatives":"Different inputs, missingness and group order remain alternative software explanations.",
             "limitations":"Synthetic fixture only; no causal conclusion or scientific evidence.",
             "followup_question":"How does the retained output change when the registered contrast is reversed?",
             "decision_change":"A verified result that differs from the prespecified software expectation would change the interpretation."}
    return service, work, payload, reference, notes


@pytest.mark.parametrize("case", ["positive", "null", "negative", "missing", "invalid"])
def test_assessment_save_inspect_repeat_and_revision_preserve_originals_and_canonical_state(tmp_path, case):
    service, work, payload, reference, notes = setup(tmp_path, case)
    before = service.verify_ledger(payload["checked_draft"]["request"]["inquiry_id"])
    assessments = ComputationAssessment(service)
    body = {"source":{"kind":"notebook",**reference},"notes":notes}
    value = assessments.save(body)
    assert assessments.save(body) == value
    assert assessments.inspect(value["assessment_sha256"]) == value
    snapshot = json.loads(value["record"]["source_snapshot_json"])
    assert snapshot["source"] == body["source"]
    assert snapshot["bundle"]["input_csv"] == work.inspect(reference["bundle_sha256"])["bundle"]["input_csv"]
    assert snapshot["outcome"]["status"] == ("refused_computation" if case=="invalid" else "verified_computation")
    assert value["record"]["notes"]["followup_question"] == notes["followup_question"]
    assert value["action_recommendation_created"] is False and value["scientific_evidence_eligible"] is False
    revised = assessments.save({**body,"notes":{**notes,"interpretation":"Revised working interpretation, earlier notes retained."}})
    assert revised["assessment_sha256"] != value["assessment_sha256"]
    assert assessments.inspect(value["assessment_sha256"]) == value
    assert len(list(assessments.root.iterdir())) == 2
    assert service.verify_ledger(payload["checked_draft"]["request"]["inquiry_id"]) == before
    assert service.list_runs(payload["checked_draft"]["request"]["inquiry_id"]) == []


@pytest.mark.parametrize("field", FIELDS)
def test_incomplete_notes_never_create_assessment(tmp_path, field):
    service, _, _, reference, notes = setup(tmp_path)
    assessments = ComputationAssessment(service)
    notes[field] = ""
    with pytest.raises(ValueError): assessments.save({"source":{"kind":"notebook",**reference},"notes":notes})
    assert not assessments.root.exists()


def test_changed_source_or_assessment_blocks_current_verification(tmp_path):
    service, work, _, reference, notes = setup(tmp_path)
    assessments = ComputationAssessment(service)
    value = assessments.save({"source":{"kind":"notebook",**reference},"notes":notes})
    path = work.directory(reference["bundle_sha256"]) / "execution" / "analysis-result.json"
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValidationError): assessments.inspect(value["assessment_sha256"])
    path = assessments.directory(value["assessment_sha256"]) / "assessment.json"
    original = path.read_bytes(); path.write_bytes(original+b" ")
    with pytest.raises(ValueError): assessments.inspect(value["assessment_sha256"])


def test_portable_source_and_local_replay_keep_distinct_assessment_lineage_without_canonical_init(tmp_path):
    source, work, _, reference, notes = setup(tmp_path / "source")
    archive = export_computation(work, reference)
    portable = PortableComputation(tmp_path / "fresh"); portable.restore(archive)
    result = portable.replay(archive["archive_sha256"])
    assessments = ComputationAssessment(ResearchService(FileSystemRepository(tmp_path / "fresh")))
    source_value = assessments.save({"source":{"kind":"portable_source","archive_sha256":archive["archive_sha256"]},"notes":notes})
    replay_value = assessments.save({"source":{"kind":"portable_replay","archive_sha256":archive["archive_sha256"],"receipt_sha256":result["receipt_sha256"]},"notes":notes})
    assert source_value["assessment_sha256"] != replay_value["assessment_sha256"]
    assert json.loads(replay_value["record"]["source_snapshot_json"])["outcome"]["comparison"] == "Byte-identical result replay."
    assert sorted(p.name for p in (tmp_path / "fresh").iterdir()) == ["computation-assessments","portable-computations"]


def test_extra_authority_and_prepared_only_reference_are_rejected(tmp_path):
    service, _, _, reference, notes = setup(tmp_path)
    assessments = ComputationAssessment(service)
    for body in ({"source":{"kind":"notebook",**reference},"notes":notes,"activate":True},
                 {"source":{"kind":"notebook","bundle_sha256":reference["bundle_sha256"]},"notes":notes}):
        with pytest.raises(ValueError): assessments.save(body)
    assert not assessments.root.exists()


def test_partial_save_is_not_replaced_on_retry(tmp_path, monkeypatch):
    service, _, _, reference, notes = setup(tmp_path)
    assessments = ComputationAssessment(service)
    def interrupted(path,raw): raise OSError("fixture interrupted before assessment publication")
    monkeypatch.setattr(assessments,"write",interrupted)
    body={"source":{"kind":"notebook",**reference},"notes":notes}
    with pytest.raises(OSError): assessments.save(body)
    with pytest.raises(FileNotFoundError): assessments.save(body)
    assert len(list(assessments.root.iterdir())) == 1


def test_symlinked_assessment_is_not_read_as_a_verified_record(tmp_path):
    service, _, _, reference, notes = setup(tmp_path)
    assessments = ComputationAssessment(service)
    value = assessments.save({"source":{"kind":"notebook",**reference},"notes":notes})
    path = assessments.directory(value["assessment_sha256"]) / "assessment.json"
    exported = tmp_path / "exported-assessment.json"; exported.write_bytes(path.read_bytes())
    path.unlink(); path.symlink_to(exported)
    with pytest.raises(ValueError): assessments.inspect(value["assessment_sha256"])


def test_http_assessment_is_session_scoped_and_cannot_request_scientific_promotion(tmp_path):
    from http.client import HTTPConnection
    from http.server import HTTPServer
    from threading import Thread
    from research_machine.interfaces.beginner import make_handler
    service, _, payload, reference, notes = setup(tmp_path)
    before = service.verify_ledger(payload["checked_draft"]["request"]["inquiry_id"])
    server=HTTPServer(("127.0.0.1",0),make_handler(tmp_path,"assessment-fixture"))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(path,body,token=True):
        connection=HTTPConnection(*server.server_address)
        headers={"Content-Type":"application/json","Host":f"127.0.0.1:{server.server_port}"}
        if token:headers["X-Faraday-Token"]="assessment-fixture"
        connection.request("POST",path,json.dumps(body),headers)
        response=connection.getresponse();value=json.loads(response.read());connection.close();return response.status,value
    try:
        body={"source":{"kind":"notebook",**reference},"notes":notes}
        assert request("/api/assessment/save",body,False)[0]==403
        status,value=request("/api/assessment/save",body)
        assert status==200 and value["action_recommendation_created"] is False
        assert request("/api/assessment/inspect",{"assessment_sha256":value["assessment_sha256"]})==(200,value)
        assert request("/api/assessment/save",{**body,"activate":True})[0]==400
        assert service.verify_ledger(payload["checked_draft"]["request"]["inquiry_id"])==before
    finally:
        server.shutdown();server.server_close();thread.join()
