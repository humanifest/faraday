from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_machine.interfaces.cli import main


def result_from(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    return payload["result"]


def test_json_cli_accepts_structured_hypothesis_proposals(
    tmp_path: Path, capsys
) -> None:
    workspace = tmp_path / "workspace"
    global_args = ["--workspace", str(workspace), "--json"]

    assert main([*global_args, "workspace", "init"]) == 0
    result_from(capsys)

    assert (
        main(
            [
                *global_args,
                "inquiry",
                "create",
                "--id",
                "fairness-audit",
                "--title",
                "Fairness audit",
                "--statement",
                "I suspect a persistent disparity in automated recommendations.",
            ]
        )
        == 0
    )
    result_from(capsys)

    proposal = tmp_path / "proposal.json"
    proposal.write_text(
        json.dumps(
            {
                "statement": "A preprocessing join creates the apparent disparity.",
                "generated_by": "external-codex-session",
                "observable_prediction": (
                    "Correcting the join eliminates the registered disparity estimate."
                ),
                "null_model": "The join correction does not materially change the estimate.",
                "falsification_conditions": [
                    "The disparity persists after independently verified joins."
                ],
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                *global_args,
                "hypothesis",
                "propose",
                "--proposal-file",
                str(proposal),
            ]
        )
        == 0
    )
    hypothesis = result_from(capsys)
    assert hypothesis["workflow_state"] == "unreviewed"
    assert hypothesis["generated_by"] == "external-codex-session"

    assert (
        main(
            [
                *global_args,
                "hypothesis",
                "activate",
                hypothesis["hypothesis_id"],
            ]
        )
        == 0
    )
    active = result_from(capsys)
    assert active["workflow_state"] == "active"

    assert main([*global_args, "workspace", "verify"]) == 0
    verification = result_from(capsys)
    assert verification["valid"] is True
    assert verification["events"] == 3


def test_json_cli_rejects_malformed_proposal_contract(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    global_args = ["--workspace", str(workspace), "--json"]
    assert main([*global_args, "workspace", "init"]) == 0
    result_from(capsys)
    assert (
        main(
            [
                *global_args,
                "inquiry",
                "create",
                "--id",
                "contract-test",
                "--title",
                "Contract test",
                "--statement",
                "Can malformed proposals cross the interface boundary?",
            ]
        )
        == 0
    )
    result_from(capsys)

    malformed = tmp_path / "malformed.json"
    malformed.write_text(
        json.dumps(
            {
                "statement": "This has the wrong collection type.",
                "competing_models": "not-an-array",
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                *global_args,
                "hypothesis",
                "propose",
                "--proposal-file",
                str(malformed),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["ok"] is False
    assert "competing_models must be an array" in error["error"]["message"]


def test_cli_stages_pending_review_without_activation(
    tmp_path: Path, capsys
) -> None:
    workspace = tmp_path / "workspace"
    global_args = ["--workspace", str(workspace), "--json"]
    assert main([*global_args, "workspace", "init"]) == 0
    result_from(capsys)
    assert (
        main(
            [
                *global_args,
                "inquiry",
                "create",
                "--id",
                "pending-review",
                "--title",
                "Pending review",
                "--statement",
                "Can exploration continue safely?",
            ]
        )
        == 0
    )
    result_from(capsys)
    assert (
        main(
            [
                *global_args,
                "hypothesis",
                "propose",
                "--statement",
                "A physical postulate removes the obstruction.",
                "--prediction",
                "A registered exploratory gate changes.",
                "--null-model",
                "The gate does not change.",
                "--falsification",
                "The gate remains failed.",
            ]
        )
        == 0
    )
    hypothesis = result_from(capsys)
    assert (
        main(
            [
                *global_args,
                "--actor",
                "delegated-codex-review",
                "hypothesis",
                "stage",
                hypothesis["hypothesis_id"],
                "--confidence",
                "high",
                "--rationale",
                "The proposal is complete and the exploration is reversible.",
            ]
        )
        == 0
    )
    staged = result_from(capsys)
    assert staged["workflow_state"] == "pending_review"
    assert staged["activated_at"] is None
    assert staged["pending_review_by"] == "delegated-codex-review"
    assert (
        main(
            [
                *global_args,
                "hypothesis",
                "list",
                "--state",
                "pending_review",
            ]
        )
        == 0
    )
    assert result_from(capsys)[0]["hypothesis_id"] == hypothesis["hypothesis_id"]


def test_cli_rigor_audit_supports_ci_failure_thresholds(tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "workspace"
    global_args = ["--workspace", str(workspace), "--json"]
    assert main([*global_args, "workspace", "init"]) == 0
    result_from(capsys)
    assert (
        main(
            [
                *global_args,
                "inquiry",
                "create",
                "--id",
                "rigor-audit",
                "--title",
                "Rigor audit",
                "--statement",
                "Can overclaims fail closed?",
            ]
        )
        == 0
    )
    result_from(capsys)

    assert main([*global_args, "workspace", "audit", "--fail-on", "error"]) == 0
    audit = result_from(capsys)
    assert audit["structurally_valid"] is True
    assert audit["conclusion_ceiling"] == "unclassified evidence only"

    assert main([*global_args, "workspace", "audit", "--fail-on", "warning"]) == 2
    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert error["ok"] is False
    assert "rigor audit failed" in error["error"]["message"]


def test_cli_records_general_protocol_run_and_next_action(
    tmp_path: Path, capsys
) -> None:
    workspace = tmp_path / "workspace"
    global_args = ["--workspace", str(workspace), "--json"]
    assert main([*global_args, "workspace", "init"]) == 0
    result_from(capsys)
    assert (
        main(
            [
                *global_args,
                "inquiry",
                "create",
                "--id",
                "theory-check",
                "--title",
                "Theory check",
                "--statement",
                "Does the formal model entail the invariant?",
            ]
        )
        == 0
    )
    result_from(capsys)
    assert (
        main(
            [
                *global_args,
                "hypothesis",
                "propose",
                "--statement",
                "The axioms entail the invariant.",
                "--prediction",
                "A proof checker accepts the derivation.",
                "--null-model",
                "No valid bounded derivation exists.",
                "--falsification",
                "The proof checker rejects a proof step.",
            ]
        )
        == 0
    )
    hypothesis = result_from(capsys)
    assert (
        main(
            [
                *global_args,
                "hypothesis",
                "activate",
                hypothesis["hypothesis_id"],
            ]
        )
        == 0
    )
    result_from(capsys)

    protocol_spec = tmp_path / "protocol.json"
    protocol_spec.write_text(
        json.dumps(
            {
                "experiment_id": "proof-check",
                "title": "Registered formal check",
                "analysis_mode": "confirmatory",
                "protocol_kind": "formal",
                "hypotheses_tested": [hypothesis["hypothesis_id"]],
                "primary_outcome": "Proof checker acceptance",
                "methodology": "Replay the proof in a pinned checker.",
                "quality_requirements": ["proof-check"],
                "controls": ["A deliberately invalid proof must be rejected."],
                "expected_outputs": ["Proof object"],
                "success_conditions": ["Checker acceptance"],
                "environment_requirements": ["Pinned checker hash"],
                "sample_size_or_stopping_rule": (
                    "One proof object and one deliberately invalid control."
                ),
                "failure_conditions": ["Any rejected proof step"],
                "safety_constraints": ["No physical intervention"],
                "analysis_code_hash": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    assert (
        main([*global_args, "protocol", "create", "--spec-file", str(protocol_spec)])
        == 0
    )
    protocol = result_from(capsys)
    assert main([*global_args, "protocol", "freeze", protocol["protocol_id"]]) == 0
    protocol = result_from(capsys)

    assert (
        main(
            [
                *global_args,
                "run",
                "template",
                "--protocol",
                protocol["protocol_id"],
            ]
        )
        == 0
    )
    template = result_from(capsys)
    assert template["would_append_event"] is False
    assert [
        item["gate_id"] for item in template["record"]["quality_gates"]
    ] == ["proof-check"]

    run_record = tmp_path / "run.json"
    run_record.write_text(
        json.dumps(
            {
                "protocol_id": protocol["protocol_id"],
                "started_at": "2026-09-02T10:00:00Z",
                "completed_at": "2026-09-02T10:01:00Z",
                "analysis_code_hash": "a" * 64,
                "environment_hash": "b" * 64,
                "output_artifacts": [{"locator": "proof.json", "sha256": "c" * 64}],
                "quality_gates": [
                    {
                        "gate_id": "proof-check",
                        "status": "passed",
                        "summary": "The proof was independently replayed.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                *global_args,
                "run",
                "preflight",
                "--record-file",
                str(run_record),
            ]
        )
        == 0
    )
    preflight = result_from(capsys)
    assert preflight["status"] == "ready"
    assert preflight["would_append_event"] is False
    assert preflight["quality_gate_order_matches_protocol"] is True
    assert preflight["record_file_sha256"] == hashlib.sha256(
        run_record.read_bytes()
    ).hexdigest()
    assert preflight["record_file_size_bytes"] == len(run_record.read_bytes())

    invalid_record = tmp_path / "invalid-run-label.json"
    invalid_value = json.loads(run_record.read_text())
    invalid_value["quality_gates"][0]["gate_id"] = "shortened label"
    invalid_record.write_text(json.dumps(invalid_value), encoding="utf-8")
    assert (
        main(
            [
                *global_args,
                "run",
                "preflight",
                "--record-file",
                str(invalid_record),
            ]
        )
        == 1
    )
    invalid_preflight = result_from(capsys)
    assert invalid_preflight["status"] == "would_record_invalid"
    assert invalid_preflight["missing_quality_gate_ids"] == ["proof-check"]
    assert invalid_preflight["unexpected_quality_gate_ids"] == [
        "shortened label"
    ]
    assert main([*global_args, "run", "list"]) == 0
    assert result_from(capsys) == []

    assert (
        main(
            [
                *global_args,
                "run",
                "record",
                "--record-file",
                str(run_record),
                "--expect-record-sha256",
                "0" * 64,
            ]
        )
        == 2
    )
    hash_error = json.loads(capsys.readouterr().err)
    assert "run record hash mismatch" in hash_error["error"]["message"]
    assert main([*global_args, "run", "list"]) == 0
    assert result_from(capsys) == []

    assert (
        main(
            [
                *global_args,
                "run",
                "record",
                "--record-file",
                str(run_record),
                "--expect-record-sha256",
                preflight["record_file_sha256"],
            ]
        )
        == 0
    )
    run = result_from(capsys)
    assert run["scientific_evidence_eligible"] is True
    assert (
        main(
            [
                *global_args,
                "evidence",
                "record",
                "--hypothesis",
                hypothesis["hypothesis_id"],
                "--direction",
                "supports",
                "--summary",
                "The registered proof check passed.",
                "--run",
                run["run_id"],
                "--uncertainty",
                "Bounded to the pinned checker and registered formal system.",
                "--scope",
                "The registered invariant only.",
                "--control-passed",
                "The deliberately invalid proof was rejected.",
                "--higher-conclusion-unsupported",
                "The candidate is empirically correct.",
                "--validation-tag",
                "internal_consistency",
                "--validation-tag",
                "controlled_benchmark",
                "--confirmatory",
            ]
        )
        == 0
    )
    evidence = result_from(capsys)
    assert evidence["run_id"] == run["run_id"]

    action_spec = tmp_path / "actions.json"
    action_spec.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "action_id": "independent-check",
                        "title": "Independent proof check",
                        "distinguishes_hypotheses": [hypothesis["hypothesis_id"]],
                        "expected_discrimination": 0.9,
                        "uncertainty_reduction": 0.8,
                        "cost": 0.2,
                        "burden": 0.1,
                        "safety_risk": 0.0,
                        "ambiguity_risk": 0.1,
                        "rationale": "A second checker probes implementation dependence.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                *global_args,
                "next-action",
                "recommend",
                "--spec-file",
                str(action_spec),
            ]
        )
        == 0
    )
    recommendation = result_from(capsys)
    assert recommendation["selected_action_id"] == "independent-check"
