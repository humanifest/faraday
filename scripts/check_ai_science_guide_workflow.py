#!/usr/bin/env python3
"""Exact-commit local gate for Faraday's provider-free AI science guide workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if __package__:
    from .check_ai_science_guide_goal import ROOT, _command, _sha
else:
    from check_ai_science_guide_goal import ROOT, _command, _sha


FIXTURES = ROOT / "tests" / "fixtures" / "guide"
WORKFLOW_INPUTS = FIXTURES / "workflow-inputs.json"
WORKFLOW_INPUTS_SHA256 = "3be59e999923f3415ded25d21b737362fe54504e49bfd18730c6b016de5e5f8e"
ANALYSIS_SPEC = FIXTURES / "independent-analysis.json"
DATA = FIXTURES / "independent-two-group.csv"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _cli(workspace: Path, *args: str) -> tuple[dict, str]:
    completed = _command([str(ROOT / "research"), "--workspace", str(workspace), "--json", *args])
    _require(completed.returncode == 0,
             f"research {' '.join(args[:2])} exited {completed.returncode}: {completed.stderr[:500]}")
    payload = json.loads(completed.stdout)
    _require(payload.get("ok") is True and "result" in payload,
             "research did not return a successful JSON result")
    return payload["result"], completed.stdout


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _content_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def run_workflow(root: Path) -> dict:
    fixture = json.loads(WORKFLOW_INPUTS.read_text(encoding="utf-8"))
    _require(fixture["fixture_id"] == "guide-workflow-independent-v1" and
             fixture["fixture_version"] == 1, "workflow fixture identity changed")
    workspace = root / "workspace"
    brief, design, data_spec = (root / f"{name}.json" for name in ("brief", "design", "data-spec"))
    for path, key in ((brief, "brief"), (design, "design"), (data_spec, "data_spec")):
        _write_json(path, fixture[key])
    source_hashes = {name: _sha(path) for name, path in (
        ("brief", brief), ("design_brief", design),
        ("analysis_specification", ANALYSIS_SPEC),
        ("data_specification", data_spec), ("data", DATA),
    )}
    packet, packet_text = _cli(
        workspace, "guide", "prepare", "--brief-file", str(brief),
        "--design-brief-file", str(design),
        "--analysis-spec-file", str(ANALYSIS_SPEC),
        "--data-spec-file", str(data_spec), "--data-file", str(DATA),
        "--expect-data-sha256", source_hashes["data"],
    )
    _require(packet["status"] == "ready_for_review" and
             packet["input_sha256"] == source_hashes and
             packet["blocking_issues"] == [] and packet["unresolved_fields"] == [] and
             packet["analysis_performed"] is False and
             packet["scientific_evidence_eligible"] is False and
             not workspace.exists(), "guide preparation was incomplete or wrote state")
    packet_file = root / "packet.json"
    packet_file.write_text(packet_text, encoding="utf-8")

    explanations = []
    receipt_hashes = []
    for index in (1, 2):
        output = root / f"analysis-{index}"
        run, _ = _cli(
            workspace, "guide", "run", "--packet-file", str(packet_file),
            "--expect-packet-sha256", _sha(packet_file),
            "--spec-file", str(ANALYSIS_SPEC),
            "--expect-spec-sha256", source_hashes["analysis_specification"],
            "--data-file", str(DATA),
            "--expect-input-sha256", source_hashes["data"],
            "--output", str(output),
        )
        receipt = run["execution"]["receipt"]
        _require(run["status"] == "exploratory_computation_only" and
                 run["scientific_evidence_eligible"] is False and
                 receipt["specification"]["sha256"] == source_hashes["analysis_specification"] and
                 receipt["input"]["sha256"] == source_hashes["data"] and
                 receipt["output"]["sha256"] == _sha(output / "analysis-result.json") and
                 receipt["scientific_evidence_eligible"] is False,
                 "guide run lost its byte or inference ceiling")
        receipt_hash = _sha(output / "execution-receipt.json")
        explanation, _ = _cli(
            workspace, "guide", "explain", "--packet-file", str(packet_file),
            "--expect-packet-sha256", _sha(packet_file),
            "--spec-file", str(ANALYSIS_SPEC), "--data-file", str(DATA),
            "--execution-directory", str(output),
            "--expected-receipt-sha256", receipt_hash,
        )
        _require(explanation["effect_estimate"]["value"] == 3.0 and
                 explanation["uncertainty"]["relation_to_zero"] == "above_zero" and
                 explanation["method"] == "independent_mean_difference_ci" and
                 explanation["next_experiment"]["candidate"] is None and
                 explanation["next_experiment"]["discrimination_established"] is False and
                 explanation["scientific_evidence_eligible"] is False and
                 explanation["canonical_write_performed"] is False,
                 "guide explanation overstated a synthetic computation")
        receipt_hashes.append(receipt_hash)
        explanations.append(explanation)
    stable = [{key: value for key, value in item.items() if key != "receipt_sha256"}
              for item in explanations]
    _require(stable[0] == stable[1] and not workspace.exists(),
             "frozen guide workflow replay drifted or wrote canonical state")
    _require(source_hashes["data"] == _sha(DATA) and
             source_hashes["analysis_specification"] == _sha(ANALYSIS_SPEC),
             "source fixture bytes changed during guide workflow")
    return {
        "fixture_id": fixture["fixture_id"], "fixture_version": fixture["fixture_version"],
        "source_sha256": source_hashes, "packet_sha256": _sha(packet_file),
        "receipt_sha256": receipt_hashes, "explanation_sha256": _content_digest(stable[0]),
        "replay_stable": True, "canonical_write_performed": False,
        "scientific_evidence_eligible": False,
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result: dict = {"local_workflow_fixture_ready": False, "checks": {}}
    try:
        _require(sys.version_info >= (3, 11), "Python 3.11+ is required")
        commit = _command(["git", "rev-parse", "HEAD"])
        status = _command(["git", "status", "--porcelain", "--untracked-files=normal"])
        _require(commit.returncode == 0 and status.returncode == 0 and not status.stdout.strip(),
                 "a clean exact Git commit is required")
        result["commit_sha"] = commit.stdout.strip()
        source_digest = _sha(WORKFLOW_INPUTS)
        _require(source_digest == WORKFLOW_INPUTS_SHA256,
                 "workflow fixture bytes drifted from the W04 baseline")
        result["fixture_sha256"] = source_digest
        with tempfile.TemporaryDirectory(prefix="faraday-guide-workflow-") as directory:
            result["workflow"] = run_workflow(Path(directory))
        result["checks"]["public_workflow"] = "passed"
        focused = _command([
            sys.executable, "-m", "pytest", "-o", "addopts=", "-q",
            "-p", "no:cacheprovider", "tests/test_guide_prepare.py",
            "tests/test_guide_run.py", "tests/test_guide_explain.py",
            "tests/test_guide_workflow.py",
        ], timeout=600)
        _require(focused.returncode == 0,
                 f"workflow adverse checks failed: {focused.stdout[-500:]} {focused.stderr[-300:]}")
        summary = focused.stdout.strip().splitlines()[-1]
        _require(re.search(r"\b\d+ passed\b", summary) is not None and
                 "skipped" not in summary, "required workflow checks were skipped")
        result["checks"]["workflow_adverse"] = summary[:200]
        previous = _command([
            sys.executable, str(ROOT / "scripts" / "check_ai_science_guide_goal.py"),
            "--json",
        ], timeout=1800)
        _require(previous.returncode == 0,
                 f"G00-G09 gate failed: {previous.stdout[-500:]} {previous.stderr[-300:]}")
        baseline = json.loads(previous.stdout)
        _require(baseline.get("software_fixture_ready") is True and
                 baseline.get("commit_sha") == result["commit_sha"] and
                 baseline["journey"]["replay_stable"] is True,
                 "earlier software fixture gate was incomplete or stale")
        result["checks"]["full_suite"] = baseline["checks"]["full_suite"]
        result["checks"]["G00_G09_audit_ledger"] = {
            "audit_errors": baseline["journey"]["audit_errors"],
            "ledger_head": baseline["journey"]["ledger_head"],
        }
        final_commit = _command(["git", "rev-parse", "HEAD"])
        final_status = _command(["git", "status", "--porcelain", "--untracked-files=normal"])
        _require(final_commit.returncode == 0 and final_commit.stdout.strip() == result["commit_sha"] and
                 final_status.returncode == 0 and not final_status.stdout.strip() and
                 _sha(WORKFLOW_INPUTS) == source_digest,
                 "commit, worktree, or workflow fixture changed during the gate")
        result["local_workflow_fixture_ready"] = True
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)[:800]
    print(json.dumps(result, sort_keys=True) if args.json else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["local_workflow_fixture_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
