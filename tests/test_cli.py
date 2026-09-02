from __future__ import annotations

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
