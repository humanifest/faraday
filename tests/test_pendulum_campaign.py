from __future__ import annotations

import json
from pathlib import Path

import pytest

from campaigns.newtonian_pendulum.executor import execute_suite
from campaigns.newtonian_pendulum.fixtures import generate_fixtures
from campaigns.newtonian_pendulum.run_campaign import SPEC_PATH, build_workspace


def _gate_statuses(report: dict[str, object]) -> dict[str, str]:
    gates = report["quality_gates"]
    assert isinstance(gates, list)
    return {
        str(gate["gate_id"]): str(gate["status"])
        for gate in gates
        if isinstance(gate, dict)
    }


def test_suite_recovers_all_laws_and_fails_closed(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixtures"
    generate_fixtures(SPEC_PATH, fixture_root)
    report = execute_suite(fixture_root, SPEC_PATH)

    assert report["synthetic"] is True
    assert report["scientific_evidence_eligible"] is False
    assert set(_gate_statuses(report).values()) == {"passed"}

    cases = {
        str(case["case_id"]): case
        for case in report["cases"]
        if isinstance(case, dict)
    }
    expected_models = {
        "clean_square_root": "square_root",
        "constant_control": "constant",
        "linear_control": "linear",
        "registered_dropout": "square_root",
    }
    for case_id, expected_model in expected_models.items():
        case = cases[case_id]
        assert case["valid"] is True
        assert case["expectation_met"] is True
        assert case["primary_analysis"]["selected_model"] == expected_model
        assert case["independent_analysis"]["selected_model"] == expected_model

    for case in cases.values():
        if case["expected_valid"]:
            continue
        statuses = _gate_statuses(case)
        assert case["valid"] is False
        assert case["expectation_met"] is True
        assert statuses[case["expected_failed_gate"]] == "failed"


def test_large_angle_fit_is_not_misreported_as_valid(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixtures"
    generate_fixtures(SPEC_PATH, fixture_root)
    report = execute_suite(fixture_root, SPEC_PATH)
    large_angle = next(
        case for case in report["cases"] if case["case_id"] == "large_angle"
    )

    assert large_angle["primary_analysis"]["selected_model"] == "square_root"
    assert large_angle["independent_analysis"]["selected_model"] == "square_root"
    assert large_angle["valid"] is False
    assert _gate_statuses(large_angle)["small-angle-boundary"] == "failed"


def test_fixture_tampering_breaks_known_result_gate(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixtures"
    generate_fixtures(SPEC_PATH, fixture_root)
    observations = fixture_root / "clean_square_root" / "observations.csv"
    observations.write_text(
        observations.read_text(encoding="utf-8").replace("clock-a", "clock-z", 1),
        encoding="utf-8",
    )

    report = execute_suite(fixture_root, SPEC_PATH)

    assert _gate_statuses(report)["fixture-integrity"] == "failed"
    assert _gate_statuses(report)["known-result-reproduction"] == "failed"


def test_end_to_end_workspace_retains_but_does_not_promote_synthetic_run(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "run"
    summary = build_workspace(output_root, human_reviewed=True)

    assert summary["run_status"] == "completed"
    assert summary["synthetic"] is True
    assert summary["scientific_evidence_eligible"] is False
    assert set(summary["suite_quality_gates"].values()) == {"passed"}
    assert summary["rigor_audit"]["structurally_valid"] is True
    assert summary["rigor_audit"]["evidence_counts"]["total"] == 0
    assert summary["ledger_verification"]["valid"] is True
    assert any(
        finding["code"] == "SYNTHETIC_KNOWN_RESULT_CALIBRATION_PASSED"
        for finding in summary["rigor_audit"]["findings"]
    )

    report = json.loads(
        (output_root / "artifacts" / "suite-report.json").read_text(encoding="utf-8")
    )
    assert report["conclusion"].endswith(
        "this is not empirical evidence for Newtonian physics."
    )
    synthesis = (
        output_root
        / ".research"
        / str(summary["synthesis_path"])
    ).read_text(encoding="utf-8")
    assert "Calibration and ineligible run outcomes" in synthesis
    assert "required gates passed 8/8" in synthesis
    assert "Conclusion ceiling: **unclassified evidence only**" in synthesis


def test_confirmatory_workspace_requires_explicit_human_review(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit human review"):
        build_workspace(tmp_path / "unreviewed")

    assert not (tmp_path / "unreviewed").exists()
