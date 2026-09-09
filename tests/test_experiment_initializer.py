from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_machine.interfaces.cli import main
import pytest
from research_machine.application.service import ResearchService
from research_machine.adapters.filesystem import FileSystemRepository
from research_machine.domain.errors import ValidationError
from research_machine.design import initializer
from research_machine.design import scaffold as scaffold_module


def _basic_brief() -> dict[str, object]:
    return {
        "title": "Light trial",
        "question": "Does blue light alter height?",
        "decision": "Choose a light.",
        "outcome": "height",
        "unit_of_observation": "pot",
        "controls": [],
        "confounds": [],
        "primary_estimand": "Mean height difference, blue minus white.",
        "contrast_definition": "blue minus white",
        "contrast_groups": ["blue", "white"],
        "expected_effect_direction": "positive",
    }


def _canary_plan(**overrides: object) -> dict[str, object]:
    plan: dict[str, object] = {
        "plan_id": "masked-target-plan",
        "candidate_target_ids": ["actual-state", "replay-decoy"],
        "seed_commitment_sha256": "1" * 64,
        "assignment_artifact_sha256": "2" * 64,
        "masking_plan": "Keep the selected target hidden until the reviewed reveal point.",
        "ethical_disclosure": "Consent discloses masked target assignment without revealing the target.",
        "assessment_gate_id": "canary-target-assessed",
    }
    plan.update(overrides)
    return plan


def test_initializer_creates_isolated_workspace_with_unreviewed_hypothesis(
    tmp_path: Path, capsys
) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps(_basic_brief()), encoding="utf-8")
    destination = tmp_path / "light-trial"
    assert main(["--json", "design", "initialize", "--brief-file", str(brief), "--output", str(destination)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["hypothesis_state"] == "unreviewed"
    assert result["git_initialized"] is True
    assert (destination / ".git").is_dir()
    assert (destination / ".research" / "workspace.json").is_file()
    state = json.loads((destination / "experiment-machine.json").read_text())
    assert state["hypothesis_state"] == "unreviewed"
    assert state["scaffold_provenance"] == result["scaffold_provenance"]
    assert state["scaffold_provenance_artifact"] == "drafts/design-scaffold-provenance.json"
    assert state["review_artifacts"] == result["review_artifacts"]
    assert state["canary_target_plan_status"] == "absent"
    assert state["canary_target_plan_artifact"] == "drafts/canary-target-plan-draft.json"
    assert (destination / "drafts" / "protocol-draft.json").is_file()
    manifest = json.loads((destination / "drafts" / "design-scaffold-provenance.json").read_text())
    assert manifest["artifact_manifest_sha256"] == result["scaffold_provenance"]["artifact_manifest_sha256"]
    protocol = json.loads((destination / "drafts" / "protocol-draft.json").read_text())
    assert protocol["scaffold_provenance"]["brief_content_sha256"] == result["scaffold_provenance"]["brief_content_sha256"]
    manifest_entries = {
        entry["name"]: entry["content_sha256"]
        for entry in manifest["artifact_manifest"]
    }
    assert manifest_entries["protocol-draft.json"] == hashlib.sha256(
        (destination / "drafts" / "protocol-draft.json").read_bytes()
    ).hexdigest()
    service = ResearchService(FileSystemRepository(destination / ".research"), actor="test")
    hypothesis = service.get_hypothesis(result["hypothesis_id"])
    assert hypothesis.primary_estimand == "Mean height difference, blue minus white."
    assert hypothesis.contrast_definition == "blue minus white"
    assert hypothesis.contrast_groups == ["blue", "white"]
    assert hypothesis.expected_effect_direction == "positive"
    ledger = next((destination / ".research").rglob("ledger.jsonl"))
    before = ledger.read_bytes()
    with pytest.raises(ValidationError, match="unresolved scaffold placeholder"):
        service.activate_hypothesis(result["hypothesis_id"])
    with pytest.raises(ValidationError, match="unresolved scaffold placeholder"):
        service.stage_hypothesis(result["hypothesis_id"], "Fixture review", "high")
    assert ledger.read_bytes() == before
    assert service.verify_ledger()["valid"]


def test_initializer_replays_canary_target_review_artifact(tmp_path: Path, capsys) -> None:
    brief_payload = {
        **_basic_brief(),
        "canary_target_plan": _canary_plan(),
    }
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps(brief_payload), encoding="utf-8")
    destination = tmp_path / "light-trial"

    assert (
        main(
            [
                "--json",
                "design",
                "initialize",
                "--brief-file",
                str(brief),
                "--output",
                str(destination),
                "--no-git",
            ]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)["result"]
    assert result["canary_target_plan_status"] == "review_required"
    state = json.loads((destination / "experiment-machine.json").read_text())
    assert state["canary_target_plan_status"] == "review_required"
    assert state["git_initialized"] is False
    artifact_names = {entry["name"] for entry in state["review_artifacts"]}
    assert "canary-target-plan-draft.json" in artifact_names
    protocol = json.loads((destination / "drafts" / "protocol-draft.json").read_text())
    canary = json.loads((destination / "drafts" / "canary-target-plan-draft.json").read_text())
    assert protocol["canary_target_plan"] == brief_payload["canary_target_plan"]
    assert canary["canary_target_plan"] == brief_payload["canary_target_plan"]
    assert (
        canary["required_run_assessment"]["gate_id"]
        == brief_payload["canary_target_plan"]["assessment_gate_id"]
    )


def test_initializer_rejects_divergent_canary_draft_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    brief_payload = {
        **_basic_brief(),
        "canary_target_plan": _canary_plan(),
    }

    original_scaffold = initializer.scaffold_design

    def divergent_scaffold(brief: dict[str, object]) -> dict[str, object]:
        scaffold = original_scaffold(brief)
        canary_artifact = dict(scaffold["artifacts"]["canary-target-plan-draft.json"])
        canary_artifact["canary_target_plan"] = {
            **brief_payload["canary_target_plan"],
            "plan_id": "different-plan",
        }
        scaffold["artifacts"]["canary-target-plan-draft.json"] = canary_artifact
        manifest = dict(scaffold["artifacts"]["design-scaffold-provenance.json"])
        entries = [
            {
                "name": name,
                "media_type": "text/markdown" if isinstance(content, str) else "application/json",
                "content_sha256": scaffold_module._rendered_artifact_sha256(content),
            }
            for name, content in sorted(scaffold["artifacts"].items())
            if name != "design-scaffold-provenance.json"
        ]
        manifest["artifact_manifest"] = entries
        manifest["artifact_manifest_sha256"] = scaffold_module._content_sha256(entries)
        scaffold["artifacts"]["design-scaffold-provenance.json"] = manifest
        scaffold["provenance"] = {
            **scaffold["provenance"],
            "artifact_manifest_sha256": manifest["artifact_manifest_sha256"],
        }
        return scaffold

    monkeypatch.setattr(initializer, "scaffold_design", divergent_scaffold)

    with pytest.raises(ValidationError, match="canary target draft"):
        initializer.initialize_experiment_repository(
            brief_payload,
            tmp_path / "light-trial",
            actor="test",
            initialize_git=False,
        )
    assert not (tmp_path / "light-trial").exists()
