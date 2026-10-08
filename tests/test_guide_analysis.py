"""G06 pinned synthetic methods, result ceilings, and adverse byte changes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_machine.addons.receipt import verify_execution_output
from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main


FIXTURES = Path(__file__).parent / "fixtures" / "guide"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(tmp_path: Path, capsys, label: str, spec_file: Path, data_file: Path) -> tuple[dict, Path, str]:
    output = tmp_path / label
    assert main([
        "--workspace", str(tmp_path / "unused-workspace"), "--json",
        "analysis", "run", "--spec-file", str(spec_file),
        "--data-file", str(data_file), "--output", str(output),
        "--expect-spec-sha256", _sha(spec_file),
        "--expect-input-sha256", _sha(data_file),
    ]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    receipt_sha = _sha(output / "execution-receipt.json")
    verified = verify_execution_output(output, receipt_sha)
    assert verified["result"] == result["result"]
    assert verified["scientific_evidence_eligible"] is False
    receipt = result["receipt"]
    assert receipt["specification"]["sha256"] == _sha(spec_file)
    assert receipt["input"]["sha256"] == _sha(data_file)
    assert receipt["implementation"]["sha256"] == _sha(Path(receipt["implementation"]["locator"]))
    assert receipt["output"]["sha256"] == _sha(output / "analysis-result.json")
    assert receipt["scientific_evidence_eligible"] is False
    assert all(gate["status"] == "passed" for gate in receipt["quality_gates"])
    return result, output, receipt_sha


def _write_case(tmp_path: Path, label: str, spec: dict, csv_text: str) -> tuple[Path, Path]:
    spec_file = tmp_path / f"{label}-spec.json"
    data_file = tmp_path / f"{label}.csv"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")
    data_file.write_text(csv_text, encoding="utf-8")
    return spec_file, data_file


def test_three_bounded_methods_and_receipts(tmp_path: Path, capsys) -> None:
    independent, output, receipt_sha = _run(
        tmp_path, capsys, "independent",
        FIXTURES / "independent-analysis.json",
        FIXTURES / "independent-two-group.csv",
    )
    replay, _, _ = _run(
        tmp_path, capsys, "independent-replay",
        FIXTURES / "independent-analysis.json",
        FIXTURES / "independent-two-group.csv",
    )
    assert replay["result"] == independent["result"]
    body = independent["result"]["result"]
    assert independent["result"]["method"] == "independent_mean_difference_ci"
    assert body["mean_difference_first_minus_second"] == 3.0
    assert body["confidence_interval"]["lower"] <= 3 <= body["confidence_interval"]["upper"]
    assert body["exclusion_report"]["excluded_records"] == []
    assert body["independent_unit_check"]["status"] == "unique_identifiers"
    assert body["assumptions"]
    assert "Causal interpretation additionally requires" in independent["result"]["claim_ceiling"]

    paired_spec, paired_data = _write_case(tmp_path, "paired", {
        "method": "paired_mean_difference_ci",
        "claim_ceiling": "Synthetic within-pair comparison only.",
        "outcome_column": "outcome", "group_column": "group",
        "groups": ["treatment", "control"], "pair_column": "pair",
        "study_design": "paired", "seed": 17, "bootstrap_resamples": 1000,
    }, "pair,group,outcome\np1,treatment,4\np1,control,2\np2,treatment,6\np2,control,3\np3,treatment,7\np3,control,3\n")
    paired, _, _ = _run(tmp_path, capsys, "paired-output", paired_spec, paired_data)
    paired_body = paired["result"]["result"]
    assert paired_body["study_design"] == "paired"
    assert paired_body["n_pairs"] == 3
    assert paired_body["confidence_interval"]["lower"] <= paired_body["mean_difference_first_minus_second"] <= paired_body["confidence_interval"]["upper"]
    assert paired_body["assumptions"]
    assert paired["result"]["maximum_inference_level"] == "design_conditional_effect"

    observational_spec, observational_data = _write_case(tmp_path, "observational", {
        "method": "adjusted_linear_effect",
        "claim_ceiling": "Synthetic adjusted association only; no causal identification.",
        "outcome_column": "outcome", "group_column": "group",
        "groups": ["treatment", "control"], "unit_column": "unit",
        "covariate_columns": ["baseline"], "study_design": "independent_groups",
        "confidence_level": 0.95,
    }, "unit,group,outcome,baseline\nu1,treatment,8,1\nu2,treatment,10,2\nu3,treatment,9,3\nu4,treatment,13,4\nu5,control,4,1\nu6,control,6,2\nu7,control,7,3\nu8,control,8,4\n")
    observational, _, _ = _run(
        tmp_path, capsys, "observational-output", observational_spec, observational_data
    )
    observed_body = observational["result"]["result"]
    assert observed_body["adjustment_columns"] == ["baseline"]
    assert observed_body["robust_confidence_interval"]["lower"] <= observed_body["adjusted_mean_difference_first_minus_second"] <= observed_body["robust_confidence_interval"]["upper"]
    assert observed_body["exclusion_report"]["excluded_records"] == []
    assert observed_body["diagnostics"]
    assert "does not verify" in observational["result"]["claim_ceiling"]

    receipt_file = output / "execution-receipt.json"
    receipt_file.write_bytes(receipt_file.read_bytes() + b" ")
    with pytest.raises(ValidationError, match="trusted hash"):
        verify_execution_output(output, receipt_sha)


def test_paired_as_independent_and_post_result_plan_switch_fail(tmp_path: Path, capsys) -> None:
    original_spec = FIXTURES / "independent-analysis.json"
    original_data = FIXTURES / "independent-two-group.csv"
    _run(tmp_path, capsys, "first-run", original_spec, original_data)
    trusted_spec = _sha(original_spec)
    trusted_data = _sha(original_data)

    switched = json.loads(original_spec.read_text(encoding="utf-8"))
    switched["method"] = "permutation_mean_difference"
    switched["permutations"] = 1000
    switched_file = tmp_path / "switched-spec.json"
    switched_file.write_text(json.dumps(switched), encoding="utf-8")
    switched_output = tmp_path / "switched-output"
    assert main([
        "--workspace", str(tmp_path / "unused-workspace"), "--json", "analysis", "run",
        "--spec-file", str(switched_file), "--data-file", str(original_data),
        "--output", str(switched_output), "--expect-spec-sha256", trusted_spec,
        "--expect-input-sha256", trusted_data,
    ]) == 2
    assert "specification does not match expected SHA-256" in capsys.readouterr().err
    assert not switched_output.exists()

    pair_data = tmp_path / "repeated-pairs.csv"
    pair_data.write_text(
        "pair,group,outcome\np1,treatment,4\np1,control,2\np2,treatment,6\np2,control,3\n",
        encoding="utf-8",
    )
    false_independent_spec, _ = _write_case(tmp_path, "false-independent", {
        "method": "independent_mean_difference_ci",
        "claim_ceiling": "Synthetic only.",
        "outcome_column": "outcome", "group_column": "group",
        "groups": ["treatment", "control"], "unit_column": "pair",
        "study_design": "independent_groups", "seed": 17,
    }, "unit,group,outcome\nx,control,1\ny,treatment,2\n")
    false_output = tmp_path / "false-independent-output"
    assert main([
        "--workspace", str(tmp_path / "unused-workspace"), "--json", "analysis", "run",
        "--spec-file", str(false_independent_spec), "--data-file", str(pair_data),
        "--output", str(false_output), "--expect-spec-sha256", _sha(false_independent_spec),
        "--expect-input-sha256", _sha(pair_data),
    ]) == 2
    assert "repeated independent-unit identifier" in capsys.readouterr().err
    assert not false_output.exists()

    changed_data = tmp_path / "changed.csv"
    changed_data.write_bytes(original_data.read_bytes() + b"\n")
    changed_output = tmp_path / "changed-output"
    assert main([
        "--workspace", str(tmp_path / "unused-workspace"), "--json", "analysis", "run",
        "--spec-file", str(original_spec), "--data-file", str(changed_data),
        "--output", str(changed_output), "--expect-spec-sha256", trusted_spec,
        "--expect-input-sha256", trusted_data,
    ]) == 2
    assert "input bytes do not match expected SHA-256" in capsys.readouterr().err
    assert not changed_output.exists()

    wrong_scale = tmp_path / "wrong-scale.csv"
    wrong_scale.write_text(
        "unit,group,outcome\nu1,treatment,high\nu2,treatment,low\nu3,control,low\nu4,control,high\n",
        encoding="utf-8",
    )
    wrong_output = tmp_path / "wrong-scale-output"
    assert main([
        "--workspace", str(tmp_path / "unused-workspace"), "--json", "analysis", "run",
        "--spec-file", str(original_spec), "--data-file", str(wrong_scale),
        "--output", str(wrong_output), "--expect-spec-sha256", trusted_spec,
        "--expect-input-sha256", _sha(wrong_scale),
    ]) == 2
    assert "non-numeric outcome" in capsys.readouterr().err
    assert not wrong_output.exists()
