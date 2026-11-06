"""Synthetic files test a low-authority published-example loading boundary."""
import csv
import hashlib
from http.client import HTTPConnection
from http.server import HTTPServer
import json
from pathlib import Path
from threading import Thread

import pytest

from research_machine.application.beginner import rehearsal_report
from research_machine.application.published_replay import PublishedReplayExample
from research_machine.interfaces.beginner import make_handler


def encode(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()


def pin(directory, manifest):
    raw = encode(manifest)
    (directory / "replay-manifest.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def example(directory):
    directory.mkdir()
    citation = "Synthetic source-fit fixture; no actual published observations."
    source_hash = "a" * 64
    draft = {"kind": "non-evidentiary-rehearsal-draft", "review_status": "unresolved",
             "scientific_evidence_eligible": False, "statement": "Fixture replay?",
             "prediction": "", "reflection": "Fixture only; no evidence.",
             "rows": [{"id": "one", "shade": "20", "sun": "18"},
                      {"id": "two", "shade": "20", "sun": "20"}],
             "history": [], "inquiry_id": None, "saved_statement": None, "save_state": "draft",
             "planning": {"available_data_sources": citation + " " + source_hash}}
    (directory / "rehearsal-draft.json").write_bytes(encode(draft))
    (directory / "rehearsal-report.json").write_bytes(encode(rehearsal_report(draft)))
    with (directory / "hourly-replay.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("id", "shade", "sun"))
        writer.writeheader()
        writer.writerows(draft["rows"])
    manifest = {"kind": "published-data-replay-manifest", "replay_schema_version": 1,
                "rehearsal_unit": "degC", "contrast_order": ["sun", "shade"],
                "source_data_synthetic": False, "scientific_evidence_eligible": False,
                "canonical_write_performed": False, "source_doi": "fixture:not-a-study",
                "source_url": "https://example.invalid/fixture", "citation": citation,
                "license": "Fixture only", "selection": "Both toy pairs, unchanged.",
                "limitations": "Synthetic software fixture, not real publication metadata.",
                "source_sha256": source_hash, "pair_count": 2,
                "lineage": [{"pair_id": row["id"]} for row in draft["rows"]]}
    refresh_outputs(directory, manifest)
    return draft, manifest, pin(directory, manifest)


def refresh_outputs(directory, manifest):
    manifest["outputs"] = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                           for name in ("rehearsal-draft.json", "rehearsal-report.json", "hourly-replay.csv")}


def test_example_replays_generated_files_read_only(tmp_path):
    directory = tmp_path / "example"
    draft, manifest, digest = example(directory)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    result = PublishedReplayExample(directory, digest).load()
    assert result["draft"] == draft
    assert result["source"]["citation"] == manifest["citation"]
    assert result["canonical_write_performed"] is False
    assert result["scientific_evidence_eligible"] is False
    assert result["data_classification"] == "published_observations_not_synthetic"
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


@pytest.mark.parametrize("mutation", [
    {"rehearsal_unit": "degF"}, {"contrast_order": ["shade", "sun"]},
    {"source_data_synthetic": True}, {"scientific_evidence_eligible": True},
    {"canonical_write_performed": True}, {"replay_schema_version": True},
    {"pair_count": True}, {"lineage": [{"pair_id": "invented"}]},
    {"citation": ""}, {"outputs": {"../escape": "a" * 64}},
])
def test_pinned_but_incompatible_contracts_are_rejected(tmp_path, mutation):
    _, manifest, _ = example(tmp_path / "example")
    manifest.update(mutation)
    digest = pin(tmp_path / "example", manifest)
    with pytest.raises(ValueError):
        PublishedReplayExample(tmp_path / "example", digest).load()


def test_changed_files_and_symlinks_fail_even_after_earlier_load(tmp_path):
    directory = tmp_path / "example"
    _, _, digest = example(directory)
    lab = PublishedReplayExample(directory, digest)
    lab.load()
    path = directory / "hourly-replay.csv"
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    with pytest.raises(ValueError):
        lab.load()
    path.write_bytes(original)
    moved = tmp_path / "retained.csv"
    path.rename(moved)
    path.symlink_to(moved)
    with pytest.raises(ValueError):
        lab.load()
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError):
        PublishedReplayExample(linked_directory, digest).load()


@pytest.mark.parametrize("name", ["rehearsal-report.json", "hourly-replay.csv", "rehearsal-draft.json"])
def test_rehashed_output_disagreement_cannot_pass(tmp_path, name):
    directory = tmp_path / "example"
    _, manifest, _ = example(directory)
    path = directory / name
    if name == "hourly-replay.csv":
        path.write_text(path.read_text().replace("18", "99"))
    else:
        data = json.loads(path.read_text())
        if name == "rehearsal-report.json":
            data["arithmetic"]["mean_difference_degC"] = 999
        else:
            data.update(inquiry_id="existing-inquiry", saved_statement="Fixture replay?", save_state="saved")
        path.write_bytes(encode(data))
    refresh_outputs(directory, manifest)
    digest = pin(directory, manifest)
    with pytest.raises(ValueError):
        PublishedReplayExample(directory, digest).load()


def test_configuration_requires_both_pins_and_keeps_source_outside_checkout(tmp_path):
    assert not PublishedReplayExample().configured
    with pytest.raises(ValueError):
        PublishedReplayExample().load()
    for directory, digest in ((tmp_path, None), (None, "a" * 64), (tmp_path, "BAD")):
        with pytest.raises(ValueError):
            PublishedReplayExample(directory, digest)
    with pytest.raises(ValueError):
        PublishedReplayExample(Path(__file__).resolve().parents[1], "a" * 64).load()


def test_http_example_is_session_bound_and_never_creates_research_state(tmp_path):
    directory = tmp_path / "example"
    _, _, digest = example(directory)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server = HTTPServer(("127.0.0.1", 0), make_handler(workspace, "fixture-token",
                        published_replay_directory=directory, published_replay_manifest_sha256=digest))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(method, path, payload=None, authorized=True):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["X-Faraday-Token"] = "fixture-token"
        connection.request(method, path, json.dumps(payload) if payload is not None else None, headers)
        response = connection.getresponse()
        answer = response.status, json.loads(response.read())
        connection.close()
        return answer
    try:
        assert request("GET", "/api/pathway")[1]["published_example_available"] is True
        assert request("POST", "/api/examples/published", {}, False)[0] == 403
        assert request("POST", "/api/examples/published", {"directory": "elsewhere"})[0] == 400
        status, result = request("POST", "/api/examples/published", {})
        assert status == 200 and result["canonical_write_performed"] is False
        assert not list(workspace.iterdir())
        (directory / "rehearsal-draft.json").write_text("changed")
        assert request("POST", "/api/examples/published", {})[0] == 400
        assert not list(workspace.iterdir())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
