"""G08 unavailable integrations are typed and effect-free."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_machine.application.guide import (
    GUIDE_UNAVAILABLE_CAPABILITIES,
    guide_unavailable_capability,
)
from research_machine.interfaces.cli import main


TODO = Path(__file__).resolve().parents[1] / "docs" / "ai-science-guide" / "TODO.md"


@pytest.mark.parametrize("capability,status", sorted(GUIDE_UNAVAILABLE_CAPABILITIES.items()))
def test_unavailable_capabilities_have_no_effect_or_fallback(
    tmp_path: Path, capsys, capability: str, status: str
) -> None:
    workspace = tmp_path / "workspace"
    assert main([
        "--workspace", str(workspace), "--json", "guide", "capability",
        "--name", capability,
    ]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result == guide_unavailable_capability(capability)
    assert result["status"] == status
    assert result["fallback_used"] is False
    assert result["external_call_performed"] is False
    assert result["canonical_write_performed"] is False
    assert result["grants_authority"] is False
    assert result["todo"].startswith("docs/ai-science-guide/TODO.md#")
    assert not workspace.exists()
    assert f"## {capability.replace('_', '-')}" in TODO.read_text(encoding="utf-8")


def test_unknown_capability_fails_without_fallback() -> None:
    with pytest.raises(ValueError, match="unknown guide capability"):
        guide_unavailable_capability("remote_model_fallback")


def test_deferred_next_experiment_and_design_boundaries_are_typed() -> None:
    assert guide_unavailable_capability("model_specific_next_experiment")["status"] == "review_only"
    assert guide_unavailable_capability("paired_observational_packet")["status"] == "review_only"


def test_capability_goal_covers_the_deferred_register() -> None:
    plan = json.loads((TODO.parent / "capability-milestones.json").read_text(encoding="utf-8"))
    covered = {capability for job in plan["jobs"] for capability in job["capabilities"]}
    assert covered == {f"T{number:02d}" for number in range(1, 12)}
    assert plan["jobs"][0]["id"] == "C00"
    assert plan["jobs"][-1]["id"] == "C12"
