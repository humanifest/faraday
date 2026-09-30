"""Fixture-only contract checks for the proposed Metamaps boundary.

These assertions validate the local migration contract, not a Metamaps
installation, compiler, scientific conclusion, or authorization decision.
"""

import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "modularity" / "metamaps-projection-v0.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_projection_is_versioned_and_declares_non_integration() -> None:
    projection = _fixture()

    assert projection["projection_contract_version"] == "metamaps-projection/v0"
    assert projection["compiler"]["module_version"] == "0-fixture"
    assert projection["compiler"]["not_live_integration"] is True
    assert projection["projection_status"] == "valid"
    assert len(projection["inputs"]) == 2


def test_changed_input_revision_invalidates_dependent_projection() -> None:
    projection = _fixture()
    changed = dict(projection["inputs"][0])
    changed["revision"] = "rev-2"
    changed_inputs = [changed, projection["inputs"][1]]

    assert changed_inputs != projection["inputs"]
    assert projection["invalidation"]["status_when_input_changes"] == "invalidated"
    assert projection["invalidation"]["rebuild_required"] is True


def test_unchanged_input_revisions_can_retain_valid_fixture_status() -> None:
    projection = _fixture()
    current_revisions = [item["revision"] for item in projection["inputs"]]

    assert current_revisions == projection["invalidation"]["depends_on_input_revisions"]
    assert projection["projection_status"] == "valid"
