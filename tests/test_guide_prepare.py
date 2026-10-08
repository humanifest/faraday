"""W01 one-command, provider-free guide packet on synthetic inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_machine.interfaces.cli import main
from test_guide_design import _brief as design_brief


FIXTURES = Path(__file__).parent / "fixtures" / "guide"


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    plan = json.loads((FIXTURES / "inquiry-plan.json").read_text(encoding="utf-8"))
    brief = _write(tmp_path / "brief.json", {
        "original_statement": plan["original_question"],
        "title": "Synthetic guide packet", "population": plan["population"],
        "unit_of_observation": "One fabricated independent unit",
        "outcome": "Fabricated score", "comparison": "treatment versus control",
        "time_window": "One synthetic post-exposure measurement",
        "decision": plan["decision"],
        "minimum_evidence": "Prospectively reviewed independent comparison",
        "decision_owner": "Synthetic decision owner",
        "decision_change_criteria": ["A precise independently reviewed effect outside a fixed neutral range"],
        "available_data_sources": ["Fabricated four-row CSV fixture"],
        "ethical_constraints": ["No real participants or source data in this fixture"],
    })
    design = design_brief()
    design["question"] = plan["original_question"]
    design["outcome"] = "Fabricated score"
    design["unit_of_observation"] = "One fabricated independent unit"
    design["decision"] = plan["decision"]
    design["comparison"] = "treatment versus control"
    design["outcome_data_column"] = "outcome"
    design["outcome_unit"] = "synthetic points"
    design_file = _write(tmp_path / "design.json", design)
    spec = json.loads((FIXTURES / "independent-analysis.json").read_text(encoding="utf-8"))
    spec["measurement_definitions"] = [{
        "measurement_id": "synthetic-outcome-v1", "data_column": "outcome",
        "scale_type": "interval", "unit": "synthetic points",
        "admissible_values": [], "missing_value_codes": ["<blank>"],
        "valid_min": 0.0, "valid_max": 100.0,
    }]
    spec_file = _write(tmp_path / "spec.json", spec)
    return brief, design_file, spec_file, FIXTURES / "independent-two-group.csv"


def _call(workspace: Path, capsys, *arguments: str) -> tuple[int, dict]:
    code = main(["--workspace", str(workspace), "--json", "guide", "prepare", *arguments])
    captured = capsys.readouterr()
    return code, json.loads(captured.out if code == 0 else captured.err)


def test_complete_synthetic_packet_is_read_only_and_not_scientific_evidence(tmp_path: Path, capsys) -> None:
    brief, design, spec, data = _inputs(tmp_path)
    workspace = tmp_path / "workspace"
    digest = hashlib.sha256(data.read_bytes()).hexdigest()
    code, response = _call(
        workspace, capsys, "--brief-file", str(brief),
        "--design-brief-file", str(design),
        "--analysis-spec-file", str(spec), "--data-file", str(data),
        "--expect-data-sha256", digest,
    )
    assert code == 0 and response["ok"] is True
    packet = response["result"]
    assert packet["packet_version"] == 1
    assert packet["status"] == "ready_for_review"
    assert packet["blocking_issues"] == packet["unresolved_fields"] == []
    assert packet["original_statement"] == json.loads(brief.read_text())["original_statement"]
    assert packet["method_preview"]["method_id"] == "independent_mean_difference_ci"
    assert packet["method_preview"]["missing_spec_fields"] == []
    assert packet["data_preview"]["row_count"] == 4
    assert packet["data_preview"]["scientific_evidence_eligible"] is False
    assert packet["input_sha256"]["data"] == digest
    assert {item["role"] for item in packet["competing_model_questions"]} == {
        "null", "measurement_error", "selection_or_confounding", "user_explanation",
    }
    assert all(not item["asserts_explanation"] for item in packet["competing_model_questions"])
    assert packet["analysis_performed"] is False
    assert packet["canonical_write_performed"] is False
    assert packet["scientific_evidence_eligible"] is False
    assert not workspace.exists()


def test_missing_and_conflicting_inputs_fail_closed(tmp_path: Path, capsys) -> None:
    brief, design, spec, data = _inputs(tmp_path)
    workspace = tmp_path / "workspace"
    sparse = _write(tmp_path / "sparse.json", {"original_statement": "Could X matter?"})
    code, response = _call(workspace, capsys, "--brief-file", str(sparse))
    assert code == 0
    packet = response["result"]
    assert packet["status"] == "needs_clarification"
    assert "outcome" in packet["unresolved_fields"]
    assert "observation_data" in packet["unresolved_fields"]
    assert packet["intake"]["supplied_fields"]["outcome"] is None

    for extra in (
        ("--data-file", str(data)),
        ("--analysis-spec-file", str(spec), "--data-file", str(data),
         "--expect-data-sha256", "0" * 64),
    ):
        code, response = _call(workspace, capsys, "--brief-file", str(brief), *extra)
        assert code == 2 and response["ok"] is False

    bad_method = json.loads(spec.read_text())
    bad_method["method"] = "unregistered_ai_chosen_test"
    _write(spec, bad_method)
    code, response = _call(workspace, capsys, "--brief-file", str(brief),
                           "--analysis-spec-file", str(spec))
    assert code == 2 and response["ok"] is False

    _, design, spec, data = _inputs(tmp_path)
    mismatch = json.loads(design.read_text())
    mismatch["outcome_scale"] = "ordinal"
    _write(design, mismatch)
    code, response = _call(workspace, capsys, "--brief-file", str(brief),
                           "--design-brief-file", str(design),
                           "--analysis-spec-file", str(spec), "--data-file", str(data))
    assert code == 0
    assert response["result"]["status"] == "blocked"
    assert any("scale" in issue for issue in response["result"]["blocking_issues"])
    assert "research analysis run" not in {step["route"] for step in response["result"]["next_steps"]}

    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_bytes(data.read_bytes().replace(b"u04,treatment,6", b"u01,treatment,6"))
    code, response = _call(workspace, capsys, "--brief-file", str(brief),
                           "--analysis-spec-file", str(spec), "--data-file", str(duplicate))
    assert code == 0
    assert response["result"]["status"] == "blocked"
    assert "CSV inventory has data-quality issues" in response["result"]["blocking_issues"]
    assert not workspace.exists()
