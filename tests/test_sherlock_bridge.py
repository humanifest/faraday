from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from research_machine.interfaces.cli import main

jsonschema = pytest.importorskip("jsonschema")

ROOT = Path(__file__).resolve().parents[1]


def _cli_result(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    return payload["result"]


def test_sherlock_bridge_example_matches_published_schema() -> None:
    schema = json.loads((ROOT / "schemas" / "sherlock-bridge-link.schema.json").read_text())
    example = json.loads((ROOT / "examples" / "sherlock-bridge-link.json").read_text())

    jsonschema.validate(example, schema)


@pytest.mark.parametrize(
    "field",
    [
        "faraday_canonical_state_mutated",
        "sherlock_note_is_faraday_evidence",
        "publication_authorized",
        "review_promotion_authorized",
    ],
)
def test_sherlock_bridge_schema_rejects_authority_merger(field: str) -> None:
    schema = json.loads((ROOT / "schemas" / "sherlock-bridge-link.schema.json").read_text())
    example = json.loads((ROOT / "examples" / "sherlock-bridge-link.json").read_text())
    example["authority_boundary"][field] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(example, schema)


def test_sherlock_bridge_project_keeps_runtime_lock_local() -> None:
    ignored = (ROOT / "sherlock-integration" / ".gitignore").read_text()

    assert "runtime-lock.json" in ignored
    assert "workspace/" in ignored
    assert ".runtime/" in ignored


def test_sherlock_bridge_project_binds_exact_charter_bytes() -> None:
    project = json.loads((ROOT / "sherlock-integration" / "project.json").read_text())
    charter = ROOT / "sherlock-integration" / project["charter_file"]
    digest = hashlib.sha256(charter.read_bytes()).hexdigest()

    assert project["charter_sha256"] == f"sha256:{digest}"


def test_cli_exports_sherlock_evidence_bridge_receipt(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    global_args = ["--workspace", str(workspace), "--json"]
    assert main([*global_args, "workspace", "init"]) == 0
    _cli_result(capsys)
    assert main([
        *global_args,
        "inquiry",
        "create",
        "--id",
        "bridge-case",
        "--title",
        "Bridge case",
        "--statement",
        "Can Sherlock inspect Faraday evidence safely?",
    ]) == 0
    _cli_result(capsys)
    assert main([
        *global_args,
        "claim",
        "add",
        "--statement",
        "The source says the fixture event occurred.",
        "--level",
        "measurement_validity",
        "--scope",
        "Synthetic fixture only.",
    ]) == 0
    claim = _cli_result(capsys)
    assert main([
        *global_args,
        "hypothesis",
        "propose",
        "--statement",
        "The fixture observation is unresolved.",
        "--parent-claim",
        claim["claim_id"],
        "--prediction",
        "A reviewed fixture note reports the observation.",
        "--null-model",
        "The reviewed fixture note does not report the observation.",
        "--falsification",
        "The reviewed fixture note contradicts the observation.",
    ]) == 0
    hypothesis = _cli_result(capsys)
    assert main([
        *global_args,
        "hypothesis",
        "stage",
        hypothesis["hypothesis_id"],
        "--confidence",
        "high",
        "--rationale",
        "Complete synthetic proposal for bridge export testing.",
    ]) == 0
    _cli_result(capsys)
    fixture = tmp_path / "fixture.csv"
    fixture.write_text("value\n1\n", encoding="utf-8")
    assert main([
        *global_args,
        "dataset",
        "register",
        "--id",
        "dataset-fixture",
        "--name",
        "Synthetic fixture source",
        "--role",
        "exploratory",
        "--file",
        str(fixture),
    ]) == 0
    _cli_result(capsys)
    assert main([
        *global_args,
        "evidence",
        "record",
        "--hypothesis",
        hypothesis["hypothesis_id"],
        "--claim",
        claim["claim_id"],
        "--direction",
        "inconclusive",
        "--summary",
        "The source is preserved but does not settle the proposition.",
        "--dataset",
        "dataset-fixture",
        "--analysis",
        "analysis-fixture",
        "--uncertainty",
        "Synthetic fixture has no inferential uncertainty.",
        "--scope",
        "Synthetic fixture only.",
        "--higher-conclusion-unsupported",
        "Any real-world scientific conclusion.",
        "--validation-tag",
        "source_assessment",
    ]) == 0
    evidence = _cli_result(capsys)

    output = tmp_path / "sherlock-export"
    assert main([
        *global_args,
        "sherlock",
        "export-evidence",
        "--evidence",
        evidence["evidence_id"],
        "--output",
        str(output),
        "--sherlock-kind",
        "assertion",
        "--sherlock-id",
        "assertion-fixture",
    ]) == 0
    exported = _cli_result(capsys)
    summary_path = Path(exported["summary_path"])
    link_path = Path(exported["bridge_link_path"])
    assert summary_path.is_file()
    assert link_path.is_file()
    assert exported["summary_sha256"] == hashlib.sha256(summary_path.read_bytes()).hexdigest()
    assert exported["bridge_link_sha256"] == hashlib.sha256(link_path.read_bytes()).hexdigest()

    schema = json.loads((ROOT / "schemas" / "sherlock-bridge-link.schema.json").read_text())
    bridge_link = json.loads(link_path.read_text())
    jsonschema.validate(bridge_link, schema)
    assert bridge_link["faraday_reference"]["id"] == evidence["evidence_id"]
    assert bridge_link["sherlock_reference"]["id"] == "assertion-fixture"
    assert bridge_link["authority_boundary"]["sherlock_note_is_faraday_evidence"] is False
    summary = json.loads(summary_path.read_text())
    assert summary["faraday_reference"]["id"] == evidence["evidence_id"]
    assert summary["authority_boundary"]["canonical_state_mutated_by_export"] is False


def test_cli_sherlock_evidence_export_is_write_once(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    global_args = ["--workspace", str(workspace), "--json"]
    assert main([*global_args, "workspace", "init"]) == 0
    _cli_result(capsys)
    assert main([
        *global_args,
        "inquiry",
        "create",
        "--id",
        "write-once",
        "--title",
        "Write once",
        "--statement",
        "Can exports avoid overwrite?",
    ]) == 0
    _cli_result(capsys)
    assert main([
        *global_args,
        "hypothesis",
        "propose",
        "--statement",
        "The bridge export remains write-once.",
        "--prediction",
        "Repeating an export to the same directory fails.",
        "--null-model",
        "Repeating an export overwrites the directory.",
        "--falsification",
        "A second export replaces the first files.",
    ]) == 0
    hypothesis = _cli_result(capsys)
    assert main([
        *global_args,
        "hypothesis",
        "stage",
        hypothesis["hypothesis_id"],
        "--confidence",
        "high",
        "--rationale",
        "Complete synthetic proposal for bridge export testing.",
    ]) == 0
    _cli_result(capsys)
    fixture = tmp_path / "write-once.csv"
    fixture.write_text("value\n1\n", encoding="utf-8")
    assert main([
        *global_args,
        "dataset",
        "register",
        "--id",
        "dataset-write-once",
        "--name",
        "Synthetic fixture source",
        "--role",
        "exploratory",
        "--file",
        str(fixture),
    ]) == 0
    _cli_result(capsys)
    assert main([
        *global_args,
        "evidence",
        "record",
        "--hypothesis",
        hypothesis["hypothesis_id"],
        "--direction",
        "inconclusive",
        "--summary",
        "The write-once export behavior is a software fixture.",
        "--dataset",
        "dataset-write-once",
        "--analysis",
        "analysis-write-once",
        "--uncertainty",
        "Synthetic fixture only.",
        "--scope",
        "Synthetic fixture only.",
        "--higher-conclusion-unsupported",
        "Any scientific conclusion.",
        "--validation-tag",
        "source_assessment",
    ]) == 0
    evidence = _cli_result(capsys)
    output = tmp_path / "sherlock-export"
    command = [
        *global_args,
        "sherlock",
        "export-evidence",
        "--evidence",
        evidence["evidence_id"],
        "--output",
        str(output),
    ]
    assert main(command) == 0
    _cli_result(capsys)
    assert main(command) == 2
    error = json.loads(capsys.readouterr().err)
    assert "already exists" in error["error"]["message"]
