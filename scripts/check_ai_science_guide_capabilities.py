#!/usr/bin/env python3
"""Exact-commit synthetic gate for deferred AI science guide capabilities."""

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
from typing import Any

if __package__:
    from .check_ai_science_guide_goal import ROOT, _command, _sha
    from .check_ai_science_guide_workflow import WORKFLOW_INPUTS, _cli
else:
    from check_ai_science_guide_goal import ROOT, _command, _sha
    from check_ai_science_guide_workflow import WORKFLOW_INPUTS, _cli


PLAN = ROOT / "docs" / "ai-science-guide" / "capability-milestones.json"
CAPABILITY_ROUTES = {
    "T01": ("live_model",),
    "T02": ("live_connector", "live_instrument"),
    "T03": ("arbitrary_statistics",),
    "T04": ("authenticated_reviewer",),
    "T05": ("metamaps_compilation",),
    "T06": ("concurrent_writes",),
    "T07": ("automated_confirmatory_activation",),
    "T08": ("publication",),
    "T09": ("domain_specific_validity",),
    "T10": ("model_specific_next_experiment",),
    "T11": ("paired_observational_packet",),
}
LIVE_STATUSES = {
    "T01": "not_configured", "T02": "not_configured", "T03": "unsupported",
    "T04": "not_configured", "T05": "not_configured", "T06": "unsupported",
    "T07": "unsupported", "T08": "unsupported", "T09": "unsupported",
    "T10": "review_only", "T11": "review_only",
}
FOCUSED_TESTS = (
    "tests/test_guide_unavailable.py", "tests/test_guide_provider.py",
    "tests/test_guide_acquisition.py", "tests/test_guide_analysis.py",
    "tests/test_measurement_validity.py", "tests/test_guide_contract.py",
    "tests/test_guide_end_to_end.py", "tests/test_guide_prepare.py",
    "tests/test_guide_explain.py", "tests/test_guide_models.py",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _prepare(
    root: Path, label: str, brief: dict[str, Any], spec: dict[str, Any],
    data: str,
) -> dict[str, Any]:
    root.mkdir()
    brief_file, spec_file = root / "brief.json", root / "analysis.json"
    data_spec_file, data_file = root / "data-spec.json", root / "data.csv"
    _write_json(brief_file, brief)
    _write_json(spec_file, spec)
    _write_json(data_spec_file, {
        **spec,
        "measurement_definitions": [{
            "measurement_id": f"{label}-outcome-v1", "data_column": "outcome",
            "scale_type": "interval", "unit": "synthetic points",
            "admissible_values": [], "missing_value_codes": ["<blank>"],
            "valid_min": 0.0, "valid_max": 100.0,
        }],
    })
    data_file.write_text(data, encoding="utf-8")
    workspace = root / "unused-workspace"
    packet, _ = _cli(
        workspace, "guide", "prepare", "--brief-file", str(brief_file),
        "--analysis-spec-file", str(spec_file),
        "--data-spec-file", str(data_spec_file),
        "--data-file", str(data_file),
        "--expect-data-sha256", _sha(data_file),
    )
    _require(not workspace.exists(), f"{label} preview wrote canonical state")
    _require(packet["analysis_performed"] is False and
             packet["scientific_evidence_eligible"] is False and
             packet["canonical_write_performed"] is False,
             f"{label} preview crossed its authority boundary")
    return packet


def run_design_previews(root: Path) -> dict[str, Any]:
    """Replay paired and observational public previews with adverse inputs."""
    root.mkdir()
    brief = json.loads(WORKFLOW_INPUTS.read_text(encoding="utf-8"))["brief"]
    paired_spec = {
        "method": "paired_mean_difference_ci", "study_design": "paired",
        "pair_column": "pair", "group_column": "group", "outcome_column": "outcome",
        "groups": ["treatment", "control"], "seed": 17,
    }
    paired = _prepare(
        root / "paired", "paired", brief, paired_spec,
        "pair,group,outcome\np1,treatment,4\np1,control,2\np2,treatment,6\np2,control,3\n",
    )
    paired_bad = _prepare(
        root / "paired-bad", "paired-bad", brief, paired_spec,
        "pair,group,outcome\np1,treatment,4\np1,treatment,5\np2,control,3\n",
    )
    _require(paired["status"] == "needs_clarification" and
             paired["unresolved_fields"] == ["prospective_design"] and
             paired["data_preview"]["design_inventory"]["pair_count"] == 2 and
             paired["data_preview"]["quality_issues"] == [] and
             paired_bad["status"] == "blocked" and
             "duplicate pair-group observations" in paired_bad["data_preview"]["quality_issues"] and
             "incomplete paired observations" in paired_bad["data_preview"]["quality_issues"],
             "paired preview or adverse pair ceiling drifted")

    observed_spec = {
        "method": "adjusted_linear_effect", "study_design": "independent_groups",
        "unit_column": "unit", "group_column": "group", "outcome_column": "outcome",
        "groups": ["treatment", "control"], "covariate_columns": ["baseline"],
        "missing_data_policy": "complete_case", "confidence_level": 0.95,
    }
    observed_data = "unit,group,outcome,baseline\nu1,treatment,8,1\nu2,control,4,\n"
    observed = _prepare(
        root / "observational", "observational", brief, observed_spec, observed_data,
    )
    no_policy = dict(observed_spec)
    del no_policy["missing_data_policy"]
    observed_bad = _prepare(
        root / "observational-bad", "observational-bad", brief, no_policy, observed_data,
    )
    inventory = observed["data_preview"]["design_inventory"]
    _require(observed["status"] == "needs_clarification" and
             observed["unresolved_fields"] == ["prospective_design"] and
             inventory["covariate_missing_count"] == {"baseline": 1} and
             inventory["complete_case_exclusion_count"] == 1 and
             inventory["causal_identification_verified"] is False and
             "confounding" in inventory["claim_ceiling"] and
             observed_bad["status"] == "blocked" and
             "missing adjusted-analysis values require an explicit complete_case policy"
             in observed_bad["data_preview"]["quality_issues"],
             "observational preview or missingness ceiling drifted")
    return {
        "paired": {"status": paired["status"], "pair_count": 2,
                   "adverse_status": paired_bad["status"]},
        "observational": {"status": observed["status"],
                          "complete_case_exclusion_count": 1,
                          "causal_identification_verified": False,
                          "adverse_status": observed_bad["status"]},
        "canonical_write_performed": False,
        "scientific_evidence_eligible": False,
    }


def _validate_plan() -> tuple[dict[str, Any], dict[str, list[str]]]:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    jobs = plan["jobs"]
    _require([job["id"] for job in jobs] == [f"C{number:02d}" for number in range(13)],
             "capability jobs are missing or out of serial order")
    _require(plan["status"] == "local_fixture_verified" and
             plan["completion_state"] == "local_capability_fixture_ready",
             "capability completion state changed")
    seen: set[str] = set()
    capability_jobs: dict[str, list[str]] = {key: [] for key in CAPABILITY_ROUTES}
    for job in jobs:
        _require(job["status"] in {"verified_local_plan", "verified_local_fixture"},
                 f"{job['id']} is not locally verified")
        _require(set(job["depends_on"]) <= seen, f"{job['id']} has a forward dependency")
        _require(bool(job["allowed_paths"]) and bool(job["acceptance"]),
                 f"{job['id']} has no artifact or acceptance check")
        for path in job["allowed_paths"]:
            _require((ROOT / path).is_file(), f"{job['id']} artifact is missing: {path}")
        for capability in job["capabilities"]:
            _require(capability in capability_jobs, f"unknown capability {capability}")
            capability_jobs[capability].append(job["id"])
        seen.add(job["id"])
    _require(all(jobs_for_capability for jobs_for_capability in capability_jobs.values()),
             "a deferred capability lacks a milestone")
    return plan, capability_jobs


def _capability_states(
    root: Path, plan: dict[str, Any], capability_jobs: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    workspace = root / "capability-workspace"
    jobs_by_id = {job["id"]: job for job in plan["jobs"]}
    result: dict[str, dict[str, Any]] = {}
    for capability, routes in CAPABILITY_ROUTES.items():
        for route in routes:
            response, _ = _cli(workspace, "guide", "capability", "--name", route)
            _require(response["status"] == LIVE_STATUSES[capability] and
                     response["canonical_write_performed"] is False and
                     response["external_call_performed"] is False and
                     response["grants_authority"] is False and
                     response["fallback_used"] is False,
                     f"{capability} route widened authority")
        paths = sorted({
            path for job_id in capability_jobs[capability]
            for path in jobs_by_id[job_id]["allowed_paths"]
        })
        artifacts = [(path, _sha(ROOT / path)) for path in paths]
        artifact_digest = hashlib.sha256(json.dumps(
            artifacts, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        result[capability] = {
            "work_items": capability_jobs[capability],
            "requirement_id": capability,
            "artifact_set_sha256": artifact_digest,
            "artifact_count": len(artifacts),
            "local_software_status": "verified_local_fixture",
            "live_activation_status": LIVE_STATUSES[capability],
            "live_activation_verified": False,
            "scientific_acceptance_verified": False,
            "routes": list(routes),
        }
    _require(not workspace.exists(), "capability inspection wrote canonical state")
    return result


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result: dict[str, Any] = {"local_capability_fixture_ready": False, "checks": {}}
    try:
        _require(sys.version_info >= (3, 11), "Python 3.11+ is required")
        commit = _command(["git", "rev-parse", "HEAD"])
        status = _command(["git", "status", "--porcelain", "--untracked-files=normal"])
        _require(commit.returncode == 0 and status.returncode == 0 and not status.stdout.strip(),
                 "a clean exact Git commit is required")
        result["commit_sha"] = commit.stdout.strip()
        result["evaluator_sha256"] = _sha(Path(__file__))
        result["milestone_plan_sha256"] = _sha(PLAN)
        plan, capability_jobs = _validate_plan()
        with tempfile.TemporaryDirectory(prefix="faraday-guide-capabilities-") as directory:
            root = Path(directory)
            first = run_design_previews(root / "first")
            second = run_design_previews(root / "second")
            _require(first == second, "paired or observational replay drifted")
            result["checks"]["paired_observational_replay"] = first
            result["capabilities"] = _capability_states(root, plan, capability_jobs)
        focused = _command([
            sys.executable, "-m", "pytest", "-o", "addopts=", "-q",
            "-p", "no:cacheprovider", *FOCUSED_TESTS,
        ], timeout=600)
        _require(focused.returncode == 0,
                 f"capability adverse checks failed: {focused.stdout[-500:]} {focused.stderr[-300:]}")
        summary = focused.stdout.strip().splitlines()[-1]
        _require(re.search(r"\b\d+ passed\b", summary) is not None and
                 "skipped" not in summary, "required capability tests were skipped")
        result["checks"]["capability_adverse"] = summary[:200]
        previous = _command([
            sys.executable, str(ROOT / "scripts" / "check_ai_science_guide_workflow.py"),
            "--json",
        ], timeout=1800)
        _require(previous.returncode == 0,
                 f"exact workflow gate failed: {previous.stdout[-500:]} {previous.stderr[-300:]}")
        workflow = json.loads(previous.stdout)
        _require(workflow.get("local_workflow_fixture_ready") is True and
                 workflow.get("commit_sha") == result["commit_sha"] and
                 workflow["workflow"]["replay_stable"] is True and
                 workflow["checks"]["G00_G09_audit_ledger"]["audit_errors"] == 0,
                 "workflow, full suite, audit, or ledger evidence is incomplete")
        result["checks"]["public_workflow"] = workflow["checks"]["public_workflow"]
        result["checks"]["full_suite"] = workflow["checks"]["full_suite"]
        result["checks"]["workflow_adverse"] = workflow["checks"]["workflow_adverse"]
        result["checks"]["audit_ledger"] = workflow["checks"]["G00_G09_audit_ledger"]
        result["checks"]["ledger_verified"] = bool(workflow["checks"]["G00_G09_audit_ledger"]["ledger_head"])
        final_commit = _command(["git", "rev-parse", "HEAD"])
        final_status = _command(["git", "status", "--porcelain", "--untracked-files=normal"])
        _require(final_commit.returncode == 0 and
                 final_commit.stdout.strip() == result["commit_sha"] and
                 final_status.returncode == 0 and not final_status.stdout.strip() and
                 _sha(PLAN) == result["milestone_plan_sha256"] and
                 _sha(Path(__file__)) == result["evaluator_sha256"],
                 "commit, worktree, plan, or evaluator changed during the gate")
        result["metamaps_graph_version"] = None
        result["metamaps_compilation_verified"] = False
        result["scientific_acceptance_verified"] = False
        result["publication_authorized"] = False
        result["local_capability_fixture_ready"] = True
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)[:800]
    print(json.dumps(result, sort_keys=True) if args.json else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["local_capability_fixture_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
