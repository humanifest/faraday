#!/usr/bin/env python3
"""Fail-closed, local synthetic gate for the AI science guide software slice."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "guide"
TEST_FILES = tuple(f"tests/test_guide_{name}.py" for name in (
    "baseline", "contract", "intake", "models", "design", "data",
    "analysis", "iteration", "unavailable", "end_to_end",
))
FIXTURE_FILES = ("inquiry-plan.json", "independent-analysis.json", "independent-two-group.csv")
PINNED_FIXTURE_SHA256 = {
    "inquiry-plan.json": "298b32ed8952619810c55e5d0d7ba54a0e78432aa200f9ca9c1fc393df3e6ea3",
    "independent-analysis.json": "918da3201e425522b085849c64a3fa59bf061add590fc4d41c0fc6bd26570535",
    "independent-two-group.csv": "0191fb3821e9746f0e7fe4bbee46d39b7786c5d090a8a2edfacf157f1698843d",
}
REQUIRED_CASES = {
    "three_supported_designs": "tests/test_guide_analysis.py::test_three_bounded_methods_and_receipts",
    "no_usable_data": "tests/test_guide_end_to_end.py::test_no_usable_data_and_failed_quality_gate_block_readiness",
    "wrong_scale": "tests/test_guide_analysis.py::test_paired_as_independent_and_post_result_plan_switch_fail",
    "duplicate_units": "tests/test_guide_baseline.py::test_existing_synthetic_guide_seams_and_adverse_identity",
    "paired_as_independent": "tests/test_guide_analysis.py::test_paired_as_independent_and_post_result_plan_switch_fail",
    "missingness_and_exclusions": "tests/test_design_aware_analysis.py::test_adjusted_linear_effect_reports_registered_complete_case_exclusions",
    "changed_input_bytes": "tests/test_guide_analysis.py::test_paired_as_independent_and_post_result_plan_switch_fail",
    "incorrect_receipt_hash": "tests/test_guide_analysis.py::test_three_bounded_methods_and_receipts",
    "incorrect_context_hash": "tests/test_guide_contract.py::test_guide_reuses_hash_bound_read_only_collaborator_contract",
    "failed_quality_gate": "tests/test_guide_baseline.py::test_existing_synthetic_guide_seams_and_adverse_identity",
    "negative_and_inconclusive_result": "tests/test_guide_iteration.py::test_synthesis_retains_weakening_and_inconclusive_observations",
    "no_discriminating_next_experiment": "tests/test_guide_iteration.py::test_synthesis_retains_weakening_and_inconclusive_observations",
    "ai_self_approval": "tests/test_guide_models.py::test_empty_alternatives_and_claimed_approval_fail_closed",
    "post_result_plan_change": "tests/test_guide_analysis.py::test_paired_as_independent_and_post_result_plan_switch_fail",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "FARADAY_PYTHON": sys.executable,
        "RESEARCH_ADDON_PATH": "",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    })
    env.pop("PYTHONPATH", None)
    env.pop("RESEARCH_MACHINE_NOTEBOOK_INTEGRATION", None)
    return env


def _command(argv: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=ROOT, env=_environment(), text=True,
        capture_output=True, timeout=timeout, check=False,
    )


def _cli(workspace: Path, *args: str, expected: int = 0) -> dict:
    result = _command([str(ROOT / "research"), "--workspace", str(workspace), "--json", *args])
    _require(result.returncode == expected,
             f"research {' '.join(args[:2])} exited {result.returncode}: {result.stderr[:500]}")
    stream = result.stdout if expected == 0 else result.stderr
    payload = json.loads(stream)
    _require(payload["ok"] is (expected == 0), "CLI JSON success flag disagrees with exit code")
    return payload.get("result", payload.get("error"))


def run_journey(root: Path) -> dict:
    """Run the public guide and research routes in an isolated temporary directory."""
    workspace = root / "workspace"
    plan = json.loads((FIXTURES / "inquiry-plan.json").read_text(encoding="utf-8"))
    data = FIXTURES / "independent-two-group.csv"
    spec = FIXTURES / "independent-analysis.json"
    data_hash, spec_hash = _sha(data), _sha(spec)
    brief_file = root / "brief.json"
    brief_file.write_text(json.dumps({
        "original_statement": plan["original_question"],
        "title": "Synthetic guide end to end",
        "population": plan["population"],
        "decision": plan["decision"],
    }), encoding="utf-8")
    intake = _cli(workspace, "guide", "intake", "--brief-file", str(brief_file))
    _require(not workspace.exists() and intake["canonical_write_performed"] is False,
             "guide intake changed canonical state")
    _require(intake["original_statement"] == plan["original_question"] and
             "outcome" in intake["unresolved_fields"], "intake inferred a missing answer")

    _cli(workspace, "workspace", "init")
    _cli(workspace, "inquiry", "create", "--id", "guide-end-to-end-v1",
         "--title", "Synthetic guide end to end", "--statement", plan["original_question"],
         "--decision", plan["decision"])
    _cli(workspace, "question", "add", "--text", "Is the measurement valid?")
    hypothesis = _cli(
        workspace, "hypothesis", "propose", "--statement",
        "Treatment could change the synthetic outcome.",
        "--prediction", "A prospective comparison would differ directionally.",
        "--null-model", "No decision-relevant change exists.",
        "--competing-model", "Measurement error could explain a contrast.",
        "--falsification", "A precise prospective comparison lies in the neutral range.",
        "--generated-by", "fixed-synthetic-guide-fixture",
    )
    _require(hypothesis["workflow_state"] == "unreviewed", "AI proposal gained review authority")
    staged = _cli(workspace, "hypothesis", "stage", hypothesis["hypothesis_id"],
                  "--confidence", "high", "--rationale",
                  "Synthetic fixture stages exploratory review without activating a claim.")
    _require(staged["workflow_state"] == "pending_review", "staging activated a hypothesis")

    data_spec = root / "data-spec.json"
    data_spec.write_text(json.dumps({
        "method": "independent_mean_difference_ci", "study_design": "independent_groups",
        "unit_column": "unit", "group_column": "group", "outcome_column": "outcome",
        "groups": ["treatment", "control"],
        "measurement_definitions": [{
            "measurement_id": "synthetic-outcome-v1", "data_column": "outcome",
            "scale_type": "interval", "unit": "synthetic points",
            "admissible_values": [], "missing_value_codes": ["<blank>"],
            "valid_min": 0.0, "valid_max": 100.0,
        }],
    }), encoding="utf-8")
    inventory = _cli(workspace, "guide", "data", "--file", str(data),
                     "--spec-file", str(data_spec), "--expect-sha256", data_hash)
    _require(inventory["raw_sha256"] == data_hash and inventory["quality_issues"] == [] and
             inventory["scientific_evidence_eligible"] is False and
             "measurement_custody_unverified" in inventory["readiness_gaps"],
             "data preview omitted byte identity or custody ceiling")
    outcomes = []
    for index in (1, 2):
        output = root / f"analysis-{index}"
        execution = _cli(
            workspace, "analysis", "run", "--spec-file", str(spec),
            "--data-file", str(data), "--output", str(output),
            "--expect-spec-sha256", spec_hash, "--expect-input-sha256", data_hash,
        )
        receipt = execution["receipt"]
        _require(receipt["input"]["sha256"] == data_hash and
                 receipt["specification"]["sha256"] == spec_hash and
                 receipt["output"]["sha256"] == _sha(output / "analysis-result.json") and
                 receipt["implementation"]["sha256"] ==
                 _sha(Path(receipt["implementation"]["locator"])) and
                 receipt["scientific_evidence_eligible"] is False and
                 all(gate["status"] == "passed" for gate in receipt["quality_gates"]),
                 "analysis receipt failed independent byte or quality inspection")
        result = execution["result"]
        _require(result["method"] == plan["method_id"] and
                 result["result"]["mean_difference_first_minus_second"] == 3.0 and
                 "Causal interpretation additionally requires" in result["claim_ceiling"],
                 "analysis selected an unexpected method or widened its conclusion")
        outcomes.append(result)
    _require(outcomes[0] == outcomes[1], "frozen analysis replay drifted")

    first = _cli(workspace, "synthesis", "build")
    report_path = workspace / first["path"]
    _require(report_path.read_text(encoding="utf-8") == first["content"],
             "synthesis output differs from report bytes")
    report_hash = _sha(report_path)
    second = _cli(workspace, "synthesis", "build")
    _require(second["content"] == first["content"] and _sha(report_path) == report_hash,
             "synthesis replay drifted")
    _require(plan["original_question"] in first["content"] and
             "Measurement error could explain a contrast." in first["content"] and
             "Is the measurement valid?" in first["content"] and
             "human ratification remains pending" in first["content"].lower(),
             "synthesis omitted the original question, alternatives, or uncertainty")
    audit = _cli(workspace, "workspace", "audit", "--fail-on", "error")
    _require(audit["structurally_valid"] is True and
             audit["conclusion_ceiling"] == "unclassified evidence only" and
             not any(audit["capabilities"].values()) and
             not any(item["severity"] == "error" for item in audit["findings"]),
             "workspace audit did not pass")
    ledger = _cli(workspace, "workspace", "verify")
    _require(ledger["valid"] is True and ledger["events"] >= 4 and
             isinstance(ledger["head_hash"], str) and len(ledger["head_hash"]) == 64,
             "ledger verification failed or had no meaningful events")
    state = _cli(workspace, "inquiry", "show")
    _require(state["hypotheses"][0]["workflow_state"] == "pending_review" and
             state["recommendations"] == [], "an unauthorized transition occurred")
    return {
        "fixture_id": plan["fixture_id"], "fixture_version": 1,
        "input_sha256": data_hash, "specification_sha256": spec_hash,
        "method": outcomes[0]["method"], "report_sha256": report_hash,
        "ledger_head": ledger["head_hash"], "ledger_events": ledger["events"],
        "audit_errors": 0, "replay_stable": True,
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit a single bounded JSON receipt")
    args = parser.parse_args()
    receipt: dict = {"software_fixture_ready": False, "checks": {}}
    try:
        _require(sys.version_info >= (3, 11), "Python 3.11+ is required")
        for package in ("pytest", "jsonschema"):
            _require(importlib.util.find_spec(package) is not None,
                     f"declared test dependency {package} is unavailable")
        commit = _command(["git", "rev-parse", "HEAD"])
        _require(commit.returncode == 0, "cannot identify exact Git commit")
        receipt["commit_sha"] = commit.stdout.strip()
        _require(all((FIXTURES / name).is_file() for name in FIXTURE_FILES),
                 "required fixture bytes are missing")
        fixture_hashes = {name: _sha(FIXTURES / name) for name in FIXTURE_FILES}
        _require(fixture_hashes == PINNED_FIXTURE_SHA256,
                 "source fixture bytes drifted from the G00 baseline")
        receipt["fixture_sha256"] = fixture_hashes
        status = _command(["git", "status", "--porcelain", "--untracked-files=normal"])
        _require(status.returncode == 0 and not status.stdout.strip(),
                 "worktree must be clean for exact-commit verification")
        for name in TEST_FILES:
            _require((ROOT / name).is_file(), f"required guide test missing: {name}")
        with tempfile.TemporaryDirectory(prefix="faraday-guide-") as directory:
            receipt["journey"] = run_journey(Path(directory))
        receipt["checks"]["public_journey_audit_ledger_replay"] = "passed"
        focused = _command([sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "-p", "no:cacheprovider", *sorted(set(REQUIRED_CASES.values()))], timeout=600)
        _require(focused.returncode == 0, f"guide adverse matrix failed: {focused.stdout[-500:]} {focused.stderr[-300:]}")
        focused_summary = focused.stdout.strip().splitlines()[-1]
        _require(re.search(r"\b\d+ passed\b", focused_summary) is not None and
                 not re.search(r"\b(?:skipped|xfailed|xpassed)\b", focused_summary),
                 "guide adverse matrix did not execute every required test")
        receipt["checks"]["guide_adverse_matrix"] = focused_summary[:200]
        receipt["checks"]["required_cases"] = sorted(REQUIRED_CASES)
        full = _command([sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "-p", "no:cacheprovider", "tests"], timeout=1800)
        _require(full.returncode == 0, f"full suite failed: {full.stdout[-500:]} {full.stderr[-300:]}")
        full_summary = full.stdout.strip().splitlines()[-1]
        _require(re.search(r"\b\d+ passed\b", full_summary) is not None,
                 "full suite returned no pass count")
        receipt["checks"]["full_suite"] = full_summary[:200]
        final_commit = _command(["git", "rev-parse", "HEAD"])
        final_status = _command(["git", "status", "--porcelain", "--untracked-files=normal"])
        _require(final_commit.returncode == 0 and final_commit.stdout.strip() == receipt["commit_sha"] and
                 final_status.returncode == 0 and not final_status.stdout.strip() and
                 fixture_hashes == {name: _sha(FIXTURES / name) for name in FIXTURE_FILES},
                 "commit, worktree, or fixture bytes changed during the gate")
        receipt["software_fixture_ready"] = True
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        receipt["error"] = str(exc)[:800]
    if args.json:
        print(json.dumps(receipt, sort_keys=True))
    else:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["software_fixture_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
