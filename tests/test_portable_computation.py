"""Portable archives replay in a fresh workspace without canonical records."""
import copy
import json
import pytest
from test_beginner_computation import fixture
from research_machine.application.portable_computation import PortableComputation, export_computation, validate_archive
from research_machine.application.beginner_computation import encoded, sha
from research_machine.domain.errors import ValidationError


def archive_fixture(tmp_path, case="positive", run=True):
    service, work, payload = fixture(tmp_path / "source", case)
    result = work.prepare(payload)
    reference = {"bundle_sha256": result["bundle_sha256"]}
    if run:
        result = work.run(result["bundle_sha256"])
        reference.update({key: result[key] for key in ("receipt_sha256", "failure_sha256") if key in result})
    return service, work, payload, export_computation(work, reference)


@pytest.mark.parametrize("case", ["positive", "null", "negative", "missing", "invalid"])
def test_restore_and_replay_preserve_source_and_do_not_create_canonical_state(tmp_path, case):
    service, _, payload, envelope = archive_fixture(tmp_path, case)
    original = copy.deepcopy(envelope)
    inquiry = payload["checked_draft"]["request"]["inquiry_id"]
    before = service.verify_ledger(inquiry)
    work = PortableComputation(tmp_path / "fresh")
    retained = work.restore(envelope)
    assert work.restore(envelope) == retained
    assert retained["envelope"] == original
    assert not (tmp_path / "fresh" / ".research").exists()
    assert list((tmp_path / "fresh").iterdir()) == [tmp_path / "fresh" / "portable-computations"]
    result = work.replay(envelope["archive_sha256"])
    reference = {"archive_sha256": envelope["archive_sha256"], **{key: result[key] for key in ("receipt_sha256", "refusal_sha256") if key in result}}
    assert work.verify_replay(**reference) == result
    assert result["envelope"] == original
    if case == "invalid":
        assert result["status"] == "verified_portable_refusal" and "result" not in result
    else:
        assert result["comparison"] == "Byte-identical result replay."
        assert result["result"] == json.loads(envelope["archive_json"])["computation"]["result"]
    assert result["scientific_evidence_eligible"] is False and result["canonical_write_performed"] is False
    with pytest.raises((ValueError, FileExistsError)): work.replay(envelope["archive_sha256"])
    assert service.verify_ledger(inquiry) == before


def test_prepared_archive_can_replay_without_claiming_an_original_result(tmp_path):
    _, _, _, envelope = archive_fixture(tmp_path, run=False)
    work = PortableComputation(tmp_path / "fresh")
    work.restore(envelope)
    result = work.replay(envelope["archive_sha256"])
    assert "new working computation" in result["comparison"]
    assert "result" not in json.loads(envelope["archive_json"])["computation"]


@pytest.mark.parametrize("field", ["input", "result", "hypothesis", "draft", "scope", "extra"])
def test_tampering_even_with_new_outer_hash_does_not_write_destination(tmp_path, field):
    _, _, _, envelope = archive_fixture(tmp_path)
    a = json.loads(envelope["archive_json"])
    if field == "input": a["computation"]["bundle"]["input_csv"] += "changed"
    elif field == "result": a["computation"]["result"]["result"]["mean_difference_first_minus_second"] = 12345
    elif field == "hypothesis": a["context"]["hypothesis"]["statement"] = "Changed proposition"
    elif field == "draft": a["context"]["protocol"]["methodology"] = "Changed method"
    elif field == "scope": a["scientific_evidence_eligible"] = True
    else: a["freeze"] = True
    envelope["archive_json"] = encoded(a).decode()
    envelope["archive_sha256"] = sha(encoded(a))
    work = PortableComputation(tmp_path / "fresh")
    with pytest.raises((ValueError, ValidationError)): work.restore(envelope)
    assert not (tmp_path / "fresh").exists()


def test_export_redacts_native_operational_locators(tmp_path):
    _, _, _, envelope = archive_fixture(tmp_path)
    assert str(tmp_path) not in json.dumps(envelope)
    receipt = json.loads(json.loads(envelope["archive_json"])["source_outcome"]["receipt_json"])
    assert receipt["specification"]["locator"] == "analysis.json"
    assert receipt["input"]["locator"] == "input.csv"
    assert receipt["implementation"]["locator"] == "bundled-method"


def test_partial_restore_is_not_repaired_and_changed_restored_bytes_block_inspection(tmp_path, monkeypatch):
    _, _, _, envelope = archive_fixture(tmp_path)
    work = PortableComputation(tmp_path / "fresh")
    original = work.write
    def interrupted(path, raw):
        if path.name == "input.csv": raise OSError("fixture interrupted")
        return original(path, raw)
    monkeypatch.setattr(work, "write", interrupted)
    with pytest.raises(OSError): work.restore(envelope)
    with pytest.raises(FileNotFoundError): work.restore(envelope)


@pytest.mark.parametrize("bad", [{}, {"format": "untrusted"}, {"format": "faraday-portable-computation-v1", "archive_sha256": "0"*64, "archive_json": "[]"}])
def test_malformed_archive_is_a_bounded_input_error(bad):
    with pytest.raises(ValueError): validate_archive(bad)


def test_outer_json_roundtrip_preserves_exact_hashed_numeric_text(tmp_path):
    _, _, _, envelope = archive_fixture(tmp_path, "null")
    assert '0.0' in envelope["archive_json"]
    roundtrip = json.loads(json.dumps(envelope))
    assert roundtrip["archive_json"] == envelope["archive_json"]
    validate_archive(roundtrip)


def test_old_implementation_archive_remains_viewable_but_replay_is_blocked(tmp_path, monkeypatch):
    _, _, _, envelope = archive_fixture(tmp_path)
    work = PortableComputation(tmp_path / "fresh")
    work.restore(envelope)
    import research_machine.application.portable_computation as module
    monkeypatch.setattr(module, "method_identity", lambda: {"method": "independent_mean_difference_ci", "implementation_sha256": "0"*64})
    assert work.inspect(envelope["archive_sha256"])["envelope"] == envelope
    with pytest.raises(ValueError): work.replay(envelope["archive_sha256"])
    assert not work.inspect(envelope["archive_sha256"])["replay_attempted"]


def test_changed_restored_bytes_and_replay_output_block_current_verification(tmp_path):
    _, _, _, envelope = archive_fixture(tmp_path)
    work = PortableComputation(tmp_path / "fresh"); work.restore(envelope)
    result = work.replay(envelope["archive_sha256"])
    path = work.directory(envelope["archive_sha256"]) / "replay" / "analysis-result.json"
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValidationError): work.verify_replay(envelope["archive_sha256"], receipt_sha256=result["receipt_sha256"])
    path = work.directory(envelope["archive_sha256"]) / "input.csv"
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValueError): work.inspect(envelope["archive_sha256"])


def test_comparison_miss_is_retained_with_both_source_and_replay(tmp_path):
    _, _, _, envelope = archive_fixture(tmp_path)
    archive = json.loads(envelope["archive_json"])
    value = json.loads(archive["source_outcome"]["result_json"])
    value["purpose"] = "Archived descriptive label differs from the replay."
    raw = encoded(value)
    receipt = json.loads(archive["source_outcome"]["receipt_json"])
    receipt["output"].update(sha256=sha(raw),size_bytes=len(raw))
    archive["source_outcome"] = {"receipt_json": encoded(receipt).decode(), "result_json": raw.decode()}
    archive["computation"]["result"] = value
    envelope.update(archive_json=encoded(archive).decode(),archive_sha256=sha(encoded(archive)))
    work = PortableComputation(tmp_path / "fresh"); work.restore(envelope)
    result = work.replay(envelope["archive_sha256"])
    assert result["status"] == "verified_portable_replay"
    assert result["comparison"].startswith("Result differs")
    assert json.loads(result["envelope"]["archive_json"])["computation"]["result"] == value
    assert result["result"] != value


def test_http_restore_on_fresh_workspace_requires_session_and_never_initializes_canonical_state(tmp_path):
    from http.client import HTTPConnection
    from http.server import HTTPServer
    from threading import Thread
    from research_machine.interfaces.beginner import make_handler
    _, _, _, envelope = archive_fixture(tmp_path)
    root = tmp_path / "fresh"
    server = HTTPServer(("127.0.0.1", 0), make_handler(root, "portable-fixture"))
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    def request(path, body, token=True):
        connection = HTTPConnection(*server.server_address)
        headers = {"Content-Type": "application/json", "Host": f"127.0.0.1:{server.server_port}"}
        if token: headers["X-Faraday-Token"] = "portable-fixture"
        connection.request("POST", path, json.dumps(body), headers)
        response = connection.getresponse(); value = json.loads(response.read()); connection.close()
        return response.status, value
    try:
        assert request("/api/portable-computation/restore", envelope, False)[0] == 403
        assert request("/api/portable-computation/restore", envelope)[0] == 200
        reference = {"archive_sha256": envelope["archive_sha256"]}
        status, value = request("/api/portable-computation/replay", reference)
        assert status == 200 and value["comparison"] == "Byte-identical result replay."
        assert request("/api/portable-computation/verify", {**reference, "receipt_sha256": value["receipt_sha256"]}) == (200, value)
        assert list(root.iterdir()) == [root / "portable-computations"]
        assert request("/api/portable-computation/restore", {**envelope, "activate": True})[0] == 400
    finally:
        server.shutdown(); server.server_close(); thread.join()
