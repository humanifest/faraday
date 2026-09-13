"""Adverse and metamorphic checks for source-composability public development."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from research_machine.domain.errors import ValidationError
from research_machine.interfaces.cli import main
from research_machine.literature.composability import (
    create_source_composability_evaluation,
    validate_source_composability_boundary,
    verify_source_composability_evaluation,
)


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "source-composability.json"


def _spec() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _write_spec(tmp_path: Path, value: dict, name: str = "spec.json") -> tuple[Path, str]:
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = tmp_path / name
    path.write_bytes(encoded)
    return path, hashlib.sha256(encoded).hexdigest()


def _create(tmp_path: Path, value: dict | None = None, name: str = "evaluation") -> dict:
    path, digest = _write_spec(tmp_path, value or _spec(), f"{name}-spec.json")
    return create_source_composability_evaluation(path, digest, tmp_path / name)


def test_cli_evaluates_and_replays_without_authority(tmp_path, capsys):
    spec_path, spec_digest = _write_spec(tmp_path, _spec())
    output = tmp_path / "evaluation"
    assert main(
        [
            "--json",
            "literature",
            "evaluate-composability",
            "--spec-file",
            str(spec_path),
            "--expected-spec-sha256",
            spec_digest,
            "--output",
            str(output),
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["verdict"] == "unclosed_with_exact_local_support"
    assert result["first_unclosed_required_arrow_id"] == "local-to-assembled"
    assert result["locally_supported_node_ids"] == ["local-object"]
    assert result["locally_supported_nodes"][0]["statement"].startswith("The local object")
    assert result["generic_missing_formula_verdict_permitted"] is False
    for field in (
        "source_truth_established",
        "scientific_validity_established",
        "scientific_evidence_eligible",
        "replication_authority_established",
        "candidate_advancement_eligible",
        "runtime_promotion_authorized",
        "conclusion_authorized",
        "auditor_independence_established",
    ):
        assert result[field] is False

    evaluation_path = output / "source-composability-evaluation.json"
    assert main(
        [
            "--json",
            "literature",
            "verify-composability",
            "--spec-file",
            str(spec_path),
            "--expected-spec-sha256",
            spec_digest,
            "--evaluation-file",
            str(evaluation_path),
            "--expected-evaluation-sha256",
            result["evaluation_sha256"],
        ]
    ) == 0
    replay = json.loads(capsys.readouterr().out)["result"]
    assert replay["status"] == "source_composability_evaluation_replayed"
    assert replay["candidate_advancement_eligible"] is False

    with pytest.raises(ValidationError, match="already exists"):
        create_source_composability_evaluation(spec_path, spec_digest, output)


def test_object_reordering_normalizes_without_changing_first_unclosed_arrow(tmp_path):
    original = _spec()
    reordered = deepcopy(original)
    reordered["source_references"].reverse()
    reordered["nodes"].reverse()
    reordered["required_arrows"].reverse()
    first = _create(tmp_path, original, "first")
    second = _create(tmp_path, reordered, "second")
    assert second["contract_sha256"] == first["contract_sha256"]
    assert second["first_unclosed_required_arrow"] == first["first_unclosed_required_arrow"]


def test_relabeling_cannot_replace_declared_arrow_order_with_lexical_order(tmp_path):
    spec = _spec()
    spec["target_node_ids"] = ["node-a", "node-b", "node-c"]
    spec["nodes"] = [
        {
            **spec["nodes"][0],
            "node_id": "node-a",
        },
        {
            **spec["nodes"][0],
            "node_id": "node-b",
            "statement": "The middle exact object is declared.",
        },
        {
            **spec["nodes"][1],
            "node_id": "node-c",
        },
    ]
    first_arrow = {
        **spec["required_arrows"][0],
        "arrow_id": "z-first",
        "source_node_id": "node-a",
        "target_node_id": "node-b",
        "compatibility_requirement": "First semantic compatibility requirement.",
    }
    second_arrow = {
        **spec["required_arrows"][0],
        "arrow_id": "a-second",
        "source_node_id": "node-b",
        "target_node_id": "node-c",
        "compatibility_requirement": "Second semantic compatibility requirement.",
    }
    spec["required_arrow_ids"] = ["z-first", "a-second"]
    spec["required_arrows"] = [second_arrow, first_arrow]
    original = _create(tmp_path, spec, "original")
    assert original["first_unclosed_required_arrow_id"] == "z-first"

    relabeled = deepcopy(spec)
    relabeled["required_arrow_ids"] = ["a-relabeled-first", "z-relabeled-second"]
    for arrow in relabeled["required_arrows"]:
        if arrow["compatibility_requirement"].startswith("First"):
            arrow["arrow_id"] = "a-relabeled-first"
        else:
            arrow["arrow_id"] = "z-relabeled-second"
    relabeled["required_arrows"].reverse()
    changed = _create(tmp_path, relabeled, "relabeled")
    assert changed["first_unclosed_required_arrow_id"] == "a-relabeled-first"
    assert changed["first_unclosed_required_arrow"]["compatibility_requirement"] == (
        original["first_unclosed_required_arrow"]["compatibility_requirement"]
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["required_arrows"].clear(),
            "define every required_arrow_id exactly once",
        ),
        (
            lambda value: value["nodes"].pop(),
            "define every target_node_id exactly once",
        ),
        (
            lambda value: value["nodes"][0]["source_refs"].__setitem__(0, "missing-source"),
            "unknown source refs",
        ),
        (
            lambda value: value["nodes"][0]["scope"].pop("carrier"),
            "scope fields do not match",
        ),
        (
            lambda value: value["required_arrows"][0]["scope"].update({"domain": " "}),
            "canonical non-empty text",
        ),
        (
            lambda value: value["required_arrows"][0].update(
                {"status": "exact_support", "source_refs": ["primary-local"]}
            ),
            "endpoint is not exactly supported",
        ),
        (
            lambda value: value["required_arrows"][0].update(
                {"status": "not_found_in_bounded_search", "source_refs": ["primary-local"]}
            ),
            "must cite bounded_search_source_ref",
        ),
    ],
)
def test_missing_or_falsely_closed_contract_fails_before_publication(
    tmp_path, mutation, message
):
    spec = _spec()
    mutation(spec)
    spec_path, digest = _write_spec(tmp_path, spec)
    output = tmp_path / "evaluation"
    with pytest.raises(ValidationError, match=message):
        create_source_composability_evaluation(spec_path, digest, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(
            {
                "chain_closed_under_declared_exact_support": True,
                "verdict": "closed_under_declared_exact_support",
            }
        ),
        lambda value: value.update(
            {"locally_supported_node_ids": [], "locally_supported_nodes": []}
        ),
        lambda value: value.update({"generic_missing_formula_verdict_permitted": True}),
        lambda value: value.update({"scientific_evidence_eligible": True}),
    ],
)
def test_replay_rejects_false_closure_supported_node_erasure_and_authority(
    tmp_path, mutation
):
    result = _create(tmp_path)
    evaluation = {
        key: value
        for key, value in result.items()
        if key not in {"path", "evaluation_sha256"}
    }
    mutation(evaluation)
    with pytest.raises(ValidationError, match="does not replay"):
        validate_source_composability_boundary(evaluation)


def test_changed_spec_or_evaluation_bytes_fail_hash_bound_replay(tmp_path):
    spec_path, digest = _write_spec(tmp_path, _spec())
    result = create_source_composability_evaluation(spec_path, digest, tmp_path / "evaluation")
    evaluation_path = tmp_path / "evaluation" / "source-composability-evaluation.json"

    changed_spec = _spec()
    changed_spec["contract_id"] = "changed-contract"
    _write_spec(tmp_path, changed_spec)
    with pytest.raises(ValidationError, match="specification does not match"):
        verify_source_composability_evaluation(
            spec_path,
            digest,
            evaluation_path,
            result["evaluation_sha256"],
        )

    spec_path, digest = _write_spec(tmp_path, _spec())
    evaluation_path.write_bytes(evaluation_path.read_bytes() + b" ")
    with pytest.raises(ValidationError, match="evaluation does not match"):
        verify_source_composability_evaluation(
            spec_path,
            digest,
            evaluation_path,
            result["evaluation_sha256"],
        )


def test_direct_limitation_is_distinct_and_unclosed(tmp_path):
    spec = _spec()
    spec["required_arrows"][0].update(
        {
            "status": "direct_limitation",
            "source_refs": ["primary-assembled"],
            "assessment": "The cited source states a direct scope limitation for this arrow.",
        }
    )
    result = _create(tmp_path, spec)
    assert result["arrow_status_counts"]["direct_limitation"] == 1
    assert result["arrow_status_counts"]["not_found_in_bounded_search"] == 0
    assert result["chain_closed_under_declared_exact_support"] is False


def test_all_exact_chain_closes_only_under_declared_exact_support(tmp_path):
    spec = _spec()
    spec["nodes"][1].update(
        {
            "status": "exact_support",
            "assessment": "The cited primary fixture states the exact assembled target.",
        }
    )
    spec["required_arrows"][0].update(
        {
            "status": "exact_support",
            "source_refs": ["primary-local", "primary-assembled"],
            "assessment": "The cited primary fixtures state the exact directed compatibility.",
        }
    )
    result = _create(tmp_path, spec)
    assert result["chain_closed_under_declared_exact_support"] is True
    assert result["verdict"] == "closed_under_declared_exact_support"
    assert result["first_unclosed_required_arrow"] is None
    assert result["scientific_validity_established"] is False
