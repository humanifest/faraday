from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_machine.addons.models import AddonManifest
from research_machine.addons.registry import AddonRegistry, default_registry
from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main


def _result(capsys) -> object:
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    return payload["result"]


def test_default_registry_exposes_general_and_domain_addons() -> None:
    registry = default_registry(include_installed=False)
    assert [item.addon_id for item in registry.list()] == ["general_science", "physics"]
    addon, method = registry.resolve_method("permutation_mean_difference")
    assert addon.addon_id == "general_science"
    assert "seed" in method.required_spec_fields
    physics, physics_method = registry.resolve_method("pendulum_gravity_estimate")
    assert physics.addon_id == "physics"
    assert physics_method.required_spec_fields == ("length_column", "period_column")


def test_registry_rejects_duplicate_addon_ids() -> None:
    registry = AddonRegistry()
    manifest = AddonManifest("example", "Example", "1", "any", "Example")
    registry.register(manifest)
    with pytest.raises(ValidationError, match="duplicate add-on id"):
        registry.register(manifest)


def test_cli_lists_addons_without_initializing_workspace(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "not-created"
    assert main(["--workspace", str(workspace), "--json", "addon", "list"]) == 0
    values = _result(capsys)
    assert {item["addon_id"] for item in values} >= {"general_science", "physics"}
    assert not workspace.exists()


def test_general_analysis_is_deterministic_and_non_evidentiary(
    tmp_path: Path, capsys
) -> None:
    data = tmp_path / "observations.csv"
    data.write_text("group,outcome\ncontrol,1\ncontrol,2\ntreatment,4\ntreatment,5\n")
    spec = tmp_path / "analysis.json"
    spec.write_text(
        json.dumps(
            {
                "method": "permutation_mean_difference",
                "analysis_id": "registered-comparison-v1",
                "outcome_column": "outcome",
                "group_column": "group",
                "groups": ["treatment", "control"],
                "permutations": 500,
                "seed": 8128,
                "missing_data_policy": "complete_case",
                "claim_ceiling": "Difference in group means in this dataset only.",
            }
        )
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    common = ["--workspace", str(tmp_path / "unused"), "--json", "analysis", "run", "--spec-file", str(spec), "--data-file", str(data)]
    assert main([*common, "--output", str(first)]) == 0
    first_result = _result(capsys)
    assert main([*common, "--output", str(second)]) == 0
    second_result = _result(capsys)
    assert first_result["result"] == second_result["result"]
    assert first_result["receipt"]["scientific_evidence_eligible"] is False
    receipt = json.loads((first / "execution-receipt.json").read_text())
    result_bytes = (first / "analysis-result.json").read_bytes()
    import hashlib

    assert receipt["output"]["sha256"] == hashlib.sha256(result_bytes).hexdigest()


def test_physics_addon_executes_through_the_same_contract(
    tmp_path: Path, capsys
) -> None:
    data = tmp_path / "pendulum.csv"
    data.write_text("length_m,period_s\n0.25,1.003\n0.50,1.419\n1.00,2.007\n")
    spec = tmp_path / "analysis.json"
    spec.write_text(
        json.dumps(
            {
                "method": "pendulum_gravity_estimate",
                "length_column": "length_m",
                "period_column": "period_s",
                "claim_ceiling": "Small-angle model estimate for these trials only.",
            }
        )
    )
    output = tmp_path / "physics-output"
    assert main(["--json", "analysis", "run", "--spec-file", str(spec), "--data-file", str(data), "--output", str(output)]) == 0
    result = _result(capsys)
    estimate = result["result"]["result"]["gravity_mean_m_s2"]
    assert 9.7 < estimate < 9.9
    assert result["receipt"]["addon"]["addon_id"] == "physics"


def test_analysis_refuses_overwrite_and_undeclared_claim_ceiling(
    tmp_path: Path, capsys
) -> None:
    data = tmp_path / "observations.csv"
    data.write_text("x\n1\n2\n")
    spec = tmp_path / "analysis.json"
    spec.write_text(json.dumps({"method": "descriptive_summary", "columns": ["x"]}))
    output = tmp_path / "output"
    assert main(["--json", "analysis", "run", "--spec-file", str(spec), "--data-file", str(data), "--output", str(output)]) == 2
    assert "claim_ceiling" in json.loads(capsys.readouterr().err)["error"]["message"]

    spec.write_text(json.dumps({"method": "descriptive_summary", "columns": ["x"], "claim_ceiling": "Description only."}))
    output.mkdir()
    (output / "preserved.txt").write_text("keep")
    assert main(["--json", "analysis", "run", "--spec-file", str(spec), "--data-file", str(data), "--output", str(output)]) == 2
    assert "not empty" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert (output / "preserved.txt").read_text() == "keep"
