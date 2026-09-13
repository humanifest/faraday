from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from research_machine.interfaces.cli import main


AUDIT_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "audit-prerequisite"
SUBJECT_SHA256 = "962db3ccf52bd2e7cb2f1c1c6f377fcb7c7b777d66ba3b1b5433d86389505984"
AUDIT_SHA256 = "0a639e59dbc54232ea6a7c70d4e8ad09dd96aaa6a31188466a18f48cd6e8e939"
SOURCE_FINDING_SHA256 = "d8eb6386dc6d56530e8b8e412e252b7a0cdb4b4ef0fc4b62cdf4a051dff76a4b"
AUDIT_REPORT_SHA256 = "d0a65fe83d6d7c6aaae5ebc5dd7b508ee255b66d7b77ed93eb766e2cd79ae425"
AUDIT_CEILING = (
    "Workflow eligibility only; does not establish audit truth, auditor identity "
    "or independence, scientific validity, or evidence eligibility."
)


def nonadvancing_information_contract() -> dict[str, object]:
    return {
        "contract_version": 1,
        "action_class": "nonadvancing_information",
        "subjects": [],
        "required_audits": [],
        "evaluator_exposure_statement": "",
        "nonadvancing_information_statement": (
            "This bounded workflow inquiry cannot advance candidate or implementation bytes."
        ),
        "limitations": ["Synthetic workflow fixture only."],
        "conclusion_ceiling": AUDIT_CEILING,
    }


def candidate_advancement_contract() -> dict[str, object]:
    return {
        "contract_version": 1,
        "action_class": "candidate_advancing",
        "subjects": [
            {
                "subject_role": "candidate",
                "subject_id": "fixture-candidate",
                "artifact_locator": "subject.txt",
                "artifact_sha256": SUBJECT_SHA256,
            }
        ],
        "required_audits": [
            {
                "audit_id": "audit-fixture-favorable",
                "artifact_role": "adversarial_candidate_audit",
                "artifact_locator": "favorable-audit.json",
                "artifact_sha256": AUDIT_SHA256,
                "audited_subject_role": "candidate",
                "audited_subject_id": "fixture-candidate",
                "audited_subject_sha256": SUBJECT_SHA256,
                "verdict": "favorable",
                "scope": "Exact synthetic candidate artifact bytes for workflow-gate testing only.",
                "auditor_identity": "synthetic-test-auditor",
                "audited_at": "2026-09-12T12:00:00Z",
                "limitations": [
                    "Synthetic fixture; does not authenticate the auditor or establish scientific validity."
                ],
                "supporting_artifacts": [
                    {
                        "artifact_role": "source_pinned_review_finding",
                        "artifact_locator": "source-pinned-finding.json",
                        "artifact_sha256": SOURCE_FINDING_SHA256,
                    },
                    {
                        "artifact_role": "detailed_adversarial_audit_report",
                        "artifact_locator": "detailed-audit-report.md",
                        "artifact_sha256": AUDIT_REPORT_SHA256,
                    }
                ],
            }
        ],
        "evaluator_exposure_statement": "",
        "nonadvancing_information_statement": "",
        "limitations": ["Synthetic workflow fixture only."],
        "conclusion_ceiling": AUDIT_CEILING,
    }


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
                        "expected_discrimination": 0.0,
                        "uncertainty_reduction": 0.8,
                        "cost": 0.2,
                        "duration": 0.2,
                        "burden": 0.1,
                        "safety_risk": 0.0,
                        "ambiguity_risk": 0.1,
                        "prerequisite_evidence_refs": [
                            "design-review:machine-audit"
                        ],
                        "safety_review_refs": ["safety-review:machine-audit"],
                        "rationale": "Probe a machine invariant.",
                        "lane_id": "machine",
                        "audit_prerequisite_contract": nonadvancing_information_contract(),
                    },
                    {
                        "action_id": "science-falsifier",
                        "title": "Run falsifier",
                        "distinguishes_hypotheses": [],
                        "information_targets": ["science:first-failing-gate"],
                        "expected_discrimination": 0.0,
                        "uncertainty_reduction": 0.6,
                        "cost": 0.2,
                        "burden": 0.1,
                        "safety_risk": 0.0,
                        "ambiguity_risk": 0.1,
                        "prerequisite_evidence_refs": [
                            "design-review:science-falsifier"
                        ],
                        "safety_review_refs": ["safety-review:science-falsifier"],
                        "rationale": "Probe the cheapest scientific failure.",
                        "lane_id": "science",
                        "audit_prerequisite_contract": nonadvancing_information_contract(),
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
    assert len(recommendation["recommendation_payload_sha256"]) == 64
    assert recommendation["selected_action_ids_by_lane"] == {
        "machine": "machine-audit",
        "science": "science-falsifier",
    }
    machine_score = next(
        score for score in recommendation["ranked_scores"]
        if score["action_id"] == "machine-audit"
    )
    assert machine_score["weighted_components"]["expected_discrimination"] == 0.0
    assert machine_score["weighted_components"]["ambiguity_risk_penalty"] == -0.075


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


def test_json_cli_records_and_replays_verified_local_cross_lane_lesson(
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
                "local-custody",
                "--title",
                "Local custody",
                "--statement",
                "Can a locally verified failure safely inform later machine work?",
            ]
        )
        == 0
    )
    result_from(capsys)
    artifact_root = tmp_path / "artifacts"
    artifact = artifact_root / "results" / "failed-control.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b'{"status":"failed","control":"fixture"}\n')
    artifact_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    spec = tmp_path / "verified-local-lesson.json"
    spec.write_text(
        json.dumps(
            {
                "origin_lane_id": "science",
                "target_lane_ids": ["machine"],
                "origin_artifact_locator": "results/failed-control.json",
                "origin_artifact_sha256": artifact_sha256,
                "origin_integrity_status": "verified_local",
                "origin_artifact_root": str(artifact_root),
                "observation": "A local control omitted its evaluation time.",
                "failure_class": "interface_ambiguity",
                "strongest_alternative_explanation": (
                    "The implementation may be defective."
                ),
                "challenged_invariant": "Every target is reproducibly defined.",
                "first_permitted_future_versions": ["machine-v2"],
                "prohibited_retroactive_targets": ["machine-v1"],
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
    recorded = result_from(capsys)
    assert recorded["origin_artifact_root"] == str(artifact_root.resolve())
    assert recorded["origin_artifact_integrity"]["status"] == "passed"
    assert recorded["origin_artifact_integrity"]["all_artifacts_match"] is True
    assert len(recorded["lesson_payload_sha256"]) == 64

    assert main([*global_args, "cross-lane-lesson", "list"]) == 0
    replayed = result_from(capsys)[0]
    assert replayed["origin_artifact_integrity"] == recorded[
        "origin_artifact_integrity"
    ]
    assert replayed["lesson_payload_sha256"] == recorded["lesson_payload_sha256"]

    artifact.write_bytes(b'{"status":"passed","control":"fixture"}\n')
    assert main([*global_args, "cross-lane-lesson", "list"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "current origin artifact bytes" in error["error"]["message"]


def test_json_cli_rejects_verified_local_cross_lane_lesson_with_missing_root(
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
                "missing-root",
                "--title",
                "Missing root",
                "--statement",
                "Can unresolvable local custody be rejected?",
            ]
        )
        == 0
    )
    result_from(capsys)
    spec = tmp_path / "missing-root-lesson.json"
    spec.write_text(
        json.dumps(
            {
                "origin_lane_id": "science",
                "target_lane_ids": ["machine"],
                "origin_artifact_locator": "results/missing.json",
                "origin_artifact_sha256": "a" * 64,
                "origin_integrity_status": "verified_local",
                "origin_artifact_root": str(tmp_path / "missing-artifacts"),
                "observation": "A local control could not be resolved.",
                "failure_class": "infrastructure_failure",
                "strongest_alternative_explanation": (
                    "The artifact root may have been declared incorrectly."
                ),
                "challenged_invariant": "Every local origin remains available.",
                "first_permitted_future_versions": ["machine-v2"],
                "prohibited_retroactive_targets": ["machine-v1"],
                "proposed_repair": "Require a resolvable artifact root.",
                "repair_falsifier": "A missing artifact root is accepted.",
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
        == 2
    )
    error = json.loads(capsys.readouterr().err)
    assert "requires current origin artifact bytes to match" in error["error"]["message"]
    assert main([*global_args, "cross-lane-lesson", "list"]) == 0
    assert result_from(capsys) == []


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


def test_json_cli_can_defer_clarifying_question(tmp_path: Path, capsys) -> None:
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
                "defer-question",
                "--title",
                "Deferred question",
                "--statement",
                "Can the design distinguish alternatives?",
            ]
        )
        == 0
    )
    result_from(capsys)
    assert (
        main(
            [
                *global_args,
                "question",
                "add",
                "--text",
                "Could measurement drift explain the apparent effect?",
            ]
        )
        == 0
    )
    question = result_from(capsys)
    assert (
        main(
            [
                *global_args,
                "question",
                "defer",
                question["question_id"],
                "--rationale",
                "Handle this in the next protocol revision before freeze.",
            ]
        )
        == 0
    )
    deferred = result_from(capsys)

    assert deferred["status"] == "deferred"
    assert deferred["answer"] == "Handle this in the next protocol revision before freeze."
    assert main([*global_args, "workspace", "verify"]) == 0
    verification = result_from(capsys)
    assert verification["valid"] is True
    assert verification["events"] == 3


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
    assert template["record"]["metadata"]["result_exposure_disclosure"] == {
        "status": "no_relevant_output_seen",
        "exposures": [],
    }
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
                    },
                    "result_exposure_disclosure": {
                        "status": "no_relevant_output_seen",
                        "exposures": [],
                    },
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
                        "hypothesis_discrimination_targets": [
                            {
                                "hypothesis_id": hypothesis["hypothesis_id"],
                                "discriminating_observation": (
                                    "A separately implemented checker reaches the "
                                    "same registered result."
                                ),
                                "expected_if_hypothesis": (
                                    "The independent checker accepts the registered "
                                    "proof and rejects the invalid control."
                                ),
                                "expected_if_alternative": (
                                    "The independent checker disagrees with the "
                                    "original implementation-dependent result."
                                ),
                                "would_weaken_if": (
                                    "The independent checker fails the registered "
                                    "proof or accepts the invalid control."
                                ),
                                "competing_model_ref": "No valid bounded derivation exists.",
                            }
                        ],
                        "expected_discrimination": 0.9,
                        "uncertainty_reduction": 0.8,
                        "cost": 0.2,
                        "duration": 0.2,
                        "burden": 0.1,
                        "safety_risk": 0.0,
                        "ambiguity_risk": 0.1,
                        "prerequisite_evidence_refs": [
                            "design-review:independent-check"
                        ],
                        "safety_review_refs": ["safety-review:independent-check"],
                        "rationale": "A second checker probes implementation dependence.",
                        "audit_prerequisite_contract": candidate_advancement_contract(),
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
                "--audit-artifact-root",
                str(AUDIT_FIXTURE_ROOT),
            ]
        )
        == 0
    )
    recommendation = result_from(capsys)
    assert recommendation["selected_action_id"] == "independent-check"
    assert len(recommendation["recommendation_payload_sha256"]) == 64
    assert recommendation["ranked_scores"][0]["weighted_components"] == {
        "expected_discrimination": 0.9,
        "uncertainty_reduction": 0.4,
        "cost_penalty": -0.05,
        "duration_penalty": -0.05,
        "burden_penalty": -0.035,
        "safety_risk_penalty": -0.0,
        "ambiguity_risk_penalty": -0.075,
    }
