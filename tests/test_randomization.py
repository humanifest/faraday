"""Synthetic assignment fixtures, not evidence of randomized implementation."""
import hashlib
import json

import pytest

from research_machine.design.randomization import generate_blocked_assignment
from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main


def test_blocked_assignment_is_reproducible_balanced_and_hash_bound(tmp_path, capsys):
    spec = {"unit_ids": [f"unit-{i}" for i in range(8)], "groups": ["control", "treatment"],
            "block_size": 4, "seed": 731}
    assert generate_blocked_assignment(spec) == generate_blocked_assignment(spec)
    path = tmp_path / "assignment.json"
    raw = json.dumps(spec)
    path.write_text(raw)
    assert main(["--json", "design", "randomize", "--spec-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["balance"] == {"control": 4, "treatment": 4}
    assert all(sum(row["group"] == group for row in result["assignments"] if row["block"] == block) == 2
               for block in (1, 2) for group in spec["groups"])
    canonical = json.dumps(result["assignments"], sort_keys=True, separators=(",", ":")).encode()
    assert result["assignment_sha256"] == hashlib.sha256(canonical).hexdigest()
    allocation = sorted(
        ({"unit_id": row["unit_id"], "group": row["group"]} for row in result["assignments"]),
        key=lambda row: row["unit_id"],
    )
    expected_allocation = hashlib.sha256(json.dumps(
        allocation, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert result["allocation_sha256"] == expected_allocation
    assert result["provenance"]["specification_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert result["scientific_evidence_eligible"] is False
    assert any("concealment" in item for item in result["limitations"])


@pytest.mark.parametrize("change", [
    {"unit_ids": ["u1", "u1", "u2", "u3"]}, {"groups": ["a", "a"]},
    {"block_size": 3}, {"block_size": True}, {"seed": True},
    {"unit_ids": ["u1", "u2", "u3", "u4", "u5", "u6"]},
])
def test_randomization_rejects_ambiguous_or_incomplete_blocks(change):
    spec = {"unit_ids": ["u1", "u2", "u3", "u4"], "groups": ["a", "b"],
            "block_size": 4, "seed": 1, **change}
    with pytest.raises(ValidationError):
        generate_blocked_assignment(spec)


def test_stratified_blocks_balance_each_declared_stratum():
    units = [f"u{i}" for i in range(8)]
    spec = {"unit_ids": units, "groups": ["control", "treatment"], "block_size": 4,
            "seed": 9, "strata": {unit: "site-a" if i < 4 else "site-b" for i, unit in enumerate(units)}}
    result = generate_blocked_assignment(spec)
    assert result["method"] == "stratified_fixed_permuted_blocks"
    assert result["balance_by_stratum"] == {
        "site-a": {"control": 2, "treatment": 2},
        "site-b": {"control": 2, "treatment": 2},
    }
    assert {row["stratum"] for row in result["assignments"]} == {"site-a", "site-b"}
    assert {row["block_within_stratum"] for row in result["assignments"]} == {1}


@pytest.mark.parametrize(("change", "message"), [
    ({"unit_ids": [" u1 ", "u2", "u3", "u4"]}, "unit_ids must be canonical"),
    ({"groups": [" control ", "treatment"]}, "groups must be canonical"),
    ({"strata": {" u1 ": "site-a", "u2": "site-a", "u3": "site-a", "u4": "site-a"}}, "strata unit_id must be canonical"),
    ({"strata": {"u1": " site-a ", "u2": "site-a", "u3": "site-a", "u4": "site-a"}}, "strata stratum must be canonical"),
])
def test_randomization_requires_canonical_assignment_handles(change, message):
    spec = {"unit_ids": ["u1", "u2", "u3", "u4"], "groups": ["control", "treatment"],
            "block_size": 4, "seed": 9,
            "strata": {"u1": "site-a", "u2": "site-a", "u3": "site-a", "u4": "site-a"},
            **change}
    with pytest.raises(ValidationError, match=message):
        generate_blocked_assignment(spec)


@pytest.mark.parametrize("strata", [
    {"u1": "a", "u2": "a", "u3": "a"},
    {"u1": "a", "u2": "a", "u3": "a", "u4": ""},
    {"u1": "a", "u2": "a", "u3": "a", "u4": "b"},
    {"u1": "a", " u1 ": "a", "u2": "a", "u3": "a", "u4": "a"},
])
def test_stratification_requires_exact_coverage_and_full_blocks(strata):
    with pytest.raises(ValidationError):
        generate_blocked_assignment({"unit_ids": ["u1", "u2", "u3", "u4"],
            "groups": ["a", "b"], "block_size": 4, "seed": 1, "strata": strata})
