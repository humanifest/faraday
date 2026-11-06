import json
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread

import pytest

from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.application.service import ResearchService
from research_machine.application.beginner import pathway, rehearsal_preview, start_inquiry
from research_machine.interfaces.beginner import make_handler

def pair(label="one", shade=20, sun=25):
    return {"id": label, "shade": shade, "sun": sun}

def preview(rows):
    return rehearsal_preview({"mode": "rehearsal", "unit": "degC", "rows": rows})

def test_pathway_never_grants_review_or_execution():
    p = pathway()
    assert p["review_status"] == "unresolved"
    assert len(p["decisions"]) == 7
    assert all(d["status"] == "unresolved" for d in p["decisions"])
    assert not p["confirmatory_collection_enabled"]
    assert not p["evidence_admission_enabled"]
    p["decisions"][0]["status"] = "approved"
    assert pathway()["decisions"][0]["status"] == "unresolved"

def test_service_preserves_literal_question_and_ledger(tmp_path):
    service = ResearchService(FileSystemRepository(tmp_path), actor="test-learner")
    service.init_workspace()
    statement = "Could the material, rather than shade, explain this?"
    result = start_inquiry(service, statement)
    state = service.show_inquiry(result["inquiry_id"])
    assert state["inquiry"]["initial_statement"] == statement
    assert len(state["questions"]) == 7
    assert state["hypotheses"] == []
    assert service.verify_ledger(result["inquiry_id"])["valid"]

@pytest.mark.parametrize("value", ["", " ", " padded question ", None, 42, "x" * 2001])
def test_invalid_question_does_not_create_workspace(tmp_path, value):
    service = ResearchService(FileSystemRepository(tmp_path))
    with pytest.raises(ValueError):
        start_inquiry(service, value)
    assert not list(tmp_path.iterdir())

def test_signed_arithmetic_missingness_and_no_inference():
    r = preview([pair("negative", 25, 20), pair("zero", 20, 20),
                 pair("missing", None, 22)])
    assert r["mean_difference_degC"] == -2.5
    assert r["incomplete_pair_ids"] == ["missing"]
    assert r["complete_pairs"] == 2
    assert r["independent_sample_size"] is None
    assert not r["uncertainty_estimated"]
    assert not r["scientific_evidence_eligible"]
    assert not r["canonical_write_performed"]
    assert preview([pair(shade=None)])["mean_difference_degC"] is None

@pytest.mark.parametrize("rows", [
    [], [pair(), pair()], [pair(label=" ")], [pair(label=" padded")],
    [pair(shade=True)], [pair(sun=float("nan"))], [pair(sun=float("inf"))],
    [pair(shade=-274)], [pair(sun="25")], [{"id":"one","shade":20}],
])
def test_bad_measurements_rejected(rows):
    with pytest.raises(ValueError):
        preview(rows)

@pytest.mark.parametrize("extra", [
    {"mode": "confirmatory"}, {"unit": "F"}, {"review_status": "approved"},
])
def test_no_client_review_or_real_data_bypass(extra):
    payload = {"mode":"rehearsal", "unit":"degC", "rows":[pair()]}
    payload.update(extra)
    with pytest.raises(ValueError):
        rehearsal_preview(payload)

def test_http_origin_request_bounds_and_canonical_write(tmp_path):
    token = "test-session-token"
    server = HTTPServer(("127.0.0.1", 0), make_handler(tmp_path, token))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(method, path, payload=None, headers=None):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        body = json.dumps(payload) if payload is not None else None
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        result = (response.status, response.read(), dict(response.getheaders()))
        connection.close()
        return result
    try:
        status, body, headers = request("GET", "/")
        assert status == 200 and b"Scientific review unresolved" in body
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert not list(tmp_path.iterdir())
        assert request("GET", "/", headers={"Host":"evil.example"})[0] == 403
        assert request("POST", "/api/inquiry", {"statement":"question"})[0] == 403
        good = {"Content-Type":"application/json", "X-Faraday-Token":token}
        assert request("POST", "/api/inquiry", {"statement":"q"},
                       {**good,"Origin":"https://evil.example"})[0] == 403
        assert request("POST", "/api/inquiry", {"statement":""}, good)[0] == 400
        assert not list(tmp_path.iterdir())
        assert request("POST", "/api/inquiry", {"statement":"x"*70000},good)[0] == 400
        assert request("POST", "/api/approve", {}, good)[0] == 404
        status, body, _ = request("POST", "/api/rehearsal",
            {"mode":"rehearsal","unit":"degC","rows":[pair()]},good)
        assert status == 200 and json.loads(body)["mean_difference_degC"] == 5
        assert not list(tmp_path.iterdir())
        status, body, _ = request("POST", "/api/inquiry", {"statement":"My literal question"},good)
        assert status == 200
        result = json.loads(body)
        service = ResearchService(FileSystemRepository(tmp_path))
        assert service.verify_ledger(result["inquiry_id"])["valid"]
        state = service.show_inquiry(result["inquiry_id"])
        assert not state["datasets"] and not state["protocols"] and not state["evidence"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

def test_html_is_packaged_and_drafts_are_scoped():
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text())
    assert "beginner.html" in config["tool"]["setuptools"]["package-data"]["research_machine.interfaces"]
    html = (root / "src/research_machine/interfaces/beginner.html").read_text()
    client = (root / "src/research_machine/interfaces/beginner.js").read_text()
    assert "__DRAFT_KEY__" in client
    assert "localStorage" in client
    assert "textContent" in client
    assert "innerHTML" not in client
    assert "beginner.js" in config["tool"]["setuptools"]["package-data"]["research_machine.interfaces"]

def test_client_asset_is_scoped_to_same_host_without_workspace_writes(tmp_path):
    server = HTTPServer(("127.0.0.1", 0), make_handler(tmp_path, "asset-test-token"))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def get(host=None):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("GET", "/beginner.js", headers={"Host": host} if host else {})
        response = connection.getresponse()
        result = response.status, response.read(), response.getheader("Content-Type")
        connection.close()
        return result
    try:
        status, body, media_type = get()
        assert status == 200 and media_type.startswith("application/javascript")
        assert b"__TOKEN__" not in body and b"__DRAFT_KEY__" not in body
        assert b"asset-test-token" in body
        assert get("other.example")[0] == 403
        assert not list(tmp_path.iterdir())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_html_has_accessible_structure_and_resolvable_descriptions():
    from html.parser import HTMLParser
    from research_machine.interfaces.beginner import PAGE
    class Structure(HTMLParser):
        def __init__(self):
            super().__init__()
            self.nodes = []
        def handle_starttag(self, tag, attributes):
            self.nodes.append((tag, dict(attributes)))
    structure = Structure()
    structure.feed(PAGE.read_text())
    nodes = structure.nodes
    ids = [attrs["id"] for _, attrs in nodes if "id" in attrs]
    assert len(ids) == len(set(ids)), "Duplicate IDs break label/error associations."
    by_id = {attrs["id"]: (tag, attrs) for tag, attrs in nodes if "id" in attrs}
    assert any(tag == "html" and attrs.get("lang") == "en" for tag, attrs in nodes)
    assert sum(tag == "h1" for tag, _ in nodes) == 1
    assert sum(tag == "main" for tag, _ in nodes) == 1
    assert any(tag == "a" and attrs.get("href") == "#main" for tag, attrs in nodes)
    assert any(tag == "noscript" for tag, _ in nodes)
    for tag, attrs in nodes:
        if tag == "label":
            assert attrs.get("for") in by_id
        for name in ("aria-labelledby", "aria-describedby"):
            for target in attrs.get(name, "").split():
                assert target in by_id, f"Missing {name} target: {target}"
        if tag == "th":
            assert attrs.get("scope") == "col"
        if tag == "section":
            assert attrs.get("aria-labelledby") in by_id
        if tag == "textarea":
            assert any(other == "label" and values.get("for") == attrs["id"]
                       for other, values in nodes)
        if tag == "script":
            assert attrs.get("src") == "/beginner.js"
            assert attrs.get("nonce") == "__TOKEN__"
    assert any(tag == "caption" for tag, _ in nodes)
    assert by_id["error"][1]["role"] == "alert"
    assert by_id["error"][1]["tabindex"] == "-1"
    for status in ("draft-status", "saved", "summary", "pair-status"):
        assert by_id[status][1]["role"] == "status"


def test_primary_activity_controls_are_visible_without_opening_advanced_tools():
    from html.parser import HTMLParser
    from research_machine.interfaces.beginner import PAGE
    class Hierarchy(HTMLParser):
        def __init__(self):super().__init__();self.stack=[];self.ancestors={};self.attributes={}
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if "id" in attrs:
                self.ancestors[attrs["id"]]=[item[1].get("id") for item in self.stack]
                self.attributes[attrs["id"]]=attrs
            if tag not in {"area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"}:self.stack.append((tag,attrs))
        def handle_endtag(self,tag):
            for i in range(len(self.stack)-1,-1,-1):
                if self.stack[i][0]==tag:self.stack=self.stack[:i];break
    page=Hierarchy();page.feed(PAGE.read_text())
    assert "open" not in page.attributes["advanced-tools"]
    for control in ("statement","save","prediction","simulation-case","simulation-prepare","simulation-run","simulation-result","reflection","simulation-download","next-question","import-apply"):
        assert "advanced-tools" not in page.ancestors[control],control
    for control in ("computation-method","computation-spec","design-preview","protocol-draft-save","hypothesis-save","assessment-save","simulation-canonical"):
        assert "advanced-tools" in page.ancestors[control],control

@pytest.mark.parametrize("namespace", ["", "f"*63, "F"*64, "../workspace", True])
def test_invalid_draft_namespace_is_rejected_without_writes(tmp_path, namespace):
    with pytest.raises(ValueError, match="64 lowercase"):
        make_handler(tmp_path, "test-token", draft_namespace=namespace)
    assert not list(tmp_path.iterdir())


def test_workspace_move_retains_browser_namespace_and_canonical_ledger(tmp_path):
    import hashlib
    import re
    import shutil
    old = tmp_path / "temporary"
    new = tmp_path / "persistent"
    service = ResearchService(FileSystemRepository(old))
    service.init_workspace()
    inquiry = start_inquiry(service, "Will this question survive restarting?")
    namespace = hashlib.sha256(str(old.resolve()).encode()).hexdigest()
    shutil.copytree(old, new)
    retained = ResearchService(FileSystemRepository(new))
    assert retained.verify_ledger(inquiry["inquiry_id"])["valid"]
    assert retained.show_inquiry(inquiry["inquiry_id"])["inquiry"]["initial_statement"] == "Will this question survive restarting?"

    def client_key(root, override=None):
        server = HTTPServer(("127.0.0.1", 0), make_handler(root, "test-token", draft_namespace=override))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/beginner.js")
            response = connection.getresponse()
            assert response.status == 200
            body = response.read().decode()
            connection.close()
            return re.search(r'const key = "([^"]+)"', body).group(1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    old_key = client_key(old)
    assert client_key(new, namespace) == old_key
    assert client_key(new) != old_key
    # Restarting with the same persistent path and retained namespace is stable.
    assert client_key(new, namespace) == old_key
