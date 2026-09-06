from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from research_machine.interfaces.cli import main


def result_from(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    return payload["result"]


def test_json_cli_rejects_duplicate_keys_and_nonfinite_numbers(
    tmp_path: Path, capsys
) -> None:
    workspace = tmp_path / "workspace"
    global_args = ["--workspace", str(workspace), "--json"]
    assert main([*global_args, "workspace", "init"]) == 0
    result_from(capsys)
    invalid_inputs = (
        (
            "duplicate.json",
            '{"statement":"first","statement":"second"}',
            "duplicate JSON object key",
        ),
        ("nan.json", '{"statement":NaN}', "non-finite JSON number"),
    )
    for name, content, expected in invalid_inputs:
        proposal = tmp_path / name
        proposal.write_text(content, encoding="utf-8")
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
            == 2
        )
        error = json.loads(capsys.readouterr().err)
        assert expected in error["error"]["message"]


def test_json_cli_records_balanced_action_portfolio(tmp_path: Path, capsys) -> None:
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
                "parallel-research",
                "--title",
                "Parallel research",
                "--statement",
                "Can multiple lanes advance without starvation?",
            ]
        )
        == 0
    )
    result_from(capsys)

    spec = tmp_path / "portfolio.json"
    spec.write_text(
        json.dumps(
            {
                "lanes": [
                    {"lane_id": "machine", "title": "Machine"},
                    {"lane_id": "science", "title": "Science"},
                ],
                "candidates": [
                    {
                        "action_id": "machine-audit",
                        "title": "Audit machine",
                        "distinguishes_hypotheses": [],
                        "information_targets": ["machine:false-acceptance"],
                        "expected_discrimination": 0.9,
                        "uncertainty_reduction": 0.8,
                        "cost": 0.2,
                        "burden": 0.1,
                        "safety_risk": 0.0,
                        "ambiguity_risk": 0.1,
                        "rationale": "Probe a machine invariant.",
                        "lane_id": "machine",
                    },
                    {
                        "action_id": "science-falsifier",
                        "title": "Run falsifier",
                        "distinguishes_hypotheses": [],
                        "information_targets": ["science:first-failing-gate"],
                        "expected_discrimination": 0.7,
                        "uncertainty_reduction": 0.6,
                        "cost": 0.2,
                        "burden": 0.1,
                        "safety_risk": 0.0,
                        "ambiguity_risk": 0.1,
                        "rationale": "Probe the cheapest scientific failure.",
                        "lane_id": "science",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                *global_args,
                "next-action",
                "portfolio",
                "--spec-file",
                str(spec),
            ]
        )
        == 0
    )
    recommendation = result_from(capsys)
    assert recommendation["selection_mode"] == "portfolio"
    assert recommendation["selected_action_ids_by_lane"] == {
        "machine": "machine-audit",
        "science": "science-falsifier",
    }


def test_json_cli_records_cross_lane_lesson(tmp_path: Path, capsys) -> None:
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
                "dogfood",
                "--title",
                "Dogfood",
                "--statement",
                "Can an exposed failure improve a future machine version?",
            ]
        )
        == 0
    )
    result_from(capsys)
    spec = tmp_path / "lesson.json"
    spec.write_text(
        json.dumps(
            {
                "origin_lane_id": "science",
                "target_lane_ids": ["machine"],
                "origin_artifact_locator": "results/run.json",
                "origin_artifact_sha256": "a" * 64,
                "origin_integrity_status": "declared",
                "observation": "A control omitted its evaluation time.",
                "failure_class": "interface_ambiguity",
                "strongest_alternative_explanation": (
                    "The implementation may be defective."
                ),
                "challenged_invariant": "Every target is reproducibly defined.",
                "first_permitted_future_versions": ["machine-v2"],
                "prohibited_retroactive_targets": ["machine-v1", "protocol-v1"],
                "proposed_repair": "Require a typed evaluation time.",
                "repair_falsifier": "An omitted-time fixture is accepted.",
                "conclusion_ceiling": "Process lesson only.",
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                *global_args,
                "cross-lane-lesson",
                "record",
                "--spec-file",
                str(spec),
            ]
        )
        == 0
    )
    lesson = result_from(capsys)
    assert lesson["failure_class"] == "interface_ambiguity"
    assert lesson["first_permitted_future_versions"] == ["machine-v2"]


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
                "measurement_definitions": [
                    {
                        "measurement_id": "candidate-proof",
                        "role": "primary",
                        "registered_target": "Proof checker acceptance",
                        "observable": "checker exit status",
                        "input_condition": "registered candidate proof",
                        "parameter_values": {"checker_mode": "strict"},
                        "evaluation_point": "after the final proof step",
                        "convention": "exit status zero means accepted",
                        "aggregation": "single checker result",
                        "tolerance": "exact",
                        "expected_behavior": "accepted",
                    },
                    {
                        "measurement_id": "invalid-proof-control",
                        "role": "control",
                        "registered_target": (
                            "A deliberately invalid proof must be rejected."
                        ),
                        "observable": "checker exit status",
                        "input_condition": "registered invalid proof",
                        "parameter_values": {"checker_mode": "strict"},
                        "evaluation_point": "at the injected invalid step",
                        "convention": "nonzero exit status means rejected",
                        "aggregation": "single checker result",
                        "tolerance": "exact",
                        "expected_behavior": "rejected",
                    },
                ],
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
    assert protocol["measurement_definitions"][1]["evaluation_point"] == (
        "at the injected invalid step"
    )

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

    registered_at = datetime.fromisoformat(
        protocol["registration_timestamp"].replace("Z", "+00:00")
    )
    run_started = registered_at + timedelta(seconds=1)
    run_completed = registered_at + timedelta(seconds=2)
    proof_output = tmp_path / "proof.json"
    proof_output.write_text('{"proof":"accepted"}\n', encoding="utf-8")
    proof_sha256 = hashlib.sha256(proof_output.read_bytes()).hexdigest()
    run_record = tmp_path / "run.json"
    run_record.write_text(
        json.dumps(
            {
                "protocol_id": protocol["protocol_id"],
                "started_at": run_started.isoformat(),
                "completed_at": run_completed.isoformat(),
                "analysis_code_hash": "a" * 64,
                "environment_hash": "b" * 64,
                "output_artifacts": [{
                    "locator": "proof.json",
                    "sha256": proof_sha256,
                    "size_bytes": proof_output.stat().st_size,
                }],
                "quality_gates": [
                    {
                            "gate_id": "proof-check",
                            "status": "passed",
                            "summary": "The proof was independently replayed.",
                            "details": {"evidence_sha256": proof_sha256},
                        }
                ],
                "metadata": {
                    "protocol_deviation_disclosure": {
                        "status": "no_deviations_declared",
                        "deviations": [],
                    }
                },
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
                "--artifact-root",
                str(tmp_path),
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
                "--artifact-root",
                str(tmp_path),
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
                "--artifact-root",
                str(tmp_path),
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
